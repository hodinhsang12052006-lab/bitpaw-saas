"""
Tài khoản mạng xã hội của tiệm cho AI Social Manager (docs/AI_SUITE_SPEC.md §0 + §4.1):
Facebook Page, Instagram (Business/Creator), YouTube, TikTok, Google Business Profile.

db.social_accounts (1 doc / tiệm / nền tảng):
    {business_id, platform, status 'connected'|'needs_reconnect'|'disconnected', account_name, external_id, token_enc,
     refresh_token_enc, token_expires_at (UTC dt), scopes [str], connected_via 'inbox'|'token'|'oauth', connected_at,
     updated_at, last_error {code, message, at}, qa_test, (gbp) location_choices}
Cách nối:
  - facebook / instagram: lấy luôn kết nối Messenger / Instagram của Hộp thư chung (connect_from_inbox) hoặc dán Page token
    (connect_token) — BitPaw chưa làm Meta OAuth riêng cho đăng bài; quyền đăng bài cần Meta App Review (nói thẳng trên UI).
  - youtube / google_business: Google OAuth (GOOGLE_CLIENT_ID/SECRET, offline + refresh token).
  - tiktok: TikTok OAuth v2 (TIKTOK_CLIENT_KEY/SECRET).
Thiếu khoá app -> SocialError('app_not_configured'): UI nói "BitPaw chưa cài app <nền tảng>", KHÔNG giả vờ đã nối.

An toàn thử nghiệm (§0): local và production DÙNG CHUNG 1 MongoDB. test_mode() = có biến *_API_BASE trỏ máy giả. Khi đó:
  - việc chạy nền / nhiều tiệm chỉ đụng business_id trong SOCIAL_TEST_BUSINESS_IDS và chỉ bài/tài khoản qa_test;
  - production KHÔNG BAO GIỜ dùng tài khoản/bài qa_test (token của máy giả) — 2 thế giới tách hẳn nhau.
Mọi URL nền tảng đều đổi được bằng biến môi trường (máy giả cho e2e) — không gọi API thật khi thử.
"""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from mongo_client import db
import nurture_channel_tokens as _vault

PLATFORMS = ('facebook', 'instagram', 'youtube', 'tiktok', 'google_business')
LABELS = {'facebook': 'Facebook', 'instagram': 'Instagram', 'youtube': 'YouTube', 'tiktok': 'TikTok',
          'google_business': 'Google Business Profile'}
OAUTH_PLATFORMS = ('youtube', 'google_business', 'tiktok')
INBOX_CHANNEL = {'facebook': 'messenger', 'instagram': 'instagram'}

GRAPH_V = os.environ.get('SOCIAL_GRAPH_VERSION', 'v23.0')
META_API = os.environ.get('SOCIAL_META_API_BASE', 'https://graph.facebook.com').rstrip('/')
# Video Facebook đi qua host riêng graph-video; ở chế độ thử dùng chung máy giả của Meta
META_VIDEO_API = (os.environ.get('SOCIAL_META_VIDEO_BASE')
                  or (META_API if os.environ.get('SOCIAL_META_API_BASE') else 'https://graph-video.facebook.com')).rstrip('/')
GOOGLE_API = os.environ.get('SOCIAL_GOOGLE_API_BASE', 'https://www.googleapis.com').rstrip('/')
GOOGLE_OAUTH = os.environ.get('SOCIAL_GOOGLE_OAUTH_BASE', 'https://oauth2.googleapis.com').rstrip('/')
GOOGLE_AUTH_URL = (os.environ.get('SOCIAL_GOOGLE_AUTH_URL')
                   or (f"{GOOGLE_OAUTH}/o/oauth2/v2/auth" if os.environ.get('SOCIAL_GOOGLE_OAUTH_BASE')
                       else 'https://accounts.google.com/o/oauth2/v2/auth'))
TIKTOK_API = os.environ.get('SOCIAL_TIKTOK_API_BASE', 'https://open.tiktokapis.com').rstrip('/')
TIKTOK_AUTH_URL = (f"{TIKTOK_API}/v2/auth/authorize/" if os.environ.get('SOCIAL_TIKTOK_API_BASE')
                   else 'https://www.tiktok.com/v2/auth/authorize/')
