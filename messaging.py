"""
Xương sống nhắn tin của BitPaw (thị trường Mỹ + Úc): SMS qua Twilio + email, có
  - danh sách TỪ CHỐI nhận tin (trả lời STOP / bấm huỷ đăng ký) — TCPA (Mỹ), Spam Act 2003 (Úc)
  - KHUNG GIỜ được phép gửi theo giờ địa phương của tiệm (mặc định 9:00–20:00)
  - HÀNG ĐỢI db.outbound_messages (chống gửi trùng bằng dedupe_key, thử lại tối đa 3 lần)
  - các "nguồn" tin tự động: nhắc lịch hẹn, xin đánh giá sau khi khách thanh toán, chuỗi chăm sóc khách AI
    đã duyệt, báo cáo cuối ngày cho chủ tiệm, trả lời cuộc gọi nhỡ (webhook Twilio)
Bộ gửi (pump) chạy bởi cron Vercel (2 lần/ngày) + khi chủ tiệm/nhân viên đang mở app (tối đa 1 lần / 3 phút / tiệm).

Cấu hình từng tiệm: db.messaging_settings (Auth Token Twilio mã hoá bằng nurture_channel_tokens/Fernet).
Thử nghiệm local: TWILIO_API_BASE trỏ về máy chủ giả (scripts/messaging_e2e.mjs) — KHÔNG gửi SMS thật.

Kênh gửi cho KHÁCH: 1 bộ giá trị chữ thường duy nhất CHANNELS = sms, email, zalo, messenger (normalize_channel() đổi các
giá trị cũ 'SMS'/'ZALO'/'FACEBOOK'/'zalo_oa'/'facebook'). Zalo/Messenger đi qua inbox_channels.send_text bằng kênh CHÍNH
tiệm đã nối ở Hộp thư chung (/inbox/channels) tới zalo_user_id / fb_psid của khách, và CHỈ trong khung trả lời của nền tảng:
  - Messenger: 24 giờ kể từ tin gần nhất KHÁCH gửi Page (ngoài 24 giờ Meta cấm tin quảng cáo/chăm sóc — không lách bằng tag);
  - Zalo OA "tin tư vấn": 48 giờ kể từ lần khách tương tác gần nhất (có nguồn ghi 7 ngày — dùng mốc chặt hơn); tin quảng
    cáo ngoài khung cần ZNS/tin truyền thông có mẫu Zalo duyệt + trả phí — chưa hỗ trợ.
Ngoài khung: gửi SMS/email nếu khách có, không thì bỏ qua và ghi rõ 'skipped: outside messaging window'.
"""
import base64
import calendar
import hashlib
import hmac
import os
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from pymongo.errors import DuplicateKeyError

from mongo_client import db, next_mongo_id
from email_service import EmailService
import nurture_channel_tokens
import plans

TWILIO_API_BASE = os.environ.get('TWILIO_API_BASE', 'https://api.twilio.com').rstrip('/')
DEFAULT_TZ = {'US': 'America/New_York', 'AU': 'Australia/Sydney', 'VN': 'Asia/Ho_Chi_Minh', 'CA': 'America/Toronto',
              'NZ': 'Pacific/Auckland', 'GB': 'Europe/London'}
MARKETING_KINDS = {'review_request', 'nurture', 'promo', 'winback', 'birthday', 'loyalty'}
# Tin TỰ ĐỘNG = tính năng 'messaging' của gói ("SMS & email tự động", Pro trở lên — plans.FEATURE_MIN_PLAN). Bảo mật (h4a):
# /settings/messaging đã khoá theo gói, nhưng tiệm Essential đã bật qua lỗ hổng cũ / tiệm vừa hạ gói vẫn còn cấu hình và tin
# trong hàng đợi -> kiểm tra gói lúc TẠO tin và lúc GỬI (pump, deliver). Tin giao dịch (báo chủ tiệm, "thợ đang tới", tin
# thử, lịch ca, phiếu lương) thuộc tính năng khác, không chặn ở đây.
AUTOMATED_KINDS = frozenset({'appointment_reminder', 'review_request', 'nurture', 'owner_report', 'missed_call', 'birthday',
                             'loyalty', 'promo', 'winback'})
PLAN_BLOCKED_ERROR = 'plan: SMS & email automation is not included in this plan'
# Bộ kênh DUY NHẤT (chữ thường) cho tin gửi khách — chiến dịch, luật tự động, sinh nhật, tích điểm đều dùng
CHANNELS = ('sms', 'email', 'zalo', 'messenger')
SOCIAL_CHANNELS = ('zalo', 'messenger')
CHANNEL_LABELS = {'sms': 'SMS', 'email': 'Email', 'zalo': 'Zalo', 'messenger': 'Messenger'}
SOCIAL_ID_FIELD = {'zalo': 'zalo_user_id', 'messenger': 'fb_psid'}   # inbox_channels.link_customer ghi vào db.customers
# Khung trả lời của nền tảng (giờ kể từ tin gần nhất KHÁCH gửi) — xem docstring đầu file
MESSAGING_WINDOW_HOURS = {'messenger': 24, 'zalo': 48}
_CHANNEL_ALIASES = {
    'sms': 'sms', 'text': 'sms', 'twilio': 'sms',
    'email': 'email', 'e-mail': 'email', 'mail': 'email',
    'zalo': 'zalo', 'zalo_oa': 'zalo', 'zalo oa': 'zalo', 'zalooa': 'zalo',
    'messenger': 'messenger', 'facebook': 'messenger', 'fb': 'messenger', 'fb_page': 'messenger',
    'fb_messenger': 'messenger', 'facebook_messenger': 'messenger',
}
STALE_NURTURE_DAYS = 14   # tin chăm sóc đã duyệt mà quá hạn gửi > 14 ngày (Zalo/Messenger cũ chưa từng gửi) -> không gửi muộn
STOP_WORDS = {'stop', 'stopall', 'unsubscribe', 'cancel', 'end', 'quit', 'optout', 'opt-out', 'revoke'}
START_WORDS = {'start', 'unstop', 'yes'}
MAX_ATTEMPTS = 3
inbox_hook = None  # app.py gắn _inbox_sms_inbound (tránh import vòng)
_INDEXES_READY = False


def _ensure_indexes():
    global _INDEXES_READY
    if _INDEXES_READY or db is None:
        return
    try:
        db.outbound_messages.create_index('dedupe_key', unique=True, sparse=True)
        db.outbound_messages.create_index([('status', 1), ('send_after', 1)])
        db.outbound_messages.create_index([('business_id', 1), ('created_at', -1)])
        db.message_optouts.create_index([('business_id', 1), ('channel', 1), ('address', 1)], unique=True)
        db.messaging_settings.create_index('business_id', unique=True)
        _INDEXES_READY = True
    except Exception as e:  # không chặn gửi tin vì lỗi tạo index
        print(f"[messaging] index: {e}")


