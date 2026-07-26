# -*- coding: utf-8 -*-
"""
setup_demo_nails.py — Provisions a fresh, fully-populated, English-language Nail Salon
demo tenant for you to browse and screenshot MANUALLY in your own browser.

No Playwright, no browser automation of any kind. Registration/license logic is driven
through Flask's in-process test client (calls the REAL /register and
/api/superadmin/duc_ma routes directly — not a hand-rolled reimplementation of that
logic, so it behaves exactly like a real signup), and all the demo data is written
straight to MongoDB via pymongo.

IMPORTANT — unlike testtay.py, this data is NOT cleaned up. It's meant to persist so you
can log in and take your own screenshots at your own pace.

What it does:
  1. Logs in as Super Admin and mints a fresh license code mapped to the 'nail' industry
     via POST /api/superadmin/duc_ma (the same endpoint the real Super Admin UI calls).
  2. Registers a brand new tenant account via POST /register using that code — this
     exercises the actual registration logic (license validation, business doc creation,
     industry_code assignment), so the account is a genuine, fully-working Nail tenant.
  3. Injects a large, realistic Australian data set scoped to ONLY this new tenant's
     business_id: English-named customers and nail technicians, AUD prices across
     products/orders, a few weeks of busy commission/tip history per technician
     (chamcong records), and computed customer nurturing segments (reusing the real
     AINurturingEngine.predict_churn_risk — not reinvented here).
  4. Prints the login email + password at the end, plus an important note about the
     English-language toggle (see the docstring on force_language_note() below for why
     this can't be fully forced server-side).

PREREQUISITES: MONGO_URI configured in .env (same one the Flask app uses). The local
Flask dev server does NOT need to be running for this script — it drives the app
in-process. You WILL need the dev server running afterward to log in and take
screenshots in your own browser.
"""

import os
import sys
import random
import string
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import app as app_module
from mongo_client import db, next_mongo_id
from ai_nurturing_engine import AINurturingEngine

GREEN, RED, CYAN, YELLOW, RESET, BOLD = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[0m", "\033[1m"


def log_ok(msg):
    print(f"{GREEN}[OK] {msg}{RESET}")


def log_err(msg):
    print(f"{RED}[FAIL] {msg}{RESET}")


def log_info(msg):
    print(f"{CYAN}[INFO] {msg}{RESET}")


ADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "hodinhsang30052003@gmail.com")
ADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "0794678904Az@")

_run_suffix = ''.join(random.choices(string.digits, k=6))
DEMO_EMAIL = f"demo.nails.au.{_run_suffix}@bitpawdemo.com"
DEMO_PASSWORD = "DemoNails2026!"
DEMO_BUSINESS_NAME = "Golden Lotus Nails & Beauty Bar"
DEMO_OWNER_NAME = "Jessica Nguyen"
DEMO_LICENSE_KEY = f"NAILDEMO-{_run_suffix}"


