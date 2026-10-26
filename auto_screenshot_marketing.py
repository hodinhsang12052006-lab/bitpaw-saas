import os
import time
from playwright.sync_api import sync_playwright

# 1. Khởi tạo thư mục
FOLDER_NAME = "Anh_Content_Marketing"
if not os.path.exists(FOLDER_NAME):
    os.makedirs(FOLDER_NAME)
    print(f"[*] Đã tạo thư mục lưu trữ ảnh chụp tại: {FOLDER_NAME}")

# Cấu hình tài khoản đăng nhập sếp vừa đưa
LOGIN_URL = "http://localhost:5000/login"
# Tài khoản super admin cho test: CHỈ đọc từ biến môi trường (mật khẩu cũ từng ghi cứng ở đây, đã lộ trong lịch sử git —
# chủ hệ thống phải đổi mật khẩu đó). BITPAW_QA_SUPERADMIN_* ưu tiên; SUPERADMIN_EMAIL/_PASSWORD cũ vẫn đọc được.
EMAIL = os.environ.get("BITPAW_QA_SUPERADMIN_EMAIL") or os.environ.get("SUPERADMIN_EMAIL", "")
PASSWORD = os.environ.get("BITPAW_QA_SUPERADMIN_PASSWORD") or os.environ.get("SUPERADMIN_PASSWORD", "")

PAGES_TO_CAPTURE = [
    {
        "url": "http://localhost:5000/dashboard",
        "filename": "1_Dashboard_Tong_Quan.png"
    },
    {
        "url": "http://localhost:5000/pos",
        "filename": "2_Man_Hinh_Ban_Hang_POS.png"
    },
    {
        "url": "http://localhost:5000/staff",
        "filename": "3_Quan_Ly_Nhan_Su.png"
    },
    {
        "url": "http://localhost:5000/crm_automation",
        "filename": "4_AI_Marketing_Bot.png"
    },
    {
        "url": "http://localhost:5000/pos",
        "filename": "5_Danh_Sach_San_Pham.png"
    }
]

def run_screenshot_tool():
    with sync_playwright() as p:
        print("[*] Đang khởi động Bot chụp ảnh (Chế độ chạy ngầm)...")
        
        # Đã đổi headless=True để chạy ngầm hoàn toàn
        browser = p.chromium.launch(headless=True, args=["--start-maximized"])
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        # 2. Đăng nhập
        print(f"[*] Đang truy cập trang đăng nhập: {LOGIN_URL}")
        page.goto(LOGIN_URL)
        
        print(f"[*] Đang đăng nhập với tài khoản: {EMAIL}...")
        page.locator('input[type="email"]').fill(EMAIL)
        page.locator('input[type="password"]').fill(PASSWORD)
        page.locator('button[type="submit"]').click()
        
        # 3. Chờ load token
        print("[*] Chờ 5 giây để hệ thống load xong dữ liệu...")
        time.sleep(5)
        
        # 4. Chụp ảnh
        for item in PAGES_TO_CAPTURE:
            url = item["url"]
            filename = item["filename"]
            save_path = os.path.join(FOLDER_NAME, filename)
            
            print(f"\n[*] Đang xử lý trang: {url}")
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(2)
                
                page.screenshot(path=save_path, full_page=True)
                print(f"[✓] Ting ting! Đã lưu ảnh: {filename}")
                
            except Exception as ex:
                print(f"[!] Lỗi ở trang {filename}: {str(ex)}")
        
        print("\n[*] XONG! Sếp mở thư mục Anh_Content_Marketing nhận hàng nhé!")
        browser.close()

if __name__ == "__main__":
    if not (EMAIL and PASSWORD):
        raise SystemExit("Missing super-admin test login: set BITPAW_QA_SUPERADMIN_EMAIL and BITPAW_QA_SUPERADMIN_PASSWORD "
                         "(Thiếu tài khoản super admin cho test: hãy đặt 2 biến môi trường này).")
    run_screenshot_tool()