# ---------------------------------------------------------------- cấu hình tiệm
DEFAULT_SETTINGS = {
    'timezone': '', 'sms_enabled': False, 'twilio_account_sid': '', 'twilio_from': '', 'shop_phone': '',
    'google_review_url': '', 'reminders_enabled': True, 'reminder_hours': 24,
    'reviews_enabled': False, 'review_delay_minutes': 90, 'missed_call_enabled': False,
    'owner_report_enabled': True, 'owner_report_email': '', 'send_window_start': 9, 'send_window_end': 20,
    'language': '',
    # xin đánh giá: mỗi khách tối đa 1 lần / N ngày; sinh nhật: gửi sớm N ngày (0 = đúng ngày); tích điểm/lên hạng:
    # Zalo/Messenger (trong khung) hoặc email — SMS (tốn phí mỗi bill) chỉ khi chủ tiệm bật loyalty_sms_enabled
    'review_cooldown_days': 60, 'birthday_enabled': True, 'birthday_days_before': 0,
    'loyalty_messages_enabled': True, 'loyalty_sms_enabled': False,
}


def automation_allowed(business_id):
    """Gói HIỆN TẠI của tiệm có tin tự động không (plans.business_allows: cache 60 giây; chi nhánh theo gói tiệm chính)."""
    return plans.business_allows(db, business_id, 'messaging')


def _cancel_plan_blocked(m):
    db.outbound_messages.update_one({'id': m['id'], 'status': 'queued'},
                                    {'$set': {'status': 'cancelled', 'error': PLAN_BLOCKED_ERROR}})
    _sync_campaign(m, {'delivery_status': 'cancelled', 'delivery_error': PLAN_BLOCKED_ERROR})


def normalize_channel(value, default=None):
    """'SMS'/'ZALO'/'FACEBOOK'/'zalo_oa'/'facebook'/... -> 'sms'|'email'|'zalo'|'messenger' (không nhận ra -> default)."""
    v = re.sub(r'\s+', ' ', str(value or '').strip().lower())
    return _CHANNEL_ALIASES.get(v, default)


def _business(business_id):
    return db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'country': 1, 'currency': 1, 'industry_code': 1}) or {}


def get_settings(business_id):
    s = dict(DEFAULT_SETTINGS)
    row = db.messaging_settings.find_one({'business_id': business_id}, {'_id': 0}) or {}
    s.update({k: v for k, v in row.items() if k in DEFAULT_SETTINGS})
    biz = _business(business_id)
    if not s['timezone']:
        s['timezone'] = DEFAULT_TZ.get((biz.get('country') or 'US').upper(), 'America/New_York')
    if not s['language']:
        s['language'] = 'vi' if (biz.get('country') or '').upper() == 'VN' else 'en'
    s['business_name'] = biz.get('name') or 'our shop'
    s['country'] = (biz.get('country') or 'US').upper()
    token = nurture_channel_tokens.get_channel_token(business_id, 'twilio') if s['twilio_account_sid'] else None
    s['twilio_ready'] = bool(s['sms_enabled'] and s['twilio_account_sid'] and s['twilio_from'] and token and token.get('access_token'))
    return s


def save_settings(business_id, data):
    clean = {}
    for k, default in DEFAULT_SETTINGS.items():
        if k not in data:
            continue
        v = data[k]
        if isinstance(default, bool):
            clean[k] = bool(v)
        elif isinstance(default, int):
            try:
                clean[k] = int(v)
            except (TypeError, ValueError):
                continue
        else:
            clean[k] = (str(v).strip() if v is not None else '')[:300]
    if 'timezone' in clean and clean['timezone']:
        try:
            ZoneInfo(clean['timezone'])
        except Exception:
            raise ValueError('Unknown time zone')
    if clean.get('google_review_url') and not re.match(r'^https://', clean['google_review_url']):
        raise ValueError('Review link must start with https://')
    for k in ('twilio_from', 'shop_phone'):
        if clean.get(k):
            clean[k] = normalize_phone(clean[k], data.get('country') or 'US') or clean[k]
    clean['send_window_start'] = max(8, min(clean.get('send_window_start', 9), 20)) if 'send_window_start' in clean else None
    clean['send_window_end'] = max(9, min(clean.get('send_window_end', 20), 21)) if 'send_window_end' in clean else None
    if 'review_cooldown_days' in clean:
        clean['review_cooldown_days'] = max(7, min(clean['review_cooldown_days'], 365))
    if 'birthday_days_before' in clean:
        clean['birthday_days_before'] = max(0, min(clean['birthday_days_before'], 7))
    clean = {k: v for k, v in clean.items() if v is not None}
    token = data.get('twilio_auth_token')
    if isinstance(token, str) and token.strip():
        nurture_channel_tokens.save_channel_token(business_id, 'twilio', token.strip(),
                                                  extra={'account_sid': clean.get('twilio_account_sid', '')})
    clean['updated_at'] = datetime.now(timezone.utc).isoformat()
    _ensure_indexes()
    db.messaging_settings.update_one({'business_id': business_id}, {'$set': clean}, upsert=True)
    return get_settings(business_id)


# ---------------------------------------------------------------- số điện thoại, giờ địa phương, từ chối
def normalize_phone(phone, country='US'):
    """Chuẩn E.164 (+1..., +61..., +84...). Trả '' nếu không hợp lệ."""
    if not phone:
        return ''
    raw = str(phone).strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+'):
        return '+' + digits if 8 <= len(digits) <= 15 else ''
    c = (country or 'US').upper()
    if c in ('US', 'CA'):
        if len(digits) == 10:
            return '+1' + digits
        if len(digits) == 11 and digits.startswith('1'):
            return '+' + digits
    if c == 'AU':
        if len(digits) == 10 and digits.startswith('0'):
            return '+61' + digits[1:]
        if len(digits) == 9 and digits[0] in '23478':
            return '+61' + digits
        if len(digits) == 11 and digits.startswith('61'):
            return '+' + digits
    if c == 'VN' and len(digits) == 10 and digits.startswith('0'):
        return '+84' + digits[1:]
    return ''


def local_now(settings):
    return datetime.now(ZoneInfo(settings['timezone']))


def in_send_window(settings, when_utc=None):
    t = (when_utc or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings['timezone']))
    return settings['send_window_start'] <= t.hour < settings['send_window_end']


def next_window_start_utc(settings, when_utc=None):
    tz = ZoneInfo(settings['timezone'])
    t = (when_utc or datetime.now(timezone.utc)).astimezone(tz)
    start = t.replace(hour=settings['send_window_start'], minute=0, second=0, microsecond=0)
    if t.hour >= settings['send_window_start']:
        start += timedelta(days=1)
    return start.astimezone(timezone.utc)


def _addr(channel, address):
    return (address or '').strip().lower() if channel == 'email' else (address or '').strip()


def is_opted_out(business_id, channel, address):
    return db.message_optouts.count_documents({'business_id': business_id, 'channel': channel, 'address': _addr(channel, address)}) > 0


