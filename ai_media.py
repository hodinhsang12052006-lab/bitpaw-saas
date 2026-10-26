"""
AI Studio — sinh ảnh/video THẬT qua Replicate dưới dạng job bất đồng bộ + hạn mức theo gói + sổ chi phí
(docs/AI_SUITE_SPEC.md §2).

Vì sao là job: video mất 30 giây – vài phút, quá giới hạn thời gian 1 request trên Vercel. Ảnh thường xong trong lúc tạo
(header `Prefer: wait=5`), video thì giao diện hỏi lại /api/ai_studio/media/jobs/<id> hoặc Replicate gọi webhook.
Kết quả luôn được chép về GridFS (media_store) vì link replicate.delivery hết hạn sau ~1 giờ.

Dùng "official models" (POST /v1/models/{owner}/{name}/predictions, KHÔNG cần version hash) — bản cũ ai_image_gen.py
ghim 1 version hash SDXL bị cụt 1 ký tự nên luôn lỗi 422. Muốn đổi model/giá: chỉ sửa bảng MODELS bên dưới.

Chạy thử local: REPLICATE_API_BASE trỏ về máy giả (không tốn tiền); khi đó test_mode() bật -> chỉ tiệm trong
SOCIAL_TEST_BUSINESS_IDS được tạo job, job/file gắn qa_test.
"""
import base64
import hashlib
import hmac
import os
import re
import time
from datetime import timedelta

import requests
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from mongo_client import db, next_mongo_id
import media_store
from media_store import MediaError, test_mode, _now, _aware, iso   # noqa: F401  (MediaError dùng chung)

REPLICATE_API = os.environ.get('REPLICATE_API_BASE', 'https://api.replicate.com').rstrip('/')
OUTPUT_HOSTS = ('replicate.delivery', 'replicate.com')
ACTIVE = ('queued', 'running')
TERMINAL = ('succeeded', 'failed', 'canceled')
# Ảnh nguồn ≤ 1 MB gửi thẳng data: URI; lớn hơn tải byte lên Replicate Files API rồi đưa link của Replicate.
# KHÔNG đưa link /m/ của mình: Replicate tải 1 lần không Range, ảnh > FULL_MAX sẽ nhận bản cụt (206).
DATA_URI_MAX = 1_000_000
STALE_AFTER = timedelta(minutes=30)
CREATE_LOST_AFTER = timedelta(minutes=10)   # polling: chưa có prediction_id sau 10 phút = lệnh tạo đã chết
ORPHAN_AFTER = timedelta(minutes=20)        # quét nền: job đứng yên quá 20 phút (không ai hỏi lại) -> xử lý
SWEEP_EVERY = timedelta(minutes=2)          # 1 job chỉ bị quét (hỏi Replicate) tối đa 2 phút/lần
MAX_STORE_ATTEMPTS = 3
_PID_RE = re.compile(r'[A-Za-z0-9_-]{4,64}')
# Hạn mức tháng: kind job -> tên ô trong quota_status và trong document giữ chỗ db.ai_media_quota
QUOTA_FIELDS = {'image': 'images', 'video': 'video_seconds'}
_INTERNAL = ('_id', 'storing_until', 'store_attempts', 'public_base', 'quota_key', 'source_file', 'swept_at')

IMAGE_ASPECTS = ('1:1', '4:5', '9:16', '16:9', '3:4', '4:3', '2:3', '3:2')   # có ở cả 3 model ảnh

# Bảng model DUY NHẤT — chỉ gửi đúng tên input có trong tài liệu từng model (replicate.com/<model>/api).
# input(prompt, aspect, duration, image) -> dict
MODELS = {
    'image': {
        'draft': {'model': 'black-forest-labs/flux-schnell', 'price': 0.003, 'aspects': IMAGE_ASPECTS,
                  'input': lambda p, a, d, img: {'prompt': p, 'aspect_ratio': a, 'output_format': 'jpg', 'num_outputs': 1}},
        'hd': {'model': 'black-forest-labs/flux-1.1-pro', 'price': 0.04, 'aspects': IMAGE_ASPECTS,
               'input': lambda p, a, d, img: {'prompt': p, 'aspect_ratio': a, 'output_format': 'jpg', 'safety_tolerance': 2}},
        # Ideogram vẽ được CHỮ trong ảnh (poster) — model không có output_format nên ra PNG (Instagram cần JPEG)
        'poster': {'model': 'ideogram-ai/ideogram-v3-turbo', 'price': 0.03, 'aspects': IMAGE_ASPECTS,
                   'input': lambda p, a, d, img: {'prompt': p, 'aspect_ratio': a}},
    },
    'video': {
        # Giá Replicate ở 480p: t2v $0.05/video (không có biến thể interpolate); i2v $0.065/video khi bật interpolate_output
        'draft': {'model': 'wan-video/wan-2.2-t2v-fast', 'model_i2v': 'wan-video/wan-2.2-i2v-fast',
                  'price_per_video': {'wan-video/wan-2.2-t2v-fast': 0.05, 'wan-video/wan-2.2-i2v-fast': 0.065},
                  'durations': (5,), 'aspects': ('9:16', '16:9'),
                  # i2v lấy khung hình theo ảnh gốc -> không gửi aspect_ratio
                  'input': lambda p, a, d, img: ({'prompt': p, 'image': img, 'resolution': '480p', 'interpolate_output': True}
                                                 if img else
                                                 {'prompt': p, 'aspect_ratio': a, 'resolution': '480p', 'interpolate_output': True})},
        'standard': {'model': 'bytedance/seedance-1-pro-fast', 'price_per_second': 0.025, 'durations': (5, 8),
                     'aspects': ('9:16', '16:9', '1:1'),
                     'input': lambda p, a, d, img: dict({'prompt': p, 'duration': d, 'resolution': '720p', 'aspect_ratio': a},
                                                        **({'image': img} if img else {}))},
        # Veo mặc định 1080p (file ~gấp đôi, cùng giá) -> ép 720p cho vừa giới hạn phát/đăng
        'premium': {'model': 'google/veo-3.1-fast', 'price_per_second': 0.15, 'durations': (4, 8), 'aspects': ('9:16', '16:9'),
                    'input': lambda p, a, d, img: dict({'prompt': p, 'duration': d, 'aspect_ratio': a, 'resolution': '720p',
                                                        'generate_audio': True},
                                                       **({'image': img} if img else {}))},
    },
}
# Ảnh nguồn để "làm ảnh động": ngoài media AI/upload, cho phép ảnh tiệm đã công khai (app.py _PUBLIC_MEDIA_KINDS)
_SOURCE_IMAGE_KINDS = media_store.KINDS | {'product_image', 'brand_logo', 'brand_cover'}

