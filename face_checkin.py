"""
Chấm công khuôn mặt (chống chấm công hộ). Trước đây nhân viên chỉ cần gõ MÃ NHÂN VIÊN (không bí mật) là chấm được,
và trang HRM quảng cáo "FaceID" dù chưa có.

Cách hoạt động:
  - Chủ tiệm bật/tắt cho cả tiệm (db.hr_settings.face_checkin). Tắt -> xoá MỌI mẫu khuôn mặt của tiệm.
  - Điện thoại tính "mẫu khuôn mặt" (vector 128 số, face-api.js) NGAY TRÊN MÁY + bắt CHỚP MẮT (chống giơ ảnh in);
    chỉ gửi vector, không gửi ảnh khuôn mặt cho việc so khớp.
  - Đăng ký lần đầu cần nhân viên đồng ý (BIPA Illinois / luật bang, Privacy Act Úc) -> lưu face_template + face_consent_at.
  - So khớp ở MÁY CHỦ (khoảng cách Euclid < ngưỡng). Khớp -> cấp "vé" HMAC hạn 3 phút; /api/hr/chamcong (check-in có ảnh)
    bắt buộc vé khi tiệm bật tính năng. Mẫu khuôn mặt không bao giờ trả về trình duyệt.
"""
import hashlib
import hmac
import math
import os
import time
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from app import login_required, role_required
from mongo_client import db

face_bp = Blueprint('face_checkin', __name__)
MATCH_THRESHOLD = float(os.environ.get('FACE_MATCH_THRESHOLD', '0.5'))
TOKEN_TTL = 180


def _bid():
    return session.get('business_id') or session.get('user_id')


def face_enabled(business_id):
    s = db.hr_settings.find_one({'business_id': business_id}, {'_id': 0, 'face_checkin': 1}) or {}
    return bool(s.get('face_checkin'))


def _secret():
    return (os.environ.get('FLASK_SECRET_KEY') or 'bitpaw-face').encode()