GBP_API = os.environ.get('SOCIAL_GBP_API_BASE', 'https://mybusiness.googleapis.com').rstrip('/')
# Google tách Business Profile thành nhiều API (bài đăng v4 / tài khoản / địa điểm) — máy giả gộp chung 1 host
GBP_ACCOUNTS_API = GBP_API if os.environ.get('SOCIAL_GBP_API_BASE') else 'https://mybusinessaccountmanagement.googleapis.com'
GBP_INFO_API = GBP_API if os.environ.get('SOCIAL_GBP_API_BASE') else 'https://mybusinessbusinessinformation.googleapis.com'

GOOGLE_SCOPES = {
    'youtube': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
    'google_business': 'https://www.googleapis.com/auth/business.manage',
}
# video.list: cần để đọc lượt xem/thích THẬT qua /v2/video/query/ (sync_metrics) — spec chỉ ghi 3 scope đầu
TIKTOK_SCOPES = 'user.info.basic,video.publish,video.upload,video.list'
TIMEOUT = 15
STATE_TTL = 600

_TEST_ENV = ('REPLICATE_API_BASE', 'SOCIAL_META_API_BASE', 'SOCIAL_GOOGLE_API_BASE', 'SOCIAL_GOOGLE_OAUTH_BASE',
             'SOCIAL_TIKTOK_API_BASE', 'SOCIAL_GBP_API_BASE')

# Điều kiện THẬT của từng nền tảng (nói thẳng với chủ tiệm). Khi chủ BitPaw đã được duyệt thì khai mã vào
# SOCIAL_APPROVED (vd "meta_review_pages,tiktok_audit") để bỏ dòng tương ứng — không tự đoán là đã duyệt.
REQUIREMENTS = {
    'facebook': [('meta_review_pages', "Meta App Review: pages_manage_posts and pages_read_engagement (read_insights for numbers) "
                                       "must be approved for BitPaw's Meta app before posting works for every shop")],
    'instagram': [('ig_business', 'Instagram must be a Business or Creator account linked to your Facebook Page'),
                  ('meta_review_ig', 'Meta App Review: instagram_content_publish (instagram_manage_insights for numbers)'),
                  ('ig_media', 'Instagram needs a photo (JPEG) or a video — text-only posts are skipped')],
    'youtube': [('google_verify', "Google must verify BitPaw's app for the YouTube upload permission"),
                ('youtube_private_until_audit', "Until Google audits BitPaw's app, uploaded videos stay private")],
    'tiktok': [('tiktok_audit', "Until TikTok audits BitPaw's app, posts are private (only you can see them)"),
               ('tiktok_manual', 'TikTok posts are never sent on autopilot — you choose privacy and interaction settings for each post')],
    'google_business': [('gbp_api_access', "Google must approve BitPaw's access to the Business Profile API"),
                        ('gbp_no_video', 'Video posts are not supported — photos and text only')],
}


class SocialError(Exception):
    """Lỗi nói thẳng được với chủ tiệm. `code` để UI dịch (VI/EN); câu tiếng Anh là bản gốc.
    transient=True: lỗi tạm (mạng, 5xx, giới hạn tốc độ) -> thử lại có giãn cách; reconnect=True: token hỏng -> cần nối lại."""

    def __init__(self, code, message, detail=None, transient=False, reconnect=False, platform=None):
        super().__init__(message)
        self.code, self.detail, self.transient, self.reconnect, self.platform = code, detail, transient, reconnect, platform

    def as_dict(self):
        return {'success': False, 'code': self.code, 'message': str(self)[:300],
                'detail': (str(self.detail)[:300] if self.detail else None), 'platform': self.platform}


# ---------------------------------------------------------------- thời gian (Mongo lưu datetime UTC có múi giờ)
def utcnow():
    return datetime.now(timezone.utc)


