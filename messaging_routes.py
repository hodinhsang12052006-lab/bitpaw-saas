"""
Route của xương sống nhắn tin (messaging.py): trang cài đặt SMS & email, gửi thử, nhật ký, bộ gửi (pump),
cron, webhook Twilio (STOP/START/HELP + trả lời cuộc gọi nhỡ) và trang huỷ đăng ký email.
Import SAU login_required/role_required trong app.py (cùng cách ai_studio_bp).
"""
import hmac
import os
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, render_template, request, session
from markupsafe import escape

import messaging
from app import _get_all_active_business_ids, login_required, role_required
from mongo_client import db

messaging_bp = Blueprint('messaging', __name__)
_PUMP_EVERY_SECONDS = 180
_pump_last = {}
_pump_lock = threading.Lock()


def _bid():
    return session.get('business_id') or session.get('user_id')


def _booking_url(business_id):
    biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'industry_code': 1}) or {}
    base = (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')
    code = (biz.get('industry_code') or '').lower()
    if code == 'nail':
        return f"{base}/booking/nail/qr/{business_id}"
    if code == 'spa':
        return f"{base}/booking/qr/{business_id}"
    return ''


def _public_settings(s):
    keys = list(messaging.DEFAULT_SETTINGS.keys()) + ['twilio_ready', 'business_name', 'country']
    out = {k: s.get(k) for k in keys}
    out['webhook_sms'] = f"{request.host_url.rstrip('/')}/api/twilio/sms/{_bid()}"
    out['webhook_voice'] = f"{request.host_url.rstrip('/')}/api/twilio/voice/{_bid()}"
    return out


# ---------------------------------------------------------------- trang + API cài đặt
@messaging_bp.route('/settings/messaging')
@login_required
@role_required('admin', 'super_admin')
def messaging_settings_page():
    return render_template('messaging_settings.html')


@messaging_bp.route('/api/messaging/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
def messaging_settings_api():
    bid = _bid()
    if request.method == 'GET':
        return jsonify({'success': True, 'settings': _public_settings(messaging.get_settings(bid))})
    data = request.get_json() or {}
    data['country'] = messaging.get_settings(bid)['country']
    try:
        s = messaging.save_settings(bid, data)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': True, 'settings': _public_settings(s)})


@messaging_bp.route('/api/messaging/test', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def messaging_test():
    """Gửi 1 tin thử NGAY (bỏ qua khung giờ) tới số/email chủ tiệm nhập — để kiểm tra kết nối."""
    bid = _bid()
    data = request.get_json() or {}
    channel = data.get('channel') if data.get('channel') in ('sms', 'email') else 'sms'
    s = messaging.get_settings(bid)
    to = messaging.normalize_phone(data.get('to'), s['country']) if channel == 'sms' else (data.get('to') or '').strip()
    if not to:
        return jsonify({'success': False, 'message': 'Enter a valid phone number (e.g. +1 555 123 4567) or email.'}), 400
    if channel == 'sms' and not s['twilio_ready']:
        return jsonify({'success': False, 'message': 'Connect Twilio first (Account SID, Auth Token, From number) and turn SMS on.'}), 400
    body = f"Test message from {s['business_name']} via BitPaw — SMS & email are connected."
    msg = {'id': 0, 'business_id': bid, 'channel': channel, 'to': to, 'body': body, 'kind': 'test',
           'subject': 'BitPaw test message'}
    try:
        provider_id = messaging.send_now(msg, s, request.host_url)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Not sent: {e}'}), 502
    db.outbound_messages.insert_one({**msg, 'id': messaging.next_mongo_id('outbound_messages'), 'status': 'sent', 'provider_id': provider_id,
                                     'created_at': datetime.now(timezone.utc).isoformat(), 'sent_at': datetime.now(timezone.utc).isoformat(), 'attempts': 1})
    return jsonify({'success': True, 'message': f'Sent to {to}.'})


@messaging_bp.route('/api/messaging/log', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def messaging_log():
    bid = _bid()
    stats = {k: db.outbound_messages.count_documents({'business_id': bid, 'status': k}) for k in ('queued', 'sent', 'failed', 'cancelled')}
    optouts = db.message_optouts.count_documents({'business_id': bid})
    return jsonify({'success': True, 'items': messaging.recent_log(bid, 60), 'stats': stats, 'optouts': optouts})


# ---------------------------------------------------------------- bộ gửi
@messaging_bp.route('/api/messages/pump', methods=['POST'])
@login_required
def messages_pump():
    """Gọi bởi app khi đang mở (tối đa 1 lần / 3 phút / tiệm) — gửi tin tới hạn không phải chờ cron."""
    bid = _bid()
    now = time.time()
    with _pump_lock:
        if now - _pump_last.get(bid, 0) < _PUMP_EVERY_SECONDS:
            return jsonify({'success': True, 'skipped': True})
        _pump_last[bid] = now
    try:
        stats = messaging.pump(bid, base_url=request.host_url)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)[:200]}), 500
    return jsonify({'success': True, **stats})


@messaging_bp.route('/api/cron/messages', methods=['GET', 'POST'])
def cron_messages():
    secret = os.environ.get('CRON_SECRET')
    if not secret or not hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {secret}'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    total = {'businesses': 0, 'produced': 0, 'sent': 0, 'failed': 0, 'deferred': 0, 'skipped': 0, 'errors': []}
    for bid in _get_all_active_business_ids():
        total['businesses'] += 1
        try:
            st = messaging.pump(bid, base_url=os.environ.get('PUBLIC_BASE_URL', request.host_url))
            for k in ('produced', 'sent', 'failed', 'deferred', 'skipped'):
                total[k] += st.get(k, 0)
        except Exception as e:
            total['errors'].append(f"{bid}: {str(e)[:120]}")
    return jsonify({'success': True, **total})


# ---------------------------------------------------------------- webhook Twilio
def _twiml(inner=''):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>', mimetype='text/xml')


def _verify_twilio(business_id):
    token = messaging.twilio_auth_token(business_id)
    if not token:
        return False
    url = request.url
    proto = request.headers.get('X-Forwarded-Proto')
    if proto and url.startswith('http://') and proto == 'https':
        url = 'https://' + url[len('http://'):]
    return messaging.validate_twilio_signature(token, url, request.form.to_dict(), request.headers.get('X-Twilio-Signature', ''))


@messaging_bp.route('/api/twilio/sms/<business_id>', methods=['POST'])
def twilio_sms(business_id):
    if not _verify_twilio(business_id):
        return Response('Forbidden', status=403)
    reply = messaging.handle_inbound_sms(business_id, request.form.get('From', ''), request.form.get('Body', ''))
    return _twiml(f'<Message>{escape(reply)}</Message>' if reply else '')


@messaging_bp.route('/api/twilio/voice/<business_id>', methods=['POST'])
def twilio_voice(business_id):
    """Cuộc gọi tới số Twilio của tiệm: chuyển tới máy tiệm 20 giây; không ai nghe -> /after nhắn lại khách."""
    if not _verify_twilio(business_id):
        return Response('Forbidden', status=403)
    s = messaging.get_settings(business_id)
    after = f"{request.url.rstrip('/')}/after"
    if s['shop_phone']:
        return _twiml(f'<Dial timeout="20" action="{escape(after)}" method="POST">{escape(s["shop_phone"])}</Dial>')
    messaging.missed_call_reply(business_id, request.form.get('From', ''), _booking_url(business_id))
    messaging.pump(business_id, produce=False)
    return _twiml(f'<Say>Thanks for calling {escape(s["business_name"])}. We will text you right away.</Say><Hangup/>')


@messaging_bp.route('/api/twilio/voice/<business_id>/after', methods=['POST'])
def twilio_voice_after(business_id):
    if not _verify_twilio(business_id):
        return Response('Forbidden', status=403)
    status = request.form.get('DialCallStatus', '')
    if status in ('no-answer', 'busy', 'failed', 'canceled'):
        messaging.missed_call_reply(business_id, request.form.get('From', ''), _booking_url(business_id))
        messaging.pump(business_id, produce=False)
        s = messaging.get_settings(business_id)
        return _twiml(f'<Say>Sorry we missed you at {escape(s["business_name"])}. We just sent you a text.</Say><Hangup/>')
    return _twiml('<Hangup/>')


# ---------------------------------------------------------------- huỷ đăng ký email
@messaging_bp.route('/unsubscribe')
def unsubscribe():
    b, e, t = request.args.get('b', ''), request.args.get('e', ''), request.args.get('t', '')
    bid = b  # id tiệm luôn là chuỗi
    ok =bool(e) and hmac.compare_digest(messaging.unsubscribe_token(bid, e), t)
    if ok:
        messaging.opt_out(bid, 'email', e, source='unsubscribe-link')
    name = (db.businesses.find_one({'id': bid}, {'name': 1, '_id': 0}) or {}).get('name') if ok else ''
    msg = (f"You're unsubscribed. {escape(name or 'This business')} will not email {escape(e)} again."
           if ok else 'This unsubscribe link is not valid. Please reply to the email and ask to be removed.')
    return (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Unsubscribe</title><body style="font-family:system-ui;background:#0b0e17;color:#e8ecf5;display:grid;place-items:center;min-height:100vh;margin:0">'
            f'<div style="max-width:420px;padding:24px;text-align:center"><h1 style="font-size:22px">{"Done" if ok else "Link not valid"}</h1><p style="color:#9aa4ba;line-height:1.6">{msg}</p></div>'), (200 if ok else 400)
