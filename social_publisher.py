"""
Bộ đăng bài của AI Social Manager (docs/AI_SUITE_SPEC.md §4.2): Facebook Page, Instagram, YouTube, TikTok, Google Business
Profile — đăng ảnh/video/chữ đúng giờ, thử lại khi nền tảng lỗi tạm, đọc số liệu THẬT (chỉ trường nền tảng trả về).

db.social_posts {id, business_id, status 'draft'|'pending_approval'|'scheduled'|'publishing'|'published'|'partial'|'failed'|
    'canceled', created_by 'owner'|'ai', author_id, plan_id, caption, captions {platform: text}, title, hashtags, link,
    media [{file_id, content_type, kind, size, is_ai_generated}], media_type 'text'|'image'|'video', image_prompt,
    targets [{platform, status 'pending'|'processing'|'scheduled_remote'|'published'|'failed'|'skipped', remote_id,
              container_id, permalink, error {code,message,at}, attempts, next_attempt_at, published_at, options, ...}],
    scheduled_at (UTC dt), approved_by, approved_at, lease_owner, lease_until, is_ai_generated, qa_test, created_at, updated_at}
db.social_post_metrics {business_id, post_id, platform, remote_id, fetched_at, metrics {views, reach, likes, comments,
    shares, saves}} — 1 dòng mới nhất / bài / nền tảng; chỉ có trường nền tảng THẬT SỰ trả về.

Máy trạng thái (run_due):
  - "nhận việc" bằng find_one_and_update có khoá thuê (lease 5 phút): 2 máy chủ/cron chạy cùng lúc không bao giờ đăng
    trùng 1 bài; máy chết giữa chừng thì hết hạn thuê, máy khác làm tiếp.
  - Facebook/YouTube hẹn giờ ≥ 12/15 phút: đẩy trước lên nền tảng (Meta/YouTube tự đăng đúng giờ) -> 'scheduled_remote',
    tới giờ thì kiểm tra lại. Nền tảng khác: tới giờ mới đăng.
  - Lỗi tạm (5xx, giới hạn tốc độ, mạng) -> thử lại sau 2^n phút (tối đa 5 lần); token hỏng (190 / invalid_grant / 401)
    -> tài khoản 'needs_reconnect' + đích 'failed'; lỗi khác -> 'failed' với mã lỗi để UI nói rõ.
  - Lệnh TẠO bài (không lặp lại được): ghi đích 'sending' TRƯỚC khi gọi. Mất phản hồi giữa chừng (hết giờ chờ, máy chủ bị
    tắt) thì KHÔNG tự gửi lại (có thể thành 2 bài) -> 'failed' mã 'publish_uncertain': chủ tiệm kiểm tra trên nền tảng rồi
    bấm "Đăng ngay" nếu bài chưa lên. Instagram lưu container trước media_publish nên lần sau hỏi lại được (PUBLISHED).
  - Sửa / huỷ / đăng ngay: khoá bài (cùng khoá thuê của bộ đăng) + so updated_at -> bộ đăng không chen vào giữa chừng; gỡ
    lịch đã đẩy lên Facebook/YouTube không được thì DỪNG và giữ remote_id (không bao giờ "Đã huỷ" mà bài vẫn tự lên).
"""
import json
import os
import re
import secrets
import socket
import struct
import time
from datetime import timedelta

from pymongo import ReturnDocument

from mongo_client import db, next_mongo_id
import social_accounts as sa
from social_accounts import GRAPH_V, SocialError, as_utc, http, iso_z, rjson, utcnow

EDITABLE = ('draft', 'pending_approval', 'scheduled')
# 'sending' = đang gọi lệnh tạo bài (ghi trước khi gọi); còn 'sending' khi nhận lại bài = máy trước chết giữa chừng
OPEN_T = ('pending', 'processing', 'scheduled_remote', 'sending')
LEASE = timedelta(minutes=5)
MAX_ATTEMPTS = 5
STALE_AFTER = timedelta(hours=24)          # trễ quá 1 ngày (cron hỏng...) thì KHÔNG đăng bài "chúc cuối tuần" vào thứ Hai
PROCESSING_TIMEOUT = timedelta(minutes=60)
# Đẩy trước lên nền tảng khi hẹn giờ đủ xa: Meta cho hẹn 10 phút–30 ngày; YouTube publishAt cần video 'private'
PREPUSH = {'facebook': (timedelta(minutes=12), timedelta(days=29)), 'youtube': (timedelta(minutes=15), timedelta(days=60))}
LIVE_MARGIN = timedelta(minutes=1)         # bài hẹn trên nền tảng sắp/đã tới giờ = coi như đã lên, không xoá nữa
META_TRANSIENT = {1, 2, 4, 17, 32, 341, 613, 80001}
TIKTOK_PRIVACY = ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')
TIKTOK_FLAGS = ('disable_comment', 'disable_duet', 'disable_stitch', 'brand_content_toggle', 'brand_organic_toggle')
TT_POST_ID_WINDOW = timedelta(hours=48)    # TikTok chỉ trả id bài công khai SAU kiểm duyệt (vài phút–vài giờ)
YT_PRIVACY = ('public', 'unlisted', 'private')
# Giới hạn chữ của từng nền tảng (Facebook: 63.206 ký tự; YouTube: mô tả ≤ 5000 BYTE — chữ có dấu tốn 2–3 byte)
CAPTION_MAX = {'facebook': 63206, 'instagram': 2200, 'tiktok': 2200, 'youtube': 5000, 'google_business': 1500}
BASE_CAPTION_MAX = max(CAPTION_MAX.values())
YT_DESC_BYTES = 5000
# Ảnh Facebook /photos: tối đa 4 MB, không nhận WebP; PNG > 1 MB Meta khuyên tránh (dễ bị nén vỡ hạt) — chỉ nhắc
FB_PHOTO_MAX = 4_000_000
FB_PNG_SOFT = 1_000_000
UPLOAD_TIMEOUT = (10, 150)                 # < LEASE: 1 lần tải video không thể kéo quá hạn thuê
VIDEO_START_MIN = 15                       # còn < 15 giây trong hạn chạy thì để lượt sau mới bắt đầu tải video
# Chỉ media "công khai theo thiết kế" mới được đăng (ảnh check-in/avatar nhân viên thì không bao giờ)
SHAREABLE_KINDS = {'ai_image', 'ai_video', 'promo_video', 'social_upload', 'product_image'}
AI_KINDS = {'ai_image', 'ai_video'}
_EXT = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif', 'video/mp4': 'mp4',
        'video/webm': 'webm', 'video/quicktime': 'mov'}
METRIC_PLATFORMS = ('facebook', 'instagram', 'youtube', 'tiktok')   # Google đã bỏ số liệu bài đăng Business Profile

_INDEXES_READY = False


def _ensure_indexes():
    global _INDEXES_READY
    if _INDEXES_READY or db is None:
        return
    try:
        db.social_posts.create_index('id', unique=True)
        db.social_posts.create_index([('status', 1), ('scheduled_at', 1)])
        db.social_posts.create_index([('business_id', 1), ('scheduled_at', -1)])
        db.social_post_metrics.create_index([('business_id', 1), ('post_id', 1), ('platform', 1)], unique=True)
        _INDEXES_READY = True
    except Exception as e:
        print(f"[social] index: {e}")


def _world():
    """Bài tạo lúc thử (máy giả) và bài thật không bao giờ lẫn nhau, kể cả khi xem/sửa."""
    return {'qa_test': True} if sa.test_mode() else {'qa_test': {'$ne': True}}


def _lease_free(now):
    return {'$or': [{'lease_until': None}, {'lease_until': {'$lt': now}}]}


def _leased(doc, now):
    lu = as_utc(doc.get('lease_until'))
    return bool(lu and lu >= now)


# ---------------------------------------------------------------- media + nội dung
def media_url(item, absolute=False):
    """Link xem media của bài. Ảnh sản phẩm đã công khai sẵn qua route menu QR của app.py; còn lại qua media_store (/m/...)."""
    fid, ext = item['file_id'], _EXT.get(item.get('content_type') or '', 'bin')
    if item.get('kind') == 'product_image':
        path = f"/api/public/storage/file/{fid}"
        return sa.public_base() + path if absolute else path
    import media_store
    return media_store.absolute_public_url(fid, ext, sa.public_base()) if absolute else media_store.public_url(fid, ext)


def url_fetch_max():
    """Ảnh lớn nhất Instagram / Google Business tải trọn được qua link BitPaw: 2 nền tảng này tải 1 lần KHÔNG kèm Range, mà
    response của Vercel chỉ chứa được ≤ media_store.FULL_MAX byte (lớn hơn thì chỉ nhận lát đầu = ảnh cụt)."""
    try:
        import media_store
        return int(getattr(media_store, 'FULL_MAX', 3_200_000))
    except Exception:
        return 3_200_000


def _mb(n):
    return f"{n / 1_000_000:.1f} MB"


def _gf(g, name):
    try:
        v = getattr(g, name)
    except AttributeError:
        v = None
    if v is None:
        v = (getattr(g, 'metadata', None) or {}).get(name)
    return v


def _resolve_media(business_id, file_ids):
    if not isinstance(file_ids, list):
        raise SocialError('bad_media', 'media_file_ids must be a list.')
    ids = [str(x).strip() for x in file_ids if str(x or '').strip()]
    if len(ids) > 1:
        # bài nhiều ảnh (carousel) cần luồng riêng từng nền tảng — chưa làm, nói thẳng thay vì lặng lẽ bỏ bớt ảnh
        raise SocialError('single_media_only', 'Pick one photo or one video per post for now.')
    out = []
    import media_store
    for fid in ids:
        g = media_store.get(fid, business_id)
        if g is None:
            raise SocialError('media_not_found', 'That photo/video was not found in your library.', fid)
        ct, kind = (_gf(g, 'content_type') or '').lower(), _gf(g, 'kind') or ''
        if kind not in SHAREABLE_KINDS:
            raise SocialError('media_not_shareable', 'This file is private and cannot be posted.', fid)
        if not (ct.startswith('image/') or ct.startswith('video/')):
            raise SocialError('bad_media', 'Only photos and videos can be posted.', ct)
        out.append({'file_id': fid, 'content_type': ct, 'kind': kind, 'size': int(_gf(g, 'length') or 0),
                    'is_ai_generated': kind in AI_KINDS or bool(_gf(g, 'is_ai_generated'))})
    return out


def _media_type(media):
    if not media:
        return 'text'
    return 'video' if media[0]['content_type'].startswith('video/') else 'image'


def _text(v, n):
    return (v.strip() if isinstance(v, str) else '')[:n]


def _hashtags(v):
    if isinstance(v, str):
        v = re.split(r'[\s,]+', v)
    out = []
    for h in v or []:
        h = re.sub(r'[^\w]', '', str(h or '').lstrip('#'))[:50]
        if h and h.lower() not in {x.lower() for x in out}:
            out.append(h)
    return out[:30]


def strip_hashtags(text):
    t = re.sub(r'(^|\s)#[\w\-]+', r'\1', text or '')
    return re.sub(r'[ \t]{2,}', ' ', re.sub(r'\n{3,}', '\n\n', t)).strip()


def _caption_full(post, platform):
    own = ((post.get('captions') or {}).get(platform) or '').strip()
    text = own or (post.get('caption') or '').strip()
    if platform == 'google_business':
        text = strip_hashtags(text)   # Google không dùng hashtag
    elif not own and platform != 'youtube':
        tags = ' '.join('#' + h for h in post.get('hashtags') or [] if ('#' + h).lower() not in text.lower())
        if tags:
            text = f"{text}\n\n{tags}".strip()
    return text


def _cut_bytes(text, n):
    """Cắt theo BYTE UTF-8 (không cắt đôi 1 chữ có dấu)."""
    return text.encode('utf-8')[:n].decode('utf-8', 'ignore')