def opt_out(business_id, channel, address, source='user'):
    _ensure_indexes()
    db.message_optouts.update_one({'business_id': business_id, 'channel': channel, 'address': _addr(channel, address)},
                                  {'$set': {'source': source, 'created_at': datetime.now(timezone.utc).isoformat()}}, upsert=True)
    # tin chưa gửi tới người này: huỷ
    db.outbound_messages.update_many({'business_id': business_id, 'channel': channel, 'to': _addr(channel, address), 'status': 'queued'},
                                     {'$set': {'status': 'cancelled', 'error': 'opted out'}})


def opt_in(business_id, channel, address):
    db.message_optouts.delete_many({'business_id': business_id, 'channel': channel, 'address': _addr(channel, address)})


def unsubscribe_token(business_id, email):
    key = (os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'bitpaw-unsub').encode()
    msg = f"{business_id}|{(email or '').strip().lower()}".encode()
    return base64.urlsafe_b64encode(hmac.new(key, msg, hashlib.sha256).digest()[:18]).decode().rstrip('=')


def unsubscribe_url(base_url, business_id, email):
    from urllib.parse import quote
    return f"{base_url.rstrip('/')}/unsubscribe?b={quote(str(business_id))}&e={quote(email)}&t={unsubscribe_token(business_id, email)}"


