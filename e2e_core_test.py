#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E Core Backend Test — BitPaw OS
==================================
Kich ban: God Mode (Super Admin) -> Tao Merchant -> Setup san pham -> 2 don
hang that (1 Cash, 1 Card co chia hoa hong Chu/Tho 6-4 + Tip 100% cho tho)
-> Dashboard tong hop doanh thu Cash/Card + so khach hom nay -> Nhan vien tra
cuu thu nhap trong ngay -> Xac nhan CRM luu nguyen ven du lieu khach hang cho
CA HAI don -> Square Terminal that (Sandbox) + Webhook bao mat.

KHONG dung Playwright/trinh duyet.

2 CHE DO CHAY:
  python e2e_core_test.py                 -> LOCAL: goi thang Flask test_client()
                                              trong tien trinh (bypass God Mode qua
                                              session_transaction, khong can mat khau that).
  python e2e_core_test.py --target production
                                           -> PRODUCTION: goi HTTP THAT vao
                                              https://bitpawsoftware.com (dung `requests`),
                                              dung dung Credentials Square THAT da cau hinh
                                              tren Vercel project bitpaw-saas-web. KHONG the
                                              bypass God Mode qua HTTP that (khong co mat
                                              khau superadmin that) nen buoc seed License Key
                                              se ghi thang vao MongoDB (dung MONGO_URI o .env,
                                              CHUNG voi production) thay vi goi API superadmin.

An toan du lieu production: script noi thang vao MONGO_URI that (Atlas) khai
bao trong .env — moi du lieu test deu dung 1 bo dinh danh CO DINH, DE NHAN
BIET va duoc XOA SACH ca truoc lan chay lan sau khi chay xong (thanh cong lan
that bai deu don dep) de khong rac du lieu that.

GIOI HAN DA BIET (che do --target production): Webhook Square dung
SQUARE_WEBHOOK_SIGNATURE_KEY duoc luu o che do "Sensitive" tren Vercel — GIA
TRI THAT KHONG THE doc lai qua CLI/API boi bat ky ai, ke ca chu tai khoan. Vi
vay script KHONG THE tu ky 1 webhook that voi đúng secret Production o che do
nay (xem log [SKIP] o Buoc Webhook). Muon xac nhan tron ven buoc nay, dung
tinh nang "Send Test Event" ngay trong Square Developer Dashboard (Webhooks ->
chon subscription -> Test) — Square se tu ky va gui 1 request that toi dung
URL da dang ky, khong can lo bi mat SQUARE_WEBHOOK_SIGNATURE_KEY.

Chay:  python e2e_core_test.py
       python e2e_core_test.py --target production
