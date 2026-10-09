# Nail Industry Master Audit Report

Generated: 2026-10-09T11:32:20.732Z

**10 PASS · 0 WARN · 0 FAIL** (10 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Khởi tạo & Giao diện POS Nails | PASS | 5138ms | console_errors=0, network_5xx=0, services=20, technicians=8, search_placeholder="Search services, techs, code..." |
| 2 | 2. Chọn Dịch Vụ & Modifier/Custom Item | PASS | 2420ms | Đã thêm: Acrylic Full Set (Ombre/Design), Callus Treatment & Heel Scrub + 1 Custom Item ($15). Tổng 3 dòng trong giỏ. |
| 3 | 3. Gán Thợ & Quản Lý Vé (Hold/Resume) | PASS | 2095ms | Thợ gán: "Ava Robertson" (NV0053). Badge hàng chờ sau Hold: 1. Giỏ trước Hold=3, sau Resume=3. |
| 4 | 4. Tính Tiền, Tip & Payment Modal | PASS | 1141ms | Total: "$230.00 AUD" -> "$238.00 AUD" (Tip: +$8.00). Dual-pricing UI toggle tồn tại: true. |
| 5 | 5. Xác Nhận Thanh Toán & Lưu DB | PASS | 1271ms | HTTP 200, order_id=1781, total_amount=238, receipt hiển thị: "Order #1781" |
| 6 | 6. Lịch Sử Hóa Đơn & In Lại Bill | PASS | 1988ms | Số dòng lịch sử hôm nay: 287. Đơn #1781 xuất hiện trong danh sách: true. |
| 7 | 7. Đối Soát Chấm Công & Payroll (US) | PASS | 2607ms | 8 nhân viên hiển thị. Lịch sử "Tính Tua" của thợ vừa gán có dữ liệu mới: true. Snippet: "[NAILS POS] ORDER #1781 — 40.0 09/10/2026 $80.11 Pay: $72.2 \| Tip: $7.91 [NAILS POS] ORDER #1779 — 40.0 09/10/2026 $36.10 Pay: $36.1 \| Tip: $0 [NAILS POS] ORDER #1778 — 40.0 09/10/2026 $36.1" |
| 8 | 8. Booking Website Công Khai + QR Code | PASS | 7334ms | Business "000b2c16-ab4e-42bd-944a-29c925cad09b" — public page: 20 dịch vụ / 8 thợ. Đặt lịch HTTP 200, appointment id=162, ticket="TICKET-162". Xuất hiện trong /calendar của chủ tiệm: true. Console errors (trang khách): 0. |
| 9 | 9. Giảm Giá, Thanh Toán Chia Đôi & Hoàn Tiền | PASS | 5573ms | Discount preview: $9.50 (áp dụng: true). Split total=85.5, cash=card=42.75, mismatch=false, order_id=1782. Refund order #1782: true ({"order_status":"partially_refunded","refund_id":1783,"success":true,"techs_clawed_back":[]}). |
| 10 | 10. Dual Pricing (Cash Price / Card Price) | PASS | 7178ms | UI: cash=$95 card=$97.85 (kỳ vọng $97.85). Order Cash #1784: total=95, hoa hồng=36.1. Order Card #1785: total=97.85, subtotal=95, phụ phí=2.85, hoa hồng=36.1 (phải bằng hoa hồng Cash — chứng minh phụ phí KHÔNG lọt vào hoa hồng thợ). |

## Findings (Spec vs. Implementation Gaps)
- Yêu cầu spec có nhắc "modal modifier: chọn độ dài móng, form móng" — tính năng này KHÔNG tồn tại trong pos_nail.html hiện tại. Chỉ có modal "Add Custom Item" (tên + giá + số lượng tự do), đã test thay thế ở bước này.
- Hold Ticket / Queue là localStorage phía client (key "bitpaw_held_tickets") — KHÔNG lưu server/DB. Nếu người dùng đổi trình duyệt/máy khác, vé giữ sẽ mất.