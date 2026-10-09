"""
TÁCH NGÀNH NGHỀ — nguồn quy định DUY NHẤT: trang/API nào thuộc ngành nào.

Trước đây mọi tiệm đăng nhập vào là mở được trang của cả 9 ngành (sidebar chỉ ẩn link): tiệm Nails gõ
/pos vào là thấy sơ đồ bàn nhà hàng (và /pos tự tạo 200 bàn ăn rác trong dữ liệu của tiệm), /karaoke,
/hotel_rooms, /kitchen_display, chấm công của ngành khác... Nút "POS" của Spa còn dẫn nhầm vào POS nhà hàng.
Lỡ một link sai là khách thấy phần mềm ngành khác + dữ liệu lẫn lộn.

Quy tắc:
  - Endpoint KHÔNG có trong ENDPOINT_INDUSTRIES = dùng chung mọi ngành (CRM, AI, nhân sự, báo cáo, cài đặt...).
  - Endpoint CÓ trong bảng: chỉ các ngành liệt kê được dùng. Ngành khác -> trang HTML chuyển về trang chủ
    của chính ngành mình, API trả 403 JSON. Super admin / tài khoản chưa chọn ngành (đang /setup) bỏ qua.
  - Thêm trang/API riêng của 1 ngành mới -> thêm 1 dòng vào bảng dưới đây (scripts/industry_isolation_audit.mjs
    kiểm tra lại toàn bộ bảng cho cả 9 ngành).

Module này KHÔNG import app.py (app.py import nó) để không vòng lặp import.
"""
from urllib.parse import quote

INDUSTRIES = ('nail', 'spa', 'fnb', 'retail', 'karaoke', 'hotel', 'production', 'technical', 'office')

# Trang chủ / POS chính của từng ngành — dùng cho redirect khi bị chặn và cho nút "POS" ở sidebar.
INDUSTRY_HOME = {
    'nail': '/chamcong/nail', 'spa': '/spa', 'fnb': '/pos', 'retail': '/retail_pos', 'karaoke': '/karaoke',
    'hotel': '/hotel_rooms', 'production': '/production_output', 'technical': '/chamcong/kythuat',
    'office': '/chamcong/vanphong',
}
INDUSTRY_POS = {
    'nail': '/sell', 'spa': '/spa', 'fnb': '/pos', 'retail': '/retail_pos', 'karaoke': '/karaoke',
    'hotel': '/hotel_rooms', 'production': '/production_output', 'technical': '/chamcong/kythuat',
    'office': '/chamcong/vanphong',
}

# Mã ngành -> tên trang chấm công riêng (templates/chamcong_<slug>.html). Trước đây sidebar ghép thẳng
# /chamcong/<mã ngành>: hotel/technical/production/office không có template trùng tên nên rơi vào trang
# chấm công CHUNG chamcong.html thay vì trang riêng của ngành.
CHAMCONG_SLUG = {
    'nail': 'nail', 'spa': 'spa', 'fnb': 'fnb', 'karaoke': 'karaoke', 'retail': 'retail',
    'hotel': 'khachsan', 'technical': 'kythuat', 'production': 'congnhan', 'office': 'vanphong',
}
_SLUG_TO_INDUSTRY = {slug: code for code, slug in CHAMCONG_SLUG.items()}
_SLUG_TO_INDUSTRY.update({code: code for code in INDUSTRIES})

_NAIL = {'nail'}
_SPA = {'spa'}
_FNB = {'fnb'}
_RETAIL = {'retail'}
_KARAOKE = {'karaoke'}
_HOTEL = {'hotel'}
_PRODUCTION = {'production'}
_TECHNICAL = {'technical'}
_BOOKING = {'nail', 'spa'}          # lịch hẹn khách (Nails + Spa)

