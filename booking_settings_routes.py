"""Trang + API "Cài đặt đặt lịch" (giờ mở cửa, luật đặt, thời lượng dịch vụ, thông tin tiệm cho AI) và API giờ trống
công khai cho trang đặt lịch. Luật nằm ở booking_rules.py (dùng chung cho form, AI, chủ tiệm).
Mục "Đặt chỗ" theo ngành (bàn F&B / phòng hát theo giờ / phòng khách sạn theo đêm): API /api/booking/reservation_settings/<kind>
chỉ đọc / ghi qua reservations_core.load_rules + save_reservation_settings và reservations_hotel.hotel_settings +
save_hotel_settings — kiểm tra + kẹp giới hạn nằm ở 2 module đó, không lặp lại ở đây."""
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

import booking_rules
import reservations_core
import reservations_hotel
from app import limiter, login_required, role_required
from i18n import resolve_lang
from mongo_client import db

booking_settings_bp = Blueprint('booking_settings', __name__)

# Ngành có đặt chỗ -> loại luật của ngành đó (mỗi tiệm chỉ thấy / sửa được đúng 1 loại).
RESERVATION_KIND = {'fnb': 'table', 'karaoke': 'karaoke', 'hotel': 'hotel'}
_AUTO_MODES = {'follow': None, 'always': True, 'never': False}   # 3 lựa chọn "tự xác nhận" của bàn / phòng hát
_FIELD_NAMES = {
    'max_covers_per_slot': ('Số khách đến tối đa mỗi khung giờ', 'Max guests arriving per time slot'),
    'slot_minutes': ('Khung giờ', 'Time slot'),
    'max_party': ('Nhóm lớn nhất đặt online', 'Largest party online'),
    'max_party_auto': ('Ngưỡng nhóm lớn', 'Large-party threshold'),
    'dining_minutes': ('Thời gian một lượt ngồi', 'Dining time'),
    'last_booking_before_close': ('Nhận đặt muộn nhất trước giờ đóng', 'Last booking before closing'),
    'hold_minutes': ('Giữ chỗ khi khách tới trễ', 'Hold for late guests'),
    'min_hours': ('Số giờ tối thiểu', 'Minimum hours'),
    'max_hours': ('Số giờ tối đa', 'Maximum hours'),
    'in_use_buffer_hours': ('Khoảng chừa khi phòng đang có khách', 'Buffer while a room is in use'),
}


def _bid():
    return session.get('business_id') or session.get('user_id')


def _lang():
    try:
        return resolve_lang(request)
    except Exception:
        return 'en'


def _say(lang, vi, en):
    return vi if lang == 'vi' else en


def _value_error_text(e, lang):
    """Câu lỗi của reservations_core ('<khoá> không hợp lệ.', chỉ tiếng Việt) -> câu VI / EN có tên ô cho chủ tiệm."""
    m = re.match(r'^(\w+) không hợp lệ\.$', str(e))
    if m and m.group(1) in _FIELD_NAMES:
        vi, en = _FIELD_NAMES[m.group(1)]
        return _say(lang, f'{vi}: phải là một con số.', f'{en}: must be a number.')
    return _say(lang, str(e) or 'Dữ liệu không hợp lệ.', 'Some values are not valid.')


def _reservation_payload(bid, kind):
    """Giá trị đang lưu (đã kẹp giới hạn) + giới hạn từng ô + tình trạng thật để trang nói đúng điều AI sẽ làm."""
    raw = db.booking_settings.find_one({'business_id': bid}, {'_id': 0}) or {}
    if kind == 'hotel':
        return {'settings': reservations_hotel.hotel_settings(bid), 'hours_published': bool(raw.get('hours')),
                'limits': {'min_nights': [1, reservations_hotel.MAX_NIGHTS], 'free_cancel_hours': [0, 24 * 60]}}
    rules = reservations_core.load_rules(bid, kind)
    sub = raw.get(reservations_core.SETTINGS_KEY[kind])
    own = sub.get('auto_confirm') if isinstance(sub, dict) else None
    settings = {k: rules[k] for k in reservations_core._LIMITS[kind]}
    settings['auto_confirm'] = 'always' if own is True else ('never' if own is False else 'follow')
    out = {'settings': settings, 'limits': {k: list(v) for k, v in reservations_core._LIMITS[kind].items()},
           'effective_auto_confirm': bool(rules['auto_confirm']), 'hours_published': bool(rules['hours']),
           'general_auto_confirm': bool(raw['auto_confirm']) if 'auto_confirm' in raw else None}
    if kind == 'table':
        tables = reservations_core.tables_with_seats(bid)
        out['tables_with_seats'] = len(tables)
        out['capacity_model'] = reservations_core.table_model(rules, tables)
    return out


@booking_settings_bp.route('/settings/booking')
@login_required
@role_required('admin', 'super_admin')
def booking_settings_page():
    return render_template('booking_settings.html')


