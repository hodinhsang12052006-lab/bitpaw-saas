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

import ai_function_tools
import messaging
from app import _get_all_active_business_ids, login_required, role_required
from mongo_client import db

messaging_bp = Blueprint('messaging', __name__)
_PUMP_EVERY_SECONDS = 180
_pump_last = {}
_pump_lock = threading.Lock()


def _bid():
    return session.get('business_id') or session.get('user_id')


def _booking_url(business_id, industry=None):
    """Trang đặt chỗ công khai THẬT theo ngành (ai_function_tools.reservation_link — cùng các route của app.py):
    nail /booking/nail/qr, spa /booking/qr, fnb /reserve, karaoke /karaoke/reserve, hotel /hotel/reserve. Ngành khác: ''."""
    return ai_function_tools.reservation_link(business_id, industry or ai_function_tools.business_industry(business_id)) or ''


# ---------------------------------------------------------------- nhắn lại cuộc gọi nhỡ: đúng ngành + đúng ngôn ngữ tiệm
# Trước đây: câu <Say> chỉ tiếng Anh, SMS tiếng Việt gọi mọi doanh nghiệp là "tiệm", link chỉ có cho nail/spa, và câu
# "We just sent you a text" đọc cả khi KHÔNG có tin nào được gửi (tắt tính năng / chưa nối Twilio / khách đã STOP).
_BOOK_PHRASE = {  # ngành -> (EN, VI) trước link
    'nail': ('Book online anytime', 'Đặt lịch online'), 'spa': ('Book online anytime', 'Đặt lịch online'),
    'fnb': ('Reserve a table online', 'Đặt bàn online'), 'karaoke': ('Book a room online', 'Đặt phòng online'),
    'hotel': ('Book your stay online', 'Đặt phòng online'),
}
_WHO = {  # ngành -> (EN "our ...", VI chủ ngữ) — không gọi mọi doanh nghiệp là "tiệm"
    'nail': ('salon team', 'tiệm'), 'spa': ('spa team', 'spa'), 'fnb': ('restaurant team', 'quán'),
    'karaoke': ('karaoke team', 'quán'), 'hotel': ('front desk', 'khách sạn'), 'retail': ('store team', 'cửa hàng'),
}
_WHO_DEFAULT = ('team', 'chúng tôi')
# Twilio <Say>: giọng Google tiếng Việt (vi-VN). Chủ có thể đổi qua biến môi trường TWILIO_VOICE_VI.
_VI_VOICE = os.environ.get('TWILIO_VOICE_VI') or 'Google.vi-VN-Standard-A'


def _missed_call_ctx(business_id, s):
    industry = ai_function_tools.business_industry(business_id) or ''
    vi = s.get('language') == 'vi'
    name = str(s.get('business_name') or '').strip()
    if name == 'our shop' or '@' in name:   # get_settings trả 'our shop' khi tiệm chưa có tên; tên = email thì không đọc
        name = ''
    return {'industry': industry, 'vi': vi, 'name': name, 'who': (_WHO.get(industry) or _WHO_DEFAULT)[1 if vi else 0],
            'link': _booking_url(business_id, industry)}


def _missed_call_sms(c):
    en_book, vi_book = _BOOK_PHRASE.get(c['industry'], ('', ''))
    link = c['link'] if en_book else ''
    if c['vi']:
        head = f"{c['name']} xin lỗi vì chưa nghe máy được!" if c['name'] else f"Xin lỗi quý khách, {c['who']} chưa nghe máy được!"
        if link:
            return f"{head} {vi_book}: {link} hoặc trả lời tin này, {c['who']} sẽ liên hệ lại ngay."
        return f"{head} Quý khách trả lời tin này hoặc gọi lại sau, {c['who']} sẽ liên hệ lại ngay."
    head = f"Hi, this is {c['name']} — sorry we missed your call!" if c['name'] else "Hi — sorry we missed your call!"
    if link:
        return f"{head} {en_book}: {link} or reply here and our {c['who']} will get back to you shortly."
    return f"{head} Reply here or call us back, and our {c['who']} will get back to you shortly."


def _missed_call_say(c, texted, answered_first):
    """Câu đọc cho người gọi. texted=False -> KHÔNG hứa 'đã nhắn tin'. answered_first: cuộc gọi đi thẳng (tiệm chưa
    cài số máy để chuyển) thay vì đã đổ chuông máy tiệm mà không ai nghe."""
    n, who = c['name'], c['who']
    if c['vi']:
        cap = who[:1].upper() + who[1:]
        if answered_first:
            head = f"Cảm ơn quý khách đã gọi {n}." if n else "Cảm ơn quý khách đã gọi."
            tail = f" {cap} sẽ nhắn tin cho quý khách ngay." if texted else " Hiện chưa có ai nghe máy, quý khách vui lòng gọi lại sau."
        else:
            head = f"Xin lỗi, {n or who} chưa nghe máy được."
            tail = f" {cap} vừa nhắn tin cho quý khách." if texted else " Quý khách vui lòng gọi lại sau ít phút."
        return f'<Say voice="{escape(_VI_VOICE)}" language="vi-VN">{escape(head + tail)}</Say>'
    if answered_first:
        head = f"Thanks for calling {n}." if n else "Thanks for calling."
        tail = " We will text you right away." if texted else " Sorry, no one can take your call right now. Please call again later."
    else:
        head = f"Sorry we missed you at {n}." if n else "Sorry we missed your call."
        tail = " We just sent you a text." if texted else " Please call again a little later."
    return f'<Say>{escape(head + tail)}</Say>'