ENDPOINT_INDUSTRIES = {
    # ----- Nails
    'sell': _NAIL, 'chamcong_nail': _NAIL,
    'api_nail_pos_checkout': _NAIL, 'api_nail_pos_square_checkout': _NAIL, 'api_nail_pos_orders_list': _NAIL,
    'api_nail_pos_order_detail': _NAIL, 'api_nail_pos_refund': _NAIL, 'api_nail_pos_checked_in_list': _NAIL,
    'api_nail_pos_checked_in_load': _NAIL, 'api_qr_nail_booking': _NAIL, 'api_desktop_sync_status': _NAIL,
    # ----- Spa
    'spa': _SPA, 'add_spa': _SPA, 'delete_spa': _SPA, 'checkout_spa': _SPA, 'chamcong_spa': _SPA,
    # ----- Lịch hẹn (Nails + Spa)
    'calendar_view': _BOOKING, 'api_appointment_update_status': _BOOKING, 'api_appointment_mark_reminded': _BOOKING,
    'stream_appointments': _BOOKING, 'qr_poster_booking': _BOOKING,
    # ----- F&B
    'pos': _FNB, 'add_table': _FNB, 'view_table': _FNB, 'order_item': _FNB, 'checkout_table': _FNB,
    'kitchen_display': _FNB, 'fnb_dashboard': _FNB, 'reservations_page': _FNB, 'chamcong_fnb': _FNB,
    'api_pos_tables': _FNB, 'api_pos_products': _FNB, 'api_pos_get_table_orders': _FNB,
    'api_pos_add_order_item': _FNB, 'api_pos_clear_table_orders': _FNB, 'api_pos_delete_order_item': _FNB,
    'api_pos_override_order_item_price': _FNB, 'api_pos_deactivate_product': _FNB,
    'api_kitchen_orders_list': _FNB, 'api_kitchen_orders_update': _FNB, 'stream_kitchen': _FNB,
    'api_qr_table': _FNB, 'api_reservation_update': _FNB, 'qr_poster_table': _FNB, 'qr_menu_base': _FNB,
    # ----- Bán lẻ
    'retail_pos': _RETAIL,
    # ----- Karaoke
    'karaoke': _KARAOKE, 'karaoke_reservations_page': _KARAOKE, 'toggle_room': _KARAOKE,
    'api_karaoke_rooms_list': _KARAOKE, 'api_karaoke_rooms_create': _KARAOKE, 'api_karaoke_room_start': _KARAOKE,
    'api_karaoke_room_checkout': _KARAOKE, 'api_karaoke_reservation_update': _KARAOKE,
    # ----- Khách sạn
    'hotel_rooms_page': _HOTEL, 'hotel_reservations_page': _HOTEL, 'chamcong_khachsan': _HOTEL,
    'api_hotel_rooms_list': _HOTEL, 'api_hotel_rooms_create': _HOTEL, 'api_hotel_rooms_update': _HOTEL,
    'api_hotel_room_checkin': _HOTEL, 'api_hotel_room_checkout': _HOTEL, 'api_hotel_room_mark_clean': _HOTEL,
    'api_hotel_room_charges_list': _HOTEL, 'api_hotel_room_charges_add': _HOTEL,
    'api_hotel_room_charges_delete': _HOTEL, 'api_hotel_room_types_bulk_rate': _HOTEL,
    'api_hotel_reservation_update': _HOTEL,
    # ----- Sản xuất
    'production_output_page': _PRODUCTION, 'production_materials_page': _PRODUCTION, 'chamcong_congnhan': _PRODUCTION,
    'api_production_output_list': _PRODUCTION, 'api_production_output_create': _PRODUCTION,
    'api_production_output_delete': _PRODUCTION, 'api_production_output_summary': _PRODUCTION,
    'api_production_materials_list': _PRODUCTION, 'api_production_materials_create': _PRODUCTION,
    'api_production_materials_update': _PRODUCTION, 'api_production_materials_delete': _PRODUCTION,
    'api_production_recipes_list': _PRODUCTION, 'api_production_recipes_create': _PRODUCTION,
    'api_production_recipes_delete': _PRODUCTION,
    # ----- Kỹ thuật (điều phối, phụ tùng)
    'chamcong_kythuat': _TECHNICAL, 'map_dashboard': _TECHNICAL, 'technical_parts_page': _TECHNICAL,
    'api_tech_parts_list': _TECHNICAL, 'api_tech_parts_create': _TECHNICAL, 'api_tech_parts_update': _TECHNICAL,
    'api_tech_parts_delete': _TECHNICAL,
    # ----- Văn phòng
    'chamcong_vanphong': {'office'},
}

# Trang/API công khai cho KHÁCH (không đăng nhập) gắn với 1 tiệm cụ thể — kiểm tra theo ngành CỦA TIỆM ĐÓ
# (xem app.py: _public_industry_guard). endpoint -> ngành được phép.
PUBLIC_ENDPOINT_INDUSTRIES = {
    'public_booking_nail': _NAIL,
    'public_booking': _SPA,
    'public_table_reservation': _FNB, 'api_public_reservation_create': _FNB,
    'public_karaoke_reservation': _KARAOKE, 'api_public_karaoke_reservation_create': _KARAOKE,
    'public_hotel_reservation': _HOTEL, 'api_public_hotel_reservation_create': _HOTEL,
}


def allowed_industries(endpoint, view_args=None):
    """Tập ngành được dùng endpoint này, hoặc None nếu dùng chung mọi ngành."""
    if endpoint == 'chamcong_industry':
        slug = ((view_args or {}).get('industry_code') or '').strip().lower()
        code = _SLUG_TO_INDUSTRY.get(slug)
        return {code} if code else set()          # mã ngành lạ -> không ai được dùng
    return ENDPOINT_INDUSTRIES.get(endpoint)


def is_allowed(industry, endpoint, view_args=None):
    allowed = allowed_industries(endpoint, view_args)
    return allowed is None or (industry in allowed)


def home_for(industry):
    return INDUSTRY_HOME.get(industry, '/')


def pos_for(industry):
    return INDUSTRY_POS.get(industry, home_for(industry))


def chamcong_url(industry):
    return '/chamcong/' + quote(CHAMCONG_SLUG.get(industry, industry or ''))
