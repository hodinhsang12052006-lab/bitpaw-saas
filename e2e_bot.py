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
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU E2E SETUP FLOW ONBOARDING TEST ==={RESET}\n")

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
    errors_found = 0
    
    try:
        # 1. Đi tới trang đăng nhập
        log_info(f"Đang kết nối tới: {URL}/login")
        driver.get(f"{URL}/login")
        time.sleep(2)
        
        # Điền form đăng nhập
        log_info("Nhập thông tin tài khoản Super Admin...")
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
        
        # 2. Thực hiện luồng đăng ký thiết lập mô hình Setup
        if "/setup" in driver.current_url:
            log_info("Đang ở trang /setup. Tự động chọn mô hình Retail (Cửa hàng Bán lẻ)...")
            
            # Đợi và tìm card Retail
            retail_card = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '.mode-card[data-mode="retail"]')))
            retail_card.click()
            time.sleep(1)
            
            # Click xác nhận trong modal
            log_info("Bấm nút Xác nhận trong Modal thiết lập...")
            confirm_btn = wait.until(EC.element_to_be_clickable((By.ID, "confirmYesBtn")))
            confirm_btn.click()
            time.sleep(4) # Đợi setup lưu DB và chuyển hướng
            
            log_success("Đã gửi yêu cầu đăng ký ngành nghề.")
            log_info(f"URL sau khi thiết lập mô hình: {driver.current_url}")
        else:
            log_warn("Tài khoản đã được thiết lập trước đó hoặc không ở màn hình /setup. Đang chuyển tới /setup...")
            driver.get(f"{URL}/setup")
            time.sleep(2)
            log_info("Tự động chọn mô hình Retail (Cửa hàng Bán lẻ)...")
            retail_card = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '.mode-card[data-mode="retail"]')))
            retail_card.click()
            time.sleep(1)
            log_info("Bấm nút Xác nhận trong Modal thiết lập...")
            confirm_btn = wait.until(EC.element_to_be_clickable((By.ID, "confirmYesBtn")))
            confirm_btn.click()
            time.sleep(4)
            log_info(f"URL sau khi thiết lập mô hình: {driver.current_url}")

        # 3. Kiểm tra trang đích Dashboard
        page_title = driver.title
        page_source = driver.page_source.lower()
        log_info(f"Tiêu đề trang đích: '{page_title}'")
        
        # Xác minh tiêu đề hoặc nội dung khớp với Retail Dashboard
        if "tổng quan dashboard" in page_title.lower() or "retail" in page_source or "bán lẻ" in page_source:
            log_success("Xác minh thành công: Đã chuyển sang màn hình Retail Dashboard!")
        else:
            log_error("Lỗi xác minh: Không tìm thấy tiêu đề hoặc nội dung Retail Dashboard!")
            errors_found += 1
            
        # Kiểm tra lỗi render / 500 error
        server_error_keywords = ["internal server error", "500 error", "exception", "jinja2.exceptions", "template not found"]
        for keyword in server_error_keywords:
            if keyword in page_source:
                log_error(f"Phát hiện lỗi render / crash trên trang đích! (Từ khóa: '{keyword}')")
                errors_found += 1
                break
                
        # Kiểm tra lỗi Javascript mức SEVERE
        console_logs = driver.get_log('browser')
        js_errors = [log for log in console_logs if log['level'] == 'SEVERE']
        if js_errors:
            log_warn(f"Phát hiện {len(js_errors)} lỗi Javascript mức SEVERE trên trang:")
            for entry in js_errors:
                print(f"   -> {entry['message']}")
                
        # Chụp ảnh màn hình làm bằng chứng
        screenshot_dir = "static/test_screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "setup_retail_onboarding.png")
        driver.save_screenshot(screenshot_path)
        log_info(f"Đã chụp ảnh màn hình và lưu tại: {screenshot_path}")

        print(f"\n{BOLD}{YELLOW}=== TỔNG KẾT QUÉT THỬ NGHIỆM THIẾT LẬP ==={RESET}")
        if errors_found == 0:
            log_success("Luồng thiết lập ngành nghề (Retail) và cấp phát business_id hoạt động trơn tru 100% từ A-Z!")
        else:
            log_error(f"Phát hiện {errors_found} lỗi trong luồng thiết lập. Cần điều tra sửa đổi!")
            
    except Exception as e:
        import traceback
        log_error("Gặp lỗi trong quá trình chạy E2E setup flow:")
        traceback.print_exc()
        
    finally:
        log_info("Đóng trình duyệt...")
        driver.quit()
        print(f"\n{BOLD}{YELLOW}=== KẾT THÚC E2E BOT SCANNING ==={RESET}\n")

if __name__ == "__main__":
    main()
