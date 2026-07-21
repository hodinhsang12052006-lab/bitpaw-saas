#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E Core Backend Test — BitPaw OS
==================================
Kich ban: God Mode (Super Admin) -> Tao Merchant -> Setup san pham -> 2 don
hang that (1 Cash, 1 Card co chia hoa hong Chu/Tho 6-4 + Tip 100% cho tho)
-> Dashboard tong hop doanh thu Cash/Card + so khach hom nay -> Nhan vien tra
cuu thu nhap trong ngay -> Xac nhan CRM luu nguyen ven du lieu khach hang cho
CA HAI don.

KHONG dung Playwright/trinh duyet — toan bo test goi thang vao Flask
`test_client()` (cung tang HTTP/route/controller that) hoac thang vao MongoDB
qua `db` (mongo_client.py) khi ban than luong nghiep vu khong co route HTTP
tuong ung (he thong nay khong co tai khoan dang nhap rieng cho khach hang
cuoi — xem log [INFO] o Buoc 3).

An toan du lieu production: script noi thang vao MONGO_URI that (Atlas) khai
bao trong .env — moi du lieu test deu dung 1 bo dinh danh CO DINH, DE NHAN
BIET va duoc XOA SACH ca truoc lan chay lan sau khi chay xong (thanh cong lan
that bai deu don dep) de khong rac du lieu that.

