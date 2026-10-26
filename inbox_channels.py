"""
Hộp thư chung (Unified Inbox) — gom tin nhắn Messenger, Instagram, WhatsApp, Zalo OA, Viber, SMS (Twilio) và chat trên
website vào CÙNG hội thoại bot_customers/bot_messages mà màn /ai_bot đang hiển thị; chủ tiệm trả lời trong 1 khung, tin đi
ngược về đúng kênh khách đã nhắn (khung chỉ khác nhau ở nhãn kênh).

Mỗi kênh của mỗi tiệm = 1 doc db.inbox_channels:
    {business_id, channel, account_name, external_id, access_token_enc, secret_enc, hook_key, verify_token,
     ai_auto_reply, status, connected_at, updated_at, last_inbound_at, last_error, (zalo) app_id, refresh_token_enc}
Webhook: /webhooks/inbox/<channel>/<hook_key> — hook_key ngẫu nhiên riêng từng tiệm + kênh (không đoán được), và MỌI
POST phải mang chữ ký đúng của nền tảng (fail-closed: thiếu secret -> từ chối).
Hội thoại: bot_customers.id = "<business_id>:<channel>:<id người gửi trên nền tảng>"; chat website giữ id cũ
"<business_id>:<SĐT>" (channel 'web').

Thử nghiệm local: INBOX_META_API_BASE / INBOX_ZALO_API_BASE / INBOX_ZALO_OAUTH_BASE / INBOX_VIBER_API_BASE trỏ về máy giả
(scripts/unified_inbox_e2e.mjs) — KHÔNG gửi tin thật.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta

import requests

from mongo_client import db
import nurture_channel_tokens as _vault

META_API = os.environ.get('INBOX_META_API_BASE', 'https://graph.facebook.com').rstrip('/')
ZALO_API = os.environ.get('INBOX_ZALO_API_BASE', 'https://openapi.zalo.me').rstrip('/')
ZALO_OAUTH = os.environ.get('INBOX_ZALO_OAUTH_BASE', 'https://oauth.zaloapp.com').rstrip('/')
VIBER_API = os.environ.get('INBOX_VIBER_API_BASE', 'https://chatapi.viber.com').rstrip('/')
GRAPH_V = 'v21.0'
TIMEOUT = 12

# Thứ tự = thứ tự chip lọc trên màn hộp thư
CHANNELS = {
    'web': {'label': 'Website', 'max_len': 2000},
    'messenger': {'label': 'Messenger', 'max_len': 1900},
    'instagram': {'label': 'Instagram', 'max_len': 990},
    'whatsapp': {'label': 'WhatsApp', 'max_len': 4000},
    'zalo': {'label': 'Zalo', 'max_len': 1900},
    'viber': {'label': 'Viber', 'max_len': 6500},
    'sms': {'label': 'SMS', 'max_len': 1500},
}
# Kênh nối bằng webhook của trang này (SMS nối ở /settings/messaging qua Twilio; website có sẵn)
CONNECTABLE = ('messenger', 'instagram', 'whatsapp', 'zalo', 'viber')
META_CHANNELS = ('messenger', 'instagram', 'whatsapp')


class ChannelError(Exception):
    """Lỗi có thể nói thẳng với chủ tiệm (token sai, kênh chưa nối, ngoài khung 24 giờ...). `code` + `ch` + `detail` để
    giao diện hiện đúng ngôn ngữ của chủ tiệm (ai_bot.html / inbox_channels.html dịch theo mã); câu tiếng Anh là bản gốc."""

    def __init__(self, message, code='provider', ch=None, detail=None):
        super().__init__(message)
        self.code, self.ch, self.detail = code, ch, detail

    def as_dict(self):
        return {'error': str(self)[:300], 'code': self.code, 'ch': self.ch, 'detail': (str(self.detail)[:200] if self.detail else None)}


# ---------------------------------------------------------------- kết nối
def _doc(business_id, channel):
    return db.inbox_channels.find_one({'business_id': business_id, 'channel': channel}, {'_id': 0})


def get_connection(business_id, channel):
    d = _doc(business_id, channel)
    return d if d and d.get('status') == 'connected' else None


def find_by_hook(channel, hook_key):
    if channel not in CONNECTABLE or not isinstance(hook_key, str) or not (16 <= len(hook_key) <= 64):
        return None
    d = db.inbox_channels.find_one({'channel': channel, 'hook_key': hook_key}, {'_id': 0})
    return d if d and d.get('status') == 'connected' else None


def webhook_url(base_url, channel, hook_key):
    return f"{base_url.rstrip('/')}/webhooks/inbox/{channel}/{hook_key}"


def _meta_error(r):
    """(mã, câu) từ lỗi Graph API của Meta."""
    try:
        e = (r.json() or {}).get('error') or {}
    except ValueError:
        return 'provider', f"HTTP {r.status_code}"
    code, sub = e.get('code'), e.get('error_subcode')
    if code == 10 and sub == 2018278 or code == 131047:
        return 'window_24h', "Outside the 24-hour reply window — the customer must message you again before you can reply here."
    if code == 190:
        return 'token_invalid', "The access token is invalid or has expired."
    return 'provider', e.get('message') or f"HTTP {r.status_code}"


def _rejected(channel, what, detail):
    return ChannelError(f"{CHANNELS[channel]['label']} rejected the {what}: {detail}", 'rejected', CHANNELS[channel]['label'], detail)


def _verify_with_provider(channel, token, external_id, extra):
    """Hỏi THẬT nền tảng xem token có dùng được không (không báo 'đã kết nối' khi token sai). Trả (external_id, account_name)."""
    try:
        if channel == 'messenger':
            r = requests.get(f"{META_API}/{GRAPH_V}/me", params={'fields': 'id,name', 'access_token': token}, timeout=TIMEOUT)
            if r.status_code >= 300:
                raise _rejected(channel, 'Page token', _meta_error(r)[1])
            j = r.json()
            if external_id and str(j.get('id')) != str(external_id):
                raise ChannelError("This token belongs to a different Page than the Page ID you entered.", 'page_mismatch')
            return str(j.get('id') or external_id), j.get('name') or ''
        if channel == 'instagram':
            r = requests.get(f"{META_API}/{GRAPH_V}/{external_id}", params={'fields': 'id,username', 'access_token': token}, timeout=TIMEOUT)
            if r.status_code >= 300:
                raise _rejected(channel, 'token / account ID', _meta_error(r)[1])
            j = r.json()
            return str(j.get('id') or external_id), ('@' + j['username']) if j.get('username') else ''
        if channel == 'whatsapp':
            r = requests.get(f"{META_API}/{GRAPH_V}/{external_id}", params={'fields': 'display_phone_number,verified_name'},
                             headers={'Authorization': f'Bearer {token}'}, timeout=TIMEOUT)
            if r.status_code >= 300:
                raise _rejected(channel, 'token / phone number ID', _meta_error(r)[1])
            j = r.json()
            name = ' · '.join(x for x in (j.get('verified_name'), j.get('display_phone_number')) if x)
            return str(external_id), name
        if channel == 'zalo':
            r = requests.get(f"{ZALO_API}/v2.0/oa/getoa", headers={'access_token': token}, timeout=TIMEOUT)
            j = r.json() if r.content else {}
            if j.get('error') not in (0, None) or r.status_code >= 300:
                raise _rejected(channel, 'OA access token', j.get('message') or r.status_code)
            d = j.get('data') or {}
            return str(d.get('oa_id') or external_id or ''), d.get('name') or ''
        if channel == 'viber':
            r = requests.post(f"{VIBER_API}/pa/get_account_info", headers={'X-Viber-Auth-Token': token}, json={}, timeout=TIMEOUT)
            j = r.json() if r.content else {}
            if j.get('status') != 0:
                raise _rejected(channel, 'bot token', j.get('status_message') or r.status_code)
            return str(j.get('id') or j.get('uri') or ''), j.get('name') or ''
    except requests.exceptions.RequestException as e:
        raise ChannelError(f"Could not reach {CHANNELS[channel]['label']}: {str(e)[:120]}", 'unreachable', CHANNELS[channel]['label'])
    raise ChannelError('Unsupported channel', 'unsupported')


def _viber_set_webhook(token, url):
    try:
        r = requests.post(f"{VIBER_API}/pa/set_webhook", headers={'X-Viber-Auth-Token': token},
                          json={'url': url, 'event_types': ['delivered', 'seen', 'failed', 'conversation_started'], 'send_name': True},
                          timeout=TIMEOUT)
        j = r.json() if r.content else {}
    except requests.exceptions.RequestException as e:
        raise ChannelError(f"Could not reach Viber: {str(e)[:120]}", 'unreachable', 'Viber')
    if j.get('status') != 0:
        detail = j.get('status_message') or r.status_code
        raise ChannelError(f"Viber did not accept the webhook address: {detail} "
                           "(Viber needs a public https address — it works on your live site).", 'viber_webhook', 'Viber', detail)


def connect(business_id, channel, fields, base_url):
    """fields: access_token (bắt buộc), external_id (Page ID / Instagram ID / Phone number ID), app_secret (Meta) hoặc
    oa_secret (Zalo), app_id + refresh_token (Zalo, để tự gia hạn token 25 giờ). Trả trạng thái công khai."""
    if channel not in CONNECTABLE:
        raise ChannelError('Unsupported channel', 'unsupported')
    f = {k: (v.strip() if isinstance(v, str) else '') for k, v in (fields or {}).items()}
    token = f.get('access_token', '')
    external_id = f.get('external_id', '')
    if not token:
        raise ChannelError('Paste the access token first.', 'need_token')
    if channel in ('instagram', 'whatsapp') and not external_id:
        raise (ChannelError('Instagram account ID is required.', 'need_ig_id') if channel == 'instagram'
               else ChannelError('Phone number ID is required.', 'need_phone_id'))
    secret = ''
    if channel in META_CHANNELS:
        secret = f.get('app_secret', '')
        if not secret and not os.environ.get('META_APP_SECRET'):
            raise ChannelError('App secret is required — it lets BitPaw check that messages really come from Meta.', 'need_app_secret')
    elif channel == 'zalo':
        secret = f.get('oa_secret', '')
        if not secret:
            raise ChannelError('OA secret key is required — it lets BitPaw check that messages really come from Zalo.', 'need_oa_secret')
    ext_id, name = _verify_with_provider(channel, token, external_id, f)
    old = _doc(business_id, channel) or {}
    hook_key = old.get('hook_key') or secrets.token_urlsafe(18)
    if channel == 'viber':
        _viber_set_webhook(token, webhook_url(base_url, channel, hook_key))
    now = datetime.now().isoformat()
    doc = {
        'business_id': business_id, 'channel': channel, 'status': 'connected',
        'account_name': (name or f.get('account_name') or '')[:120], 'external_id': ext_id[:80],
        'access_token_enc': _vault.encrypt_secret(token), 'hook_key': hook_key,
        'verify_token': old.get('verify_token') or secrets.token_urlsafe(16),
        'ai_auto_reply': ai_auto_reply_on(business_id, channel, doc=old), 'connected_at': old.get('connected_at') or now,
        'token_saved_at': now, 'updated_at': now, 'last_error': None,
    }
    doc['secret_enc'] = _vault.encrypt_secret(secret) if secret else None
    if channel == 'zalo':
        doc['app_id'] = f.get('app_id', '')[:40]
        doc['app_secret_enc'] = _vault.encrypt_secret(f['app_secret']) if f.get('app_secret') else None
        doc['refresh_token_enc'] = _vault.encrypt_secret(f['refresh_token']) if f.get('refresh_token') else None
    db.inbox_channels.update_one({'business_id': business_id, 'channel': channel}, {'$set': doc}, upsert=True)
    return public_status(business_id, base_url)[channel]


def disconnect(business_id, channel):
    db.inbox_channels.update_one({'business_id': business_id, 'channel': channel},
                                 {'$set': {'status': 'disconnected', 'access_token_enc': None, 'secret_enc': None,
                                           'refresh_token_enc': None, 'app_secret_enc': None,
                                           'updated_at': datetime.now().isoformat()}})


def set_ai_auto_reply(business_id, channel, enabled):
    # ai_auto_reply_by_owner: phân biệt "chủ tiệm tự bật" với giá trị mặc định cũ (connect() từng ghi sẵn True cho mọi ngành)
    db.inbox_channels.update_one({'business_id': business_id, 'channel': channel},
                                 {'$set': {'ai_auto_reply': bool(enabled), 'ai_auto_reply_by_owner': True,
                                           'updated_at': datetime.now().isoformat()},
                                  '$setOnInsert': {'status': 'disconnected'}}, upsert=True)


def ai_default_on(business_id):
    """AI tự trả lời mặc định BẬT chỉ cho ngành có gói đặt lịch thật (Nails/Spa). Ngành khác mặc định TẮT — chủ tiệm tự
    bật thì AI chỉ hỏi đáp + chuyển yêu cầu cho nhân viên (ai_function_tools.QA_TOOLS), không bao giờ đặt lịch."""
    try:
        import ai_function_tools
        return ai_function_tools.has_booking_pack(business_id)
    except Exception:
        return False


def ai_auto_reply_on(business_id, channel, doc=None):
    d = doc if doc is not None else (db.inbox_channels.find_one({'business_id': business_id, 'channel': channel},
                                                                 {'ai_auto_reply': 1, 'ai_auto_reply_by_owner': 1, '_id': 0}) or {})
    if ai_default_on(business_id):
        return d.get('ai_auto_reply', True)
    # Ngành chưa có gói đặt lịch: chỉ BẬT khi chính chủ tiệm đã bật (giá trị True cũ do connect() tự ghi không tính)
    return bool(d.get('ai_auto_reply')) if d.get('ai_auto_reply_by_owner') else False


def public_status(business_id, base_url, sms_ready=False):
    """Trạng thái từng kênh cho màn hình (KHÔNG BAO GIỜ trả token/secret)."""
    docs = {d['channel']: d for d in db.inbox_channels.find({'business_id': business_id}, {'_id': 0})}
    counts = {r['_id'] or 'web': r['n'] for r in db.bot_customers.aggregate([
        {'$match': {'business_id': business_id}}, {'$group': {'_id': '$channel', 'n': {'$sum': 1}}}])}
    out = {}
    # 'booking' = AI đặt lịch thật (Nails/Spa); 'questions_and_handoff' = AI chỉ hỏi đáp + chuyển yêu cầu cho nhân viên
    ai_mode = 'booking' if ai_default_on(business_id) else 'questions_and_handoff'
    for ch, meta in CHANNELS.items():
        d = docs.get(ch) or {}
        connected = (d.get('status') == 'connected') if ch in CONNECTABLE else (True if ch == 'web' else bool(sms_ready))
        row = {'channel': ch, 'label': meta['label'], 'connected': connected, 'conversations': counts.get(ch, 0),
               'ai_auto_reply': ai_auto_reply_on(business_id, ch, doc=d), 'ai_mode': ai_mode, 'account_name': d.get('account_name') or '',
               'external_id': d.get('external_id') or '', 'last_inbound_at': d.get('last_inbound_at'),
               'last_error': d.get('last_error'), 'connected_at': d.get('connected_at')}
        if ch in CONNECTABLE and d.get('hook_key') and connected:
            row['webhook_url'] = webhook_url(base_url, ch, d['hook_key'])
            if ch in META_CHANNELS:
                row['verify_token'] = d.get('verify_token')
        if ch == 'zalo' and connected:
            row['auto_refresh'] = bool(d.get('refresh_token_enc'))
        out[ch] = row
    return out


# ---------------------------------------------------------------- chữ ký webhook
def _secret_for(doc):
    if doc['channel'] == 'viber':
        return _vault.decrypt_secret(doc.get('access_token_enc'))
    s = _vault.decrypt_secret(doc.get('secret_enc'))
    if not s and doc['channel'] in META_CHANNELS:
        s = os.environ.get('META_APP_SECRET')
    return s


def verify_signature(doc, raw_body, headers):
    """Fail-closed: chưa có secret, thiếu header hay sai chữ ký đều -> False."""
    secret = _secret_for(doc)
    if not secret or not isinstance(raw_body, (bytes, bytearray)):
        return False
    ch = doc['channel']
    if ch in META_CHANNELS:
        sig = headers.get('X-Hub-Signature-256', '')
        if not sig.startswith('sha256='):
            return False
        want = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig[7:], want)
    if ch == 'viber':
        sig = headers.get('X-Viber-Content-Signature', '')
        want = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return bool(sig) and hmac.compare_digest(sig, want)
    if ch == 'zalo':
        # Zalo: mac = sha256(app_id + nguyên văn body + timestamp + OA secret key)
        sig = headers.get('X-ZEvent-Signature', '')
        try:
            j = json.loads(raw_body)
        except ValueError:
            return False
        base = f"{j.get('app_id', '')}{raw_body.decode('utf-8', 'replace')}{j.get('timestamp', '')}{secret}"
        want = 'mac=' + hashlib.sha256(base.encode()).hexdigest()
        return bool(sig) and hmac.compare_digest(sig, want)
    return False


# ---------------------------------------------------------------- tin đến -> sự kiện chuẩn hoá
_ATTACH_LABEL = {'image': '[photo]', 'video': '[video]', 'audio': '[voice message]', 'file': '[file]', 'sticker': '[sticker]',
                 'location': '[location]', 'gif': '[GIF]', 'contacts': '[contact card]', 'document': '[file]',
                 'picture': '[photo]', 'url': '[link]'}


def _ev(kind, user_id, text, mid, name=None, phone=None):
    return {'kind': kind, 'user_id': str(user_id), 'text': (text or '').strip()[:2000], 'ext_msg_id': str(mid or '') or None,
            'name': (name or '').strip()[:80] or None, 'phone': phone}


def parse_events(channel, payload):
    """Trả list sự kiện {kind: 'customer'|'echo', user_id, text, ext_msg_id, name, phone}. Bỏ qua sự kiện không phải tin nhắn
    (đã xem, đã nhận, typing...). 'echo' = tin chính Page/OA gửi đi (vd nhân viên trả lời thẳng trong Meta Business Suite)."""
    out = []
    if not isinstance(payload, dict):
        return out
    try:
        if channel in ('messenger', 'instagram'):
            for entry in payload.get('entry') or []:
                for m in entry.get('messaging') or []:
                    msg = m.get('message') or {}
                    text = msg.get('text')
                    if not text and msg.get('attachments'):
                        text = ' '.join(_ATTACH_LABEL.get((a or {}).get('type'), '[attachment]') for a in msg['attachments'][:3])
                    if not text and (m.get('postback') or {}).get('title'):
                        text = m['postback']['title']
                    if not text:
                        continue
                    if msg.get('is_echo'):
                        out.append(_ev('echo', (m.get('recipient') or {}).get('id'), text, msg.get('mid')))
                    else:
                        out.append(_ev('customer', (m.get('sender') or {}).get('id'), text, msg.get('mid') or (m.get('postback') or {}).get('mid')))
        elif channel == 'whatsapp':
            for entry in payload.get('entry') or []:
                for ch in entry.get('changes') or []:
                    v = ch.get('value') or {}
                    names = {c.get('wa_id'): ((c.get('profile') or {}).get('name')) for c in v.get('contacts') or []}
                    for m in v.get('messages') or []:
                        t = m.get('type')
                        if t == 'text':
                            text = (m.get('text') or {}).get('body')
                        elif t in ('button', 'interactive'):
                            text = (m.get('button') or {}).get('text') or json.dumps(m.get('interactive') or {})[:200]
                        else:
                            text = _ATTACH_LABEL.get(t, '[message]') + ((' ' + (m.get(t) or {}).get('caption', '')) if isinstance(m.get(t), dict) else '')
                        wa = m.get('from')
                        if wa and text:
                            out.append(_ev('customer', wa, text, m.get('id'), names.get(wa), '+' + re.sub(r'\D', '', wa)))
        elif channel == 'zalo':
            ev = payload.get('event_name') or ''
            msg = payload.get('message') or {}
            text = msg.get('text')
            if not text and ev.endswith(('_image', '_gif', '_sticker', '_file', '_audio', '_video', '_location', '_link')):
                text = _ATTACH_LABEL.get(ev.rsplit('_', 1)[1], '[attachment]')
            if text and ev.startswith('user_send_'):
                out.append(_ev('customer', (payload.get('sender') or {}).get('id'), text, msg.get('msg_id')))
            elif text and ev.startswith('oa_send_'):
                out.append(_ev('echo', (payload.get('recipient') or {}).get('id'), text, msg.get('msg_id')))
        elif channel == 'viber':
            if payload.get('event') == 'message':
                s = payload.get('sender') or {}
                msg = payload.get('message') or {}
                text = msg.get('text') if msg.get('type') == 'text' else _ATTACH_LABEL.get(msg.get('type'), '[attachment]')
                if s.get('id') and text:
                    out.append(_ev('customer', s['id'], text, payload.get('message_token'), s.get('name')))
    except (AttributeError, TypeError, KeyError):
        return out
    return [e for e in out if e['user_id'] and e['user_id'] != 'None']


# ---------------------------------------------------------------- gửi tin
def _zalo_token(doc):
    """Token OA của Zalo sống 25 giờ: có refresh token thì tự gia hạn khi token đã quá 23 giờ."""
    token = _vault.decrypt_secret(doc.get('access_token_enc'))
    saved = doc.get('token_saved_at') or ''
    rt = _vault.decrypt_secret(doc.get('refresh_token_enc'))
    app_secret = _vault.decrypt_secret(doc.get('app_secret_enc'))
    if rt and doc.get('app_id') and app_secret and saved < (datetime.now() - timedelta(hours=23)).isoformat():
        try:
            r = requests.post(f"{ZALO_OAUTH}/v4/oa/access_token", headers={'secret_key': app_secret},
                              data={'refresh_token': rt, 'app_id': doc['app_id'], 'grant_type': 'refresh_token'}, timeout=TIMEOUT)
            j = r.json() if r.content else {}
            if j.get('access_token'):
                token = j['access_token']
                upd = {'access_token_enc': _vault.encrypt_secret(token), 'token_saved_at': datetime.now().isoformat()}
                if j.get('refresh_token'):
                    upd['refresh_token_enc'] = _vault.encrypt_secret(j['refresh_token'])
                db.inbox_channels.update_one({'business_id': doc['business_id'], 'channel': 'zalo'}, {'$set': upd})
        except requests.exceptions.RequestException:
            pass
    return token


def send_text(business_id, channel, user_id, text):
    """Gửi 1 tin chữ tới khách trên đúng kênh. Trả id tin của nền tảng; lỗi -> ChannelError (câu dễ hiểu)."""
    text = (text or '').strip()
    if not text:
        raise ChannelError('Empty message', 'empty')
    meta = CHANNELS.get(channel)
    if not meta:
        raise ChannelError('Unknown channel', 'unsupported')
    text = text[:meta['max_len']]
    if channel == 'web':
        return 'web'  # khách đang mở widget/booking page tự tải tin mới (SSE /api/portal/stream)
    if channel == 'sms':
        import messaging
        try:
            return messaging._twilio_send(messaging.get_settings(business_id), business_id, user_id, text)
        except messaging.SendError as e:
            raise ChannelError(str(e), 'not_connected' if 'not connected' in str(e) else 'provider', 'SMS', str(e))
    doc = get_connection(business_id, channel)
    if not doc:
        raise ChannelError(f"{meta['label']} is not connected — the reply is saved here but was not delivered.", 'not_connected', meta['label'])
    token = _zalo_token(doc) if channel == 'zalo' else _vault.decrypt_secret(doc.get('access_token_enc'))
    if not token:
        raise ChannelError(f"{meta['label']} token could not be read — reconnect this channel.", 'token_unreadable', meta['label'])
    try:
        if channel in ('messenger', 'instagram'):
            r = requests.post(f"{META_API}/{GRAPH_V}/me/messages", params={'access_token': token},
                              json={'recipient': {'id': user_id}, 'messaging_type': 'RESPONSE', 'message': {'text': text}}, timeout=TIMEOUT)
            if r.status_code >= 300:
                raise ChannelError(*reversed(_meta_error(r)), meta['label'])
            return (r.json() or {}).get('message_id') or ''
        if channel == 'whatsapp':
            r = requests.post(f"{META_API}/{GRAPH_V}/{doc['external_id']}/messages", headers={'Authorization': f'Bearer {token}'},
                              json={'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': re.sub(r'\D', '', user_id),
                                    'type': 'text', 'text': {'body': text, 'preview_url': False}}, timeout=TIMEOUT)
            if r.status_code >= 300:
                raise ChannelError(*reversed(_meta_error(r)), meta['label'])
            return (((r.json() or {}).get('messages') or [{}])[0]).get('id') or ''
        if channel == 'zalo':
            r = requests.post(f"{ZALO_API}/v3.0/oa/message/cs", headers={'access_token': token},
                              json={'recipient': {'user_id': user_id}, 'message': {'text': text}}, timeout=TIMEOUT)
            j = r.json() if r.content else {}
            if j.get('error') not in (0, None) or r.status_code >= 300:
                if j.get('error') in (-216, -124):
                    raise ChannelError("The Zalo access token has expired — reconnect Zalo (add the refresh token to keep it renewed).",
                                       'zalo_expired', 'Zalo')
                raise ChannelError(j.get('message') or f"HTTP {r.status_code}", 'provider', 'Zalo', j.get('message'))
            return str((j.get('data') or {}).get('message_id') or '')
        if channel == 'viber':
            biz = db.businesses.find_one({'id': business_id}, {'name': 1, '_id': 0}) or {}
            r = requests.post(f"{VIBER_API}/pa/send_message", headers={'X-Viber-Auth-Token': token},
                              json={'receiver': user_id, 'min_api_version': 1, 'type': 'text', 'text': text,
                                    'sender': {'name': (biz.get('name') or doc.get('account_name') or 'Shop')[:28]}}, timeout=TIMEOUT)
            j = r.json() if r.content else {}
            if j.get('status') != 0:
                raise ChannelError(j.get('status_message') or f"HTTP {r.status_code}", 'provider', 'Viber', j.get('status_message'))
            return str(j.get('message_token') or '')
    except requests.exceptions.RequestException as e:
        raise ChannelError(f"Could not reach {meta['label']}: {str(e)[:120]}", 'unreachable', meta['label'])
    raise ChannelError('Unknown channel', 'unsupported')


def note_error(business_id, channel, err):
    info = err.as_dict() if isinstance(err, ChannelError) else {'error': str(err)[:300], 'code': 'provider'}
    db.inbox_channels.update_one({'business_id': business_id, 'channel': channel},
                                 {'$set': {'last_error': {'message': info['error'], 'code': info.get('code'), 'ch': info.get('ch'),
                                                          'detail': info.get('detail'), 'at': datetime.now().isoformat()}}})


# ---------------------------------------------------------------- lưu hội thoại
def conversation_id(business_id, channel, user_id):
    return f"{business_id}:{channel}:{user_id}"


def find_message(customer_id, ext_msg_id):
    if not ext_msg_id:
        return None
    return db.bot_messages.find_one({'customer_id': customer_id, 'ext_msg_id': ext_msg_id}, {'_id': 1})


def recently_sent_same(customer_id, text, minutes=3):
    """Tin echo của chính BitPaw (AI/nhân viên vừa gửi) có thể tới trước khi kịp ghi id tin -> so nội dung gần đây."""
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    return db.bot_messages.find_one({'customer_id': customer_id, 'sender_type': {'$in': ['ai', 'staff']},
                                     'content': text, 'created_at': {'$gte': since}}, {'_id': 1})


def record(business_id, channel, user_id, text, sender_type, *, name=None, phone=None, ext_msg_id=None, delivery=None,
           default_name='Client', return_msg_id=False):
    """Ghi 1 tin vào hộp thư chung (bot_customers + bot_messages). Trả customer_id (hoặc (customer_id, _id của tin))."""
    cid = conversation_id(business_id, channel, user_id)
    now = datetime.now().isoformat()
    label = CHANNELS.get(channel, {}).get('label', channel)
    st = {'last_message': text[:500], 'last_message_time': now, 'business_id': business_id, 'channel': channel,
          'ext_user_id': str(user_id)}
    on_insert = {'created_at': now}
    if name:
        st['full_name'] = name
    else:
        tail = re.sub(r'\D', '', str(user_id))[-4:] or str(user_id)[-4:]
        on_insert['full_name'] = f"{default_name} · {label} {tail}"
    if phone:
        on_insert['phone'] = phone
    if sender_type == 'customer':
        st['last_inbound_at'] = now
    db.bot_customers.update_one({'id': cid}, {'$set': st, '$setOnInsert': on_insert}, upsert=True)
    m = {'customer_id': cid, 'sender_type': sender_type, 'content': text[:2000], 'business_id': business_id,
         'created_at': now, 'is_read': sender_type != 'customer', 'channel': channel}
    if ext_msg_id:
        m['ext_msg_id'] = ext_msg_id
    if delivery:
        m['delivery'] = delivery
    res = db.bot_messages.insert_one(m)
    return (cid, res.inserted_id) if return_msg_id else cid


def deliver(business_id, channel, user_id, text, sender_type, default_name='Client'):
    """Tin của AI/nhân viên: GHI TRƯỚC (trạng thái 'sending') rồi mới gửi — tin echo của nền tảng tới sớm vẫn nhận ra là
    tin của mình (recently_sent_same), không hiện 2 lần. Trả dict delivery thật ({'status': 'sent'|'failed', ...})."""
    cid, mid = record(business_id, channel, user_id, text, sender_type, delivery={'status': 'sending'},
                      default_name=default_name, return_msg_id=True)
    try:
        ext = send_text(business_id, channel, user_id, text)
        delivery = {'status': 'sent', 'at': datetime.now().isoformat()}
        upd = {'delivery': delivery}
        if ext and ext != 'web':
            upd['ext_msg_id'] = ext
    except ChannelError as e:
        delivery = {'status': 'failed', **e.as_dict()}
        upd = {'delivery': delivery}
        note_error(business_id, channel, e)
    db.bot_messages.update_one({'_id': mid}, {'$set': upd})
    return delivery


_PHONE_RE = re.compile(r'(?<![\w+])(\+?\d[\d\s.\-()]{7,17}\d)(?!\w)')


def capture_phone(customer_id, text):
    """Khách nhắn SĐT trong Messenger/Zalo/Viber -> lưu vào hội thoại để AI đặt lịch được (lịch hẹn cần SĐT)."""
    for mt in _PHONE_RE.finditer(text or ''):
        raw = mt.group(1)
        digits = re.sub(r'\D', '', raw)
        if 9 <= len(digits) <= 15:
            phone = ('+' + digits) if raw.strip().startswith('+') else digits
            # {'$in': [None, '']} cũng khớp khi chưa có field phone (Mongo coi thiếu field = null); không ghi đè SĐT đã có
            db.bot_customers.update_one({'id': customer_id, 'phone': {'$in': [None, '']}}, {'$set': {'phone': phone}})
            return phone
    return None


def link_customer(business_id, channel, user_id, phone):
    """Khách đã nhắn qua Zalo/Messenger và có SĐT -> gắn id nền tảng vào hồ sơ khách (db.customers), để chiến dịch chăm
    sóc gửi được qua đúng kênh đó (message_delivery_worker cần zalo_user_id / fb_psid)."""
    field = {'zalo': 'zalo_user_id', 'messenger': 'fb_psid'}.get(channel)
    want = re.sub(r'\D', '', phone or '')[-9:]
    if not field or len(want) < 8:
        return False
    tail = r'\D*'.join(want[-4:]) + r'\D*$'  # SĐT lưu kiểu "0412 345 678" vẫn khớp
    for c in db.customers.find({'business_id': business_id, 'phone': {'$regex': tail}}, {'_id': 0, 'id': 1, 'phone': 1}).limit(50):
        if re.sub(r'\D', '', str(c.get('phone') or ''))[-9:] == want:
            db.customers.update_one({'id': c['id'], 'business_id': business_id}, {'$set': {field: str(user_id)}})
            return True
    return False


def plain_text(s):
    """Messenger/Zalo/Viber/SMS không hiển thị Markdown: bỏ **đậm**, giữ chữ."""
    return re.sub(r'\*\*([^*\n]+?)\*\*', r'\1', s or '').strip()
