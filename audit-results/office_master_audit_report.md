# Office Industry Master Audit Report

Generated: 2026-09-27T02:27:39.162Z

**3 PASS · 1 WARN · 0 FAIL** (4 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Bảng Chấm Công Excel | WARN | 3712ms | URL: http://127.0.0.1:5001/chamcong_vanphong. Số dòng nhân viên: 6. console_errors=1 |
| 2 | 2. Ghi Nhận Chấm Công (Giờ Vào/Ra/OT) | PASS | 953ms | Nhân viên NV0077: 08:00-17:30, OT 1.5h, "Có mặt". HTTP 200. Dòng đã khoá sau khi lưu: true. |
| 3 | 3. Duyệt Nghỉ Phép Siêu Tốc | PASS | 2102ms | HTTP 200, body={"data":{"business_id":"e4a7e4b4-985f-4a45-a0f9-a5b1ac010e53","ghi_chu":"[HR Đã Duyệt] QA Audit — kiểm tra luồng duyệt nghỉ phép siêu tốc.","id":1203, |
| 4 | 4. Bảng Vinh Danh Kudos + Module Dùng Chung | PASS | 4851ms | Kudos: "1 Trần Văn Hải 41 BitPaw 2 Phạm Văn Nghĩa 41 BitPaw 3 Vũ Thị Hằng 31 BitPaw 4 Mai Le 19 B". Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)