Chay:  python e2e_core_test.py
"""

import sys
import os
import uuid
import time
from datetime import datetime

# Windows console: bat buoc UTF-8 truoc khi in bat ky dong log tieng Viet/emoji nao,
# neu khong se UnicodeEncodeError ngay dong print() dau tien tren cp1252.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# HANG SO DINH DANH DU LIEU TEST (co dinh qua nhieu lan chay -> cleanup don gian,
# idempotent — chay lai bao nhieu lan cung khong tao rac chong chat).
# ============================================================================
TEST_EMAIL = "e2e_test_merchant@bitpaw-e2e.local"
TEST_PASSWORD = "E2eTest!2026"
TEST_LICENSE_KEY = "E2E-TEST-LICENSE-0001"
TEST_BUSINESS_NAME = "E2E Test Coffee Shop"
TEST_INDUSTRY = "retail"

CUSTOMER_CASH_PHONE = "0909000111"
CUSTOMER_CARD_PHONE = "0909000222"
STAFF_NAME = "E2E Test Technician"
STAFF_PHONE = "0909000333"

PRODUCT_A = {"name": "E2E Test Latte", "price": 12.99, "stock": 100,
             "image_url": "https://picsum.photos/seed/e2e-latte/400/300"}
PRODUCT_B = {"name": "E2E Test Croissant", "price": 7.50, "stock": 100,
             "image_url": "https://picsum.photos/seed/e2e-croissant/400/300"}

# Don CASH: 1 san pham don gian, khong gan thu -> khong chia hoa hong.
CASH_ORDER_QTY_A = 1
CASH_ORDER_TIP = 2.00

# Don CARD: 2 san pham + gan staff_id -> BAT BUOC test chia hoa hong 60/40 (mac dinh
# he thong, KHONG cau hinh rieng gi ca de xac nhan dung fallback mac dinh).
CARD_ORDER_QTY_A, CARD_ORDER_QTY_B = 1, 2
CARD_ORDER_TIP = 5.00
EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT = 40  # Chu 60% - Tho 40%

_step_no = 0


def step(title):
    global _step_no
    _step_no += 1
    print(f"\n{'=' * 78}\nBUOC {_step_no}: {title}\n{'=' * 78}")


def check(label, condition, detail=""):
    """In ket qua 1 assertion va NEM RuntimeError ngay neu fail — dung de dung
    script tai diem loi dau tien thay vi chay tiep tren du lieu da sai."""
    mark = "[OK]" if condition else "[FAIL]"
    print(f"  {mark} {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        raise RuntimeError(f"ASSERTION FAILED: {label} ({detail})")
    return condition


def mock_payment_gateway_charge(amount_usd, method="card", card_last4="4242"):
    """Mock 100% local — khong goi network that. Mo phong 1 cong thanh toan
    (quet the HOAC nhan tien mat) tra ve SUCCESS/FAILED kem transaction_id."""
    if method == "cash":
        print(f"  -> [MOCK GATEWAY] Ghi nhan thu Tien Mat ${amount_usd:.2f} tai quay ...")
    else:
        print(f"  -> [MOCK GATEWAY] Charging card **** **** **** {card_last4} "
              f"for ${amount_usd:.2f} ...")
    time.sleep(0.2)
    txn_id = f"MOCK-TXN-{uuid.uuid4().hex[:12].upper()}"
    return {"status": "SUCCESS", "transaction_id": txn_id, "amount": round(amount_usd, 2)}


def cleanup_test_data(db, phase):
    """Xoa sach moi du lieu test (theo email/license_key/phone co dinh) khoi
    MongoDB production — chay ca TRUOC (phong truong hop lan chay truoc bi
    crash giua chung de lai rac) LAN SAU khi test xong (thanh cong hay that
    bai deu don dep, khong de lai du lieu gia trong DB that)."""
    if db is None:
        return
    print(f"  [cleanup:{phase}] Dang don dep du lieu test cu (neu co)...")
    existing_user = db.users.find_one({"email": TEST_EMAIL}, {"id": 1, "business_id": 1, "_id": 0})
    if existing_user:
        old_business_id = existing_user.get("business_id") or existing_user["id"]
        db.businesses.delete_many({"id": old_business_id})
        db.products.delete_many({"business_id": old_business_id})
        db.orders.delete_many({"business_id": old_business_id})
        db.order_items.delete_many({"business_id": old_business_id})
        db.staff.delete_many({"business_id": old_business_id})
        db.customers.delete_many({"business_id": old_business_id,
                                   "phone": {"$in": [CUSTOMER_CASH_PHONE, CUSTOMER_CARD_PHONE]}})
        db.system_settings.delete_many({"key": f"business_mode_{old_business_id}"})
        db.system_settings.delete_many({"key": "commission_rate", "business_id": old_business_id})
        db.business_memberships.delete_many({"owner_user_id": old_business_id})
        db.user_logs.delete_many({"business_id": old_business_id})
        db.users.delete_many({"email": TEST_EMAIL})
        print(f"  [cleanup:{phase}] Da xoa merchant/orders/products/staff cu (business_id={old_business_id}).")
    else:
        print(f"  [cleanup:{phase}] Khong co du lieu merchant test cu can xoa.")
    db.license_codes.delete_many({"license_key": TEST_LICENSE_KEY})


def main():
    print("#" * 78)
    print("# E2E CORE BACKEND TEST — BitPaw OS (Flask test_client, khong Playwright)")
    print(f"# Bat dau luc: {datetime.now().isoformat(timespec='seconds')}")
    print("#" * 78)

    import app as flask_app
    from mongo_client import db

    if db is None:
        print("\n[FAIL] MongoDB chua ket noi (kiem tra MONGO_URI trong .env). Dung test.")
        sys.exit(1)

    flask_app.app.testing = True
    cleanup_test_data(db, "before")

    try:
        # ====================================================================
        step("Dot nhap Super Admin (God Mode bypass) & Khoi tao Merchant")
        # ====================================================================
        admin_client = flask_app.app.test_client()
        with admin_client.session_transaction() as sess:
            sess["user_id"] = "superadmin-fallback"
            sess["business_id"] = "superadmin-fallback"
            sess["user_email"] = flask_app.SUPERADMIN_ROOT_EMAIL
            sess["role"] = "super_admin"
            sess["business_mode"] = "none"
        print(f"  -> Da bypass auth voi quyen Super Admin ({flask_app.SUPERADMIN_ROOT_EMAIL}).")

        resp = admin_client.get("/super_admin")
        check("GET /super_admin (God Mode) tra ve 200", resp.status_code == 200, f"status={resp.status_code}")

        resp = admin_client.post("/api/superadmin/duc_ma", json={
            "license_key": TEST_LICENSE_KEY, "nganh_nghe": TEST_INDUSTRY
        })
        rj = resp.get_json()
        check("POST /api/superadmin/duc_ma tao license key thanh cong",
              resp.status_code == 200 and rj and rj.get("success") is True, str(rj))

        merchant_client = flask_app.app.test_client()
        resp = merchant_client.post("/register", data={
            "email": TEST_EMAIL, "password": TEST_PASSWORD, "business_type": TEST_INDUSTRY,
            "business_name": TEST_BUSINESS_NAME, "fullname": "E2E Tester", "license_key": TEST_LICENSE_KEY,
        }, follow_redirects=False)
        check("POST /register redirect ve /login sau khi tao Merchant thanh cong",
              resp.status_code in (301, 302), f"status={resp.status_code}")

        user_doc = db.users.find_one({"email": TEST_EMAIL})
        check("Merchant duoc ghi vao collection 'users'", user_doc is not None, str(user_doc))
        business_id = user_doc["business_id"]
        business_doc = db.businesses.find_one({"id": business_id})
        check("Ho so 'businesses' duoc tao dung ten cua hang",
              business_doc is not None and business_doc.get("name") == TEST_BUSINESS_NAME, str(business_doc))

        resp = merchant_client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
                                     follow_redirects=False)
        check("POST /login (Merchant) thanh cong -> redirect", resp.status_code in (301, 302),
              f"status={resp.status_code}")

        resp = merchant_client.post("/setup", data={"mode": TEST_INDUSTRY}, follow_redirects=False)
        check("POST /setup luu nganh nghe thanh cong", resp.status_code in (301, 302), f"status={resp.status_code}")

        print(f"\n  ==> Merchant '{TEST_BUSINESS_NAME}' (business_id={business_id}) da san sang.")

        # ====================================================================
        step("Setup Menu/Dich vu (2 san pham) + Tao 1 Nhan vien (Tho)")
        # ====================================================================
        created_products = []
        for prod in (PRODUCT_A, PRODUCT_B):
            resp = merchant_client.post("/add", data={
                "name": prod["name"], "category": "test-category",
                "stock": str(prod["stock"]), "price": str(prod["price"]),
            }, follow_redirects=False)
            check(f"POST /add tao san pham '{prod['name']}' thanh cong",
                  resp.status_code in (301, 302), f"status={resp.status_code}")
            doc = db.products.find_one({"business_id": business_id, "name": prod["name"]})
            check(f"San pham '{prod['name']}' co trong DB voi gia dung",
                  doc is not None and abs(doc["price"] - prod["price"]) < 0.001, str(doc))
            # Route /add hien tai chi nhan upload file that (request.files), khong nhan link
            # anh dang URL — gan Link hinh anh ao truc tiep vao DB (goi thang Controller/DB,
            # duoc phep theo yeu cau de bai) de mo phong dung field "image" nhu khi merchant
            # dan link ngoai vao.
            db.products.update_one({"id": doc["id"]}, {"$set": {"image": prod["image_url"]}})
            created_products.append(db.products.find_one({"id": doc["id"]}))
        product_a_doc, product_b_doc = created_products

        # Tao 1 nhan vien (tho) — CO Y KHONG nhap commission_rate rieng, de xac nhan he thong
        # tu fallback ve muc mac dinh toan cua hang (DEFAULT_STAFF_COMMISSION_PERCENT = 40%).
        resp = merchant_client.post("/add_staff", json={
            "name": STAFF_NAME, "phone": STAFF_PHONE, "role": "technician",
        })
        rj = resp.get_json()
        check("POST /add_staff tao nhan vien thanh cong", resp.status_code == 200 and rj.get("success") is True, str(rj))
        staff_doc = db.staff.find_one({"business_id": business_id, "phone": STAFF_PHONE})
        check("Nhan vien co trong DB, commission_rate=None (chua cau hinh rieng)",
              staff_doc is not None and staff_doc.get("commission_rate") is None, str(staff_doc))
        staff_id = staff_doc["id"]

        resp = merchant_client.get("/api/settings/commission_rate")
        rj = resp.get_json()
        check(f"Ty le hoa hong MAC DINH cua ca cua hang = {EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT}% (Tho)",
              rj.get("data", {}).get("staff_commission_rate") == EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT, str(rj))

        # ====================================================================
        step("Kiem tra CRM RONG truoc khi ban hang (dieu kien dau, chua co du lieu)")
        # ====================================================================
        for phone in (CUSTOMER_CASH_PHONE, CUSTOMER_CARD_PHONE):
            existing = db.customers.find_one({"business_id": business_id, "phone": phone})
            check(f"Khach {phone} CHUA ton tai trong CRM truoc khi mua hang", existing is None, str(existing))

        # ====================================================================
        step("DON HANG #1 — Thanh toan TIEN MAT (Cash), khong gan thu")
        # ====================================================================
        cash_subtotal = round(PRODUCT_A["price"] * CASH_ORDER_QTY_A, 2)
        cash_total = round(cash_subtotal + CASH_ORDER_TIP, 2)
        print(f"  -> Gio hang Cash: {CASH_ORDER_QTY_A} x {PRODUCT_A['name']} = ${cash_subtotal:.2f}, "
              f"Tip ${CASH_ORDER_TIP:.2f} -> Total ky vong ${cash_total:.2f}")

        gw = mock_payment_gateway_charge(cash_total, method="cash")
        check("Mock Gateway (Cash) tra ve SUCCESS", gw["status"] == "SUCCESS", str(gw))

        resp = merchant_client.post("/api/sales/checkout", json={
            "items": [{"product_id": product_a_doc["id"], "quantity": CASH_ORDER_QTY_A}],
            "tip_amount": CASH_ORDER_TIP,
            "payment_method": "cash",
            "status": "PAID",
            "customer_phone": CUSTOMER_CASH_PHONE,
            "currency": "USD",
        })
        rj = resp.get_json()
        check("POST /api/sales/checkout (Cash) thanh cong", resp.status_code == 200 and rj.get("success") is True, str(rj))
        check("Total don Cash dung", abs(rj["total_amount"] - cash_total) < 0.01, str(rj))
        check("payment_bucket tra ve dung 'cash'", rj.get("payment_bucket") == "cash", str(rj))
        check("Don Cash KHONG co field hoa hong (khong gan staff_id)", "staff_commission" not in rj, str(rj))
        cash_order_id = rj["order_id"]

        cash_order_doc = db.orders.find_one({"id": cash_order_id})
        check("Don hang Cash luu DB dung payment_method='cash' + payment_bucket='cash'",
              cash_order_doc.get("payment_method") == "cash" and cash_order_doc.get("payment_bucket") == "cash",
              str(cash_order_doc))
        check("Don hang Cash trang thai 'PAID'", cash_order_doc.get("status") == "PAID")

        # ====================================================================
        step("DON HANG #2 — Thanh toan QUET THE (Card), CO chia hoa hong Chu/Tho 60/40")
        # ====================================================================
        card_subtotal = round(PRODUCT_A["price"] * CARD_ORDER_QTY_A + PRODUCT_B["price"] * CARD_ORDER_QTY_B, 2)
        card_total = round(card_subtotal + CARD_ORDER_TIP, 2)
        expected_staff_commission = round(card_subtotal * (EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT / 100), 2)
        expected_owner_commission = round(card_subtotal - expected_staff_commission, 2)
        expected_staff_total_earning = round(expected_staff_commission + CARD_ORDER_TIP, 2)
        print(f"  -> Gio hang Card: {CARD_ORDER_QTY_A} x {PRODUCT_A['name']} + {CARD_ORDER_QTY_B} x "
              f"{PRODUCT_B['name']} = ${card_subtotal:.2f}, Tip ${CARD_ORDER_TIP:.2f} -> Total ky vong ${card_total:.2f}")
        print(f"  -> Hoa hong ky vong: Tho {EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT}% x subtotal = "
              f"${expected_staff_commission:.2f}, Chu = ${expected_owner_commission:.2f}, "
              f"+ Tip 100% ve Tho = ${CARD_ORDER_TIP:.2f} -> Tho thuc nhan ${expected_staff_total_earning:.2f}")

        gw = mock_payment_gateway_charge(card_total, method="card")
        check("Mock Gateway (Card) tra ve SUCCESS", gw["status"] == "SUCCESS", str(gw))

        resp = merchant_client.post("/api/sales/checkout", json={
            "items": [
                {"product_id": product_a_doc["id"], "quantity": CARD_ORDER_QTY_A},
                {"product_id": product_b_doc["id"], "quantity": CARD_ORDER_QTY_B},
            ],
            "tip_amount": CARD_ORDER_TIP,
            "payment_method": "card",
            "status": "PAID",
            "customer_phone": CUSTOMER_CARD_PHONE,
            "currency": "USD",
            "staff_id": staff_id,
        })
        rj = resp.get_json()
        check("POST /api/sales/checkout (Card) thanh cong", resp.status_code == 200 and rj.get("success") is True, str(rj))
        check("Total don Card dung", abs(rj["total_amount"] - card_total) < 0.01, str(rj))
        check("payment_bucket tra ve dung 'card'", rj.get("payment_bucket") == "card", str(rj))
        check("Hoa hong Tho (staff_commission) dung 40% subtotal",
              abs(rj["staff_commission"] - expected_staff_commission) < 0.01, str(rj))
        check("Hoa hong Chu (owner_commission) dung 60% subtotal",
              abs(rj["owner_commission"] - expected_owner_commission) < 0.01, str(rj))
        check("Tip 100% ve Tho (staff_tip_earning = tip_amount, KHONG bi chia %)",
              abs(rj["staff_tip_earning"] - CARD_ORDER_TIP) < 0.01, str(rj))
        check("Tong Tho thuc nhan (staff_total_earning = hoa hong + tip) dung",
              abs(rj["staff_total_earning"] - expected_staff_total_earning) < 0.01, str(rj))
        card_order_id = rj["order_id"]

        card_order_doc = db.orders.find_one({"id": card_order_id})
        check("Don hang Card luu DB dung payment_method='card' + payment_bucket='card'",
              card_order_doc.get("payment_method") == "card" and card_order_doc.get("payment_bucket") == "card",
              str(card_order_doc))
        check("Don hang Card gan dung staff_id", card_order_doc.get("staff_id") == staff_id, str(card_order_doc))
        check("Don hang Card trang thai 'PAID'", card_order_doc.get("status") == "PAID")

        # ====================================================================
        step("Dashboard Chu tiem — Tong hop doanh thu HOM NAY (Cash/Card/So khach)")
        # ====================================================================
        resp = merchant_client.get("/api/dashboard/sales_summary")
        rj = resp.get_json()
        check("GET /api/dashboard/sales_summary thanh cong", resp.status_code == 200 and rj.get("success") is True, str(rj))
        d = rj["data"]
        print(f"  -> Dashboard hom nay: {d}")
        check("Tong so don hom nay = 2", d["total_orders_today"] == 2, str(d))
        check("Tong doanh thu hom nay = Cash + Card",
              abs(d["total_revenue_today"] - round(cash_total + card_total, 2)) < 0.01, str(d))
        check("Doanh thu Cash hom nay dung", abs(d["cash_revenue_today"] - cash_total) < 0.01, str(d))
        check("Doanh thu Card hom nay dung", abs(d["card_revenue_today"] - card_total) < 0.01, str(d))
        check("Tong so khach hom nay = 2 (2 SDT khac nhau)", d["total_customers_today"] == 2, str(d))

        # ====================================================================
        step("Nhan vien (Tho) tra cuu thu nhap chinh xac trong ngay")
        # ====================================================================
        resp = merchant_client.get(f"/api/staff/{staff_id}/income_today")
        rj = resp.get_json()
        check("GET /api/staff/<id>/income_today thanh cong", resp.status_code == 200 and rj.get("success") is True, str(rj))
        d = rj["data"]
        print(f"  -> Thu nhap hom nay cua {d.get('staff_name')}: {d}")
        check("Tho phuc vu dung 1 khach hom nay (chi don Card co gan staff_id)",
              d["customers_served_today"] == 1, str(d))
        check("Tho huong dung tien hoa hong dich vu (40%)",
              abs(d["commission_earned_today"] - expected_staff_commission) < 0.01, str(d))
        check("Tho thu dung 100% tien Tip", abs(d["tips_earned_today"] - CARD_ORDER_TIP) < 0.01, str(d))
        check("Tong thu nhap hom nay cua Tho dung",
              abs(d["total_income_today"] - expected_staff_total_earning) < 0.01, str(d))

        # ====================================================================
        step("Xac nhan CRM luu nguyen ven cho CA HAI don (Cash va Card)")
        # ====================================================================
        cash_customer = db.customers.find_one({"business_id": business_id, "phone": CUSTOMER_CASH_PHONE})
        check("Khach hang don CASH da duoc luu vao CRM voi dung SDT + tong chi tieu",
              cash_customer is not None and abs(cash_customer.get("total_spent", 0) - cash_total) < 0.01,
              str(cash_customer))
        card_customer = db.customers.find_one({"business_id": business_id, "phone": CUSTOMER_CARD_PHONE})
        check("Khach hang don CARD da duoc luu vao CRM voi dung SDT + tong chi tieu",
              card_customer is not None and abs(card_customer.get("total_spent", 0) - card_total) < 0.01,
              str(card_customer))

        cash_items_in_db = list(db.order_items.find({"order_id": cash_order_id}))
        check("order_items don Cash giu dung customer_phone (khong that thoat)",
              all(it.get("customer_phone") == CUSTOMER_CASH_PHONE for it in cash_items_in_db), str(cash_items_in_db))
        card_items_in_db = list(db.order_items.find({"order_id": card_order_id}))
        check("order_items don Card giu dung customer_phone (khong that thoat)",
              all(it.get("customer_phone") == CUSTOMER_CARD_PHONE for it in card_items_in_db), str(card_items_in_db))

        # ====================================================================
        step("Xuat Bill don Card (co hoa hong) — tong hop tu du lieu that trong DB")
        # ====================================================================
        print("\n" + "-" * 60)
        print("               HOA DON / RECEIPT (BitPaw OS)")
        print("-" * 60)
        print(f"  Cua hang     : {business_doc['name']}")
        print(f"  Ma don hang  : #{card_order_id}  (Card)")
        print(f"  Khach hang   : {card_customer['name']} ({CUSTOMER_CARD_PHONE})")
        print(f"  Tho phuc vu  : {STAFF_NAME} (staff_id={staff_id})")
        for it in card_items_in_db:
            pname = PRODUCT_A["name"] if it["product_id"] == product_a_doc["id"] else PRODUCT_B["name"]
            print(f"    - {pname:<24} x{it['quantity']}  @ ${it['price']:.2f}  = ${it['total_price']:.2f}")
        print(f"  {'Subtotal':<26}: ${card_order_doc['subtotal']:.2f}")
        print(f"  {'Tip (100% ve Tho)':<26}: ${card_order_doc['tip_amount']:.2f}")
        print(f"  {'TOTAL':<26}: ${card_order_doc['total_amount']:.2f}")
        print(f"  {'-- Hoa hong Chu (60%)':<26}: ${card_order_doc['owner_commission']:.2f}")
        print(f"  {'-- Hoa hong Tho (40%)':<26}: ${card_order_doc['staff_commission']:.2f}")
        print(f"  {'-- Tho thuc nhan (HH+Tip)':<26}: ${card_order_doc['staff_total_earning']:.2f}")
        print(f"  Phuong thuc  : {card_order_doc['payment_method']} (Gateway txn: {gw['transaction_id']})")
        print(f"  Trang thai   : {card_order_doc['status']}")
        print("-" * 60)

        print("\n✅ E2E TEST PASSED: TỪ SETUP ĐẾN XUẤT BILL THÀNH CÔNG")
        exit_code = 0

    except Exception as e:
        print(f"\n❌ E2E TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1

    finally:
        print("\n" + "=" * 78)
        cleanup_test_data(db, "after")
        print("=" * 78)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
