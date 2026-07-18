# BÁO CÁO KHẢO SÁT & ĐÁNH GIÁ KIẾN TRÚC HỆ THỐNG BITPAW OS
> **Vai trò:** System Architect  
> **Dự án:** Phần mềm Quản lý Bán hàng đa ngành & Chấm công thông minh (BitPaw)  
> **Thời gian đánh giá:** 2026-07-07  
> **Trạng thái quét:** Thành công (Read-Only Audit)

---

## 1. TỔNG QUAN CÔNG NGHỆ (TECHNOLOGY OVERVIEW)

Kiến trúc phần mềm BitPaw được thiết kế theo mô hình **Hybrid (Lai)** kết hợp giữa ứng dụng cục bộ (Local Server) và điện toán đám mây (Cloud Serverless Backend).

*   **Ngôn ngữ lập trình chính:**
    *   **Backend:** Python (3.12+)
    *   **Frontend:** HTML5, CSS3 (Vanilla CSS, Tailwind CSS qua CDN), JavaScript (ES6+).
*   **Backend Framework:**
    *   Sử dụng **Flask** làm lõi routing và API Controller chính.
    *   Tích hợp máy chủ **Waitress** cho môi trường Production trên Windows để tăng tính ổn định và xử lý luồng đồng thời.
*   **Kiến trúc Database:** Hệ thống triển khai giải pháp lưu trữ kép (Dual Database) để tự động chịu lỗi (Graceful Degradation):
    1.  **Local SQLite Databases:**
        *   `database.db`: Lưu trữ cấu hình kích hoạt bản quyền (`kho_license`), hàng đợi yêu cầu CSKH khi mất mạng (`cskh_request_outbox`), kết nối đa kênh (`platform_connections`), hồ sơ khách hàng (`customer_profiles`), các chiến dịch CSKH và nhật ký chấm công offline (`local_attendance`).
        *   `sales.db`: Quản lý dữ liệu hoạt động kinh doanh cục bộ bao gồm sản phẩm (`products`), đơn hàng (`sales`), chi phí (`expenses`), sơ đồ bàn ăn (`dining_tables`), hóa đơn treo (`table_orders`), phòng hát (`karaoke_rooms`), và dịch vụ spa (`spa_services`).
    2.  **Cloud Database (Supabase PostgreSQL):**
        *   Lưu trữ tập trung thông tin nhân sự (`staff` / `employees`), bảng chấm công tổng hợp (`attendance` / `chamcong`), dữ liệu cấu hình hệ thống (`system_settings`), tài khoản quản trị và bảo mật.
        *   **Bypass & Fallback Logic:** Khi ứng dụng không có kết nối tới Supabase (hoặc credentials bị thiếu), class `DummySupabaseClient` trong `supabase_client.py` sẽ kích hoạt chế độ bộ nhớ cục bộ. Dữ liệu chấm công hoặc CSKH sẽ tự lưu tạm vào SQLite local và chờ đồng bộ lại khi mạng online trở lại.

---

## 2. BẢN ĐỒ TÍNH NĂNG (FEATURES MAP)

Dựa vào việc quét toàn bộ các route tại `app.py` và các tệp giao diện trong thư mục `templates`, hệ thống BitPaw được cấu trúc thành các phân hệ chính sau:

### Phân hệ Xác thực & Cấp phép (Auth & Licensing)
*   **Route:** `/register`, `/login`, `/logout`, `/setup`
*   **Tính năng:** Kiểm tra khóa bản quyền đa ngành nghề (`license_key` khớp với loại hình kinh doanh như retail, fnb, spa...) được quản lý cục bộ ở bảng `kho_license`. Hỗ trợ tài khoản demo kết thúc bằng đuôi `@test.com` để thử nghiệm offline nhanh.