def caption_for(post, platform):
    """Chữ đăng lên 1 nền tảng: bản AI/chủ tiệm viết riêng cho nền tảng đó, không có thì bản chung + hashtag.
    Lên lịch đã kiểm tra độ dài (_check_caption) — cắt ở đây chỉ là chốt chặn cuối cho bài cũ."""
    text = _caption_full(post, platform)
    if platform == 'youtube':
        return _cut_bytes(text, YT_DESC_BYTES)
    return text[:CAPTION_MAX[platform]]


def _check_caption(post, platform):
    """Quá giới hạn của nền tảng thì nói rõ để chủ tiệm rút gọn — không lặng lẽ cắt mất phần cuối."""
    text, label = _caption_full(post, platform), sa.LABELS[platform]
    if platform == 'youtube':
        n = len(re.sub(r'[<>]', '', text).encode('utf-8'))
        if n > YT_DESC_BYTES:
            raise SocialError('caption_too_long', f"The YouTube description is too long: {n} bytes (max {YT_DESC_BYTES}; "
                              'accented letters count as 2–3 bytes) — shorten it.', f"{n}/{YT_DESC_BYTES}", platform=platform)
    elif len(text) > CAPTION_MAX[platform]:
        raise SocialError('caption_too_long', f"The {label} text is too long: {len(text)} characters (max "
                          f"{CAPTION_MAX[platform]}) — shorten it.", f"{len(text)}/{CAPTION_MAX[platform]}", platform=platform)


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ('true', '1', 'yes', 'on'):
        return True
    if isinstance(v, str) and v.lower() in ('false', '0', 'no', 'off', ''):
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    raise SocialError('bad_option', 'Invalid option value.', str(v)[:40])


def _clean_options(platform, opts):
    opts = opts if isinstance(opts, dict) else {}
    if platform == 'tiktok':
        # Quy định Direct Post của TikTok: chủ tiệm tự chọn từng bài, KHÔNG có giá trị mặc định
        o = {}
        pl = opts.get('privacy_level')
        if pl not in (None, ''):
            if pl not in TIKTOK_PRIVACY:
                raise SocialError('tiktok_bad_privacy', 'Pick who can see the TikTok post.', str(pl)[:40], platform='tiktok')
            o['privacy_level'] = pl
        for k in TIKTOK_FLAGS:
            if opts.get(k) is not None:
                o[k] = _bool(opts[k])
        if o.get('brand_content_toggle') and o.get('privacy_level') == 'SELF_ONLY':
            raise SocialError('tiktok_branded_private', "Branded content can't be posted as 'Only me'.", platform='tiktok')
        if opts.get('music_usage_confirmed') is not None:
            o['music_usage_confirmed'] = _bool(opts['music_usage_confirmed'])
        return o
    if platform == 'youtube':
        ps = opts.get('privacy_status')
        if ps in (None, ''):
            return {}
        if ps not in YT_PRIVACY:
            raise SocialError('bad_option', 'YouTube visibility must be public, unlisted or private.', str(ps)[:40], platform='youtube')
        return {'privacy_status': ps}
    return {}


def _tiktok_missing(o):
    return [k for k in ('privacy_level',) + TIKTOK_FLAGS if k not in (o or {})]


def _fresh_target(platform, options):
    return {'platform': platform, 'status': 'pending', 'remote_id': None, 'container_id': None, 'permalink': None,
            'error': None, 'attempts': 0, 'next_attempt_at': None, 'published_at': None, 'options': options}


def _targets(raw, old_targets=None):
    if not isinstance(raw, list):
        raise SocialError('bad_targets', 'targets must be a list.')
    old = {t.get('platform'): t for t in old_targets or []}
    out, seen = [], set()
    for item in raw:
        p = item if isinstance(item, str) else (item or {}).get('platform') if isinstance(item, dict) else None
        if p not in sa.PLATFORMS:
            raise SocialError('bad_platform', 'Unknown platform.', str(p)[:40])
        if p in seen:
            continue
        seen.add(p)
        opts = item.get('options') if isinstance(item, dict) and 'options' in item else (old.get(p) or {}).get('options')
        out.append(_fresh_target(p, _clean_options(p, opts)))
    return out


def _norm(business_id, data, old):
    if not isinstance(data, dict):
        raise SocialError('bad_request', 'JSON body required.')
    out = {}
    new = old is None
    if 'caption' in data or new:
        cap = _text(data.get('caption'), None)
        if len(cap) > BASE_CAPTION_MAX:
            raise SocialError('caption_too_long', f"The text is too long: {len(cap)} characters (max {BASE_CAPTION_MAX}).",
                              f"{len(cap)}/{BASE_CAPTION_MAX}")
        out['caption'] = cap
    if 'captions' in data or new:
        caps = data.get('captions') or {}
        if not isinstance(caps, dict):
            raise SocialError('bad_captions', 'captions must be an object {platform: text}.')
        out['captions'] = {}
        for p, t in caps.items():
            if p not in sa.PLATFORMS or not _text(t, 1):
                continue
            t = _text(t, None)
            if len(t) > CAPTION_MAX[p]:
                # không lặng lẽ cắt: chủ tiệm phải thấy phần cuối bị mất
                raise SocialError('caption_too_long', f"The {sa.LABELS[p]} text is too long: {len(t)} characters (max "
                                  f"{CAPTION_MAX[p]}) — shorten it.", f"{len(t)}/{CAPTION_MAX[p]}", platform=p)
            out['captions'][p] = t
        if isinstance(caps.get('youtube_title'), str) and 'title' not in data:
            out['title'] = re.sub(r'[<>]', '', _text(caps['youtube_title'], 100))
    if 'title' in data or (new and 'title' not in out):
        out['title'] = re.sub(r'[<>]', '', _text(data.get('title'), 100))   # YouTube cấm < > trong tiêu đề
    if 'link' in data or new:
        link = _text(data.get('link'), 500)
        if link and not re.match(r'^https?://[^\s/]+\.[^\s/]+\S*$', link):
            raise SocialError('bad_link', 'The link must be a full web address starting with https://')
        out['link'] = link or None
    if 'hashtags' in data or new:
        out['hashtags'] = _hashtags(data.get('hashtags'))
    if 'image_prompt' in data:
        out['image_prompt'] = _text(data.get('image_prompt'), 600) or None
    if 'media_file_ids' in data or new:
        out['media'] = _resolve_media(business_id, data.get('media_file_ids') or [])
        out['media_type'] = _media_type(out['media'])
        out['is_ai_generated'] = any(m['is_ai_generated'] for m in out['media'])
    if 'targets' in data or new:
        out['targets'] = _targets(data.get('targets') or [], (old or {}).get('targets'))
    if 'scheduled_at' in data:
        v = data.get('scheduled_at')
        try:
            out['scheduled_at'] = sa.parse_iso(v) if v else None
        except (ValueError, TypeError):
            raise SocialError('bad_time', 'Use a full date and time with the time zone (ISO 8601).', str(v)[:40])
    return out


def _due_time(t, now):
    t = as_utc(t)
    if t is None:
        return now
    if t < now - timedelta(minutes=10):
        raise SocialError('time_in_past', 'The scheduled time has already passed — pick a new time.')
    return max(t, now)


def _validate_ready(business_id, doc, platforms=None):
    """Điều kiện để lên lịch / đăng: có nơi đăng, có nội dung, tài khoản đã nối (Google Business đã chọn địa điểm), chữ
    không quá giới hạn, ảnh không quá cỡ nền tảng tải được, TikTok đã chọn đủ tuỳ chọn. Lỗi ở đây = chưa gửi nơi nào
    (không bao giờ đăng nửa vời rồi mới báo)."""
    targets = doc.get('targets') or []
    if not targets:
        raise SocialError('no_targets', 'Pick at least one place to post.')
    if not (doc.get('caption') or doc.get('captions') or doc.get('media')):
        raise SocialError('empty_post', 'Write a caption or add a photo/video first.')
    warns = compat_warnings(doc)
    skipped = {w['platform'] for w in warns if w['skip']}
    for t in targets:
        p = t['platform']
        if platforms is not None and p not in platforms:
            continue
        if not sa.is_connected(business_id, p):
            acc = sa.get_account(business_id, p)
            if sa.needs_location(acc):
                raise SocialError('needs_location', 'Choose which Google Business Profile location to post to (Accounts tab).',
                                  platform=p)
            raise SocialError('not_connected', f"{sa.LABELS[p]} is not connected.", platform=p)
        for w in warns:
            if w['platform'] == p and w['blocking']:
                raise SocialError(w['code'], w['message'], platform=p)
        if p not in skipped:
            _check_caption(doc, p)
        if p == 'tiktok':
            miss = _tiktok_missing(t.get('options'))
            if miss:
                raise SocialError('tiktok_options_required', 'Choose who can see the TikTok post and the comment / duet / stitch '
                                  'and branded-content settings.', ','.join(miss), platform='tiktok')


def _media_problem(platform, media_type, ct, size):
    """Mã lỗi media cho 1 nền tảng (None nếu ổn). Dùng chung cho cảnh báo trước (compat_warnings) và adapter lúc đăng."""
    if platform == 'instagram':
        if media_type == 'text':
            return 'ig_needs_media'
        if media_type == 'image' and ct != 'image/jpeg':
            return 'ig_needs_jpeg'
        if media_type == 'image' and size > url_fetch_max():
            return 'media_too_large'
    elif platform == 'youtube' and media_type != 'video':
        return 'youtube_needs_video'
    elif platform == 'tiktok' and media_type != 'video':
        return 'tiktok_needs_video'
    elif platform == 'google_business':
        if media_type == 'video':
            return 'gbp_no_video'
        if media_type == 'image' and size > url_fetch_max():
            return 'media_too_large'
    elif platform == 'facebook' and media_type == 'image':
        if ct == 'image/webp':
            return 'fb_photo_format'
        if size > FB_PHOTO_MAX:
            return 'fb_photo_too_large'
        if ct == 'image/png' and size > FB_PNG_SOFT:
            return 'fb_png_large'
    return None


def _media_message(code, platform, size):
    if code == 'media_too_large':
        return (f"This photo is {_mb(size)} — too large for {sa.LABELS[platform]} to download from BitPaw (max "
                f"{_mb(url_fetch_max())}). Use a smaller photo or remove {sa.LABELS[platform]}.")
    if code == 'fb_photo_too_large':
        return f"Facebook accepts photos up to {_mb(FB_PHOTO_MAX)} — this one is {_mb(size)}, so it will not be sent there."
    return SKIP_MESSAGES[code]


def compat_warnings(post):
    """Nói trước cho chủ tiệm (thay vì để tới giờ mới biết): {platform, code, message, skip, blocking}.
    skip=True: đích sẽ bị bỏ qua lúc đăng; blocking=True: không cho lên lịch tới khi sửa (vd ảnh quá cỡ Instagram/Google
    tải được — gửi đi là ảnh cụt); cả 2 False: chỉ là lưu ý (vẫn đăng)."""
    mt, out = post.get('media_type') or 'text', []
    m = (post.get('media') or [{}])[0] or {}
    ct, size = m.get('content_type') or '', int(m.get('size') or 0)
    for t in post.get('targets') or []:
        p = t['platform']
        code = _media_problem(p, mt, ct, size)
        if code:
            out.append({'platform': p, 'code': code, 'message': _media_message(code, p, size),
                        'skip': code not in NOTE_ONLY and code not in BLOCKING, 'blocking': code in BLOCKING})
    return out