_WEBHOOK_SECRET = {'value': None}


def output_hosts():
    return OUTPUT_HOSTS + (media_store.LOCAL_HOSTS if test_mode() else ())


def _token():
    tok = (os.environ.get('REPLICATE_API_TOKEN') or '').strip()
    if not tok:
        raise MediaError('not_configured', 'AI image/video generation is not set up on this server (REPLICATE_API_TOKEN).',
                         status=503)
    return tok


def _headers(extra=None):
    h = {'Authorization': f'Bearer {_token()}', 'Content-Type': 'application/json'}
    h.update(extra or {})
    return h


# ---------------------------------------------------------------- giá + hạn mức
def estimate(kind, preset, duration=None, model=None):
    """Chi phí Replicate ước tính (USD). model: model thật sẽ chạy (vd i2v khi làm ảnh động) — giá có thể khác."""
    cfg = (MODELS.get(kind) or {}).get(preset)
    if not cfg:
        raise MediaError('bad_preset', f'Unknown preset: {kind}/{preset}')
    if kind == 'image':
        return round(cfg['price'], 4)
    if 'price_per_video' in cfg:
        ppv = cfg['price_per_video']
        if isinstance(ppv, dict):
            ppv = ppv.get(model or cfg['model'], ppv[cfg['model']])
        return round(ppv, 4)
    return round(cfg['price_per_second'] * int(duration or cfg['durations'][0]), 4)


def presets_public():
    """Bảng preset cho giao diện (giá USD là chi phí ước tính phía Replicate, không phải giá bán)."""
    out = {}
    for kind, presets in MODELS.items():
        out[kind] = []
        for name, cfg in presets.items():
            row = {'preset': name, 'model': cfg['model'], 'aspects': list(cfg['aspects'])}
            if kind == 'video':
                row['durations'] = list(cfg['durations'])
                row['estimates_usd'] = {str(d): estimate(kind, name, d) for d in cfg['durations']}
                # "Làm ảnh động" (có ảnh nguồn) có thể chạy model khác giá (draft: wan i2v)
                i2v = cfg.get('model_i2v') or cfg['model']
                row['estimates_animate_usd'] = {str(d): estimate(kind, name, d, model=i2v) for d in cfg['durations']}
            else:
                row['estimate_usd'] = estimate(kind, name)
            out[kind].append(row)
    return out


def aspect_from_size(size):
    """'1024x1792' (kiểu tham số cũ) -> tỉ lệ khung gần nhất mà các model ảnh nhận."""
    try:
        w, h = (int(x) for x in str(size).lower().split('x')[:2])
        ratio = w / h
    except (TypeError, ValueError, ZeroDivisionError):
        return '1:1'

    def _r(a):
        x, y = a.split(':')
        return int(x) / int(y)
    return min(IMAGE_ASPECTS, key=lambda a: abs(_r(a) - ratio))


def _month_start(now=None):
    now = now or _now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _units(job):
    return 1 if job.get('kind') == 'image' else int(job.get('duration') or 0)


def _quota_key(business_id, month):
    # _id cố định theo (tiệm, tháng): upsert song song không thể sinh 2 document (index _id luôn unique)
    return f'{business_id}|{month}'


def quota_status(business_id):
    """used = sổ ai_usage tháng này; pending = job đang chạy; reserved = ô giữ chỗ nguyên tử (db.ai_media_quota) mà
    create_job tăng/giảm — bình thường reserved == used + pending."""
    import plans
    plan = plans.business_plan(db, business_id)
    limits = (getattr(plans, 'AI_MEDIA_QUOTA', {}) or {}).get(plan) or {'images': 0, 'video_seconds': 0}
    start = _month_start()
    month = start.strftime('%Y-%m')
    used = {'image': 0, 'video': 0}
    for row in db.ai_usage.aggregate([
        {'$match': {'business_id': business_id, 'kind': {'$in': ['image', 'video']}, 'created_at': {'$gte': start}}},
        {'$group': {'_id': '$kind', 'n': {'$sum': '$units'}}},
    ]):
        used[row['_id']] = int(row['n'] or 0)
    # Job đang chạy chưa vào sổ nhưng sắp tốn tiền -> giữ chỗ, để bấm liên tục không vượt hạn mức
    pending = {'image': 0, 'video': 0}
    for j in db.ai_media_jobs.find({'business_id': business_id, 'status': {'$in': list(ACTIVE)}, 'created_at': {'$gte': start}},
                                   {'_id': 0, 'kind': 1, 'duration': 1}):
        if j.get('kind') in pending:
            pending[j['kind']] += _units(j)
    try:
        held = db.ai_media_quota.find_one({'_id': _quota_key(business_id, month)}) or {}
    except Exception as e:
        print(f'[ai_media] quota doc: {e}')
        held = {}
    out = {'plan': plan, 'month': month}
    for kind, field in QUOTA_FIELDS.items():
        out[field] = {'used': used[kind], 'pending': pending[kind], 'limit': int(limits.get(field) or 0),
                      'reserved': int(held[field]) if field in held else used[kind] + pending[kind]}
    return out


