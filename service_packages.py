"""
Gói liệu trình / gói nhiều buổi (Spa, Nails): "mua 10 buổi massage giá 900".

  - Định nghĩa gói (db.service_packages): tên, số buổi, giá, dịch vụ áp dụng (trống = mọi dịch vụ), hạn dùng (ngày).
  - Bán gói tại quầy (/api/packages/sell): tạo đơn hàng + sổ cái (doanh thu ghi NGAY lúc bán) và thẻ gói của khách
    (db.customer_packages) gắn theo SĐT.
  - Dùng buổi khi thanh toán ở POS Spa: dòng dịch vụ gửi kèm package_id -> giá 0 trên bill, trừ 1 buổi NGUYÊN TỬ
    (điều kiện sessions_left >= số buổi), lịch sử ghi số đơn. Hoa hồng KTV tính theo giá trị 1 buổi của gói.
    Hoàn tiền đơn -> trả lại buổi đã dùng.
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

from app import login_required, role_required
from mongo_client import db, next_mongo_id

packages_bp = Blueprint('packages', __name__)


def _bid():
    return session.get('business_id') or session.get('user_id')


def _phone(v):
    return re.sub(r'[^\d+]', '', str(v or ''))[:20]


def active_for(business_id, phone):
    """Thẻ gói còn buổi + còn hạn của 1 khách."""
    phone = _phone(phone)
    if not phone:
        return []
    now = datetime.now().isoformat()
    return list(db.customer_packages.find({'business_id': business_id, 'customer_phone': phone, 'sessions_left': {'$gt': 0},
                                           '$or': [{'expires_at': None}, {'expires_at': {'$gt': now}}]},
                                          {'_id': 0, 'history': 0}).sort('expires_at', 1))


def price_items(business_id, items_payload, order_items_docs, products_map, customer_phone):  # noqa: ARG001
    """Gọi từ _compute_cart_order: dòng có package_id -> kiểm tra gói hợp lệ cho khách + dịch vụ, đặt giá 0.
    Không trừ buổi ở đây (xem redeem). Trả tổng tiền đã miễn (để trừ khỏi subtotal)."""
    waived = 0.0
    phone = _phone(customer_phone)
    for it, oi in zip(items_payload, order_items_docs):
        pid = it.get('package_id')
        if pid in (None, ''):
            continue
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise ValueError('Invalid package.')
        cp = db.customer_packages.find_one({'business_id': business_id, 'id': pid}, {'_id': 0, 'history': 0})
        if not cp or not phone or cp.get('customer_phone') != phone:
            raise ValueError('This package does not belong to this customer.')
        if cp.get('expires_at') and cp['expires_at'] <= datetime.now().isoformat():
            raise ValueError('This package has expired.')
        if cp.get('service_ids') and oi['product_id'] not in cp['service_ids']:
            raise ValueError(f"The package \"{cp.get('name')}\" does not cover this service.")
        if int(cp.get('sessions_left') or 0) < oi['quantity']:
            raise ValueError(f"Not enough sessions left on \"{cp.get('name')}\".")
        waived += float(oi['total_price'])
        oi['package_id'] = pid
        oi['commission_value'] = round(float(cp.get('session_value') or 0) * oi['quantity'], 2)
        oi['list_price'] = oi['price']
        oi['price'] = 0
        oi['total_price'] = 0
    return round(waived, 2)


def redeem(business_id, order_items_docs):
    """Trừ buổi NGUYÊN TỬ trước khi ghi đơn. Lỗi giữa chừng -> hoàn các buổi đã trừ rồi raise."""
    done = []
    for oi in order_items_docs:
        if not oi.get('package_id'):
            continue
        r = db.customer_packages.update_one({'business_id': business_id, 'id': oi['package_id'], 'sessions_left': {'$gte': oi['quantity']}},
                                            {'$inc': {'sessions_left': -oi['quantity'], 'sessions_used': oi['quantity']}})
        if r.modified_count != 1:
            restore(business_id, done)
            raise ValueError('Package sessions were just used up. Please refresh and try again.')
        done.append((oi['package_id'], oi['quantity']))
    return done


def restore(business_id, redeemed, order_id=None, reason='rollback'):
    for pid, qty in redeemed:
        db.customer_packages.update_one({'business_id': business_id, 'id': pid},
                                        {'$inc': {'sessions_left': qty, 'sessions_used': -qty},
                                         '$push': {'history': {'at': datetime.now().isoformat(), 'order_id': order_id, 'qty': qty, 'type': reason}}})


def log_use(business_id, redeemed, order_id):
    for pid, qty in redeemed:
        db.customer_packages.update_one({'business_id': business_id, 'id': pid},
                                        {'$push': {'history': {'at': datetime.now().isoformat(), 'order_id': order_id, 'qty': -qty, 'type': 'use'}}})


# ---------------------------------------------------------------- trang + API
@packages_bp.route('/packages')
@login_required
@role_required('admin', 'super_admin')
def packages_page():
    return render_template('packages.html')


@packages_bp.route('/api/packages', methods=['GET', 'POST'])
@login_required
def packages_api():
    bid = _bid()
    if request.method == 'GET':
        defs = list(db.service_packages.find({'business_id': bid, 'active': {'$ne': False}}, {'_id': 0}).sort('id', -1))
        services = list(db.products.find({'business_id': bid, 'is_active': {'$in': [1, True]}, 'price': {'$gt': 0}},
                                         {'_id': 0, 'id': 1, 'name': 1, 'price': 1}).sort('name', 1).limit(300))
        sold = list(db.customer_packages.find({'business_id': bid}, {'_id': 0}).sort('id', -1).limit(200))
        biz = db.businesses.find_one({'id': bid}, {'_id': 0, 'currency': 1}) or {}
        return jsonify({'success': True, 'packages': defs, 'services': services, 'sold': sold, 'currency': (biz.get('currency') or 'USD').upper()})
    if session.get('role') not in ('admin', 'super_admin'):
        return jsonify({'success': False, 'message': 'Only the owner can create packages.'}), 403
    d = request.json or {}
    name = str(d.get('name') or '').strip()[:80]
    try:
        sessions = int(d.get('sessions'))
        price = round(float(d.get('price')), 2)
        valid_days = int(d.get('valid_days') or 0)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Sessions, price and validity must be numbers.'}), 400
    if not name or not (1 <= sessions <= 200) or not (0 < price < 1e9) or not (0 <= valid_days <= 3650):
        return jsonify({'success': False, 'message': 'Enter a name, 1–200 sessions and a price above 0.'}), 400
    sids = []
    for x in (d.get('service_ids') or [])[:50]:
        try:
            sids.append(int(x))
        except (TypeError, ValueError):
            pass
    if sids and db.products.count_documents({'business_id': bid, 'id': {'$in': sids}}) != len(set(sids)):
        return jsonify({'success': False, 'message': 'Unknown service.'}), 400
    doc = {'id': next_mongo_id('service_packages'), 'business_id': bid, 'name': name, 'sessions': sessions, 'price': price,
           'valid_days': valid_days, 'service_ids': sorted(set(sids)), 'active': True, 'created_at': datetime.now().isoformat()}
    db.service_packages.insert_one(doc)
    doc.pop('_id', None)
    return jsonify({'success': True, 'data': doc})


@packages_bp.route('/api/packages/<int:pkg_id>', methods=['DELETE'])
@login_required
@role_required('admin', 'super_admin')
def packages_retire(pkg_id):
    """Ngừng bán gói (thẻ gói khách đã mua vẫn dùng tiếp bình thường)."""
    r = db.service_packages.update_one({'business_id': _bid(), 'id': pkg_id}, {'$set': {'active': False}})
    return jsonify({'success': r.matched_count == 1})


@packages_bp.route('/api/packages/sell', methods=['POST'])
@login_required
def packages_sell():
    bid = _bid()
    d = request.json or {}
    try:
        pkg_id = int(d.get('package_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Choose a package.'}), 400
    pkg = db.service_packages.find_one({'business_id': bid, 'id': pkg_id, 'active': {'$ne': False}}, {'_id': 0})
    phone = _phone(d.get('customer_phone'))
    if not pkg:
        return jsonify({'success': False, 'message': 'Package not found.'}), 404
    if len(re.sub(r'\D', '', phone)) < 6:
        return jsonify({'success': False, 'message': 'Enter the customer\'s phone number.'}), 400
    method = str(d.get('payment_method') or 'cash').strip().lower()[:32]
    name = str(d.get('customer_name') or '').strip()[:80]
    now = datetime.now()
    from app import _record_pos_transaction
    order_id = next_mongo_id('orders')
    db.orders.insert_one({'id': order_id, 'business_id': bid, 'created_at': now.isoformat(), 'status': 'completed',
                          'total_amount': pkg['price'], 'payment_method': method,
                          'metadata': {'channel': 'package_sale', 'package_id': pkg['id'], 'package_name': pkg['name'],
                                       'customer_phone': phone, 'customer_name': name, 'subtotal': pkg['price'],
                                       'payment_bucket': 'cash' if method == 'cash' else 'card'}})
    _record_pos_transaction(bid, order_id, pkg['price'], method)
    cp = {'id': next_mongo_id('customer_packages'), 'business_id': bid, 'package_id': pkg['id'], 'name': pkg['name'],
          'customer_phone': phone, 'customer_name': name, 'sessions_total': pkg['sessions'], 'sessions_left': pkg['sessions'],
          'sessions_used': 0, 'session_value': round(pkg['price'] / pkg['sessions'], 2), 'service_ids': pkg.get('service_ids') or [],
          'price_paid': pkg['price'], 'order_id': order_id, 'purchased_at': now.isoformat(),
          'expires_at': (now + timedelta(days=pkg['valid_days'])).isoformat() if pkg.get('valid_days') else None,
          'history': [{'at': now.isoformat(), 'order_id': order_id, 'qty': pkg['sessions'], 'type': 'purchase'}]}
    db.customer_packages.insert_one(cp)
    if not db.customers.find_one({'business_id': bid, 'phone': phone}, {'_id': 1}):
        try:
            db.customers.insert_one({'id': next_mongo_id('customers'), 'business_id': bid, 'phone': phone,
                                     'name': name or f"Customer {phone[-4:]}", 'join_date': now.date().isoformat(), 'total_spent': 0, 'loyalty_points': 0})
        except Exception:
            pass
    cp.pop('_id', None)
    return jsonify({'success': True, 'data': cp, 'order_id': order_id})


@packages_bp.route('/api/packages/customer', methods=['GET'])
@login_required
def packages_for_customer():
    return jsonify({'success': True, 'data': active_for(_bid(), request.args.get('phone'))})
