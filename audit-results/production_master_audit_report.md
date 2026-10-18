# Production Industry Master Audit Report

Generated: 2026-10-18T12:54:24.296Z

**3 PASS · 0 WARN · 0 FAIL** (3 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân | PASS | 3923ms | Công nhân "NV0069", công đoạn "QA Audit Stage 1792328049530", số lượng 20. HTTP 200. Hiện trong "Bản Ghi Gần Đây": true. console_errors=0 |
| 2 | 2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động | PASS | 3875ms | NVL "QA Audit Vải 1792328054658" (id=16) tồn 100m. Công thức "QA Audit Stage 1792328049530": 2m/đơn vị. Ghi thêm 10 đơn vị -> kỳ vọng còn 80m, thực tế 80m. material_warnings=[] |
| 3 | 3. Chấm Công Công Nhân + Module Dùng Chung | PASS | 6287ms | Chấm công: 701 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)