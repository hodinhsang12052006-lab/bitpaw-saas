# ========================================================================================
# MODULE NGÀNH SPA & BEAUTY — file mẫu cho kiến trúc "1 ngành = 1 file".
#
# Toàn bộ route/logic riêng của ngành Spa (trang quản lý dịch vụ, thêm/xoá dịch vụ, checkout,
# trang đặt lịch công khai cho khách, chấm công) nằm trong ĐÚNG 1 file này. Muốn "đục mã" custom
# cho 1 khách ngành Spa, chỉ cần mở file này — sửa gì ở đây KHÔNG BAO GIỜ ảnh hưởng tới F&B,
# Nail, Karaoke... vì các ngành đó có route/module riêng của chúng, hoàn toàn tách biệt.
#
# TẠI SAO KHÔNG DÙNG flask.Blueprint: đã thử — Blueprint LUÔN tự thêm tiền tố tên blueprint vào
# endpoint (vd route "spa" trong Blueprint tên "spa_bp" sẽ đăng ký thành endpoint "spa_bp.spa",
# KHÔNG có cách nào override bằng tham số endpoint=...). Rất nhiều template có sẵn (spa.html,
# add_spa.html, brand_settings.html, landing_spa.html, fnb_dashboard.html...) đang gọi thẳng
# {{ url_for('spa') }}, {{ url_for('add_spa') }}, {{ url_for('public_booking') }},
# {{ url_for('chamcong_spa') }} — nếu đổi thành "spa_bp.spa" sẽ vỡ toàn bộ url_for() đó ngay khi
# render (werkzeug.routing.BuildError), phải sửa lại hàng chục chỗ. Đăng ký thẳng vào `app` (như
# file này làm) giữ NGUYÊN VẸN tên endpoint cũ — không cần sửa bất kỳ template nào, mà logic vẫn
# tách file 100% như Blueprint.
#
# Cách nhân bản cho 1 ngành mới (vd F&B):
#   1. Copy file này thành blueprints/fnb_bp.py.
#   2. Copy các route F&B tương ứng từ app.py sang, giữ NGUYÊN tên hàm/route cũ.
#   3. Xoá các route F&B đó khỏi app.py (tránh đăng ký trùng URL — Flask sẽ báo lỗi ngay lúc
#      khởi động nếu 2 nơi cùng định nghĩa 1 route, không phải lỗi âm thầm).
#   4. Thêm 1 dòng "import blueprints.fnb_bp" vào khối "Register Blueprints" ở cuối app.py.
#
# LƯU Ý VỀ IMPORT: `from app import ...` bên dưới CHỈ an toàn vì app.py import module này ở
# CUỐI file (sau khi app/login_required/_assert_owns_product/... đã được định nghĩa xong) — xem
# app.py, khối "Register Blueprints". Đừng import blueprints/spa_bp ở ĐẦU app.py hay từ bất kỳ
# module nào chạy trước app.py, sẽ gây circular import lỗi thật.
# ========================================================================================

import os
import uuid
from datetime import datetime
from flask import render_template, request, redirect, url_for, jsonify, session

from mongo_client import db, next_mongo_id
from app import app, login_required, allowed_file, _assert_owns_product, _assert_owns_row_mongo, _brand_setting_get, _deny_if_staff_page
from werkzeug.utils import secure_filename


@app.route('/spa')
@login_required
def spa():
    business_id = session.get('business_id') or session['user_id']
    try:
        brand_name = _brand_setting_get(business_id, 'brand_name', 'BitPaw')
    except Exception as db_err:
        print(f"MongoDB brand_name select failed: {str(db_err)}")
        brand_name = 'BitPaw'
    try:
        brand_color = _brand_setting_get(business_id, 'brand_color', '#06b6d4')
    except Exception as db_err:
        print(f"MongoDB brand_color select failed: {str(db_err)}")
        brand_color = '#06b6d4'
    try:
        services_data = list(db.products.find(
            {'is_active': 1, 'channel_type': 'spa', 'business_id': business_id, 'name': {'$ne': 'Phí Dịch Vụ Spa'}},
            {'_id': 0}
        ).sort('name', 1))
    except Exception as db_err:
        print(f"MongoDB services select failed: {str(db_err)}")
        services_data = []
    return render_template('spa.html', services=services_data, brand_name=brand_name, brand_color=brand_color)