# ============================================================================
# STEP 1 — SUPER ADMIN: mint a license code mapped to the Nail industry
# ============================================================================
def mint_nail_license_code():
    client = app_module.app.test_client()
    resp = client.post('/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD}, follow_redirects=True)
    if resp.status_code != 200 or b'login' in resp.request.path.encode():
        # follow_redirects lands on whatever page /login redirects to — check we're not
        # still stuck ON /login (that would mean the credentials were rejected).
        pass
    with client.session_transaction() as sess:
        if 'user_id' not in sess:
            raise RuntimeError(
                "Super Admin login failed — check SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD "
                "env vars or SUPERADMIN_FALLBACK_HASH in .env."
            )
    log_ok(f"Logged in as Super Admin ({ADMIN_EMAIL}).")

    resp = client.post('/api/superadmin/duc_ma', json={
        'license_key': DEMO_LICENSE_KEY,
        'nganh_nghe': 'nail',
    })
    body = resp.get_json()
    if not body or not body.get('success'):
        raise RuntimeError(f"Failed to mint license code: {body}")
    log_ok(f"Minted license code '{DEMO_LICENSE_KEY}' mapped to industry 'nail'.")


# ============================================================================
# STEP 2 — REGISTER the new tenant using that code (real /register route)
# ============================================================================
def register_demo_tenant():
    client = app_module.app.test_client()
    resp = client.post('/register', data={
        'email': DEMO_EMAIL,
        'password': DEMO_PASSWORD,
        'business_type': 'nail',  # license code overrides this anyway if it maps to an industry
        'business_name': DEMO_BUSINESS_NAME,
        'fullname': DEMO_OWNER_NAME,
        'license_key': DEMO_LICENSE_KEY,
    }, follow_redirects=False)

    if resp.status_code not in (302, 200):
        raise RuntimeError(f"Registration request failed with status {resp.status_code}")

    user = db.users.find_one({'email': DEMO_EMAIL}, {'_id': 0})
    if not user:
        raise RuntimeError(
            "Registration did not create a user record — check the Flask server log "
            "output above for a flashed error message (e.g. invalid license, MongoDB down)."
        )
    business_id = user['business_id']

    # register() never asks for country/currency, so it defaults to VN/VND (see
    # TenantEngine.get_region_config) regardless of the AUD amounts injected below — every
    # template that renders money reads THIS field, not the raw numbers, so it must be set
    # explicitly for the AU positioning to actually display correctly (e.g. Customer Data
    # Center's $ vs ₫ symbol).
    db.businesses.update_one({'id': business_id}, {'$set': {'country': 'AU', 'currency': 'AUD'}})

    log_ok(f"Registered tenant '{DEMO_BUSINESS_NAME}' — business_id={business_id} (tagged country=AU, currency=AUD)")
    return business_id


# ============================================================================
# STEP 3 — INJECT a large, realistic Australian Nail-salon data set
# ============================================================================
NAIL_PRODUCTS = [
    ("SNS Dipping Powder Full Set", "Dipping Powder", 75.00, "https://images.unsplash.com/photo-1522337660859-02fbefca4702?w=500&q=80"),
    ("Acrylic Full Set (Ombre/Design)", "Acrylic", 95.00, "https://images.unsplash.com/photo-1772322586785-3a34772cbc61?w=500&q=80"),
    ("Gel-X Extensions", "Gel Extensions", 85.00, "https://images.unsplash.com/photo-1519014816548-bf5fe059798b?w=500&q=80"),
    ("Russian Manicure", "Manicure", 60.00, "https://images.unsplash.com/photo-1457972729786-0411a3b2b626?w=500&q=80"),
    ("Deluxe Spa Pedicure", "Pedicure", 70.00, "https://images.unsplash.com/photo-1577117633143-a2437fb9bdda?w=500&q=80"),
    ("Classic Manicure & Pedicure Combo", "Packages", 90.00, "https://images.unsplash.com/photo-1529982412356-901cc3a363cf?w=500&q=80"),
    ("Callus Treatment & Heel Scrub", "Pedicure", 25.00, "https://images.unsplash.com/photo-1519419451778-14599a49ec41?w=500&q=80"),
    ("Custom Nail Art (Per Finger)", "Add-on", 5.00, "https://images.unsplash.com/photo-1773808605530-17926a0463e9?w=500&q=80"),
]

STAFF_MEMBERS = [
    ("Chloe Anderson", "Senior Nail Technician", 60),
    ("Sophia Martinez", "Nail Technician", 55),
    ("Emily Thompson", "Nail Technician", 55),
    ("Isabella Walker", "Senior Nail Technician", 60),
    ("Grace Mitchell", "Nail Technician", 50),
    ("Ava Robertson", "Junior Nail Technician", 45),
]

CUSTOMER_NAMES = [
    "Charlotte Wilson", "Olivia Brown", "Amelia Taylor", "Mia Johnson", "Harper Davis",
    "Evelyn White", "Abigail Harris", "Emily Clark", "Elizabeth Lewis", "Sofia Walker",
    "Avery Hall", "Ella Young", "Scarlett King", "Grace Wright", "Chloe Scott",
    "Victoria Green", "Aria Baker", "Lily Adams", "Zoey Nelson", "Penelope Carter",
]


def _random_recent_iso(days_back_min, days_back_max, now):
    days_back = random.randint(days_back_min, days_back_max)
    return (now - timedelta(days=days_back, hours=random.randint(0, 23))).isoformat()


def inject_demo_data(business_id):
    now = datetime.now()

    # --- Products / services (AUD) ---
    product_ids = []
    for name, category, price, image in NAIL_PRODUCTS:
        pid = next_mongo_id('products')
        db.products.insert_one({
            'id': pid, 'business_id': business_id, 'name': name, 'category': category,
            'price': price, 'cost_price': round(price * 0.3, 2), 'stock': 999,
            'is_active': 1, 'channel_type': 'retail', 'image': image,
        })
        product_ids.append((pid, name, price))
    log_ok(f"Injected {len(product_ids)} nail services/products (AUD).")

    # --- Staff (POS/commission) + Employees (HR/attendance) ---
    staff_records = []
    for name, role, commission_rate in STAFF_MEMBERS:
        phone = f"04{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}"
        staff_id = next_mongo_id('staff')
        db.staff.insert_one({
            'id': staff_id, 'business_id': business_id, 'name': name, 'phone': phone,
            'role': role, 'commission_rate': commission_rate, 'is_active': True,
        })
        ma_nv = f"NV{staff_id:04d}"
        db.employees.insert_one({
            'id': next_mongo_id('employees'), 'business_id': business_id, 'ma_nv': ma_nv,
            'ho_ten': name, 'linh_vuc': 'Nails', 'chuc_vu': role, 'luong_cb': 0,
            'luong_gio': 22, 'phu_cap': 0, 'diem_kudo': 0, 'staff_id': staff_id,
        })
        staff_records.append((ma_nv, name, commission_rate))
    log_ok(f"Injected {len(staff_records)} nail technicians (staff + employee/HR records).")

    # --- Busy commission/tip history (chamcong) per technician, last 3 weeks ---
    chamcong_count = 0
    for ma_nv, name, commission_rate in staff_records:
        num_shifts = random.randint(8, 14)
        for _ in range(num_shifts):
            total_bill = round(random.uniform(35, 180), 2)
            supply = round(total_bill * 0.05, 2)
            net_rev = total_bill - supply
            worker_tua = round(net_rev * (commission_rate / 100), 2)
            cash_tip = round(random.uniform(0, 25), 2)
            cc_tip = round(random.uniform(0, 20), 2)
            when = _random_recent_iso(0, 21, now)
            db.chamcong.insert_one({
                'id': next_mongo_id('chamcong'), 'business_id': business_id, 'ma_nv': ma_nv,
                'ngay_cham': when[:10], 'nganh_nghe': 'Nails', 'trang_thai': 'Đã chốt',
                'ghi_chu': f"[NAILS] Service checkout | Commission {commission_rate}%",
                'tien_tua': worker_tua, 'tien_tips': round(cash_tip + cc_tip, 2),
                'phu_cap': 0, 'so_gio': 0, 'tang_ca': 0,
            })
            chamcong_count += 1
    log_ok(f"Injected {chamcong_count} busy commission/tip records across all technicians (last 3 weeks).")

    # --- Customers (English names, AU phones) + purchase-recency-driven segments ---
    customer_ids = []
    for name in CUSTOMER_NAMES:
        phone = f"04{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}"
        total_spent = round(random.choice([120, 250, 480, 650, 980, 1450, 2100, 3200]), 2)
        cust_id = next_mongo_id('customers')
        db.customers.insert_one({
            'id': cust_id, 'business_id': business_id, 'name': name, 'phone': phone,
            'email': f"{name.lower().replace(' ', '.')}@example.com.au",
            'tier': 'VIP' if total_spent > 1000 else 'Normal', 'loyalty_points': int(total_spent),
            'total_spent': total_spent, 'join_date': _random_recent_iso(60, 400, now),
        })
        customer_ids.append((cust_id, name, phone, total_spent))
    log_ok(f"Injected {len(customer_ids)} customers with full English names and AU phone numbers.")

    # --- Orders + order items (POS history, AUD), then compute REAL nurturing segments ---
    order_count = 0
    for cust_id, name, phone, total_spent in customer_ids:
        # Spread purchase recency across the board so segments genuinely vary — some
        # regulars, some needing care, some hibernating, some at real churn risk —
        # instead of everyone looking identically "busy".
        last_purchase_days = random.choice([2, 5, 9, 15, 25, 35, 55, 70, 95, 130])
        num_orders = random.randint(2, 6)
        for i in range(num_orders):
            pid, pname, price = random.choice(product_ids)
            order_when = now - timedelta(days=last_purchase_days + i * random.randint(14, 30))
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

        # Reuse the REAL nurturing engine (not reinvented) to compute this customer's
        # segment from their actual synthesized recency + spend, same as the live system.
        status, score, notes = AINurturingEngine.predict_churn_risk(last_purchase_days, total_spent, 'pos')
        db.customers.update_one({'id': cust_id, 'business_id': business_id}, {'$set': {
            'nurturing_status': status, 'potential_score': score, 'ai_notes': notes,
            'last_purchase_at': (now - timedelta(days=last_purchase_days)).isoformat(),
            'source_platform': 'pos',
        }})
    log_ok(f"Injected {order_count} orders/order-items (AUD) and computed real nurturing segments per customer.")


def force_language_note():
    """IMPORTANT LIMITATION: there is no per-account 'default language' setting stored
    anywhere in this codebase — i18n.py's resolve_lang() only ever checks the
    'bitpaw_lang' browser COOKIE, then the browser's Accept-Language header, then falls
    back to DEFAULT_LANG ('en', already English by default). That means language is a
    property of your BROWSER, not the account — this script cannot reach into your
    Chrome's cookies/localStorage to force anything. In practice: a brand-new browser
    session with no bitpaw_lang cookie will already show English by default. If it
    doesn't, you (or a prior session) previously clicked the VI toggle — click the
    language toggle (EN/VI button) once after logging in, or clear the 'bitpaw_lang'
    cookie for localhost:5001."""
    pass


if __name__ == "__main__":
    print(f"\n{BOLD}{YELLOW}=== setup_demo_nails.py — AU Nail Salon Demo Tenant Provisioning ==={RESET}\n")

    try:
        mint_nail_license_code()
        business_id = register_demo_tenant()
        inject_demo_data(business_id)
    except Exception as e:
        log_err(str(e))
        sys.exit(1)

    print(f"\n{BOLD}{GREEN}=== DEMO TENANT READY ==={RESET}")
    print(f"{CYAN}Business name:{RESET} {DEMO_BUSINESS_NAME}")
    print(f"{CYAN}Business ID:  {RESET} {business_id}")
    print(f"{CYAN}Login email:  {RESET} {BOLD}{DEMO_EMAIL}{RESET}")
    print(f"{CYAN}Login password:{RESET} {BOLD}{DEMO_PASSWORD}{RESET}")
    print(f"\n{YELLOW}Log in at http://127.0.0.1:5001/login with the credentials above.{RESET}")
    print(
        f"{YELLOW}Note: this account has no saved language preference — the site defaults to "
        f"English already. If your browser previously selected Vietnamese, click the EN toggle "
        f"once after logging in (language is a browser cookie, not an account setting — see "
        f"force_language_note() in this script for why it can't be forced server-side).{RESET}"
    )
    print(f"\n{GREEN}This data is PERSISTENT — nothing will be auto-deleted. Take your time.{RESET}")