SKIP_MESSAGES = {
    'ig_needs_media': 'Instagram needs a photo or a video — this post will not be sent there.',
    'ig_needs_jpeg': 'Instagram only accepts JPEG photos — this photo will not be sent there.',
    'youtube_needs_video': 'YouTube needs a video — this post will not be sent there.',
    'tiktok_needs_video': 'TikTok needs a video — this post will not be sent there.',
    'gbp_no_video': 'Google Business Profile does not take videos — this post will not be sent there.',
    'fb_photo_format': 'Facebook does not accept WebP photos — this photo will not be sent there (use JPEG or PNG).',
    'fb_photo_too_large': 'Facebook accepts photos up to 4 MB — this photo will not be sent there.',
    'fb_png_large': 'Facebook recommends PNG photos under 1 MB — this one may look blurry after Facebook compresses it '
                    '(a JPEG usually looks better).',
    'media_too_large': 'This photo is too large for the platform to download from BitPaw — use a smaller photo.',
}
BLOCKING = {'media_too_large'}
NOTE_ONLY = {'fb_png_large'}


# ---------------------------------------------------------------- CRUD
def _get(business_id, post_id):
    doc = db.social_posts.find_one({'id': post_id, 'business_id': business_id, **_world()}, {'_id': 0})
    if not doc:
        raise SocialError('not_found', 'Post not found.')
    return doc


def get_post(business_id, post_id):
    return _get(business_id, post_id)


def create_post(business_id, user_id, data, created_by='owner', plan_id=None, is_admin=True):
    _ensure_indexes()
    raw = (data or {}).get('status') if isinstance(data, dict) else None
    if raw is not None and not isinstance(raw, str):
        raise SocialError('bad_status', 'A new post can be a draft, waiting for approval, or scheduled.')
    status = raw or 'draft'
    if status not in ('draft', 'scheduled', 'pending_approval'):
        raise SocialError('bad_status', 'A new post can be a draft, waiting for approval, or scheduled.')
    if not is_admin and status == 'scheduled':
        status = 'pending_approval'   # nhân viên soạn bài -> chủ tiệm duyệt mới đăng
    f = _norm(business_id, data, None)
    now = utcnow()
    doc = {'id': next_mongo_id('social_posts'), 'business_id': business_id, 'status': status, 'created_by': created_by,
           'author_id': user_id, 'plan_id': plan_id, 'scheduled_at': None, 'image_prompt': None, **f,
           'approved_by': None, 'approved_at': None, 'lease_owner': None, 'lease_until': None,
           'qa_test': sa.test_mode(), 'created_at': now, 'updated_at': now}
    if status == 'scheduled':
        doc['scheduled_at'] = _due_time(doc.get('scheduled_at'), now)
        _validate_ready(business_id, doc)
        doc['approved_by'], doc['approved_at'] = user_id, now
    db.social_posts.insert_one(dict(doc))
    doc['warnings'] = compat_warnings(doc)
    return doc


UNCERTAIN_MSG = ("BitPaw lost the connection while sending this post to {p} — it may already be live there. Check {p}; "
                 "if it is not there, press 'Publish now' to send it again.")


def _lock(doc, now):
    """Khoá bài trong lúc chủ tiệm sửa / huỷ / xoá / đăng ngay (dùng chung khoá thuê với bộ đăng): bộ đăng không nhận bài
    giữa chừng; bài đã đổi kể từ lúc đọc (updated_at khác — vd vừa được đẩy lên Facebook) thì dừng, không ghi đè."""
    me = f"user-{secrets.token_hex(6)}"
    flt = {'$and': [{'id': doc['id'], 'business_id': doc['business_id'], 'status': doc['status'],
                     'updated_at': doc.get('updated_at')}, _lease_free(now)]}
    if db.social_posts.update_one(flt, {'$set': {'lease_owner': me, 'lease_until': now + LEASE}}).matched_count != 1:
        raise SocialError('busy', 'This post changed or is being sent right now — reload and try again.')
    return me


def _unlock(doc, me):
    db.social_posts.update_one({'id': doc['id'], 'business_id': doc['business_id'], 'lease_owner': me},
                               {'$set': {'lease_owner': None, 'lease_until': None}})


def _write_locked(doc, me, fields):
    """Ghi kết quả + trả khoá — chỉ khi vẫn đang giữ khoá của chính lần sửa này."""
    res = db.social_posts.update_one({'id': doc['id'], 'business_id': doc['business_id'], 'lease_owner': me},
                                     {'$set': {**fields, 'updated_at': utcnow(), 'lease_owner': None, 'lease_until': None}})
    if res.matched_count != 1:
        raise SocialError('busy', 'This post changed — reload and try again.')


def _unschedule_remote(doc, now, me, mode, force=False):
    """Bài đã đẩy trước lên Facebook/YouTube (nền tảng tự đăng đúng giờ) mà chủ tiệm sửa / đăng ngay / huỷ / xoá: gỡ lịch
    bên đó trước, nếu không bản cũ vẫn tự lên. mode: 'edit' (sửa, đăng ngay) | 'cancel' | 'delete'.
      - đã tới giờ hẹn (nền tảng đã/sắp đăng): KHÔNG xoá bài đang chạy (mất lượt thích, bình luận) — sửa / đăng ngay / huỷ bị
        từ chối ('already_live'); xoá khỏi BitPaw thì để nguyên trên nền tảng (kèm cảnh báo).
      - gỡ không được: giữ nguyên 'scheduled_remote' + remote_id và DỪNG ('remote_cancel_failed') — không bao giờ báo "đã huỷ"
        mà bài vẫn tự lên. force=True (chủ tiệm xác nhận đã tự xoá bên nền tảng) thì huỷ/xoá ở BitPaw, giữ remote_id + cảnh báo.
      - đích 'sending' (lần gửi trước mất phản hồi): có thể đã lên — sửa / đăng ngay bị từ chối, huỷ / xoá kèm cảnh báo.
    Đích gỡ xong được ghi ngay vào DB (kể cả khi đích sau đó lỗi) để không trỏ tới bài đã xoá."""
    sched = as_utc(doc.get('scheduled_at'))
    live = bool(sched and sched <= now + LIVE_MARGIN)
    warnings, changed, fail = [], False, None
    for i, t in enumerate(doc.get('targets') or []):
        p, st = t.get('platform'), t.get('status')
        label = sa.LABELS.get(p, p)
        if st == 'sending':
            if mode == 'edit':
                # lần gửi trước mất phản hồi (máy chết giữa chừng): đánh dấu 'failed / publish_uncertain' rồi dừng — chủ tiệm
                # kiểm tra trên nền tảng trước; bấm lại lần nữa là xác nhận gửi lại (không kẹt mãi, không tự đăng 2 lần)
                msg = (f"BitPaw lost the connection while sending this post to {label} — it may already be scheduled or live "
                       f"there. Check {label} first (delete it there if you see it), then save or publish again.")
                doc['targets'][i] = {**t, 'status': 'failed', 'next_attempt_at': None,
                                     'error': {'code': 'publish_uncertain', 'message': msg, 'at': now}}
                changed = True
                fail = SocialError('publish_uncertain', msg, platform=p)
                break
            warnings.append({'platform': p, 'code': 'publish_uncertain', 'message': UNCERTAIN_MSG.format(p=label)})
            continue
        if st != 'scheduled_remote' or not t.get('remote_id'):
            continue
        if live:
            msg = f"{label} has already published this post at its scheduled time — edit or delete it on {label}."
            if mode == 'delete' or (force and mode == 'cancel'):
                warnings.append({'platform': p, 'code': 'already_live', 'message': msg})
                continue
            fail = SocialError('already_live', msg, platform=p)
            break
        try:
            acc = sa.get_account(doc['business_id'], p)
            if not acc:
                raise SocialError('not_connected', f"{label} is not connected.", platform=p)
            ADAPTERS[p]['unschedule'](t, sa.access_token(acc))
        except SocialError as e:
            if e.reconnect:
                sa.mark_needs_reconnect(doc['business_id'], p, e)
            msg = (f"Could not remove the scheduled post from {label} ({e}). It is still scheduled there — reconnect {label} "
                   f"and try again, or delete it on {label} first.")
            if force and mode != 'edit':
                warnings.append({'platform': p, 'code': 'remote_cancel_failed', 'message': msg})
                continue   # giữ 'scheduled_remote' + remote_id trong bản ghi
            fail = SocialError('remote_cancel_failed', msg, e.code, platform=p)
            break
        doc['targets'][i] = _fresh_target(p, t.get('options') or {})
        changed = True
    if changed:
        db.social_posts.update_one({'id': doc['id'], 'business_id': doc['business_id'], 'lease_owner': me},
                                   {'$set': {'targets': doc['targets'], 'updated_at': utcnow()}})
    if fail:
        raise fail
    return warnings


def update_post(business_id, post_id, data, user_id=None, is_admin=True):
    doc = _get(business_id, post_id)
    now = utcnow()
    if doc['status'] not in EDITABLE:
        raise SocialError('not_editable', 'This post is already being published or is finished — it can no longer be edited.')
    if _leased(doc, now):
        raise SocialError('busy', 'This post is being sent right now — try again in a minute.')
    raw = data.get('status') if isinstance(data, dict) else None
    if raw is not None and not isinstance(raw, str):
        raise SocialError('bad_status', 'Status must be draft, pending_approval or scheduled.')
    status = raw or doc['status']
    if status not in EDITABLE:
        raise SocialError('bad_status', 'Status must be draft, pending_approval or scheduled.')
    if not is_admin and (status == 'scheduled' or doc['status'] == 'scheduled'):
        # nhân viên không bao giờ tự lên lịch hay giữ lịch đã duyệt sau khi sửa: quay lại chờ chủ tiệm duyệt
        status = 'pending_approval'
    # kiểm tra hết TRƯỚC khi đụng tới bài đã hẹn trên Facebook/YouTube (sửa bị từ chối thì bài hẹn bên đó còn nguyên)
    f = _norm(business_id, data, doc)
    if 'targets' not in f:
        # nội dung đổi -> lỗi/lần thử cũ (từ lần đẩy trước lên Facebook/YouTube) không còn đúng: làm lại từ đầu
        f['targets'] = [_fresh_target(t['platform'], t.get('options') or {}) for t in doc['targets']]
    new = {**doc, **f}
    if status == 'scheduled':
        f['scheduled_at'] = _due_time(new.get('scheduled_at'), now)
        new['scheduled_at'] = f['scheduled_at']
        _validate_ready(business_id, new)
        f['approved_by'], f['approved_at'] = user_id, now
    else:
        f['approved_by'], f['approved_at'] = None, None   # nội dung mới chưa ai duyệt
    f['status'] = status
    me = _lock(doc, now)
    try:
        _unschedule_remote(doc, now, me, 'edit')
        _write_locked(doc, me, f)
    finally:
        _unlock(doc, me)
    out = _get(business_id, post_id)
    out['warnings'] = compat_warnings(out)
    return out


def approve(business_id, post_id, user_id):
    doc = _get(business_id, post_id)
    if doc['status'] != 'pending_approval':
        raise SocialError('not_pending', 'This post is not waiting for approval.')
    now = utcnow()
    when = as_utc(doc.get('scheduled_at'))
    if not when or when < now:
        # duyệt muộn (giờ AI đề xuất đã qua): dời sang khung giờ tốt kế tiếp thay vì đăng vội
        try:
            import social_planner
            when = social_planner.next_slot(business_id, doc['targets'][0]['platform'], now) if doc.get('targets') else now
        except Exception:
            when = now
    new = {**doc, 'scheduled_at': when}
    _validate_ready(business_id, new)
    # updated_at: duyệt đúng bản chủ tiệm vừa đọc — nhân viên sửa xen giữa thì phải xem lại
    res = db.social_posts.update_one({'$and': [{'id': post_id, 'business_id': business_id, 'status': 'pending_approval',
                                                'updated_at': doc.get('updated_at')}, _lease_free(now)]},
                                     {'$set': {'status': 'scheduled', 'scheduled_at': when, 'approved_by': user_id,
                                               'approved_at': now, 'updated_at': max(now, utcnow())}})
    if res.matched_count != 1:
        raise SocialError('busy', 'This post changed — reload and try again.')
    out = _get(business_id, post_id)
    out['warnings'] = compat_warnings(out)
    return out


