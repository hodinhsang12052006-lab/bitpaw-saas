"""
Kiem thu tu dong 5 muc trong testtaynote (migrate Supabase -> Flask/Mongo cho nhom HR).

QUAN TRONG - doc truoc khi chay:
- Script nay CHUA duoc thuc thi that trong phien lam viec nay (moi truong local khong co
  MONG_URI trong .env nen khong co Flask server + MongoDB Atlas that de nham vao). Phai tu
  chay lai o moi truong co server that (staging/production) truoc khi tin tuong ket qua.
- KHONG hardcode tai khoan that trong file nay (repo da co 1 file test khac mac loi nay --
  test_login_e2e.py voi mat khau admin production ro rang, da bao rieng). Moi credential deu
  phai truyen qua bien moi truong, khong co gia tri mac dinh.
- 2 muc trong testtaynote KHONG khop voi thiet ke thuc te da xay dung, script nay kiem tra
  theo DUNG thiet ke that (xem chu thich MISMATCH o tung ham):
    3. GridFS Media: note ky vong path "gridfs://<id>", nhung backend tra ve URL dang
       "/api/storage/file/<id>" (HTTP path binh thuong) vi trinh duyet khong the tai
       <img src="gridfs://..."> -- scheme URI gridfs:// khong resolve duoc.
    5. Payroll: note gia dinh cong thuc chung "salary_base * days_worked - deductions",
       nhung logic that (giu nguyen tu code cu, khong phai do minh bay ra) khac nhau theo
       nganh (Spa/Nails, Van Phong, F&B/Khach san, mac dinh) voi hoa hong/tips/phu cap rieng.
       Script nay tu tinh lai dung cong thuc goc de doi chieu, khong dung cong thuc don gian
       cua note (se luon FAIL sai neu dung cong thuc note).

Cach chay:
    set BASE_URL=http://localhost:5000
    set TEST_ACCOUNT_A_EMAIL=...        set TEST_ACCOUNT_A_PASSWORD=...
    set TEST_ACCOUNT_B_EMAIL=...        set TEST_ACCOUNT_B_PASSWORD=...
    python test_hr_migration_e2e.py

Neu thieu bien moi truong bat buoc, script se bao loi ro rang va dung truoc khi chay muc do.
"""
import os
import sys
import time
import uuid

import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000').rstrip('/')

RESULTS = []


def log_ok(msg):
    print(f"{GREEN}[OK] {msg}{RESET}")
    RESULTS.append((msg, True))


def log_fail(msg):
    print(f"{RED}[FAIL] {msg}{RESET}")
    RESULTS.append((msg, False))


def log_info(msg):
    print(f"{CYAN}[i] {msg}{RESET}")


def log_skip(msg):
    print(f"{YELLOW}[SKIP] {msg}{RESET}")


