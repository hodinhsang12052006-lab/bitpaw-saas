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
from html import escape as _html_escape
from flask import render_template, request, redirect, url_for, jsonify, session

from mongo_client import db, next_mongo_id
from app import app, login_required, role_required, allowed_file, _assert_owns_product, _assert_owns_row_mongo, _brand_setting_get
from booking_engine import book_appointment, SlotAlreadyBookedError
from email_service import EmailService
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
                'business_id': business_id,
                'created_at': datetime.now().isoformat(),
                'status': 'completed',
                'total_amount': total_price,
                'payment_method': 'cash',
                'metadata': {'order_code': order_code, 'channel': 'spa'},
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
    # Cho khách TỰ chọn thợ (tuỳ chọn) thay vì luôn để tiệm tự xếp — db.staff là nguồn nhân sự
    # Spa đang dùng cho commission/chấm công (xem add_staff()), CHỈ trả id+name (không lộ phone/
    # commission_rate — public route, không có session). {id, name} khớp shape với nail_bp.py để
    # booking.html dùng chung 1 đoạn JS render dropdown, không cần biết đang ở ngành nào.
    technicians = []
    if spa_id:
        try:
            technicians = [
                {'id': s['id'], 'name': s['name']}
                for s in db.staff.find({'business_id': spa_id, 'is_active': True}, {'id': 1, 'name': 1, '_id': 0})
            ]
        except Exception as e:
            print(f"MongoDB public_booking technicians select failed: {str(e)}")
            technicians = []
    return render_template(
        'booking.html', services=services_data, technicians=technicians,
        pre_selected_service_id=service_id, spa_id=spa_id,
    )


@app.route('/create_appointment', methods=['POST'])
def create_appointment():
    data = request.json or {}
    try:
        # Route public (khách đặt lịch, không có session) — xác định business_id qua dịch vụ được chọn
        svc = db.products.find_one({'id': data['service_id']}, {'business_id': 1, 'name': 1, '_id': 0})
        if not svc:
            return jsonify({'success': False, 'message': 'Dịch vụ không tồn tại.'}), 400
        appointment = book_appointment(
            business_id=svc['business_id'],
            customer_info={'name': data['name'], 'phone': data['phone']},
            staff_id=data.get('staff_id'),
            book_time=data['book_time'],
            service_id=data['service_id'],
            note=data.get('note'),
            source='web',
        )
    except SlotAlreadyBookedError as e:
        return jsonify({'success': False, 'message': str(e)}), 409
    except Exception as e:
        return jsonify({'success': False, 'message': f'Không thể tạo lịch hẹn: {str(e)}'}), 400

    _notify_owner_new_appointment(svc, appointment)
    return jsonify({'success': True, 'id': appointment['id']})


def _notify_owner_new_appointment(svc, appointment):
    """Báo NGƯỜI TIỆM (không phải khách — Zalo OA không gửi được cho SĐT lạ chưa từng chat với
    OA, và hệ thống chưa tích hợp nhà cung cấp SMS nào) ngay khi có booking mới qua QR/link công
    khai (Spa lẫn Nails, route này dùng chung). Trước đây booking rơi thẳng vào db.appointments,
    không ai được báo — chủ tiệm chỉ biết khi tự mở lịch lên xem, dễ bỏ sót/trễ xác nhận với
    khách. Best-effort tuyệt đối: lỗi gửi email KHÔNG BAO GIỜ được làm hỏng response đặt lịch đã
    thành công của khách — hàm này gọi SAU khi book_appointment() đã insert xong."""
    try:
        owner = db.users.find_one(
            {'business_id': appointment['business_id'], 'role': 'admin'}, {'email': 1, '_id': 0}
        )
        owner_email = (owner or {}).get('email')
        if not owner_email:
            return
        try:
            book_time_display = datetime.fromisoformat(appointment['book_time']).strftime('%H:%M, %d/%m/%Y')
        except (TypeError, ValueError):
            book_time_display = appointment['book_time']
        # Escape TOÀN BỘ dữ liệu khách tự nhập (tên/SĐT/ghi chú) trước khi nhét vào HTML email —
        # đây là input công khai, không xác thực (route /create_appointment không có session),
        # thiếu escape thì 1 khách gõ tên/ghi chú chứa thẻ HTML sẽ chèn được HTML tuỳ ý vào email
        # thật của chủ tiệm (hiển thị sai lệch/giả mạo nội dung khi họ mở email trên client HTML).
        safe_name = _html_escape(appointment['customer_name'] or '')
        safe_phone = _html_escape(appointment['customer_phone'] or '')
        safe_service = _html_escape((svc or {}).get('name') or '')
        safe_note = _html_escape(appointment.get('note') or '') or '(không có)'
        body = f"""
            <div style="font-family:sans-serif;max-width:480px;margin:0 auto;">
                <h2 style="color:#06b6d4;">🔔 Lịch hẹn mới qua cổng đặt lịch online</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr><td style="padding:6px 0;color:#666;">Khách hàng</td><td style="padding:6px 0;font-weight:bold;">{safe_name}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Số điện thoại</td><td style="padding:6px 0;font-weight:bold;">{safe_phone}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Dịch vụ</td><td style="padding:6px 0;font-weight:bold;">{safe_service}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;">Giờ hẹn</td><td style="padding:6px 0;font-weight:bold;color:#06b6d4;">{book_time_display}</td></tr>
                    <tr><td style="padding:6px 0;color:#666;vertical-align:top;">Ghi chú</td><td style="padding:6px 0;">{safe_note}</td></tr>
                </table>
                <p style="color:#999;font-size:12px;margin-top:16px;">Vui lòng gọi lại xác nhận với khách sớm nhất có thể — lịch hẹn đang ở trạng thái "pending" chờ tiệm duyệt trên Lịch (Calendar).</p>
            </div>
        """
        ok, msg = EmailService.send_email(
            owner_email, f"🔔 Lịch hẹn mới: {safe_name} — {book_time_display}", body
        )
        if not ok:
            print(f"[create_appointment] Gửi email báo lịch hẹn mới thất bại (business_id={appointment['business_id']}): {msg}")
    except Exception as e:
        print(f"[create_appointment] Lỗi báo lịch hẹn mới qua email (không ảnh hưởng booking đã tạo): {str(e)}")


@app.route('/chamcong/spa')
@app.route('/chamcong_spa')
@login_required
@role_required('admin', 'super_admin')
def chamcong_spa():
    return render_template('chamcong_spa.html')
