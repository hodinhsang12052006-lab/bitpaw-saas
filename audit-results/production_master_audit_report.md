# Production Industry Master Audit Report

Generated: 2026-10-30T09:36:11.153Z

**3 PASS · 0 WARN · 0 FAIL** (3 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Đăng Nhập & Ghi Nhận Sản Lượng Công Nhân | PASS | 6502ms | Công nhân "NV0069", công đoạn "QA Audit Stage 1793352949813", số lượng 20. HTTP 200. Hiện trong "Bản Ghi Gần Đây": true. console_errors=0 |
| 2 | 2. Nguyên Vật Liệu & Công Thức Tiêu Hao Tự Động | PASS | 4639ms | NVL "QA Audit Vải 1793352957956" (id=23) tồn 100m. Công thức "QA Audit Stage 1793352949813": 2m/đơn vị. Ghi thêm 10 đơn vị -> kỳ vọng còn 80m, thực tế 80m. material_warnings=[] |
| 3 | 3. Chấm Công Công Nhân + Module Dùng Chung | PASS | 8511ms | Chấm công: 817 ký tự, 0 lỗi console mới. Shared: /customers=200, /ai_bot=200, /nhanvien=200, /report=200 |

## Findings (Spec vs. Implementation Gaps)