# -*- coding: utf-8 -*-
"""
testtay.py — Australian Market QA/Marketing Screenshot Automation for BitPaw OS.

What this does, in order:
  1. Seeds realistic Australian mock data into MongoDB (AUD-priced Nail services and
     F&B menu items, English/mixed-heritage customer names, busy dining tables) —
     every single document is tagged with {'_qa_seed_tag': SEED_TAG} so cleanup can
     delete EXACTLY what this run created, nothing else, regardless of which shared
     business_id it landed under.
  2. Launches headless Chromium (Playwright) and screenshots:
       - The public Nail and F&B marketing pages (no login needed)
       - The live Nail POS/sell screen, F&B table overview, and F&B kitchen display
         (logged in as Superadmin — same God Mode pattern as test_pos_nails_e2e.py)
  3. ALWAYS deletes every seeded document in a `finally` block, even if the browser
     step throws — mock data never survives past this script's own run.

PREREQUISITES (this script does NOT start these for you):
  - Local Flask dev server running at ADMIN_BASE_URL (default http://127.0.0.1:5001).
    See .claude/launch.json — e.g. `python -m flask --app app run --port 5001`.
  - MONGO_URI configured in .env (same one the Flask app itself uses).
  - Playwright's Chromium browser installed (`playwright install chromium`) — already
    verified present in this environment.

NOTE ON SCOPE: this seeds one shared demo business (business_id = "superadmin-fallback",
the same one the Superadmit God Mode login session already uses) with BOTH Nail and F&B
data together, rather than provisioning two fully separate tenant businesses with their
own logins. That's a deliberate simplification for a quick screenshot script — it means
the /sell screen may show both Nail and F&B items in the same list. If you need fully
isolated per-industry demo tenants, that's a larger follow-up (real business + user
registration per industry), not in scope here.
"""

import os
import sys
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mongo_client import db, next_mongo_id

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================================
# CONFIG
# ============================================================================
BASE_URL = os.getenv("ADMIN_BASE_URL", "http://127.0.0.1:5001")
# Cùng tài khoản/mật khẩu God Mode mà test_pos_nails_e2e.py đã dùng — xem SUPERADMIN_FALLBACK_HASH
# trong .env. Cho phép override qua biến môi trường nếu cần dùng tài khoản khác.
ADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "hodinhsang30052003@gmail.com")
ADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "0794678904Az@")

# Đăng nhập God Mode luôn gán session['business_id'] = 'superadmin-fallback' (xem app.py
# dòng ~648) — seed dữ liệu mock đúng vào business_id này để nó THẬT SỰ hiện ra trên các
# màn hình sản phẩm khi mình đăng nhập bằng chính tài khoản này.
BUSINESS_ID = "superadmin-fallback"

# Tag DUY NHẤT gắn vào MỌI document mock — cleanup xoá theo đúng tag này, KHÔNG xoá theo
# business_id (business_id này có thể đã có dữ liệu thật/dữ liệu test khác từ trước).
SEED_TAG = "testtay_au_market"

SCREENSHOT_DIR = os.path.join("static", "test_screenshots", "au_market_qa")

