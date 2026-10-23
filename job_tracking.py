"""
"Thợ đang đến" cho ngành Kỹ thuật: thợ bấm "On my way" trong app -> khách nhận SMS kèm link theo dõi.

  - Link ký HMAC theo (tiệm, việc) — không đoán được việc khác.
  - Trang công khai chỉ hiện TÊN (tên gọi) của thợ, thời gian dự kiến và vị trí thợ KHI ĐANG TRÊN ĐƯỜNG tới. Tới nơi
    (cách < 150 m), xong việc, hoặc vị trí cũ hơn 15 phút -> không hiện vị trí nữa (riêng tư của thợ).
  - Thời gian dự kiến = khoảng cách đường chim bay × 1,3 / 35 km/h (ước lượng, ghi rõ là ước tính).
  - Tiệm chưa nối Twilio / khách không có SĐT hợp lệ -> trả link + nội dung để thợ tự nhắn bằng máy mình (sms:).
"""
import hashlib
import hmac
import math
import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

from app import limiter, login_required
from mongo_client import db

tracking_bp = Blueprint('job_tracking', __name__)
ARRIVED_M = 150
STALE_MIN = 15
ROAD_FACTOR, AVG_KMH = 1.3, 35


def _bid():
    return session.get('business_id') or session.get('user_id')


def track_token(business_id, task_id):
    key = (os.environ.get('FLASK_SECRET_KEY') or 'bitpaw-track').encode()
    return hmac.new(key, f"track|{business_id}|{task_id}".encode(), hashlib.sha256).hexdigest()[:20]


def _dist_m(a_lat, a_lng, b_lat, b_lng):
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _tech(business_id, name):
    if not name:
        return None
    return db.employees.find_one({'business_id': business_id, 'ho_ten': name},
                                 {'_id': 0, 'ho_ten': 1, 'toa_do_lat': 1, 'toa_do_lng': 1, 'gps_at': 1, 'avatar_url': 1})


def status(business_id, task):
    """Trạng thái công khai của việc: on_way / arrived / done / scheduled (+ vị trí thợ nếu đang trên đường)."""
    tech = _tech(business_id, task.get('nguoi_nhan'))
    first = ((tech or {}).get('ho_ten') or task.get('nguoi_nhan') or '').split(' ')[0]
    out = {'tech': first, 'address': task.get('dia_chi') or '', 'state': 'scheduled', 'eta_min': None, 'tech_pos': None,
           'dest': [task['lat'], task['lng']] if task.get('lat') is not None and task.get('lng') is not None else None}
    if task.get('trang_thai') == 'Hoàn Thành':
        out['state'] = 'done'
        return out
    if not task.get('on_way_at') or task.get('trang_thai') != 'Đã Nhận':
        return out
    out['state'] = 'on_way'
    fresh = False
    if tech and tech.get('toa_do_lat') is not None and tech.get('gps_at'):
        try:
            fresh = datetime.now() - datetime.fromisoformat(tech['gps_at']) < timedelta(minutes=STALE_MIN)
        except ValueError:
            fresh = False
    if fresh and out['dest']:
        d = _dist_m(float(tech['toa_do_lat']), float(tech['toa_do_lng']), out['dest'][0], out['dest'][1])
        if d <= ARRIVED_M:
            out['state'] = 'arrived'
            return out
        out['eta_min'] = max(3, round(d / 1000 * ROAD_FACTOR / AVG_KMH * 60))
        out['tech_pos'] = [round(float(tech['toa_do_lat']), 5), round(float(tech['toa_do_lng']), 5)]
    elif task.get('on_way_eta_min'):
        mins_left = task['on_way_eta_min'] - int((datetime.now() - datetime.fromisoformat(task['on_way_at'])).total_seconds() // 60)
        out['eta_min'] = max(1, mins_left)
    return out


@tracking_bp.route('/api/tasks/<int:task_id>/on_my_way', methods=['POST'])
@login_required
def on_my_way(task_id):
    bid = _bid()
    task = db.tasks.find_one({'business_id': bid, 'id': task_id}, {'_id': 0})
    if not task:
        return jsonify({'success': False, 'message': 'Job not found.'}), 404
    if task.get('trang_thai') != 'Đã Nhận' or not task.get('nguoi_nhan'):
        return jsonify({'success': False, 'message': 'Accept the job before sending an on-the-way message.'}), 409
    now = datetime.now().isoformat()
    db.tasks.update_one({'business_id': bid, 'id': task_id}, {'$set': {'on_way_at': now}})
    task['on_way_at'] = now
    st = status(bid, task)
    if st['eta_min']:
        db.tasks.update_one({'business_id': bid, 'id': task_id}, {'$set': {'on_way_eta_min': st['eta_min']}})
    base = (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')
    url = f"{base}/track/{bid}/{task_id}/{track_token(bid, task_id)}"
    import messaging
    s = messaging.get_settings(bid)
    n = st['eta_min']
    if s['language'] == 'vi':
        body = f"{s['business_name']}: Kỹ thuật viên {st['tech']} đang trên đường tới" + (f" (khoảng {n} phút)" if n else '') + f". Theo dõi: {url}"
    else:
        body = f"{s['business_name']}: {st['tech']} is on the way" + (f" (about {n} min)" if n else '') + f". Track your technician: {url}"
    sent = False
    phone = messaging.normalize_phone(task.get('sdt') or '', s['country'])
    if phone and s['twilio_ready']:
        mid = messaging.queue(bid, 'sms', phone, body, 'on_my_way', dedupe_key=f"omw:{bid}:{task_id}:{now[:19]}", meta={'task_id': task_id})
        if mid:
            try:
                messaging.pump(bid, base_url=base, produce=False)
            except Exception as ex:
                print(f"[on_my_way] pump: {ex}")
            sent = True
    return jsonify({'success': True, 'sent': sent, 'url': url, 'text': body, 'phone': phone or '', 'eta_min': st['eta_min']})


def _public_task(business_id, task_id, token):
    if not hmac.compare_digest(track_token(business_id, task_id), token or ''):
        return None
    return db.tasks.find_one({'business_id': business_id, 'id': task_id}, {'_id': 0})


@tracking_bp.route('/track/<business_id>/<int:task_id>/<token>')
def track_page(business_id, task_id, token):
    task = _public_task(business_id, task_id, token)
    biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'country': 1}) or {}
    lang = 'vi' if (biz.get('country') or '').upper() == 'VN' else 'en'
    if not task:
        return render_template('job_track.html', invalid=True, biz={}, lang='en', api_url=''), 404
    return render_template('job_track.html', invalid=False, biz=biz, lang=lang,
                           api_url=f"/api/public/track/{business_id}/{task_id}/{token}")


@tracking_bp.route('/api/public/track/<business_id>/<int:task_id>/<token>')
@limiter.limit("240 per hour")
def track_api(business_id, task_id, token):
    task = _public_task(business_id, task_id, token)
    if not task:
        return jsonify({'success': False}), 404
    return jsonify({'success': True, **status(business_id, task)})
