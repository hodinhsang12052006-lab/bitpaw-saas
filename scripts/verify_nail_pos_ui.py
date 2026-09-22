# -*- coding: utf-8 -*-
"""
verify_nail_pos_ui.py — Playwright E2E verification & screenshot capture
for the overhauled Galaxy / Zota POS & Interactive Attendance Calendar modules.
"""

import os
import sys
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_client import db, next_mongo_id

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = os.getenv("ADMIN_BASE_URL", "http://127.0.0.1:5001")
DEMO_EMAIL = os.getenv("DEMO_NAIL_EMAIL", "demo.nails.au.006758@bitpawdemo.com")
DEMO_PASSWORD = os.getenv("DEMO_NAIL_PASSWORD", "DemoNails2026!")
BUSINESS_ID = "000b2c16-ab4e-42bd-944a-29c925cad09b"

SCREENSHOT_DIR = os.path.join("static", "test_screenshots", "nail_revamp")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def ensure_seed_data():
    """Ensure rich demo data exists for nails so screenshots are vivid and realistic."""
    print("Checking / seeding demo nail data...")
    now = datetime.now()

    # Ensure business mode is nail
    db.businesses.update_one({'id': BUSINESS_ID}, {'$set': {'mode': 'nail', 'name': 'Golden Lotus Nails & Beauty Bar'}})

    # 1. Ensure nail services exist
    existing_prods = db.products.count_documents({'business_id': BUSINESS_ID, 'category': {'$in': ['Acrylic', 'Pedicure', 'Gel', 'Design', 'Waxing', 'Packages']}})
    if existing_prods < 6:
        services_data = [
            ("Fullset Acrylic + Gel Color", "Acrylic", 75.0, "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=500&q=80"),
            ("Ombre Powder Full Set", "Acrylic", 85.0, "https://images.unsplash.com/photo-1632345031435-8797b2d58045?w=500&q=80"),
            ("Signature Spa Pedicure", "Pedicure", 65.0, "https://images.unsplash.com/photo-1519415510236-8a59ddadf584?w=500&q=80"),
            ("Deluxe Volcano Spa Pedi", "Pedicure", 80.0, "https://images.unsplash.com/photo-1522337660859-02fbefca4702?w=500&q=80"),
            ("Gel Manicure & Cuticle Care", "Gel", 45.0, "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=500&q=80"),
            ("Shellac Hand Treatment", "Gel", 50.0, "https://images.unsplash.com/photo-1519014816548-bf5fe059798b?w=500&q=80"),
            ("Custom 3D Chrome Nail Art", "Design", 25.0, "https://images.unsplash.com/photo-1607779097040-26e80aa78e66?w=500&q=80"),
            ("Diamond Gem Encapsulation", "Design", 30.0, "https://images.unsplash.com/photo-1529982412356-901cc3a363cf?w=500&q=80"),
            ("Eyebrow & Lip Waxing", "Waxing", 28.0, "https://images.unsplash.com/photo-1540555700478-4be289fbecef?w=500&q=80"),
            ("Mani & Pedi Royalty Combo", "Packages", 115.0, "https://images.unsplash.com/photo-1596462502278-27bfdc403348?w=500&q=80"),
        ]
        for name, cat, price, img in services_data:
            db.products.update_one(
                {'business_id': BUSINESS_ID, 'name': name},
                {'$set': {
                    'id': next_mongo_id('products'),
                    'business_id': BUSINESS_ID,
                    'name': name,
                    'category': cat,
                    'price': price,
                    'cost_price': round(price * 0.3, 2),
                    'stock': 999,
                    'is_active': 1,
                    'channel_type': 'retail',
                    'image': img
                }},
                upsert=True
            )
        print("  -> Seeded nail services.")

    # 2. Ensure nail technicians exist
    techs = [
        ("NV001", "Jessica Nguyen", "Senior Nail Technician", 60),
        ("NV002", "Chloe Anderson", "Nail Artist", 55),
        ("NV003", "Emily Thompson", "Pedicurist Specialist", 55),
        ("NV004", "Sophia Martinez", "Nail Technician", 50),
        ("NV005", "David Vo", "Senior Nail Master", 65),
    ]
    for mnv, name, role, comm in techs:
        db.employees.update_one(
            {'business_id': BUSINESS_ID, 'ma_nv': mnv},
            {'$set': {
                'id': next_mongo_id('employees'),
                'business_id': BUSINESS_ID,
                'ma_nv': mnv,
                'ho_ten': name,
                'linh_vuc': 'Nails',
                'chuc_vu': role,
                'luong_cb': 0,
                'luong_gio': 25,
                'phu_cap': 0,
                'diem_kudo': 100
            }},
            upsert=True
        )
    print("  -> Seeded nail technicians.")

    # 3. Seed calendar chamcong turns for current month so the calendar grid is rich
    # Check if chamcong already has data for this month
    existing_chamcong = db.chamcong.count_documents({'business_id': BUSINESS_ID, 'nganh_nghe': 'Nails'})
    if existing_chamcong < 15:
        chamcong_batch = []
        for day_offset in range(0, 8):
            d = now - timedelta(days=day_offset)
            dmy = d.strftime('%d/%m/%Y')
            for idx, (mnv, name, role, comm) in enumerate(techs):
                st = 'Có mặt' if (idx + day_offset) % 4 != 0 else 'Nghỉ phép'
                chamcong_batch.append({
                    'id': next_mongo_id('chamcong'),
                    'business_id': BUSINESS_ID,
                    'ma_nv': mnv,
                    'ngay_cham': dmy,
                    'nganh_nghe': 'Nails',
                    'trang_thai': st,
                    'ghi_chu': f"Ca làm chuẩn {dmy}",
                    'gio_den': '09:00',
                    'gio_ve': '18:00',
                    'so_gio': 8.5,
                    'tien_tua': 0,
                    'tien_tips': 0,
                    'phu_cap': 0,
                    'tang_ca': 0
                })
                if st == 'Có mặt':
                    for t_idx in range(1, 3):
                        tua_val = round(45.0 + t_idx * 15, 2)
                        tip_val = round(10.0 + t_idx * 5, 2)
                        chamcong_batch.append({
                            'id': next_mongo_id('chamcong'),
                            'business_id': BUSINESS_ID,
                            'ma_nv': mnv,
                            'ngay_cham': dmy,
                            'nganh_nghe': 'Nails',
                            'trang_thai': 'Đã chốt',
                            'ghi_chu': f"Turn #{t_idx} - Fullset & Pedicure",
                            'tien_tua': tua_val,
                            'tien_tips': tip_val,
                            'phu_cap': 0,
                            'so_gio': 0,
                            'tang_ca': 0
                        })
        if chamcong_batch:
            db.chamcong.insert_many(chamcong_batch)
            print(f"  -> Bulk inserted {len(chamcong_batch)} chamcong records.")
    else:
        print(f"  -> Chamcong already has {existing_chamcong} records.")