def _taken(bucket):
    return max(bucket['used'] + bucket['pending'], int(bucket.get('reserved') or 0))


def _check_quota(business_id, kind, units):
    """Kiểm tra RẺ, không nguyên tử (chặn sớm trước khi tốn DeepSeek). Chốt thật là _reserve() trong create_job."""
    q = quota_status(business_id)
    bucket = q[QUOTA_FIELDS[kind]]
    if _taken(bucket) + units > bucket['limit']:
        raise MediaError('quota_exceeded', 'Monthly AI media quota reached for your plan.', detail=q, status=402)
    return q


def _reserve(business_id, kind, units):
    """Giữ chỗ hạn mức NGUYÊN TỬ trước khi gọi Replicate: 1 document/tiệm/tháng, $inc có điều kiện "còn đủ chỗ".
    Trước đây đọc used+pending rồi mới insert job -> 20 request song song cùng đọc 1 con số, cùng lọt, cùng tốn tiền.
    Trả _id của ô giữ chỗ (lưu vào job để trả lại đúng tháng khi job lỗi)."""
    field = QUOTA_FIELDS[kind]
    q = quota_status(business_id)
    limit = q[field]['limit']
    key = _quota_key(business_id, q['month'])
    now = _now()
    if units > limit:
        raise MediaError('quota_exceeded', 'Monthly AI media quota reached for your plan.', detail=q, status=402)
    try:
        # Lần đầu trong tháng: khởi tạo bằng số thật (đã dùng + đang chạy) — job từ trước bản vá cũng được tính
        db.ai_media_quota.update_one({'_id': key}, {'$setOnInsert': {
            'business_id': business_id, 'month': q['month'], 'created_at': now,
            **{f: q[f]['used'] + q[f]['pending'] for f in QUOTA_FIELDS.values()}}}, upsert=True)
    except DuplicateKeyError:
        pass   # request song song vừa tạo trước -> dùng document đó
    held = db.ai_media_quota.find_one_and_update(
        {'_id': key, field: {'$lte': limit - units}},
        {'$inc': {field: units}, '$set': {'updated_at': now}}, return_document=ReturnDocument.AFTER)
    if not held:
        raise MediaError('quota_exceeded', 'Monthly AI media quota reached for your plan.',
                         detail=quota_status(business_id), status=402)
    return key


def _job_quota_key(job):
    if job.get('quota_key'):
        return job['quota_key']
    # Job tạo trước bản vá: đã được tính vào ô giữ chỗ lúc khởi tạo (nếu còn đang chạy) -> trả về tháng tạo job
    created = _aware(job.get('created_at'))
    if not created or not job.get('business_id'):
        return None
    return _quota_key(job['business_id'], created.strftime('%Y-%m'))


def _quota_adjust(key, kind, delta):
    """Trả lại (delta < 0, không bao giờ xuống âm) hoặc tính thêm (delta > 0) vào ô giữ chỗ — không tạo ô mới."""
    field = QUOTA_FIELDS.get(kind)
    if not key or not field or not delta:
        return
    flt = {'_id': key}
    if delta < 0:
        flt[field] = {'$gte': -delta}
    try:
        db.ai_media_quota.update_one(flt, {'$inc': {field: delta}, '$set': {'updated_at': _now()}})
    except Exception as e:
        print(f'[ai_media] quota adjust {key}: {e}')


# ---------------------------------------------------------------- tạo job
def _public_job(job):
    if not job:
        return None
    out = {k: v for k, v in job.items() if k not in _INTERNAL}
    for k in ('created_at', 'updated_at', 'completed_at'):
        if k in out:
            out[k] = iso(out[k])
    if out.get('file_id'):
        # play_url/download_url = link /m/ có Range; 'url' giữ cho giao diện cũ (video cũng trỏ về /m/)
        out.update(media_store.file_links(out['file_id'], out.get('content_type')))
    return out


def public_job(job):
    return _public_job(job)


def _load_source_image(business_id, image_file_id):
    """Ảnh nguồn "làm ảnh động": phải của đúng tiệm, kind công khai được, đúng ảnh JPEG/PNG/WebP thật."""
    grid = media_store.get(image_file_id, business_id)
    if grid is None:
        raise MediaError('image_not_found', 'Photo not found in your shop.', status=404)
    if getattr(grid, 'kind', None) not in _SOURCE_IMAGE_KINDS:
        raise MediaError('image_not_allowed', 'This photo cannot be used for AI video.')
    size = int(grid.length or 0)
    if size > media_store.MAX_IMAGE_BYTES:
        raise MediaError('image_too_large', 'Photo is too large (max 8 MB).')
    data = grid.read()
    ctype = media_store.sniff(data)   # đọc lại byte thật, không tin contentType đã lưu (ảnh cũ lưu theo đuôi file)
    if ctype not in media_store.IMAGE_TYPES:
        raise MediaError('unsupported_type', 'Only JPEG, PNG or WebP photos can be animated.')
    return {'file_id': str(grid._id), 'data': data, 'content_type': ctype}