def cancel(business_id, post_id, force=False):
    """Huỷ bài chưa đăng. Bài đã hẹn trên Facebook/YouTube: gỡ bên đó trước; gỡ không được thì báo lỗi (bài vẫn còn hẹn,
    remote_id giữ nguyên) — force=True khi chủ tiệm đã tự xoá bên nền tảng."""
    doc = _get(business_id, post_id)
    if doc['status'] == 'canceled':
        return {**doc, 'warnings': []}
    now = utcnow()
    if doc['status'] not in EDITABLE:
        raise SocialError('not_cancelable', 'This post was already sent (or is being sent) — delete it on the platform instead.')
    if _leased(doc, now):
        raise SocialError('busy', 'This post is being sent right now — try again in a minute.')
    me = _lock(doc, now)
    try:
        warnings = _unschedule_remote(doc, now, me, 'cancel', force=force)
        _write_locked(doc, me, {'status': 'canceled'})
    finally:
        _unlock(doc, me)
    return {**_get(business_id, post_id), 'warnings': warnings}


def delete(business_id, post_id, force=False):
    """Xoá bài khỏi BitPaw (bài đã lên nền tảng vẫn còn trên nền tảng). Bài còn hẹn trên Facebook/YouTube mà gỡ không được
    thì KHÔNG xoá (mất remote_id = hết cách gỡ) — trừ khi force=True."""
    doc = _get(business_id, post_id)
    now = utcnow()
    if _leased(doc, now):
        raise SocialError('busy', 'This post is being sent right now — try again in a minute.')
    me = _lock(doc, now)
    try:
        warnings = _unschedule_remote(doc, now, me, 'delete', force=force) if doc['status'] in EDITABLE else []
        res = db.social_posts.delete_one({'id': post_id, 'business_id': business_id, 'lease_owner': me})
        if res.deleted_count != 1:
            raise SocialError('busy', 'This post changed — reload and try again.')
    finally:
        _unlock(doc, me)
    db.social_post_metrics.delete_many({'business_id': business_id, 'post_id': post_id})
    return warnings


def publish_now(business_id, post_id, user_id, deadline=25):
    """Đăng NGAY (hoặc thử lại đích lỗi sau khi nối lại tài khoản), chạy đồng bộ ≤ deadline giây."""
    doc = _get(business_id, post_id)
    now = utcnow()
    if _leased(doc, now):
        raise SocialError('busy', 'This post is being sent right now — try again in a minute.')
    if doc['status'] in EDITABLE:
        _validate_ready(business_id, {**doc, 'scheduled_at': now})
        upd = {'status': 'scheduled', 'scheduled_at': now, 'approved_by': user_id, 'approved_at': now}
        fresh = True
    elif doc['status'] in ('failed', 'partial', 'publishing'):
        retry = [t['platform'] for t in doc['targets'] if t.get('status') == 'failed']
        _validate_ready(business_id, doc, platforms=set(retry))
        targets = [(_fresh_target(t['platform'], t.get('options') or {}) if t.get('status') == 'failed'
                    else {**t, 'next_attempt_at': None} if t.get('status') == 'pending' else t) for t in doc['targets']]
        if not any(t['status'] in OPEN_T for t in targets):
            raise SocialError('nothing_to_publish', 'Nothing left to send for this post.')
        upd = {'status': 'publishing', 'targets': targets}
        fresh = False
    else:
        raise SocialError('nothing_to_publish', 'This post was already published or canceled.')
    me = _lock(doc, now)
    try:
        if fresh:
            # bài đã hẹn trên Facebook/YouTube: gỡ lịch bên đó trước (đã tới giờ = đã lên -> từ chối, không đăng bản 2)
            _unschedule_remote(doc, now, me, 'edit')
            upd['targets'] = [_fresh_target(t['platform'], t.get('options') or {}) for t in doc['targets']]
        _write_locked(doc, me, upd)
    finally:
        _unlock(doc, me)
    stats = run_due(business_id, limit=1, now=now, post_id=post_id, deadline=deadline)
    return _get(business_id, post_id), stats


def list_posts(business_id, frm=None, to=None, statuses=None, limit=300):
    q = {'business_id': business_id, **_world()}
    if statuses:
        q['status'] = {'$in': list(statuses)}
    if frm or to:
        rng = {}
        if frm:
            rng['$gte'] = frm
        if to:
            rng['$lt'] = to
        # bản nháp chưa có giờ vẫn hiện trong danh sách
        q['$or'] = [{'scheduled_at': rng}, {'scheduled_at': None}]
        return list(db.social_posts.find(q, {'_id': 0}).sort('scheduled_at', 1).limit(limit))
    # không chọn khoảng ngày (tab danh sách): bài mới nhất trước
    return list(db.social_posts.find(q, {'_id': 0}).sort('created_at', -1).limit(limit))


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if hasattr(v, 'isoformat') and hasattr(v, 'tzinfo'):
        return iso_z(v)
    return v


def public_post(doc):
    """Bài cho UI/API: giờ ISO 'Z', media có url, không lộ thông tin khoá thuê."""
    out = {k: v for k, v in doc.items() if k not in ('_id', 'lease_owner', 'lease_until', 'business_id')}
    out['busy'] = _leased(doc, utcnow())
    media = []
    for m in doc.get('media') or []:
        try:
            url = media_url(m)
        except Exception:
            url = None
        media.append({**m, 'url': url})
    out['media'] = media
    return _jsonable(out)


# ---------------------------------------------------------------- lỗi từng nền tảng
def _meta(r, platform):
    j = rjson(r)
    if r.status_code < 300 and not j.get('error'):
        return j
    e = j.get('error') if isinstance(j.get('error'), dict) else {}
    code, sub = e.get('code'), e.get('error_subcode')
    msg = e.get('error_user_msg') or e.get('message') or f"HTTP {r.status_code}"
    label = sa.LABELS[platform]
    if code in (190, 102):
        raise SocialError('token_invalid', f"The {label} access token is invalid or has expired — reconnect {label}.", msg,
                          reconnect=True, platform=platform)
    if code == 9007 or sub == 2207027:
        raise SocialError('ig_not_ready', 'Instagram is still processing the media.', msg, transient=True, platform=platform)
    if r.status_code >= 500 or code in META_TRANSIENT or (isinstance(code, int) and 80000 <= code <= 80014) or e.get('is_transient'):
        raise SocialError('provider_busy', f"{label} is busy or rate-limited — will retry.", msg, transient=True, platform=platform)
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        raise SocialError('meta_permission', f"{label} refused: BitPaw's app is missing a permission for this ({msg}).", msg, platform=platform)
    if code == 368:
        raise SocialError('meta_blocked', f"{label} temporarily blocked posting from this account ({msg}).", msg, platform=platform)
    raise SocialError('rejected', f"{label} rejected the post: {msg}", msg, platform=platform)


def _google(r, platform):
    if r.status_code < 300:
        return rjson(r)
    raise sa.google_error(r, platform)


_TIKTOK_PERMANENT = {
    'spam_risk_too_many_posts': ('tiktok_daily_limit', 'TikTok daily post limit reached for this account.'),
    'spam_risk_user_banned_from_posting': ('tiktok_banned', 'TikTok does not allow this account to post right now.'),
    'reached_active_user_cap': ('tiktok_app_cap', "BitPaw's TikTok app reached TikTok's daily user cap — try tomorrow."),
    'unaudited_client_can_only_post_to_private_accounts': ('tiktok_unaudited_private',
                                                           "Until TikTok audits BitPaw's app, only 'Only me' posts are allowed."),
    'privacy_level_option_mismatch': ('tiktok_privacy_unavailable', 'That TikTok privacy option is not available for this account.'),
    'url_ownership_unverified': ('tiktok_url_unverified', 'TikTok could not verify the video address.'),
}


def _tiktok(r):
    j = rjson(r)
    e = j.get('error') if isinstance(j.get('error'), dict) else {}
    code = e.get('code') or ('ok' if r.status_code < 300 else f'http_{r.status_code}')
    if code == 'ok' and r.status_code < 300:
        return j.get('data') or {}
    msg = e.get('message') or f"HTTP {r.status_code}"
    if code in ('access_token_invalid', 'scope_not_authorized', 'scope_permission_missed') or r.status_code == 401:
        raise SocialError('token_invalid', 'TikTok access expired or lacks a permission — reconnect TikTok.', msg,
                          reconnect=True, platform='tiktok')
    if code in ('rate_limit_exceeded', 'internal_error') or r.status_code == 429 or r.status_code >= 500:
        raise SocialError('provider_busy', 'TikTok is busy or rate-limited — will retry.', msg, transient=True, platform='tiktok')
    if code in _TIKTOK_PERMANENT:
        c, m = _TIKTOK_PERMANENT[code]
        raise SocialError(c, m, msg, platform='tiktok')
    raise SocialError('rejected', f"TikTok rejected the post: {msg}", msg, platform='tiktok')


# ---------------------------------------------------------------- bối cảnh 1 lần đăng
def _native_window(platform, target, sched, now):
    """Giờ hẹn nằm trong khung nền tảng TỰ đăng đúng giờ? (Meta 12 phút–29 ngày; YouTube 15 phút–60 ngày và chỉ khi video để
    công khai — publishAt luôn biến video thành công khai, sẽ bỏ qua lựa chọn 'unlisted'/'private' của chủ tiệm.)"""
    if platform not in PREPUSH or not sched:
        return None
    if platform == 'youtube' and ((target or {}).get('options') or {}).get('privacy_status') not in (None, '', 'public'):
        return None
    lo, hi = PREPUSH[platform]
    return sched if now + lo <= sched <= now + hi else None


class _LeaseLost(Exception):
    """Mất khoá thuê giữa chừng (máy khác đã nhận bài) — dừng ngay, không gọi nền tảng nữa."""


class _Ctx:
    def __init__(self, post, target, account, token, now, phase='due', save=None):
        self.post, self.target, self.account, self.token, self.now = post, target, account, token, now
        self.platform = target['platform']
        self.options = target.get('options') or {}
        self.media = (post.get('media') or [None])[0]
        self.media_type = post.get('media_type') or 'text'
        self.scheduled_at = as_utc(post.get('scheduled_at'))
        self.phase, self._save, self.sent = phase, save, False
        self._bytes = None

    def checkpoint(self, fields):
        """Ghi NGAY trạng thái đích vào DB trước 1 bước không làm lại được (máy chết giữa chừng thì lần sau biết)."""
        if self._save is not None and not self._save(fields):
            raise _LeaseLost()
        if fields.get('status') != 'sending':
            self.target.update(fields)

    def create(self, method, url, **kw):
        """Gọi lệnh TẠO bài công khai (không lặp lại được). Ghi 'sending' trước; mất phản hồi sau khi đã gửi (hết giờ chờ,
        đứt kết nối) -> 'publish_uncertain': KHÔNG tự gửi lại — bài có thể đã lên, gửi nữa là thành 2 bài."""
        self.checkpoint({'status': 'sending', 'sending_since': self.now})
        try:
            r = http(method, url, **kw)
        except SocialError as e:
            if e.ambiguous:
                raise SocialError('publish_uncertain', UNCERTAIN_MSG.format(p=sa.LABELS[self.platform]), str(e)[:200],
                                  platform=self.platform)
            raise
        self.sent = True
        return r

    def caption(self):
        return caption_for(self.post, self.platform)

    def media_bytes(self):
        if self._bytes is None:
            import media_store
            g = media_store.get(self.media['file_id'], self.post['business_id'])
            if g is None:
                raise SocialError('media_missing', 'The photo/video of this post was deleted from the library.', platform=self.platform)
            self._bytes = g.read()
        return self._bytes

    def media_url(self):
        return media_url(self.media, absolute=True)

    def filename(self):
        return f"bitpaw-{self.post['id']}.{_EXT.get(self.media['content_type'], 'bin')}"

    def native_at(self, platform):
        return _native_window(platform, self.target, self.scheduled_at, self.now)

    def media_size(self):
        return int((self.media or {}).get('size') or 0)