GREEN, RED, CYAN, YELLOW, RESET, BOLD = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[0m", "\033[1m"


def log_ok(msg):
    print(f"{GREEN}[OK] {msg}{RESET}")


def log_err(msg):
    print(f"{RED}[FAIL] {msg}{RESET}")


def log_info(msg):
    print(f"{CYAN}[INFO] {msg}{RESET}")


# ============================================================================
# STEP 1 — SEED MOCK AUSTRALIAN DATA
# ============================================================================
def _get_original_business_mode():
    """Chỉ ĐỌC giá trị business_mode hiện tại của tài khoản God Mode dùng chung
    ('superadmin-fallback') để cleanup khôi phục lại đúng như cũ sau này — KHÔNG ghi gì ở
    đây. Login qua _superadmin_emergency_login() (app.py) luôn hardcode
    session['business_mode'] = 'none' bất kể system_settings lưu gì, nên việc set mode
    THẬT cho phiên đang chạy phải đi qua đúng luồng UI /setup thật (xem run_screenshots),
    không thể set trước bằng cách ghi thẳng DB như với tài khoản đăng nhập thường."""
    existing = db.system_settings.find_one({'key': f"business_mode_{BUSINESS_ID}"})
    return existing['value'] if existing else None


def _restore_business_mode(original_value):
    key = f"business_mode_{BUSINESS_ID}"
    if original_value is None:
        db.system_settings.delete_one({'key': key})
    else:
        db.system_settings.update_one({'key': key}, {'$set': {'value': original_value}})


def seed_mock_data():
    log_info("Seeding mock Australian market data into MongoDB...")
    now = datetime.now()
    tag = {'_qa_seed_tag': SEED_TAG}

    original_business_mode = _get_original_business_mode()

    nail_products = [
        {'name': 'Gel Manicure', 'price': 45.00},
        {'name': 'Dip Powder Full Set', 'price': 65.00},
        {'name': 'Deluxe Pedicure', 'price': 55.00},
        {'name': 'Acrylic Full Set + Nail Art', 'price': 75.00},
    ]
    fnb_products = [
        {'name': 'Pho Beef Deluxe', 'price': 18.50},
        {'name': 'Banh Mi Combo', 'price': 12.00},
        {'name': 'Vietnamese Iced Coffee', 'price': 5.50},
        {'name': 'Fresh Spring Rolls (4pc)', 'price': 9.00},
    ]

    product_count = 0
    for p in nail_products:
        db.products.insert_one({
            'id': next_mongo_id('products'), 'business_id': BUSINESS_ID, 'name': p['name'],
            'category': 'Nails', 'price': p['price'], 'cost_price': round(p['price'] * 0.35, 2),
            'stock': 999, 'is_active': 1, 'channel_type': 'retail', **tag,
        })
        product_count += 1
    for p in fnb_products:
        db.products.insert_one({
            'id': next_mongo_id('products'), 'business_id': BUSINESS_ID, 'name': p['name'],
            'category': 'F&B', 'price': p['price'], 'cost_price': round(p['price'] * 0.35, 2),
            'stock': 999, 'is_active': 1, 'channel_type': 'retail', **tag,
        })
        product_count += 1

    # Realistic Australian customer names (mixed Anglo/Vietnamese-heritage, matching the
    # actual target demographic — Vietnamese-Australian small business owners' clientele).
    customers = [
        ("Emily Chen", "0412 345 678", "emily.chen@gmail.com", "VIP"),
        ("James Wilson", "0423 456 789", "j.wilson@outlook.com", "Normal"),
        ("Sarah Nguyen", "0434 567 890", "sarah.nguyen@gmail.com", "VIP"),
        ("Michael Tran", "0445 678 901", "michael.tran@gmail.com", "Normal"),
        ("Olivia Pham", "0456 789 012", "olivia.pham@gmail.com", "Normal"),
    ]
    for name, phone, email, tier in customers:
        db.customers.insert_one({
            'id': next_mongo_id('customers'), 'business_id': BUSINESS_ID, 'name': name,
            'phone': phone, 'email': email, 'tier': tier, 'total_spent': 850.00,
            'join_date': (now - timedelta(days=200)).isoformat(), **tag,
        })

    # Nail technicians — Nail mode's key screen is Salon Staff Management (commission
    # split calculator), not a product checkout screen, so this is what actually needs
    # to look "busy" for the Nail screenshot.
    staff_members = [
        ("Kim Tran", "0467 111 222", "Nail Technician", 60),
        ("Anna Le", "0467 222 333", "Nail Technician", 55),
        ("David Vo", "0467 333 444", "Senior Technician", 65),
    ]
    for name, phone, role, commission_rate in staff_members:
        db.staff.insert_one({
            'id': next_mongo_id('staff'), 'business_id': BUSINESS_ID, 'name': name,
            'phone': phone, 'role': role, 'commission_rate': commission_rate,
            'is_active': True, **tag,
        })
        # Salon Staff Management (chamcong_nail.html) reads from db.employees via
        # /api/hr/employees, a SEPARATE HR/attendance collection from db.staff (POS
        # commission) — both need seeding for that screen to show real technicians.
        db.employees.insert_one({
            'id': next_mongo_id('employees'), 'business_id': BUSINESS_ID,
            'ma_nv': phone.replace(' ', ''), 'ho_ten': name, 'linh_vuc': 'Nails',
            'chuc_vu': role, 'luong_cb': 0, 'luong_gio': 25, 'phu_cap': 0,
            'diem_kudo': 0, 'staff_id': None, **tag,
        })

    # Busy recent orders, AUD amounts.
    order_count = 0
    for i in range(6):
        db.orders.insert_one({
            'id': next_mongo_id('orders'), 'business_id': BUSINESS_ID,
            'customer_phone': customers[i % len(customers)][1],
            'total_amount': round(45.0 + (i * 12.5), 2), 'status': 'completed',
            'created_at': (now - timedelta(hours=i)).isoformat(), **tag,
        })
        order_count += 1

    # Busy dining tables for the F&B /pos table overview — mostly "Đang phục vụ" (occupied),
    # a couple "Còn trống" (free), matching the exact status strings app.py already uses.
    table_names = [f'Table {i}' for i in range(1, 9)]
    for idx, tname in enumerate(table_names):
        status = 'Còn trống' if idx in (2, 6) else 'Đang phục vụ'
        db.dining_tables.insert_one({
            'id': next_mongo_id('dining_tables'), 'business_id': BUSINESS_ID, 'name': tname,
            'qr_token': f"qa-{SEED_TAG}-{idx}", 'status': status, **tag,
        })

    log_ok(
        f"Seeded {product_count} products, {len(customers)} customers, "
        f"{len(staff_members)} staff, {order_count} orders, {len(table_names)} dining tables."
    )
    return original_business_mode


# ============================================================================
# CLEANUP — always runs, matches ONLY documents tagged by this script
# ============================================================================
def cleanup_mock_data(original_business_mode):
    log_info("Cleaning up all seeded mock data from MongoDB...")
    tag_filter = {'_qa_seed_tag': SEED_TAG}
    total_deleted = 0
    for coll_name in ('products', 'customers', 'staff', 'employees', 'orders', 'dining_tables'):
        result = db[coll_name].delete_many(tag_filter)
        total_deleted += result.deleted_count
        log_info(f"  - {coll_name}: {result.deleted_count} document(s) removed")
    _restore_business_mode(original_business_mode)
    log_info(f"  - business_mode restored to: {original_business_mode!r}")
    log_ok(f"Cleanup complete — {total_deleted} mock document(s) deleted. MongoDB is clean.")


# ============================================================================
# STEP 2 — SCREENSHOTS
# ============================================================================
def run_screenshots():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        try:
            log_info("Capturing public Nail landing page (/solutions/nail)...")
            page.goto(f"{BASE_URL}/solutions/nail", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_landing_nail_hero.png"))
            log_ok("Saved 01_landing_nail_hero.png")

            log_info("Capturing public F&B landing page (/solutions/fnb)...")
            page.goto(f"{BASE_URL}/solutions/fnb", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_landing_fnb_hero.png"))
            log_ok("Saved 02_landing_fnb_hero.png")

            log_info("Logging in as Superadmin (God Mode) to reach live product screens...")
            page.goto(f"{BASE_URL}/login", timeout=15000)
            page.wait_for_selector("#loginFormElement", timeout=10000)
            page.fill("#loginEmail", ADMIN_EMAIL)
            page.fill("#loginPassword", ADMIN_PASSWORD)
            page.click("#btnLogin")
            # Chờ thoát khỏi /login thật sự (URL đổi) thay vì đoán 1 khoảng thời gian cố định.
            page.wait_for_url(lambda url: "/login" not in url, timeout=10000)
            log_ok(f"Logged in. Current URL: {page.url}")

            # God Mode login always starts business_mode='none' (app.py:
            # _superadmin_emergency_login hardcodes it) regardless of what's stored in
            # system_settings, so /sell would otherwise show the "What business are you
            # running?" first-time setup picker instead of the real POS screen. Drive the
            # actual /setup UI to pick "Nails & Salon" for real, same as a real user would.
            log_info("Selecting 'Nails & Salon' business mode via /setup (required once per session)...")
            page.goto(f"{BASE_URL}/setup", timeout=15000)
            page.click('.mode-card[data-mode="nail"]', timeout=10000)
            page.wait_for_selector('#confirmModal.active', timeout=5000)
            page.click('#confirmYesBtn', timeout=10000)
            # /setup POST redirects to the Nail dashboard on success — wait for navigation
            # to actually complete rather than a fixed sleep.
            page.wait_for_url(lambda url: "/setup" not in url, timeout=10000)
            log_ok(f"Business mode set. Current URL: {page.url}")

            # In Nail mode, /sell resolves to Salon Staff Management (commission-split
            # calculator) rather than a product checkout screen — that IS the Nail
            # industry's key feature in this app (see landing_nail.html's commission
            # calculator section), which is why staff_members were seeded above.
            #
            # NOTE on the previous "No staff in the system yet" issue: this was NOT
            # actually a screenshot-timing race condition — the root cause was that this
            # screen reads from db.employees (a separate HR/attendance collection) rather
            # than db.staff (POS/commission), and the seed step wasn't populating it. That
            # was fixed by seeding db.employees above. The waits below are still added as
            # requested, as genuine defensive hardening against real network/render timing
            # (e.g. slow DB round-trips) — waiting for the actual DOM to be populated
            # instead of a fixed sleep, which is more correct regardless.
            log_info("Capturing Nail Salon Staff Management screen (/sell) with seeded technicians...")
            page.goto(f"{BASE_URL}/sell", timeout=20000)
            page.wait_for_selector("#employeeGrid:not(:empty)", timeout=15000)
            # Cards fade/slide in via a staggered CSS animation (.cascade-item,
            # animation-delay per card) — the selector above only proves the DOM has been
            # populated, not that the animation has finished. A short settle buffer avoids
            # screenshotting mid-transition; this is the one place a small wait_for_timeout
            # is still appropriate ON TOP OF the selector wait, not instead of it.
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_nail_staff_management.png"))
            log_ok("Saved 03_nail_staff_management.png")

            log_info("Capturing F&B busy table overview (/pos)...")
            page.goto(f"{BASE_URL}/pos", timeout=20000)
            # #tableGrid is populated async by loadTables()->renderTables() — wait for the
            # seeded tables to actually be in the DOM, not a fixed sleep.
            page.wait_for_selector("#tableGrid:not(:empty)", timeout=15000)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "04_fnb_table_overview_busy.png"))
            log_ok("Saved 04_fnb_table_overview_busy.png")

            log_info("Capturing F&B kitchen display (/kitchen_display)...")
            page.goto(f"{BASE_URL}/kitchen_display", timeout=20000)
            # NOTE: deliberately NOT using wait_for_load_state("networkidle") here — this
            # page opens a persistent SSE connection (/api/stream/kitchen) for live order
            # updates, so network activity never goes idle and networkidle would always
            # time out. Waiting for the actual container element is the correct approach
            # for any page with a live socket/SSE/polling connection.
            page.wait_for_selector("#ordersContainer", timeout=15000)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_fnb_kitchen_display.png"))
            log_ok("Saved 05_fnb_kitchen_display.png")

            return True
        except Exception as e:
            log_err(f"Screenshot run failed: {str(e)}")
            try:
                page.screenshot(path=os.path.join(SCREENSHOT_DIR, "error_state.png"))
                log_info("Saved error_state.png for debugging.")
            except Exception:
                pass
            return False
        finally:
            browser.close()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    print(f"\n{BOLD}{YELLOW}=== testtay.py — AU Market QA Screenshot Automation ==={RESET}")
    print(f"{CYAN}Target server: {BASE_URL}{RESET}")
    print(f"{CYAN}Screenshots will be saved to: {SCREENSHOT_DIR}{RESET}\n")

    original_business_mode = seed_mock_data()

    success = False
    try:
        success = run_screenshots()
    finally:
        # Luôn dọn dẹp — kể cả khi bước chụp ảnh phía trên lỗi/crash giữa chừng.
        cleanup_mock_data(original_business_mode)

    if success:
        log_ok(f"All done! Screenshots saved to: {SCREENSHOT_DIR}")
        sys.exit(0)
    else:
        log_err("Screenshot run hit errors — mock data was still fully cleaned up. See log above.")
        sys.exit(1)