def main():
    ensure_seed_data()

    print(f"\n=== LAUNCHING PLAYWRIGHT VERIFICATION FOR NAIL REVAMP ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Step 1: Login
        print("1. Logging into Nail Salon Admin account...")
        page.goto(f"{BASE_URL}/login", timeout=20000)
        page.wait_for_selector("#loginFormElement", timeout=10000)
        page.fill("#loginEmail", DEMO_EMAIL)
        page.fill("#loginPassword", DEMO_PASSWORD)
        try:
            with page.expect_navigation(timeout=10000):
                page.click("#btnLogin")
        except Exception:
            page.wait_for_timeout(2000)
        print(f"  -> Logged in. Current URL: {page.url}")

        # Step 3: Open /sell (POS Nail Split-Screen)
        print("3. Navigating to /sell (Galaxy/Zota POS Nail Screen)...")
        page.goto(f"{BASE_URL}/sell", timeout=20000)
        page.wait_for_selector(".pos-split-layout", timeout=10000)
        page.wait_for_selector(".svc-card", timeout=10000)
        page.wait_for_timeout(1000)

        # 3.1: Capture initial Split Screen
        shot1 = os.path.join(SCREENSHOT_DIR, "01_pos_split_screen_initial.png")
        page.screenshot(path=shot1)
        print(f"  -> Captured: {shot1}")

        # 3.2: Click on 2 services to add to cart
        print("  -> Adding services to ticket cart...")
        cards = page.locator(".svc-card")
        if cards.count() > 0:
            cards.nth(0).click()
            page.wait_for_timeout(300)
        if cards.count() > 1:
            cards.nth(1).click()
            page.wait_for_timeout(300)
        if cards.count() > 2:
            cards.nth(2).click()
            page.wait_for_timeout(300)

        # Select tip preset 18%
        page.locator("button.tip-chip:has-text('18%')").click()
        page.wait_for_timeout(500)

        shot2 = os.path.join(SCREENSHOT_DIR, "02_pos_ticket_active_cart.png")
        page.screenshot(path=shot2)
        print(f"  -> Captured: {shot2}")

        # 3.3: Open Turn Sheet Modal
        print("  -> Opening Turn Tracking Sheet...")
        page.locator("button[onclick='openTurnQueueModal()']").click()
        page.wait_for_selector("#turnQueueModal.active", timeout=5000)
        page.wait_for_timeout(600)
        shot3 = os.path.join(SCREENSHOT_DIR, "03_turn_tracking_sheet_modal.png")
        page.screenshot(path=shot3)
        print(f"  -> Captured: {shot3}")
        page.locator("#turnQueueModal button[onclick='closeTurnQueueModal()']").first.click()
        page.wait_for_timeout(400)

        # 3.4: Open Daily Closeout Modal
        print("  -> Opening Daily Closeout Modal...")
        page.locator("button[onclick='openDailyCloseoutModal()']").click()
        page.wait_for_selector("#dailyCloseoutModal.active", timeout=5000)
        page.wait_for_timeout(600)
        shot4 = os.path.join(SCREENSHOT_DIR, "04_daily_closeout_modal.png")
        page.screenshot(path=shot4)
        print(f"  -> Captured: {shot4}")
        page.locator("#dailyCloseoutModal button[onclick='closeDailyCloseoutModal()']").first.click()
        page.wait_for_timeout(400)

        # 3.5: Open Payment Modal
        print("  -> Opening Payment Modal...")
        page.locator("#btnPayNow").click()
        page.wait_for_selector("#paymentModal.active", timeout=5000)
        page.wait_for_timeout(600)
        shot5 = os.path.join(SCREENSHOT_DIR, "05_pos_payment_modal.png")
        page.screenshot(path=shot5)
        print(f"  -> Captured: {shot5}")
        page.locator("#paymentModal button[onclick='closePaymentModal()']").first.click()
        page.wait_for_timeout(400)

        # Step 4: Open /chamcong_nail (Interactive Attendance Calendar)
        print("4. Navigating to /chamcong_nail (Interactive Attendance Calendar Grid)...")
        page.goto(f"{BASE_URL}/chamcong_nail", timeout=20000)
        page.wait_for_selector("#calendarGridCells", timeout=10000)
        page.wait_for_selector(".cal-cell:not(.empty)", timeout=10000)
        page.wait_for_timeout(1000)

        shot6 = os.path.join(SCREENSHOT_DIR, "06_attendance_calendar_grid.png")
        page.screenshot(path=shot6)
        print(f"  -> Captured: {shot6}")

        # 4.1: Click on a day cell with present techs to open day detail
        cells = page.locator(".cal-cell:not(.empty)")
        if cells.count() > 0:
            cells.nth(min(cells.count() - 1, 10)).click()
            page.wait_for_selector("#calDayDetailModal.active", timeout=5000)
            page.wait_for_timeout(800)
            shot7 = os.path.join(SCREENSHOT_DIR, "07_attendance_day_detail_modal.png")
            page.screenshot(path=shot7)
            print(f"  -> Captured: {shot7}")
            page.locator("#calDayDetailModal button[onclick='closeDayDetailModal()']").first.click()
            page.wait_for_timeout(400)

        # 4.2: Switch to "Đối Soát Thợ" view
        print("  -> Switching to 'Đối Soát Thợ' (Audit view)...")
        page.locator("button.nav-view-tab[data-view='audit']").click()
        page.wait_for_selector("#view_audit:not(.hidden)", timeout=5000)
        page.wait_for_timeout(800)
        shot8 = os.path.join(SCREENSHOT_DIR, "08_technician_audit_portal.png")
        page.screenshot(path=shot8)
        print(f"  -> Captured: {shot8}")

        # 4.3: Switch to "Tính Tua / Ca" view
        print("  -> Switching to 'Tính Tua / Ca' (Entry form)...")
        page.locator("button.nav-view-tab[data-view='entry']").click()
        page.wait_for_selector("#view_entry:not(.hidden)", timeout=5000)
        page.wait_for_timeout(800)
        shot9 = os.path.join(SCREENSHOT_DIR, "09_tua_entry_form.png")
        page.screenshot(path=shot9)
        print(f"  -> Captured: {shot9}")

        browser.close()
        print("\nAll screenshots captured successfully in:", SCREENSHOT_DIR)

if __name__ == '__main__':
    main()
