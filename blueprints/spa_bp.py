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
from app import app, limiter, login_required, role_required, allowed_file, _assert_owns_product, _assert_owns_row_mongo, _brand_setting_get
from booking_engine import book_appointment, SlotAlreadyBookedError
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
    # Kỹ thuật viên (db.employees — cùng danh sách app nhân viên/chấm công/lương) để gán cho TỪNG dịch vụ trong giỏ:
    # hoa hồng ghi thẳng vào chấm công -> Bảng lương tự có, không phải nhập tay lần 2 ở màn Chấm công Spa.
    try:
        therapists = [{'ma_nv': e['ma_nv'], 'ho_ten': e.get('ho_ten') or e['ma_nv']} for e in db.employees.find(
            {'business_id': business_id, 'linh_vuc': {'$regex': 'spa|nail', '$options': 'i'}}, {'ma_nv': 1, 'ho_ten': 1, '_id': 0}
        ).sort('ho_ten', 1) if e.get('ma_nv')]
    except Exception as db_err:
        print(f"MongoDB therapists select failed: {str(db_err)}")
        therapists = []
    return render_template('spa.html', services=services_data, brand_name=brand_name, brand_color=brand_color,
                           therapists=therapists)


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
    # BUG THẬT NGHIÊM TRỌNG đã vá (audit cách ly QR đa tiệm): thiếu spa_id trước đây vẫn CHẠY
    # query không lọc business_id -> gộp dịch vụ của MỌI tiệm Spa trong toàn hệ thống vào 1
    # trang — và landing_spa.html/landing_hotel.html lại gắn link demo url_for('public_booking')
    # THẲNG RA TRANG MARKETING CÔNG KHAI (không qua QR, không có spa_id), nghĩa là bất kỳ khách
    # nào bấm vào link "Cổng đặt lịch online" trên trang giới thiệu sản phẩm đều thấy dịch vụ/
    # giá của MỌI tiệm Spa đang dùng hệ thống trộn chung — đúng kiểu lỗi "quét tiệm này ra tiệm
    # khác" nghiêm trọng nhất. Sửa theo ĐÚNG mẫu an toàn nail_bp.py::public_booking_nail() đã
    # áp dụng: thiếu spa_id -> KHÔNG query gì cả, trả về rỗng thay vì trộn dữ liệu.
    services_data = []
    business_name = None
    biz_doc = None
    if spa_id:
        try:
            services_data = list(db.products.find(
                {'is_active': 1, 'channel_type': 'spa', 'name': {'$ne': 'Phí Dịch Vụ Spa'}, 'business_id': spa_id},
                {'_id': 0}
            ))
        except Exception as e:
            print(f"MongoDB public_booking services select failed: {str(e)}")
            services_data = []
        try:
            # Tên tiệm để hiển thị ngay trên trang booking công khai thay vì luôn ghi cứng
            # "BitPaw Services" — khớp mẫu đã áp dụng ở nail_bp.py::public_booking_nail().
            biz_doc = db.businesses.find_one({'id': spa_id}, {'name': 1, 'phone': 1, 'address': 1, '_id': 0})
            business_name = (biz_doc or {}).get('name')
        except Exception as e:
            print(f"MongoDB public_booking business lookup failed: {str(e)}")
            business_name = None
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
        business_name=business_name,
        shop_phone=((biz_doc or {}).get('phone') or ''),
        shop_address=((biz_doc or {}).get('address') or ''),
        booking_auto_confirm=_auto_confirm(spa_id),
        # Logo tiệm (Cài đặt thương hiệu) cho phần đầu trang đặt lịch — khách quét QR thấy đúng thương hiệu tiệm
        shop_logo_url=((db.system_settings.find_one({'key': 'brand_logo_url', 'business_id': spa_id}, {'value': 1, '_id': 0}) or {}).get('value')
                       if spa_id else None),
    )


# Trang đặt lịch công khai: 1 IP tối đa 30 lượt/giờ (khách quét QR trên Wi-Fi của tiệm dùng chung IP nên không để
# quá thấp) + 1 SĐT tối đa PUBLIC_BOOKINGS_PER_PHONE lịch sắp tới. Kiểm thử tải: 1 kẻ phá gửi 300 lịch giả từ 1 IP/1 SĐT
# thì CẢ 300 vào thẳng Lịch của chủ tiệm, đẩy lịch thật của khách xuống dưới.
PUBLIC_BOOKINGS_PER_PHONE = 3