# ---------------------------------------------------------------- hàng đợi
def queue(business_id, channel, to, body, kind, send_after=None, subject=None, dedupe_key=None, meta=None):
    """Xếp 1 tin vào hàng đợi. Trả id, hoặc None nếu trùng dedupe_key / người nhận đã từ chối / địa chỉ sai."""
    _ensure_indexes()
    if channel not in CHANNELS or not to or not body:
        return None
    to = _addr(channel, to)
    if is_opted_out(business_id, channel, to):
        return None
    doc = {
        'id': next_mongo_id('outbound_messages'), 'business_id': business_id, 'channel': channel, 'to': to,
        'subject': subject or '', 'body': body[:1600], 'kind': kind, 'status': 'queued', 'attempts': 0,
        'send_after': (send_after or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        'created_at': datetime.now(timezone.utc).isoformat(), 'meta': meta or {},
    }
    if dedupe_key:
        doc['dedupe_key'] = dedupe_key
    try:
        db.outbound_messages.insert_one(doc)
        return doc['id']
    except DuplicateKeyError:
        return None


# ---------------------------------------------------------------- gửi thật
class SendError(Exception):
    pass


class OutsideWindow(SendError):
    """Zalo/Messenger: khách chưa nhắn tiệm trong khung trả lời của nền tảng -> KHÔNG gửi (chuyển SMS/email hoặc bỏ qua)."""


def _twilio_send(settings, business_id, to, body):
    token = nurture_channel_tokens.get_channel_token(business_id, 'twilio')
    if not settings.get('twilio_ready') or not token:
        raise SendError('SMS is not connected')
    sid = settings['twilio_account_sid']
    r = requests.post(f"{TWILIO_API_BASE}/2010-04-01/Accounts/{sid}/Messages.json",
                      data={'To': to, 'From': settings['twilio_from'], 'Body': body},
                      auth=(sid, token['access_token']), timeout=15)
    if r.status_code >= 300:
        try:
            err = r.json().get('message') or r.text[:200]
        except ValueError:
            err = r.text[:200]
        raise SendError(f"Twilio {r.status_code}: {err}")
    return (r.json() or {}).get('sid', '')


def _email_send(to, subject, body, unsubscribe):
    html = '<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.55;color:#111">' + \
           '<br>'.join(_esc(line) for line in body.split('\n')) + '</div>'
    if unsubscribe:
        html += f'<p style="font-size:12px;color:#777;margin-top:24px">Don\'t want these emails? <a href="{unsubscribe}">Unsubscribe</a>.</p>'
    ok, msg = EmailService.send_email(to, subject or 'Message', html)
    if not ok:
        raise SendError(msg)
    return 'email'


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _as_server_naive(value):
    """Chuỗi ISO (có/không múi giờ) -> datetime theo giờ MÁY CHỦ không múi giờ (hệ giờ inbox_channels ghi created_at)."""
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return _server_naive(t) if t.tzinfo else t


def last_customer_message_at(business_id, channel, user_id):
    """Lúc KHÁCH nhắn tiệm gần nhất trên kênh đó (hội thoại Hộp thư chung bot_customers/bot_messages), hoặc None."""
    import inbox_channels
    cid = inbox_channels.conversation_id(business_id, channel, user_id)
    t = (db.bot_customers.find_one({'id': cid}, {'_id': 0, 'last_inbound_at': 1}) or {}).get('last_inbound_at')
    if not t:   # hội thoại cũ trước khi có last_inbound_at
        m = db.bot_messages.find_one({'customer_id': cid, 'sender_type': 'customer'}, {'_id': 0, 'created_at': 1},
                                     sort=[('created_at', -1)])
        t = (m or {}).get('created_at')
    return _as_server_naive(t) if t else None


def in_messaging_window(business_id, channel, user_id, now_utc=None):
    """Messenger 24 giờ / Zalo 48 giờ kể từ tin gần nhất của khách. SMS/email: không có khung (luôn True)."""
    hours = MESSAGING_WINDOW_HOURS.get(channel)
    if hours is None:
        return True
    last = last_customer_message_at(business_id, channel, user_id)
    if last is None:
        return False
    return last >= _server_naive((now_utc or datetime.now(timezone.utc)) - timedelta(hours=hours))


def _social_connected(business_id, channel):
    import inbox_channels
    return bool(inbox_channels.get_connection(business_id, channel))


def _social_send(msg, now_utc=None):
    """Zalo/Messenger qua kênh CHÍNH tiệm nối ở Hộp thư chung. Tin cũng hiện trong hội thoại của khách ở /ai_bot (ghi trước
    rồi mới gửi — tin echo của nền tảng không bị hiện 2 lần; gửi lỗi thì xoá, không để lại bong bóng lỗi mỗi lần thử lại)."""
    import inbox_channels
    bid, ch, uid, body = msg['business_id'], msg['channel'], msg['to'], msg['body']
    label = CHANNEL_LABELS[ch]
    if not _social_connected(bid, ch):
        raise SendError(f"{label} is not connected — connect it in Messaging channels (/inbox/channels)")
    if not in_messaging_window(bid, ch, uid, now_utc):
        raise OutsideWindow(f"outside messaging window ({label}: {MESSAGING_WINDOW_HOURS[ch]} h after the customer's last message)")
    _cid, mid = inbox_channels.record(bid, ch, uid, body, 'ai', delivery={'status': 'sending', 'via': msg.get('kind')},
                                      return_msg_id=True)
    try:
        ext = inbox_channels.send_text(bid, ch, uid, body)
    except inbox_channels.ChannelError as e:
        db.bot_messages.delete_one({'_id': mid})
        if e.code == 'window_24h':
            raise OutsideWindow(f"outside messaging window ({label}: {e})")
        if e.code in ('not_connected', 'token_unreadable', 'token_invalid', 'zalo_expired'):
            raise SendError(f"{label} is not connected ({e}) — reconnect it in Messaging channels")
        raise SendError(f"{label}: {e}")
    upd = {'delivery': {'status': 'sent', 'at': datetime.now().isoformat(), 'via': msg.get('kind')}}
    if ext and ext != 'web':
        upd['ext_msg_id'] = ext
    db.bot_messages.update_one({'_id': mid}, {'$set': upd})
    return ext or ch


def send_now(msg, settings, base_url='', now_utc=None):
    """Gửi 1 tin của hàng đợi ngay (đã kiểm tra khung giờ/từ chối ở pump)."""
    body = msg['body']
    if msg['channel'] in SOCIAL_CHANNELS:
        return _social_send(msg, now_utc)
    if msg['channel'] == 'sms':
        if msg['kind'] in MARKETING_KINDS and 'stop' not in body.lower():
            body += ' Reply STOP to opt out.' if settings['language'] == 'en' else ' Trả lời STOP để ngừng nhận.'
        return _twilio_send(settings, msg['business_id'], msg['to'], body)
    unsub = unsubscribe_url(base_url or os.environ.get('PUBLIC_BASE_URL', 'https://www.bitpawsoftware.com'), msg['business_id'], msg['to']) \
        if msg['kind'] in MARKETING_KINDS else ''
    return _email_send(msg['to'], msg.get('subject') or settings['business_name'], body, unsub)


def deliver(msg_id, base_url=''):
    """Gửi NGAY đúng 1 tin vừa xếp hàng (báo chủ tiệm khách đang chờ, báo đổi ca...). pump() xử lý cả hàng đợi của tiệm
    (tới 40 tin + tạo tin tự động) — gọi trong lúc khách đang chờ AI trả lời làm chậm 1-2 giây. Lỗi -> để pump/cron thử lại."""
    m = db.outbound_messages.find_one({'id': msg_id, 'status': 'queued'}, {'_id': 0})
    if not m:
        return False
    if m.get('kind') in AUTOMATED_KINDS and not automation_allowed(m['business_id']):   # h4a: gói không có tin tự động
        _cancel_plan_blocked(m)
        return False
    lock = db.outbound_messages.update_one({'id': msg_id, 'status': 'queued'}, {'$set': {'status': 'sending'}, '$inc': {'attempts': 1}})
    if lock.modified_count != 1:
        return False
    try:
        provider_id = send_now(m, get_settings(m['business_id']), base_url)
        _mark_sent(m, provider_id)
        return True
    except Exception as e:
        db.outbound_messages.update_one({'id': msg_id}, {'$set': {'status': 'queued', 'error': str(e)[:300],
                                                                  'send_after': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}})
        return False


def _sync_campaign(m, fields):
    """Tin của chiến dịch chăm sóc (meta.campaign_message_id): ghi trạng thái gửi THẬT về db.campaign_messages — 'success'
    chỉ khi nhà mạng/nền tảng đã nhận tin (trước đây tin SMS/email đã gửi vẫn mãi 'queued', báo cáo chiến dịch luôn 0 đã gửi)."""
    cmid = (m.get('meta') or {}).get('campaign_message_id')
    if cmid:
        db.campaign_messages.update_one({'id': cmid, 'business_id': m['business_id']}, {'$set': fields})


def _mark_sent(m, provider_id):
    now = datetime.now(timezone.utc).isoformat()
    db.outbound_messages.update_one({'id': m['id']}, {'$set': {'status': 'sent', 'sent_at': now, 'provider_id': provider_id}})
    _sync_campaign(m, {'delivery_status': 'success', 'sent_at': now, 'delivery_channel': m['channel'], 'delivery_error': None})


# ---------------------------------------------------------------- chọn kênh cho 1 khách
def first_name(name, settings):
    """Tên gọi trong tin; tên tự sinh ('Client 1234', 'Khách 1234', 'Walk-in') -> lời chào chung.
    Tiệm tiếng Việt gọi tên (chữ CUỐI: 'Nguyễn Thu' -> 'Thu'), tiệm tiếng Anh gọi first name (chữ đầu)."""
    n = (name or '').strip()
    if not n or re.match(r'^(client|khách|khach|walk-?in|guest|customer)\b', n, re.I):
        return _t(settings, 'there', 'bạn')
    parts = n.split()
    return parts[0] if settings['language'] == 'en' else parts[-1]


def subject_for(kind, settings):
    b = settings['business_name']
    return {
        'nurture': _t(settings, f"A note from {b}", f"{b} gửi bạn"),
        'review_request': _t(settings, f"How was your visit to {b}?", f"Bạn thấy {b} thế nào?"),
        'birthday': _t(settings, f"Happy birthday from {b}", f"{b} chúc mừng sinh nhật bạn"),
        'loyalty': _t(settings, f"Your rewards at {b}", f"Điểm thưởng của bạn tại {b}"),
        'appointment_reminder': _t(settings, f"Appointment reminder — {b}", f"Nhắc lịch hẹn — {b}"),
    }.get(kind, b)


def contact_routes(business_id, settings, customer, preferred=None, now_utc=None, allow=None):
    """Kênh THẬT tiệm dùng được để nhắn 1 khách, theo thứ tự ưu tiên -> (routes [(kênh, địa chỉ)], skipped [(kênh, lý do)]).
      - zalo/messenger: tiệm đã nối kênh đó ở Hộp thư chung + khách đã liên kết (zalo_user_id / fb_psid); có now_utc thì chỉ
        khi đang trong khung trả lời của nền tảng (tin gửi ngay). Tin hẹn ngày sau: kiểm tra lại lúc gửi (pump).
      - sms: Twilio của tiệm sẵn sàng; email: khách có email.
      - bỏ địa chỉ khách đã từ chối nhận tin.
    preferred: 'sms' (SMS rồi email), 'email' (chỉ email), 'zalo'/'messenger' (kênh đó rồi SMS/email), None = Zalo/Messenger
    (miễn phí, trong khung) trước rồi SMS, email. allow: giới hạn tập kênh."""
    customer = customer or {}
    sms, em = _customer_contacts(business_id, customer.get('phone'), customer.get('email'), settings)
    social = [(ch, str(customer.get(SOCIAL_ID_FIELD[ch]) or '').strip()) for ch in SOCIAL_CHANNELS]
    social = [(ch, uid) for ch, uid in social if uid and uid != 'None']
    direct = ([('sms', sms)] if sms else []) + ([('email', em)] if em else [])
    if preferred == 'email':
        order = [r for r in direct if r[0] == 'email']
    elif preferred == 'sms':
        order = direct
    elif preferred in SOCIAL_CHANNELS:
        order = [r for r in social if r[0] == preferred] + direct
    else:
        order = social + direct
    if allow:
        order = [r for r in order if r[0] in allow]
    routes, skipped = [], []
    for ch, addr in order:
        if ch == 'sms' and not settings.get('twilio_ready'):
            skipped.append((ch, 'sms_not_connected'))
        elif ch in SOCIAL_CHANNELS and not _social_connected(business_id, ch):
            skipped.append((ch, 'not_connected'))
        elif ch in SOCIAL_CHANNELS and now_utc is not None and not in_messaging_window(business_id, ch, addr, now_utc):
            skipped.append((ch, 'outside_window'))
        elif is_opted_out(business_id, ch, addr):
            skipped.append((ch, 'opted_out'))
        else:
            routes.append((ch, addr))
    return routes, skipped


def no_route_status(skipped):
    """Không có kênh nào gửi được -> trạng thái nói thật lý do."""
    reasons = {r for _, r in skipped}
    if not skipped:
        return 'no_contact'
    if reasons == {'opted_out'}:
        return 'opted_out'
    if 'outside_window' in reasons:
        return 'skipped'
    return 'no_channel'


def queue_customer_message(business_id, customer, body, kind, settings=None, now_utc=None, send_after=None, subject=None,
                           dedupe_key=None, preferred=None, allow=None, meta=None):
    """Xếp 1 tin cho khách qua kênh tốt nhất của CHÍNH tiệm (không bao giờ dùng token chung của máy chủ).
    Trả (kênh | None, trạng thái 'queued'|'duplicate'|'no_contact'|'no_channel'|'opted_out'|'skipped', id | None).
    Zalo/Messenger hết khung lúc gửi -> pump tự chuyển SMS/email (meta.fallback) hoặc bỏ qua."""
    settings = settings or get_settings(business_id)
    now_utc = now_utc or datetime.now(timezone.utc)
    soon = send_after is None or send_after <= now_utc + timedelta(hours=1)
    routes, skipped = contact_routes(business_id, settings, customer, preferred=preferred,
                                     now_utc=now_utc if soon else None, allow=allow)
    if not routes:
        return None, no_route_status(skipped), None
    ch, to = routes[0]
    m = dict(meta or {})
    if customer.get('id') is not None:
        m.setdefault('customer_id', customer.get('id'))
    else:
        m.setdefault('contact', {'phone': customer.get('phone') or '', 'email': customer.get('email') or ''})
    if ch in SOCIAL_CHANNELS:
        m['fallback'] = not allow or any(c in allow for c in ('sms', 'email'))
    qid = queue(business_id, ch, to, body, kind, send_after=send_after, subject=subject or subject_for(kind, settings),
                dedupe_key=dedupe_key, meta=m)
    return ch, ('queued' if qid else 'duplicate'), qid


def _queue_fallback(m, settings):
    """Zalo/Messenger không gửi được (ngoài khung / chưa nối) -> xếp đúng nội dung đó qua SMS rồi email (nếu khách có)."""
    meta = m.get('meta') or {}
    if not meta.get('fallback'):
        return None, None
    contact = meta.get('contact') or {}
    if not contact and meta.get('customer_id') is not None:
        contact = db.customers.find_one({'business_id': m['business_id'], 'id': meta['customer_id']},
                                        {'_id': 0, 'phone': 1, 'email': 1}) or {}
    routes, _ = contact_routes(m['business_id'], settings, contact, preferred='sms', allow=('sms', 'email'))
    if not routes:
        return None, None
    ch, to = routes[0]
    new_meta = {k: v for k, v in meta.items() if k != 'fallback'}
    new_meta['fallback_from'] = m['channel']
    fid = queue(m['business_id'], ch, to, m['body'], m['kind'], subject=m.get('subject') or subject_for(m['kind'], settings),
                dedupe_key=f"fb:{m['id']}", meta=new_meta)
    return (fid, ch) if fid else (None, None)


def _reroute(m, settings, base_url, reason, only_if_fallback=False):
    """Huỷ tin Zalo/Messenger (ghi rõ lý do) và gửi bản SMS/email nếu có. Trả (kênh thay thế | None, đã gửi được?).
    only_if_fallback: không có SMS/email thì không đụng gì (để pump ghi lỗi gửi như thường)."""
    fid, ch = _queue_fallback(m, settings)
    if not ch and only_if_fallback:
        return None, False
    note = f"skipped: {reason}" + (f" — sent by {ch} instead" if ch else '')
    db.outbound_messages.update_one({'id': m['id']}, {'$set': {'status': 'cancelled', 'error': note[:300]}})
    if not ch:
        _sync_campaign(m, {'delivery_status': 'skipped', 'delivery_error': reason[:200]})
        return None, False
    _sync_campaign(m, {'delivery_status': 'queued', 'delivery_channel': ch, 'delivery_error': None, 'delivery_note': note[:300]})
    return ch, deliver(fid, base_url)


def birthday_plan(settings, now_utc=None):
    """Ngày gửi lời chúc = ngày gửi KẾ TIẾP theo giờ TIỆM (hôm nay nếu chưa qua khung giờ gửi, không thì ngày mai) — cron
    chạy giờ UTC (02:00 UTC = 22:00 hôm trước ở Mỹ) không làm lời chúc tới trễ 1 ngày. Gửi sớm N ngày nếu cài.
    -> {send_day, birthday, match_md ['MM-DD'...], send_after (UTC), days_before}"""
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(settings['timezone'])
    local = now_utc.astimezone(tz)
    send_day = local.date() if local.hour < int(settings['send_window_end']) else local.date() + timedelta(days=1)
    days_before = max(0, min(int(settings.get('birthday_days_before') or 0), 7))
    bday = send_day + timedelta(days=days_before)
    match = [bday.strftime('%m-%d')]
    if bday.month == 2 and bday.day == 28 and not calendar.isleap(bday.year):
        match.append('02-29')   # sinh 29/2: năm không nhuận chúc ngày 28/2
    start = datetime(send_day.year, send_day.month, send_day.day, int(settings['send_window_start']), tzinfo=tz)
    return {'send_day': send_day, 'birthday': bday, 'match_md': match, 'days_before': days_before,
            'send_after': max(now_utc, start.astimezone(timezone.utc))}


# ---------------------------------------------------------------- nguồn tin tự động
def _server_naive(dt_aware):
    """Đơn hàng/khách hàng lưu created_at = datetime.now() của MÁY CHỦ (UTC trên Vercel, giờ máy ở local) — so sánh
    phải dùng đúng hệ giờ đó."""
    return dt_aware.astimezone().replace(tzinfo=None)


def _t(settings, en, vi):
    return en if settings['language'] == 'en' else vi


def _customer_contacts(business_id, phone=None, email=None, settings=None):
    sms = normalize_phone(phone, settings['country']) if phone else ''
    return sms, (email or '').strip().lower()


def produce_appointment_reminders(business_id, settings, now_utc):
    """Lịch hẹn trong N giờ tới (giờ ĐỊA PHƯƠNG của tiệm) chưa nhắc -> SMS (hoặc email)."""
    if not settings['reminders_enabled']:
        return 0
    tz = ZoneInfo(settings['timezone'])
    now_local = now_utc.astimezone(tz).replace(tzinfo=None)
    end_local = now_local + timedelta(hours=int(settings['reminder_hours'] or 24))
    n = 0
    for appt in db.appointments.find({'business_id': business_id, 'status': {'$in': ['pending', 'confirmed']},
                                      'book_time': {'$gte': now_local.isoformat(), '$lte': end_local.isoformat()},
                                      'reminder_sent': {'$ne': True}}, {'_id': 0}).limit(300):
        try:
            when = datetime.fromisoformat(str(appt['book_time'])[:19])
        except ValueError:
            continue
        svc = ''
        if appt.get('service_id'):
            p = db.products.find_one({'id': appt['service_id']}, {'name': 1, '_id': 0})
            svc = (p or {}).get('name') or ''
        name = (appt.get('customer_name') or '').split(' ')[0] or _t(settings, 'there', 'quý khách')
        day = when.strftime('%a %b %d') if settings['language'] == 'en' else when.strftime('%d/%m')
        hour = when.strftime('%I:%M %p').lstrip('0') if settings['language'] == 'en' else when.strftime('%H:%M')
        body = _t(settings,
                  f"Hi {name}, this is {settings['business_name']}: reminder of your {svc + ' ' if svc else ''}appointment {day} at {hour}. Need to change it? Reply here or call us.",
                  f"Chào {name}, {settings['business_name']} nhắc lịch hẹn {svc + ' ' if svc else ''}lúc {hour} ngày {day}. Cần đổi lịch, vui lòng trả lời tin này hoặc gọi tiệm.")
        sms, email = _customer_contacts(business_id, appt.get('customer_phone'), appt.get('customer_email'), settings)
        queued = None
        if sms and settings['twilio_ready']:
            queued = queue(business_id, 'sms', sms, body, 'appointment_reminder', dedupe_key=f"rem:{business_id}:{appt['id']}:sms", meta={'appointment_id': appt['id']})
        elif email:
            queued = queue(business_id, 'email', email, body, 'appointment_reminder', subject=_t(settings, f"Appointment reminder — {settings['business_name']}", f"Nhắc lịch hẹn — {settings['business_name']}"),
                           dedupe_key=f"rem:{business_id}:{appt['id']}:email", meta={'appointment_id': appt['id']})
        if queued:
            n += 1
        elif settings['country'] == 'VN':
            continue  # tiệm Việt Nam không có SMS/email cho khách này: để luồng nhắc qua Zalo/Messenger cũ xử lý
        db.appointments.update_one({'id': appt['id'], 'business_id': business_id}, {'$set': {'reminder_sent': True, 'reminder_sent_at': now_utc.isoformat()}})
    return n


def _order_contact(o):
    """(SĐT, tên, email) của khách trên 1 đơn. Mọi luồng thanh toán lưu chúng trong order['metadata'] (schema chuẩn hoá —
    top-level chỉ còn id/business_id/created_at/total_amount/status/payment_method); top-level chỉ là dự phòng cho đơn cũ."""
    meta = o.get('metadata') if isinstance(o.get('metadata'), dict) else {}
    pick = lambda k: str(meta.get(k) or o.get(k) or '').strip()  # noqa: E731
    return pick('customer_phone'), pick('customer_name'), pick('customer_email')


def produce_review_requests(business_id, settings, now_utc):
    """Đơn đã thanh toán trong (review_delay_minutes .. 48 giờ) qua, khách có SĐT/email, chưa xin đánh giá -> xin đánh giá
    (link Google của tiệm). Mỗi khách tối đa 1 lần / review_cooldown_days ngày; khách đã STOP/huỷ đăng ký không nhận; tin
    được pump gửi trong khung giờ của tiệm. Không lọc theo số sao: ai cũng nhận cùng 1 lời mời (FTC/Google cấm "chỉ khách vui")."""
    if not settings['reviews_enabled'] or not settings['google_review_url']:
        return 0
    since = _server_naive(now_utc - timedelta(hours=48)).isoformat()
    until = _server_naive(now_utc - timedelta(minutes=int(settings['review_delay_minutes'] or 90))).isoformat()
    cooldown = max(7, int(settings.get('review_cooldown_days') or 60))
    n = 0
    has = {'$nin': [None, '']}
    # chỉ đơn CÓ liên lạc của khách — đơn vãng lai không SĐT/email không chiếm suất 200 đơn mỗi lượt
    q = {'business_id': business_id, 'status': {'$in': ['completed', 'paid']}, 'review_requested': {'$ne': True},
         'created_at': {'$gte': since, '$lte': until},
         '$or': [{'metadata.customer_phone': has}, {'metadata.customer_email': has}, {'customer_phone': has}, {'customer_email': has}]}
    for o in db.orders.find(q, {'_id': 0, 'id': 1, 'metadata': 1, 'customer_phone': 1, 'customer_name': 1, 'customer_email': 1}).limit(200):
        phone, name, email = _order_contact(o)
        cust = (db.customers.find_one({'business_id': business_id, 'phone': phone},
                                      {'_id': 0, 'id': 1, 'name': 1, 'email': 1, 'zalo_user_id': 1, 'fb_psid': 1}) or {}) if phone else {}
        contact = {'phone': phone, 'email': email or cust.get('email') or '',
                   'zalo_user_id': cust.get('zalo_user_id'), 'fb_psid': cust.get('fb_psid')}
        if cust.get('id') is not None:
            contact['id'] = cust['id']
        db.orders.update_one({'id': o['id'], 'business_id': business_id}, {'$set': {'review_requested': True}})
        # đã xin đánh giá khách này (bất kỳ địa chỉ nào của họ) trong N ngày qua thì thôi — không làm phiền khách quen
        sms, em = _customer_contacts(business_id, contact['phone'], contact['email'], settings)
        addrs = [x for x in (sms, em, str(contact.get('zalo_user_id') or ''), str(contact.get('fb_psid') or '')) if x and x != 'None']
        if not addrs:
            continue
        recent = db.outbound_messages.count_documents({'business_id': business_id, 'kind': 'review_request', 'to': {'$in': addrs},
                                                       'created_at': {'$gte': (now_utc - timedelta(days=cooldown)).isoformat()}})
        if recent:
            continue
        first = first_name(name or cust.get('name'), settings)
        body = _t(settings,
                  f"Hi {first}, thanks for visiting {settings['business_name']}! Would you mind leaving us a quick review? {settings['google_review_url']}",
                  f"Chào {first}, cảm ơn bạn đã ghé {settings['business_name']}! Bạn để lại giúp tiệm một đánh giá nhé: {settings['google_review_url']}")
        ch, status, _qid = queue_customer_message(business_id, contact, body, 'review_request', settings=settings, now_utc=now_utc,
                                                  dedupe_key=f"rev:{business_id}:{o['id']}", meta={'order_id': o['id']})
        if status == 'queued':
            n += 1
    return n


def produce_nurture(business_id, settings, now_utc):
    """Tin chăm sóc khách AI đã được chủ tiệm DUYỆT -> xếp hàng gửi lúc approved_at + step_delay, theo kênh chiến dịch
    (sms | email | zalo | messenger — giá trị cũ 'SMS'/'ZALO'/'FACEBOOK'/'zalo_oa' được chuẩn hoá). Zalo/Messenger đi qua kênh
    CHÍNH tiệm nối ở Hộp thư chung tới zalo_user_id/fb_psid của khách; tiệm chưa nối / khách chưa liên kết -> SMS/email.
    Tới giờ gửi mà khách ngoài khung trả lời của nền tảng -> pump chuyển SMS/email hoặc bỏ qua (ghi lý do). Trước đây tin
    Zalo/Messenger bị bỏ qua ở đây để chờ message_delivery_worker.py — worker đó không được lên lịch nên không tin nào đi."""
    n = 0
    q = {'business_id': business_id, 'approval_status': 'APPROVED', 'queued': {'$ne': True}, 'sent_at': None,
         'delivery_status': {'$nin': ['success', 'failed_permanent']}}
    for m in db.campaign_messages.find(q, {'_id': 0}).limit(500):
        approved_at = m.get('approved_at')
        try:
            base = datetime.fromisoformat(approved_at) if approved_at else now_utc
        except ValueError:
            base = now_utc
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        due = base + timedelta(days=int(m.get('step_delay') or 0))
        channel = normalize_channel(m.get('channel'), 'sms')
        upd = {'queued': True, 'channel': channel, 'scheduled_for': due.isoformat()}
        if due < now_utc - timedelta(days=STALE_NURTURE_DAYS):
            # tin Zalo/Messenger duyệt từ lâu mà chưa từng gửi (worker cũ không chạy): gửi bây giờ là sai ngữ cảnh ("đã 45 ngày")
            upd.update({'delivery_status': 'expired', 'delivery_error': f'not sent within {STALE_NURTURE_DAYS} days of its date'})
            db.campaign_messages.update_one({'id': m['id'], 'business_id': business_id}, {'$set': upd})
            continue
        cust = db.customers.find_one({'business_id': business_id, 'id': m.get('customer_id')},
                                     {'_id': 0, 'id': 1, 'phone': 1, 'email': 1, 'zalo_user_id': 1, 'fb_psid': 1}) or {}
        ch, status, qid = queue_customer_message(
            business_id, cust, m['message_body'], 'nurture', settings=settings, now_utc=now_utc, send_after=due,
            subject=subject_for('nurture', settings), dedupe_key=f"nur:{m['id']}", preferred=channel,
            meta={'campaign_message_id': m['id'], 'campaign_id': m.get('campaign_id'), 'customer_id': m.get('customer_id')})
        upd['delivery_status'] = 'queued' if status in ('queued', 'duplicate') else status
        if ch:
            upd['delivery_channel'] = ch
        if status == 'skipped':
            upd['delivery_error'] = 'outside messaging window'
        db.campaign_messages.update_one({'id': m['id'], 'business_id': business_id}, {'$set': upd})
        if qid:
            n += 1
    return n


def low_stock(business_id):
    """Sản phẩm đang bán có tồn <= ngưỡng "nguy cấp" của tiệm (trang Cảnh báo tồn kho, mặc định 5), ít nhất trước."""
    doc = db.system_settings.find_one({'key': 'inventory_thresholds', 'business_id': business_id}, {'value': 1, '_id': 0})
    try:
        critical = float(json.loads(doc['value']).get('critical', 5)) if doc else 5.0
    except (ValueError, TypeError, AttributeError):
        critical = 5.0
    rows = db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}, 'stock': {'$lte': critical}},
                            {'_id': 0, 'name': 1, 'stock': 1}).sort('stock', 1).limit(30)
    return [{'name': r.get('name') or '?', 'stock': float(r.get('stock') or 0)} for r in rows]


