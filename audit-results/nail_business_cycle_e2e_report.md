# Nail Business Cycle E2E — Booking → Check-in → POS → Payroll

Generated: 2026-10-09T10:16:04.203Z

**9 PASS · 0 WARN · 0 FAIL**

| Step | Status | Note |
|---|---|---|
| 0. Đăng nhập chủ tiệm + chụp lưới dịch vụ | PASS | business_id=000b2c16-ab4e-42bd-944a-29c925cad09b |
| 1. Khách đặt lịch công khai (Acrylic Full Set + Ava Robertson, hôm nay) | PASS | appointment_id=155, service_id=193, staff_id=NV0053 |
| 2a. Check-in lịch hẹn trên /calendar | PASS | status badge: "Checked-In" |
| 2b. POS "Vào vé" — dịch vụ + thợ tự động vào giỏ | PASS | cart_count=1, assigned_tech=NV0053 (expected NV0053) |
| 3. Xác nhận thanh toán (Tip mặt $10 + Tip thẻ $5) | PASS | HTTP 200, order_id=1644, total=110 |
| 4a. order_id thật trong MongoDB (không chỉ RAM) | PASS | db.orders: status=completed, total_amount=110 |
| 4b. db.chamcong tăng đúng: hoa hồng + tip mặt/thẻ tách riêng | PASS | Δcommission=36.1 (kỳ vọng 36.1), Δtip_cash=10 (kỳ vọng 10), Δtip_card=4.85 (kỳ vọng 4.85 — đã trừ phí thẻ 3% trên $5 gốc = $4.85) |
| 4c. Phiếu lương 3 dòng khớp từng xu (Cash Payout / Check-Deposit / Tax Withheld) | PASS | Panel hiện: cash=$48.00, check=$604.45, tax=-$106.67, net=$652.45 — kỳ vọng: cash=$48, check=$604.45, tax=$106.67, net=$652.45 (thuế ước tính 15%, không phải engine thuế thật) |
| Console errors trong toàn bộ chu trình | PASS | 0 lỗi:  |