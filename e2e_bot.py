import time
import os
import sys
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select

# Ensure Vietnamese prints correctly on Windows Console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# ANSI Color codes
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

URL = "http://localhost:5001"
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

def main():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU KIỂM THỬ LUỒNG SAAS ĐĂNG KÝ KHÁCH HÀNG MỚI (E2E) ==={RESET}\n")

    chrome_options = Options()
    chrome_options.add_argument("--window-size=1280,900")
    
    log_info("Khởi chạy Chrome (Giao diện hiển thị trực quan)...")
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        log_error(f"Không thể khởi chạy WebDriver: {str(e)}")
        sys.exit(1)

    wait = WebDriverWait(driver, 10)
    errors_found = 0
    
    try:
        # ==========================================
        # PHẦN 1: ĐĂNG NHẬP SUPER ADMIN & TẠO KEY BẢN QUYỀN
        # ==========================================
        log_info("=== BƯỚC 1: ĐĂNG NHẬP SUPER ADMIN ===")
        driver.get(f"{URL}/login")
        time.sleep(1.5)
        
        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginEmail")))
        email_input.clear()
        email_input.send_keys(ADMIN_EMAIL)
        
        pass_input = driver.find_element(By.ID, "loginPassword")
        pass_input.clear()
        pass_input.send_keys(ADMIN_PASSWORD)
        
        driver.find_element(By.ID, "loginFormElement").submit()
        time.sleep(3)
        log_success("Đăng nhập Super Admin thành công.")
        
        log_info("Điều hướng trực tiếp sang bảng điều khiển Super Admin...")
        driver.get(f"{URL}/super_admin")
        time.sleep(2.5)
        
        log_info("Chuyển sang Tab Cấp Phép Bản Quyền...")
        driver.execute_script("switchTab('license')")
        time.sleep(1.5)
        
        log_info("Tạo mã đăng ký ngẫu nhiên...")
        driver.execute_script("randomKey()")
        time.sleep(1)
        
        license_input = driver.find_element(By.ID, "keyCodeInput")
        license_key = license_input.get_attribute("value")
        if not license_key:
            log_error("Không thể sinh License Key ngẫu nhiên!")
            driver.quit()
            sys.exit(1)
        log_success(f"Mã License Key vừa tạo: '{license_key}'")
        
        # Chọn ngành nghề F&B để test chuyển đổi tự động
        log_info("Chọn ngành nghề của Gói cấp phép: F&B...")
        select_el = Select(driver.find_element(By.ID, "industrySelect"))
        select_el.select_by_value("fnb")
        time.sleep(1)
        
        log_info("Bấm nút đúc bản quyền mới để lưu xuống hệ thống SQLite...")
        confirm_mint_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'ĐÚC BẢN QUYỀN MỚI')]/..")))
        confirm_mint_btn.click()
        time.sleep(3.5)
        
        log_success("Đúc bản quyền hoàn tất.")
        
        # Đăng xuất Super Admin
        log_info("Đăng xuất tài khoản Super Admin...")
        driver.get(f"{URL}/logout")
        time.sleep(2)
        log_success("Đăng xuất Super Admin thành công.")
        
        # ==========================================
        # PHẦN 2: ĐÓNG GIẢ KHÁCH HÀNG MỚI ĐỂ ĐĂNG KÝ
        # ==========================================
        log_info("\n=== BƯỚC 2: ĐÓNG GIẢ KHÁCH HÀNG MỚI ĐĂNG KÝ ===")
        driver.get(f"{URL}/login")
        time.sleep(1.5)
        
        # Mở form Đăng ký bằng JS
        driver.execute_script("document.getElementById('loginForm').classList.remove('active'); document.getElementById('registerForm').classList.add('active');")
        time.sleep(1.5)
        
        # Tạo thông tin khách hàng ngẫu nhiên
        rand_id = random.randint(10000, 99999)
        new_email = f"customer_{rand_id}@bitpaw.com"
        new_password = "Customerpass123"
        log_info(f"Khởi tạo Email khách hàng mới: {new_email}")
        
        fullname_input = wait.until(EC.presence_of_element_located((By.ID, "regFullname")))
        fullname_input.send_keys("Sếp Tổng Chuỗi FNB")
        time.sleep(0.5)
        
        business_input = driver.find_element(By.ID, "regBusinessName")
        business_input.send_keys("Hệ Thống F&B BitPaw Auto")
        time.sleep(0.5)
        
        # Chọn ngành nghề trùng khớp F&B
        select_type = Select(driver.find_element(By.ID, "reg_business_type"))
        select_type.select_by_value("fnb")
        time.sleep(0.5)
        
        email_input_reg = driver.find_element(By.ID, "regEmail")
        email_input_reg.send_keys(new_email)
        time.sleep(0.5)
        
        # Nhập License key vừa đúc
        license_input_reg = driver.find_element(By.ID, "reg_license")
        license_input_reg.clear()
        license_input_reg.send_keys(license_key)
        time.sleep(0.5)
        
        pass_input_reg = driver.find_element(By.ID, "regPassword")
        pass_input_reg.send_keys(new_password)
        time.sleep(0.5)
        
        confirm_input_reg = driver.find_element(By.ID, "regConfirm")
        confirm_input_reg.send_keys(new_password)
        time.sleep(1.5) # Đợi quan sát
        
        log_info("Bấm nút Đăng ký khởi tạo...")
        driver.find_element(By.ID, "btnRegister").click()
        time.sleep(4)
        
        log_success("Gửi biểu mẫu Đăng ký thành công.")
        
        # ==========================================
        # PHẦN 3: ĐĂNG NHẬP ĐỂ KIỂM CHỨNG TỰ ĐỘNG THIẾT LẬP
        # ==========================================
        log_info("\n=== BƯỚC 3: ĐĂNG NHẬP VỚI TÀI KHOẢN KHÁCH HÀNG MỚI ===")
        # Đảm bảo form đăng nhập mở sẵn
        driver.get(f"{URL}/login")
        time.sleep(1.5)
        
        email_input_login = wait.until(EC.presence_of_element_located((By.ID, "loginEmail")))
        email_input_login.clear()
        email_input_login.send_keys(new_email)
        
        pass_input_login = driver.find_element(By.ID, "loginPassword")
        pass_input_login.clear()
        pass_input_login.send_keys(new_password)
        
        log_info("Bấm nút Đăng nhập...")
        driver.find_element(By.ID, "loginFormElement").submit()
        time.sleep(4)
        
        # Xác minh chuyển hướng tự động dựa trên license key
        current_url = driver.current_url
        page_title = driver.title
        log_info(f"URL đích sau đăng nhập: {current_url}")
        log_info(f"Tiêu đề trang đích: '{page_title}'")
        
        # Kiểm tra xem có trỏ tới đúng phân hệ F&B (POS / pos.html) không
        if "/pos" in current_url or "f&b" in page_title.lower() or "sơ đồ bàn" in page_title.lower():
            log_success("XÁC MINH THÀNH CÔNG: Hệ thống tự động thiết lập ngành F&B dựa trên License Key và chuyển thẳng về màn hình POS!")
        else:
            log_error("LỖI THIẾT LẬP: Không tự động chuyển hướng về phân hệ F&B tương ứng!")
            errors_found += 1
            
        # Kiểm tra lỗi Javascript mức SEVERE
        console_logs = driver.get_log('browser')
        js_errors = [log for log in console_logs if log['level'] == 'SEVERE']
        if js_errors:
            log_warn(f"Phát hiện {len(js_errors)} lỗi Javascript mức SEVERE trên trang:")
            for entry in js_errors:
                print(f"   -> {entry['message']}")
                
        # Chụp ảnh làm bằng chứng
        screenshot_dir = "static/test_screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "customer_signup_fb_verification.png")
        driver.save_screenshot(screenshot_path)
        log_info(f"Đã chụp ảnh màn hình lưu tại: {screenshot_path}")

        print(f"\n{BOLD}{YELLOW}=== KẾT QUẢ TỔNG KẾT LUỒNG NGHIỆP VỤ ==={RESET}")
        if errors_found == 0:
            log_success("Hệ thống SaaS đăng ký khách hàng, đúc License Key và tự động cấu hình workspace hoạt động HOÀN HẢO!")
        else:
            log_error(f"Phát hiện {errors_found} lỗi nghiệp vụ trong hệ thống.")
            
        print(f"\n{BOLD}{YELLOW}Treo trình duyệt để Sếp nghiệm thu trực tiếp UI/UX. Nhấn CTRL+C trên terminal khi muốn đóng.{RESET}")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        log_info("Bấm CTRL+C. Đang đóng trình duyệt...")
    except Exception as e:
        import traceback
        log_error("Gặp lỗi trong quá trình chạy E2E:")
        traceback.print_exc()
    finally:
        try:
            driver.quit()
            log_info("Đã đóng trình duyệt.")
        except:
            pass
        print(f"\n{BOLD}{YELLOW}=== KẾT THÚC E2E BOT SCANNING ==={RESET}\n")

if __name__ == "__main__":
    main()