def _skip(code, message=None):
    return {'status': 'skipped', 'error': {'code': code, 'message': message or SKIP_MESSAGES.get(code, code)}}


def _fail(code, message):
    return {'status': 'failed', 'error': {'code': code, 'message': message}}


def _still_processing(ctx, every=timedelta(minutes=1)):
    since = as_utc(ctx.target.get('processing_since')) or ctx.now
    if ctx.now - since > PROCESSING_TIMEOUT:
        return _fail(f"{ctx.platform}_processing_timeout", f"{sa.LABELS[ctx.platform]} kept processing the video for over an hour.")
    return {'status': 'processing', 'next_attempt_at': ctx.now + every}


def _with_link(msg, link):
    return f"{msg}\n{link}".strip() if link and link not in msg else msg


# ---------------------------------------------------------------- Facebook Page
def _fb_permalink(path_or_url):
    if not path_or_url:
        return None
    return path_or_url if path_or_url.startswith('http') else 'https://www.facebook.com' + path_or_url


def _fb_publish(ctx):
    page, tok, link = ctx.account['external_id'], ctx.token, ctx.post.get('link')
    native = ctx.native_at('facebook')
    if ctx.phase == 'prepush' and not native:
        return None   # ngoài khung Meta tự đăng: KHÔNG đăng ngay — đợi tới giờ hẹn
    if ctx.media_type == 'image':
        code = _media_problem('facebook', 'image', ctx.media.get('content_type'), ctx.media_size())
        if code and code not in NOTE_ONLY:
            return _skip(code, _media_message(code, 'facebook', ctx.media_size()))
    msg = ctx.caption()
    sched = {'published': 'false', 'scheduled_publish_time': str(int(native.timestamp()))} if native else {}
    base = f"{sa.META_API}/{GRAPH_V}/{page}"
    if ctx.media_type == 'video':
        r = ctx.create('POST', f"{sa.META_VIDEO_API}/{GRAPH_V}/{page}/videos",
                       data={'description': _with_link(msg, link), 'title': (ctx.post.get('title') or '')[:100], 'access_token': tok,
                             **sched},
                       files={'source': (ctx.filename(), ctx.media_bytes(), ctx.media['content_type'])}, timeout=UPLOAD_TIMEOUT)
        vid = str(_meta(r, 'facebook').get('id') or '')
        out = {'remote_id': vid, 'remote_kind': 'video', 'permalink': f"https://www.facebook.com/{page}/videos/{vid}"}
    elif ctx.media_type == 'image':
        src = {'source': (ctx.filename(), ctx.media_bytes(), ctx.media['content_type'])}
        if native:
            # bài ảnh hẹn giờ: tải ảnh lên dạng tạm (chưa đăng) rồi tạo bài /feed hẹn giờ gắn ảnh đó (cách Meta hướng dẫn)
            r = http('POST', f"{base}/photos", data={'published': 'false', 'temporary': 'true', 'access_token': tok},
                     files=src, timeout=UPLOAD_TIMEOUT)
            photo_id = _meta(r, 'facebook').get('id')
            r = ctx.create('POST', f"{base}/feed", data={'message': _with_link(msg, link), 'access_token': tok, **sched,
                                                        'attached_media': json.dumps([{'media_fbid': str(photo_id)}])})
            pid = str(_meta(r, 'facebook').get('id') or '')
        else:
            r = ctx.create('POST', f"{base}/photos", data={'caption': _with_link(msg, link), 'access_token': tok}, files=src,
                           timeout=UPLOAD_TIMEOUT)
            j = _meta(r, 'facebook')
            pid = str(j.get('post_id') or j.get('id') or '')
        out = {'remote_id': pid, 'remote_kind': 'post', 'permalink': f"https://www.facebook.com/{pid}"}
    else:
        data = {'message': msg, 'access_token': tok, **sched}
        if link:
            data['link'] = link
        pid = str(_meta(ctx.create('POST', f"{base}/feed", data=data), 'facebook').get('id') or '')
        out = {'remote_id': pid, 'remote_kind': 'post', 'permalink': f"https://www.facebook.com/{pid}"}
    if native:
        return {'status': 'scheduled_remote', **out, 'next_attempt_at': native + timedelta(minutes=2)}
    return {'status': 'published', **out}


def _fb_check(ctx):
    t = ctx.target
    fields = 'published,permalink_url' if t.get('remote_kind') == 'video' else 'is_published,permalink_url'
    j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{t['remote_id']}", params={'fields': fields, 'access_token': ctx.token}), 'facebook')
    if j.get('is_published', j.get('published')):
        out = {'status': 'published', 'published_at': min(ctx.scheduled_at or ctx.now, ctx.now)}
        if j.get('permalink_url'):
            out['permalink'] = _fb_permalink(j['permalink_url'])
        return out
    if ctx.scheduled_at and ctx.now > ctx.scheduled_at + timedelta(hours=2):
        return _fail('fb_not_published', 'Facebook did not publish the scheduled post on time — check it in Meta Business Suite.')
    return {'status': 'scheduled_remote', 'next_attempt_at': ctx.now + timedelta(minutes=5)}


def _fb_unschedule(target, token):
    _meta(http('DELETE', f"{sa.META_API}/{GRAPH_V}/{target['remote_id']}", params={'access_token': token}), 'facebook')


# ---------------------------------------------------------------- Instagram
def _ig_upload_url(uri, cid):
    """Link tải byte của container Reels. Chỉ dùng link Meta trả về khi nó đúng host rupload đã cấu hình (token đi kèm không
    bao giờ gửi tới host lạ); còn lại tự ghép theo tài liệu Meta: {rupload}/ig-api-upload/{version}/{container}."""
    if isinstance(uri, str) and uri.startswith(sa.META_RUPLOAD + '/'):
        return uri
    return f"{sa.META_RUPLOAD}/ig-api-upload/{GRAPH_V}/{cid}"


def _rupload(r):
    j = rjson(r)
    if r.status_code < 300 and j.get('success', True) is not False:
        return j
    info = j.get('debug_info') if isinstance(j.get('debug_info'), dict) else {}
    err = j.get('error') if isinstance(j.get('error'), dict) else {}
    msg = info.get('message') or err.get('message') or f"HTTP {r.status_code}"
    if r.status_code == 401 or err.get('code') == 190 or info.get('type') == 'OAuthException':
        raise SocialError('token_invalid', 'The Instagram access token is invalid or has expired — reconnect Instagram.', msg,
                          reconnect=True, platform='instagram')
    if r.status_code >= 500 or r.status_code == 429 or info.get('retriable'):
        raise SocialError('provider_busy', 'Instagram is busy — will retry.', msg, transient=True, platform='instagram')
    raise SocialError('ig_upload_failed', f"Instagram did not accept the video upload: {msg}", msg, platform='instagram')


def _ig_publish(ctx):
    ct, size = (ctx.media or {}).get('content_type'), ctx.media_size()
    code = _media_problem('instagram', ctx.media_type, ct, size)
    if code == 'media_too_large':
        # Instagram tải ảnh qua link không kèm Range: ảnh lớn hơn 1 response Vercel = ảnh cụt -> không gửi
        return _fail(code, _media_message(code, 'instagram', size))
    if code:
        return _skip(code)
    base = f"{sa.META_API}/{GRAPH_V}/{ctx.account['external_id']}"
    if ctx.media_type == 'image':
        r = http('POST', f"{base}/media", data={'image_url': ctx.media_url(), 'caption': ctx.caption(), 'access_token': ctx.token})
        cid = str(_meta(r, 'instagram').get('id') or '')
        if not cid:
            raise SocialError('provider_busy', 'Instagram did not create the post container — will retry.', transient=True,
                              platform='instagram')
        # lưu container TRƯỚC media_publish: mất phản hồi lúc đăng thì lần sau hỏi trạng thái container (PUBLISHED = đã lên)
        # thay vì tạo container mới và đăng ảnh lần 2
        ctx.checkpoint({'status': 'processing', 'container_id': cid, 'processing_since': ctx.now, 'next_attempt_at': ctx.now})
        return _ig_finish(ctx, cid)
    # Reels: tải thẳng byte lên Instagram (upload_type=resumable) — không nhờ Instagram tải link /m/ của BitPaw (Vercel chỉ trả
    # vài MB/response, Instagram tải link không kèm Range nên video lớn sẽ bị cụt)
    r = http('POST', f"{base}/media", data={'media_type': 'REELS', 'upload_type': 'resumable', 'caption': ctx.caption(),
                                           'share_to_feed': 'true', 'access_token': ctx.token})
    j = _meta(r, 'instagram')
    cid = str(j.get('id') or '')
    if not cid:
        raise SocialError('provider_busy', 'Instagram did not create the video container — will retry.', transient=True,
                          platform='instagram')
    data = ctx.media_bytes()
    _rupload(http('POST', _ig_upload_url(j.get('uri'), cid), data=data, timeout=UPLOAD_TIMEOUT,
                  headers={'Authorization': f'OAuth {ctx.token}', 'offset': '0', 'file_size': str(len(data))}))
    return {'status': 'processing', 'container_id': cid, 'processing_since': ctx.now, 'next_attempt_at': ctx.now + timedelta(seconds=30)}


def _ig_finish(ctx, cid):
    base = f"{sa.META_API}/{GRAPH_V}/{ctx.account['external_id']}"
    # Instagram giới hạn số bài đăng qua API / 24 giờ: hết lượt thì bỏ qua và nói rõ, không cố đăng để bị lỗi
    j = _meta(http('GET', f"{base}/content_publishing_limit", params={'fields': 'quota_usage,config', 'access_token': ctx.token}), 'instagram')
    row = ((j.get('data') or [{}])[0]) or {}
    usage, cfg = row.get('quota_usage'), row.get('config') or {}
    total = cfg.get('quota_total') or cfg.get('total')
    if isinstance(usage, (int, float)) and total and usage >= total:
        return _skip('ig_daily_limit', f"Instagram allows {total} posts per 24 hours from apps — the limit is reached, so this post was not sent.")
    try:
        mid = str(_meta(http('POST', f"{base}/media_publish", data={'creation_id': cid, 'access_token': ctx.token}), 'instagram').get('id') or '')
    except SocialError as e:
        if e.code == 'ig_not_ready':
            return {'status': 'processing', 'container_id': cid, 'processing_since': ctx.target.get('processing_since') or ctx.now,
                    'next_attempt_at': ctx.now + timedelta(minutes=1)}
        raise
    out = {'status': 'published', 'remote_id': mid, 'container_id': cid}
    try:
        r = http('GET', f"{sa.META_API}/{GRAPH_V}/{mid}", params={'fields': 'permalink', 'access_token': ctx.token}, timeout=8)
        if r.status_code < 300 and rjson(r).get('permalink'):
            out['permalink'] = rjson(r)['permalink']
    except SocialError:
        pass
    return out


def _ig_check(ctx):
    cid = ctx.target.get('container_id')
    j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{cid}", params={'fields': 'status_code,status', 'access_token': ctx.token}), 'instagram')
    sc = j.get('status_code')
    if sc == 'FINISHED':
        return _ig_finish(ctx, cid)
    if sc == 'PUBLISHED':
        return {'status': 'published'}   # lần trước đã đăng nhưng mất phản hồi — không đăng lần 2
    if sc in ('ERROR', 'EXPIRED'):
        return _fail('ig_media_error', f"Instagram could not process the video: {j.get('status') or sc}")
    return _still_processing(ctx)