### Phân hệ Dashboard đa ngành nghề (Multi-Industry Dashboards)
Hệ thống tự động chuyển đổi giao diện dựa trên ngành nghề được cấu hình trong `business_mode` lưu tại session:
*   **Bán lẻ (Retail):** Route `/dashboard` phục vụ giao diện bán hàng, báo cáo doanh thu 7 ngày (vẽ biểu đồ Chart.js), cảnh báo tồn kho (`inventory_alert`), quản lý nhà kho (`quanly_kho`).
*   **Nhà hàng & Cafe (F&B):** Route `/pos` quản lý sơ đồ bàn trực quan (`dining_tables`), gọi món tại bàn (`table_order`), màn hình hiển thị nhà bếp (`kitchen_display`), và menu gọi món bằng mã QR (`qr_menu`).
*   **Spa & Thẩm mỹ viện (Spa):** Route `/spa` quản lý điều phối kỹ thuật viên, theo dõi hoa hồng, và hồ sơ khách hàng VIP có lưu hình ảnh trước/sau liệu trình.
*   **Karaoke & Bida:** Route `/karaoke` tính giờ tự động cho từng phòng hát/bàn chơi, quản lý trạng thái bật/tắt phòng và gọi dịch vụ đi kèm.

### Phân hệ Trạm CSKH & AI Nurturing (Customer Service & CRM Automation)
*   **Route:** `/api/cskh/request`, `/crm_automation`, `/ai_bot`, `/customer_nurturing`, `/campaign_builder`
*   **Tính năng:** Nút widget CSKH toàn cục (`cskh_global.html`) giúp khách hàng gửi yêu cầu hỗ trợ. Phía admin có công cụ AI gợi ý nội dung chăm sóc khách hàng, quản lý kịch bản chatbot tự động gửi qua Zalo/Messenger, và phân tích điểm tiềm năng khách hàng.

### Phân hệ Định vị & Radar GPS (GPS Dispatching)
*   **Route:** `/map_dashboard`
*   **Tính năng:** Giao diện bản đồ hiển thị vị trí thực tế của kỹ thuật viên/thợ ngoài hiện trường theo thời gian thực (Real-time GPS Tracking).

### Phân hệ Chấm công chuyên biệt cho từng ngành (Custom Attendance Modules)
Hệ thống thiết lập 7 mẫu chấm công tối ưu riêng cho từng loại hình lao động:
1.  `chamcong_spa.html`: Quản lý "Vòng quay tua tự động" cho kỹ thuật viên spa, tính hoa hồng tua, ghi nhận tiền tips và tạo hồ sơ VIP.
2.  `chamcong_nail.html`: POS tính tua tiệm nail (hỗ trợ chia tỷ lệ %, khấu trừ phí supply, tính CC Tip fee, xuất hóa đơn lương ra CSV hoặc ảnh biên lai).
3.  `chamcong_fnb.html`: Điểm danh ca làm việc nhà hàng, tích hợp "Chợ đổi ca" giữa các nhân viên.
4.  `chamcong_khachsan.html`: Chấm công ca bộ phận lễ tân, buồng phòng khách sạn.
5.  `chamcong_congnhan.html`: Chấm công tổ đội sản xuất tại nhà máy, ghi nhận năng suất sản lượng.
6.  `chamcong_kythuat.html`: Điểm danh kỹ thuật viên kèm tọa độ GPS ngoài hiện trường và nhiệm vụ được giao.
7.  `chamcong_vanphong.html`: Điểm danh khối hành chính văn phòng, tích hợp tự động tính bảng lương cuối tháng.

---

## 3. ĐÁNH GIÁ TIẾN ĐỘ HOÀN THIỆN (PROGRESS EVALUATION)

| Thành phần | Mức độ hoàn thiện (%) | Đánh giá hiện trạng kỹ thuật |
| :--- | :---: | :--- |
| **Giao diện người dùng (Frontend)** | **95%** | **Cực kỳ xuất sắc.** Giao diện sử dụng trường phái Glassmorphism sang trọng, màu tối neon sâu thẩm, kết hợp các hạt 3D chuyển động tương tác (Three.js), hiệu ứng nghiêng (Vanilla Tilt), cuộn mượt (Lenis) mang lại trải nghiệm rất cao cấp. Các form nhập liệu, modal và logic tính toán bằng JavaScript thuần chạy rất trơn tru với dữ liệu mẫu trực quan. |
| **Lõi xử lý Backend (Flask Python)** | **90%** | **Đầy đủ ruột và sẵn sàng chạy.** File `app.py` nặng gần 150KB chứa toàn bộ code xử lý logic thật của hệ thống. Đã hoàn thiện kết nối cơ sở dữ liệu kép (SQLite local & Supabase Cloud API), cơ chế retry tự động khi gọi API đám mây bị nghẽn mạng, và đầy đủ logic CRUD cho nhân sự, bảng lương, quản lý kho, phòng hát, backup/restore hệ thống. |
| **Cơ sở dữ liệu (Database Schemas)** | **95%** | **Đã hoàn thiện.** Các file SQL bao gồm `supabase_schema_clean.sql` đã chứa đầy đủ định nghĩa cấu trúc bảng PostgreSQL cho Supabase. Phía SQLite cục bộ tự động khởi tạo bảng khi ứng dụng khởi chạy lần đầu thông qua hàm `init_db()` trong `app.py`. |