"""

import sys
import os
import uuid
import time
import hmac
import hashlib
import base64
import argparse
import json as _json
from datetime import datetime

# Windows console: bat buoc UTF-8 truoc khi in bat ky dong log tieng Viet/emoji nao,
# neu khong se UnicodeEncodeError ngay dong print() dau tien tren cp1252.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PRODUCTION_BASE_URL = "https://www.bitpawsoftware.com"  # domain goc (khong "www") luon 308
# redirect sang ban "www" — dung thang dang canonical de tranh 1 hop redirect lam sai lech
# status code cac request follow_redirects=False (vd /register/-login dang mong 301/302 that
# cua app, khong phai 308 redirect ten mien).

# Che do LOCAL: Square webhook (SQUARE_WEBHOOK_SIGNATURE_KEY/SQUARE_WEBHOOK_URL) khong co
# trong .env local — tu set 1 key TEST-ONLY truoc khi import app.py/payment_us_engine.py (2
# module doc gia tri nay tai thoi diem import) de van test duoc THUAT TOAN verify chu ky.
# KHONG anh huong gi den cau hinh that tren Vercel (chi ap dung cho tien trinh Python local).
os.environ.setdefault("SQUARE_WEBHOOK_SIGNATURE_KEY", "e2e-test-only-webhook-signature-key")
os.environ.setdefault("SQUARE_WEBHOOK_URL", "https://e2e-test.local/api/webhooks/square")

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
CUSTOMER_SQUARE_PHONE = "0909000444"
STAFF_NAME = "E2E Test Technician"
STAFF_PHONE = "0909000333"
FAKE_SQUARE_CHECKOUT_ID = "E2E-TEST-SQUARE-CHECKOUT-0001"

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
    (quet the HOAC nhan tien mat) tra ve SUCCESS/FAILED kem transaction_id. Chi dung cho
    luong Cash/Card noi bo (khong lien quan Square) — Square duoc goi that o buoc rieng
    ben duoi."""
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
                                   "phone": {"$in": [CUSTOMER_CASH_PHONE, CUSTOMER_CARD_PHONE, CUSTOMER_SQUARE_PHONE]}})
        db.system_settings.delete_many({"key": f"business_mode_{old_business_id}"})
        db.system_settings.delete_many({"key": "commission_rate", "business_id": old_business_id})
        db.business_memberships.delete_many({"owner_user_id": old_business_id})
        db.user_logs.delete_many({"business_id": old_business_id})
        db.users.delete_many({"email": TEST_EMAIL})
        print(f"  [cleanup:{phase}] Da xoa merchant/orders/products/staff cu (business_id={old_business_id}).")
    else:
        print(f"  [cleanup:{phase}] Khong co du lieu merchant test cu can xoa.")
    db.license_codes.delete_many({"license_key": TEST_LICENSE_KEY})


# ============================================================================
# CLIENT ADAPTER — cho phep dung LAI y het 1 bo logic test cho ca 2 che do:
#   - LocalClient: boc Flask test_client() (goi thang trong tien trinh)
#   - ProdClient:  boc requests.Session() (goi HTTP that toi bitpawsoftware.com)
# ============================================================================
class _RespAdapter:
    """Chuan hoa response cua `requests` cho co cung interface .status_code/.get_json()
    nhu Flask test_client — de phan con lai cua script khong can if/else theo che do."""
    def __init__(self, raw_response):
        self._raw = raw_response
        self.status_code = raw_response.status_code

    def get_json(self):
        try:
            return self._raw.json()
        except Exception:
            return {}

    def get_data(self, as_text=False):
        return self._raw.text if as_text else self._raw.content


class ProdClient:
    """Goi HTTP THAT toi production — dung cho --target production."""
    def __init__(self, base_url):
        import requests
        import urllib3
        # Moi truong local nay khong xac thuc duoc chain chung chi cua bitpawsoftware.com
        # (thieu local issuer certificate trong CA bundle cua Python/urllib3 tren may nay) —
        # da gap dung van de nay o cac lan kiem tra production truoc (khi do dung `curl -sk`).
        # Tat verify=False CHI cho phien HTTP cua script test nay, KHONG anh huong gi den bao
        # mat that cua site (van la HTTPS that, chi la khong tu xac thuc chain o may local).
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._requests = requests
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = False

    def get(self, path, headers=None):
        r = self.session.get(self.base_url + path, headers=headers, timeout=30)
        return _RespAdapter(r)

    def post(self, path, json=None, data=None, headers=None, content_type=None, follow_redirects=True):
        req_headers = dict(headers or {})
        if content_type:
            req_headers["Content-Type"] = content_type
        r = self.session.post(
            self.base_url + path, json=json, data=data, headers=req_headers,
            allow_redirects=follow_redirects, timeout=30
        )
        return _RespAdapter(r)