def _missed_call_text_back(business_id, caller, s, c):
    """Xếp SMS xin lỗi (đúng ngành/ngôn ngữ, link đặt chỗ thật nếu ngành có). True = khách THẬT SỰ được nhắn: vừa xếp
    tin, hoặc đã nhắn số này trong 30 phút qua (chống nhắn liên tục khi gọi lại nhiều lần). False khi tính năng tắt,
    Twilio chưa sẵn sàng, số không hợp lệ hoặc khách đã STOP."""
    if not (s.get('missed_call_enabled') and s.get('twilio_ready') and caller):
        return False
    now = datetime.now(timezone.utc)
    key = f"mc:{business_id}:{caller}:{now.strftime('%Y%m%d%H')}{now.minute // 30}"
    if messaging.queue(business_id, 'sms', caller, _missed_call_sms(c), 'missed_call', dedupe_key=key) is not None:
        return True
    return db.outbound_messages.find_one({'dedupe_key': key}, {'_id': 1}) is not None


def _missed_call_flow(business_id, s, answered_first):
    c = _missed_call_ctx(business_id, s)
    texted = _missed_call_text_back(business_id, request.form.get('From', ''), s, c)
    if texted:
        try:
            messaging.pump(business_id, produce=False)
        except Exception as e:   # tin đã nằm trong hàng đợi, cron sẽ gửi — không làm hỏng câu trả lời cho Twilio
            print(f"[missed call] pump: {e}")
    return _twiml(_missed_call_say(c, texted, answered_first) + '<Hangup/>')


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
    return _missed_call_flow(business_id, s, answered_first=True)


@messaging_bp.route('/api/twilio/voice/<business_id>/after', methods=['POST'])
def twilio_voice_after(business_id):
    if not _verify_twilio(business_id):
        return Response('Forbidden', status=403)
    status = request.form.get('DialCallStatus', '')
    if status in ('no-answer', 'busy', 'failed', 'canceled'):
        return _missed_call_flow(business_id, messaging.get_settings(business_id), answered_first=False)
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


# ---------------------------------------------------------------- bảng lương cá nhân qua email
@messaging_bp.route('/api/payroll/pay_summaries', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def payroll_pay_summaries():
    """Gửi mỗi nhân viên bảng lương CỦA RIÊNG HỌ (email trong hồ sơ / lịch ca). Số liệu là con số chủ tiệm đang xem ở
    /bangluong. Ghi rõ đây là bảng tóm tắt, không thay phiếu lương theo luật (Úc: Fair Work; Mỹ: luật bang)."""
    bid = _bid()
    data = request.json or {}
    try:
        month, year = int(data.get('month')), int(data.get('year'))
        assert 1 <= month <= 12 and 2000 <= year <= 2100
    except (TypeError, ValueError, AssertionError):
        return jsonify({'success': False, 'message': 'Invalid pay period.'}), 400
    cur = str(data.get('currency') or 'USD').upper()[:3]
    labels = data.get('labels') or {}
    lab = [str(labels.get(k) or d)[:40] for k, d in (('col1', 'Base pay'), ('col2', 'Commission'), ('col3', 'Tips / allowances'))]
    s = messaging.get_settings(bid)
    vi = s['language'] == 'vi'

    def money(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        return f"{v:,.0f} ₫" if cur == 'VND' else f"{'A$' if cur == 'AUD' else '$'}{v:,.2f}"
    sent, no_email = 0, []
    for row in (data.get('rows') or [])[:300]:
        code = str(row.get('ma_nv') or '')
        emp = db.employees.find_one({'business_id': bid, 'ma_nv': code}, {'_id': 0, 'ho_ten': 1, 'email': 1})
        if not emp:
            continue
        if not emp.get('email'):
            no_email.append(emp.get('ho_ten') or code)
            continue
        first = (emp.get('ho_ten') or '').split(' ')[0]
        lines = [f"{lab[0]}: {money(row.get('col1'))}", f"{lab[1]}: {money(row.get('col2'))}", f"{lab[2]}: {money(row.get('col3'))}",
                 f"{'Thực lãnh' if vi else 'Total'}: {money(row.get('net'))}"]
        if vi:
            body = (f"Chào {first},\n\nBảng lương tháng {month}/{year} của bạn tại {s['business_name']}:\n\n" + '\n'.join(lines) +
                    "\n\nĐây là bảng tóm tắt để bạn đối chiếu. Có sai sót, vui lòng báo quản lý trước ngày trả lương.")
            subject = f"Bảng lương tháng {month}/{year} — {s['business_name']}"
        else:
            body = (f"Hi {first},\n\nHere is your pay summary for {month}/{year} at {s['business_name']}:\n\n" + '\n'.join(lines) +
                    "\n\nThis is a summary for you to check, not a formal payslip. If anything looks wrong, tell your manager before payday.")
            subject = f"Your pay summary {month}/{year} — {s['business_name']}"
        if messaging.queue(bid, 'email', emp['email'], body, 'pay_summary', subject=subject,
                           dedupe_key=f"pay:{bid}:{code}:{year}-{month}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"):
            sent += 1
    if sent:
        try:
            messaging.pump(bid, base_url=request.host_url, produce=False)
        except Exception as ex:
            print(f"[pay_summaries] pump: {ex}")
    return jsonify({'success': True, 'sent': sent, 'no_email': no_email})
