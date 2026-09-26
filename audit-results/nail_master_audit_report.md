# Nail Industry Master Audit Report

Generated: 2026-09-25T17:25:51.987Z

**9 PASS · 1 WARN · 0 FAIL** (10 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Khởi tạo & Giao diện POS Nails | WARN | 5199ms | console_errors=1, network_5xx=0, services=18, technicians=6, search_placeholder="Search services, techs, code..." |
| 2 | 2. Chọn Dịch Vụ & Modifier/Custom Item | PASS | 2614ms | Đã thêm: Acrylic Full Set (Ombre/Design), Callus Treatment & Heel Scrub + 1 Custom Item ($15). Tổng 3 dòng trong giỏ. |
| 3 | 3. Gán Thợ & Quản Lý Vé (Hold/Resume) | PASS | 2120ms | Thợ gán: "Ava Robertson" (NV0053). Badge hàng chờ sau Hold: 1. Giỏ trước Hold=3, sau Resume=3. |
| 4 | 4. Tính Tiền, Tip & Payment Modal | PASS | 1196ms | Total: "$230.00 AUD" -> "$238.00 AUD" (Tip: +$8.00). Dual-pricing UI toggle tồn tại: true. |
| 5 | 5. Xác Nhận Thanh Toán & Lưu DB | PASS | 1879ms | HTTP 200, order_id=891, total_amount=238, receipt hiển thị: "Order #891" |
| 6 | 6. Lịch Sử Hóa Đơn & In Lại Bill | PASS | 2061ms | Số dòng lịch sử hôm nay: 20. Đơn #891 xuất hiện trong danh sách: true. |
| 7 | 7. Đối Soát Chấm Công & Payroll (US) | PASS | 2826ms | 6 nhân viên hiển thị. Lịch sử "Tính Tua" của thợ vừa gán có dữ liệu mới: true. Snippet: "[NAILS POS] ORDER #891 — 40.0% 25/09/2026 $80.11 Pay: $72.2 \| Tip: $7.91 [NAILS POS] ORDER #888 — 40.0% 25/09/2026 $44.01 Pay: $36.1 \| Tip: $7.91 [NAILS POS] ORDER #887 — 40.0% 25/09/2026 $5" |
| 8 | 8. Booking Website Công Khai + QR Code | PASS | 7516ms | Business "000b2c16-ab4e-42bd-944a-29c925cad09b" — public page: 18 dịch vụ / 6 thợ. Đặt lịch HTTP 200, appointment id=103, ticket="TICKET-103". Xuất hiện trong /calendar của chủ tiệm: true. Console errors (trang khách): 0. |
| 9 | 9. Giảm Giá, Thanh Toán Chia Đôi & Hoàn Tiền | PASS | 5442ms | Discount preview: $9.50 (áp dụng: true). Split total=85.5, cash=card=42.75, mismatch=false, order_id=892. Refund order #892: true ({"order_status":"partially_refunded","refund_id":893,"success":true,"techs_clawed_back":[]}). |
| 10 | 10. Dual Pricing (Cash Price / Card Price) | PASS | 7586ms | UI: cash=$95 card=$97.85 (kỳ vọng $97.85). Order Cash #894: total=95, hoa hồng=36.1. Order Card #895: total=97.85, subtotal=95, phụ phí=2.85, hoa hồng=36.1 (phải bằng hoa hồng Cash — chứng minh phụ phí KHÔNG lọt vào hoa hồng thợ). |

## Findings (Spec vs. Implementation Gaps)
- Yêu cầu spec có nhắc "modal modifier: chọn độ dài móng, form móng" — tính năng này KHÔNG tồn tại trong pos_nail.html hiện tại. Chỉ có modal "Add Custom Item" (tên + giá + số lượng tự do), đã test thay thế ở bước này.
- Hold Ticket / Queue là localStorage phía client (key "bitpaw_held_tickets") — KHÔNG lưu server/DB. Nếu người dùng đổi trình duyệt/máy khác, vé giữ sẽ mất.