import sys
import time
import socket
import subprocess
import webbrowser

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
BASE_URL = f"http://localhost:{PORT}"

FUNCTIONAL_ROUTES = [
    ('Thêm chi phí (Add Expense)', '/add_expense'),
    ('Thêm sản phẩm (Add Product)', '/add'),
    ('Thêm dịch vụ Spa (Add Spa Service)', '/add_spa'),
    ('Quản lý giao dịch (Payment Transactions)', '/payment_transactions'),
    ('AI Studio (AI Content Creator)', '/ai_studio'),
    ('BitPaw AI Bot (Chatbot Config)', '/ai_bot'),
    ('Trang Chat nội bộ (Internal Chat)', '/app_chat'),
    ('Mini-App Nhân viên (Attendance App)', '/app_nhanvien'),
    ('Sao lưu & Phục hồi (Backup & Restore)', '/backup_restore'),
    ('Bảng lương nhân sự (Payroll)', '/bangluong'),
    ('Báo cáo lợi nhuận (Profit Report)', '/baocao_loinhuan'),
    ('Thiết lập thương hiệu (Brand Settings)', '/brand_settings'),
    ('Kế hoạch chiến dịch (Campaign Builder)', '/campaign_builder'),
    ('Cấu hình tính lương (Payroll Config)', '/cauhinh_luong'),
    ('Chấm công tổng hợp (Timekeeping)', '/chamcong'),
    ('Chấm công Công nhân (Factory Timekeeping)', '/chamcong_congnhan'),
    ('Chấm công F&B (Cafe/Restaurant Timekeeping)', '/chamcong_fnb'),
    ('Chấm công Khách sạn (Hotel Timekeeping)', '/chamcong_khachsan'),
    ('Chấm công Kỹ thuật (Technical Timekeeping)', '/chamcong_kythuat'),
    ('Chấm công Nail (Nail Timekeeper)', '/chamcong_nail'),
    ('Chấm công Spa (Spa Timekeeper)', '/chamcong_spa'),
    ('Chấm công Văn phòng (Office Timekeeping)', '/chamcong_vanphong'),
    ('Trang Live Chat (Live Support Chat)', '/chat'),
    ('Thanh toán chung (Checkout)', '/checkout'),
    ('Danh sách khách hàng (CRM Customers)', '/customers'),
    ('Tự động hóa CRM (CRM Automation)', '/crm_automation'),
    ('Chăm sóc khách hàng (Customer Nurturing)', '/customer_nurturing'),
    ('Bảng điều khiển OS (Dashboard)', '/dashboard'),
    ('Điểm danh nhân sự (Staff Attendance)', '/diemdanh'),
    ('Đồng bộ thương mại điện tử (E-Commerce Sync)', '/ecommerce_sync'),
    ('Danh sách chi phí (Expense List)', '/expense_list'),
    ('Báo cáo F&B (F&B Dashboard)', '/fnb_dashboard'),
    ('Cảnh báo tồn kho (Inventory Alerts)', '/inventory_alert'),
    ('Sơ đồ phòng/bàn 3D (Interactive Tables Map)', '/karaoke'),
    ('Hiển thị màn hình bếp (Kitchen Display)', '/kitchen_display'),
    ('Bản đồ định vị GPS (Live GPS Map)', '/map_dashboard'),
    ('Danh sách nhân viên (Staff Directory)', '/nhanvien'),
    ('Kết nối đa kênh (Omnichannel Portal)', '/omnichannel_connect'),
    ('Cổng thanh toán (Payment Gateway)', '/payment_gateway'),
    ('Lịch sử thanh toán (Payment History)', '/payment_history'),
    ('Đơn hàng chờ xử lý (Pending Orders)', '/payment_pending'),
    ('Thanh toán thành công (Payment Success)', '/payment_success'),
    ('Bảng điều khiển Quản trị (Portal)', '/portal'),
    ('Màn hình POS bán hàng (POS Point of Sale)', '/pos'),
    ('Doanh thu theo sản phẩm (Profit by Product)', '/profit_report'),
    ('Quản lý khuyến mãi (Promotions Management)', '/promotions'),
    ('Quản lý công nợ (Debt Management)', '/quanly_congno'),
    ('Quản lý dịch vụ (Services Directory)', '/quanly_dichvu'),
    ('Quản lý kho hàng (Inventory Management)', '/quanly_kho'),
    ('Quản lý thu chi (Cashflow Registry)', '/quanly_thuchi'),
    ('Báo cáo doanh số (Sales Report)', '/report'),
    ('Màn hình bán nhanh (Fast Sales)', '/sell'),
    ('Thiết lập ban đầu (Initial Setup)', '/setup'),
    ('Hồ sơ dịch vụ Spa (Spa Profile)', '/spa'),
    ('Quản lý nhân viên (Staff Management)', '/staff'),
    ('Trang quản trị tối cao (Super Admin)', '/super-admin'),
    ('Nhật ký người dùng (User System Logs)', '/user_logs')
]

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def main():
    print(f"\n{BOLD}{YELLOW}=== CHƯƠNG TRÌNH TRÌNH DIỄN GIAO DIỆN CHỨC NĂNG THỰC TẾ ==={RESET}\n")

    server_process = None
    started_by_us = False

    # Bước 1: Khởi động Flask Server ngầm
    if is_port_open(PORT):
        print(f"{YELLOW}[*] Cổng {PORT} đã mở sẵn. Sử dụng Server đang chạy.{RESET}")
    else:
        print(f"{CYAN}[🤖 BƯỚC 1] Khởi động Flask Server (app.py) ngầm...{RESET}")
        try:
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

    # Bước 2: Chờ Server sẵn sàng
    print(f"\n{CYAN}[🤖 BƯỚC 2] Đang kết nối tới Server BitPaw OS tại {BASE_URL}...{RESET}")
    import urllib.request
    from urllib.error import URLError

    max_attempts = 15
    server_ready = False
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(BASE_URL, timeout=1) as response:
                if response.status == 200 or response.status == 302:
                    server_ready = True
                    break
        except (URLError, socket.timeout, ConnectionResetError):
            pass
        print(f"  -> Lần kiểm tra {attempt}/{max_attempts}: Server chưa phản hồi, chờ 1 giây...")
        time.sleep(1)

    if not server_ready:
        print(f"{RED}[- ] Lỗi: Server không phản hồi sau {max_attempts} giây.{RESET}")
        if started_by_us and server_process:
            server_process.terminate()
        sys.exit(1)

    print(f"{GREEN}[✓] Server đã hoạt động ổn định!{RESET}")

    # Bước 3: Tự động mở các tab trình diễn giao diện chức năng thực tế
    print(f"\n{CYAN}[🤖 BƯỚC 3] Tự động mở các giao diện CHỨC NĂNG THỰC TẾ trên Trình duyệt...{RESET}")
    
    for name, route in FUNCTIONAL_ROUTES:
        url = f"{BASE_URL}{route}"
        print(f"  -> Đang mở {name}: {url}")
        webbrowser.open(url)
        time.sleep(0.8)

    print(f"\n{GREEN}[✓] Đã mở toàn bộ {len(FUNCTIONAL_ROUTES)} giao diện chức năng thực tế thành công!{RESET}")
    
    # Bước 4: Chờ người dùng nhấn ENTER để dọn dẹp tắt server
    print(f"\n{BOLD}{YELLOW}[!] Đã mở toàn bộ giao diện trên Trình duyệt.{RESET}")
    print(f"{BOLD}{YELLOW}[!] Nhấn ENTER tại đây để đóng Server và dọn dẹp cổng kết nối...{RESET}")
    
    try:
        input()
    except KeyboardInterrupt:
        pass

    # Dọn dẹp dập tắt server
    print(f"\n{CYAN}[🤖 BƯỚC 4] Tiến hành dọn dẹp hệ thống...{RESET}")
    if started_by_us and server_process:
        server_process.terminate()
        server_process.wait()
        print(f"  -> Đã đóng Flask server ngầm và giải phóng cổng {PORT}.")
    else:
        print("  -> Giữ nguyên server đang chạy sẵn.")

    print(f"\n{BOLD}{GREEN}=== HOÀN THÀNH CHƯƠNG TRÌNH TRÌNH DIỄN! ==={RESET}\n")

if __name__ == '__main__':
    main()
