# Production Industry Master Audit Report

Generated: 2026-10-25T06:50:55.023Z

**3 PASS · 0 WARN · 0 FAIL** (3 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân | PASS | 7250ms | Công nhân "NV0069", công đoạn "QA Audit Stage 1792911030030", số lượng 20. HTTP 200. Hiện trong "Bản Ghi Gần Đây": true. console_errors=0 |
| 2 | 2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động | PASS | 5632ms | NVL "QA Audit Vải 1792911039307" (id=21) tồn 100m. Công thức "QA Audit Stage 1792911030030": 2m/đơn vị. Ghi thêm 10 đơn vị -> kỳ vọng còn 80m, thực tế 80m. material_warnings=[] |
| 3 | 3. Chấm Công Công Nhân + Module Dùng Chung | PASS | 10710ms | Chấm công: 765 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)