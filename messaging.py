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
"""
import base64
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

TWILIO_API_BASE = os.environ.get('TWILIO_API_BASE', 'https://api.twilio.com').rstrip('/')
DEFAULT_TZ = {'US': 'America/New_York', 'AU': 'Australia/Sydney', 'VN': 'Asia/Ho_Chi_Minh', 'CA': 'America/Toronto',
              'NZ': 'Pacific/Auckland', 'GB': 'Europe/London'}
MARKETING_KINDS = {'review_request', 'nurture', 'promo', 'winback'}
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
}


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
    if channel not in ('sms', 'email') or not to or not body:
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


def send_now(msg, settings, base_url=''):
    """Gửi 1 tin của hàng đợi ngay (đã kiểm tra khung giờ/từ chối ở pump)."""
    body = msg['body']
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
    lock = db.outbound_messages.update_one({'id': msg_id, 'status': 'queued'}, {'$set': {'status': 'sending'}, '$inc': {'attempts': 1}})
    if lock.modified_count != 1:
        return False
    try:
        provider_id = send_now(m, get_settings(m['business_id']), base_url)
        db.outbound_messages.update_one({'id': msg_id}, {'$set': {'status': 'sent', 'sent_at': datetime.now(timezone.utc).isoformat(),
                                                                  'provider_id': provider_id}})
        return True
    except Exception as e:
        db.outbound_messages.update_one({'id': msg_id}, {'$set': {'status': 'queued', 'error': str(e)[:300],
                                                                  'send_after': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}})
        return False


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


def produce_review_requests(business_id, settings, now_utc):
    """Đơn đã thanh toán trong 2–48 giờ qua, khách có SĐT/email, chưa xin đánh giá -> xin đánh giá 5 sao (link Google của tiệm)."""
    if not settings['reviews_enabled'] or not settings['google_review_url']:
        return 0
    since = _server_naive(now_utc - timedelta(hours=48)).isoformat()
    until = _server_naive(now_utc - timedelta(minutes=int(settings['review_delay_minutes'] or 90))).isoformat()
    n = 0
    q = {'business_id': business_id, 'status': {'$in': ['completed', 'paid']}, 'review_requested': {'$ne': True},
         'created_at': {'$gte': since, '$lte': until}}
    for o in db.orders.find(q, {'_id': 0, 'id': 1, 'customer_phone': 1, 'customer_name': 1, 'customer_email': 1}).limit(200):
        phone = o.get('customer_phone')
        email = o.get('customer_email')
        if not phone and not email:
            continue
        # đã xin đánh giá khách này trong 60 ngày qua thì thôi (không làm phiền khách quen)
        sms, em = _customer_contacts(business_id, phone, email, settings)
        recent = db.outbound_messages.count_documents({'business_id': business_id, 'kind': 'review_request', 'to': {'$in': [x for x in (sms, em) if x]},
                                                       'created_at': {'$gte': (now_utc - timedelta(days=60)).isoformat()}})
        db.orders.update_one({'id': o['id'], 'business_id': business_id}, {'$set': {'review_requested': True}})
        if recent:
            continue
        name = (o.get('customer_name') or '').split(' ')[0] or _t(settings, 'there', 'bạn')
        body = _t(settings,
                  f"Hi {name}, thanks for visiting {settings['business_name']}! Would you mind leaving us a quick review? {settings['google_review_url']}",
                  f"Chào {name}, cảm ơn bạn đã ghé {settings['business_name']}! Bạn để lại giúp tiệm một đánh giá nhé: {settings['google_review_url']}")
        if sms and settings['twilio_ready'] and queue(business_id, 'sms', sms, body, 'review_request', dedupe_key=f"rev:{business_id}:{o['id']}"):
            n += 1
        elif em and queue(business_id, 'email', em, body, 'review_request', subject=_t(settings, f"How was your visit to {settings['business_name']}?", f"Bạn thấy {settings['business_name']} thế nào?"), dedupe_key=f"rev:{business_id}:{o['id']}"):
            n += 1
    return n


def produce_nurture(business_id, settings, now_utc):
    """Tin chăm sóc khách AI đã được chủ tiệm DUYỆT -> tới ngày (approved_at + step_delay) thì gửi theo kênh chiến dịch."""
    n = 0
    for m in db.campaign_messages.find({'business_id': business_id, 'approval_status': 'APPROVED', 'queued': {'$ne': True}}, {'_id': 0}).limit(500):
        approved_at = m.get('approved_at')
        try:
            base = datetime.fromisoformat(approved_at) if approved_at else now_utc
        except ValueError:
            base = now_utc
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        due = base + timedelta(days=int(m.get('step_delay') or 0))
        cust = db.customers.find_one({'business_id': business_id, 'id': m.get('customer_id')}, {'_id': 0, 'phone': 1, 'email': 1}) or {}
        channel = (m.get('channel') or '').upper()
        sms, em = _customer_contacts(business_id, cust.get('phone'), cust.get('email'), settings)
        qid = None
        if channel in ('SMS', '') and sms and settings['twilio_ready']:
            qid = queue(business_id, 'sms', sms, m['message_body'], 'nurture', send_after=due, dedupe_key=f"nur:{m['id']}")
        elif channel in ('EMAIL', 'SMS', '') and em:
            qid = queue(business_id, 'email', em, m['message_body'], 'nurture', send_after=due,
                        subject=_t(settings, f"A note from {settings['business_name']}", f"{settings['business_name']} gửi bạn"), dedupe_key=f"nur:{m['id']}")
        if channel in ('ZALO', 'FACEBOOK'):
            continue  # Zalo/Messenger: message_delivery_worker.py (API riêng của từng nền tảng)
        status = 'queued' if qid else 'no_contact'
        db.campaign_messages.update_one({'id': m['id'], 'business_id': business_id},
                                        {'$set': {'queued': True, 'delivery_status': status, 'scheduled_for': due.isoformat()}})
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
    if produce:
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
        transactional = m['kind'] in ('owner_report', 'missed_call', 'test', 'on_my_way', 'staff_alert')
        if not transactional and not in_send_window(settings, now_utc):
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {'send_after': next_window_start_utc(settings, now_utc).isoformat()}})
            stats['deferred'] += 1
            continue
        if m['kind'] != 'test' and is_opted_out(business_id, m['channel'], m['to']):
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {'status': 'cancelled', 'error': 'opted out'}})
            stats['skipped'] += 1
            continue
        # khoá nhẹ: chỉ 1 tiến trình được gửi tin này
        lock = db.outbound_messages.update_one({'id': m['id'], 'status': 'queued'}, {'$set': {'status': 'sending'}, '$inc': {'attempts': 1}})
        if lock.modified_count != 1:
            continue
        try:
            provider_id = send_now(m, settings, base_url)
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {'status': 'sent', 'sent_at': datetime.now(timezone.utc).isoformat(), 'provider_id': provider_id}})
            stats['sent'] += 1
        except Exception as e:
            attempts = (m.get('attempts') or 0) + 1
            final = attempts >= MAX_ATTEMPTS or 'not connected' in str(e).lower()
            db.outbound_messages.update_one({'id': m['id']}, {'$set': {
                'status': 'failed' if final else 'queued', 'error': str(e)[:300],
                'send_after': (now_utc + timedelta(minutes=15 * attempts)).isoformat()}})
            stats['failed'] += 1
    return stats


def recent_log(business_id, limit=50):
    return list(db.outbound_messages.find({'business_id': business_id}, {'_id': 0, 'business_id': 0, 'dedupe_key': 0}).sort('id', -1).limit(limit))


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


def missed_call_reply(business_id, caller, booking_url):
    settings = get_settings(business_id)
    if not settings['missed_call_enabled'] or not caller:
        return None
    if is_opted_out(business_id, 'sms', caller):
        return None
    body = _t(settings,
              f"Hi, this is {settings['business_name']} — sorry we missed your call! " + (f"Book online anytime: {booking_url} " if booking_url else '') + "or reply here and we'll get back to you shortly.",
              f"{settings['business_name']} xin lỗi vì chưa nghe máy được! " + (f"Đặt lịch online: {booking_url} " if booking_url else '') + "hoặc trả lời tin này, tiệm sẽ liên hệ lại ngay.")
    # mỗi số tối đa 1 tin / 30 phút (gọi lại liên tục không bị nhắn liên tục)
    bucket = datetime.now(timezone.utc).strftime('%Y%m%d%H') + str(datetime.now(timezone.utc).minute // 30)
    return queue(business_id, 'sms', caller, body, 'missed_call', dedupe_key=f"mc:{business_id}:{caller}:{bucket}")
