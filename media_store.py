"""
Kho media bền vững cho AI Studio + Đăng bài mạng xã hội (docs/AI_SUITE_SPEC.md §1).

Ảnh/video AI (Replicate), video quảng cáo render trên trình duyệt và file chủ tiệm tải lên đều nằm trong CÙNG GridFS
bucket 'media' của app.py (media_fs) — phân biệt bằng trường `kind`. Link Replicate trả về hết hạn sau ~1 giờ, nên mọi
kết quả phải chép về đây trước khi đưa vào thư viện/đăng bài.

Vì sao có route công khai /m/<token>.<ext>: Instagram/Google Business cần 1 URL HTTPS công khai để TỰ tải ảnh/video về
(không gửi cookie). Token = file_id + HMAC(FLASK_SECRET_KEY) nên không dò được từ ObjectId (ObjectId sinh theo thời gian,
dễ đoán). Chỉ các kind trong KINDS mới phát qua link này — ảnh chấm công, avatar… KHÔNG BAO GIỜ.

Vercel giới hạn body request/response 4,5 MB: video phát theo HTTP Range từng lát ≤ SLICE, file lớn tải lên theo từng
khúc (chunk) qua /api/media/upload/*.

Content-Type luôn lấy từ magic bytes (sniff) lúc lưu — không tin tên file hay Content-Type client khai (cùng lý do với
_safe_image_content_type() trong app.py: khai text/html cho 1 file là Stored XSS).
"""
import hashlib
import hmac
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urljoin

import requests
from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, Response, jsonify, request, session
from gridfs import GridFS
from gridfs.errors import NoFile
from pymongo import ReturnDocument

from mongo_client import db

MAX_IMAGE_BYTES = 8_000_000
MAX_VIDEO_BYTES = 30_000_000
# Vercel chặn body response > 4,5 MB và body nhị phân đi qua dạng base64 (to thêm 4/3): lát 3,5 MB thành ~4,67 MB -> lỗi.
# 2,5 MB -> ~3,33 MB; trọn file 3,2 MB -> ~4,27 MB + header, vẫn dưới trần.
SLICE = 2_500_000
# Không có header Range mà file ≤ ngưỡng này -> trả trọn file (200). Module khác import hằng này (social_publisher:
# Instagram image_url/video_url, Google sourceUrl tự tải 1 lần KHÔNG Range -> file lớn hơn sẽ nhận bản cụt).
FULL_MAX = 3_200_000
# Ảnh tải lên để đăng bài bị nền tảng/thẻ <img> tải 1 lần không Range -> phải vừa 1 response
MAX_SHARE_IMAGE_BYTES = FULL_MAX
# Khúc tải lên: client mới dùng chunk_size = SLICE do /upload/init trả về; vẫn nhận tới 3,5 MB cho trang đang mở bản cũ
CHUNK_MAX = 3_500_000
MIN_CHUNK = 256 * 1024     # chặn số khúc tối đa / phiên (khúc nhỏ quá = hàng nghìn document rác)
# Link /m/ không thu hồi được -> cache CDN/trình duyệt tối đa 1 ngày: xoá file thì sau ≤ 1 ngày link thôi phát
PUBLIC_CACHE = 'public, max-age=86400'
KINDS = {'ai_image', 'ai_video', 'promo_video', 'social_upload'}   # đều "chia sẻ công khai bằng link ký"
UPLOAD_KINDS = ('promo_video', 'social_upload')
IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/webp')
VIDEO_TYPES = ('video/mp4', 'video/webm')
EXT = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'video/mp4': 'mp4', 'video/webm': 'webm'}
UPLOAD_TTL = timedelta(hours=2)
# Trần dung lượng media mỗi tiệm (Atlas tính tiền theo dung lượng) — đổi bằng env khi cần
SHOP_CAP_BYTES = int(os.environ.get('MEDIA_SHOP_CAP_BYTES') or 2_000_000_000)
TEST_ENV_KEYS = ('REPLICATE_API_BASE', 'SOCIAL_META_API_BASE', 'SOCIAL_GOOGLE_API_BASE', 'SOCIAL_GOOGLE_OAUTH_BASE',
                 'SOCIAL_TIKTOK_API_BASE', 'SOCIAL_GBP_API_BASE')