@booking_settings_bp.route('/api/booking/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
def booking_settings_api():
    bid = _bid()
    if request.method == 'POST':
        try:
            rules = booking_rules.save_rules(bid, request.json or {})
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
    else:
        rules = booking_rules.get_rules(bid)
    services = list(db.products.find({'business_id': bid, 'is_active': {'$in': [1, True]}, 'price': {'$gt': 0}},
                                     {'_id': 0, 'id': 1, 'name': 1, 'price': 1}).sort('name', 1).limit(200))
    for s in services:
        s['duration'] = booking_rules.duration_of(rules, s['id'])
    staff_count = len(booking_rules._staff_names(bid))  # Nails = nhân viên ngành Nails, ngành khác = db.staff (trước đây luôn đếm db.staff -> Nails báo 0)
    # Câu khách hỏi mà AI không có dữ liệu để trả lời (công cụ ask_team) — chủ tiệm điền vào "Thông tin tiệm" là lần sau AI tự trả lời
    since = (datetime.now() - timedelta(days=30)).isoformat()
    gaps, seen = [], set()
    for m in db.bot_messages.find({'business_id': bid, 'sender_type': 'system', 'content': {'$regex': '^❓'}, 'created_at': {'$gte': since}},
                                  {'_id': 0, 'content': 1, 'created_at': 1}).sort('created_at', -1).limit(60):
        q = m['content'].split(':', 1)[-1].strip()
        if q.lower() not in seen:
            seen.add(q.lower())
            gaps.append({'question': q[:200], 'at': m['created_at'][:10]})
    return jsonify({'success': True, 'rules': rules, 'services': services, 'staff_count': staff_count, 'gaps': gaps[:15]})


@booking_settings_bp.route('/api/booking/reservation_settings/<kind>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
def reservation_settings_api(kind):
    """Luật đặt chỗ riêng của ngành cho mục "Đặt chỗ" của trang Cài đặt đặt lịch: 'table' (F&B), 'karaoke', 'hotel' — chỉ
    đúng loại của ngành tiệm đang đăng nhập. POST trả lại giá trị ĐÃ LƯU (sau khi module kẹp giới hạn) để trang hiện đúng."""
    lang = _lang()
    if kind not in ('table', 'karaoke', 'hotel'):
        return jsonify({'success': False, 'message': _say(lang, 'Không có loại đặt chỗ này.', 'Unknown reservation type.')}), 404
    industry = (session.get('business_mode') or session.get('industry_code') or '').strip().lower()
    if RESERVATION_KIND.get(industry) != kind:
        return jsonify({'success': False, 'message': _say(lang, 'Mục đặt chỗ này không dùng cho ngành của tiệm bạn.',
                                                          'These reservation rules do not apply to your type of business.')}), 403
    bid = _bid()
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'success': False, 'message': _say(lang, 'Dữ liệu không hợp lệ.', 'Invalid data.')}), 400
        try:
            if kind == 'hotel':
                # save_hotel_settings ghi cả khối 'hotel' -> trộn với giá trị đang lưu để ô không gửi lên không bị xoá
                merged = reservations_hotel.hotel_settings(bid)
                merged.update({k: data[k] for k in reservations_hotel.SETTINGS_DEFAULTS if k in data})
                reservations_hotel.save_hotel_settings(bid, merged)
            else:
                body = dict(data)
                mode = body.get('auto_confirm')
                if mode is not None and not isinstance(mode, bool):
                    if not isinstance(mode, str) or mode not in _AUTO_MODES:
                        return jsonify({'success': False, 'message': _say(
                            lang, 'Tự xác nhận phải là: theo công tắc chung / luôn / không bao giờ.',
                            'Auto-confirm must be: follow the general switch / always / never.')}), 400
                    body['auto_confirm'] = _AUTO_MODES[mode]
                reservations_core.save_reservation_settings(bid, kind, body)
        except reservations_hotel.HotelRequestError as e:
            return jsonify({'success': False, 'message': e.text(lang)}), 400
        except ValueError as e:
            return jsonify({'success': False, 'message': _value_error_text(e, lang)}), 400
        booking_rules._CACHE.pop(('rules', bid), None)   # AI khách sạn đọc booking_rules.get_rules (cache 20 giây)
    return jsonify(dict(_reservation_payload(bid, kind), success=True, kind=kind))


@booking_settings_bp.route('/api/public/booking_slots/<business_id>')
@limiter.limit("120 per hour")
def public_booking_slots(business_id):
    """Giờ còn trống của 1 ngày (cho trang đặt lịch công khai hiện các nút giờ thay vì ô nhập tự do)."""
    if not db.businesses.find_one({'id': business_id}, {'_id': 1}):
        return jsonify({'success': False}), 404
    try:
        day = datetime.strptime(str(request.args.get('date') or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'date=YYYY-MM-DD'}), 400
    service_id = request.args.get('service_id')
    try:
        service_id = int(service_id) if service_id not in (None, '') else None
    except ValueError:
        service_id = None
    staff_id = request.args.get('staff_id') or None
    rules = booking_rules.get_rules(business_id)
    hrs = booking_rules.hours_on(rules, day)
    return jsonify({'success': True, 'date': day.isoformat(), 'open': bool(hrs),
                    'slots': booking_rules.available_slots(business_id, day, service_id, staff_id, limit=40),
                    'duration': booking_rules.duration_of(rules, service_id)})