def produce_owner_report(business_id, settings, now_utc):
    """Sau 7 giờ sáng (giờ tiệm): gửi email tóm tắt NGÀY HÔM QUA cho chủ tiệm (1 lần/ngày)."""
    if not settings['owner_report_enabled']:
        return 0
    tz = ZoneInfo(settings['timezone'])
    local = now_utc.astimezone(tz)
    if local.hour < 7:
        return 0
    day = (local - timedelta(days=1)).date()
    to = settings['owner_report_email']
    if not to:
        owner = db.users.find_one({'business_id': business_id, 'role': {'$in': ['admin', 'owner']}}, {'email': 1, '_id': 0}) or {}
        to = owner.get('email') or ''
    if not to or (to.endswith('@bitpawdemo.com') and not os.environ.get('MESSAGING_DEMO_REPORTS')):
        return 0
    start_local = datetime.combine(day, datetime.min.time())
    end_local = start_local + timedelta(days=1)
    # ngày hôm qua theo giờ TIỆM -> quy về hệ giờ lưu created_at của máy chủ
    rng = {'$gte': _server_naive(start_local.replace(tzinfo=tz)).isoformat(), '$lt': _server_naive(end_local.replace(tzinfo=tz)).isoformat()}
    orders = list(db.orders.find({'business_id': business_id, 'status': {'$in': ['completed', 'paid']}, 'created_at': rng},
                                 {'_id': 0, 'total_amount': 1, 'payment_method': 1}))
    revenue = sum(float(o.get('total_amount') or 0) for o in orders)
    cash = sum(float(o.get('total_amount') or 0) for o in orders if (o.get('payment_method') or '').lower() in ('cash', 'tien_mat', 'tiền mặt'))
    today = local.date()
    appts_tomorrow = db.appointments.count_documents({'business_id': business_id, 'status': {'$in': ['pending', 'confirmed']},
                                                      'book_time': {'$gte': today.isoformat(), '$lt': (today + timedelta(days=1)).isoformat()}})
    new_customers = db.customers.count_documents({'business_id': business_id, 'created_at': rng})
    biz = _business(business_id)
    low = low_stock(business_id)
    low_txt = ', '.join(f"{x['name']} ({x['stock']:g})" for x in low[:6]) + (f" +{len(low) - 6}" if len(low) > 6 else '')
    cur = (biz.get('currency') or 'USD').upper()
    sym = {'USD': '$', 'AUD': 'A$', 'CAD': 'C$', 'NZD': 'NZ$', 'GBP': '£'}.get(cur, '')
    money = (lambda v: f"{sym}{v:,.2f}") if sym else (lambda v: f"{int(v):,}đ".replace(',', '.'))
    body = _t(settings,
              f"{settings['business_name']} — {day.strftime('%A, %B %d')}\n\nSales: {money(revenue)} from {len(orders)} bills\nCash to have in the drawer: {money(cash)}\nNew customers: {new_customers}\nAppointments today: {appts_tomorrow}" + (f"\nLow stock: {low_txt}" if low else '') + "\n\nOpen BitPaw for the full report.",
              f"{settings['business_name']} — ngày {day.strftime('%d/%m/%Y')}\n\nDoanh thu: {money(revenue)} từ {len(orders)} bill\nTiền mặt phải có trong két: {money(cash)}\nKhách mới: {new_customers}\nLịch hẹn hôm nay: {appts_tomorrow}" + (f"\nSắp hết hàng: {low_txt}" if low else '') + "\n\nMở BitPaw để xem báo cáo đầy đủ.")
    return 1 if queue(business_id, 'email', to, body, 'owner_report', subject=_t(settings, f"Daily report — {settings['business_name']}", f"Báo cáo ngày — {settings['business_name']}"),
                      dedupe_key=f"rep:{business_id}:{day.isoformat()}") else 0


