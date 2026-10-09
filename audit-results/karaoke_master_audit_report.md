# Karaoke Industry Master Audit Report

Generated: 2026-10-09T11:34:47.144Z

**4 PASS · 0 WARN · 0 FAIL** (4 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng nhập & Khởi tạo Phòng Karaoke | PASS | 3990ms | console_errors=0, network_5xx=0, rooms=7 |
| 2 | 2. Mở Phòng & Chốt Phòng (tính giờ tự động) | PASS | 32553ms | Phòng "Room 2" (id=2). Start: HTTP 200. Checkout: HTTP 200, order_id=1790, total_amount=62500. |
| 3 | 3. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị | PASS | 3981ms | POST /api/public/karaoke_reservations/0cc47d38-b306-46f3-9da1-cdf2d840d79b: HTTP 200, id=11. Hiện trên /karaoke/reservations: true. Console errors trang khách: 0. |
| 4 | 4. Chấm Công Karaoke + Module Dùng Chung | PASS | 6623ms | Chấm công: 863 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)
- Module "pos_ordering" khai báo trong INDUSTRY_CONFIG['karaoke'] không có UI tương ứng trong karaoke.html — không có giỏ hàng gọi đồ uống/đồ ăn trong lúc chơi, chỉ tính tiền phòng theo giờ khi chốt phòng. Ghi nhận là spec-vs-implementation gap, không phải bug.