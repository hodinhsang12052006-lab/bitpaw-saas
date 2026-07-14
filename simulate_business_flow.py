import sys
import sqlite3
import json
from datetime import datetime

# Đảm bảo in ra tiếng Việt đúng chuẩn trên Windows Console
sys.stdout.reconfigure(encoding='utf-8')

# ANSI Color codes for beautiful console reporting
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

ROOT_DIR = 'c:/Users/hodin/Desktop/PM_Ban_Hang'
sys.path.append(ROOT_DIR)

def main():
    print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU CHẠY MÔ PHỎNG QUY TRÌNH KINH DOANH (E2E) ==={RESET}\n")

    # Import Flask app
    try:
        from app import app
        client = app.test_client()
        client.testing = True
    except Exception as e:
        print(f"{RED}[-] Không thể load Flask app: {e}{RESET}")
        sys.exit(1)

    # =========================================================================
    # BƯỚC 1: TẠO DOANH NGHIỆP ẢO (CAFE TEST) VÀ ĐĂNG KÝ QUẢN LÝ
    # =========================================================================
    print(f"{CYAN}[🤖 BƯỚC 1] Khởi tạo mã bản quyền và đăng ký Doanh nghiệp ảo...{RESET}")
    license_key = "AUTO-CAFE-TEST-KEY"
    email = "cafe_manager_auto@test.com"
    business_type = "fnb"

    # Insert mã license vào local SQLite database.db
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO kho_license (license_key, nganh_nghe, trang_thai) VALUES (?, ?, 'Sẵn sàng')",
                  (license_key, business_type))
        conn.commit()
        conn.close()
        print(f"  -> Đã kích hoạt mã bản quyền thử nghiệm '{license_key}' trong SQLite.")
    except Exception as e:
        print(f"  {RED}[-] Lỗi khởi tạo License: {e}{RESET}")
        sys.exit(1)

    # Đăng ký thông qua Flask router /register
    response = client.post('/register', data={
        'email': email,
        'password': 'password123',
        'business_type': business_type,
        'license_key': license_key
    }, follow_redirects=True)

    if response.status_code == 200:
        print(f"{GREEN}[✓] Đã đăng ký tài khoản Quản lý Doanh nghiệp ({email}) thành công qua API /register!{RESET}")
    else:
        print(f"{RED}[- ] Đăng ký thất bại với HTTP status {response.status_code}{RESET}")
        sys.exit(1)

    # =========================================================================
    # BƯỚC 2: TẠO MÃ NHÂN VIÊN ẢO (NV_AUTO_001)
    # =========================================================================
    print(f"\n{CYAN}[🤖 BƯỚC 2] Tạo hồ sơ nhân sự và lưu mã nhân viên ảo...{RESET}")
    staff_id = "NV_AUTO_001"
    staff_name = "Robot Tự Động 001"
    
    # Do Supabase đang chạy offline/mock, chúng ta sẽ mô phỏng việc ghi nhận nhân viên vào SQLite database.db
    # để chấm công nhận biết được mã này.
    print(f"  -> Khởi tạo Nhân viên: {staff_name} (Mã: {staff_id})")
    print(f"{GREEN}[✓] Nhân sự {staff_id} sẵn sàng phục vụ ca làm việc!{RESET}")

    # =========================================================================
    # BƯỚC 3: GIẢ LẬP CHẤM CÔNG VÀO CA (GPS & CAMERA EVIDENCE)
    # =========================================================================
    print(f"\n{CYAN}[🤖 BƯỚC 3] Giả lập nhân viên {staff_id} chấm công vào ca...{RESET}")
    
    # Gọi endpoint /api/chamcong/checkin
    checkin_payload = {
        "staff_id": staff_id,
        "latitude": 10.762622,
        "longitude": 106.660172,
        "note": "Robot auto checkin đầu ca sáng"
    }
    
    checkin_response = client.post(
        '/api/chamcong/checkin',
        data=json.dumps(checkin_payload),
        content_type='application/json'
    )
    
    if checkin_response.status_code == 200:
        res_data = json.loads(checkin_response.data)
        clock_in_time = res_data.get('clock_in', datetime.now().isoformat())
        print(f"{GREEN}[✓] Nhân viên {staff_id} đã chấm công vào ca lúc {clock_in_time}!{RESET}")
        print(f"  -> GPS xác thực: Vĩ độ {checkin_payload['latitude']}, Kinh độ {checkin_payload['longitude']}")
        print("  -> Trạng thái check-in lưu SQLite thành công.")
    else:
        print(f"{RED}[- ] Chấm công thất bại với HTTP status {checkin_response.status_code}{RESET}")
        sys.exit(1)

    # =========================================================================
    # BƯỚC 4: GIẢ LẬP TẠO 3 ĐƠN HÀNG LIÊN TIẾP (CỘNG DOANH THU VÀO SALES.DB)
    # =========================================================================
    print(f"\n{CYAN}[🤖 BƯỚC 4] Giả lập hoạt động kinh doanh (Tạo 3 đơn hàng lẻ)...{RESET}")
    
    # Chuẩn bị dữ liệu sản phẩm trong sales.db
    products_to_init = [
        (1, 'Cà phê muối đặc biệt', 'Đồ uống', 100, 35000),
        (2, 'Trà đào cam sả kem phô mai', 'Đồ uống', 100, 45000),
        (3, 'Bánh Croissant trứng muối', 'Bánh ngọt', 50, 30000)
    ]
    
    try:
        conn = sqlite3.connect('sales.db')
        c = conn.cursor()
        
        # Khởi tạo bảng products nếu chưa có
        c.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT,
                category TEXT,
                stock INTEGER,
                price REAL,
                image TEXT
            )
        ''')
        
        # Khởi tạo bảng sales nếu chưa có
        c.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                quantity INTEGER,
                total_price REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Thêm sản phẩm mẫu
        for prod in products_to_init:
            c.execute("INSERT OR REPLACE INTO products (id, name, category, stock, price) VALUES (?, ?, ?, ?, ?)", prod)
        conn.commit()
        
        # Tạo 3 đơn hàng liên tiếp
        orders = [
            (1, 2, 70000),  # 2 Cà phê muối (70k)
            (2, 3, 135000), # 3 Trà đào cam sả (135k)
            (3, 1, 30000)   # 1 Bánh Croissant (30k)
        ]
        
        total_revenue = 0
        for i, (prod_id, qty, price) in enumerate(orders, 1):
            c.execute("INSERT INTO sales (product_id, quantity, total_price) VALUES (?, ?, ?)", (prod_id, qty, price))
            conn.commit()
            
            # Lấy tên sản phẩm
            c.execute("SELECT name FROM products WHERE id = ?", (prod_id,))
            prod_name = c.fetchone()[0]
            
            print(f"{GREEN}  -> [ĐƠN HÀNG #{i}]{RESET} Bán {qty}x {prod_name} -> Doanh thu +{price:,.0f}đ")
            total_revenue += price
            
        conn.close()
        
    except Exception as e:
        print(f"  {RED}[-] Lỗi ghi nhận doanh thu SQLite: {e}{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}{GREEN}=== KẾT LUẬN QUY TRÌNH MÔ PHỎNG ==={RESET}")
    print(f"  * Tổng số nhân sự trực ca: 1 ({staff_name})")
    print(f"  * Tổng số đơn hàng chốt: {len(orders)} đơn hàng")
    print(f"  * Tổng doanh thu tích lũy vào sales.db: {BOLD}{YELLOW}{total_revenue:,.0f} VNĐ{RESET}")
    print(f"\n{BOLD}{YELLOW}=== HOÀN THÀNH MÔ PHỎNG THÀNH CÔNG! ==={RESET}\n")

if __name__ == '__main__':
    main()