def make_token(business_id, ma_nv, ts=None):
    ts = int(ts or time.time())
    sig = hmac.new(_secret(), f"face|{business_id}|{ma_nv}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


def check_token(business_id, ma_nv, token):
    try:
        ts_s, sig = str(token).split('.', 1)
        ts = int(ts_s)
    except (ValueError, AttributeError):
        return False
    if time.time() - ts > TOKEN_TTL or ts > time.time() + 30:
        return False
    good = hmac.new(_secret(), f"face|{business_id}|{ma_nv}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig)


def _clean_descriptor(v):
    if not isinstance(v, list) or len(v) != 128:
        return None
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        return None
    if any(math.isnan(x) or abs(x) > 2 for x in out):
        return None
    return out


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@face_bp.route('/api/hr/face/status', methods=['GET'])
@login_required
def face_status():
    bid = _bid()
    ma_nv = (request.args.get('ma_nv') or '').strip().upper()
    emp = db.employees.find_one({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0, 'face_enrolled_at': 1}) if ma_nv else None
    return jsonify({'success': True, 'enabled': face_enabled(bid), 'enrolled': bool(emp and emp.get('face_enrolled_at')),
                    'threshold': MATCH_THRESHOLD})


@face_bp.route('/api/hr/face/settings', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
def face_settings():
    bid = _bid()
    if request.method == 'POST':
        on = bool((request.get_json() or {}).get('enabled'))
        db.hr_settings.update_one({'business_id': bid}, {'$set': {'face_checkin': on, 'updated_at': datetime.now().isoformat()}}, upsert=True)
        if not on:  # tắt -> xoá mọi mẫu khuôn mặt (đúng cam kết trong Chính sách bảo mật)
            db.employees.update_many({'business_id': bid}, {'$unset': {'face_template': '', 'face_enrolled_at': '', 'face_consent_at': ''}})
    enrolled = db.employees.count_documents({'business_id': bid, 'face_enrolled_at': {'$exists': True}})
    total = db.employees.count_documents({'business_id': bid})
    return jsonify({'success': True, 'enabled': face_enabled(bid), 'enrolled': enrolled, 'total': total})


@face_bp.route('/api/hr/face/enroll', methods=['POST'])
@login_required
def face_enroll():
    bid = _bid()
    data = request.get_json() or {}
    ma_nv = (data.get('ma_nv') or '').strip().upper()
    desc = _clean_descriptor(data.get('descriptor'))
    if not face_enabled(bid):
        return jsonify({'success': False, 'message': 'Face check-in is turned off for this business.'}), 400
    if not data.get('consent'):
        return jsonify({'success': False, 'message': 'Consent is required before saving a face template.'}), 400
    if not desc:
        return jsonify({'success': False, 'message': 'Face not captured clearly. Please try again in good light.'}), 400
    # lấy kèm ma_nv: nhân viên chưa có face_enrolled_at thì projection chỉ 1 trường trả về {} (rỗng = 'không thấy')
    emp = db.employees.find_one({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0, 'ma_nv': 1, 'face_enrolled_at': 1})
    if not emp:
        return jsonify({'success': False, 'message': 'Employee not found.'}), 404
    if emp.get('face_enrolled_at'):
        # đã có mẫu: chỉ chủ tiệm xoá mẫu cũ mới đăng ký lại được (không ai tự thay mặt người khác)
        return jsonify({'success': False, 'message': 'A face is already registered for this employee. Ask the owner to reset it.'}), 409
    now = datetime.now().isoformat()
    db.employees.update_one({'business_id': bid, 'ma_nv': ma_nv},
                            {'$set': {'face_template': desc, 'face_enrolled_at': now, 'face_consent_at': now}})
    return jsonify({'success': True, 'token': make_token(bid, ma_nv)})


@face_bp.route('/api/hr/face/verify', methods=['POST'])
@login_required
def face_verify():
    bid = _bid()
    data = request.get_json() or {}
    ma_nv = (data.get('ma_nv') or '').strip().upper()
    desc = _clean_descriptor(data.get('descriptor'))
    if not desc:
        return jsonify({'success': False, 'message': 'Face not captured clearly. Please try again.'}), 400
    emp = db.employees.find_one({'business_id': bid, 'ma_nv': ma_nv}, {'_id': 0, 'face_template': 1})
    if not emp or not emp.get('face_template'):
        return jsonify({'success': False, 'message': 'No face registered for this employee yet.', 'need_enroll': True}), 404
    dist = round(_distance(desc, emp['face_template']), 4)
    ok = dist < MATCH_THRESHOLD
    db.face_checks.insert_one({'business_id': bid, 'ma_nv': ma_nv, 'distance': dist, 'match': ok, 'at': datetime.now().isoformat()})
    if not ok:
        return jsonify({'success': False, 'match': False, 'distance': dist,
                        'message': "Face doesn't match this employee code."}), 403
    return jsonify({'success': True, 'match': True, 'distance': dist, 'token': make_token(bid, ma_nv)})


@face_bp.route('/api/hr/face/<ma_nv>', methods=['DELETE'])
@login_required
@role_required('admin', 'super_admin')
def face_reset(ma_nv):
    bid = _bid()
    r = db.employees.update_one({'business_id': bid, 'ma_nv': ma_nv.strip().upper()},
                                {'$unset': {'face_template': '', 'face_enrolled_at': '', 'face_consent_at': ''}})
    return jsonify({'success': r.matched_count == 1})


def guard_checkin(business_id, data):
    """Gọi trong /api/hr/chamcong: check-in CÓ ẢNH (từ app nhân viên) khi tiệm bật khuôn mặt phải có vé hợp lệ.
    Trả (ok, error_message, extra_fields)."""
    if not data.get('anh_checkin') or not face_enabled(business_id):
        return True, None, {}
    ma_nv = (data.get('ma_nv') or '').strip().upper()
    if check_token(business_id, ma_nv, data.get('face_token')):
        return True, None, {'face_verified': True}
    if data.get('offline_sync'):
        # chấm lúc mất mạng (không xác minh được) -> vẫn ghi nhưng gắn cờ để chủ tiệm xem lại
        return True, None, {'face_verified': False, 'face_note': 'offline — not verified'}
    return False, 'Face check required: please check in from the staff app and look at the camera.', {}
