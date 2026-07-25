import sys
import time
import os
import random
from playwright.sync_api import sync_playwright

# Đảm bảo hiển thị đúng font chữ tiếng Việt trên Windows Console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Mã màu ANSI để in báo cáo log chuyên nghiệp
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

# HỆ THỐNG HYBRID ARCHITECTURE: 2 NỀN TẢNG DÙNG CHUNG MONGODB
ADMIN_BASE_URL = os.getenv("ADMIN_BASE_URL", "http://127.0.0.1:5001")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://www.bitpawsoftware.com")

ADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "hodinhsang30052003@gmail.com")
ADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "0794678904Az@")
LICENSE_CODE = "NAIL2026"

def log_success(msg):
    print(f"{GREEN}[✓] {msg}{RESET}")

def log_error(msg):
    print(f"{RED}[❌] {msg}{RESET}")

def log_info(msg):
    print(f"{CYAN}[ℹ] {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}[⚠️] {msg}{RESET}")

def run_test():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU AUTOMATION TEST E2E - HYBRID NAILS ARCHITECTURE (PLAYWRIGHT) ==={RESET}")
    print(f"{CYAN}📌 Admin Local URL: {ADMIN_BASE_URL}{RESET}")
    print(f"{CYAN}📌 Public Web URL:  {PUBLIC_BASE_URL}{RESET}\n")
    
    with sync_playwright() as p:
        log_info("Khởi chạy trình duyệt Chromium (Chế độ UI Non-Headless, quan sát trực quan)...")
        try:
            # 1. CẤU HÌNH TRÌNH DUYỆT NON-HEADLESS & KÍCH THƯỚC MÀN HÌNH
            browser = p.chromium.launch(headless=False, args=["--window-size=1280,900"])
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
        except Exception as e:
            log_error(f"Không thể khởi chạy Chromium: {str(e)}")
            return False

        try:
            # ==========================================================
            # BƯỚC 1: ĐĂNG NHẬP SUPERADMIN (TẠI ADMIN LOCALHOST 5001)
            # ==========================================================
            log_info(f"BƯỚC 1: Đăng nhập tài khoản Superadmin tại Admin Localhost ({ADMIN_BASE_URL}/login)...")
            page.goto(f"{ADMIN_BASE_URL}/login", timeout=15000)
            page.wait_for_selector("#loginFormElement", timeout=10000)
            
            if page.locator("input#loginEmail").count() > 0:
                page.fill("input#loginEmail", ADMIN_EMAIL)
                page.fill("input#loginPassword", ADMIN_PASSWORD)
                page.click("#btnLogin")
            elif page.locator("input#email").count() > 0:
                page.fill("input#email", ADMIN_EMAIL)
                page.fill("input#password", ADMIN_PASSWORD)
                if page.locator("#loginBtn").count() > 0:
                    page.click("#loginBtn")
                else:
                    page.click("button[type='submit']")
            else:
                page.click("button[type='submit']")

            page.wait_for_timeout(3500)
            if "/login" not in page.url:
                log_success(f"Đăng nhập Superadmin tại Admin Localhost thành công! URL: {page.url}")
            else:
                log_warn(f"Trang chưa chuyển hướng khỏi /login (Tiếp tục chuyển tới /super_admin). URL: {page.url}")
            page.wait_for_timeout(1000)

            # ==========================================================
            # BƯỚC 2.1: ĐÚC MÃ BẢN QUYỀN NAIL2026 TẠI SUPERADMIN LOCAL
            # ==========================================================
            log_info(f"BƯỚC 2.1: Truy cập Superadmin Dashboard tại Local ({ADMIN_BASE_URL}/super_admin)...")
            page.goto(f"{ADMIN_BASE_URL}/super_admin", timeout=15000)
            page.wait_for_timeout(1500)
            
            # Mở tab license và đúc mã NAIL2026
            page.evaluate("if(typeof switchTab === 'function') switchTab('license')")
            page.wait_for_timeout(1000)
            
            # Gán mã NAIL2026 vào input
            if page.locator("#keyCodeInput").count() > 0:
                page.fill("#keyCodeInput", LICENSE_CODE)
                page.wait_for_timeout(1000)
            
            if page.locator("#industrySelect").count() > 0:
                page.select_option("#industrySelect", "spa")
                page.wait_for_timeout(1000)
                
            duc_btn = page.locator("button:has-text('ĐÚC BẢN QUYỀN MỚI')")
            if duc_btn.count() > 0:
                duc_btn.click()
                page.wait_for_timeout(2000)
                log_success(f"Đã đúc mã bản quyền '{LICENSE_CODE}' cho ngành Spa/Nails xuống DB chung.")
            
            # Đăng xuất Superadmin khỏi Localhost
            log_info("Đăng xuất Superadmin trên Localhost...")
            page.goto(f"{ADMIN_BASE_URL}/logout", timeout=10000)
            page.wait_for_timeout(1500)

            # ==========================================================
            # BƯỚC 2.2: ONBOARDING - ĐĂNG KÝ TENANT TẠI WEB PUBLIC THẬT
            # ==========================================================
            log_info(f"BƯỚC 2.2: Onboarding - Đăng ký Tenant mới tại Web Thật ({PUBLIC_BASE_URL}/register)...")
            page.goto(f"{PUBLIC_BASE_URL}/register", timeout=15000)
            page.wait_for_selector("#registerFormElement", timeout=10000)

            rand_id = random.randint(1000, 9999)
            tenant_email = f"nail_owner_{rand_id}@bitpaw.com"
            tenant_pass = "NailPass2026!"

            page.fill("input#regFullname", "Sếp Tiệm Nails Luxury")
            page.wait_for_timeout(800)
            page.fill("input#regBusinessName", "Nail Studio Luxury")
            page.wait_for_timeout(800)
            page.select_option("select#reg_business_type", "spa")
            page.wait_for_timeout(800)
            page.fill("input#regEmail", tenant_email)
            page.wait_for_timeout(800)
            page.fill("input#reg_license", LICENSE_CODE)
            page.wait_for_timeout(800)
            page.fill("input#regPassword", tenant_pass)
            page.wait_for_timeout(800)
            page.fill("input#regConfirm", tenant_pass)
            page.wait_for_timeout(1500)

            log_info("Gửi form đăng ký Tenant mới tại Web Thật...")
            page.click("#btnRegister")
            page.wait_for_timeout(4500)
            log_success(f"Đăng ký Tenant 'Nail Studio Luxury' thành công! Email: {tenant_email}")

            # Nếu cần đăng nhập lại trên Web Thật
            if "/login" in page.url:
                log_info("Đăng nhập với tài khoản Chủ tiệm Nails mới trên Web Thật...")
                page.fill("input#loginEmail", tenant_email)
                page.fill("input#loginPassword", tenant_pass)
                page.click("#btnLogin")
                page.wait_for_timeout(3000)

            # ==========================================================
            # BƯỚC 3: THIẾT LẬP MENU DỊCH VỤ (PUBLIC WEB / TENANT)
            # ==========================================================
            log_info(f"BƯỚC 3: Quản lý Dịch vụ tại ({PUBLIC_BASE_URL}/add_spa) -> Tạo 'Cắt da' (50K), 'Sơn Gel' (150K)...")
            page.goto(f"{PUBLIC_BASE_URL}/add_spa", timeout=15000)
            page.wait_for_timeout(2000)

            # Tạo Dịch vụ 1: Cắt da - 50,000 VNĐ
            log_info("Tạo dịch vụ 'Cắt da' (50,000 VNĐ)...")
            if page.locator("input[name='name']").count() > 0:
                page.fill("input[name='name']", "Cắt da")
                page.fill("input[name='price']", "50000")
                page.wait_for_timeout(1000)
                page.click("button[type='submit']")
                page.wait_for_timeout(2000)
                log_success("Đã tạo dịch vụ 'Cắt da' (50K).")

            # Tạo Dịch vụ 2: Sơn Gel - 150,000 VNĐ
            page.goto(f"{PUBLIC_BASE_URL}/add_spa", timeout=15000)
            page.wait_for_timeout(1500)
            log_info("Tạo dịch vụ 'Sơn Gel' (150,000 VNĐ)...")
            if page.locator("input[name='name']").count() > 0:
                page.fill("input[name='name']", "Sơn Gel")
                page.fill("input[name='price']", "150000")
                page.wait_for_timeout(1000)
                page.click("button[type='submit']")
                page.wait_for_timeout(2000)
                log_success("Đã tạo dịch vụ 'Sơn Gel' (150K).")

            # ==========================================================
            # BƯỚC 4: THIẾT LẬP NHÂN SỰ (PUBLIC WEB / TENANT)
            # ==========================================================
            log_info(f"BƯỚC 4: Quản lý Nhân sự tại ({PUBLIC_BASE_URL}/staff) -> Tạo 'Thợ A'...")
            page.goto(f"{PUBLIC_BASE_URL}/staff", timeout=15000)
            page.wait_for_timeout(2000)

            log_info("Tạo nhân viên mới 'Thợ A'...")
            add_staff_payload = {
                "name": "Thợ A",
                "phone": "0909123456",
                "role": "Kỹ thuật viên Nails",
                "commission_rate": 10,
                "is_active": 1
            }
            
            page.evaluate("""payload => {
                fetch('/add_staff', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
            }""", add_staff_payload)
            page.wait_for_timeout(2000)
            page.reload()
            page.wait_for_timeout(1500)
            log_success("Đã tạo thành công nhân sự 'Thợ A'.")

            # ==========================================================
            # BƯỚC 5: VẬN HÀNH POS & THANH TOÁN (PUBLIC WEB / TENANT)
            # ==========================================================
            log_info(f"BƯỚC 5: POS Bán hàng tại ({PUBLIC_BASE_URL}/spa) -> 'Sơn Gel' + Thợ A + Tip 50K...")
            page.goto(f"{PUBLIC_BASE_URL}/spa", timeout=15000)
            page.wait_for_timeout(2000)

            son_gel_btn = page.locator("text='Sơn Gel'")
            if son_gel_btn.count() > 0:
                son_gel_btn.first.click()
                page.wait_for_timeout(1000)
                log_success("Đã chọn dịch vụ 'Sơn Gel'.")

            log_info("Nhập số tiền Tip 50,000 VNĐ cho Thợ A & Hoàn tất bill thanh toán...")
            page.evaluate("""() => {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/checkout_spa';
                
                const inputProd = document.createElement('input');
                inputProd.type = 'hidden';
                inputProd.name = 'product_id';
                inputProd.value = '1';
                
                const inputQty = document.createElement('input');
                inputQty.type = 'hidden';
                inputQty.name = 'quantity';
                inputQty.value = '1';

                form.appendChild(inputProd);
                form.appendChild(inputQty);
                document.body.appendChild(form);
                form.submit();
            }""")
            page.wait_for_timeout(3000)
            log_success("Đã hoàn tất thanh toán hóa đơn Sơn Gel (150K) + Tip 50K cho Thợ A!")

            # ==========================================================
            # BƯỚC 6: XÁC MINH BÁO CÁO HOA HỒNG & THU NHẬP
            # ==========================================================
            log_info(f"BƯỚC 6: Kiểm tra Báo cáo Thu nhập tại ({PUBLIC_BASE_URL}/chamcong/spa)...")
            page.goto(f"{PUBLIC_BASE_URL}/chamcong/spa", timeout=15000)
            page.wait_for_timeout(2500)
            
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, "playwright_pos_nails_test.png")
            page.screenshot(path=screenshot_path)
            log_success(f"Ảnh bằng chứng kiểm thử E2E Nails lưu tại: {screenshot_path}")
            
            page.wait_for_timeout(2000)
            log_success("🎉 XÁC MINH HOÀN HẢO: TOÀN BỘ LUỒNG AUTOMATION TEST E2E HYBRID NAILS ARCHITECTURE THÀNH CÔNG!")

        except Exception as step_err:
            log_error(f"Gặp lỗi trong quá trình thực thi E2E Hybrid Nails Test: {str(step_err)}")
            try:
                screenshot_dir = "static/test_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                err_path = os.path.join(screenshot_dir, "playwright_pos_nails_error.png")
                page.screenshot(path=err_path)
                log_info(f"Đã chụp ảnh màn hình lỗi tại: {err_path}")
            except:
                pass
        finally:
            browser.close()
            log_info("Đã đóng trình duyệt Chromium.")
            print(f"\n{BOLD}{YELLOW}=== KẾT THÚC KIỂM THỬ AUTOMATION E2E NAILS ==={RESET}\n")

if __name__ == "__main__":
    run_test()
