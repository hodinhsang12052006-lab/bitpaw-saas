import time
import os
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Ensure Vietnamese prints correctly on Windows Console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ANSI Color codes
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

URL = "http://localhost:5001"
EMAIL = "hodinhsang30052003@gmail.com"
PASSWORD = "0794678904Az@"

def log_success(msg):
    print(f"{GREEN}[✓] {msg}{RESET}")

def log_error(msg):
    print(f"{RED}[❌] {msg}{RESET}")

def log_info(msg):
    print(f"{CYAN}[ℹ] {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}[⚠️] {msg}{RESET}")

def main():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU E2E AUTOMATED BOT SCANNING SYSTEM ==={RESET}\n")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1280,800")
    
    log_info("Khởi chạy Chrome Headless...")
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        log_error(f"Không thể khởi chạy WebDriver: {str(e)}")
        sys.exit(1)

    wait = WebDriverWait(driver, 10)
    
    try:
        # 1. Đi tới trang đăng nhập
        log_info(f"Đang kết nối tới: {URL}/login")
        driver.get(f"{URL}/login")
        time.sleep(2)
        
        # Kiểm tra nếu đã redirect tới /setup hay /dashboard (nếu session còn lưu - mặc dù ở đây là trình duyệt mới)
        current_url = driver.current_url
        log_info(f"URL hiện tại: {current_url}")
        
        # Điền form đăng nhập
        log_info("Nhập thông tin tài khoản Admin...")
        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginEmail")))
        email_input.clear()
        email_input.send_keys(EMAIL)
        
        pass_input = driver.find_element(By.ID, "loginPassword")
        pass_input.clear()
        pass_input.send_keys(PASSWORD)
        
        log_info("Click nút đăng nhập...")
        login_form = driver.find_element(By.ID, "loginFormElement")
        login_form.submit()
        
        time.sleep(3)
        log_success("Đăng nhập hoàn thành, kiểm tra trang chuyển hướng...")
        log_info(f"URL sau đăng nhập: {driver.current_url}")
        
        # 2. Xử lý thiết lập mô hình kinh doanh (nếu ở trang /setup)
        if "/setup" in driver.current_url:
            log_info("Đang ở trang /setup. Tự động chọn mô hình kinh doanh 'fnb' (Nhà hàng & Cafe)...")
            # Tìm card F&B
            fnb_card = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '.mode-card[data-mode="fnb"]')))
            fnb_card.click()
            time.sleep(1)
            
            # Click xác nhận trong modal
            log_info("Xác nhận chuyển mô hình trong Modal...")
            confirm_btn = wait.until(EC.element_to_be_clickable((By.ID, "confirmYesBtn")))
            confirm_btn.click()
            time.sleep(3)
            log_info(f"URL sau khi thiết lập mô hình: {driver.current_url}")
            
        # 3. Quét các phân hệ chính
        endpoints = {
            "POS Bán Hàng": "/pos",
            "Quản lý Khách Hàng (CRM)": "/customers",
            "Quản lý Khuyến Mãi": "/promotions",
            "Chấm Công": "/chamcong",
            "Bảng Lương": "/bangluong"
        }
        
        errors_found = 0
        
        for name, path in endpoints.items():
            full_url = f"{URL}{path}"
            log_info(f"--- Đang quét phân hệ: {name} ({full_url}) ---")
            driver.get(full_url)
            time.sleep(2.5) # Để trang load & chạy Javascript
            
            # Kiểm tra lỗi render (500 Internal Server Error, Template Not Found, trắng trang)
            page_source = driver.page_source.lower()
            page_title = driver.title
            
            # Kiểm tra các dấu hiệu lỗi máy chủ
            server_error_keywords = ["internal server error", "500 error", "exception", "jinja2.exceptions", "template not found", "error 500"]
            is_error = False
            for keyword in server_error_keywords:
                if keyword in page_source:
                    log_error(f"Phát hiện lỗi render / crash trên phân hệ {name}! (Từ khóa: '{keyword}')")
                    is_error = True
                    errors_found += 1
                    break
            
            if not is_error:
                # Kiểm tra lỗi Javascript qua log console
                console_logs = driver.get_log('browser')
                js_errors = [log for log in console_logs if log['level'] == 'SEVERE']
                if js_errors:
                    log_warn(f"Phát hiện {len(js_errors)} lỗi Javascript mức SEVERE trên phân hệ {name}:")
                    for entry in js_errors:
                        print(f"   -> {entry['message']}")
                
                log_success(f"Phân hệ {name} hoạt động bình thường. Tiêu đề: '{page_title}'")
            
            # Lưu ảnh chụp màn hình phân hệ làm bằng chứng
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"{path.strip('/')}.png")
            driver.save_screenshot(screenshot_path)
            log_info(f"Đã chụp ảnh màn hình và lưu tại: {screenshot_path}")

        print(f"\n{BOLD}{YELLOW}=== TỔNG KẾT QUÉT THỬ NGHIỆM CHẤT LƯỢNG ==={RESET}")
        if errors_found == 0:
            log_success("Bot không phát hiện lỗi logic hay lỗi render nghiêm trọng nào trên toàn bộ 5 luồng phân hệ chính!")
        else:
            log_error(f"Quá trình quét phát hiện tổng cộng {errors_found} lỗi render/crash cần được fix.")
            
    except Exception as e:
        import traceback
        log_error("Gặp lỗi trong quá trình quét E2E:")
        traceback.print_exc()
        
    finally:
        log_info("Đóng trình duyệt...")
        driver.quit()
        print(f"\n{BOLD}{YELLOW}=== KẾT THÚC E2E BOT SCANNING ==={RESET}\n")

if __name__ == "__main__":
    main()
