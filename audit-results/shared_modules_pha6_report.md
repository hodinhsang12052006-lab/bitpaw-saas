# Pha 6 Shared Modules Audit Report

Generated: 2026-10-24T00:57:46.640Z

**2 PASS · 0 WARN · 1 FAIL** (3 test clusters)

| # | Chức năng | Trạng thái | Thời gian | Ghi chú |
|---|---|---|---|---|
| 1 | 1. Brand Settings — Tenant F&B Lưu Xong Không Bị Đẩy Sang /spa | PASS | 7315ms | HTTP 200. URL sau khi lưu: http://127.0.0.1:5001/brand_settings. Bị đẩy sang /spa (bug cũ): false. |
| 2 | 2. Checkout Công Khai — Đăng Ký Mua Gói SaaS | FAIL | 10323ms | page.waitForSelector: Timeout 8000ms exceeded.
Call log:
[2m  - waiting for locator('#checkoutForm') to be visible[22m
 |
| 3 | 3. Quản Lý Khuyến Mãi — Tạo Mã Giảm Giá | PASS | 4946ms | Mã "QAAUDIT463829" (giảm 15%). HTTP 200. Hiện trong danh sách: true. |

## Findings