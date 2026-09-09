# ========================================================================================
# MODULE NGÀNH NAILS — Cổng đặt lịch công khai qua QR (nhân bản từ blueprints/spa_bp.py theo
# đúng kiến trúc "1 ngành = 1 file" đã ghi trong file đó).
#
# BUG THẬT đã phát hiện lúc audit: landing_nail.html quảng cáo thẳng "Customers book
# appointments online themselves via the Online Booking Portal" trỏ vào url_for('public_booking')
# — nhưng route đó (spa_bp.py) LỌC CỨNG channel_type='spa'. Dịch vụ Nails lưu với business_id +
# is_active (không lọc channel_type — xem app.py::sell() nhánh business_mode=='nail'), nên KHÔNG
# BAO GIỜ khớp filter đó: tiệm Nails quét QR/mở link booking sẽ luôn thấy danh sách dịch vụ RỖNG,
# dù trang landing đang quảng cáo tính năng này hoạt động. File này vá đúng bằng cách thêm 1 cổng
# booking RIÊNG cho Nails, lọc dữ liệu ĐÚNG CÁCH /sell (nail) đang dùng — không đụng gì tới
# spa_bp.py/booking Spa hiện có.
#
# Cùng dùng chung template booking.html (đã kiểm tra: không hardcode chữ "Spa" ở đâu cả, purely
# "Book a Service") và route /create_appointment (đã ngành-trung-lập sẵn — tự resolve business_id
# qua chính service_id được chọn, không quan tâm ngành nào).
# ========================================================================================

from flask import render_template

from mongo_client import db
from app import app


@app.route('/booking/nail')
@app.route('/booking/nail/qr/<business_id>')
@app.route('/booking/nail/service/<service_id>')
def public_booking_nail(business_id=None, service_id=None):
    # KHÔNG lấy business_id qua service_id ở đây (route Spa gốc cũng không) — cố ý an toàn hơn
    # bản gốc: thiếu business_id -> KHÔNG query gì cả, tránh trộn dịch vụ của MỌI tiệm Nails vào
    # 1 trang khi ai đó mở link trần /booking/nail (link quảng cáo trên landing_nail.html chỉ
    # minh hoạ tính năng, không đại diện 1 tiệm cụ thể nào).
    services_data = []
    technicians = []
    if business_id:
        try:
            # Lọc ĐÚNG như app.py::sell() (nhánh nail) đang dùng cho chính màn POS — không lọc
            # channel_type, vì dịch vụ Nails không gắn field đó theo giá trị 'nail' nào cả.
            services_data = list(db.products.find(
                {'business_id': business_id, 'is_active': 1}, {'_id': 0}
            ).sort('name', 1))
        except Exception as e:
            print(f"MongoDB public_booking_nail services select failed: {str(e)}")
            services_data = []
        try:
            # ĐÚNG nguồn thợ pos_nail.html/app.py::sell() đang dùng (db.employees,
            # linh_vuc='Nails') — chuẩn hoá về {id, name} khớp shape với spa_bp.py để
            # booking.html dùng chung 1 đoạn JS render dropdown, không cần biết đang ở ngành nào.
            technicians = [
                {'id': e_doc['ma_nv'], 'name': e_doc['ho_ten']}
                for e_doc in db.employees.find(
                    {'business_id': business_id, 'linh_vuc': 'Nails'}, {'ma_nv': 1, 'ho_ten': 1, '_id': 0}
                )
            ]
        except Exception as e:
            print(f"MongoDB public_booking_nail technicians select failed: {str(e)}")
            technicians = []
    return render_template(
        'booking.html', services=services_data, technicians=technicians,
        pre_selected_service_id=service_id, spa_id=business_id,
    )