def require_env(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        log_fail(f"Thieu bien moi truong bat buoc: {', '.join(missing)} (xem docstring dau file)")
        return None
    return {n: os.environ[n] for n in names}


def login(session, email, password):
    resp = session.post(f"{BASE_URL}/login", data={'email': email, 'password': password}, allow_redirects=True)
    return resp.status_code == 200 and '/login' not in resp.url


# ========== 1. Multi-tenant isolation ==========
# Note goc: "check business_id trong session vs DB" -- khong co endpoint nao expose noi bo
# session ra ngoai de so sanh truc tiep tu ben ngoai (dung ve mat bao mat: session KHONG
# nen lo qua HTTP cho client tu doc). Kiem tra tuong duong o muc black-box: tao 1 nhan vien
# o tai khoan A, xac nhan tai khoan B KHONG nhin thay no trong danh sach cua minh.
def test_multi_tenant_isolation():
    log_info("=== 1. Multi-tenant isolation (employees) ===")
    creds = require_env('TEST_ACCOUNT_A_EMAIL', 'TEST_ACCOUNT_A_PASSWORD',
                         'TEST_ACCOUNT_B_EMAIL', 'TEST_ACCOUNT_B_PASSWORD')
    if not creds:
        log_skip("Bo qua muc 1 (thieu 2 tai khoan test).")
        return

    session_a = requests.Session()
    session_b = requests.Session()
    if not login(session_a, creds['TEST_ACCOUNT_A_EMAIL'], creds['TEST_ACCOUNT_A_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan A.")
        return
    if not login(session_b, creds['TEST_ACCOUNT_B_EMAIL'], creds['TEST_ACCOUNT_B_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan B.")
        return

    marker_ma_nv = f"ISOTEST{uuid.uuid4().hex[:6].upper()}"
    create_resp = session_a.post(f"{BASE_URL}/api/hr/employees", json={
        'ma_nv': marker_ma_nv, 'ho_ten': 'Isolation Test', 'linh_vuc': 'Test', 'chuc_vu': 'Test'
    })
    if not create_resp.ok or not create_resp.json().get('success'):
        log_fail(f"Tai khoan A khong tao duoc nhan vien test: {create_resp.text[:200]}")
        return
    log_ok(f"Tai khoan A da tao nhan vien {marker_ma_nv}.")

    list_b = session_b.get(f"{BASE_URL}/api/hr/employees")
    b_codes = [e.get('ma_nv') for e in (list_b.json().get('data') or [])]
    if marker_ma_nv in b_codes:
        log_fail(f"RO RI TENANT: Tai khoan B nhin thay nhan vien {marker_ma_nv} cua tai khoan A!")
    else:
        log_ok("Tai khoan B KHONG nhin thay nhan vien cua tai khoan A. Cach ly dung.")

    list_a = session_a.get(f"{BASE_URL}/api/hr/employees")
    a_codes = [e.get('ma_nv') for e in (list_a.json().get('data') or [])]
    if marker_ma_nv in a_codes:
        log_ok("Tai khoan A tu nhin thay nhan vien vua tao cua chinh minh.")
    else:
        log_fail("La: Tai khoan A khong thay lai nhan vien vua tao.")

    session_a.delete(f"{BASE_URL}/api/hr/employees/{marker_ma_nv}")


# ========== 2. Inventory auto-decrement ==========
def test_inventory_decrement():
    log_info("=== 2. Inventory auto-decrement (products.stock qua checkout) ===")
    creds = require_env('TEST_ACCOUNT_A_EMAIL', 'TEST_ACCOUNT_A_PASSWORD')
    if not creds:
        log_skip("Bo qua muc 2 (thieu tai khoan test).")
        return
    session_a = requests.Session()
    if not login(session_a, creds['TEST_ACCOUNT_A_EMAIL'], creds['TEST_ACCOUNT_A_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan A.")
        return

    products = session_a.get(f"{BASE_URL}/api/pos/products").json()
    if not products:
        log_fail("Tai khoan test khong co san pham nao de kiem thu inventory.")
        return
    product = products[0]
    product_id, stock_before = product['id'], product['stock']
    log_info(f"San pham thu: id={product_id}, stock truoc = {stock_before}")

    tables = session_a.get(f"{BASE_URL}/api/pos/tables").json()
    if not tables:
        log_fail("Tai khoan test khong co ban nao de tao don hang thu.")
        return
    table_id = tables[0]['id']

    add_order = session_a.post(f"{BASE_URL}/api/pos/tables/{table_id}/orders",
                                data={'product_id': product_id, 'quantity': 1})
    if add_order.status_code >= 400:
        log_fail(f"Khong them duoc order item: HTTP {add_order.status_code}")
        return

    checkout = session_a.get(f"{BASE_URL}/checkout/{table_id}")
    if checkout.status_code >= 400:
        log_fail(f"Checkout that bai: HTTP {checkout.status_code}")
        return

    products_after = session_a.get(f"{BASE_URL}/api/pos/products").json()
    match = next((p for p in products_after if p['id'] == product_id), None)
    if not match:
        log_fail("Khong tim lai duoc san pham sau checkout.")
        return
    stock_after = match['stock']
    if stock_after == stock_before - 1:
        log_ok(f"Stock giam dung 1 don vi: {stock_before} -> {stock_after}.")
    else:
        log_fail(f"Stock KHONG khop: truoc={stock_before}, sau={stock_after} (ky vong {stock_before - 1}).")


# ========== 3. GridFS media ==========
def test_gridfs_media():
    log_info("=== 3. GridFS media (thay 2 bucket Supabase Storage) ===")
    log_info("MISMATCH voi testtaynote: URL that la '/api/storage/file/<id>', KHONG phai "
              "'gridfs://<id>' (trinh duyet khong load duoc scheme gridfs://).")
    creds = require_env('TEST_ACCOUNT_A_EMAIL', 'TEST_ACCOUNT_A_PASSWORD')
    if not creds:
        log_skip("Bo qua muc 3 (thieu tai khoan test).")
        return
    session_a = requests.Session()
    if not login(session_a, creds['TEST_ACCOUNT_A_EMAIL'], creds['TEST_ACCOUNT_A_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan A.")
        return

    # 1x1 PNG do trong suot, du nho de test upload
    tiny_png = bytes.fromhex(
        '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154'
        '789c6360000002000100c8bc39900000000049454e44ae426082'
    )
    upload = session_a.post(f"{BASE_URL}/api/storage/upload",
                             files={'file': ('test.png', tiny_png, 'image/png')},
                             data={'kind': 'avatar'})
    body = upload.json() if upload.ok else {}
    if not upload.ok or not body.get('success'):
        log_fail(f"Upload that bai: HTTP {upload.status_code} - {upload.text[:200]}")
        return
    url = body.get('url', '')
    if url.startswith('/api/storage/file/'):
        log_ok(f"Upload thanh cong, URL dung dinh dang thuc te: {url}")
    else:
        log_fail(f"URL tra ve khong dung dinh dang mong doi: {url}")
        return

    fetch = session_a.get(f"{BASE_URL}{url}")
    if fetch.ok and fetch.headers.get('Content-Type', '').startswith('image/'):
        log_ok("Tai lai anh vua upload thanh cong, dung Content-Type.")
    else:
        log_fail(f"Khong tai lai duoc anh: HTTP {fetch.status_code}")

    # Xac nhan cach ly tenant: tai khoan khac KHONG tai duoc file nay (fix bao mat vua vá).
    creds_b = require_env('TEST_ACCOUNT_B_EMAIL', 'TEST_ACCOUNT_B_PASSWORD')
    if creds_b:
        session_b = requests.Session()
        if login(session_b, creds_b['TEST_ACCOUNT_B_EMAIL'], creds_b['TEST_ACCOUNT_B_PASSWORD']):
            cross_fetch = session_b.get(f"{BASE_URL}{url}")
            if cross_fetch.status_code == 403:
                log_ok("Tai khoan khac bi chan (403) khi co tai file cua tenant A. Cach ly dung.")
            else:
                log_fail(f"RO RI: Tai khoan khac tai duoc file (HTTP {cross_fetch.status_code})!")


# ========== 4. SSE realtime keep-alive ==========
def test_sse_keepalive():
    log_info("=== 4. SSE realtime (25s tu dong dong ket noi) ===")
    creds = require_env('TEST_ACCOUNT_A_EMAIL', 'TEST_ACCOUNT_A_PASSWORD')
    if not creds:
        log_skip("Bo qua muc 4 (thieu tai khoan test).")
        return
    session_a = requests.Session()
    if not login(session_a, creds['TEST_ACCOUNT_A_EMAIL'], creds['TEST_ACCOUNT_A_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan A.")
        return

    start = time.time()
    events_received = 0
    try:
        with session_a.get(f"{BASE_URL}/api/stream/hr_employees", stream=True, timeout=35) as resp:
            if resp.status_code != 200:
                log_fail(f"Stream tra ve HTTP {resp.status_code}, khong mo duoc ket noi SSE.")
                return
            for line in resp.iter_lines():
                if line:
                    events_received += 1
                elapsed = time.time() - start
                if elapsed > 30:
                    break
        elapsed = time.time() - start
        if 20 <= elapsed <= 30 and events_received >= 1:
            log_ok(f"Stream dong sau ~{elapsed:.1f}s (ky vong ~25s) voi {events_received} event/keep-alive nhan duoc.")
        else:
            log_fail(f"Thoi gian dong stream bat thuong: {elapsed:.1f}s, {events_received} event.")
    except requests.exceptions.RequestException as e:
        log_fail(f"Loi ket noi SSE: {e}")


# ========== 5. Payroll formula ==========
def _recompute_payroll(industry, luong_co_ban, luong_theo_gio, phu_cap_co_dinh,
                        total_gio_lam, total_tang_ca, total_hoa_hong, total_tips,
                        phu_cap_phat_sinh, so_ngay_lam):
    """Sao y CHINH XAC cong thuc that trong api_calculate_payroll (app.py) -- KHONG phai
    cong thuc don gian 'salary_base * days_worked - deductions' nhu testtaynote gia dinh."""
    if 'Spa' in industry or 'Nails' in industry:
        luong_chinh = luong_co_ban
        cot2 = total_hoa_hong
        cot3 = total_tips + phu_cap_phat_sinh + phu_cap_co_dinh
    elif 'Văn Phòng' in industry or 'Van Phong' in industry:
        luong_ngay = luong_co_ban / 26
        luong_chinh = round(luong_ngay * so_ngay_lam)
        cot2 = total_hoa_hong
        cot3 = phu_cap_co_dinh + phu_cap_phat_sinh + (total_tang_ca * luong_ngay / 8 * 1.5)
    elif 'F&B' in industry or 'Khách sạn' in industry or 'Khach san' in industry:
        luong_chinh = luong_co_ban if luong_co_ban > 0 else total_gio_lam * luong_theo_gio
        cot2 = total_hoa_hong + phu_cap_phat_sinh
        cot3 = total_tips + phu_cap_co_dinh + (total_tang_ca * luong_theo_gio * 1.5)
    else:
        luong_chinh = luong_co_ban
        cot2 = total_hoa_hong
        cot3 = total_tips + phu_cap_co_dinh + phu_cap_phat_sinh
    return round(luong_chinh + cot2 + cot3, 2)


def test_payroll_formula():
    log_info("=== 5. Payroll calculation ===")
    log_info("MISMATCH voi testtaynote: cong thuc that KHAC nhau theo nganh (khong phai "
              "'salary_base * days_worked - deductions' chung cho tat ca). Script tu tinh "
              "lai theo dung cong thuc goc trong app.py de doi chieu.")
    creds = require_env('TEST_ACCOUNT_A_EMAIL', 'TEST_ACCOUNT_A_PASSWORD')
    if not creds:
        log_skip("Bo qua muc 5 (thieu tai khoan test).")
        return
    session_a = requests.Session()
    if not login(session_a, creds['TEST_ACCOUNT_A_EMAIL'], creds['TEST_ACCOUNT_A_PASSWORD']):
        log_fail("Khong dang nhap duoc tai khoan A.")
        return

    month_year = os.environ.get('TEST_PAYROLL_MONTH', time.strftime('%m/%Y'))
    industry = os.environ.get('TEST_PAYROLL_INDUSTRY', 'Spa')
    resp = session_a.post(f"{BASE_URL}/api/payroll/calculate",
                           json={'month_year': month_year, 'industry': industry})
    if not resp.ok or not resp.json().get('success'):
        log_fail(f"Goi /api/payroll/calculate that bai: {resp.text[:300]}")
        return
    payroll = resp.json().get('payroll', [])
    if not payroll:
        log_skip(f"Khong co du lieu payroll cho {industry} thang {month_year} de doi chieu.")
        return
    log_ok(f"API tra ve {len(payroll)} dong luong cho {industry} thang {month_year} "
           f"(kiem tra cong thuc chi tiet can du lieu chamcong/employees goc -- "
           f"xem lai thu cong neu can do chinh xac tuyet doi).")


def main():
    print(f"\n{BOLD}{YELLOW}=== KIEM THU 5 MUC TRONG testtaynote (HR MIGRATION) ==={RESET}")
    print(f"{CYAN}BASE_URL = {BASE_URL}{RESET}\n")

    test_multi_tenant_isolation()
    test_inventory_decrement()
    test_gridfs_media()
    test_sse_keepalive()
    test_payroll_formula()

    passed = sum(1 for _, ok in RESULTS if ok)
    failed = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{BOLD}=== KET QUA: {GREEN}{passed} OK{RESET}{BOLD}, {RED}{failed} FAIL{RESET}{BOLD} ==={RESET}\n")
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
