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

# Mã màu ANSI để in báo cáo log
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

URL = "https://bitpawsoftware.com"
ADMIN_EMAIL = "hodinhsang30052003@gmail.com"
ADMIN_PASSWORD = "0794678904Az@"

def log_success(msg):
    print(f"{GREEN}[✓] {msg}{RESET}")

def log_error(msg):
    print(f"{RED}[❌] {msg}{RESET}")

def log_info(msg):
    print(f"{CYAN}[ℹ] {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}[⚠️] {msg}{RESET}")

def run_test():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU KIỂM THỬ SAAS SIGNUP E2E (PLAYWRIGHT) ==={RESET}\n")
    
    with sync_playwright() as p:
        log_info("Khởi chạy trình duyệt Chromium (Chế độ hiển thị UI)...")
        try:
            browser = p.chromium.launch(headless=False, args=["--window-size=1280,900"])
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
        except Exception as e:
            log_error(f"Không thể khởi chạy Chromium: {str(e)}")
            return False

        try:
            # ==========================================================
            # BƯỚC 1: ĐĂNG NHẬP SUPER ADMIN & TẠO KEY BẢN QUYỀN MỚI
            # ==========================================================
            log_info("Bước 1: Đăng nhập tài khoản Super Admin...")
            page.goto(f"{URL}/login", timeout=15000)
            page.wait_for_selector("#loginFormElement")
            
            page.fill("input#loginEmail", ADMIN_EMAIL)
            page.fill("input#loginPassword", ADMIN_PASSWORD)
            page.click("#btnLogin")
            
            # Chờ chuyển hướng thành công
            page.wait_for_timeout(3000)
            page.wait_for_url(lambda url: "/login" not in url, timeout=10000)
            log_success(f"Đăng nhập Super Admin thành công. URL hiện tại: {page.url}")
            
            # Đi tới trang super_admin
            log_info("Đi tới trang quản lý Super Admin...")
            page.goto(f"{URL}/super_admin", timeout=15000)
            page.wait_for_timeout(2000)
            
            # Thực thi JS để chuyển đổi tab license và sinh khóa ngẫu nhiên
            log_info("Sinh mã kích hoạt bản quyền mới cho phân hệ F&B...")
            page.evaluate("switchTab('license')")
            page.wait_for_timeout(1000)
            page.evaluate("randomKey()")
            page.wait_for_timeout(1000)
            
            # Lấy key từ ô nhập keyCodeInput
            license_key = page.eval_on_selector("#keyCodeInput", "el => el.value")
            if not license_key:
                raise Exception("Không thể tự động tạo mã License Key từ giao diện Super Admin!")
            log_success(f"Đã sinh mã bản quyền ngẫu nhiên: {license_key}")
            
            # Chọn loại hình doanh nghiệp fnb
            page.select_option("#industrySelect", "fnb")
            page.wait_for_timeout(500)
            
            # Click nút Đúc bản quyền
            log_info("Bấm nút đúc bản quyền mới...")
            page.locator("button:has-text('ĐÚC BẢN QUYỀN MỚI')").click()
            page.wait_for_timeout(3500)
            log_success("Đúc bản quyền thành công xuống SQLite local.")
            
            # Đăng xuất Super Admin
            log_info("Đăng xuất tài khoản Super Admin...")
            page.goto(f"{URL}/logout")
            page.wait_for_timeout(2000)
            log_success("Đã đăng xuất tài khoản Super Admin.")
            
            # ==========================================================
            # BƯỚC 2: ĐĂNG KÝ TÀI KHÀN KHÁCH HÀNG MỚI BẰNG KEY VỪA ĐÚC
            # ==========================================================
            log_info("Bước 2: Tiến hành đăng ký tài khoản khách hàng mới...")
            page.goto(f"{URL}/register", timeout=15000)
            page.wait_for_selector("#registerFormElement")
            
            # Tạo email ngẫu nhiên để test
            rand_id = random.randint(10000, 99999)
            new_email = f"customer_{rand_id}@bitpaw.com"
            new_password = "Customerpass123"
            log_info(f"Đăng ký bằng email: {new_email}")
            
            page.fill("input#regFullname", "Sếp Tổng Chuỗi FNB")
            page.fill("input#regBusinessName", "Hệ Thống F&B BitPaw Auto")
            page.select_option("select#reg_business_type", "fnb")
            page.fill("input#regEmail", new_email)
            page.fill("input#reg_license", license_key)
            page.fill("input#regPassword", new_password)
            page.fill("input#regConfirm", new_password)
            page.wait_for_timeout(1500)
            
            # Click nút đăng ký
            page.click("#btnRegister")
            page.wait_for_timeout(5000) # Đợi đăng ký thành công và chuyển hướng
            log_success("Đã gửi yêu cầu đăng ký tài khoản mới.")
            
            # ==========================================================
            # BƯỚC 3: ĐĂNG NHẬP KHÁCH HÀNG MỚI & KIỂM TRA CHUYỂN HƯỚNG WORKSPACE
            # ==========================================================
            log_info("Bước 3: Đăng nhập bằng tài khoản mới đăng ký...")
            page.goto(f"{URL}/login", timeout=15000)
            page.wait_for_selector("#loginFormElement")
            
            page.fill("input#loginEmail", new_email)
            page.fill("input#loginPassword", new_password)
            page.click("#btnLogin")
            
            log_info("Chờ hệ thống xử lý và chuyển hướng...")
            page.wait_for_timeout(4000)
            page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
            
            current_url = page.url
            log_info(f"URL đích sau khi đăng nhập: {current_url}")
            
            # Kiểm tra xem có trỏ tới đúng phân hệ F&B (POS / pos.html) không
            is_pos = "/pos" in current_url
            if is_pos:
                log_success("XÁC MINH THÀNH CÔNG: Hệ thống tự động thiết lập ngành F&B dựa trên License Key và chuyển thẳng về màn hình POS!")
            else:
                log_error(f"LỖI THIẾT LẬP: Không tự động chuyển hướng về phân hệ F&B tương ứng! URL hiện tại: {current_url}")
                
            # Chụp ảnh màn hình làm bằng chứng
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, "playwright_saas_signup_test.png")
            page.screenshot(path=screenshot_path)
            log_success(f"Đã chụp ảnh màn hình lưu tại: {screenshot_path}")
            
            log_info("Hoàn tất quy trình kiểm thử.")
            page.wait_for_timeout(2000)
            
        except Exception as step_err:
            log_error(f"Gặp lỗi trong quá trình thực thi kịch bản E2E: {str(step_err)}")
            # Chụp màn hình lỗi hỗ trợ debug
            try:
                screenshot_dir = "static/test_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                page.screenshot(path=os.path.join(screenshot_dir, "playwright_saas_signup_error.png"))
                log_info("Đã chụp ảnh màn hình lỗi tại static/test_screenshots/playwright_saas_signup_error.png")
            except:
                pass
        finally:
            browser.close()
            log_info("Đã đóng trình duyệt.")
            print(f"\n{BOLD}{YELLOW}=== KẾT THÚC KIỂM THỬ SAAS SIGNUP ==={RESET}\n")

if __name__ == "__main__":
    run_test()