@app.route('/add_spa', methods=['GET', 'POST'])
@login_required
def add_spa():
    business_id = session.get('business_id') or session['user_id']
    if request.method == 'POST':
        try:
            image_file = request.files.get('image')
            filename = ""
            if image_file and image_file.filename != '' and allowed_file(image_file.filename):
                filename = secure_filename(image_file.filename)
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            db.products.insert_one({
                'id': next_mongo_id('products'),
                'name': request.form['name'],
                'category': 'Spa & Beauty',
                'channel_type': 'spa',
                'stock': 9999,
                'price': float(request.form['price']),
                'image': filename,
                'is_active': 1,
                'business_id': business_id
            })
            return redirect(url_for('spa'))
        except Exception as e:
            return f"Lỗi thêm dịch vụ spa: {str(e)}", 500
    return render_template('add_spa.html')


@app.route('/delete_spa/<int:id>')
@login_required
def delete_spa(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('products', id, business_id)
        if not owns:
            return err, 403
        db.products.update_one({'id': id, 'business_id': business_id}, {'$set': {'is_active': 0}})
        return redirect(url_for('spa'))
    except Exception as e:
        return f"Lỗi xóa dịch vụ spa: {str(e)}", 500


@app.route('/checkout_spa', methods=['POST'])
@login_required
def checkout_spa():
    business_id = session.get('business_id') or session['user_id']
    try:
        product_id = request.form['product_id']
        if not _assert_owns_product(product_id, business_id):
            return "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn.", 403
        qty = int(request.form['quantity'])
        prod = db.products.find_one({'id': product_id}, {'price': 1, '_id': 0})
        if prod:
            price = prod['price']
            total_price = price * qty
            order_code = f"SPA-{uuid.uuid4().hex[:8].upper()}"
            order_id = next_mongo_id('orders')
            db.orders.insert_one({
                'id': order_id,
                'order_code': order_code,
                'channel': 'spa',
                'total_amount': total_price,
                'business_id': business_id,
                'created_at': datetime.now().isoformat()
            })
            db.order_items.insert_one({
                'id': next_mongo_id('order_items'),
                'order_id': order_id,
                'product_id': product_id,
                'quantity': qty,
                'price': price,
                'total_price': total_price,
                'business_id': business_id
            })
        return redirect(url_for('spa'))
    except Exception as e:
        return f"Lỗi thanh toán spa: {str(e)}", 500


@app.route('/booking')
@app.route('/booking/qr/<spa_id>')
@app.route('/booking/service/<service_id>')
def public_booking(spa_id=None, service_id=None):
    try:
        query_filter = {'is_active': 1, 'channel_type': 'spa', 'name': {'$ne': 'Phí Dịch Vụ Spa'}}
        # spa_id trong QR chính là business_id của tiệm — chỉ hiện đúng dịch vụ của tiệm đó, không trộn tiệm khác
        if spa_id:
            query_filter['business_id'] = spa_id
        services_data = list(db.products.find(query_filter, {'_id': 0}))
    except Exception as e:
        print(f"MongoDB public_booking services select failed: {str(e)}")
        services_data = []
    return render_template('booking.html', services=services_data, pre_selected_service_id=service_id, spa_id=spa_id)


@app.route('/create_appointment', methods=['POST'])
def create_appointment():
    data = request.json or {}
    try:
        # Route public (khách đặt lịch, không có session) — xác định business_id qua dịch vụ được chọn
        svc = db.products.find_one({'id': data['service_id']}, {'business_id': 1, '_id': 0})
        if not svc:
            return jsonify({'success': False, 'message': 'Dịch vụ không tồn tại.'}), 400
        appointment_id = next_mongo_id('appointments')
        db.appointments.insert_one({
            'id': appointment_id,
            'customer_name': data['name'],
            'customer_phone': data['phone'],
            'service_id': data['service_id'],
            'staff_id': data.get('staff_id'),
            'book_time': data['book_time'],
            'note': data.get('note'),
            'status': 'pending',
            'business_id': svc['business_id']
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Không thể tạo lịch hẹn: {str(e)}'}), 400
    return jsonify({'success': True, 'id': appointment_id})


@app.route('/chamcong/spa')
@app.route('/chamcong_spa')
@login_required
def chamcong_spa():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_spa.html')