# ---------------------------------------------------------------- YouTube
def _yt_publish(ctx):
    if ctx.media_type != 'video':
        return _skip('youtube_needs_video')
    native = ctx.native_at('youtube')   # None khi chủ tiệm chọn 'unlisted'/'private' (publishAt sẽ biến video thành công khai)
    if ctx.phase == 'prepush' and not native:
        return None   # ngoài khung YouTube tự đăng: KHÔNG tải lên công khai ngay — đợi tới giờ hẹn
    data, ct = ctx.media_bytes(), ctx.media['content_type']
    caption = ctx.caption()
    title = re.sub(r'[<>]', '', (ctx.post.get('title') or caption.split('\n')[0] or 'Video'))[:90].strip() or 'Video'
    tags, total = [], 0
    for h in ctx.post.get('hashtags') or []:
        if len(tags) >= 15 or total + len(h) > 450:
            break
        tags.append(h)
        total += len(h) + 1
    status = {'privacyStatus': 'private' if native else ctx.options.get('privacy_status') or 'public',
              'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': bool(ctx.post.get('is_ai_generated'))}
    if native:
        status['publishAt'] = iso_z(native)   # YouTube tự chuyển công khai đúng giờ (video phải để private tới lúc đó)
    # YouTube giới hạn mô tả 5000 BYTE (không phải ký tự): cắt theo byte UTF-8 để chữ có dấu không làm hỏng lần tải
    body = {'snippet': {'title': title, 'description': _cut_bytes(re.sub(r'[<>]', '', caption), YT_DESC_BYTES), 'tags': tags,
                        'categoryId': '22'},
            'status': status}
    hdr = {'Authorization': f'Bearer {ctx.token}'}
    r = http('POST', f"{sa.GOOGLE_API}/upload/youtube/v3/videos", params={'uploadType': 'resumable', 'part': 'snippet,status'},
             json=body, headers={**hdr, 'Content-Type': 'application/json; charset=UTF-8', 'X-Upload-Content-Length': str(len(data)),
                                 'X-Upload-Content-Type': ct})
    _google(r, 'youtube')
    loc = r.headers.get('Location')
    if not loc:
        raise SocialError('provider_busy', 'YouTube did not open an upload session — will retry.', transient=True, platform='youtube')
    r = ctx.create('PUT', loc, data=data, headers={**hdr, 'Content-Type': ct}, timeout=UPLOAD_TIMEOUT)
    j = _google(r, 'youtube')
    vid = j.get('id')
    if not vid:
        # tải xong (2xx) mà không có id: video có thể đã nằm trên kênh — không tự tải lại thành 2 video
        raise SocialError('publish_uncertain', UNCERTAIN_MSG.format(p='YouTube'), 'upload finished without a video id',
                          platform='youtube')
    out = {'remote_id': vid, 'permalink': f"https://youtu.be/{vid}", 'visibility': (j.get('status') or {}).get('privacyStatus')}
    if native:
        return {'status': 'scheduled_remote', **out, 'next_attempt_at': native + timedelta(minutes=3)}
    return {'status': 'published', **out}


def _yt_check(ctx):
    j = _google(http('GET', f"{sa.GOOGLE_API}/youtube/v3/videos", params={'part': 'status', 'id': ctx.target['remote_id']},
                     headers={'Authorization': f'Bearer {ctx.token}'}), 'youtube')
    items = j.get('items') or []
    if not items:
        return _fail('youtube_video_missing', 'The video is no longer on YouTube (deleted or rejected).')
    st = items[0].get('status') or {}
    if st.get('uploadStatus') in ('failed', 'rejected'):
        return _fail('youtube_rejected', f"YouTube rejected the video: {st.get('rejectionReason') or st.get('failureReason') or st['uploadStatus']}")
    # quá giờ hẹn: YouTube đã xử lý; 'private' nghĩa là app chưa được Google duyệt (ghi rõ trong visibility)
    return {'status': 'published', 'visibility': st.get('privacyStatus'), 'published_at': min(ctx.scheduled_at or ctx.now, ctx.now)}


def _yt_unschedule(target, token):
    r = http('DELETE', f"{sa.GOOGLE_API}/youtube/v3/videos", params={'id': target['remote_id']}, headers={'Authorization': f'Bearer {token}'})
    if r.status_code != 404:
        _google(r, 'youtube')


# ---------------------------------------------------------------- TikTok (Content Posting API — Direct Post)
def _mp4_duration(data):
    """Thời lượng (giây) đọc từ hộp mvhd của MP4 — không cần thư viện. Kiểm tra kích thước hộp để không đọc nhầm dữ liệu
    video ngẫu nhiên có chứa chữ 'mvhd'."""
    start = 0
    for _ in range(8):
        i = data.find(b'mvhd', start)
        if i < 4:
            return None
        size = struct.unpack('>I', data[i - 4:i])[0]
        try:
            if data[i + 4] == 0 and size == 108:
                ts, du = struct.unpack('>II', data[i + 16:i + 24])
                return du / ts if ts else None
            if data[i + 4] == 1 and size == 120:
                ts, du = struct.unpack('>IQ', data[i + 24:i + 36])
                return du / ts if ts else None
        except (IndexError, struct.error):
            return None
        start = i + 4
    return None


def _tt_publish(ctx):
    if ctx.media_type != 'video':
        return _skip('tiktok_needs_video')
    o = ctx.options
    miss = _tiktok_missing(o)
    if miss:
        return _fail('tiktok_options_required', 'TikTok settings (who can see it, comments/duet/stitch, branded content) were not chosen.')
    hdr = {'Authorization': f'Bearer {ctx.token}', 'Content-Type': 'application/json; charset=UTF-8'}
    info = _tiktok(http('POST', f"{sa.TIKTOK_API}/v2/post/publish/creator_info/query/", json={}, headers=hdr))
    if info.get('privacy_level_options') and o['privacy_level'] not in info['privacy_level_options']:
        return _fail('tiktok_privacy_unavailable', 'That TikTok privacy option is not available for this account right now.')
    data, ct = ctx.media_bytes(), ctx.media['content_type']
    n = len(data)
    max_sec = info.get('max_video_post_duration_sec')
    dur = _mp4_duration(data) if ct == 'video/mp4' else None
    if dur and max_sec and dur > max_sec + 0.5:
        return _fail('tiktok_too_long', f"TikTok allows videos up to {max_sec} seconds for this account.")
    post_info = {'title': ctx.caption(), 'privacy_level': o['privacy_level'],
                 # tài khoản tự tắt bình luận/duet/stitch trong app TikTok thì luôn giữ tắt
                 'disable_comment': bool(o['disable_comment'] or info.get('comment_disabled')),
                 'disable_duet': bool(o['disable_duet'] or info.get('duet_disabled')),
                 'disable_stitch': bool(o['disable_stitch'] or info.get('stitch_disabled')),
                 'brand_content_toggle': bool(o['brand_content_toggle']), 'brand_organic_toggle': bool(o['brand_organic_toggle']),
                 'is_aigc': bool(ctx.post.get('is_ai_generated'))}
    init = _tiktok(http('POST', f"{sa.TIKTOK_API}/v2/post/publish/video/init/", headers=hdr,
                        json={'post_info': post_info, 'source_info': {'source': 'FILE_UPLOAD', 'video_size': n, 'chunk_size': n,
                                                                      'total_chunk_count': 1}}))
    publish_id, upload_url = init.get('publish_id'), init.get('upload_url')
    if not publish_id or not upload_url:
        raise SocialError('provider_busy', 'TikTok did not open an upload — will retry.', transient=True, platform='tiktok')
    r = ctx.create('PUT', upload_url, data=data, headers={'Content-Range': f'bytes 0-{n - 1}/{n}', 'Content-Type': ct,
                                                           'Content-Length': str(n)}, timeout=UPLOAD_TIMEOUT)
    if r.status_code >= 500:
        raise SocialError('provider_busy', 'TikTok upload failed — will retry.', f"HTTP {r.status_code}", transient=True, platform='tiktok')
    if r.status_code >= 300:
        return _fail('tiktok_upload_failed', f"TikTok did not accept the video upload (HTTP {r.status_code}).")
    return {'status': 'processing', 'container_id': publish_id, 'creator_username': info.get('creator_username'),
            'processing_since': ctx.now, 'next_attempt_at': ctx.now + timedelta(seconds=30)}


