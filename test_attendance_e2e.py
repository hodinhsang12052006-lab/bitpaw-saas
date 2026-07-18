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

def log_success(msg):
    print(f"{GREEN}[✓] {msg}{RESET}")

def log_error(msg):
    print(f"{RED}[❌] {msg}{RESET}")

def log_info(msg):
    print(f"{CYAN}[ℹ] {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}[⚠️] {msg}{RESET}")

def run_test():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU KIỂM THỬ E2E CHẤM CÔNG NHÂN VIÊN (PLAYWRIGHT) ==={RESET}\n")
    
    with sync_playwright() as p:
        log_info("Khởi chạy trình duyệt Chromium với cấu hình giả lập Thiết bị Camera & Định vị GPS...")
        try:
            # Bật camera giả lập
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    "--window-size=480,900"
                ]
            )
            
            # Khởi tạo ngữ cảnh với quyền định vị GPS và camera
            context = browser.new_context(
                viewport={"width": 450, "height": 850},
                permissions=["camera", "geolocation"],
                geolocation={"latitude": 10.762622, "longitude": 106.660172}
            )
            page = context.new_page()
        except Exception as e:
            log_error(f"Không thể khởi chạy Chromium: {str(e)}")
            return False

        try:
            # Intercept API Supabase để giả lập phản hồi thành công (mock)
            # Tránh lỗi Supabase RLS hoặc Key hết hạn khi chạy test
            log_info("Thiết lập hệ thống chặn và phản hồi Mock API Supabase...")
            
            # Mock truy vấn thông tin nhân sự employees
            page.route("**/rest/v1/employees*", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='[{"ma_nv": "NV001", "ho_ten": "Test Worker", "linh_vuc": "F&B", "chuc_vu": "Nhân viên", "avatar_url": ""}]'
            ))
            
            # Mock tải ảnh lên storage
            page.route("**/storage/v1/object/checkin_images*", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"Key": "checkin_images/test.jpg"}'
            ))
            
            # Mock chèn dữ liệu chấm công chamcong
            page.route("**/rest/v1/chamcong*", lambda route: route.fulfill(
                status=201,
                content_type="application/json",
                body='[]'
            ))

            # 1. Truy cập trực tiếp qua link Token Auto-Login của PawBook
            target_url = f"{URL}/app_nhanvien?token=NV001"
            log_info(f"Bước 1: Điều hướng tới Mini-App nhân sự: {target_url}")
            page.goto(target_url, timeout=15000)
            
            # 2. Chờ trang nhận diện đăng nhập từ URL
            page.wait_for_timeout(3000)
            
            # 3. Kiểm tra xem màn hình Check-in đã hiển thị chưa
            # Nếu chưa tự động đăng nhập (do lỗi token hoặc db local), tiến hành đăng ký tài khoản test
            if page.locator("#checkinScreen").is_visible():
                log_success("Đã tự động xác thực và đăng nhập nhân sự thành công qua mã Token URL.")
            else:
                log_warn("Auto-login token không kích hoạt. Chuyển sang đăng ký nhân viên mới...")
                # Điền form Đăng ký để test
                page.click("#tabRegister")
                page.fill("input#reg_name", "Test Worker Playwright")
                page.select_option("select#reg_linhvuc", "F&B")
                page.fill("input#reg_admin_code", "BITPAW2026")
                page.wait_for_timeout(1000)
                
                # Bấm Join
                page.click("#btn_reg_submit")
                page.wait_for_timeout(3000)
            
            # Chờ màn hình checkinScreen hiển thị hoàn tất
            page.wait_for_selector("#checkinScreen", state="visible", timeout=10000)
            
            # Kiểm tra thời gian đồng hồ
            clock_text = page.locator("#clockText").text_content()
            log_info(f"Thời gian đồng hồ hiển thị trên UI: {clock_text}")
            
            # ==========================================================
            # BƯỚC 4: BẮT ĐẦU CHẤM CÔNG (CLOCK IN)
            # ==========================================================
            log_info("Bước 2: Click nút 'CLOCK IN' để tiến hành chấm công...")
            # Click nút fingerprint
            page.locator(".btn-glow").click()
            page.wait_for_timeout(2000)
            
            # Đợi Camera và GPS kích hoạt
            page.wait_for_selector("#cameraFeed", timeout=10000)
            log_info("Camera feed đã kích hoạt.")
            
            # Đợi GPS lock
            gps_status = page.locator("#gpsStatus")
            page.wait_for_function("() => document.getElementById('captureBtn').disabled === false", timeout=15000)
            log_success("GPS Target đã định vị thành công. Nút lưu bằng chứng đã sẵn sàng.")
            
            # Bấm chụp và nộp báo cáo chấm công
            log_info("Bước 3: Bấm nút lưu bằng chứng chụp ảnh khuôn mặt...")
            page.click("#captureBtn")
            
            # Chờ xử lý nộp bằng chứng chấm công
            log_info("Đang nộp bằng chứng chấm công lên Supabase...")
            page.wait_for_timeout(4000)
            
            # ==========================================================
            # BƯỚC 5: XÁC MINH CHẤM CÔNG HOÀN TẤT & VÀO APP CHÍNH
            # ==========================================================
            page.wait_for_selector("#mainApp", state="visible", timeout=15000)
            log_success("XÁC MINH THÀNH CÔNG: Chấm công hoàn tất, hệ thống chuyển vào giao diện chính Main App!")
            
            # Verify tên hiển thị
            ui_name = page.locator("#ui_name").text_content()
            log_info(f"Tên nhân viên hiển thị trên Header: '{ui_name}'")
            
            # Chụp ảnh làm bằng chứng test
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, "playwright_attendance_test.png")
            page.screenshot(path=screenshot_path)
            log_success(f"Ảnh chụp màn hình lưu tại: {screenshot_path}")
            
            page.wait_for_timeout(2000)
            
        except Exception as step_err:
            log_error(f"Gặp lỗi trong các bước kiểm thử chấm công: {str(step_err)}")
            try:
                screenshot_dir = "static/test_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                page.screenshot(path=os.path.join(screenshot_dir, "playwright_attendance_error.png"))
                log_info("Đã chụp ảnh màn hình lỗi tại static/test_screenshots/playwright_attendance_error.png")
            except:
                pass
        finally:
            browser.close()
            log_info("Đã đóng trình duyệt.")
            print(f"\n{BOLD}{YELLOW}=== KẾT THÚC KIỂM THỬ CHẤM CÔNG ==={RESET}\n")

if __name__ == "__main__":
    run_test()