LOCAL_HOSTS = ('127.0.0.1', 'localhost')


class MediaError(Exception):
    """Lỗi nói thẳng được với chủ tiệm — `code` để giao diện dịch VI/EN, câu tiếng Anh là bản gốc (giống
    inbox_channels.ChannelError). ai_media dùng lại đúng class này."""

    def __init__(self, code, message=None, detail=None, status=400):
        super().__init__(message or code)
        self.code, self.message, self.detail, self.status = code, (message or code), detail, status

    def as_dict(self):
        return {'success': False, 'code': self.code, 'message': str(self.message)[:300],
                'detail': self.detail if isinstance(self.detail, (dict, list)) else (str(self.detail)[:300] if self.detail else None)}


def test_mode():
    """§0: đang trỏ API ngoài về máy giả (chạy thử local) -> không được đụng dữ liệu/tiệm thật."""
    return any((os.environ.get(k) or '').strip() for k in TEST_ENV_KEYS)


def test_business_ids():
    return {x.strip() for x in (os.environ.get('SOCIAL_TEST_BUSINESS_IDS') or '').split(',') if x.strip()}


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    # MongoClient không bật tz_aware -> đọc ra datetime "naive" (vốn là UTC); so với now() có tz sẽ TypeError
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt):
    dt = _aware(dt)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if isinstance(dt, datetime) else dt


# ---------------------------------------------------------------- nhận diện loại file
_MP4_BRANDS = {'isom', 'iso2', 'iso3', 'iso4', 'iso5', 'iso6', 'iso8', 'iso9', 'mp41', 'mp42', 'mp71', 'avc1', 'dash',
               'm4v ', 'm4vh', 'm4vp', 'msnv', '3gp4', '3gp5', '3gp6', 'f4v ', 'mmp4', 'ndas'}
# HEIC/AVIF và M4A cũng là hộp 'ftyp' nhưng KHÔNG phải video mp4
_NOT_VIDEO_BRANDS = {'heic', 'heix', 'heim', 'heis', 'hevc', 'hevx', 'mif1', 'msf1', 'avif', 'avis', 'm4a ', 'm4b ', 'm4p '}


