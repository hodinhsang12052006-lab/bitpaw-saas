# F&B Industry Master Audit Report

Generated: 2026-10-02T15:58:11.103Z

**8 PASS · 0 WARN · 0 FAIL** (8 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng nhập & Khởi tạo POS F&B | PASS | 4509ms | console_errors=0, network_5xx=0, tables=12, menu_items=9, bàn_tiếng_việt_hiển_thị=12 |
| 2 | 2. Chọn Bàn & Thêm Món Vào Order | PASS | 3220ms | Bàn "Bàn 1" (id=6518). Đã thêm 2 món (mỗi món x2). Khu vực Checkout hiện: true. |
| 3 | 3. Thanh Toán Tiền Mặt (payment/start -> pending -> confirm) | PASS | 5378ms | start: HTTP 200 txn_id=FNB-51F44F35. confirm: HTTP 200 success=true. URL cuối: http://127.0.0.1:5001/payment_success?txn_id=FNB-51F44F35&method=cash&amount=121000.0&currency=VND&industry=fnb |
| 4 | 4. Chọn Phương Thức Thanh Toán Chia Đôi (Split) | PASS | 3747ms | Bàn id=6519. Nút Split active: true. /api/payment/start: HTTP 200, body={"redirect_url":"/payment_pending?table_id=6519&txn_id=FNB-DCDC9F62&amount=176000&method=split&industry=fnb","success":true,"txn_id":"FNB-DCDC9F62"} |
| 5 | 5. QR Tự Gọi Món (khách) -> Kitchen Display Real-time (SSE) | PASS | 11178ms | submit_qr_order: HTTP 200 success=true. Kitchen orders: 33 -> 34 (không reload, chờ SSE). Console errors trang khách: 0. |
| 6 | 6. Đặt Bàn Công Khai (khách vãng lai, không đăng nhập) | PASS | 2154ms | POST /api/public/reservations/39821fa8-e42a-4052-bc9d-eb061eaaae11: HTTP 200, body={"id":17,"success":true}. Console errors: 0. |
| 7 | 7. Chấm Công F&B (/chamcong_fnb) | PASS | 3216ms | Trang tải nội dung dài 1022 ký tự, 0 lỗi console mới. Snippet: "BitPaw VI Dashboard Smart POS Kitchen Display QR Menu Customer Management AI Copilot AI Studio Staff Management Attendance Payroll Leave Requests Expe" |
| 8 | 8. Module Dùng Chung Cho F&B (CRM/AI Bot/Nhân Viên/Báo Cáo) | PASS | 4424ms | /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)