def _upload_source(src):
    """Ảnh > 1 MB -> POST {REPLICATE_API}/v1/files (multipart 'content'), dùng urls.get làm input. Replicate tự đọc
    file của chính nó — không phụ thuộc link /m/ (bị cắt lát ở Vercel) hay site HTTPS (chạy được cả local)."""
    name = f"bitpaw-{src['file_id']}.{media_store.ext_for(src['content_type'])}"
    try:
        resp = requests.post(f'{REPLICATE_API}/v1/files', headers={'Authorization': f'Bearer {_token()}'},
                             files={'content': (name, src['data'], src['content_type'])}, timeout=(10, 60))
    except requests.exceptions.RequestException as e:
        raise MediaError('provider_unreachable', 'Could not send the photo to the AI provider — try again.', status=502) from e
    if not 200 <= resp.status_code < 300:
        raise _provider_error(resp)
    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    urls = body.get('urls') if isinstance(body.get('urls'), dict) else {}
    url = urls.get('get')
    try:
        if not isinstance(url, str) or not url:
            raise MediaError('bad_url', 'missing urls.get')
        media_store._check_url(url, output_hosts())   # chỉ nhận link về chính Replicate (https)
    except MediaError as e:
        raise MediaError('provider_error', 'The AI provider did not accept the photo — try again.', detail=e.code,
                         status=502) from e
    fid = body.get('id')
    return url, {'id': fid if isinstance(fid, str) and _PID_RE.fullmatch(fid) else None}


def _source_input(src):
    """(input cho model, thông tin file trên Replicate hoặc None)."""
    if len(src['data']) <= DATA_URI_MAX:
        return f"data:{src['content_type']};base64,{base64.b64encode(src['data']).decode()}", None
    return _upload_source(src)


def _drop_source_file(job):
    """Xoá ảnh nguồn đã gửi lên Replicate Files khi job xong/lỗi (ảnh của tiệm không nằm lại bên thứ 3). Best-effort."""
    fid = ((job or {}).get('source_file') or {}).get('id')
    if not isinstance(fid, str) or not _PID_RE.fullmatch(fid):
        return
    try:
        requests.delete(f'{REPLICATE_API}/v1/files/{fid}', headers=_headers(), timeout=(5, 10))
    except Exception as e:
        print(f'[ai_media] drop source file: {e.__class__.__name__}')


def _cancel_remote(pid):
    """Job bị coi là quá hạn -> huỷ luôn bên Replicate để không bị tính tiền cho kết quả sẽ bỏ đi. Best-effort."""
    if not isinstance(pid, str) or not _PID_RE.fullmatch(pid):
        return
    try:
        requests.post(f'{REPLICATE_API}/v1/predictions/{pid}/cancel', headers=_headers(), timeout=(5, 10))
    except Exception as e:
        print(f'[ai_media] cancel: {e.__class__.__name__}')


def _provider_error(resp):
    try:
        body = resp.json()
        detail = body.get('detail') or body.get('title') or body.get('error') or ''
    except ValueError:
        detail = (resp.text or '')[:200]
    code = {401: 'provider_auth', 402: 'provider_billing', 403: 'provider_auth', 404: 'provider_model_missing',
            422: 'provider_rejected', 429: 'provider_busy'}.get(resp.status_code, 'provider_error')
    return MediaError(code, f'Replicate error {resp.status_code}: {str(detail)[:200]}', detail=str(detail)[:300], status=502)


def precheck(business_id, kind, units=1):
    """Kiểm tra rẻ TRƯỚC khi tốn 1 lượt DeepSeek viết prompt: đã cấu hình, đúng tiệm thử nghiệm (test mode), còn hạn mức."""
    _token()
    if test_mode() and business_id not in media_store.test_business_ids():
        raise MediaError('test_mode_business', 'Test mode: this shop is not in SOCIAL_TEST_BUSINESS_IDS.', status=403)
    sweep_stale(business_id, limit=1)   # job mồ côi thôi giữ chỗ trước khi tính hạn mức (≤ 1 lần hỏi Replicate)
    return _check_quota(business_id, kind, units)


