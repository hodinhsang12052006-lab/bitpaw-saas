# Hotel Industry Master Audit Report

Generated: 2026-09-27T02:26:05.804Z

**4 PASS · 1 WARN · 0 FAIL** (5 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng nhập & Khởi tạo Sơ Đồ Phòng | WARN | 3750ms | console_errors=1, network_5xx=0, rooms=7 |
| 2 | 2. Nhận Phòng, Thêm Phụ Thu & Trả Phòng | PASS | 3706ms | Phòng id=5. Checkin: HTTP 200. Thêm phụ thu 150,000: HTTP 200. Checkout: HTTP 200, room_total=650000, extra_charges_total=150000 (kỳ vọng 150000), total_amount=800000. |
| 3 | 3. Dọn Phòng (Housekeeping) | PASS | 1453ms | Phòng id=5: HTTP 200, body={"success":true} |
| 4 | 4. Đặt Phòng Công Khai QR + Hiện Trên Trang Quản Trị | PASS | 3554ms | POST /api/public/hotel_reservations/885e1075-9191-4b1e-91ee-d100e961257d: HTTP 200, id=14. Hiện trên /hotel/reservations: true. Console errors trang khách: 0. |
| 5 | 5. Chấm Công Hotel + Module Dùng Chung | PASS | 8558ms | Chấm công: 1537 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)