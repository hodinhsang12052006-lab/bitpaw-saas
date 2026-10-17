# Icon 3D ngành Nails — 35 icon

Phần mềm tự dùng ảnh 3D cho icon nào có file `static/icons/3d/<tên>.webp`; icon chưa có ảnh vẫn hiện icon cũ (ô sơn gel SVG).

## Quy trình

1. Tạo ảnh bằng Gemini theo **thông số** và **prompt** bên dưới.
2. Lưu ảnh vào thư mục **`3d/`** ở thư mục gốc dự án, **tên file = cột "Tên file"** (vd `3d/checkout.png`). PNG hoặc JPG đều được.
3. Chạy `python scripts/prepare_3d_icons.py` — tự tách nền, cắt sát, căn giữa, thu về 256×256, lưu `static/icons/3d/<tên>.webp`.
4. Khởi động lại server / deploy.

## Thông số ảnh

| | |
|---|---|
| Tỉ lệ | **1:1 (vuông)** |
| Kích thước tạo | **1024 × 1024 px** (tối thiểu 512 × 512) |
| Nền | Trong suốt nếu được; không thì **nền trắng trơn hoặc xám trơn một màu** (script tự xoá nền) — không gradient, không hoạ tiết, không bóng đổ xuống nền |
| Vật thể | Một vật thể duy nhất, **ở giữa, chiếm ~80% khung**, nhìn thẳng hơi chéo 3/4 từ trên xuống |
| Chữ | **Không có chữ, số, logo** trong ảnh |
| Đồng bộ | Tạo **cả 35 icon cùng 1 câu mô tả phong cách** (bên dưới) để cùng ánh sáng, cùng chất liệu |
| Hiển thị trong app | 18–46 px (có ô 22, 34, 38, 46 px) — vì vậy hình phải **đơn giản, khối rõ, ít chi tiết nhỏ** |

## Câu phong cách (dán trước mỗi prompt)

> 3D icon, glossy soft clay style, rounded friendly shapes, smooth gel-polish shine, soft studio lighting from top-left, subtle ambient occlusion, pastel-to-vivid color, single object centered, fills 80% of the frame, isometric 3/4 view, plain solid white background, no text, no logo, no shadow on background, high detail, 1:1, 1024x1024

## Danh sách icon

| # | Tên file | Chức năng trong app | Vật thể cần vẽ (prompt) | Màu chủ đạo |
|---|---|---|---|---|
| 1 | `checkout.png` | Tab Checkout (thanh toán) | a modern cash register with a small receipt coming out | xanh ngọc (teal) |
| 2 | `hold.png` | Giữ vé | an hourglass with glowing sand | cam – hổ phách |
| 3 | `booking.png` | Đặt lịch online / Lịch hẹn | a calendar page with a check mark and a tiny nail polish bottle | hồng fuchsia |
| 4 | `checkedin.png` | Khách đã check-in / Chấm công | a person avatar with a green check badge | tím |
| 5 | `polish.png` | Thêm dịch vụ / Món tự do / POS dịch vụ | a nail polish bottle with a plus badge | xanh cyan |
| 6 | `history.png` | Lịch sử thanh toán / Phiếu lương | a long paper receipt with zigzag bottom | xanh dương – tím |
| 7 | `discount.png` | Giảm giá | a price tag with a percent sign | vàng – cam |
| 8 | `refund.png` | Hoàn tiền / Hoàn ứng chi phí | a coin with a circular return arrow | tím lavender |
| 9 | `quote.png` | In báo giá | a document page with a dollar sign | xanh dương |
| 10 | `clear.png` | Xoá vé | a trash bin | đỏ hồng |
| 11 | `ticket.png` | Tab "Vé hiện tại" / Biên lai | a service ticket card with lines | xanh ngọc đậm |
| 12 | `queue.png` | Tab "Hàng chờ" | two people standing in line | hồng |
| 13 | `all.png` | Danh mục "Tất cả" | four rounded squares grid | vàng |
| 14 | `acrylic.png` | Danh mục Acrylic / Full set / Extensions | a long almond-shaped acrylic nail on a fingertip | hồng đậm |
| 15 | `pedicure.png` | Danh mục Pedicure | a foot with painted toenails | xanh ngọc nhạt |
| 16 | `package.png` | Danh mục Packages / Combo | a gift box with a ribbon bow | vàng – cam |
| 17 | `design.png` | Danh mục Design / Nail art / AI Studio | a nail art brush with a sparkle | tím |
| 18 | `addon.png` | Danh mục Add-on / Gem | a faceted diamond gem | xanh cyan |
| 19 | `waxing.png` | Danh mục Waxing / Lash / Brow | a drop of warm honey wax | cam |
| 20 | `gel.png` | Danh mục Gel / Shellac | a glossy gel polish drop with a sparkle | hồng đỏ |
| 21 | `spark.png` | Danh mục khác (mặc định) | a four-point sparkle star | tím nhạt |
| 22 | `dashboard.png` | Sidebar: Tổng quan | a speedometer gauge | xanh dương |
| 23 | `qr.png` | Sidebar: QR đặt lịch | a QR code tile | hồng tím |
| 24 | `customers.png` | Sidebar: Khách hàng (CRM) | a heart with a small person inside | đỏ hồng |
| 25 | `ai.png` | Sidebar: AI Copilot | a chat bubble with a sparkle | xanh indigo |
| 26 | `staff.png` | Sidebar: Nhân sự / Quản lý thợ | a group of two staff avatars | hồng |
| 27 | `payroll.png` | Sidebar: Bảng lương / Calculate Pay | a stack of gold coins | vàng |
| 28 | `leave.png` | Sidebar: Đơn xin nghỉ | a beach umbrella | xanh ngọc |
| 29 | `chart.png` | Sidebar: Báo cáo | a bar chart with rising bars | xanh lá |
| 30 | `settings.png` | Sidebar: Cài đặt thương hiệu | an artist color palette | tím |
| 31 | `exit.png` | Sidebar: Đăng xuất | a door with an arrow pointing out | xám xanh |
| 32 | `cash.png` | Thanh toán: Tiền mặt | a banknote | xanh lá đậm |
| 33 | `card.png` | Thanh toán: Thẻ | a credit card | vàng hổ phách |
| 34 | `split.png` | Thanh toán: Chia đôi | a banknote and a credit card split side by side | xanh cyan |
| 35 | `terminal.png` | Thanh toán: Máy Square Terminal | a handheld card payment terminal | tím đậm |

Ví dụ prompt hoàn chỉnh cho #15: *3D icon, glossy soft clay style, … 1:1, 1024x1024 — a foot with painted toenails, main color soft teal.*