def create_job(business_id, user_id, kind, preset, prompt, aspect='9:16', duration=5, image_file_id=None,
               base_url=None, source_text=None):
    if not business_id:
        raise MediaError('auth_required', 'Please sign in to continue.', status=401)
    cfg = (MODELS.get(kind) or {}).get(preset)
    if not cfg:
        raise MediaError('bad_preset', f'Unknown preset: {kind}/{preset}')
    aspect = aspect or ('9:16' if kind == 'video' else '1:1')
    if aspect not in cfg['aspects']:
        raise MediaError('bad_aspect', f"Aspect must be one of {', '.join(cfg['aspects'])}.")
    if kind == 'video':
        try:
            duration = int(duration if duration is not None else cfg['durations'][0])
        except (TypeError, ValueError):
            raise MediaError('bad_duration', 'Duration must be a number of seconds.')
        if duration not in cfg['durations']:
            raise MediaError('bad_duration', f"Duration must be one of {cfg['durations']} seconds.")
    else:
        duration = None
        if image_file_id:
            raise MediaError('image_not_supported', 'Image presets do not take a source photo.')
    prompt = re.sub(r'\s+', ' ', (prompt or '')).strip()
    if not prompt:
        raise MediaError('prompt_required', 'Describe what to generate.')
    if len(prompt) > 2000:
        raise MediaError('prompt_too_long', 'Prompt is too long (max 2000 characters).')
    units = _units({'kind': kind, 'duration': duration})
    # Local + production chung 1 DB: chạy thử với Replicate giả không được ghi job/file vào tiệm thật (precheck)
    precheck(business_id, kind, units)
    src = _load_source_image(business_id, image_file_id) if image_file_id else None
    model = cfg.get('model_i2v') if (src and cfg.get('model_i2v')) else cfg['model']
    job_id = next_mongo_id('ai_media_jobs')
    quota_key = _reserve(business_id, kind, units)   # nguyên tử; hết chỗ -> quota_exceeded, chưa tốn gì
    now = _now()
    job = {
        'id': job_id, 'business_id': business_id, 'kind': kind, 'preset': preset, 'model': model,
        'prompt': prompt, 'source_text': (source_text or None) and str(source_text)[:3000], 'aspect': aspect,
        'duration': duration, 'image_file_id': str(image_file_id) if image_file_id else None, 'status': 'queued',
        'prediction_id': None, 'cost_estimate_usd': estimate(kind, preset, duration, model=model), 'file_id': None,
        'content_type': None, 'public_url': None, 'error': None, 'is_ai_generated': True, 'created_by': user_id,
        'created_at': now, 'updated_at': now, 'completed_at': None, 'qa_test': bool(test_mode()),
        'public_base': (base_url or '').rstrip('/') or None, 'quota_key': quota_key,
    }
    try:
        db.ai_media_jobs.insert_one(dict(job))
    except Exception:
        _quota_adjust(quota_key, kind, -units)
        raise

    image_input = None
    if src:
        try:
            image_input, source_file = _source_input(src)
        except MediaError as e:
            _fail(job_id, e.code, e.message)   # trả lại chỗ hạn mức
            raise
        if source_file:
            job['source_file'] = source_file
            db.ai_media_jobs.update_one({'id': job_id}, {'$set': {'source_file': source_file}})

    body = {'input': cfg['input'](prompt, aspect, duration, image_input)}
    base = (base_url or '').rstrip('/')
    if base.startswith('https://') and not test_mode():
        # Webhook chỉ khi có domain HTTPS thật (máy local Replicate không gọi tới được)
        body['webhook'] = f"{base}/api/ai_studio/replicate_webhook?job={job['id']}"
        body['webhook_events_filter'] = ['completed']
    extra = {'Prefer': 'wait=5'} if kind == 'image' else {'Cancel-After': '15m'}
    try:
        resp = requests.post(f'{REPLICATE_API}/v1/models/{model}/predictions', headers=_headers(extra), json=body,
                             timeout=(10, 30))
    except requests.exceptions.RequestException as e:
        _fail(job['id'], 'provider_unreachable', f'Could not reach Replicate: {e.__class__.__name__}')
        raise MediaError('provider_unreachable', 'Could not reach the AI provider — try again.', status=502) from e
    # Mọi 2xx là đã tạo: 201, hoặc 202 "đã tạo nhưng chưa có output" (Prefer: wait=5 hết 5 giây — hay gặp với hd/poster).
    # Trước đây 202 bị coi là lỗi -> job failed, prediction vẫn chạy và tính tiền, webhook bị bỏ qua, kết quả mất.
    if not 200 <= resp.status_code < 300:
        err = _provider_error(resp)
        _fail(job['id'], err.code, err.message)
        raise err
    try:
        pred = resp.json() if resp.content else {}
    except ValueError:
        pred = {}
    pid = pred.get('id') if isinstance(pred, dict) else None
    if not isinstance(pid, str) or not _PID_RE.fullmatch(pid):
        _fail(job['id'], 'provider_error', 'Replicate returned no prediction id.')
        raise MediaError('provider_error', 'The AI provider returned an unexpected answer.', status=502)
    db.ai_media_jobs.update_one({'id': job['id'], 'status': {'$in': list(ACTIVE)}},
                                {'$set': {'prediction_id': pid, 'updated_at': _now()}})
    job['prediction_id'] = pid
    return _apply_prediction(job, pred)


def _fail(job_id, code, message, status='failed'):
    """Đưa job đang chạy sang failed/canceled ĐÚNG 1 LẦN (lọc theo status) và chỉ lần đó trả lại chỗ hạn mức."""
    now = _now()
    before = db.ai_media_jobs.find_one_and_update(
        {'id': job_id, 'status': {'$in': list(ACTIVE)}},
        {'$set': {'status': status, 'error': {'code': code, 'message': str(message)[:300]},
                  'updated_at': now, 'completed_at': now},
         '$unset': {'storing_until': ''}},
        projection={'_id': 0, 'id': 1, 'business_id': 1, 'kind': 1, 'duration': 1, 'created_at': 1, 'quota_key': 1,
                    'source_file': 1},
        return_document=ReturnDocument.BEFORE)
    if before:
        _quota_adjust(_job_quota_key(before), before.get('kind'), -_units(before))
        _drop_source_file(before)
    return bool(before)


def _get_job(job_id):
    return db.ai_media_jobs.find_one({'id': job_id}, {'_id': 0})


def _apply_prediction(job, pred):
    """Đồng bộ trạng thái job theo prediction của Replicate (dùng chung cho create/refresh)."""
    status = (pred or {}).get('status')
    now = _now()
    if status == 'succeeded':
        return _store_output(job, pred)
    if status in ('failed', 'canceled', 'aborted'):
        err = str(pred.get('error') or ('Canceled' if status != 'failed' else 'Generation failed'))
        # Cancel-After 15m hết hạn -> Replicate báo canceled
        code = 'generation_failed' if status == 'failed' else 'canceled'
        _fail(job['id'], code, err, status='failed' if status == 'failed' else 'canceled')
        return _get_job(job['id'])
    new = 'running' if status == 'processing' else 'queued'
    if _aware(job.get('created_at')) and _now() - _aware(job['created_at']) > STALE_AFTER:
        _cancel_remote(job.get('prediction_id'))   # bỏ kết quả thì đừng để Replicate chạy tiếp và tính tiền
        _fail(job['id'], 'timeout', 'Generation took too long.')
        return _get_job(job['id'])
    db.ai_media_jobs.update_one({'id': job['id'], 'status': {'$in': list(ACTIVE)}},
                                {'$set': {'status': new, 'updated_at': now}})
    return _get_job(job['id'])


