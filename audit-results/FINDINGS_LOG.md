# Findings Log — Audit toàn bộ codebase (sau khi Nails hoàn tất)

Sổ theo dõi DUY NHẤT cho mọi lỗi phát hiện xuyên suốt các pha audit landing pages + 8 ngách còn lại + module dùng chung.
Mỗi dòng = 1 phát hiện thật. Trạng thái: **Fixed** (đã sửa + verify lại) / **Deferred** (biết lỗi nhưng cần quyết định sản phẩm hoặc phụ thuộc bên ngoài, chưa sửa) / **WIP-confirmed** (không phải bug, là tính năng chưa hoàn thiện đã biết trước).

---

## Đã hoàn tất trước đó — Nails (tham khảo, không lặp lại ở đây)

4 lỗi thật đã fix trong pha Nails: mascot che nút gửi AI chat (`static/js/cskh_widget.js`), sai đơn vị tiền tệ AI trả lời khách (`ai_context_engine.py`), thiếu category "Nails" ở `/add` (`templates/add_product.html`), thiếu department "Nails" ở `/nhanvien` (`templates/nhanvien.html`), thiếu field Notes ở CRM (`templates/crm.html` + `app.py`). Chi tiết đầy đủ trong lịch sử hội thoại, không lặp lại ở log này.

---

## Pha 0 — Dọn dẹp

| Ngách/Khu vực | File | Mô tả | Trạng thái |
|---|---|---|---|
| Dọn dẹp | `templates/login.html`, `templates/register.html` | Xác nhận mồ côi (grep toàn bộ `app.py` + blueprints + mọi `.html`/`.js`: không route/include/reference nào tới) | Fixed (đã xóa) |

---

## Pha 1 — Landing Pages

Script: `scripts/landing_pages_audit.mjs` (dùng chung cho cả 11 trang). Kết quả cuối: 65 PASS · 1 WARN (flaky mạng, không phải bug) · 0 FAIL.

| # | File | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `templates/landing_technical.html` | `backToTopBtn.addEventListener('click', ...)` chạy trên `null` → crash JS ngay khi tải trang (test Playwright bắt được `TypeError: Cannot read properties of null`). Nguồn gốc: trang tự viết CSS+JS `#backToTop` riêng, TRÙNG LẶP với nút mà `static/js/cskh_widget.js` (widget dùng chung, load trên mọi trang) đã tự tạo động lúc `DOMContentLoaded`. Script của trang chạy ĐỒNG BỘ, SỚM HƠN thời điểm widget tạo nút → luôn query ra `null`. | Fixed — xóa hẳn CSS+JS trùng lặp trên trang, dùng nguyên bản của widget (đã tự guard `if(backToTopBtn)` đúng cách). |
| 2 | `templates/landing.html` | Cùng gốc bug #1 nhưng nằm trong scroll listener (chỉ crash khi user CUỘN trang, không phải load ngay) — khó phát hiện hơn qua test thông thường. Thêm phát hiện: CSS `#backToTop` bị định nghĩa **trùng lặp 2 lần** trong cùng 1 file, ngay CẠNH 1 comment đã ghi rõ từ trước "không định nghĩa tĩnh ở đây nữa để tránh 3 bản định nghĩa xung đột" — rõ ràng 1 lần dọn dẹp trước đã bỏ sót đúng block này. | Fixed — xóa cả 2 bản CSS trùng + phần JS `backToTopBtn` (giữ nguyên logic `header-scrolled` không liên quan). |
| 3 | `templates/landing_hr.html`, `landing_karaoke.html`, `landing_office.html`, `landing_production.html`, `landing_retail.html` (5 file) | Cùng gốc bug #1 nhưng có `if (backToTopBtn)` guard nên không crash — chỉ khiến tính năng "về đầu trang" tự viết trên trang không bao giờ chạy (im lặng, không lỗi console) vì luôn null lúc guard-check. Code chết/trùng lặp thuần tuý. | Fixed — xóa CSS+JS trùng lặp trên cả 5 file, dùng nguyên bản của widget. |
| 4 | `templates/landing.html` (footer) | 3 link chính sách (Điều khoản sử dụng / Chính sách bảo mật / Chính sách thanh toán) đều mở cùng 1 modal với nội dung CỐ ĐỊNH "Chính sách đang được cập nhật..." — không có nội dung pháp lý thật nào cho CẢ 3 loại chính sách, trên toàn bộ site. | **Deferred** — cần nội dung Điều khoản/Chính sách bảo mật thật từ chủ doanh nghiệp (không tự soạn thảo văn bản pháp lý thay được); quan trọng cho việc nộp app lên Google Play (thường yêu cầu Privacy Policy thật). |
| — | Toàn bộ 11 trang | Đã kiểm: tải trang, title, ảnh vỡ (404), link chết, toggle EN/VI (bao gồm cả cơ chế auto-detect ngôn ngữ trình duyệt cho khách quốc tế), console errors. Không phát hiện thêm lỗi nào khác ngoài 4 mục trên. Nghi ngờ ban đầu về "copy chéo ngách" (vd trang Spa nhắc tới "nail salon") đã XÁC MINH LÀ BÁO ĐỘNG GIẢ — đến từ `components/mobile_bottom_nav.html`, menu điều hướng đổi-ngách hợp lệ dùng chung mọi trang, không phải lỗi nội dung. | Đã xác minh, không phải bug. |

---

## Pha 2 — F&B

*(sẽ điền khi audit)*

---

## Pha 3 — Spa

*(sẽ điền khi audit)*

---

## Pha 4 — Retail

*(sẽ điền khi audit)*

---

## Pha 5 — Karaoke / Hotel / Production / Technical / Office-HR

*(sẽ điền khi audit)*

---

## Pha 6 — Module dùng chung

*(sẽ điền khi audit)*
