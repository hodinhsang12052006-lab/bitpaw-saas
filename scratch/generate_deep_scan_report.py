import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = 'c:/Users/hodin/Desktop/PM_Ban_Hang'
EXCLUDE_DIRS = {'.git', '.vscode', '__pycache__', 'node_modules', '.gemini', 'venv'}

def get_directory_tree(path, prefix=''):
    tree_str = ''
    try:
        entries = sorted(os.listdir(path))
    except Exception as e:
        return f"{prefix}[Error: {e}]\n"
        
    for entry in entries:
        full_path = os.path.join(path, entry)
        if entry in EXCLUDE_DIRS:
            continue
        if os.path.isdir(full_path):
            tree_str += f"{prefix}├── {entry}/\n"
            tree_str += get_directory_tree(full_path, prefix + '    ')
        else:
            size_kb = os.path.getsize(full_path) / 1024
            tree_str += f"{prefix}├── {entry} ({size_kb:.2f} KB)\n"
    return tree_str

def extract_routes(app_py_path):
    routes = []
    if not os.path.exists(app_py_path):
        return routes
    
    with open(app_py_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        
    current_route = []
    for idx, line in enumerate(lines, 1):
        line_strip = line.strip()
        if '@app.route' in line_strip:
            current_route.append(line_strip)
        elif current_route and line_strip.startswith('def '):
            routes.append((idx, " / ".join(current_route), line_strip))
            current_route = []
    return routes

if __name__ == '__main__':
    tree = get_directory_tree(ROOT_DIR)
    routes = extract_routes(os.path.join(ROOT_DIR, 'app.py'))
    
    report_content = f"""# BÁO CÁO QUÉT TIA X TOÀN DIỆN HỆ THỐNG BITPAW OS
> **Thời gian quét:** 2026-07-07  
> **Phương pháp:** Deep Scanner Script (Recursive File Inspection)

---

## 1. CÂY THƯ MỤC HOÀN CHỈNH (COMPLETE DIRECTORY TREE)
Bỏ qua các thư mục hệ thống/bộ nhớ đệm như `.git`, `.vscode`, `__pycache__`, `node_modules`.

```text
{tree}```

---

## 2. BẢN ĐỒ ROUTE (FLASK ROUTES MAP)
Dưới đây là danh sách toàn bộ các API và Route được định nghĩa trong Flask server (`app.py`):

| Dòng | Route Định Nghĩa | Hàm Backend Xử Lý |
| :--- | :--- | :--- |
"""
    
    for idx, route, func in routes:
        # Escape markdown characters
        r_esc = route.replace('|', '\\|')
        f_esc = func.replace('|', '\\|')
        report_content += f"| {idx} | `{r_esc}` | `{f_esc}` |\n"
        
    report_content += """
---

## 3. LUỒNG XÁC THỰC CHI TIẾT (AUTH FLOW ANALYSIS)

Hệ thống quản lý xác thực được phân tách làm hai giải pháp độc lập tùy theo phân hệ giao diện:

### A. Luồng Đăng nhập/Đăng ký khối Quản trị (Admin/OS Portal)
*   **Giao diện chính:** Tệp `templates/index.html` (sử dụng hai tab `login` và `register` phục vụ đăng nhập/đăng ký mặc định) hoặc hai tệp giao diện độc lập [login.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/login.html) và [register.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/register.html).
*   **Cơ chế hoạt động:**
    1.  Khách hàng/Admin nhập form và gửi `POST` request trực tiếp về Flask server tại các endpoints `@app.route('/login')` hoặc `@app.route('/register')`.
    2.  Tại Backend, Flask sử dụng thư viện **Supabase Python SDK** (`supabase.auth.sign_in_with_password` hoặc `supabase.auth.sign_up`) để kiểm tra tài khoản trên Cloud.
    3.  Đồng thời, khi đăng ký, Backend sẽ đối chiếu mã kích hoạt bản quyền `license_key` trực tiếp trên cơ sở dữ liệu SQLite local (`database.db`, bảng `kho_license`).
    4.  Nếu đăng nhập/đăng ký thành công, Flask lưu thông tin định danh và quyền của người dùng vào `session` phía máy chủ (`session['user_id']`, `session['business_mode']`) để quản lý quyền truy cập.

### B. Luồng Xác thực khối Nhân viên (Employee Mini-App)
*   **Giao diện chính:** [app_nhanvien.html](file:///c:/Users/hodin/Desktop/PM_Ban_Hang/templates/app_nhanvien.html) (truy cập thông qua route GET `/app_nhanvien`).
*   **Cơ chế hoạt động:**
    1.  **Xác thực không mật khẩu (Passwordless/Token Code):** Phân hệ nhân viên không sử dụng mật khẩu. Thay vào đó, nhân viên đăng nhập bằng **Mã Nhân Viên (Employee Code - ví dụ: NV001)**.
    2.  **Xử lý thuần Client-side:** Trình duyệt tải tệp `app_nhanvien.html` và sử dụng trực tiếp thư viện **Supabase Javascript SDK** (`@supabase/supabase-js`) để gọi API từ Supabase Cloud.
    3.  **Auto-Login (Tích hợp PawBook):**
        *   Khi mở trang với định dạng `/app_nhanvien?token=NV001`, mã Javascript sẽ bắt sự kiện `window.onload` và lấy giá trị `token` từ tham số URL.
        *   Nó gửi câu lệnh truy vấn trực tiếp lên Supabase PostgreSQL: `supabase.from('employees').select('*').eq('ma_nv', token)`
        *   Nếu nhân sự tồn tại, JS tự động ghi thông tin vào `localStorage`, lưu vào biến toàn cục `currentUser` và gọi `vaoAppNgay()`, ẩn hoàn toàn màn hình xác thực mà không cần đi qua cổng Flask backend.

---
*Báo cáo Deep Scan được lập tự động bởi Antigravity AI.*
"""

    with open(os.path.join(ROOT_DIR, 'DEEP_SCAN_REPORT.md'), 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print("[*] DEEP_SCAN_REPORT.md generated successfully!")