def as_utc(dt):
    """pymongo trả datetime NAIVE (UTC) vì MongoClient không bật tz_aware -> luôn chuẩn hoá trước khi so sánh."""
    if dt is None or not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso_z(dt):
    dt = as_utc(dt)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def parse_iso(value):
    """ISO 8601 CÓ múi giờ ('Z' hoặc +hh:mm) -> datetime UTC. Giờ không có múi giờ bị từ chối (mơ hồ giữa máy chủ/tiệm)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('time needs a timezone offset')
        return value.astimezone(timezone.utc)
    s = str(value or '').strip()
    if not s:
        raise ValueError('empty time')
    if s.endswith(('Z', 'z')):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError('time needs a timezone offset')
    return dt.astimezone(timezone.utc)


_TZ_BY_CURRENCY = {'AUD': 'Australia/Sydney', 'USD': 'America/Los_Angeles', 'VND': 'Asia/Ho_Chi_Minh'}


def shop_tz(business_id):
    """Múi giờ của tiệm: cài đặt nhắn tin (messaging) -> theo tiền tệ -> UTC."""
    try:
        import messaging
        return ZoneInfo(messaging.get_settings(business_id)['timezone'])
    except Exception:
        pass
    try:
        from app import _tenant_currency
        return ZoneInfo(_TZ_BY_CURRENCY.get((_tenant_currency(business_id) or '').upper(), 'UTC'))
    except Exception:
        return ZoneInfo('UTC')


def shop_language(business_id):
    try:
        import messaging
        return 'vi' if messaging.get_settings(business_id).get('language') == 'vi' else 'en'
    except Exception:
        return 'en'


def business_industry(business_id):
    try:
        biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'industry_code': 1}) or {}
        code = (biz.get('industry_code') or '').strip().lower()
        if not code:
            row = db.system_settings.find_one({'key': f'business_mode_{business_id}'}, {'_id': 0, 'value': 1}) or {}
            code = (row.get('value') or '').strip().lower()
        return 'nail' if code == 'nails' else code
    except Exception:
        return ''


def public_base():
    """Gốc URL công khai (Instagram/Google cần tải ảnh/video qua https từ máy chủ BitPaw)."""
    return (os.environ.get('SOCIAL_PUBLIC_BASE') or os.environ.get('PUBLIC_BASE_URL')
            or 'https://www.bitpawsoftware.com').rstrip('/')


# ---------------------------------------------------------------- công tắc an toàn khi thử (§0)
def test_mode():
    return any(os.environ.get(k) for k in _TEST_ENV)


def test_business_ids():
    return {x.strip() for x in (os.environ.get('SOCIAL_TEST_BUSINESS_IDS') or '').split(',') if x.strip()}


def business_allowed(business_id):
    return (not test_mode()) or str(business_id) in test_business_ids()


def tick_allowed():
    """Việc chạy cho MỌI tiệm (cron) chỉ trên production, hoặc khi tự bật SOCIAL_ALLOW_TICK=1 (vẫn theo bộ lọc thử)."""
    return os.environ.get('VERCEL_ENV') == 'production' or os.environ.get('SOCIAL_ALLOW_TICK') == '1'


def _usable(doc):
    """Tài khoản tạo lúc thử (token máy giả) không bao giờ dùng ở production và ngược lại."""
    return bool(doc) and bool(doc.get('qa_test')) == test_mode()


# ---------------------------------------------------------------- HTTP
def http(method, url, timeout=TIMEOUT, **kw):
    """Mọi lệnh gọi nền tảng đi qua đây: luôn có timeout; lỗi mạng = lỗi tạm (thử lại sau)."""
    try:
        return requests.request(method, url, timeout=timeout, **kw)
    except requests.exceptions.RequestException as e:
        host = re.sub(r'^https?://', '', url).split('/')[0]
        raise SocialError('unreachable', f"Could not reach {host}: {str(e)[:120]}", transient=True)


def rjson(r):
    try:
        j = r.json() if r.content else {}
    except ValueError:
        return {}
    return j if isinstance(j, dict) else {}


def _oauth_error(r, platform, what):
    j = rjson(r)
    err = j.get('error')
    code = err if isinstance(err, str) else ((err or {}).get('code') if isinstance(err, dict) else None)
    desc = j.get('error_description') or (err.get('message') if isinstance(err, dict) else None) or f"HTTP {r.status_code}"
    if code in ('invalid_client', 'unauthorized_client'):
        # khoá app của BitPaw sai — chủ tiệm nối lại cũng không hết, phải báo chủ BitPaw
        return SocialError('app_misconfigured', f"BitPaw's {LABELS[platform]} app keys were rejected — contact BitPaw support.",
                           desc, platform=platform)
    if code == 'invalid_grant' or (r.status_code in (400, 401) and what == 'refresh'):
        return SocialError('token_invalid', f"{LABELS[platform]} access was revoked or expired — reconnect {LABELS[platform]}.",
                           desc, reconnect=True, platform=platform)
    if r.status_code >= 500 or r.status_code == 429:
        return SocialError('provider_busy', f"{LABELS[platform]} is busy — try again in a minute.", desc, transient=True, platform=platform)
    return SocialError('oauth_failed', f"{LABELS[platform]} did not accept the sign-in: {desc}", desc, platform=platform)


def _meta_check(r, platform):
    if r.status_code < 300:
        return rjson(r)
    e = rjson(r).get('error') or {}
    code, msg = e.get('code'), e.get('message') or f"HTTP {r.status_code}"
    if code == 190:
        raise SocialError('token_invalid', 'The access token is invalid or has expired.', msg, reconnect=True, platform=platform)
    if code == 100 and 'node type (User)' in msg:
        raise SocialError('need_page_token', 'This is a personal (user) token — paste a Page access token.', msg, platform=platform)
    if r.status_code >= 500:
        raise SocialError('provider_busy', f"{LABELS[platform]} is busy — try again in a minute.", msg, transient=True, platform=platform)
    raise SocialError('rejected', f"{LABELS[platform]} rejected the token / ID: {msg}", msg, platform=platform)


# ---------------------------------------------------------------- đọc / ghi tài khoản
_INDEXES_READY = False


def _ensure_indexes():
    global _INDEXES_READY
    if _INDEXES_READY or db is None:
        return
    try:
        db.social_accounts.create_index([('business_id', 1), ('platform', 1)], unique=True)
        _INDEXES_READY = True
    except Exception as e:  # không chặn kết nối vì lỗi tạo index
        print(f"[social] index: {e}")


def _doc(business_id, platform):
    return db.social_accounts.find_one({'business_id': business_id, 'platform': platform}, {'_id': 0})


def get_account(business_id, platform):
    """Doc tài khoản dùng được (đã nối HOẶC cần nối lại — để báo đúng lỗi), hoặc None."""
    d = _doc(business_id, platform)
    if not _usable(d) or d.get('status') not in ('connected', 'needs_reconnect'):
        return None
    return d


def is_connected(business_id, platform):
    d = get_account(business_id, platform)
    return bool(d and d.get('status') == 'connected')


def _save(business_id, platform, external_id, account_name, token, connected_via, refresh_token=None, expires_in=None,
          scopes=None, extra=None):
    _ensure_indexes()
    old = _doc(business_id, platform) or {}
    if test_mode() and old.get('status') == 'connected' and not old.get('qa_test'):
        # máy local đang trỏ máy giả: không được ghi đè tài khoản THẬT của tiệm trong DB dùng chung
        raise SocialError('real_account_exists', 'This shop already has a real account connected — test runs must not overwrite it.',
                          platform=platform)
    now = utcnow()
    ext = str(external_id or '')[:160]
    if refresh_token:
        rt_enc = _vault.encrypt_secret(refresh_token)
    elif connected_via == 'oauth' and old.get('external_id') == ext and bool(old.get('qa_test')) == test_mode():
        # Google không trả lại refresh token khi đã đồng ý trước đó: chỉ giữ token cũ nếu CÙNG kênh/địa điểm
        # (giữ token của tài khoản khác = đăng nhầm sang kênh khác)
        rt_enc = old.get('refresh_token_enc')
    else:
        rt_enc = None
    doc = {
        'business_id': business_id, 'platform': platform, 'status': 'connected',
        'account_name': (account_name or '')[:120], 'external_id': ext,
        'token_enc': _vault.encrypt_secret(token),
        'refresh_token_enc': rt_enc,
        'token_expires_at': (now + timedelta(seconds=int(expires_in))) if expires_in else None,
        'scopes': list(scopes or []), 'connected_via': connected_via, 'connected_at': now, 'updated_at': now,
        'last_error': None, 'qa_test': test_mode(),
    }
    doc.update(extra or {})
    db.social_accounts.update_one({'business_id': business_id, 'platform': platform}, {'$set': doc}, upsert=True)
    return public_status(business_id)[platform]


def _verify_meta(platform, token, external_id):
    """Hỏi THẬT Meta xem token đọc được Page / tài khoản Instagram không (không báo 'đã nối' khi token sai)."""
    if platform == 'facebook':
        r = http('GET', f"{META_API}/{GRAPH_V}/me", params={'fields': 'id,name,category', 'access_token': token})
        j = _meta_check(r, platform)
        if external_id and str(j.get('id')) != str(external_id):
            raise SocialError('page_mismatch', 'This token belongs to a different Page than the Page ID you entered.', platform=platform)
        return str(j.get('id') or external_id), j.get('name') or ''
    if not external_id:
        raise SocialError('need_ig_id', 'Instagram account ID is required.', platform=platform)
    r = http('GET', f"{META_API}/{GRAPH_V}/{external_id}", params={'fields': 'id,username', 'access_token': token})
    j = _meta_check(r, platform)
    return str(j.get('id') or external_id), ('@' + j['username']) if j.get('username') else ''


def connect_from_inbox(business_id, platform):
    """facebook <- kết nối 'messenger' của Hộp thư chung (Page token + Page ID); instagram <- kết nối 'instagram'."""
    import inbox_channels
    ch = INBOX_CHANNEL.get(platform)
    if not ch:
        raise SocialError('unsupported', 'Only Facebook and Instagram can be connected from the Unified Inbox.', platform=platform)
    conn = inbox_channels.get_connection(business_id, ch)
    if not conn:
        raise SocialError('inbox_not_connected', f"{LABELS[platform]} is not connected in the Unified Inbox yet.", platform=platform)
    token = _vault.decrypt_secret(conn.get('access_token_enc'))
    if not token:
        raise SocialError('token_unreadable', 'The Unified Inbox token could not be read — reconnect it there first.', platform=platform)
    ext_id, name = _verify_meta(platform, token, conn.get('external_id'))
    return _save(business_id, platform, ext_id, name or conn.get('account_name'), token, 'inbox')


def connect_token(business_id, platform, fields):
    """facebook: Page access token (+ page_id); instagram: token + ig_user_id; google_business: chọn địa điểm khác
    (fields.location trong danh sách Google đã trả lúc nối)."""
    f = {k: (v.strip() if isinstance(v, str) else v) for k, v in (fields or {}).items()}
    if platform == 'google_business':
        return select_location(business_id, f.get('location') or '')
    if platform not in INBOX_CHANNEL:
        raise SocialError('use_oauth', f"Connect {LABELS.get(platform, platform)} with the sign-in button.", platform=platform)
    token = f.get('access_token') or ''
    if not token:
        raise SocialError('need_token', 'Paste the access token first.', platform=platform)
    ext = f.get('page_id') if platform == 'facebook' else (f.get('ig_user_id') or f.get('external_id'))
    ext_id, name = _verify_meta(platform, token, ext or (f.get('external_id') if platform == 'facebook' else None))
    return _save(business_id, platform, ext_id, name, token, 'token')


# ---------------------------------------------------------------- OAuth Google / TikTok
def _google_creds():
    return os.environ.get('GOOGLE_CLIENT_ID'), os.environ.get('GOOGLE_CLIENT_SECRET')


def _tiktok_creds():
    return os.environ.get('TIKTOK_CLIENT_KEY'), os.environ.get('TIKTOK_CLIENT_SECRET')


def oauth_configured(platform):
    if platform in GOOGLE_SCOPES:
        return all(_google_creds())
    if platform == 'tiktok':
        return all(_tiktok_creds())
    return False


def _need_app(platform):
    if platform not in OAUTH_PLATFORMS:
        raise SocialError('unsupported', f"{LABELS.get(platform, platform)} does not use the sign-in button.", platform=platform)
    if not oauth_configured(platform):
        raise SocialError('app_not_configured', f"BitPaw's {LABELS[platform]} app is not set up yet.", platform=platform)


def new_state():
    return secrets.token_urlsafe(24)


def oauth_start_url(business_id, platform, redirect_uri, state):
    _need_app(platform)
    if platform in GOOGLE_SCOPES:
        cid, _ = _google_creds()
        params = {'client_id': cid, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': GOOGLE_SCOPES[platform],
                  'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true', 'state': state}
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    key, _ = _tiktok_creds()
    params = {'client_key': key, 'scope': TIKTOK_SCOPES, 'response_type': 'code', 'redirect_uri': redirect_uri, 'state': state}
    return f"{TIKTOK_AUTH_URL}?{urlencode(params)}"


def oauth_finish(business_id, platform, code, redirect_uri):
    _need_app(platform)
    if not code:
        raise SocialError('oauth_failed', 'Sign-in failed — please try again.', platform=platform)
    if platform in GOOGLE_SCOPES:
        cid, sec = _google_creds()
        r = http('POST', f"{GOOGLE_OAUTH}/token", data={'code': code, 'client_id': cid, 'client_secret': sec,
                                                       'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'})
        if r.status_code >= 300:
            raise _oauth_error(r, platform, 'exchange')
        tok = rjson(r)
        access = tok.get('access_token')
        if not access:
            raise SocialError('oauth_failed', 'Google did not return an access token.', platform=platform)
        granted = set((tok.get('scope') or '').split())
        need = set(GOOGLE_SCOPES[platform].split())
        # Google cho người dùng bỏ tick từng quyền: thiếu quyền đăng thì nói thẳng, không lưu kết nối nửa vời
        if granted and not need <= granted:
            raise SocialError('scope_missing', 'Google sign-in did not include every permission BitPaw needs — tick all boxes and try again.',
                              ' '.join(sorted(need - granted)), platform=platform)
        hdr = {'Authorization': f'Bearer {access}'}
        extra = {}
        if platform == 'youtube':
            r = http('GET', f"{GOOGLE_API}/youtube/v3/channels", params={'part': 'snippet', 'mine': 'true'}, headers=hdr)
            if r.status_code >= 300:
                raise _oauth_error(r, platform, 'channel')
            items = rjson(r).get('items') or []
            if not items:
                raise SocialError('youtube_no_channel', 'This Google account has no YouTube channel yet — create one on YouTube first.',
                                  platform=platform)
            ext, name = items[0].get('id'), ((items[0].get('snippet') or {}).get('title') or '')
        else:
            ext, name, choices = _gbp_locations(hdr)
            extra['location_choices'] = choices
        return _save(business_id, platform, ext, name, access, 'oauth', refresh_token=tok.get('refresh_token'),
                     expires_in=tok.get('expires_in') or 3600, scopes=sorted(granted or need), extra=extra)
    key, sec = _tiktok_creds()
    r = http('POST', f"{TIKTOK_API}/v2/oauth/token/", data={'client_key': key, 'client_secret': sec, 'code': code,
                                                            'grant_type': 'authorization_code', 'redirect_uri': redirect_uri},
             headers={'Content-Type': 'application/x-www-form-urlencoded'})
    tok = rjson(r)
    if r.status_code >= 300 or not tok.get('access_token'):
        raise _oauth_error(r, platform, 'exchange')
    scopes = [s for s in (tok.get('scope') or '').split(',') if s]
    if scopes and 'video.publish' not in scopes:
        raise SocialError('scope_missing', 'TikTok sign-in did not allow posting videos — allow every permission and try again.',
                          'video.publish', platform=platform)
    name = ''
    r = http('GET', f"{TIKTOK_API}/v2/user/info/", params={'fields': 'open_id,display_name'},
             headers={'Authorization': f"Bearer {tok['access_token']}"})
    if r.status_code < 300:
        name = ((rjson(r).get('data') or {}).get('user') or {}).get('display_name') or ''
    return _save(business_id, platform, tok.get('open_id') or '', name, tok['access_token'], 'oauth',
                 refresh_token=tok.get('refresh_token'), expires_in=tok.get('expires_in') or 86400, scopes=scopes)


def _gbp_locations(hdr):
    """Tài khoản + địa điểm Google Business Profile của người vừa đăng nhập (lấy địa điểm đầu, giữ danh sách để đổi)."""
    r = http('GET', f"{GBP_ACCOUNTS_API}/v1/accounts", headers=hdr)
    if r.status_code >= 300:
        raise google_error(r, 'google_business')
    choices = []
    for a in (rjson(r).get('accounts') or [])[:5]:
        r = http('GET', f"{GBP_INFO_API}/v1/{a.get('name')}/locations", params={'readMask': 'name,title', 'pageSize': 100}, headers=hdr)
        if r.status_code >= 300:
            continue
        for loc in rjson(r).get('locations') or []:
            # tên địa điểm Google trả 'locations/456'; API bài đăng v4 cần 'accounts/123/locations/456'
            loc_id = str(loc.get('name') or '').split('/')[-1]
            if loc_id:
                choices.append({'id': f"{a.get('name')}/locations/{loc_id}", 'name': (loc.get('title') or '')[:120]})
            if len(choices) >= 30:
                break
    if not choices:
        raise SocialError('gbp_no_location', 'No Business Profile location was found for this Google account.', platform='google_business')
    return choices[0]['id'], choices[0]['name'], choices


def select_location(business_id, location):
    d = get_account(business_id, 'google_business')
    if not d:
        raise SocialError('not_connected', 'Google Business Profile is not connected.', platform='google_business')
    pick = next((c for c in d.get('location_choices') or [] if c.get('id') == location), None)
    if not pick:
        raise SocialError('bad_location', 'Pick one of the locations Google listed for your account.', platform='google_business')
    db.social_accounts.update_one({'business_id': business_id, 'platform': 'google_business'},
                                  {'$set': {'external_id': pick['id'], 'account_name': pick['name'], 'updated_at': utcnow()}})
    return public_status(business_id)['google_business']


def google_error(r, platform):
    j = rjson(r)
    e = j.get('error') if isinstance(j.get('error'), dict) else {}
    msg = e.get('message') or j.get('error_description') or f"HTTP {r.status_code}"
    reasons = {x.get('reason') for x in e.get('errors') or [] if isinstance(x, dict)}
    if r.status_code == 401:
        return SocialError('token_invalid', f"{LABELS[platform]} access was revoked or expired — reconnect.", msg, reconnect=True, platform=platform)
    if reasons & {'quotaExceeded', 'dailyLimitExceeded'}:
        return SocialError('google_quota', "Google's daily API quota is used up — it resets tomorrow.", msg, platform=platform)
    if reasons & {'uploadLimitExceeded'}:
        return SocialError('youtube_upload_limit', 'YouTube says this channel reached its upload limit for now.', msg, platform=platform)
    if r.status_code in (429, 500, 502, 503, 504) or reasons & {'rateLimitExceeded', 'userRateLimitExceeded', 'backendError'}:
        return SocialError('provider_busy', f"{LABELS[platform]} is busy — will retry.", msg, transient=True, platform=platform)
    if r.status_code == 403:
        return SocialError('google_permission', f"Google refused: {msg}", msg, platform=platform)
    return SocialError('rejected', f"{LABELS[platform]} rejected the request: {msg}", msg, platform=platform)


def access_token(acc):
    """Token dùng được ngay. Google/TikTok: tự gia hạn khi còn < 5 phút. Lỗi -> SocialError (reconnect/transient)."""
    platform = acc['platform']
    if platform in INBOX_CHANNEL and acc.get('connected_via') == 'inbox':
        # token Hộp thư chung có thể vừa được dán lại: dùng bản mới nhất nếu vẫn đúng Page / tài khoản
        try:
            import inbox_channels
            conn = inbox_channels.get_connection(acc['business_id'], INBOX_CHANNEL[platform])
            if conn and str(conn.get('external_id')) == str(acc.get('external_id')):
                t = _vault.decrypt_secret(conn.get('access_token_enc'))
                if t:
                    return t
        except Exception:
            pass
    token = _vault.decrypt_secret(acc.get('token_enc'))
    if platform in INBOX_CHANNEL:
        if not token:
            raise SocialError('token_unreadable', f"{LABELS[platform]} token could not be read — reconnect.", reconnect=True, platform=platform)
        return token
    exp = as_utc(acc.get('token_expires_at'))
    if token and exp and exp > utcnow() + timedelta(minutes=5):
        return token
    rt = _vault.decrypt_secret(acc.get('refresh_token_enc'))
    if not rt:
        raise SocialError('token_expired', f"{LABELS[platform]} sign-in expired — reconnect.", reconnect=True, platform=platform)
    if platform in GOOGLE_SCOPES:
        cid, sec = _google_creds()
        if not (cid and sec):
            raise SocialError('app_not_configured', f"BitPaw's {LABELS[platform]} app is not set up yet.", platform=platform)
        r = http('POST', f"{GOOGLE_OAUTH}/token", data={'client_id': cid, 'client_secret': sec, 'refresh_token': rt,
                                                       'grant_type': 'refresh_token'})
    else:
        key, sec = _tiktok_creds()
        if not (key and sec):
            raise SocialError('app_not_configured', "BitPaw's TikTok app is not set up yet.", platform=platform)
        r = http('POST', f"{TIKTOK_API}/v2/oauth/token/", data={'client_key': key, 'client_secret': sec, 'refresh_token': rt,
                                                                'grant_type': 'refresh_token'},
                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    tok = rjson(r)
    if r.status_code >= 300 or not tok.get('access_token'):
        raise _oauth_error(r, platform, 'refresh')
    upd = {'token_enc': _vault.encrypt_secret(tok['access_token']), 'updated_at': utcnow(),
           'token_expires_at': utcnow() + timedelta(seconds=int(tok.get('expires_in') or 3600))}
    if tok.get('refresh_token'):
        upd['refresh_token_enc'] = _vault.encrypt_secret(tok['refresh_token'])
    db.social_accounts.update_one({'business_id': acc['business_id'], 'platform': platform}, {'$set': upd})
    return tok['access_token']


# ---------------------------------------------------------------- trạng thái / ngắt kết nối
def _err_doc(err):
    if isinstance(err, SocialError):
        return {'code': err.code, 'message': str(err)[:300], 'at': utcnow()}
    if isinstance(err, dict):
        return {'code': err.get('code') or 'provider', 'message': str(err.get('message') or '')[:300], 'at': utcnow()}
    return {'code': 'provider', 'message': str(err)[:300], 'at': utcnow()}


def mark_needs_reconnect(business_id, platform, err):
    db.social_accounts.update_one({'business_id': business_id, 'platform': platform, 'status': 'connected'},
                                  {'$set': {'status': 'needs_reconnect', 'last_error': _err_doc(err), 'updated_at': utcnow()}})


def note_error(business_id, platform, err):
    db.social_accounts.update_one({'business_id': business_id, 'platform': platform},
                                  {'$set': {'last_error': _err_doc(err), 'updated_at': utcnow()}})


def disconnect(business_id, platform):
    d = _doc(business_id, platform) or {}
    if _usable(d) and d.get('connected_via') == 'oauth':
        # thu hồi quyền phía Google/TikTok (cố gắng; lỗi mạng không chặn việc ngắt ở BitPaw)
        tok = _vault.decrypt_secret(d.get('refresh_token_enc')) or _vault.decrypt_secret(d.get('token_enc'))
        try:
            if tok and platform in GOOGLE_SCOPES:
                http('POST', f"{GOOGLE_OAUTH}/revoke", params={'token': tok}, timeout=8)
            elif tok and platform == 'tiktok' and all(_tiktok_creds()):
                key, sec = _tiktok_creds()
                http('POST', f"{TIKTOK_API}/v2/oauth/revoke/", data={'client_key': key, 'client_secret': sec, 'token': tok}, timeout=8)
        except SocialError:
            pass
    db.social_accounts.update_one({'business_id': business_id, 'platform': platform},
                                  {'$set': {'status': 'disconnected', 'token_enc': None, 'refresh_token_enc': None,
                                            'token_expires_at': None, 'updated_at': utcnow()}})


def _approved():
    return {x.strip() for x in (os.environ.get('SOCIAL_APPROVED') or '').split(',') if x.strip()}


def public_status(business_id):
    """Trạng thái từng nền tảng cho màn hình (KHÔNG BAO GIỜ trả token)."""
    docs = {d['platform']: d for d in db.social_accounts.find({'business_id': business_id}, {'_id': 0}) if d.get('platform') in PLATFORMS}
    inbox = {}
    try:
        import inbox_channels
        for p, ch in INBOX_CHANNEL.items():
            inbox[p] = bool(inbox_channels.get_connection(business_id, ch))
    except Exception:
        pass
    approved = _approved()
    out = {}
    for p in PLATFORMS:
        d = docs.get(p) or {}
        usable = _usable(d)
        status = d.get('status') if usable and d.get('status') else 'disconnected'
        last_error = d.get('last_error') if usable else None
        if d and not usable and d.get('status') == 'connected':
            last_error = {'code': 'test_connection', 'message': 'This connection was made by a test run and is not used here.', 'at': None}
        reqs = [(c, t) for c, t in REQUIREMENTS[p] if c not in approved]
        if p in OAUTH_PLATFORMS and not oauth_configured(p):
            reqs.insert(0, ('app_not_configured', f"BitPaw's {LABELS[p]} app is not set up yet"))
        row = {
            'platform': p, 'label': LABELS[p], 'connected': status == 'connected', 'status': status,
            'account_name': d.get('account_name') or '' if usable else '', 'external_id': d.get('external_id') or '' if usable else '',
            'connected_via': d.get('connected_via') if usable else None, 'connected_at': iso_z(d.get('connected_at')) if usable else None,
            'last_error': ({**last_error, 'at': iso_z(last_error.get('at'))} if last_error else None),
            'requirements': [t for _, t in reqs], 'requirement_codes': [c for c, _ in reqs],
            'can_oauth': p in OAUTH_PLATFORMS and oauth_configured(p), 'inbox_available': bool(inbox.get(p)),
            'methods': ['inbox', 'token'] if p in INBOX_CHANNEL else ['oauth'],
        }
        if p == 'google_business' and usable:
            row['location_choices'] = d.get('location_choices') or []
        out[p] = row
    return out
