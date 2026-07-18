import sys
import time
import os
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
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU KIỂM THỬ TỰ ĐỘNG LOGIN E2E (PLAYWRIGHT) ==={RESET}\n")
    
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
            # 1. Truy cập vào đường link Login
            target_url = f"{URL}/login"
            log_info(f"Bước 1: Điều hướng tới trang đăng nhập: {target_url}")
            page.goto(target_url, timeout=15000)
            
            # 2. Đợi trang Login load xong (chờ form login và trường email)
            page.wait_for_selector("#loginFormElement", timeout=10000)
            log_success("Trang đăng nhập đã tải thành công (#loginFormElement đã xuất hiện).")
            
            # 3. Click vào nút ngôn ngữ US (button[onclick="setLang('en')"])
            log_info("Bước 2: Click nút chuyển ngôn ngữ US (tiếng Anh)...")
            us_btn = page.locator('button[onclick="setLang(\'en\')"]')
            
            if us_btn.count() > 0:
                us_btn.click()
                log_info("Đã click nút chuyển ngôn ngữ US. Đang chờ DOM cập nhật...")
                page.wait_for_timeout(1000) # Đợi 1 giây để JS chạy setLang
                
                # Xác minh văn bản chào mừng được dịch
                welcome_text = page.locator("#txt_welcome").text_content().strip()
                log_info(f"Văn bản chào mừng hiện tại: '{welcome_text}'")
                if "System Activation Hub" in welcome_text:
                    log_success("XÁC MINH ĐA NGÔN NGỮ THÀNH CÔNG: Giao diện đã được dịch sang tiếng Anh.")
                else:
                    log_warn("Văn bản chào mừng chưa được dịch hoặc dùng chuỗi dịch khác.")
            else:
                log_error("LỖI: Không tìm thấy nút chuyển ngôn ngữ US (button[onclick=\"setLang('en')\"])!")
            
            # 4. Tự động điền Email và Password admin vào form
            log_info("Bước 3: Tự động điền thông tin tài khoản Admin...")
            page.fill("input#loginEmail", ADMIN_EMAIL)
            page.fill("input#loginPassword", ADMIN_PASSWORD)
            log_success("Đã điền Email và Password thành công.")
            
            # 5. Bấm nút đăng nhập (#btnLogin)
            log_info("Bước 4: Click nút Đăng nhập (#btnLogin)...")
            submit_btn = page.locator("#btnLogin")
            submit_btn.click()
            log_info("Đã click nút đăng nhập. Chờ chuyển hướng...")
            
            # 6. Đợi hệ thống xử lý và verify xem có chuyển hướng thành công
            page.wait_for_timeout(3000) # Đợi xử lý
            
            try:
                page.wait_for_url(lambda url: "/login" not in url, timeout=10000)
                current_url = page.url
                log_success(f"Đăng nhập thành công! Đã chuyển hướng sang URL mới: {current_url}")
                
                if any(path in current_url for path in ["/pos", "/dashboard", "/super_admin", "/portal", "/setup"]):
                    log_success("XÁC MINH THÀNH CÔNG: Đã chuyển hướng vào không gian làm việc chính.")
                else:
                    log_warn(f"Chuyển hướng đến URL không xác định: {current_url}")
            except Exception as url_err:
                log_error(f"LỖI CHUYỂN HƯỚNG: Trang không chuyển hướng sau đăng nhập. URL hiện tại: {page.url}")
                
            # Chụp ảnh màn hình làm bằng chứng
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, "playwright_login_test.png")
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
                page.screenshot(path=os.path.join(screenshot_dir, "playwright_login_error.png"))
                log_info("Đã chụp ảnh màn hình lỗi tại static/test_screenshots/playwright_login_error.png")
            except:
                pass
        finally:
            browser.close()
            log_info("Đã đóng trình duyệt.")
            print(f"\n{BOLD}{YELLOW}=== KẾT THÚC KIỂM THỬ LOGIN E2E ==={RESET}\n")

if __name__ == "__main__":
    run_test()