def pump(business_id, base_url='', now_utc=None, produce=True, limit=40):
    """Tạo tin tự động tới hạn rồi gửi các tin đã tới giờ của 1 tiệm. An toàn khi gọi nhiều lần (dedupe)."""
    _ensure_indexes()
    now_utc = now_utc or datetime.now(timezone.utc)
    settings = get_settings(business_id)
    stats = {'produced': 0, 'sent': 0, 'failed': 0, 'deferred': 0, 'skipped': 0}
    # h4a: gói không có tin tự động (Essential / vừa hạ gói) -> không tạo tin tự động, và tin tự động đã xếp hàng bị huỷ
    # lúc tới hạn gửi (cron /api/cron/messages + /api/cron/daily_tasks, /api/messages/pump đều đi qua đây)
    automation_ok = automation_allowed(business_id)
    if produce and automation_ok:
        for fn in (produce_appointment_reminders, produce_review_requests, produce_nurture, produce_owner_report):
            try:
                stats['produced'] += fn(business_id, settings, now_utc)
            except Exception as e:
                print(f"[messaging] {fn.__name__}[{business_id}]: {e}")
    # mốc "tới giờ" lấy SAU khi tạo tin (tin vừa xếp có send_after = lúc xếp, muộn hơn now_utc vài ms)
    cutoff = max(now_utc, datetime.now(timezone.utc))
    due = list(db.outbound_messages.find({'business_id': business_id, 'status': 'queued', 'send_after': {'$lte': cutoff.isoformat()}},
                                         {'_id': 0}).sort('send_after', 1).limit(limit))
    for m in due:
        if m['kind'] in AUTOMATED_KINDS and not automation_ok:
            _cancel_plan_blocked(m)
            stats['skipped'] += 1
            continue
        transactional = m['kind'] in ('owner_report', 'missed_call', 'test', 'on_my_way', 'staff_alert')
        if not transactional and not in_send_window(settings, now_utc):
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {'send_after': next_window_start_utc(settings, now_utc).isoformat()}})
            stats['deferred'] += 1
            continue
        if m['kind'] != 'test' and is_opted_out(business_id, m['channel'], m['to']):
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {'status': 'cancelled', 'error': 'opted out'}})
            _sync_campaign(m, {'delivery_status': 'opted_out'})
            stats['skipped'] += 1
            continue
        # khoá nhẹ: chỉ 1 tiến trình được gửi tin này
        lock = db.outbound_messages.update_one({'id': m['id'], 'status': 'queued'}, {'$set': {'status': 'sending'}, '$inc': {'attempts': 1}})
        if lock.modified_count != 1:
            continue
        try:
            provider_id = send_now(m, settings, base_url, now_utc=now_utc)
            _mark_sent(m, provider_id)
            stats['sent'] += 1
        except OutsideWindow as e:
            # Messenger/Zalo ngoài khung: KHÔNG gửi (luật nền tảng) — SMS/email nếu khách có, không thì bỏ qua có lý do
            _ch, delivered = _reroute(m, settings, base_url, 'outside messaging window')
            print(f"[messaging] {m['id']} {e}")
            stats['skipped'] += 1
            stats['sent'] += 1 if delivered else 0
        except Exception as e:
            attempts = (m.get('attempts') or 0) + 1
            final = attempts >= MAX_ATTEMPTS or 'not connected' in str(e).lower()
            if final and m['channel'] in SOCIAL_CHANNELS and (m.get('meta') or {}).get('fallback'):
                _ch, delivered = _reroute(m, settings, base_url, str(e)[:160], only_if_fallback=True)
                if _ch:
                    stats['skipped'] += 1
                    stats['sent'] += 1 if delivered else 0
                    continue
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {
                'status': 'failed' if final else 'queued', 'error': str(e)[:300],
                'send_after': (now_utc + timedelta(minutes=15 * attempts)).isoformat()}})
            if final:
                _sync_campaign(m, {'delivery_status': 'failed', 'delivery_error': str(e)[:200]})
            stats['failed'] += 1
    return stats


