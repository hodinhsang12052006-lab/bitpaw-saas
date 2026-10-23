"""Trang + API "Cài đặt đặt lịch" (giờ mở cửa, luật đặt, thời lượng dịch vụ, thông tin tiệm cho AI) và API giờ trống
công khai cho trang đặt lịch. Luật nằm ở booking_rules.py (dùng chung cho form, AI, chủ tiệm)."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

import booking_rules
from app import limiter, login_required, role_required
from mongo_client import db

booking_settings_bp = Blueprint('booking_settings', __name__)


def _bid():
    return session.get('business_id') or session.get('user_id')


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
