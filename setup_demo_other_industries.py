# -*- coding: utf-8 -*-
"""
setup_demo_other_industries.py — Provisions persistent, fully-populated demo tenants for
the 7 industries that don't have one yet: Retail, Spa, Karaoke, Hotel, Production,
Technical, Office. Mirrors setup_demo_nails.py's approach exactly:

  1. Mints a license code mapped to the target industry via the real
     POST /api/superadmin/duc_ma (same endpoint the Super Admin UI calls).
  2. Registers a brand-new tenant via the real POST /register (real registration logic,
     not reimplemented — license validation, business doc creation, industry_code).
  3. Injects realistic data scoped to ONLY that tenant's business_id via pymongo, matching
     each industry's actual schema (verified by reading the real routes beforehand).
  4. Prints login email + password for each account created.

This data is PERSISTENT (matches setup_demo_nails.py's convention) — meant for real
prospective customers to log in and try before buying.

PREREQUISITES: MONGO_URI configured in .env. Runs the Flask app in-process (no dev server
needed to run this script).
"""

import os
import sys
import random
import string
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import app as app_module
from mongo_client import db, next_mongo_id

GREEN, RED, CYAN, YELLOW, RESET, BOLD = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[0m", "\033[1m"


def log_ok(msg): print(f"{GREEN}[OK] {msg}{RESET}")
def log_err(msg): print(f"{RED}[FAIL] {msg}{RESET}")
def log_info(msg): print(f"{CYAN}[INFO] {msg}{RESET}")


ADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "hodinhsang30052003@gmail.com")
ADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "0794678904Az@")
DEMO_PASSWORD = "DemoBitPaw2026!"

_run_suffix = ''.join(random.choices(string.digits, k=6))


import re as _re


def _get_csrf_token(client, page='/login'):
    """CSRFProtect (via the _hybrid_auth_and_csrf before_request hook) rejects any
    unsafe-method request with no token — a plain test_client POST has none, unlike a real
    browser (which gets one from the rendered form or the CSRF-bootstrap script). Fetch a
    real token the same way a browser would: GET a page first, then read either the login
    form's hidden csrf_token input or the bootstrap script's CSRF_TOKEN JS var."""
    r = client.get(page)
    html = r.get_data(as_text=True)
    m = _re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if m:
        return m.group(1)
    m = _re.search(r'CSRF_TOKEN\s*=\s*"([^"]+)"', html)
    return m.group(1) if m else None


# /login and /register are both rate-limited "5 per 15 minutes" per client IP (a real,
# correct anti-abuse control — not weakened or bypassed here). This script logs in as
# Super Admin ONCE and reuses that single authenticated client for all 7 mint_license_code
# calls (instead of logging in 7 times), which keeps /login usage to 1 request. /register
# still needs one real call per tenant, so this script runs in batches of at most 5 with
# the caller waiting out the window between batches — see __main__ below.
_SUPERADMIN_CLIENT = None


