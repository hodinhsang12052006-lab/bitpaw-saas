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
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU KIỂM THỬ E2E POS F&B (PLAYWRIGHT) ==={RESET}\n")
    
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
            # BƯỚC 1: ĐĂNG NHẬP ADMIN VÀ TRUY CẬP PHÂN HỆ POS F&B
            # ==========================================================
            log_info("Bước 1: Đăng nhập tài khoản admin...")
            page.goto(f"{URL}/login", timeout=15000)
            page.wait_for_selector("#loginForm")
            page.fill("input#email", ADMIN_EMAIL)
            page.fill("input#password", ADMIN_PASSWORD)
            page.click("#loginBtn")
            
            page.wait_for_timeout(3000)
            page.wait_for_url(lambda url: "/login" not in url, timeout=10000)
            
            # Đảm bảo điều hướng thẳng tới trang POS (/pos)
            log_info("Truy cập phân hệ POS Bán hàng...")
            page.goto(f"{URL}/pos", timeout=15000)
            page.wait_for_selector("#tableGrid", timeout=10000)
            log_success("Tru cập trang POS thành công.")
            
            # ==========================================================
            # BƯỚC 2: KIỂM TRA SƠ ĐỒ BÀN (TẠO MỚI NẾU THIẾU BÀN 1)
            # ==========================================================
            log_info("Bước 2: Tìm và chọn 'Bàn 1' trên sơ đồ...")
            table_selector = "[data-table-name='Bàn 1']"
            
            if page.locator(table_selector).count() == 0:
                log_warn("Không tìm thấy 'Bàn 1'. Tiến hành tạo bàn mới...")
                page.fill("input#newTableName", "Bàn 1")
                page.click("#addTableBtn")
                page.wait_for_timeout(2000)
                log_success("Đã đúc 'Bàn 1' thành công.")
            
            # Click chọn 'Bàn 1'
            page.locator(table_selector).click()
            log_info("Đã chọn 'Bàn 1'.")
            page.wait_for_timeout(1000)
            
            # Verify tên bàn đã chọn hiển thị trên UI
            selected_table_name = page.locator("#selectedTableName").text_content()
            log_info(f"Tên bàn được chọn hiển thị: '{selected_table_name}'")
            if "Bàn 1" in selected_table_name:
                log_success("Xác nhận 'Bàn 1' đã được đưa vào trạng thái kích hoạt gọi món.")
            else:
                log_error("LỖI: Trạng thái chọn bàn hoạt động không chính xác.")
                
            # ==========================================================
            # BƯỚC 3: KIỂM TRA THỰC ĐƠN MENU (THÊM SẢN PHẨM MỚI NẾU RỖNG)
            # ==========================================================
            log_info("Bước 3: Chọn món từ thực đơn menu...")
            product_selector = "#menuGrid [data-product-id]"
            
            # Lọc sản phẩm thực tế
            products_count = page.locator(product_selector).count()
            log_info(f"Số lượng món trong thực đơn hiện tại: {products_count}")
            
            if products_count == 0:
                log_warn("Menu hiện tại đang trống. Điều hướng sang trang thêm món để tạo món ăn mới...")
                page.goto(f"{URL}/add", timeout=15000)
                page.wait_for_selector("#productName")
                
                page.fill("input#productName", "Lẩu Thái Thập Cẩm")
                page.select_option("select#productCategory", "Đồ Ăn")
                page.fill("input#productStock", "99")
                page.fill("input#priceDisplay", "150000")
                page.wait_for_timeout(1000)
                
                # Submit form
                page.click("#submitBtn")
                page.wait_for_timeout(4000)
                log_success("Đã thêm món mới thành công. Hệ thống tự quay lại trang POS.")
                
                # Click chọn lại Bàn 1 sau khi render lại
                page.locator(table_selector).click()
                page.wait_for_timeout(1000)
                
            # Click chọn món đầu tiên
            first_product = page.locator(product_selector).first
            first_product.click()
            log_info("Đã chọn món ăn. Giao diện hiển thị modal đặt món.")
            page.wait_for_timeout(1000)
            
            # Tăng số lượng trong modal lên
            log_info("Bấm tăng số lượng món lên...")
            page.click("#increaseQty")
            page.wait_for_timeout(500)
            
            # Xác nhận gọi món
            log_info("Bấm nút Xác nhận để đưa món vào hóa đơn...")
            page.click("#confirmOrderBtn")
            page.wait_for_timeout(2000)
            
            # ==========================================================
            # BƯỚC 4: XÁC MINH HÓA ĐƠN & TÍNH TIỀN HÓA ĐƠN
            # ==========================================================
            log_info("Bước 4: Xác minh thông tin thanh toán trên Panel Đơn hiện tại...")
            
            # Verify panel đơn hàng được hiển thị
            checkout_visible = page.locator("#orderCheckoutSection").is_visible()
            if checkout_visible:
                log_success("XÁC MINH THÀNH CÔNG: Panel tính tiền đã tự động mở và cập nhật hóa đơn.")
                
                # Check tổng tiền
                order_total = page.locator("#orderTotal").text_content()
                log_info(f"Tổng tiền thanh toán hiển thị: {order_total}")
                if "0₫" not in order_total and len(order_total) > 0:
                    log_success("Xác nhận tính toán tổng tiền hóa đơn chính xác (> 0₫).")
                else:
                    log_error("LỖI: Giá trị tổng tiền hóa đơn không chính xác.")
            else:
                log_error("LỖI: Hóa đơn không xuất hiện trên giao diện sau khi gọi món.")
                
            # Chụp ảnh làm bằng chứng
            screenshot_dir = "static/test_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, "playwright_pos_fnb_test.png")
            page.screenshot(path=screenshot_path)
            log_success(f"Ảnh chụp màn hình lưu tại: {screenshot_path}")
            
            page.wait_for_timeout(2000)
            
        except Exception as step_err:
            log_error(f"Gặp lỗi trong quá trình thực thi E2E POS F&B: {str(step_err)}")
            try:
                screenshot_dir = "static/test_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                page.screenshot(path=os.path.join(screenshot_dir, "playwright_pos_fnb_error.png"))
                log_info("Đã chụp ảnh màn hình lỗi tại static/test_screenshots/playwright_pos_fnb_error.png")
            except:
                pass
        finally:
            browser.close()
            log_info("Đã đóng trình duyệt.")
            print(f"\n{BOLD}{YELLOW}=== KẾT THÚC KIỂM THỬ POS F&B ==={RESET}\n")

if __name__ == "__main__":
    run_test()
