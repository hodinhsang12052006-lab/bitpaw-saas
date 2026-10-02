# Production Industry Master Audit Report

Generated: 2026-10-02T15:31:17.467Z

**3 PASS · 0 WARN · 0 FAIL** (3 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân | PASS | 5966ms | Công nhân "NV0069", công đoạn "QA Audit Stage 1790955057443", số lượng 20. HTTP 200. Hiện trong "Bản Ghi Gần Đây": true. console_errors=0 |
| 2 | 2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động | PASS | 4241ms | NVL "QA Audit Vải 1790955064730" (id=10) tồn 100m. Công thức "QA Audit Stage 1790955057443": 2m/đơn vị. Ghi thêm 10 đơn vị -> kỳ vọng còn 80m, thực tế 80m. material_warnings=[] |
| 3 | 3. Chấm Công Công Nhân + Module Dùng Chung | PASS | 9063ms | Chấm công: 712 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)