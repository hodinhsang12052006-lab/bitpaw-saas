# Office Industry Master Audit Report

Generated: 2026-10-09T10:15:31.895Z

**4 PASS · 0 WARN · 0 FAIL** (4 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Bảng Chấm Công Excel | PASS | 3472ms | URL: http://127.0.0.1:5001/chamcong_vanphong. Số dòng nhân viên: 6. console_errors=0 |
| 2 | 2. Ghi Nhận Chấm Công (Giờ Vào/Ra/OT) | PASS | 968ms | Nhân viên NV0077: 08:00-17:30, OT 1.5h, "Có mặt". HTTP 200. Dòng đã khoá sau khi lưu: true. |
| 3 | 3. Duyệt Nghỉ Phép Siêu Tốc | PASS | 1882ms | HTTP 200, body={"data":{"business_id":"e4a7e4b4-985f-4a45-a0f9-a5b1ac010e53","ghi_chu":"[HR Đã Duyệt] QA Audit — kiểm tra luồng duyệt nghỉ phép siêu tốc.","id":1299, |
| 4 | 4. Bảng Vinh Danh Kudos + Module Dùng Chung | PASS | 5117ms | Kudos: "1 Trần Văn Hải 41 BitPaw 2 Phạm Văn Nghĩa 41 BitPaw 3 Vũ Thị Hằng 31 BitPaw 4 Mai Le 19 B". Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)