def tiktok_creator_info(business_id):
    """Quy định Direct Post của TikTok: màn soạn bài phải hiện tên tài khoản + đúng các lựa chọn quyền riêng tư TikTok trả
    về (và khoá bình luận/duet/stitch nếu tài khoản đã tắt trong app). Gọi khi chủ tiệm bật TikTok trong màn soạn bài."""
    acc = sa.get_account(business_id, 'tiktok')
    if not acc or acc.get('status') != 'connected':
        raise SocialError('not_connected', 'TikTok is not connected.', platform='tiktok')
    try:
        tok = sa.access_token(acc)
        d = _tiktok(http('POST', f"{sa.TIKTOK_API}/v2/post/publish/creator_info/query/", json={},
                         headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json; charset=UTF-8'}))
    except SocialError as e:
        if e.reconnect:
            sa.mark_needs_reconnect(business_id, 'tiktok', e)
        raise
    keys = ('creator_nickname', 'creator_username', 'creator_avatar_url', 'privacy_level_options', 'comment_disabled',
            'duet_disabled', 'stitch_disabled', 'max_video_post_duration_sec')
    return {k: d.get(k) for k in keys if k in d}


def _tt_status(token, publish_id):
    return _tiktok(http('POST', f"{sa.TIKTOK_API}/v2/post/publish/status/fetch/", json={'publish_id': publish_id},
                        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=UTF-8'}))


def _tt_post_ids(d):
    # TikTok viết sai chính tả 'publicaly' trong API thật — đọc cả 2 cách
    return d.get('publicaly_available_post_id') or d.get('publicly_available_post_id') or []


def _tt_ids(target, ids):
    out = {'remote_id': str(ids[0]), 'needs_post_id': False}
    if target.get('creator_username'):
        out['permalink'] = f"https://www.tiktok.com/@{target['creator_username']}/video/{ids[0]}"
    return out


def _tt_check(ctx):
    d = _tt_status(ctx.token, ctx.target.get('container_id'))
    s = d.get('status')
    if s == 'PUBLISH_COMPLETE':
        ids = _tt_post_ids(d)
        out = {'status': 'published'}
        if ids:
            out.update(_tt_ids(ctx.target, ids))
        elif ctx.options.get('privacy_level') != 'SELF_ONLY':
            # TikTok chỉ trả id bài công khai SAU kiểm duyệt (vài phút–vài giờ): sync_metrics hỏi lại tới 48 giờ để có link + số
            out.update(needs_post_id=True, post_id_until=ctx.now + TT_POST_ID_WINDOW)
        return out
    if s == 'FAILED':
        return _fail('tiktok_failed', f"TikTok could not publish the video: {d.get('fail_reason') or 'unknown reason'}")
    return _still_processing(ctx)


# ---------------------------------------------------------------- Google Business Profile
def _gbp_publish(ctx):
    code = _media_problem('google_business', ctx.media_type, (ctx.media or {}).get('content_type'), ctx.media_size())
    if code == 'media_too_large':
        # Google tải ảnh qua link (không kèm Range): ảnh lớn hơn 1 response Vercel = ảnh cụt -> không gửi
        return _fail(code, _media_message(code, 'google_business', ctx.media_size()))
    if code:
        return _skip(code)
    body = {'languageCode': sa.shop_language(ctx.post['business_id']), 'summary': ctx.caption()[:1500], 'topicType': 'STANDARD'}
    link = None
    try:
        from ai_nurturing_engine import AINurturingEngine
        link = AINurturingEngine.booking_link(ctx.post['business_id'], sa.business_industry(ctx.post['business_id']), sa.public_base())
    except Exception:
        link = None
    if link:
        body['callToAction'] = {'actionType': 'BOOK', 'url': link}
    elif ctx.post.get('link'):
        body['callToAction'] = {'actionType': 'LEARN_MORE', 'url': ctx.post['link']}
    if ctx.media_type == 'image':
        body['media'] = [{'mediaFormat': 'PHOTO', 'sourceUrl': ctx.media_url()}]
    j = _google(ctx.create('POST', f"{sa.GBP_API}/v4/{ctx.account['external_id']}/localPosts", json=body,
                           headers={'Authorization': f'Bearer {ctx.token}'}), 'google_business')
    return _gbp_state(ctx, j)


def _gbp_state(ctx, j):
    state, name = j.get('state'), j.get('name') or ctx.target.get('container_id')
    if state == 'REJECTED':
        return _fail('gbp_rejected', 'Google rejected this post (it may break the Business Profile content policy).')
    out = {'remote_id': name, 'container_id': name}
    if j.get('searchUrl'):
        out['permalink'] = j['searchUrl']
    if state == 'PROCESSING':
        return {**out, 'status': 'processing', 'processing_since': ctx.target.get('processing_since') or ctx.now,
                'next_attempt_at': ctx.now + timedelta(minutes=1)}
    return {**out, 'status': 'published'}


def _gbp_check(ctx):
    j = _google(http('GET', f"{sa.GBP_API}/v4/{ctx.target['container_id']}", headers={'Authorization': f'Bearer {ctx.token}'}),
                'google_business')
    res = _gbp_state(ctx, j)
    return _still_processing(ctx) if res['status'] == 'processing' else res


def _no_unschedule(target, token):
    return None


ADAPTERS = {
    'facebook': {'publish': _fb_publish, 'check': _fb_check, 'unschedule': _fb_unschedule},
    'instagram': {'publish': _ig_publish, 'check': _ig_check, 'unschedule': _no_unschedule},
    'youtube': {'publish': _yt_publish, 'check': _yt_check, 'unschedule': _yt_unschedule},
    'tiktok': {'publish': _tt_publish, 'check': _tt_check, 'unschedule': _no_unschedule},
    'google_business': {'publish': _gbp_publish, 'check': _gbp_check, 'unschedule': _no_unschedule},
}


# ---------------------------------------------------------------- engine
def _scope(business_id, post_id):
    q = dict(_world())
    if business_id is not None:
        q['business_id'] = business_id
    elif sa.test_mode():
        q['business_id'] = {'$in': sorted(sa.test_business_ids())}
    if post_id is not None:
        q['id'] = post_id
    return q


def _claim(scope, now, worker, phase):
    """Nhận 1 bài (khoá thuê LEASE). Trả doc TRƯỚC khi nhận (để biết trạng thái cũ) hoặc None."""
    open_due = {'status': {'$in': list(OPEN_T)}, '$or': [{'next_attempt_at': None}, {'next_attempt_at': {'$lte': now}}]}
    if phase == 'due':
        cond = {'$or': [{'status': 'scheduled', 'scheduled_at': {'$lte': now}},
                        {'status': {'$in': ['publishing', 'partial']}, 'targets': {'$elemMatch': open_due}}]}
        upd = {'status': 'publishing', 'lease_owner': worker, 'lease_until': now + LEASE, 'updated_at': now}
    else:
        ors = []
        for p, (lo, hi) in PREPUSH.items():
            em = {'platform': p, 'status': 'pending', '$or': [{'next_attempt_at': None}, {'next_attempt_at': {'$lte': now}}]}
            if p == 'youtube':
                em['options.privacy_status'] = {'$in': [None, '', 'public']}   # khớp _native_window (không nhận lại mãi)
            ors.append({'scheduled_at': {'$gte': now + lo, '$lte': now + hi}, 'targets': {'$elemMatch': em}})
        cond = {'status': 'scheduled', '$or': ors}
        upd = {'lease_owner': worker, 'lease_until': now + LEASE}
    return db.social_posts.find_one_and_update({'$and': [scope, cond, _lease_free(now)]}, {'$set': upd},
                                               sort=[('scheduled_at', 1)], projection={'_id': 0},
                                               return_document=ReturnDocument.BEFORE)


def _extend_lease(post_id, worker, now):
    until = max(now, utcnow()) + LEASE
    return db.social_posts.update_one({'id': post_id, 'lease_owner': worker}, {'$set': {'lease_until': until}}).matched_count == 1


def _stamp(now):
    # updated_at là "phiên bản" để màn sửa/huỷ biết bài vừa đổi — luôn tiến lên (now của cron có thể là mốc cũ)
    return max(now, utcnow())


def _save_target(post_id, idx, fields, worker, now):
    upd = {f'targets.{idx}.{k}': v for k, v in fields.items()}
    upd['updated_at'] = _stamp(now)
    return db.social_posts.update_one({'id': post_id, 'lease_owner': worker}, {'$set': upd}).matched_count == 1


def _final_status(targets):
    sts = [t.get('status') for t in targets]
    if any(s in OPEN_T for s in sts):
        return 'publishing'
    if sts and all(s == 'published' for s in sts):
        return 'published'
    if any(s == 'published' for s in sts):
        return 'partial'   # có nơi lên, có nơi lỗi/bị bỏ qua — nói đúng là "một phần"
    return 'failed'


def _run_target(post, target, now, phase='due', save=None):
    """Chạy 1 đích. Trả field cần ghi, hoặc None = không làm gì lượt này (vd ngoài khung tự đăng khi đẩy trước).
    save(fields): ghi ngay vào DB giữa chừng (checkpoint) — dùng trước lệnh tạo bài."""
    platform, bid = target['platform'], post['business_id']
    attempts = int(target.get('attempts') or 0)
    ctx = None
    try:
        acc = sa.get_account(bid, platform)
        if not acc:
            raise SocialError('not_connected', f"{sa.LABELS[platform]} is not connected.", platform=platform)
        if acc.get('status') == 'needs_reconnect':
            raise SocialError('needs_reconnect', f"{sa.LABELS[platform]} needs to be reconnected.", platform=platform)
        if sa.needs_location(acc):
            raise SocialError('needs_location', 'Choose which Google Business Profile location to post to (Accounts tab).',
                              platform=platform)
        ctx = _Ctx(post, target, acc, sa.access_token(acc), now, phase, save)
        res = ADAPTERS[platform]['publish' if target.get('status') == 'pending' else 'check'](ctx)
        if res is None:
            return None
        if res.get('error'):
            res['error'] = {**res['error'], 'at': now}
        else:
            res['error'] = None
        if res['status'] == 'published':
            res.setdefault('published_at', now)
            res['next_attempt_at'] = None
        return res
    except SocialError as e:
        err = {'code': e.code, 'message': str(e)[:300], 'at': now}
        if e.reconnect:
            sa.mark_needs_reconnect(bid, platform, e)
            return {'status': 'failed', 'error': err, 'next_attempt_at': None}
        if e.transient:
            attempts += 1
            if attempts >= MAX_ATTEMPTS:
                return {'status': 'failed', 'attempts': attempts, 'error': err, 'next_attempt_at': None}
            return {'status': target.get('status') or 'pending', 'attempts': attempts, 'error': err,
                    'next_attempt_at': now + timedelta(minutes=2 ** attempts)}
        return {'status': 'failed', 'error': err, 'next_attempt_at': None}
    except _LeaseLost:
        raise
    except Exception as e:   # lỗi ngoài dự kiến: không để bài kẹt mãi — tính như lỗi tạm, hết lượt thì báo lỗi
        print(f"[social] {platform} post {post.get('id')}: {e!r}")
        if ctx is not None and ctx.sent:
            # lệnh tạo bài đã gửi xong rồi mới lỗi: có thể đã lên — không tự gửi lại
            return {'status': 'failed', 'next_attempt_at': None,
                    'error': {'code': 'publish_uncertain', 'message': UNCERTAIN_MSG.format(p=sa.LABELS[platform]), 'at': now}}
        attempts += 1
        err = {'code': 'internal', 'message': 'Unexpected error while posting.', 'at': now}
        if attempts >= MAX_ATTEMPTS:
            return {'status': 'failed', 'attempts': attempts, 'error': err, 'next_attempt_at': None}
        return {'status': target.get('status') or 'pending', 'attempts': attempts, 'error': err,
                'next_attempt_at': now + timedelta(minutes=2 ** attempts)}


def _process(doc, now, worker, phase, stats, deadline_at):
    pid = doc['id']
    sched = as_utc(doc.get('scheduled_at'))
    stale = phase == 'due' and doc.get('status') == 'scheduled' and sched and now - sched > STALE_AFTER
    targets = doc.get('targets') or []
    for idx, t in enumerate(targets):
        st = t.get('status')
        if st not in OPEN_T:
            continue
        if phase == 'prepush' and (st != 'pending' or not _native_window(t['platform'], t, sched, now)):
            # bài được nhận vì khung của NỀN TẢNG KHÁC: đích này ngoài khung tự đăng của mình -> đợi tới giờ, không đăng sớm
            continue
        nxt = as_utc(t.get('next_attempt_at'))
        if nxt and nxt > now:
            continue
        if deadline_at and time.monotonic() > deadline_at:
            break
        if deadline_at and st == 'pending' and doc.get('media_type') == 'video' and deadline_at - time.monotonic() < VIDEO_START_MIN:
            break   # sắp hết giờ chạy: không bắt đầu tải video (bị tắt giữa chừng = không biết đã lên chưa) — để lượt sau
        if st == 'sending':
            # máy trước chết giữa lệnh tạo bài (hết hạn thuê): bài có thể đã lên — không gửi lại, báo chủ tiệm kiểm tra
            fields = {'status': 'failed', 'next_attempt_at': None,
                      'error': {'code': 'publish_uncertain', 'message': UNCERTAIN_MSG.format(p=sa.LABELS[t['platform']]), 'at': now}}
        elif stale and st == 'pending' and not t.get('attempts'):
            fields = {'status': 'failed', 'next_attempt_at': None,
                      'error': {'code': 'missed_time', 'message': 'Not sent: it was more than 24 hours past the scheduled time.', 'at': now}}
        else:
            if not _extend_lease(pid, worker, now):
                return
            try:
                fields = _run_target(doc, t, now, phase, lambda f, i=idx: _save_target(pid, i, f, worker, now))
            except _LeaseLost:
                return
            if fields is None:
                continue
        if not _save_target(pid, idx, fields, worker, now):
            return   # mất khoá thuê (quá hạn, máy khác đã nhận) — dừng, không ghi đè
        t.update(fields)
        key = {'published': 'published', 'failed': 'failed', 'skipped': 'skipped', 'processing': 'processing',
               'scheduled_remote': 'processing'}.get(fields['status'], 'retrying')
        stats[key] = stats.get(key, 0) + 1
    rel = {'lease_owner': None, 'lease_until': None, 'updated_at': _stamp(now)}
    if phase == 'due':
        rel['status'] = _final_status(targets)
    db.social_posts.update_one({'id': pid, 'lease_owner': worker}, {'$set': rel})


def run_due(business_id=None, limit=10, now=None, worker=None, post_id=None, deadline=None):
    """Đăng các bài tới giờ (và đẩy trước bài Facebook/YouTube hẹn giờ xa). business_id=None = mọi tiệm (cron):
    chỉ chạy trên production hoặc khi SOCIAL_ALLOW_TICK=1, và luôn theo bộ lọc thử (§0)."""
    stats = {'claimed': 0, 'published': 0, 'failed': 0, 'processing': 0, 'skipped': 0, 'retrying': 0}
    if business_id is None and not sa.tick_allowed():
        stats['blocked'] = 'not_production'
        return stats
    if business_id is not None and not sa.business_allowed(business_id):
        stats['blocked'] = 'test_mode_business'
        return stats
    _ensure_indexes()
    now = as_utc(now) or utcnow()
    worker = worker or f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"
    scope = _scope(business_id, post_id)
    deadline_at = time.monotonic() + deadline if deadline else None
    seen = set()
    for phase in ('due', 'prepush'):
        while stats['claimed'] < limit:
            if deadline_at and time.monotonic() > deadline_at:
                break
            doc = _claim(scope, now, worker, phase)
            if not doc:
                break
            if (phase, doc['id']) in seen:   # chống vòng lặp: bài vừa xử lý mà vẫn khớp điều kiện -> trả khoá, dừng
                db.social_posts.update_one({'id': doc['id'], 'lease_owner': worker},
                                           {'$set': {'lease_owner': None, 'lease_until': None,
                                                     **({'status': _final_status(doc.get('targets') or [])} if phase == 'due' else {})}})
                break
            seen.add((phase, doc['id']))
            stats['claimed'] += 1
            _process(doc, now, worker, phase, stats, deadline_at)
    return stats


# ---------------------------------------------------------------- số liệu THẬT
def _first_value(row):
    vals = row.get('values') or []
    if vals and isinstance(vals[0], dict):
        return vals[0].get('value')
    return (row.get('total_value') or {}).get('value')


def _fb_metrics(acc, tok, t, upd):
    pid = t.get('post_id') or (t['remote_id'] if t.get('remote_kind') != 'video' else None)
    if not pid:
        pid = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{t['remote_id']}", params={'fields': 'post_id', 'access_token': tok}),
                    'facebook').get('post_id')
        if not pid:
            return {}
        upd['post_id'] = pid
    m, errs = {}, []
    try:
        j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{pid}/insights",
                       params={'metric': 'post_media_view,post_total_media_view_unique', 'access_token': tok}), 'facebook')
        for row in j.get('data') or []:
            key = {'post_media_view': 'views', 'post_total_media_view_unique': 'reach'}.get(row.get('name'))
            val = _first_value(row)
            if key and isinstance(val, (int, float)):
                m[key] = int(val)
    except SocialError as e:
        if e.reconnect or e.transient:
            raise
        errs.append(e)
    try:
        j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{pid}",
                       params={'fields': 'likes.summary(true),comments.summary(true),shares', 'access_token': tok}), 'facebook')
    except SocialError as e:
        if e.reconnect or e.transient:
            raise
        errs.append(e)
        j = {}
    for key, field in (('likes', 'likes'), ('comments', 'comments')):
        v = ((j.get(field) or {}).get('summary') or {}).get('total_count')
        if isinstance(v, int):
            m[key] = v
    if isinstance(j.get('shares'), dict) and isinstance(j['shares'].get('count'), int):
        m['shares'] = j['shares']['count']
    if not m and errs:
        raise errs[0]
    return m