@app.route('/create_appointment', methods=['POST'])
@limiter.limit("30 per hour")
def create_appointment():
    data = request.json or {}
    import security_shield
    if security_shield.honeypot_tripped(data):  # bot điền ô ẩn -> "thành công" giả, không tạo lịch
        security_shield.strike(security_shield.client_ip(request), 'honeypot: booking form', 1, request.path,
                               request.headers.get('User-Agent', ''))
        return jsonify({'success': True, 'id': 0, 'status': 'pending'})
    try:
        # BUG THẬT đã vá (phát hiện khi live-test QR booking Nails): booking.html gửi
        # service_id qua JS `<select>.value`, LUÔN LUÔN là string — nhưng db.products.id lưu
        # kiểu int (xem next_mongo_id()/mọi route tạo sản phẩm khác). MongoDB match tuyệt đối
        # theo kiểu dữ liệu: find_one({'id': "192"}) KHÔNG khớp document có id=192 (int), nên
        # MỌI lượt đặt lịch qua trang booking công khai/QR trước đây đều rớt 400 "Dịch vụ không
        # tồn tại" — dù khách chọn đúng dịch vụ thật đang hiển thị ngay trên form. Ép kiểu int
        # trước khi query (fallback về giá trị gốc nếu không phải số, phòng khi có id dạng chuỗi
        # ở nơi khác) để khớp đúng kiểu đang lưu thật trong DB.
        raw_service_id = data.get('service_id')
        # Route công khai: chỉ nhận số nguyên — trước đây giá trị không ép được kiểu (vd dict
        # {"$gt": 0}) đi thẳng vào query, khớp bừa dịch vụ của tiệm khác.
        try:
            service_id = int(raw_service_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Service not found. / Dịch vụ không tồn tại.'}), 400
        svc = db.products.find_one({'id': service_id}, {'business_id': 1, 'name': 1, '_id': 0})
        if not svc:
            return jsonify({'success': False, 'message': 'Service not found. / Dịch vụ không tồn tại.'}), 400
        vi = _shop_is_vi(svc['business_id'])
        staff_raw = data.get('staff_id')
        if staff_raw not in (None, '') and not isinstance(staff_raw, (str, int)):
            return jsonify({'success': False, 'message': 'Nhân viên không hợp lệ.' if vi else 'Invalid team member.'}), 400
        for _f in ('name', 'phone', 'book_time'):
            if not isinstance(data.get(_f), str) or not data.get(_f).strip():
                return jsonify({'success': False, 'message': 'Thiếu thông tin đặt lịch.' if vi else 'Please fill in your name, phone and time.'}), 400
        upcoming = db.appointments.count_documents({
            'business_id': svc['business_id'], 'customer_phone': data['phone'].strip(),
            'status': {'$in': ['pending', 'confirmed']}, 'book_time': {'$gte': datetime.now().strftime('%Y-%m-%dT%H:%M')},
        })
        if upcoming >= PUBLIC_BOOKINGS_PER_PHONE:
            return jsonify({'success': False, 'message': (f'Số điện thoại này đã có {upcoming} lịch hẹn sắp tới. Vui lòng gọi tiệm nếu cần đổi hoặc đặt thêm.'
                                                         if vi else f'This phone number already has {upcoming} upcoming bookings. '
                                                         'Please call the business to change or add more.')}), 429
        appointment = book_appointment(
            business_id=svc['business_id'],
            customer_info={'name': data['name'].strip()[:80], 'phone': data['phone'].strip()[:20]},
            staff_id=data.get('staff_id'),
            book_time=data['book_time'],
            service_id=service_id,
            note=data.get('note'),
            source='web',
        )
    except SlotAlreadyBookedError as e:
        msg = str(e)
        if ' / ' in msg:  # "EN / VI" từ booking_rules -> đúng ngôn ngữ của tiệm
            en, vi = msg.split(' / ', 1)
            msg = vi if _shop_is_vi(svc.get('business_id')) else en
        return jsonify({'success': False, 'message': msg}), 409
    except Exception as e:
        return jsonify({'success': False, 'message': f'Could not create the booking: {str(e)}'}), 400

    # Báo email chủ tiệm giờ nằm NGAY TRONG book_appointment() (booking_engine.py) — chạy cho
    # MỌI nguồn tạo lịch hẹn (QR công khai LẪN AI Bot), không riêng route này nữa. Xem comment
    # đầu file booking_engine.py để biết lý do dời (bug thật: AI Bot từng không báo được).
    return jsonify({'success': True, 'id': appointment['id'], 'status': appointment.get('status'), 'book_time': appointment.get('book_time'),
                    'service_name': svc.get('name')})


def _shop_is_vi(business_id):
    b = db.businesses.find_one({'id': business_id}, {'_id': 0, 'country': 1}) or {}
    return (b.get('country') or 'VN').upper() == 'VN'


@app.route('/chamcong/spa')
@app.route('/chamcong_spa')
@login_required
@role_required('admin', 'super_admin')
def chamcong_spa():
    return render_template('chamcong_spa.html')


def _auto_confirm(business_id):
    """Chip "Xác nhận ngay" trên trang đặt lịch chỉ hiện khi tiệm thật sự tự xác nhận (Cài đặt đặt lịch)."""
    if not business_id:
        return False
    try:
        import booking_rules
        return bool(booking_rules.get_rules(business_id).get('auto_confirm', True))
    except Exception:
        return False