def _first_output(output):
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        for o in output:
            if isinstance(o, str):
                return o
    if isinstance(output, dict):
        for k in ('video', 'image', 'url', 'output'):
            if isinstance(output.get(k), str):
                return output[k]
    return None


def _store_output(job, pred):
    """Chép kết quả về GridFS ĐÚNG 1 LẦN: giành 'storing_until' bằng find_one_and_update có điều kiện — webhook và
    giao diện hỏi lại cùng lúc thì chỉ 1 bên tải + lưu, bên kia thấy job đang lưu/đã xong."""
    now = _now()
    claimed = db.ai_media_jobs.find_one_and_update(
        {'id': job['id'], 'status': {'$in': list(ACTIVE)},
         '$or': [{'storing_until': None}, {'storing_until': {'$lt': now}}]},
        {'$set': {'storing_until': now + timedelta(seconds=120), 'updated_at': now}, '$inc': {'store_attempts': 1}},
        return_document=ReturnDocument.AFTER, projection={'_id': 0})
    if not claimed:
        return _get_job(job['id'])
    bid = claimed['business_id']
    kind_store = 'ai_image' if claimed['kind'] == 'image' else 'ai_video'
    try:
        # Lần trước đã lưu file nhưng chết trước khi cập nhật job -> dùng lại file đó, không lưu bản thứ 2
        prev = db['media.files'].find_one({'job_id': claimed['id'], 'business_id': bid, 'kind': kind_store},
                                          {'_id': 1, 'contentType': 1, 'length': 1})
        if prev:
            fid = str(prev['_id'])
            ctype = prev.get('contentType')
            saved = {'file_id': fid, 'content_type': ctype, 'size': prev.get('length'), **media_store.file_links(fid, ctype)}
        else:
            url = _first_output(pred.get('output'))
            if not url:
                _fail(claimed['id'], 'no_output', 'The AI provider returned no file.')
                return _get_job(claimed['id'])
            cap = media_store.MAX_IMAGE_BYTES if kind_store == 'ai_image' else media_store.MAX_VIDEO_BYTES
            saved = media_store.fetch_to_store(bid, url, kind_store, output_hosts(), cap,
                                               meta={'source': 'replicate', 'job_id': claimed['id']})
    except MediaError as e:
        if int(claimed.get('store_attempts') or 0) >= MAX_STORE_ATTEMPTS or e.code in ('bad_host', 'bad_url', 'unsupported_type', 'too_large'):
            _fail(claimed['id'], 'store_failed', f'{e.code}: {e.message}')
        else:
            db.ai_media_jobs.update_one({'id': claimed['id'], 'status': {'$in': list(ACTIVE)}},
                                        {'$set': {'status': 'running', 'updated_at': _now(),
                                                  'error': {'code': e.code, 'message': str(e.message)[:300]}},
                                         '$unset': {'storing_until': ''}})
        return _get_job(claimed['id'])
    done = _now()
    before = db.ai_media_jobs.find_one_and_update(
        {'id': claimed['id']},
        {'$set': {'status': 'succeeded', 'file_id': saved['file_id'], 'content_type': saved['content_type'],
                  'public_url': saved['public_url'], 'size': saved.get('size'), 'error': None, 'updated_at': done,
                  'completed_at': done},
         '$unset': {'storing_until': ''}},
        projection={'_id': 0, 'status': 1}, return_document=ReturnDocument.BEFORE)
    final = _get_job(claimed['id'])
    if before and before.get('status') not in ACTIVE:
        # Bên khác vừa đánh lỗi job (và trả chỗ hạn mức) trong lúc mình đang lưu — Replicate đã tính tiền -> tính lại
        _quota_adjust(_job_quota_key(final), final.get('kind'), _units(final))
    _record_usage(final)
    _legacy_row(final)
    _drop_source_file(final)
    return final


def _record_usage(job):
    # Sổ chi phí: đúng 1 dòng / job thành công (kiểm tra trước khi ghi — refresh trùng không ghi 2 lần).
    # created_at = lúc TẠO job: hạn mức giữ chỗ theo tháng tạo job, job tạo 31/10 xong 1/11 vẫn tính vào tháng 10
    # (khớp ô giữ chỗ db.ai_media_quota); recorded_at = lúc ghi sổ thật.
    if db.ai_usage.find_one({'job_id': job['id']}, {'_id': 1}):
        return
    now = _now()
    db.ai_usage.insert_one({'business_id': job['business_id'], 'kind': job['kind'], 'units': _units(job),
                            'cost_usd': float(job.get('cost_estimate_usd') or 0), 'model': job.get('model'),
                            'job_id': job['id'], 'created_at': _aware(job.get('created_at')) or now, 'recorded_at': now,
                            'qa_test': bool(job.get('qa_test'))})