def _ig_metrics(acc, tok, t, upd):
    names = {'views': 'views', 'reach': 'reach', 'likes': 'likes', 'comments': 'comments', 'shares': 'shares', 'saved': 'saves'}
    m = {}
    try:
        j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{t['remote_id']}/insights",
                       params={'metric': ','.join(names), 'access_token': tok}), 'instagram')
        for row in j.get('data') or []:
            val = _first_value(row)
            if row.get('name') in names and isinstance(val, (int, float)):
                m[names[row['name']]] = int(val)
    except SocialError as e:
        if e.reconnect or e.transient:
            raise
        # thiếu quyền insights / loại media không hỗ trợ: vẫn lấy được lượt thích + bình luận công khai
        j = _meta(http('GET', f"{sa.META_API}/{GRAPH_V}/{t['remote_id']}",
                       params={'fields': 'like_count,comments_count', 'access_token': tok}), 'instagram')
        if isinstance(j.get('like_count'), int):
            m['likes'] = j['like_count']
        if isinstance(j.get('comments_count'), int):
            m['comments'] = j['comments_count']
    return m


def _yt_metrics(acc, tok, t, upd):
    j = _google(http('GET', f"{sa.GOOGLE_API}/youtube/v3/videos", params={'part': 'statistics', 'id': t['remote_id']},
                     headers={'Authorization': f'Bearer {tok}'}), 'youtube')
    st = ((j.get('items') or [{}])[0] or {}).get('statistics') or {}
    m = {}
    for src, key in (('viewCount', 'views'), ('likeCount', 'likes'), ('commentCount', 'comments')):
        try:
            if st.get(src) is not None:
                m[key] = int(st[src])
        except (TypeError, ValueError):
            pass
    return m


def _tt_metrics(acc, tok, t, upd):
    d = _tiktok(http('POST', f"{sa.TIKTOK_API}/v2/video/query/", params={'fields': 'id,view_count,like_count,comment_count,share_count'},
                     json={'filters': {'video_ids': [t['remote_id']]}},
                     headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json; charset=UTF-8'}))
    v = (d.get('videos') or [{}])[0] or {}
    m = {}
    for src, key in (('view_count', 'views'), ('like_count', 'likes'), ('comment_count', 'comments'), ('share_count', 'shares')):
        if isinstance(v.get(src), int):
            m[key] = v[src]
    return m


METRIC_FETCH = {'facebook': _fb_metrics, 'instagram': _ig_metrics, 'youtube': _yt_metrics, 'tiktok': _tt_metrics}


def _cadence(age):
    if age < timedelta(days=2):
        return timedelta(hours=3)
    if age < timedelta(days=14):
        return timedelta(hours=12)
    return timedelta(hours=48)


def _account_token(bid, p, accounts):
    """(acc, token) dùng chung trong 1 lượt đọc số liệu; lỗi (chưa nối / token hỏng) cũng nhớ để không hỏi lại."""
    key = (bid, p)
    if key not in accounts:
        acc = sa.get_account(bid, p)
        if not acc or acc.get('status') != 'connected':
            accounts[key] = SocialError('not_connected', f"{sa.LABELS[p]} is not connected.", platform=p)
        else:
            try:
                accounts[key] = (acc, sa.access_token(acc))
            except SocialError as e:
                accounts[key] = e
                if e.reconnect:
                    sa.mark_needs_reconnect(bid, p, e)
    if isinstance(accounts[key], SocialError):
        raise accounts[key]
    return accounts[key]


def _tt_resolve_id(tok, t, now):
    """Bài TikTok công khai đã lên nhưng chưa có id (TikTok còn kiểm duyệt): hỏi lại status/fetch.
    Trả field cập nhật (có id -> remote_id + link), {'needs_post_id': False} khi quá 48 giờ (thôi hỏi), hoặc None (hỏi sau)."""
    ids = _tt_post_ids(_tt_status(tok, t.get('container_id')))
    if ids:
        return _tt_ids(t, ids)
    if now > (as_utc(t.get('post_id_until')) or now):
        return {'needs_post_id': False}
    return None


def sync_metrics(business_id=None, max_targets=30, now=None, deadline=None):
    """Đọc số liệu THẬT của bài đã đăng (≤ 60 ngày). Trả số đích đã cập nhật số liệu.
    Bài TikTok công khai chưa có id (đang kiểm duyệt) được hỏi lại id ở đây (≤ 48 giờ) để có link + số liệu."""
    if business_id is None and not sa.tick_allowed():
        return 0
    if business_id is not None and not sa.business_allowed(business_id):
        return 0
    _ensure_indexes()
    now = as_utc(now) or utcnow()
    when = [{'metrics_next_at': None}, {'metrics_next_at': {'$lte': now}}]
    due = {'status': 'published', 'remote_id': {'$nin': [None, '']}, 'platform': {'$in': list(METRIC_PLATFORMS)},
           'metrics_done': {'$ne': True}, '$or': when}
    due_id = {'status': 'published', 'platform': 'tiktok', 'needs_post_id': True, '$or': when}
    q = {'$and': [_scope(business_id, None), {'status': {'$in': ['published', 'partial', 'publishing']}},
                  {'$or': [{'targets': {'$elemMatch': due}}, {'targets': {'$elemMatch': due_id}}]}]}
    done, tried, accounts = 0, 0, {}
    deadline_at = time.monotonic() + deadline if deadline else None
    for post in list(db.social_posts.find(q, {'_id': 0}).sort('scheduled_at', -1).limit(max_targets)):
        bid = post['business_id']
        for idx, t in enumerate(post.get('targets') or []):
            if tried >= max_targets or (deadline_at and time.monotonic() > deadline_at):
                return done
            nxt = as_utc(t.get('metrics_next_at'))
            p = t.get('platform')
            want_id = p == 'tiktok' and t.get('status') == 'published' and t.get('needs_post_id') and not t.get('remote_id')
            if (nxt and nxt > now) or (not want_id and (t.get('status') != 'published' or not t.get('remote_id')
                                                        or p not in METRIC_PLATFORMS or t.get('metrics_done'))):
                continue
            tried += 1
            age = now - (as_utc(t.get('published_at')) or as_utc(post.get('scheduled_at')) or now)
            upd = {}
            if age > timedelta(days=60):
                upd.update(metrics_done=True, needs_post_id=False)
            else:
                try:
                    acc, tok = _account_token(bid, p, accounts)
                    if want_id:
                        got = _tt_resolve_id(tok, t, now)
                        if got is None:
                            upd['metrics_next_at'] = now + timedelta(minutes=30)
                        else:
                            upd.update(got)
                            t.update(got)
                    if t.get('remote_id') and 'metrics_next_at' not in upd:
                        m = METRIC_FETCH[p](acc, tok, t, upd)
                        if m:
                            db.social_post_metrics.update_one({'business_id': bid, 'post_id': post['id'], 'platform': p},
                                                              {'$set': {'remote_id': t['remote_id'], 'fetched_at': now, 'metrics': m,
                                                                        'qa_test': bool(post.get('qa_test'))}},
                                                              upsert=True)
                            done += 1
                        upd.update(metrics_at=now, metrics_error=None, metrics_next_at=now + _cadence(age))
                except SocialError as e:
                    if e.reconnect:
                        sa.mark_needs_reconnect(bid, p, e)
                        accounts[(bid, p)] = e
                    upd.update(metrics_error={'code': e.code, 'message': str(e)[:200], 'at': now},
                               metrics_next_at=now + timedelta(hours=6))
            db.social_posts.update_one({'id': post['id'], 'business_id': bid},
                                       {'$set': {f'targets.{idx}.{k}': v for k, v in upd.items()}})
    return done


def insights(business_id, days=30, now=None):
    """Số liệu THẬT theo nền tảng: tổng chỉ cộng các trường nền tảng đã trả (ghi kèm số bài có trường đó)."""
    now = as_utc(now) or utcnow()
    days = max(1, min(int(days or 30), 365))
    posts = list(db.social_posts.find({'business_id': business_id, **_world(), 'status': {'$in': ['published', 'partial', 'publishing']},
                                       'scheduled_at': {'$gte': now - timedelta(days=days)}}, {'_id': 0}).sort('scheduled_at', -1).limit(300))
    by_id = {p['id']: p for p in posts}
    rows = list(db.social_post_metrics.find({'business_id': business_id, 'post_id': {'$in': list(by_id)}}, {'_id': 0})) if by_id else []
    totals = {}
    for p in posts:
        for t in p.get('targets') or []:
            if t.get('status') == 'published':
                tot = totals.setdefault(t['platform'], {'posts': 0, 'posts_with_metrics': 0, 'metrics': {}, 'metric_posts': {}})
                tot['posts'] += 1
    items = []
    for r in rows:
        tot = totals.setdefault(r['platform'], {'posts': 0, 'posts_with_metrics': 0, 'metrics': {}, 'metric_posts': {}})
        tot['posts_with_metrics'] += 1
        for k, v in (r.get('metrics') or {}).items():
            if isinstance(v, (int, float)):
                tot['metrics'][k] = tot['metrics'].get(k, 0) + v
                tot['metric_posts'][k] = tot['metric_posts'].get(k, 0) + 1
        p = by_id.get(r['post_id']) or {}
        tgt = next((t for t in p.get('targets') or [] if t.get('platform') == r['platform']), {})
        items.append({'post': {'id': p.get('id'), 'caption': (p.get('caption') or '')[:200], 'media_type': p.get('media_type'),
                               'scheduled_at': iso_z(p.get('scheduled_at')), 'permalink': tgt.get('permalink')},
                      'platform': r['platform'], 'metrics': r.get('metrics') or {}, 'fetched_at': iso_z(r.get('fetched_at'))})
    items.sort(key=lambda x: x['post']['scheduled_at'] or '', reverse=True)
    return {'days': days, 'totals': totals, 'posts': items}