def sniff(data):
    """Loại file theo magic bytes — chỉ 5 loại được phép, còn lại None."""
    if not data or len(data) < 12:
        return None
    head = bytes(data[:64])
    if head[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head[4:8] == b'ftyp':
        box = int.from_bytes(head[:4], 'big')
        major = head[8:12].decode('latin-1').lower()
        if major in _NOT_VIDEO_BRANDS:
            return None
        if major in _MP4_BRANDS:
            return 'video/mp4'
        compat = bytes(data[16:min(max(box, 16), 64)])
        brands = {compat[i:i + 4].decode('latin-1').lower() for i in range(0, len(compat) - 3, 4)}
        return 'video/mp4' if brands & _MP4_BRANDS and not brands & _NOT_VIDEO_BRANDS else None
    if head[:4] == b'\x1a\x45\xdf\xa3':
        # EBML: Matroska chung không phát được trên mọi trình duyệt — chỉ nhận DocType 'webm'
        return 'video/webm' if b'webm' in head else None
    return None


def ext_for(content_type):
    return EXT.get(content_type or '', 'bin')


def _cap_for(content_type, kind=None):
    if (content_type or '').startswith('video/'):
        return MAX_VIDEO_BYTES
    # Ảnh chủ tiệm tải lên để đăng: Instagram/Google tải bằng 1 GET không Range -> > FULL_MAX sẽ nhận bản cụt (206).
    # Ảnh AI (Replicate) giữ trần 8 MB: đã trả tiền rồi, không vứt kết quả vì cỡ file.
    return MAX_SHARE_IMAGE_BYTES if kind in UPLOAD_KINDS else MAX_IMAGE_BYTES


def _mb(n):
    return f'{n / 1_000_000:g} MB'


def file_links(file_id, content_type):
    """Các link của 1 file media. play_url/download_url = link /m/ có Range (phát được trên iOS, tải từng lát ≤ SLICE
    khi file > 4,5 MB). 'url' giữ cho giao diện cũ: video trỏ luôn về /m/ vì /api/storage/file trả trọn file, không
    Range (vỡ trên Vercel và Safari); ảnh vẫn là /api/storage/file như trước."""
    fid = str(file_id)
    pub = public_url(fid, ext_for(content_type))
    is_video = (content_type or '').startswith('video/')
    return {'url': pub if is_video else f'/api/storage/file/{fid}', 'public_url': pub, 'play_url': pub, 'download_url': pub}


def public_limits():
    """Ngưỡng cho giao diện (cắt khúc tải lên, ảnh phải nhỏ hơn bao nhiêu để đăng được bằng link)."""
    return {'slice_bytes': SLICE, 'chunk_bytes': SLICE, 'full_max_bytes': FULL_MAX,
            'max_upload_image_bytes': MAX_SHARE_IMAGE_BYTES, 'max_image_bytes': MAX_IMAGE_BYTES,
            'max_video_bytes': MAX_VIDEO_BYTES}


# ---------------------------------------------------------------- GridFS
_FS = None


def _fs():
    global _FS
    if _FS is None:
        if db is None:
            raise MediaError('storage_unavailable', 'Media storage is not configured (MongoDB unavailable).', status=503)
        _FS = GridFS(db, collection='media')   # cùng bucket với media_fs của app.py
    return _FS


def _files():
    return db['media.files']


def _oid(file_id):
    try:
        return ObjectId(str(file_id))
    except (InvalidId, TypeError):
        return None


def save_bytes(business_id, data, kind, filename=None, meta=None):
    if not business_id:
        raise MediaError('auth_required', 'Missing business.', status=401)
    if kind not in KINDS:
        raise MediaError('bad_kind', f'Unsupported media kind: {kind}')
    data = bytes(data or b'')
    if not data:
        raise MediaError('empty_file', 'The file is empty.')
    ctype = sniff(data)
    if not ctype:
        raise MediaError('unsupported_type', 'Only JPEG, PNG, WebP images and MP4/WebM videos are supported.')
    cap = _cap_for(ctype, kind)
    if len(data) > cap:
        raise MediaError('too_large', f'File is larger than {_mb(cap)}.', detail={'max_bytes': cap})
    meta = dict(meta or {})
    now = _now()
    ext = ext_for(ctype)
    base = re.sub(r'[^A-Za-z0-9_.-]+', '_', (filename or '').rsplit('.', 1)[0])[:60] or f"{kind}_{now.strftime('%Y%m%d%H%M%S')}"
    fields = {
        'business_id': business_id, 'kind': kind, 'size': len(data),
        'source': meta.pop('source', None) or 'upload', 'job_id': meta.pop('job_id', None), 'created_at': now,
    }
    if test_mode():
        fields['qa_test'] = True   # dọn được dữ liệu thử nghiệm (local và production chung 1 DB)
    for k, v in meta.items():
        if k not in fields and k not in ('_id', 'length', 'chunkSize', 'uploadDate', 'filename', 'contentType', 'md5'):
            fields[k] = v
    # content_type -> pymongo lưu thành 'contentType' (GridOut.content_type đọc lại), như app.py api_storage_upload
    file_id = str(_fs().put(data, filename=f'{base}.{ext}', content_type=ctype, **fields))
    return {'file_id': file_id, 'content_type': ctype, 'size': len(data), **file_links(file_id, ctype)}


def _host_allowed(host, allowed_hosts):
    host = (host or '').lower().rstrip('.')
    for h in allowed_hosts or ():
        h = (h or '').lower().strip('.')
        if not h:
            continue
        if h in LOCAL_HOSTS:
            if host == h:
                return True
        elif host == h or host.endswith('.' + h):   # có dấu chấm: 'evilreplicate.delivery' không lọt
            return True
    return False


def _check_url(url, allowed_hosts):
    parts = urlsplit(url or '')
    host = (parts.hostname or '').lower()
    if parts.username or parts.password:
        raise MediaError('bad_url', 'Credentials in media URLs are not allowed.')
    if parts.scheme == 'https':
        pass
    elif parts.scheme == 'http' and host in LOCAL_HOSTS and test_mode():
        pass   # máy giả local khi chạy thử
    else:
        raise MediaError('bad_url', 'Media URL must be HTTPS.')
    if not _host_allowed(host, allowed_hosts):
        raise MediaError('bad_host', f'Media host not allowed: {host}')
    return url


def fetch_to_store(business_id, url, kind, allowed_hosts, max_bytes, meta=None):
    """Tải file từ nhà cung cấp (Replicate…) về GridFS. Chặn SSRF: chỉ host trong allowlist, tự đi theo redirect
    (tối đa 3) và kiểm tra lại host ở MỖI bước — requests tự theo redirect thì 1 URL hợp lệ có thể nhảy vào mạng nội bộ."""
    cap = int(max_bytes or MAX_VIDEO_BYTES)
    current = _check_url(url, allowed_hosts)
    resp = None
    try:
        for _ in range(4):
            resp = requests.get(current, stream=True, timeout=(10, 60), allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get('Location'):
                nxt = urljoin(current, resp.headers['Location'])
                resp.close()
                current = _check_url(nxt, allowed_hosts)
                continue
            break
        else:
            raise MediaError('fetch_failed', 'Too many redirects while downloading media.', status=502)
        if resp.status_code != 200:
            raise MediaError('fetch_failed', f'Download failed (HTTP {resp.status_code}).', status=502)
        try:
            declared = int(resp.headers.get('Content-Length') or 0)
        except ValueError:
            declared = 0
        if declared > cap:
            raise MediaError('too_large', 'Remote file is too large.', detail={'max_bytes': cap})
        buf = bytearray()
        for chunk in resp.iter_content(65536):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > cap:   # Content-Length có thể nói dối -> đếm thật khi đọc
                raise MediaError('too_large', 'Remote file is too large.', detail={'max_bytes': cap})
    except requests.exceptions.RequestException as e:
        raise MediaError('fetch_failed', f'Download failed: {e.__class__.__name__}', status=502) from e
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
    name = os.path.basename(urlsplit(current).path) or None
    return save_bytes(business_id, bytes(buf), kind, filename=name, meta=meta)


def get(file_id, business_id=None):
    oid = _oid(file_id)
    if oid is None:
        return None
    try:
        grid = _fs().get(oid)
    except NoFile:
        return None
    if business_id is not None and getattr(grid, 'business_id', None) != business_id:
        return None
    return grid


def delete(file_id, business_id):
    grid = get(file_id, business_id)
    if grid is None:
        return False
    _fs().delete(grid._id)
    return True


def usage_bytes(business_id):
    rows = list(_files().aggregate([
        {'$match': {'business_id': business_id, 'kind': {'$in': sorted(KINDS)}}},
        {'$group': {'_id': None, 'n': {'$sum': '$length'}}},
    ]))
    return int(rows[0]['n']) if rows else 0


def pending_upload_bytes(business_id, now=None):
    """Byte đã giữ chỗ bởi phiên tải lên CHƯA xong (open/finishing, chưa hết hạn) — khúc của chúng nằm trong
    media_upload_chunks, chưa vào GridFS nên usage_bytes() không thấy. Không tính thì mở N phiên trước khi finish
    phiên nào là vượt trần dung lượng tiệm."""
    now = now or _now()
    return sum(int(s.get('size') or 0) for s in db.media_upload_chunks.find(
        {'type': 'session', 'business_id': business_id, 'status': {'$in': ['open', 'finishing']}, 'expires_at': {'$gte': now}},
        {'_id': 0, 'size': 1}))


def list_files(business_id, kinds=UPLOAD_KINDS, limit=40):
    """File media (không phải job AI) của tiệm — cho thư viện AI Studio / bộ chọn media của trang Đăng bài."""
    cur = _files().find({'business_id': business_id, 'kind': {'$in': list(kinds)}},
                        {'_id': 1, 'kind': 1, 'contentType': 1, 'length': 1, 'source': 1, 'created_at': 1, 'uploadDate': 1}
                        ).sort('uploadDate', -1).limit(max(1, min(int(limit or 40), 200)))
    out = []
    for f in cur:
        fid = str(f['_id'])
        ctype = f.get('contentType')
        out.append({'file_id': fid, 'kind': f.get('kind'), 'content_type': ctype, 'size': f.get('length'),
                    'source': f.get('source') or 'upload', 'created_at': iso(f.get('created_at') or f.get('uploadDate')),
                    **file_links(fid, ctype)})
    return out


# ---------------------------------------------------------------- link công khai có chữ ký
def _secret():
    key = os.environ.get('FLASK_SECRET_KEY')
    if not key:
        try:
            from flask import current_app
            key = current_app.secret_key
        except Exception:
            key = None
    if not key:
        raise MediaError('not_configured', 'FLASK_SECRET_KEY is not set.', status=503)
    return key.encode() if isinstance(key, str) else key


def public_token(file_id):
    file_id = str(file_id)
    sig = hmac.new(_secret(), f'media|{file_id}'.encode(), hashlib.sha256).hexdigest()[:24]
    return f'{file_id}.{sig}'


def verify_token(token):
    """file_id nếu chữ ký đúng, ngược lại None (so sánh hằng thời gian)."""
    if not isinstance(token, str) or token.count('.') != 1:
        return None
    file_id, sig = token.split('.')
    if not re.fullmatch(r'[0-9a-f]{24}', file_id) or not re.fullmatch(r'[0-9a-f]{24}', sig):
        return None
    good = public_token(file_id).split('.')[1]
    return file_id if hmac.compare_digest(sig, good) else None


def public_url(file_id, ext):
    return f'/m/{public_token(file_id)}.{(ext or "bin").lstrip(".")}'


def absolute_public_url(file_id, ext, base):
    return (base or '').rstrip('/') + public_url(file_id, ext)


_RANGE_RE = re.compile(r'(\d*)\s*-\s*(\d*)')
_RANGE_DIGITS = 15   # 15 chữ số ≈ 1 PB, thừa cho mọi file; số dài hơn = rác (5000 chữ số làm int() ném ValueError -> 500)


def plan_range(range_header, size):
    """(status, start, end) cho 1 response ≤ SLICE byte.
    Không có Range (hoặc đơn vị lạ, vd 'items=' — RFC 9110 §14.2 bắt phải bỏ qua): file ≤ FULL_MAX -> 200 trọn file;
    file lớn hơn -> 206 lát đầu. Trả 206 cho request không xin Range là lệch chuẩn HTTP, nhưng trả trọn file > 4,5 MB thì
    Vercel cắt hẳn response (lỗi) — 206 + Content-Range ít ra để trình tải hiểu là còn phần sau. Trình phát <video> luôn
    gửi 'Range: bytes=0-' nên không vướng; ảnh tải lên bị chặn ≤ FULL_MAX nên luôn trọn file.
    'bytes=' sai cú pháp / số quá dài / cuối < đầu / ngoài file -> 416 (RFC cho phép từ chối), không bao giờ 500."""
    if size <= 0:
        return 416, None, None
    spec = (range_header or '').strip()
    unit, eq, ranges = spec.partition('=')
    if not eq or unit.strip().lower() != 'bytes':
        if size <= FULL_MAX:
            return 200, 0, size - 1
        return 206, 0, min(size, SLICE) - 1
    first = ranges.split(',')[0].strip()   # nhiều khoảng -> chỉ phục vụ khoảng đầu (single-part)
    m = _RANGE_RE.fullmatch(first)
    if not m or (m.group(1) == '' and m.group(2) == ''):
        return 416, None, None
    a, b = m.group(1), m.group(2)
    if len(a) > _RANGE_DIGITS or len(b) > _RANGE_DIGITS:
        return 416, None, None
    try:
        if a == '':
            n = int(b)
            if n <= 0:
                return 416, None, None
            start, end = max(0, size - n), size - 1
        else:
            start = int(a)
            end = int(b) if b != '' else size - 1
            if end < start or start >= size:
                return 416, None, None
            end = min(end, size - 1)
    except ValueError:
        return 416, None, None
    end = min(end, start + SLICE - 1)
    return 206, start, end


# ---------------------------------------------------------------- blueprint
media_bp = Blueprint('media_store', __name__)


def _err(code, message, status=400, detail=None):
    return jsonify(MediaError(code, message, detail).as_dict()), status


def _bid():
    if 'user_id' not in session:
        return None
    return session.get('business_id') or session.get('user_id')


@media_bp.route('/m/<name>', methods=['GET'])
def public_media(name):
    """Link công khai (không cần đăng nhập) — Instagram/Google tự tải; 404 chung cho mọi lỗi để không lộ gì."""
    token, _, ext = (name or '').rpartition('.')
    file_id = verify_token(token) if token else None
    if not file_id:
        return _err('not_found', 'Not found.', 404)
    grid = get(file_id)
    if grid is None or getattr(grid, 'kind', None) not in KINDS:
        return _err('not_found', 'Not found.', 404)
    ctype = grid.content_type
    if ctype not in EXT:
        return _err('not_found', 'Not found.', 404)
    exts = {ext_for(ctype)} | ({'jpeg'} if ctype == 'image/jpeg' else set())
    if ext.lower() not in exts:
        return _err('not_found', 'Not found.', 404)
    size = int(grid.length or 0)
    etag = f'"{file_id}"'
    headers = {
        'Accept-Ranges': 'bytes',
        # Nội dung theo file_id không đổi nhưng chủ tiệm XOÁ được -> chỉ cache 1 ngày (không 'immutable', không 1 năm),
        # để CDN/trình duyệt thôi phát file đã xoá trong ≤ 1 ngày. X-Media-Cache: after_request của app.py không ghi đè no-store
        'Cache-Control': PUBLIC_CACHE,
        'X-Media-Cache': '1',
        'ETag': etag,
        'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'inline; filename="bitpaw-{file_id}.{ext_for(ctype)}"',
    }
    if etag in (request.headers.get('If-None-Match') or ''):
        return Response(status=304, headers=headers)
    status, start, end = plan_range(request.headers.get('Range'), size)
    if status == 416:
        headers['Content-Range'] = f'bytes */{size}'
        return Response(status=416, headers=headers)
    grid.seek(start)
    body = grid.read(end - start + 1)
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return Response(body, status=status, mimetype=ctype, headers=headers)


@media_bp.route('/api/media/upload/init', methods=['POST'])
def upload_init():
    bid = _bid()
    if not bid:
        return _err('auth_required', 'Please sign in to continue.', 401)
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    ctype = (data.get('content_type') or '').split(';')[0].strip().lower()
    if kind not in UPLOAD_KINDS:
        return _err('bad_kind', 'kind must be promo_video or social_upload.')
    allowed = VIDEO_TYPES if kind == 'promo_video' else IMAGE_TYPES + VIDEO_TYPES
    if ctype not in allowed:
        return _err('unsupported_type', 'Only JPEG, PNG, WebP images and MP4/WebM videos are supported.')
    try:
        size = int(data.get('size'))
    except (TypeError, ValueError):
        return _err('bad_size', 'size must be a number of bytes.')
    cap = _cap_for(ctype, kind)
    if size <= 0:
        return _err('empty_file', 'The file is empty.')
    if size > cap:
        if ctype.startswith('image/') and size <= MAX_IMAGE_BYTES:
            # Ảnh 3,2–8 MB: Instagram/Google tải link 1 lần không Range -> nhận ảnh cụt. Trang tự thu nhỏ trước khi tải lên.
            return _err('too_large', f'Photos must be {_mb(cap)} or smaller so Instagram and Google can fetch them — '
                                     'shrink the photo and try again.', detail={'max_bytes': cap, 'reason': 'share_by_link'})
        return _err('too_large', f'File is larger than {_mb(cap)}.', detail={'max_bytes': cap})
    now = _now()
    try:
        _ensure_upload_indexes()
        # Dọn phiên tải dở đã hết hạn (TTL index ở trên cũng tự xoá, lệnh này cho chắc khi index chưa kịp chạy)
        db.media_upload_chunks.delete_many({'expires_at': {'$lt': now}})
        # Trần dung lượng tính cả phiên tải CHƯA xong (khúc đang nằm trong media_upload_chunks)
        used = usage_bytes(bid) + pending_upload_bytes(bid, now)
        if used + size > SHOP_CAP_BYTES:
            return _err('storage_full', 'Media storage for this shop is full — delete old videos first.',
                        detail={'cap_bytes': SHOP_CAP_BYTES, 'used_bytes': used})
        upload_id = secrets.token_urlsafe(18)
        chunks = math.ceil(size / SLICE)
        db.media_upload_chunks.insert_one({
            'type': 'session', 'upload_id': upload_id, 'business_id': bid, 'user_id': session.get('user_id'),
            'kind': kind, 'content_type': ctype, 'size': size, 'chunks': chunks, 'status': 'open',
            'created_at': now, 'expires_at': now + UPLOAD_TTL,
        })
    except MediaError as e:
        return jsonify(e.as_dict()), e.status
    return jsonify({'success': True, 'upload_id': upload_id, 'chunk_size': SLICE, 'chunks': chunks,
                    'max_chunk_bytes': CHUNK_MAX})


_INDEXES = {'done': False}


def _ensure_upload_indexes():
    """TTL index trên expires_at: khúc của phiên bỏ dở tự biến mất (trước đây chỉ dọn khi có lần init sau). 1 lần/tiến trình."""
    if _INDEXES['done']:
        return
    _INDEXES['done'] = True
    try:
        db.media_upload_chunks.create_index('expires_at', expireAfterSeconds=0, name='ttl_expires_at')
    except Exception as e:   # index đã có với tuỳ chọn khác… -> không chặn việc tải lên
        print(f'[media_store] TTL index: {e}')


def _max_chunks(sess):
    # Không ép đúng 1 cỡ khúc: trang cũ cắt 3,0/3,4 MB, trang mới cắt theo chunk_size — miễn đủ byte và liền mạch
    return max(int(sess.get('chunks') or 1), math.ceil(int(sess.get('size') or 0) / MIN_CHUNK))


def _session_doc(upload_id, bid):
    if not isinstance(upload_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', upload_id):
        return None
    return db.media_upload_chunks.find_one({'type': 'session', 'upload_id': upload_id, 'business_id': bid}, {'_id': 0})


@media_bp.route('/api/media/upload/<upload_id>/chunk', methods=['POST'])
def upload_chunk(upload_id):
    bid = _bid()
    if not bid:
        return _err('auth_required', 'Please sign in to continue.', 401)
    sess = _session_doc(upload_id, bid)
    if not sess or _aware(sess.get('expires_at')) < _now():
        return _err('upload_not_found', 'Upload not found or expired — start again.', 404)
    if sess.get('status') != 'open':
        return _err('upload_closed', 'This upload is already finished.', 409)
    try:
        index = int(request.args.get('index', ''))
    except ValueError:
        return _err('bad_index', 'index must be a number.')
    if not 0 <= index < _max_chunks(sess):
        return _err('bad_index', 'Chunk index out of range.')
    if (request.content_length or 0) > CHUNK_MAX:
        return _err('chunk_too_large', f'Each chunk must be at most {CHUNK_MAX} bytes.', 413)
    body = request.get_data(cache=False)
    if not body:
        return _err('empty_chunk', 'Empty chunk.')
    if len(body) > CHUNK_MAX:
        return _err('chunk_too_large', f'Each chunk must be at most {CHUNK_MAX} bytes.', 413)
    others = sum(c.get('size', 0) for c in db.media_upload_chunks.find(
        {'type': 'chunk', 'upload_id': upload_id, 'index': {'$ne': index}}, {'_id': 0, 'size': 1}))
    if others + len(body) > int(sess['size']):
        return _err('too_large', 'More data than the declared size.')
    # Gửi lại cùng index (mạng chập chờn) -> ghi đè, không nhân đôi
    db.media_upload_chunks.update_one(
        {'type': 'chunk', 'upload_id': upload_id, 'index': index},
        {'$set': {'business_id': bid, 'data': body, 'size': len(body), 'expires_at': sess['expires_at'],
                  'created_at': _now()}},
        upsert=True)
    return jsonify({'success': True, 'index': index, 'received': others + len(body), 'size': int(sess['size'])})


@media_bp.route('/api/media/upload/<upload_id>/finish', methods=['POST'])
def upload_finish(upload_id):
    bid = _bid()
    if not bid:
        return _err('auth_required', 'Please sign in to continue.', 401)
    sess = _session_doc(upload_id, bid)
    if not sess:
        return _err('upload_not_found', 'Upload not found or expired — start again.', 404)
    if sess.get('status') == 'finished' and sess.get('result'):
        return jsonify({'success': True, **sess['result']})   # gọi lại finish sau lỗi mạng -> cùng kết quả
    # Giành quyền ghép file (2 lần finish song song không lưu 2 bản)
    claimed = db.media_upload_chunks.find_one_and_update(
        {'type': 'session', 'upload_id': upload_id, 'business_id': bid, 'status': 'open'},
        {'$set': {'status': 'finishing'}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        return _err('upload_busy', 'This upload is being finished — try again in a moment.', 409)
    try:
        parts = sorted(db.media_upload_chunks.find({'type': 'chunk', 'upload_id': upload_id}, {'_id': 0, 'index': 1, 'data': 1}),
                       key=lambda c: c['index'])
        have = [c['index'] for c in parts]
        # Khúc phải liền mạch từ 0 và đủ đúng số byte đã khai (số khúc tuỳ cỡ khúc client dùng)
        if not parts or have != list(range(len(parts))):
            raise MediaError('missing_chunks', 'Some chunks are missing — upload them again.',
                             detail={'have': have, 'chunks': sess['chunks']})
        data = b''.join(bytes(c['data']) for c in parts)
        if len(data) < int(sess['size']):
            raise MediaError('missing_chunks', 'Some chunks are missing — upload them again.',
                             detail={'have': have, 'chunks': sess['chunks']})
        if len(data) != int(sess['size']):
            raise MediaError('size_mismatch', 'Uploaded size does not match the declared size.')
        # Kiểm lại trần lúc lưu thật (phiên mở song song lúc init có thể cùng lọt)
        if usage_bytes(bid) + len(data) > SHOP_CAP_BYTES:
            raise MediaError('storage_full', 'Media storage for this shop is full — delete old videos first.',
                             detail={'cap_bytes': SHOP_CAP_BYTES})
        ctype = sniff(data)
        declared = sess.get('content_type') or ''
        if not ctype or ctype.split('/')[0] != declared.split('/')[0]:
            raise MediaError('unsupported_type', 'The file content is not a supported image/video.')
        if sess['kind'] == 'promo_video' and not ctype.startswith('video/'):
            raise MediaError('unsupported_type', 'Promo videos must be MP4 or WebM.')
        saved = save_bytes(bid, data, sess['kind'],
                           meta={'source': 'browser' if sess['kind'] == 'promo_video' else 'upload',
                                 'uploaded_by': sess.get('user_id')})
    except MediaError as e:
        db.media_upload_chunks.update_one({'type': 'session', 'upload_id': upload_id}, {'$set': {'status': 'open'}})
        return jsonify(e.as_dict()), e.status
    except Exception:
        db.media_upload_chunks.update_one({'type': 'session', 'upload_id': upload_id}, {'$set': {'status': 'open'}})
        raise
    db.media_upload_chunks.update_one({'type': 'session', 'upload_id': upload_id},
                                      {'$set': {'status': 'finished', 'result': saved}})
    db.media_upload_chunks.delete_many({'type': 'chunk', 'upload_id': upload_id})
    return jsonify({'success': True, **saved})