def _legacy_row(job):
    """ad_assistant.create_campaign chỉ nhận image_url có trong db.generated_media của tiệm (chống SSRF) và
    facebook_ads_client tải lại URL đó -> ghi 1 dòng với link công khai TUYỆT ĐỐI của ảnh đã lưu."""
    if job.get('kind') != 'image' or not job.get('public_base') or not job.get('file_id'):
        return
    try:
        if db.generated_media.find_one({'job_id': job['id']}, {'_id': 1}):
            return
        db.generated_media.insert_one({
            'id': next_mongo_id('generated_media'), 'business_id': job['business_id'], 'campaign_id': None,
            'prompt': job.get('prompt'), 'media_url': job['public_base'] + job['public_url'], 'provider': 'replicate',
            'file_id': job['file_id'], 'job_id': job['id'], 'created_at': _now().isoformat()})
    except Exception as e:
        print(f'[ai_media] legacy row: {e}')


def refresh_job(job_id):
    job = _get_job(job_id)
    if not job:
        raise MediaError('not_found', 'Job not found.', status=404)
    if job.get('status') not in ACTIVE:
        return job
    pid = job.get('prediction_id')
    if not pid:
        # Tạo prediction bị đứt giữa chừng -> sau 10 phút coi là lỗi để không giữ chỗ hạn mức mãi
        if _now() - _aware(job['created_at']) > CREATE_LOST_AFTER:
            _fail(job_id, 'create_lost', 'The AI request was not created.')
        return _get_job(job_id)
    try:
        resp = requests.get(f'{REPLICATE_API}/v1/predictions/{pid}', headers=_headers(), timeout=(10, 20))
    except requests.exceptions.RequestException:
        return job   # mạng chập chờn -> lần hỏi sau thử lại
    if resp.status_code == 404:
        _fail(job_id, 'provider_lost', 'The AI provider no longer has this job.')
        return _get_job(job_id)
    if resp.status_code != 200:
        return job
    try:
        pred = resp.json()
    except ValueError:
        return job
    return _apply_prediction(job, pred if isinstance(pred, dict) else {})


def sweep_stale(business_id, limit=2, now=None):
    """Job mồ côi giữ chỗ hạn mức tới cuối tháng: lệnh tạo chết sau insert (không có prediction_id, trình duyệt không
    nhận được id nên không bao giờ hỏi lại), hoặc chết giữa lúc lưu kết quả khi webhook đã bị bỏ qua. Không ai gọi
    refresh_job nữa -> tự quét khi tiệm mở AI Studio / tạo job:
      - queued/running KHÔNG có prediction_id quá ORPHAN_AFTER (20 phút) -> failed 'create_lost'
      - có prediction_id quá STALE_AFTER (30 phút) -> hỏi Replicate: xong thì lưu kết quả, Replicate báo lỗi/mất thì
        failed, vẫn chưa xong thì quá hạn (huỷ bên Replicate) — đều trả lại chỗ hạn mức.
    Mỗi job tối đa 1 lần / SWEEP_EVERY (Replicate chậm không làm mọi lần tải trang chờ). Trả số job đã xử lý."""
    if not business_id:
        return 0
    now = now or _now()
    done = 0
    try:
        cur = db.ai_media_jobs.find({'business_id': business_id, 'status': {'$in': list(ACTIVE)},
                                     'created_at': {'$lt': now - ORPHAN_AFTER}},
                                    {'_id': 0, 'id': 1, 'prediction_id': 1, 'created_at': 1}).sort('created_at', 1).limit(20)
        for j in list(cur):
            if done >= limit:
                break
            created = _aware(j.get('created_at'))
            if j.get('prediction_id') and created and now - created <= STALE_AFTER:
                continue   # còn trong hạn, giao diện/webhook vẫn lo
            claimed = db.ai_media_jobs.find_one_and_update(
                {'id': j['id'], 'status': {'$in': list(ACTIVE)},
                 '$or': [{'swept_at': None}, {'swept_at': {'$lt': now - SWEEP_EVERY}}]},
                {'$set': {'swept_at': now}}, projection={'_id': 0, 'id': 1}, return_document=ReturnDocument.AFTER)
            if not claimed:
                continue
            done += 1
            if not j.get('prediction_id'):
                _fail(j['id'], 'create_lost', 'The AI request was not created.')
            else:
                refresh_job(j['id'])
    except Exception as e:   # quét là việc phụ — không bao giờ làm hỏng request chính
        print(f'[ai_media] sweep: {e.__class__.__name__}: {e}')
    return done


def adopt_prediction(job_id, prediction_id, model=None):
    """Webhook ĐÃ KIỂM CHỮ KÝ báo xong 1 prediction cho job ?job=<id> mà create_job chết trước khi lưu prediction_id
    (URL webhook chứa id job do chính create_job đặt) -> nhận prediction đó để kết quả đã trả tiền không bị mất.
    Chỉ job còn chạy, chưa có prediction_id, cùng model (khi Replicate gửi model)."""
    if not isinstance(prediction_id, str) or not _PID_RE.fullmatch(prediction_id):
        return None
    flt = {'id': job_id, 'status': {'$in': list(ACTIVE)}, 'prediction_id': None}
    if isinstance(model, str) and model:
        flt['model'] = model
    return db.ai_media_jobs.find_one_and_update(flt, {'$set': {'prediction_id': prediction_id, 'updated_at': _now()}},
                                                projection={'_id': 0}, return_document=ReturnDocument.AFTER)


# ---------------------------------------------------------------- webhook
def _webhook_secret():
    sec = (os.environ.get('REPLICATE_WEBHOOK_SECRET') or '').strip() or _WEBHOOK_SECRET['value']
    if sec:
        return sec
    try:
        resp = requests.get(f'{REPLICATE_API}/v1/webhooks/default/secret', headers=_headers(), timeout=(5, 10))
        if resp.status_code == 200:
            sec = (resp.json() or {}).get('key')
    except (requests.exceptions.RequestException, ValueError, MediaError):
        sec = None
    if sec:
        _WEBHOOK_SECRET['value'] = sec
    return sec


