# F&B Industry Master Audit Report

Generated: 2026-10-25T08:28:31.494Z

**8 PASS · 0 WARN · 0 FAIL** (8 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng nhập & Khởi tạo POS F&B | PASS | 5574ms | console_errors=0, network_5xx=0, tables=12, menu_items=9, bàn_tiếng_việt_hiển_thị=12 |
| 2 | 2. Chọn Bàn & Thêm Món Vào Order | PASS | 4064ms | Bàn "Table 1" (id=6518). Đã thêm 2 món (mỗi món x2). Khu vực Checkout hiện: true. |
| 3 | 3. Thanh Toán Tiền Mặt (payment/start -> pending -> confirm) | PASS | 6653ms | start: HTTP 200 txn_id=FNB-0D95A8F9. confirm: HTTP 200 success=true. URL cuối: http://127.0.0.1:5002/payment_success?txn_id=FNB-0D95A8F9&method=cash&amount=129.25&currency=USD&industry=fnb |
| 4 | 4. Chọn Phương Thức Thanh Toán Chia Đôi (Split) | PASS | 5692ms | Bàn id=6519. Nút Split active: true. /api/payment/start: HTTP 200, body={"redirect_url":"/payment_pending?table_id=6519&txn_id=FNB-03C0AF48&amount=15.13&method=split&industry=fnb&currency=USD","success":true,"txn_id":"FNB-03C0AF48"} |
| 5 | 5. QR Tự Gọi Món (khách) -> Kitchen Display Real-time (SSE) | PASS | 10266ms | submit_qr_order: HTTP 200 success=true. Kitchen orders: 3 -> 4 (không reload, chờ SSE). Console errors trang khách: 0. |
| 6 | 6. Đặt Bàn Công Khai (khách vãng lai, không đăng nhập) | PASS | 3032ms | POST /api/public/reservations/39821fa8-e42a-4052-bc9d-eb061eaaae11: HTTP 200, body={"id":48,"success":true}. Console errors: 0. |
| 7 | 7. Chấm Công F&B (/chamcong_fnb) | PASS | 2849ms | Trang tải nội dung dài 1182 ký tự, 0 lỗi console mới. Snippet: "BitPaw VI Dashboard Smart POS Kitchen Display QR Menu Customer Management AI Copilot AI Studio Staff Management Employees & App Logins Attendance Payr" |
| 8 | 8. Module Dùng Chung Cho F&B (CRM/AI Bot/Nhân Viên/Báo Cáo) | PASS | 6818ms | /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)