def main():
    parser = argparse.ArgumentParser(description="BitPaw OS E2E backend test.")
    parser.add_argument("--target", choices=["local", "production"], default="local",
                         help="local = Flask test_client() trong tien trinh; "
                              "production = HTTP that toi bitpawsoftware.com")
    args = parser.parse_args()
    is_production = args.target == "production"

    print("#" * 78)
    mode_label = f"PRODUCTION ({PRODUCTION_BASE_URL})" if is_production else "LOCAL (Flask test_client)"
    print(f"# E2E CORE BACKEND TEST — BitPaw OS — CHE DO: {mode_label}")
    print(f"# Bat dau luc: {datetime.now().isoformat(timespec='seconds')}")
    print("#" * 78)

    from mongo_client import db
    flask_app = None
    if not is_production:
        import app as flask_app
        flask_app.app.testing = True

    if db is None:
        print("\n[FAIL] MongoDB chua ket noi (kiem tra MONGO_URI trong .env). Dung test.")
        sys.exit(1)

    cleanup_test_data(db, "before")

    try:
        # ====================================================================
        step("Khoi tao dieu kien Merchant (License Key) & Tao Merchant that")
        # ====================================================================
        if is_production:
            # Khong the bypass God Mode qua HTTP that (khong co mat khau superadmin that
            # trong tay script) — seed thang License Key vao MongoDB (CHUNG DB voi
            # production), tuong duong hanh dong "Superadmin bam nut sinh key" ma khong
            # can dang nhap that. Day la 1 lan goi DB truc tiep duoc phep theo de bai gom
            # "hoac goi thang vao Controller/Database khi khong co route HTTP tuong ung".
            from mongo_client import next_mongo_id
            db.license_codes.update_one(
                {"license_key": TEST_LICENSE_KEY},
                {"$set": {"nganh_nghe": TEST_INDUSTRY, "trang_thai": "Sẵn sàng"},
                 "$setOnInsert": {"id": next_mongo_id("license_codes")}},
                upsert=True
            )
            print(f"  -> Da seed License Key '{TEST_LICENSE_KEY}' thang vao MongoDB production (trang_thai='Sẵn sàng').")
            admin_client = None
            merchant_client = ProdClient(PRODUCTION_BASE_URL)
        else:
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
        step("DON HANG #2 — Thanh toan QUET THE (Card noi bo), CO chia hoa hong Chu/Tho 60/40")
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

        # ====================================================================
        step("SQUARE TERMINAL — Day lenh quet the THAT xuong Square Sandbox")
        # ====================================================================
        square_qty = 1
        square_subtotal = round(PRODUCT_A["price"] * square_qty, 2)
        resp = merchant_client.post("/api/payments/square/checkout", json={
            "items": [{"product_id": product_a_doc["id"], "quantity": square_qty}],
            "tip_amount": 3.00,
            "customer_phone": CUSTOMER_SQUARE_PHONE,
            "staff_id": staff_id,
            "currency": "USD",
        })
        rj = resp.get_json()
        print(f"  -> POST /api/payments/square/checkout -> status={resp.status_code}, body={rj}")

        if is_production:
            # Che do production: TUYET DOI khong bypass/fallback — neu Square that khong
            # tra ve thanh cong, day la 1 KET QUA THAT can bao cao ro rang, khong tu mo
            # phong don hang de "cho qua".
            check("POST /api/payments/square/checkout goi THANH CONG sang Square Sandbox (khong 503/bypass)",
                  resp.status_code == 200 and rj.get("success") is True, str(rj))
            check("Square API tra ve checkout_id hop le", bool(rj.get("checkout_id")), str(rj))
            square_order_id = rj["order_id"]
            square_checkout_id = rj["checkout_id"]
            print(f"  ==> ĐÃ XÁC NHẬN: Square Sandbox trả về checkout_id THẬT = {square_checkout_id} "
                  f"(terminal_status={rj.get('terminal_status')}).")
        elif rj.get("success"):
            # Che do local nhung .env local lai co du credentials that (hiem, nhung van xu ly
            # dung: dung dung checkout_id THAT Square tra ve).
            square_order_id = rj["order_id"]
            square_checkout_id = rj["checkout_id"]
            check("Đơn Square 'pending' được tạo với subtotal đúng",
                  abs(db.orders.find_one({"id": square_order_id})["subtotal"] - square_subtotal) < 0.01)
        else:
            print("  [INFO] Che do LOCAL: SQUARE_DEVICE_ID trong .env local dang trong/chua that ->"
                  " tu tao 1 don 'pending' TUONG DUONG de van test tron ven phan Webhook ben duoi"
                  " (khong anh huong ket qua Buoc nay, day KHONG phai loi code).")
            order_fields = {
                "subtotal": square_subtotal, "tip_amount": 3.00, "total_amount": round(square_subtotal + 3.00, 2),
                "payment_method": "square", "payment_bucket": "card", "currency": "USD",
                "customer_phone": CUSTOMER_SQUARE_PHONE, "staff_id": staff_id,
                "commission_rate": EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT,
                "staff_commission": round(square_subtotal * (EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT / 100), 2),
                "owner_commission": round(square_subtotal * (1 - EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT / 100), 2),
                "staff_tip_earning": 3.00,
                "staff_total_earning": round(square_subtotal * (EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT / 100) + 3.00, 2),
            }
            from mongo_client import next_mongo_id as _next_id
            square_order_id = _next_id("orders")
            square_checkout_id = FAKE_SQUARE_CHECKOUT_ID
            db.orders.insert_one({
                "id": square_order_id, "business_id": business_id, "status": "pending",
                "created_at": datetime.now().isoformat(), "square_checkout_id": square_checkout_id,
                "square_txn_id": f"SQTERM-{square_order_id}-FAKE", **order_fields
            })

        pending_order = db.orders.find_one({"id": square_order_id})
        check("Đơn Square đang ở trạng thái 'pending' TRƯỚC khi có Webhook",
              pending_order.get("status") == "pending", str(pending_order))
        check("Đơn Square đã tính SẴN hoa hồng Thợ (không đợi Webhook mới tính)",
              abs(pending_order.get("staff_commission", 0) -
                  round(square_subtotal * (EXPECTED_DEFAULT_STAFF_COMMISSION_PERCENT / 100), 2)) < 0.01,
              str(pending_order))

        # ====================================================================
        step("WEBHOOK SECURITY — từ chối request KHÔNG có chữ ký hợp lệ (chống fake webhook)")
        # ====================================================================
        fake_webhook_payload = {
            "type": "terminal.checkout.updated",
            "data": {"object": {"checkout": {"id": square_checkout_id, "status": "COMPLETED"}}}
        }
        resp = merchant_client.post("/api/webhooks/square", json=fake_webhook_payload)
        check("Webhook KHÔNG có header chữ ký -> bị từ chối 401", resp.status_code == 401,
              f"status={resp.status_code}, body={resp.get_json()}")

        resp = merchant_client.post(
            "/api/webhooks/square", json=fake_webhook_payload,
            headers={"x-square-hmacsha256-signature": "hacker-fake-signature-not-real"}
        )
        check("Webhook có chữ ký SAI -> vẫn bị từ chối 401", resp.status_code == 401,
              f"status={resp.status_code}, body={resp.get_json()}")

        still_pending = db.orders.find_one({"id": square_order_id})
        check("Đơn hàng VẪN CÒN 'pending' sau 2 lần webhook giả mạo bị chặn (không bị đánh lừa)",
              still_pending.get("status") == "pending", str(still_pending))

        # ====================================================================
        step("WEBHOOK THẬT — Square báo COMPLETED -> cập nhật PAID + CRM + Hoa hồng")
        # ====================================================================
        if is_production:
            # SQUARE_WEBHOOK_SIGNATURE_KEY that duoc luu o che do "Sensitive" tren Vercel —
            # KHONG THE doc lai gia tri that qua CLI/API du la chinh chu tai khoan (gioi han
            # nen tang cua Vercel, khong phai gioi han cua script). Script KHONG the tu ky 1
            # webhook "that" khop voi secret Production trong che do nay — bo qua that thi
            # (khong gia mao/bypass), huong dan xac nhan thay the ngay ben duoi.
            print("  [SKIP] Không thể tự ký Webhook bằng ĐÚNG SQUARE_WEBHOOK_SIGNATURE_KEY của Production:")
            print("         Vercel lưu biến này ở chế độ 'Sensitive' -> giá trị thật KHÔNG THỂ đọc lại")
            print("         qua CLI/API bởi bất kỳ ai, kể cả chủ tài khoản. Đây là giới hạn nền tảng")
            print("         Vercel, không phải lỗ hổng logic hay bug của code.")
            print("  -> CÁCH XÁC NHẬN THAY THẾ (bạn tự làm, mất ~1 phút, KHÔNG cần lộ secret):")
            print("     Square Developer Dashboard -> Webhooks -> chọn subscription đang trỏ về")
            print(f"     {PRODUCTION_BASE_URL}/api/webhooks/square -> nút 'Test' / 'Send Test Event'.")
            print("     Square sẽ tự ký bằng đúng key thật và gửi 1 request thật tới URL trên —")
            print("     nếu Dashboard báo 200 OK nghĩa là chữ ký đã verify thành công trên Production.")
            print(f"  -> Đơn hàng test 'pending' vẫn còn nguyên tại order_id={square_order_id}, "
                  f"square_checkout_id={square_checkout_id} để bạn tự đối chiếu nếu cần.")
        else:
            webhook_url = os.environ["SQUARE_WEBHOOK_URL"]
            webhook_key = os.environ["SQUARE_WEBHOOK_SIGNATURE_KEY"]
            raw_body = _json.dumps(fake_webhook_payload).encode("utf-8")
            digest = hmac.new(webhook_key.encode("utf-8"), webhook_url.encode("utf-8") + raw_body, hashlib.sha256).digest()
            valid_signature = base64.b64encode(digest).decode("utf-8")
            print("  -> Đã tự ký webhook bằng SQUARE_WEBHOOK_SIGNATURE_KEY test-only (không phải secret Production).")

            resp = merchant_client.post(
                "/api/webhooks/square", data=raw_body, content_type="application/json",
                headers={"x-square-hmacsha256-signature": valid_signature}
            )
            rj = resp.get_json()
            check("Webhook CÓ chữ ký ĐÚNG -> được chấp nhận (200)", resp.status_code == 200 and rj.get("success") is True,
                  f"status={resp.status_code}, body={rj}")

            paid_order = db.orders.find_one({"id": square_order_id})
            check("Đơn hàng Square đã chuyển trạng thái 'PAID' sau Webhook", paid_order.get("status") == "PAID", str(paid_order))

            square_customer = db.customers.find_one({"business_id": business_id, "phone": CUSTOMER_SQUARE_PHONE})
            check("Khách hàng đơn Square ĐÃ được lưu vào CRM (Webhook trigger đúng _finalize_paid_order)",
                  square_customer is not None and abs(square_customer.get("total_spent", 0) - paid_order["total_amount"]) < 0.01,
                  str(square_customer))

            # Webhook trùng (Square có thể gửi lại) không được cộng CRM/điểm 2 lần.
            spent_before_retry = square_customer["total_spent"]
            resp = merchant_client.post(
                "/api/webhooks/square", data=raw_body, content_type="application/json",
                headers={"x-square-hmacsha256-signature": valid_signature}
            )
            check("Webhook GỬI TRÙNG (retry) vẫn trả 200 (Square sẽ không retry vô ích)",
                  resp.status_code == 200)
            square_customer_after_retry = db.customers.find_one({"business_id": business_id, "phone": CUSTOMER_SQUARE_PHONE})
            check("CRM KHÔNG bị cộng trùng total_spent khi Webhook gửi lại (idempotent)",
                  abs(square_customer_after_retry["total_spent"] - spent_before_retry) < 0.01,
                  str(square_customer_after_retry))

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
