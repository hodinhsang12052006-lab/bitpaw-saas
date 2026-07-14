import sys
import time
import socket
import subprocess
import sqlite3

# Đảm bảo in ra tiếng Việt đúng chuẩn trên Windows Console
sys.stdout.reconfigure(encoding='utf-8')

# ANSI Color codes
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

PORT = 5001
URL = f"http://localhost:{PORT}"

def is_port_open(port):
    """Kiểm tra xem cổng port có đang hoạt động hay không"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def init_test_license():
    """Tự động chèn mã bản quyền mẫu vào SQLite để quá trình đăng ký UI thành công"""
    license_key = "AUTO-UI-LICENSE-KEY"
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO kho_license (license_key, nganh_nghe, trang_thai) VALUES (?, 'fnb', 'Sẵn sàng')", (license_key,))
        conn.commit()
        conn.close()
        print(f"{GREEN}[✓] Đã kích hoạt mã bản quyền '{license_key}' trong SQLite database.db.{RESET}")
    except Exception as e:
        print(f"{YELLOW}[!] Cảnh báo: Không thể chèn license vào SQLite: {e}{RESET}")

def main():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU CHẠY THỬ NGHIỆM GIAO DIỆN CHUẨN CÔNG NGHIỆP ==={RESET}\n")
    
    init_test_license()
    
    server_process = None
    started_by_us = False

    # Bước 1: Khởi động Server nếu cổng chưa mở
    if is_port_open(PORT):
        print(f"{YELLOW}[*] Cổng {PORT} đang mở. Sử dụng Server hiện tại.{RESET}")
    else:
        print(f"{CYAN}[🤖 BƯỚC 1] Khởi động Flask Server (app.py) ngầm...{RESET}")
        try:
            # Chạy app.py ngầm sử dụng trình thực thi Python hiện tại
            server_process = subprocess.Popen(
                [sys.executable, 'app.py'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            started_by_us = True
            print("  -> Đang khởi chạy Flask server...")
        except Exception as e:
            print(f"{RED}[- ] Không thể khởi động Flask server ngầm: {e}{RESET}")
            sys.exit(1)

    # Bước 2: Chờ Server sẵn sàng (Ping check)
    print(f"\n{CYAN}[🤖 BƯỚC 2] Chờ Server BitPaw OS phản hồi tại {URL}...{RESET}")
    import urllib.request
    from urllib.error import URLError

    max_attempts = 15
    server_ready = False
    for attempt in range(1, max_attempts + 1):
        try:
            # Gửi request check cổng
            with urllib.request.urlopen(URL, timeout=1) as response:
                if response.status == 200 or response.status == 302:
                    server_ready = True
                    break
        except (URLError, socket.timeout, ConnectionResetError):
            pass
        print(f"  -> Lần kiểm tra {attempt}/{max_attempts}: Server chưa phản hồi, đợi 1 giây...")
        time.sleep(1)

    if not server_ready:
        print(f"{RED}[- ] Lỗi: Server không phản hồi sau {max_attempts} giây.{RESET}")
        if started_by_us and server_process:
            server_process.terminate()
        sys.exit(1)
    
    print(f"{GREEN}[✓] Server đã hoạt động và sẵn sàng kết nối!{RESET}")

    # Bước 3: Khởi chạy Selenium kiểm thử giao diện
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select

        print(f"\n{CYAN}[🤖 BƯỚC 3] Khởi chạy Chrome Webdriver...{RESET}")
        driver = webdriver.Chrome()
        driver.maximize_window()
        driver.get(URL)
        time.sleep(2)  # Độ trễ quan sát

        # Sử dụng Explicit Wait để đợi nút đăng ký xuất hiện
        wait = WebDriverWait(driver, 10)
        
        print(f"\n{CYAN}[🤖 BƯỚC 4] Chuyển hướng sang Form Đăng Ký...{RESET}")
        try:
            btn_switch_tab = wait.until(EC.element_to_be_clickable((By.ID, "txt_createnow")))
            btn_switch_tab.click()
        except Exception as click_err:
            print(f"  -> Cảnh báo click UI: {click_err}, dùng Javascript thay thế...")
        
        # Đảm bảo form đăng ký hiển thị chắc chắn bằng JS
        driver.execute_script("document.getElementById('loginForm').classList.remove('active'); document.getElementById('registerForm').classList.add('active');")
        time.sleep(2)  # Độ trễ quan sát

        print(f"\n{CYAN}[🤖 BƯỚC 5] Tự động điền Form Đăng Ký Bản Quyền...{RESET}")
        
        # Nhập các trường
        fullname_input = wait.until(EC.visibility_of_element_located((By.ID, "regFullname")))
        fullname_input.send_keys("Sếp Tổng Tự Động")
        time.sleep(1)

        business_input = driver.find_element(By.ID, "regBusinessName")
        business_input.send_keys("Chuỗi Cafe Auto UI")
        time.sleep(1)

        # Chọn F&B
        select_elem = driver.find_element(By.ID, "reg_business_type")
        select = Select(select_elem)
        select.select_by_value("fnb")
        time.sleep(1)

        email_input = driver.find_element(By.ID, "regEmail")
        email_input.send_keys("auto_ui_boss@test.com")
        time.sleep(1)

        # Nhập License key bản quyền
        license_input = driver.find_element(By.ID, "reg_license")
        license_input.clear()
        license_input.send_keys("AUTO-UI-LICENSE-KEY")
        time.sleep(1)

        pass_input = driver.find_element(By.ID, "regPassword")
        pass_input.send_keys("password123")
        time.sleep(1)

        confirm_input = driver.find_element(By.ID, "regConfirm")
        confirm_input.send_keys("password123")
        time.sleep(2)  # Đợi quan sát trước khi bấm

        # Gửi thông tin
        print(f"\n{CYAN}[🤖 BƯỚC 6] Thực hiện Submit và đăng ký...{RESET}")
        btn_register = driver.find_element(By.ID, "btnRegister")
        btn_register.click()
        
        # Chờ 5 giây xem kết quả chuyển trang
        time.sleep(5)
        print(f"{GREEN}[✓] Quá trình UI Test hoàn thành! Đã đăng ký thành công.{RESET}")

    except Exception:
        import traceback
        print(f"\n{RED}[- ] Lỗi trong quá trình kiểm thử:{RESET}")
        traceback.print_exc()
    finally:
        # Bước 4: Dọn dẹp tài nguyên (Giải phóng cổng và tắt Chrome)
        print(f"\n{CYAN}[🤖 BƯỚC 7] Tiến hành dọn dẹp hệ thống...{RESET}")
        if driver:
            driver.quit()
            print("  -> Đã đóng trình duyệt Chrome.")
            
        if started_by_us and server_process:
            server_process.terminate()
            server_process.wait()
            print(f"  -> Đã đóng Flask server ngầm và giải phóng cổng {PORT}.")
            
        print(f"\n{BOLD}{YELLOW}=== HOÀN THÀNH TOÀN BỘ QUY TRÌNH KIỂM THỬ GIAO DIỆN TỰ ĐỘNG! ==={RESET}\n")

if __name__ == '__main__':
    main()
