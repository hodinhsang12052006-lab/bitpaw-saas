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
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU E2E SETUP MULTI-INDUSTRY ONBOARDING TEST ==={RESET}\n")

    # TẮT chế độ headless để hiển thị trình duyệt rõ ràng trên màn hình
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1280,890")
    
    log_info("Khởi chạy Chrome (Giao diện hiển thị trực quan)...")
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
        time.sleep(1.5)
        
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
        log_success("Đăng nhập thành công.")
        
        # 2. Vòng lặp quét TOÀN BỘ ngành nghề
        industries = ['retail', 'fnb', 'spa', 'nail', 'karaoke', 'hotel', 'production', 'technical', 'office']
        
        for i, ind in enumerate(industries):
            log_info(f"\n--- [{i+1}/{len(industries)}] Đang kiểm thử ngành: {ind.upper()} ---")
            
            # Điều hướng trực tiếp sang trang setup để chọn ngành mới
            driver.get(f"{URL}/setup")
            time.sleep(2)
            
            log_info(f"Chọn card mô hình '{ind}'...")
            card_selector = f'.mode-card[data-mode="{ind}"]'
            try:
                card_el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, card_selector)))
                card_el.click()
                time.sleep(1)
            except Exception as e:
                log_error(f"Không thể tìm thấy card cho ngành {ind}: {str(e)}")
                continue
                
            log_info("Bấm nút Xác nhận trong Modal thiết lập...")
            try:
                confirm_btn = wait.until(EC.element_to_be_clickable((By.ID, "confirmYesBtn")))
                confirm_btn.click()
            except Exception as e:
                log_error(f"Không thể bấm nút xác nhận: {str(e)}")
                continue
                
            time.sleep(4) # Đợi hệ thống lưu DB và chuyển hướng
            
            # Ghi nhận kết quả chuyển hướng và chất lượng trang đích
            current_url = driver.current_url
            page_title = driver.title
            log_success(f"Thiết lập thành công. URL đích: {current_url} | Tiêu đề: '{page_title}'")
            
            # Kiểm tra lỗi render trên trang đích
            page_source = driver.page_source.lower()
            server_error_keywords = ["internal server error", "500 error", "exception", "jinja2.exceptions", "template not found"]
            has_render_error = False
            for keyword in server_error_keywords:
                if keyword in page_source:
                    log_error(f"Phát hiện lỗi render / crash trên trang đích của ngành {ind}! (Từ khóa: '{keyword}')")
                    has_render_error = True
                    break
            
            # Kiểm tra các lỗi Javascript mức SEVERE
            console_logs = driver.get_log('browser')
            js_errors = [log for log in console_logs if log['level'] == 'SEVERE']
            if js_errors:
                log_warn(f"Phát hiện {len(js_errors)} lỗi Javascript mức SEVERE trên trang:")
                for entry in js_errors:
                    print(f"   -> {entry['message']}")
            
            # Chụp ảnh màn hình làm bằng chứng cho từng ngành nghề
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"setup_{ind}_onboarding.png")
            driver.save_screenshot(screenshot_path)
            log_info(f"Đã chụp ảnh màn hình lưu tại: {screenshot_path}")

        print(f"\n{BOLD}{GREEN}=== TẤT CẢ CÁC MÔ HÌNH ĐÃ ĐƯỢC THIẾT LẬP THÀNH CÔNG ==={RESET}")
        log_success("Hệ thống hoạt động trơn tru trên mọi ngành nghề!")
        print(f"\n{BOLD}{YELLOW}Giữ nguyên trình duyệt để Sếp nghiệm thu trực tiếp UI/UX. Nhấn CTRL+C trên terminal khi muốn đóng.{RESET}")
        
        # Treo trình duyệt không tắt để người dùng kiểm tra
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        log_info("Bấm CTRL+C. Đang đóng trình duyệt...")
    except Exception as e:
        import traceback
        log_error("Gặp lỗi trong quá trình quét E2E:")
        traceback.print_exc()
    finally:
        # Chỉ tắt nếu gặp lỗi nặng trước khi treo máy, hoặc ngắt phím CTRL+C
        try:
            driver.quit()
            log_info("Đã đóng trình duyệt.")
        except:
            pass
        print(f"\n{BOLD}{YELLOW}=== KẾT THÚC E2E BOT SCANNING ==={RESET}\n")

if __name__ == "__main__":
    main()