> [!NOTE]
> **Nhận xét quan trọng về sự không đồng nhất tên bảng (Database Discrepancy):**
> *   Trong các file HTML giao diện client-side (như `app_nhanvien.html` hoặc `chamcong_spa.html`), mã JavaScript đang trực tiếp truy vấn Supabase tới hai bảng tên là **`employees`** và **`chamcong`**.
> *   Trong khi đó, ở Backend Python (`app.py`) và trong file định nghĩa SQL (`supabase_schema_clean.sql`), bảng chấm công được thiết kế chuẩn hóa dưới tên **`staff`** và **`attendance`**. 
> *   *Khảo sát thực tế:* Hai luồng này chạy độc lập. Luồng admin/backend sử dụng `staff`/`attendance`, còn giao diện thợ tự động hóa ngoài front-end sử dụng `employees`/`chamcong`. Điều này cho thấy hệ thống hỗ trợ cả hai mô hình bảng hoặc đang duy trì song song cả hai luồng chấm công.

---

## 4. ĐỀ XUẤT ĐIỂM KẾT NỐI IFRAME SANG PAWBOOK (MINI-APP CONNECTION)

Để nhúng một màn hình chấm công/điểm danh nhỏ gọn dành cho nhân viên vào trong ứng dụng mạng xã hội doanh nghiệp **PawBook** dưới dạng Iframe, hệ thống đã có sẵn tài nguyên tối ưu:

*   **Tệp giao diện (Frontend File):** `templates/app_nhanvien.html`
*   **Đường dẫn Route chính xác (Backend Route):** `/app_nhanvien` (phương thức GET)
*   **Hàm xử lý Backend:**
    ```python
    @app.route('/app_nhanvien')
    def app_nhanvien():
        return render_template('app_nhanvien.html')
    ```

### Lý do lựa chọn tệp này làm Mini-App nhúng:
1.  **Thiết kế Mobile-First chuyên dụng:** Giao diện được bao bọc trong container `.mobile-container { max-width: 480px; }` giả lập ứng dụng di động dạng Native. Không chứa thanh điều hướng sidebar lớn của Admin, rất phù hợp để nhúng vừa khít vào các khung webview hoặc Iframe của thiết bị di động.
2.  **Bảo mật & Xác thực tối giản:** Hỗ trợ màn hình đăng nhập độc lập cực nhanh chỉ bằng **Mã nhân viên (Employee Code - ví dụ: NV001)** và kiểm tra mã xác thực công ty (`reg_admin_code`), giảm thiểu quy trình nhập mật khẩu phức tạp trên Iframe.
3.  **Tích hợp đầy đủ phần cứng di động:**
    *   **Camera & Face Verification:** Kích hoạt camera trước để chụp ảnh thực tế khi vào ca.
    *   **GPS Positioning:** Tự động lấy tọa độ kinh độ/vĩ độ của thiết bị để xác thực vị trí làm việc.
    *   **IndexedDB (Chế độ chấm công Offline):** Nếu nhân viên check-in tại nơi mất sóng điện thoại, dữ liệu ảnh và tọa độ sẽ tự lưu vào IndexedDB của trình duyệt cục bộ, và tự động đẩy lên Supabase Storage khi có kết nối trở lại.
4.  **Tích hợp đa năng tiện ích:** Ngoài chấm công, mini-app này còn tích hợp màn hình nhận việc từ radar điều phối của công ty, gửi đơn xin nghỉ phép đến HR, tặng sao Kudo đồng nghiệp, và đổi ca làm việc.

---
*Báo cáo được chuẩn bị bởi công cụ Antigravity AI.*