def _superadmin_client():
    global _SUPERADMIN_CLIENT
    if _SUPERADMIN_CLIENT is None:
        client = app_module.app.test_client()
        token = _get_csrf_token(client, '/login')
        client.post('/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD, 'csrf_token': token}, follow_redirects=True)
        with client.session_transaction() as sess:
            if 'user_id' not in sess:
                raise RuntimeError("Super Admin login failed.")
        _SUPERADMIN_CLIENT = (client, token)
    return _SUPERADMIN_CLIENT


def mint_license_code(industry_code, license_key):
    client, token = _superadmin_client()
    resp = client.post('/api/superadmin/duc_ma', json={'license_key': license_key, 'nganh_nghe': industry_code},
                        headers={'X-CSRFToken': token} if token else {})
    body = resp.get_json()
    if not body or not body.get('success'):
        raise RuntimeError(f"Failed to mint license code: {body}")
    log_ok(f"Minted license '{license_key}' -> industry '{industry_code}'.")


def register_tenant(email, business_type, business_name, owner_name, license_key, country='VN', currency='VND'):
    client = app_module.app.test_client()
    token = _get_csrf_token(client, '/register')
    resp = client.post('/register', data={
        'email': email, 'password': DEMO_PASSWORD, 'business_type': business_type,
        'business_name': business_name, 'fullname': owner_name, 'license_key': license_key,
        'csrf_token': token,
    }, follow_redirects=False)
    if resp.status_code not in (302, 200):
        raise RuntimeError(f"Registration failed with status {resp.status_code}")
    user = db.users.find_one({'email': email}, {'_id': 0})
    if not user:
        raise RuntimeError("Registration did not create a user record.")
    business_id = user['business_id']
    db.businesses.update_one({'id': business_id}, {'$set': {'country': country, 'currency': currency}})
    log_ok(f"Registered '{business_name}' [{business_type}] — business_id={business_id}")
    return business_id


def _iso_days_ago(days, now, hour=None):
    h = hour if hour is not None else random.randint(8, 20)
    return (now - timedelta(days=days)).replace(hour=h, minute=random.randint(0, 59), second=0, microsecond=0).isoformat()


def _ddmmyyyy_days_ago(days, now):
    """BUG THẬT đã vá (audit chấm công): bangluong.html lọc chamcong theo tháng bằng
    `ngay_cham.split('/')` (parts[1]=tháng, parts[2]=năm) — đúng định dạng 'DD/MM/YYYY' mà
    luồng chấm công thật (app_nhanvien.html: `new Date().toLocaleDateString('en-GB')`) luôn
    ghi. Trước đây hàm này (và setup_demo_nails.py gốc) ghi ngay_cham dạng ISO
    'YYYY-MM-DD' — không có ký tự '/' nào để split, nên MỌI bản ghi chấm công demo bị lọc
    mất hết, bảng lương demo hiện $0 dù có đủ dữ liệu."""
    d = now - timedelta(days=days)
    return d.strftime('%d/%m/%Y')


def inject_employees_and_attendance(business_id, staff_list, nganh_nghe_label, now,
                                     hourly_pay_field='luong_gio', shifts_range=(10, 16),
                                     with_gps=False):
    """staff_list: [(ho_ten, chuc_vu, luong_gio_or_rate)] or [(ho_ten, chuc_vu, luong_gio,
    luong_cb)] — generic across all non-POS-commission industries (Office/Production/
    Technical/Hotel/Karaoke HR side). BUG THẬT đã vá (audit lương): bangluong.html's "Văn
    Phòng" branch tính lương DUY NHẤT từ luong_cb/26*ngày_làm (không có fallback theo giờ
    như các ngành khác) — trước đây hàm này luôn ghi luong_cb=0 cho mọi ngành, khiến nhân
    viên Văn phòng demo luôn hiện lương $0 dù có đủ ngày công. Cho phép truyền luong_cb
    riêng (4-tuple) cho các ngành thật sự dùng lương cứng tháng."""
    records = []
    for staff_tuple in staff_list:
        if len(staff_tuple) == 4:
            ho_ten, chuc_vu, luong_gio, luong_cb = staff_tuple
        else:
            ho_ten, chuc_vu, luong_gio = staff_tuple
            luong_cb = 0
        staff_id_num = next_mongo_id('employees')
        ma_nv = f"NV{staff_id_num:04d}"
        doc = {
            'id': staff_id_num, 'business_id': business_id, 'ma_nv': ma_nv, 'ho_ten': ho_ten,
            'linh_vuc': nganh_nghe_label, 'chuc_vu': chuc_vu, 'luong_cb': luong_cb,
            'luong_gio': luong_gio, 'phu_cap': 0, 'diem_kudo': random.randint(0, 50),
            'staff_id': staff_id_num,
        }
        if with_gps:
            # Random plausible Vietnam coordinates (HCMC area) for the GPS dispatch feature.
            doc['toa_do_lat'] = round(10.75 + random.uniform(-0.08, 0.08), 6)
            doc['toa_do_lng'] = round(106.66 + random.uniform(-0.08, 0.08), 6)
            doc['trang_thai_gps'] = random.choice(['Đang di chuyển', 'Tại hiện trường', 'Rảnh'])
        db.employees.insert_one(doc)
        records.append((ma_nv, ho_ten, luong_gio))
    log_ok(f"Injected {len(records)} employees ({nganh_nghe_label}).")

    chamcong_count = 0
    for ma_nv, ho_ten, luong_gio in records:
        num_shifts = random.randint(*shifts_range)
        for _ in range(num_shifts):
            so_gio = round(random.uniform(4, 9), 1)
            tang_ca = round(random.uniform(0, 2), 1) if random.random() < 0.3 else 0
            days_back = random.randint(0, 21)
            db.chamcong.insert_one({
                'id': next_mongo_id('chamcong'), 'business_id': business_id, 'ma_nv': ma_nv,
                'ngay_cham': _ddmmyyyy_days_ago(days_back, now), 'nganh_nghe': nganh_nghe_label,
                'trang_thai': 'Đã chốt', 'ghi_chu': f"[{nganh_nghe_label.upper()}] Ca làm việc",
                'tien_tua': 0, 'tien_tips': 0, 'phu_cap': 0, 'so_gio': so_gio, 'tang_ca': tang_ca,
            })
            chamcong_count += 1
    log_ok(f"Injected {chamcong_count} attendance/timesheet records (last 3 weeks).")
    return records


def inject_customers(business_id, names, now, currency_symbol_note=""):
    customer_ids = []
    for name in names:
        phone = f"0{random.randint(3,9)}{random.randint(10000000, 99999999)}"
        total_spent = round(random.choice([250000, 480000, 950000, 1500000, 2800000, 5200000]), 0)
        cust_id = next_mongo_id('customers')
        db.customers.insert_one({
            'id': cust_id, 'business_id': business_id, 'name': name, 'phone': phone,
            'email': f"{name.lower().replace(' ', '.')}@example.com",
            'tier': 'VIP' if total_spent > 1500000 else 'Normal', 'loyalty_points': int(total_spent // 1000),
            'total_spent': total_spent, 'join_date': _iso_days_ago(random.randint(30, 300), now),
        })
        customer_ids.append((cust_id, name, phone, total_spent))
    log_ok(f"Injected {len(customer_ids)} customers.")
    return customer_ids


def inject_orders(business_id, customer_ids, product_ids, now, channel_type='retail'):
    order_count = 0
    for cust_id, name, phone, total_spent in customer_ids:
        num_orders = random.randint(1, 4)
        for i in range(num_orders):
            pid, pname, price = random.choice(product_ids)
            order_when = now - timedelta(days=random.randint(1, 90))
            order_id = next_mongo_id('orders')
            db.orders.insert_one({
                'id': order_id, 'business_id': business_id, 'customer_phone': phone,
                'total_amount': price, 'status': 'completed', 'created_at': order_when.isoformat(),
            })
            db.order_items.insert_one({
                'id': next_mongo_id('order_items'), 'order_id': order_id, 'business_id': business_id,
                'product_id': pid, 'customer_phone': phone, 'quantity': 1,
                'total_price': price, 'created_at': order_when.isoformat(),
            })
            order_count += 1
    log_ok(f"Injected {order_count} orders/order-items.")


def inject_products(business_id, product_defs, channel_type='retail'):
    product_ids = []
    for name, category, price, image in product_defs:
        pid = next_mongo_id('products')
        db.products.insert_one({
            'id': pid, 'business_id': business_id, 'name': name, 'category': category,
            'price': price, 'cost_price': round(price * 0.4, 2), 'stock': random.randint(20, 200),
            'is_active': 1, 'channel_type': channel_type, 'image': image,
        })
        product_ids.append((pid, name, price))
    log_ok(f"Injected {len(product_ids)} products/services.")
    return product_ids


RESULTS = []


# ============================================================================
# 1. RETAIL
# ============================================================================
def setup_retail():
    now = datetime.now()
    key = f"RETAILDEMO-{_run_suffix}"
    email = f"demo.retail.{_run_suffix}@bitpawdemo.com"
    mint_license_code('retail', key)
    business_id = register_tenant(email, 'retail', "Sunrise Mart Convenience Store", "David Tran", key)

    products = inject_products(business_id, [
        ("Coca-Cola 330ml (lốc 6)", "Đồ uống", 45000, "https://images.unsplash.com/photo-1554866585-cd94860890b7?w=500&q=80"),
        ("Mì tôm Hảo Hảo (thùng 30)", "Thực phẩm khô", 120000, "https://images.unsplash.com/photo-1612929633738-8fe44f7ec841?w=500&q=80"),
        ("Bánh quy Oreo", "Bánh kẹo", 28000, "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=500&q=80"),
        ("Sữa tươi Vinamilk 1L", "Sữa & Chế phẩm", 34000, "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=500&q=80"),
        ("Nước rửa chén Sunlight 750ml", "Hoá phẩm", 32000, "https://images.unsplash.com/photo-1583947215259-38e31be8751f?w=500&q=80"),
        ("Giấy vệ sinh Bless You (lốc 10)", "Đồ gia dụng", 55000, "https://images.unsplash.com/photo-1584556812952-905ffd0c611a?w=500&q=80"),
        ("Cà phê hoà tan G7 (hộp 20)", "Đồ uống", 65000, "https://images.unsplash.com/photo-1447933601403-0c6688de566e?w=500&q=80"),
        ("Kem đánh răng P/S", "Chăm sóc cá nhân", 22000, "https://images.unsplash.com/photo-1571781926291-c477ebfd024b?w=500&q=80"),
    ], channel_type='retail')

    customers = inject_customers(business_id, [
        "Nguyễn Văn An", "Trần Thị Bích", "Lê Hoàng Nam", "Phạm Thu Hà", "Đỗ Minh Khôi",
        "Vũ Ngọc Lan", "Bùi Quang Huy", "Hoàng Thị Mai", "Ngô Văn Tài", "Đặng Thị Thu",
    ], now)
    inject_orders(business_id, customers, products, now)

    inject_employees_and_attendance(business_id, [
        ("David Tran", "Chủ cửa hàng", 0),
        ("Nguyễn Thị Hương", "Thu ngân", 25000),
        ("Trần Văn Phúc", "Nhân viên bán hàng", 25000),
        ("Lê Thị Kim", "Nhân viên kho", 24000),
    ], "Retail", now)

    # Expenses (retail's explicit "Expense Tracking" module)
    exp_count = 0
    for desc, cat, amt in [
        ("Tiền điện tháng", "Vận hành", 2500000), ("Nhập hàng đồ uống", "Nhập hàng", 8500000),
        ("Tiền thuê mặt bằng", "Vận hành", 15000000), ("Sửa máy lạnh", "Bảo trì", 800000),
        ("Nhập hàng bánh kẹo", "Nhập hàng", 4200000),
    ]:
        db.expenses.insert_one({
            'id': next_mongo_id('expenses'), 'business_id': business_id, 'category': cat,
            'description': desc, 'amount': amt,
            'expense_date': _iso_days_ago(random.randint(1, 40), now)[:10],
        })
        exp_count += 1
    log_ok(f"Injected {exp_count} expense records.")

    RESULTS.append(("Retail", "Sunrise Mart Convenience Store", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 2. SPA
# ============================================================================
def setup_spa():
    now = datetime.now()
    key = f"SPADEMO-{_run_suffix}"
    email = f"demo.spa.{_run_suffix}@bitpawdemo.com"
    mint_license_code('spa', key)
    business_id = register_tenant(email, 'spa', "Serenity Wellness Spa", "Linh Pham", key,
                                   country='AU', currency='AUD')

    products = inject_products(business_id, [
        ("Swedish Full Body Massage (60min)", "Massage", 89.0, "https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=500&q=80"),
        ("Deep Tissue Massage (90min)", "Massage", 129.0, "https://images.unsplash.com/photo-1519823551278-64ac92734fb1?w=500&q=80"),
        ("Hot Stone Therapy", "Massage", 110.0, "https://images.unsplash.com/photo-1600334089648-b0d9d3028eb2?w=500&q=80"),
        ("Signature Facial Treatment", "Facial", 95.0, "https://images.unsplash.com/photo-1616394158624-9b3ea9376f4e?w=500&q=80"),
        ("Anti-Aging Facial", "Facial", 135.0, "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?w=500&q=80"),
        ("Aromatherapy Body Wrap", "Body Treatment", 105.0, "https://images.unsplash.com/photo-1540555700478-4be289fbecef?w=500&q=80"),
        ("Couples Spa Package (90min)", "Packages", 220.0, "https://images.unsplash.com/photo-1596178060810-72660ee8e3c2?w=500&q=80"),
        ("Express Relaxation (30min)", "Massage", 55.0, "https://images.unsplash.com/photo-1591343395082-e120087004b4?w=500&q=80"),
    ], channel_type='spa')
    # BUG THẬT đã vá (audit QA cuối trước khi lên production): trước đây để mặc định
    # channel_type='retail' — cả /spa (POS) LẪN /booking/qr/<spa_id> (đặt lịch công khai cho
    # khách) đều lọc CỨNG channel_type='spa' (xem blueprints/spa_bp.py dòng 59/153), nên toàn
    # bộ 8 dịch vụ demo trước đây KHÔNG hiện được ở cả 2 màn hình cốt lõi nhất của ngành Spa.

    customers = inject_customers(business_id, [
        "Emma Wilson", "James Cooper", "Olivia Bennett", "Liam Hayes", "Charlotte Reid",
        "Noah Parker", "Amelia Foster", "Lucas Grant",
    ], now)
    inject_orders(business_id, customers, products, now)

    staff_records = inject_employees_and_attendance(business_id, [
        ("Sarah Mitchell", "Senior Therapist", 32),
        ("Rachel Nguyen", "Massage Therapist", 28),
        ("Jessica Lee", "Massage Therapist", 28),
        ("Michael Chen", "Therapist", 26),
    ], "Spa", now)

    # `staff` collection (POS/commission structure — mirrors Nails' pattern; spa.html /
    # booking staff picker reads staff by business_id, same as nail's technician list did).
    for ma_nv, ho_ten, luong_gio in staff_records:
        phone = f"04{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}"
        db.staff.insert_one({
            'id': next_mongo_id('staff'), 'business_id': business_id, 'name': ho_ten, 'phone': phone,
            'role': 'Therapist', 'commission_rate': 40, 'is_active': True,
        })
    log_ok("Injected matching `staff` records (booking/commission).")

    # A handful of upcoming/past appointments (online booking module)
    appt_count = 0
    for i in range(8):
        cust_id, name, phone, _ = random.choice(customers)
        pid, pname, price = random.choice(products)
        when = now + timedelta(days=random.randint(-5, 10), hours=random.randint(9, 17))
        db.appointments.insert_one({
            'id': next_mongo_id('appointments'), 'business_id': business_id,
            'customer_name': name, 'customer_phone': phone, 'service_id': pid, 'service_name': pname,
            'staff_id': None, 'appointment_time': when.isoformat(),
            'status': 'confirmed' if when > now else 'completed', 'note': '',
            'created_at': now.isoformat(),
        })
        appt_count += 1
    log_ok(f"Injected {appt_count} appointments (online booking).")

    RESULTS.append(("Spa", "Serenity Wellness Spa", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 3. KARAOKE
# ============================================================================
def setup_karaoke():
    now = datetime.now()
    key = f"KARAOKEDEMO-{_run_suffix}"
    email = f"demo.karaoke.{_run_suffix}@bitpawdemo.com"
    mint_license_code('karaoke', key)
    business_id = register_tenant(email, 'karaoke', "Neon Nights Karaoke & Bida", "Kevin Le", key)

    room_defs = [
        ("Phòng VIP 1", 250000), ("Phòng VIP 2", 250000), ("Phòng Đôi (2-4 người)", 120000),
        ("Phòng Gia Đình (6-8 người)", 180000), ("Phòng Đại Sảnh (10-15 người)", 300000),
        ("Bàn Bida 1", 60000), ("Bàn Bida 2", 60000),
    ]
    for name, price_per_hour in room_defs:
        db.karaoke_rooms.insert_one({
            'id': next_mongo_id('karaoke_rooms'), 'name': name, 'price_per_hour': price_per_hour,
            'status': 'Trống', 'start_time': None, 'business_id': business_id,
        })
    log_ok(f"Injected {len(room_defs)} karaoke rooms/pool tables.")

    products = inject_products(business_id, [
        ("Bia Tiger (lon)", "Đồ uống", 25000, "https://images.unsplash.com/photo-1608270586620-248524c67de9?w=500&q=80"),
        ("Nước ngọt Pepsi", "Đồ uống", 15000, "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500&q=80"),
        ("Trái cây thập cẩm", "Đồ ăn nhẹ", 120000, "https://images.unsplash.com/photo-1610832958506-aa56368176cf?w=500&q=80"),
        ("Snack khô mực", "Đồ ăn nhẹ", 80000, "https://images.unsplash.com/photo-1599490659213-e2b9527bd087?w=500&q=80"),
        ("Combo bia 1 thùng", "Đồ uống", 380000, "https://images.unsplash.com/photo-1613919316861-9e0d0e5b3b9c?w=500&q=80"),
    ], channel_type='retail')

    customers = inject_customers(business_id, ["Nhóm anh Tuấn", "Nhóm chị Linh", "Công ty ABC (team building)"], now)
    inject_orders(business_id, customers, products, now)

    inject_employees_and_attendance(business_id, [
        ("Kevin Le", "Quản lý", 0),
        ("Phan Văn Đức", "Nhân viên phục vụ", 24000),
        ("Trịnh Thị Ngọc", "Thu ngân", 25000),
        ("Nguyễn Hữu Phát", "Nhân viên kỹ thuật âm thanh", 26000),
    ], "Karaoke", now)

    RESULTS.append(("Karaoke", "Neon Nights Karaoke & Bida", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 4. HOTEL — only Attendance/HR is actually implemented (room_management is label-only,
#    no rooms API/collection exists in the codebase yet), so keep scope honest.
# ============================================================================
def setup_hotel():
    now = datetime.now()
    key = f"HOTELDEMO-{_run_suffix}"
    email = f"demo.hotel.{_run_suffix}@bitpawdemo.com"
    mint_license_code('hotel', key)
    business_id = register_tenant(email, 'hotel', "Lakeview Boutique Hotel", "Thanh Nguyen", key)

    inject_employees_and_attendance(business_id, [
        ("Thanh Nguyen", "Quản lý khách sạn", 0),
        ("Lê Thị Hồng", "Lễ tân", 26000),
        ("Trần Văn Sơn", "Lễ tân", 26000),
        ("Nguyễn Thị Lan", "Nhân viên buồng phòng", 23000),
        ("Phạm Văn Hòa", "Nhân viên buồng phòng", 23000),
        ("Đỗ Minh Tuấn", "Bảo vệ", 22000),
    ], "Khách sạn", now)

    RESULTS.append(("Hotel", "Lakeview Boutique Hotel", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 5. PRODUCTION — Attendance/HR only (factory_output is label-only, no separate
#    implementation found in the codebase).
# ============================================================================
def setup_production():
    now = datetime.now()
    key = f"PRODDEMO-{_run_suffix}"
    email = f"demo.production.{_run_suffix}@bitpawdemo.com"
    mint_license_code('production', key)
    business_id = register_tenant(email, 'production', "Phuc Thanh Garment Factory", "Hung Vo", key)

    inject_employees_and_attendance(business_id, [
        ("Hung Vo", "Quản đốc xưởng", 0),
        ("Nguyễn Văn Bình", "Tổ trưởng tổ may", 28000),
        ("Trần Thị Yến", "Công nhân may", 22000),
        ("Lê Văn Cường", "Công nhân may", 22000),
        ("Phạm Thị Hoa", "Công nhân cắt", 22000),
        ("Vũ Văn Đạt", "Công nhân đóng gói", 21000),
        ("Bùi Thị Nga", "Kiểm hàng (QC)", 24000),
    ], "Sản xuất", now, shifts_range=(14, 20))

    RESULTS.append(("Production", "Phuc Thanh Garment Factory", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 6. TECHNICAL — Attendance + GPS dispatch fields on employees.
# ============================================================================
def setup_technical():
    now = datetime.now()
    key = f"TECHDEMO-{_run_suffix}"
    email = f"demo.technical.{_run_suffix}@bitpawdemo.com"
    mint_license_code('technical', key)
    business_id = register_tenant(email, 'technical', "FixIt Pro Technical Services", "Quan Ho", key)

    inject_employees_and_attendance(business_id, [
        ("Quan Ho", "Trưởng nhóm kỹ thuật", 0),
        ("Nguyễn Văn Long", "Kỹ thuật viên điện lạnh", 30000),
        ("Trần Văn Khoa", "Kỹ thuật viên điện nước", 28000),
        ("Lê Hoàng Nam", "Kỹ thuật viên mạng/IT", 32000),
        ("Phạm Văn Toàn", "Kỹ thuật viên bảo trì", 27000),
    ], "Kỹ thuật", now, with_gps=True)

    RESULTS.append(("Technical", "FixIt Pro Technical Services", email, DEMO_PASSWORD, business_id))


# ============================================================================
# 7. OFFICE — Attendance + Payroll (payroll computed from chamcong so_gio, no separate
#    schema — same generic payroll engine every industry uses).
# ============================================================================
def setup_office():
    now = datetime.now()
    key = f"OFFICEDEMO-{_run_suffix}"
    email = f"demo.office.{_run_suffix}@bitpawdemo.com"
    mint_license_code('office', key)
    business_id = register_tenant(email, 'office', "Vietstar Consulting Co., Ltd", "Mai Le", key)

    inject_employees_and_attendance(business_id, [
        # (ho_ten, chuc_vu, luong_gio, luong_cb) — Office's payroll formula (bangluong.html)
        # uses ONLY luong_cb/26*ngày_làm, no hourly fallback, so these need a real monthly
        # base salary (VND/month) to show non-zero payroll — luong_gio kept at 0 since it's
        # unused by this industry's formula.
        ("Mai Le", "Giám đốc", 0, 25000000),
        ("Nguyễn Thị Thanh", "Trưởng phòng Nhân sự", 0, 18000000),
        ("Trần Văn Hải", "Kế toán trưởng", 0, 17000000),
        ("Lê Thị Duyên", "Chuyên viên Marketing", 0, 13000000),
        ("Phạm Văn Nghĩa", "Nhân viên Kinh doanh", 0, 11000000),
        ("Vũ Thị Hằng", "Nhân viên Hành chính", 0, 10000000),
    ], "Văn phòng", now, shifts_range=(18, 22))

    RESULTS.append(("Office", "Vietstar Consulting Co., Ltd", email, DEMO_PASSWORD, business_id))


if __name__ == "__main__":
    print(f"\n{BOLD}{YELLOW}=== Provisioning demo tenants for all remaining industries ==={RESET}\n")
    all_steps = {
        'retail': ("Retail", setup_retail), 'spa': ("Spa", setup_spa),
        'karaoke': ("Karaoke", setup_karaoke), 'hotel': ("Hotel", setup_hotel),
        'production': ("Production", setup_production),
        'technical': ("Technical", setup_technical), 'office': ("Office", setup_office),
    }
    # /register is rate-limited "5 per 15 minutes" per IP (real anti-abuse control, not
    # bypassed) — select which industries to run this invocation via
    # DEMO_INDUSTRIES=karaoke,hotel (comma-separated keys from all_steps above).
    selected = os.environ.get('DEMO_INDUSTRIES', '')
    if selected:
        steps = [all_steps[k.strip()] for k in selected.split(',') if k.strip() in all_steps]
    else:
        steps = list(all_steps.values())
    for name, fn in steps:
        print(f"\n{BOLD}{CYAN}--- {name} ---{RESET}")
        try:
            fn()
        except Exception as e:
            log_err(f"{name} failed: {e}")

    print(f"\n{BOLD}{GREEN}=== SUMMARY — {len(RESULTS)}/{len(steps)} demo tenants created ==={RESET}")
    for industry, biz_name, email, pwd, biz_id in RESULTS:
        print(f"{CYAN}{industry:12s}{RESET} {biz_name:35s} email={BOLD}{email}{RESET} password={BOLD}{pwd}{RESET} biz_id={biz_id}")