def verify_webhook(raw_body, headers, now=None):
    """Chữ ký kiểu Svix của Replicate: base64(HMAC-SHA256(key, "{id}.{timestamp}.{body}")); key = base64 phần sau
    'whsec_'. Thiếu secret/header -> từ chối (fail-closed). Timestamp lệch quá 5 phút -> từ chối (chống phát lại)."""
    try:
        h = {str(k).lower(): v for k, v in (headers.items() if hasattr(headers, 'items') else [])}
        wid, ts, sigs = h.get('webhook-id'), h.get('webhook-timestamp'), h.get('webhook-signature')
        if not (wid and ts and sigs):
            return False
        ts_i = int(ts)
        if abs((now if now is not None else time.time()) - ts_i) > 300:
            return False
        secret = _webhook_secret()
        if not secret or '_' not in secret:
            return False
        key = base64.b64decode(secret.split('_', 1)[1])
        body = raw_body if isinstance(raw_body, (bytes, bytearray)) else str(raw_body).encode()
        signed = f'{wid}.{ts}.'.encode() + bytes(body)
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        for entry in sigs.split(' '):
            version, _, sig = entry.partition(',')
            if version == 'v1' and sig and hmac.compare_digest(sig.encode(), expected.encode()):
                return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------- prompt từ văn bản
def deepseek_text(system_prompt, user_prompt, temperature, max_tokens, business_id, json_mode=False):
    """Gọi DeepSeek (tự qua AI Proxy ở chế độ Desktop) — trả text thuần. ai_studio_bp._call_deepseek_text dùng lại hàm này."""
    from ai_deepseek_client import deepseek_chat_completion
    payload = {
        'model': 'deepseek-chat',
        'messages': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
        'temperature': temperature, 'max_tokens': max_tokens,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    is_desktop = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
    result = deepseek_chat_completion(
        payload, business_id=business_id,
        proxy_api_key=os.environ.get('BITPAW_AI_PROXY_KEY') if is_desktop else None,
        direct_api_key=os.environ.get('DEEPSEEK_API_KEY') if not is_desktop else None,
    )
    return result['choices'][0]['message']['content']


def log_text_usage(business_id, units, model='deepseek-chat'):
    # Chi phí DeepSeek tính ở chỗ khác -> cost 0, chỉ đếm số token đã xin để biết ai dùng nhiều
    try:
        db.ai_usage.insert_one({'business_id': business_id, 'kind': 'text', 'units': int(units or 0), 'cost_usd': 0.0,
                                'model': model, 'job_id': None, 'created_at': _now()})
    except Exception as e:
        print(f'[ai_media] usage log: {e}')


def brand_context(business_id):
    """Brand DNA (db.ai_brand_profiles) + tên/ngành tiệm — để ảnh/video đúng chất thương hiệu."""
    lines = []
    try:
        biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'industry_code': 1}) or {}
        brand = db.ai_brand_profiles.find_one({'business_id': business_id}, {'_id': 0}) or {}
        name = brand.get('name') or (biz.get('name') if '@' not in (biz.get('name') or '') else '')
        if name:
            lines.append(f'Brand: {name}')
        if biz.get('industry_code'):
            lines.append(f"Industry: {biz['industry_code']}")
        if brand.get('usp'):
            lines.append(f"What makes it different: {brand['usp']}")
        if brand.get('audience'):
            lines.append(f"Target customers: {brand['audience']}")
        if brand.get('blacklist'):
            lines.append(f"Never show or mention: {brand['blacklist']}")
    except Exception as e:
        print(f'[ai_media] brand: {e}')
    return '\n'.join(lines)


def prompt_from_text(business_id, text, kind, lang='en', preset=None):
    """Caption/kịch bản -> 1 prompt hình ảnh tiếng Anh. Không bao giờ xin chữ trong ảnh, trừ preset 'poster'
    (Ideogram vẽ chữ chuẩn) — model ảnh khác vẽ chữ thành ký tự méo, nhìn rất "AI"."""
    text = (text or '').strip()[:3000]
    if not text:
        raise MediaError('prompt_required', 'Write the caption or script first.')
    if kind == 'video':
        task = ('Write ONE English prompt for an AI video model: a single continuous vertical 9:16 shot of about 5 seconds. '
                'Describe subject, setting, lighting, mood and ONE simple camera movement. No text, logos or captions on screen.')
    elif preset == 'poster':
        task = ('Write ONE English prompt for an AI poster generator that renders text well. Include at most one short '
                'headline in double quotes taken from the message (keep its language, max 6 words); never invent prices, '
                'discounts or claims that are not in the message. Describe layout, colors, imagery.')
    else:
        task = ('Write ONE English prompt for an AI image generator: a realistic promotional photo. Describe scene, subject, '
                'lighting, mood and composition. Do NOT include any text, words, letters or logos in the image.')
    system = ('You are a creative director for a local business\'s social media. ' + task +
              ' Output ONLY the prompt, nothing else, max 120 words.')
    ctx = brand_context(business_id)
    user = (ctx + '\n\n' if ctx else '') + f'Message ({lang}): "{text}"'
    try:
        out = deepseek_text(system, user, 0.8, 300, business_id)
    except Exception as e:
        raise MediaError('ai_unavailable', 'The AI writer is busy — try again or type the prompt yourself.', status=502) from e
    log_text_usage(business_id, 300)
    out = re.sub(r'\s+', ' ', (out or '')).strip().strip('"').strip()
    if not out:
        raise MediaError('ai_unavailable', 'The AI writer returned nothing — type the prompt yourself.', status=502)
    return out[:1500]