def recent_log(business_id, limit=50):
    return list(db.outbound_messages.find({'business_id': business_id}, {'_id': 0, 'business_id': 0, 'dedupe_key': 0, 'meta.contact': 0})
                .sort('id', -1).limit(limit))


# ---------------------------------------------------------------- webhook Twilio
def validate_twilio_signature(auth_token, url, params, signature):
    """Chuẩn của Twilio: HMAC-SHA1(url + các cặp key+value theo thứ tự key), base64."""
    s = url + ''.join(k + (params.get(k) or '') for k in sorted(params.keys()))
    digest = base64.b64encode(hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(digest, signature or '')


def twilio_auth_token(business_id):
    t = nurture_channel_tokens.get_channel_token(business_id, 'twilio')
    return (t or {}).get('access_token') or ''


def handle_inbound_sms(business_id, from_number, body):
    """STOP/START/HELP theo chuẩn nhà mạng. Trả câu trả lời (hoặc '' nếu không cần trả lời)."""
    settings = get_settings(business_id)
    word = (body or '').strip().lower()
    if word in STOP_WORDS:
        opt_out(business_id, 'sms', from_number, source='STOP')
        return _t(settings, f"You're unsubscribed from {settings['business_name']} texts. Reply START to resubscribe.",
                  f"Bạn đã ngừng nhận tin từ {settings['business_name']}. Trả lời START để nhận lại.")
    if word in START_WORDS:
        opt_in(business_id, 'sms', from_number)
        return _t(settings, f"You're resubscribed to {settings['business_name']} texts. Reply STOP to opt out.",
                  f"Bạn đã nhận lại tin từ {settings['business_name']}. Trả lời STOP để ngừng.")
    if word in ('help', 'info'):
        return _t(settings, f"{settings['business_name']}: appointment and visit messages. Reply STOP to opt out. Call {settings['shop_phone'] or 'us'} for help.",
                  f"{settings['business_name']}: tin lịch hẹn và chăm sóc khách. Trả lời STOP để ngừng nhận.")
    # tin trả lời bình thường của khách -> lưu cho chủ tiệm xem (Twilio vẫn chuyển tiếp nếu tiệm cấu hình)
    db.inbound_messages.insert_one({'id': next_mongo_id('inbound_messages'), 'business_id': business_id, 'channel': 'sms',
                                    'from': from_number, 'body': (body or '')[:1600], 'created_at': datetime.now(timezone.utc).isoformat()})
    # Hộp thư chung (app.py::_inbox_sms_inbound): tin hiện trong /ai_bot cạnh Messenger/Zalo/..., AI trả lời nếu đang bật
    if inbox_hook is not None:
        try:
            return inbox_hook(business_id, from_number, body) or ''
        except Exception as e:
            print(f"[sms inbox] {e}")
    return ''
