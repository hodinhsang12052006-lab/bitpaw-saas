# Findings Log — Audit toàn bộ codebase (sau khi Nails hoàn tất)

Sổ theo dõi DUY NHẤT cho mọi lỗi phát hiện xuyên suốt các pha audit landing pages + 8 ngách còn lại + module dùng chung.
Mỗi dòng = 1 phát hiện thật. Trạng thái: **Fixed** (đã sửa + verify lại) / **Deferred** (biết lỗi nhưng cần quyết định sản phẩm hoặc phụ thuộc bên ngoài, chưa sửa) / **WIP-confirmed** (không phải bug, là tính năng chưa hoàn thiện đã biết trước).

---

## Đã hoàn tất trước đó — Nails (tham khảo, không lặp lại ở đây)

4 lỗi thật đã fix trong pha Nails: mascot che nút gửi AI chat (`static/js/cskh_widget.js`), sai đơn vị tiền tệ AI trả lời khách (`ai_context_engine.py`), thiếu category "Nails" ở `/add` (`templates/add_product.html`), thiếu department "Nails" ở `/nhanvien` (`templates/nhanvien.html`), thiếu field Notes ở CRM (`templates/crm.html` + `app.py`). Chi tiết đầy đủ trong lịch sử hội thoại, không lặp lại ở log này.

---

## Pha 1.5 — Kiểm thử bảo mật (Penetration Test được ủy quyền, chỉ trên server local)

Rà soát code (2 agent đọc `app.py` 12.785 dòng + blueprints + JS/HTML liên quan) rồi tự tay xác nhận trực tiếp bằng PoC thật chạy trên `http://127.0.0.1:5001` (không đụng production). Toàn bộ payload test đã dọn sạch khỏi DB ngay sau khi verify.

| # | Mức độ | Lỗi | File:dòng | PoC xác nhận | Trạng thái |
|---|---|---|---|---|---|
| 1 | 🔴 CRITICAL | NoSQL Injection (toán tử MongoDB) | `app.py` `_resolve_portal_customer()` (được `/api/portal/messages` dùng chung) | Gửi `{"customer_id": {"$ne": null}, ...}` (không cần biết customer_id thật) → HTTP 200, khớp bừa vào dữ liệu của tenant `superadmin-fallback`; đổi sang `{"$regex": "^000b2c16"}` → ghi được vào đúng business_id Nails mà kẻ tấn công chỉ đoán mù tiền tố. Sau fix: cùng payload → HTTP 404, bị từ chối. | **Fixed** — thêm `isinstance(customer_id, str)` chặn tận gốc tại hàm dùng chung. |
| 2 | 🔴 CRITICAL | Stored XSS (chuỗi tấn công nối tiếp lỗi #1) | `templates/ai_bot.html` (`appendUserMessageStatic`/`appendAIMessageStatic`/danh sách khách hàng) | Gửi tin nhắn thật chứa `<img src=x onerror="...">` qua route công khai → đăng nhập chủ tiệm Nails thật, mở `/ai_bot`, script THỰC THI THẬT trong session đã đăng nhập (xác nhận bằng biến `window.__xss_poc` được set). Sau fix: cùng payload → hiển thị dạng chữ thường, không thực thi. | **Fixed** — thêm `escapeHtml()` (copy đúng mẫu đã dùng ở `portal.html`), áp dụng cho nội dung tin nhắn VÀ tên/preview khách hàng trong danh sách (phát hiện thêm 1 điểm hở thứ 2 khi rà tay). |
| 3 | 🟠 HIGH | Stored XSS (cùng lớp lỗi, widget công khai) | `static/js/cskh_widget.js` (`appendMessage`) | Cùng cơ chế lỗi #2 nhưng ảnh hưởng widget chat trên MỌI trang landing công khai. | **Fixed** — thêm `escapeHtml()`, mặc định escape mọi tin nhắn; 1 chỗ cần giữ HTML thật (dòng hiện SĐT Zalo `<strong>`) sửa để tự escape riêng phần dữ liệu động trước khi ghép, không escape nhầm cấu trúc HTML cố định. |
| 4 | 🟡 LOW | So sánh secret không an toàn thời gian | `app.py` `cron_daily_tasks()` | So sánh tay bằng logic, không PoC thực thi (CRON_SECRET chưa cấu hình ở môi trường này nên luôn 401 sẵn) — fix theo nguyên tắc phòng thủ chuẩn. | **Fixed** — đổi `!=` thành `hmac.compare_digest()`, khớp đúng cách webhook Square trong CÙNG file đã làm đúng. |
| 5 | 🟡 LOW | Không kiểm tra độ dài mật khẩu | `app.py` `register()` | Xác nhận qua đọc code: mật khẩu rỗng/1 ký tự đi thẳng vào `generate_password_hash()` không chặn. | **Fixed** — thêm chặn `len(password) < 8`. |
| 6 | 🟡 LOW | Thiếu header `X-Content-Type-Options: nosniff` | Toàn bộ response (`app.py`) | Xác nhận bằng `curl -I` — header vắng mặt hoàn toàn trước fix, có mặt sau fix. | **Fixed** — thêm `@app.after_request` mới, không đụng hook cache-control có sẵn. |

**Test khả năng chịu lỗi (không phải DoS — chỉ input dị dạng có kiểm soát)**: 10 case (JSON sai định dạng, kiểu dữ liệu sai, mảng lồng sâu, chuỗi 200KB, null-byte, emoji cực đoan) gửi tới login/portal-messages/cskh-chat/ai-generate — tất cả trả về 4xx/5xx gọn gàng, server sống xuyên suốt, không traceback crash tiến trình. Script giữ lại: `scripts/security_crash_resilience_audit.mjs`.

**Regression check**: chạy lại `nail_ai_bot_customer_care_e2e.mjs` sau khi fix — 6/6 PASS, xác nhận việc thêm escapeHtml không làm hỏng luồng chat AI hợp lệ bình thường.

### Đã rà soát, xác nhận AN TOÀN — không cần fix
JWT thuật toán hardcode HS256 (chặn `alg:none`/RS256-confusion) · webhook Square verify HMAC đúng chuẩn, fail-closed, so sánh an toàn thời gian sẵn có · IDOR: rà ~50 route mutating theo ID, TẤT CẢ lọc đúng `business_id` · SSRF: không route nào fetch URL do client cung cấp · Upload file: allowlist đuôi file chặt (không cho .svg/.html), Content-Type ép theo đuôi đã validate, `secure_filename()` đầy đủ.

### Deferred — cần quyết định kiến trúc/sản phẩm, không phải fix 1 dòng
- **JWT không có cơ chế thu hồi**: đổi mật khẩu/xóa tài khoản không làm JWT cũ (sống tới 30 ngày) hết hạn ngay — cần session-versioning hoặc blocklist.
- **Không rate-limit riêng route thanh toán/hoàn tiền** (`/api/orders/<id>/refund`, `/api/payments/square/*`) — cần bàn ngưỡng hợp lý, không làm nghẽn thao tác thật của thu ngân.
- **`/api/cskh/chat/messages` khoá theo SĐT đoán được** — đánh đổi CÓ CHỦ ĐÍCH đã ghi nhận sẵn trong code (khách vãng lai không cần đăng nhập), không tự ý đổi kiến trúc.
- **Session/role không re-validate với DB mỗi request** (thiết kế session ký sẵn chuẩn Flask) — cần server-side session store để đổi, ngoài phạm vi 1 lần fix.

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
| 4 | `templates/landing.html` (footer) | 3 link chính sách (Điều khoản sử dụng / Chính sách bảo mật / Chính sách thanh toán) đều mở cùng 1 modal với nội dung CỐ ĐỊNH "Chính sách đang được cập nhật..." — không có nội dung pháp lý thật nào cho CẢ 3 loại chính sách, trên toàn bộ site. Cộng thêm 1 bug thật phát hiện lúc quay lại sửa (Pha 7): dòng code lấy NỘI DUNG modal dùng CHUNG đúng 1 key `modal_content_placeholder` cho cả 3 loại (chỉ dòng lấy TIÊU ĐỀ có rẽ nhánh theo `type`) — bấm cả 3 link đều ra y hệt 1 câu, dù đã có `type` truyền đúng. | **Fixed (bản nháp — cần chủ doanh nghiệp/luật sư duyệt lại)**. Theo yêu cầu Pha 7 ("test lại + đưa lên CH Play"), đã soạn nội dung Điều khoản/Chính sách bảo mật/Chính sách thanh toán đầy đủ (VI+EN) dựa ĐÚNG trên những gì app thực sự thu thập/vận hành (đã audit kỹ toàn phiên: dữ liệu tài khoản/nhân viên/khách hàng, GridFS lưu ảnh, Square/Stripe/VietQR cho thanh toán, DeepSeek AI cho chat) — thêm vào `translations/vi.json`+`en.json` (key `terms_content`/`privacy_content`/`payment_content`), sửa `openModal()` trong `landing.html` rẽ nhánh đúng theo `type`. 10 trang landing ngách còn lại (mỗi trang tự viết `openModal()` riêng, không dùng chung file JSON) được trỏ về đúng 1 nguồn nội dung duy nhất tại `/landing` thay vì chép lại y hệt ~2000 từ luật vào 11 nơi (tránh lệch nội dung về sau). Đã verify bằng Playwright thật trên cả 11 trang, cả 2 ngôn ngữ — không còn placeholder, không lỗi JS. **CẢNH BÁO**: đây là nội dung do AI soạn dựa trên hành vi thật của app, có các chỗ `[để trong ngoặc vuông]` cần điền thông tin pháp lý cụ thể (tên pháp nhân, mã số thuế, địa chỉ, email liên hệ) — chủ doanh nghiệp/luật sư BẮT BUỘC phải duyệt lại trước khi coi là chính sách chính thức, đặc biệt trước khi nộp lên Google Play. |
| — | Toàn bộ 11 trang | Đã kiểm: tải trang, title, ảnh vỡ (404), link chết, toggle EN/VI (bao gồm cả cơ chế auto-detect ngôn ngữ trình duyệt cho khách quốc tế), console errors. Không phát hiện thêm lỗi nào khác ngoài 4 mục trên. Nghi ngờ ban đầu về "copy chéo ngách" (vd trang Spa nhắc tới "nail salon") đã XÁC MINH LÀ BÁO ĐỘNG GIẢ — đến từ `components/mobile_bottom_nav.html`, menu điều hướng đổi-ngách hợp lệ dùng chung mọi trang, không phải lỗi nội dung. | Đã xác minh, không phải bug. |

---

## Pha 2 — F&B

Bản đồ chức năng: `templates/pos.html` (POS bàn ăn, dùng CHUNG cho F&B/Retail/Spa/Karaoke/Hotel — không riêng F&B), `templates/kitchen_display.html` (SSE real-time), `templates/table_order.html`/`qr_menu.html` (khách tự gọi món qua QR), `templates/table_reservation_public.html` (đặt bàn công khai), `templates/chamcong_fnb.html` (chấm công + chia tip pool). Demo tenant tạo mới qua `setup_demo_other_industries.py` (`setup_fnb()`): `demo.fnb.343602@bitpawdemo.com` / business_id `39821fa8-e42a-4052-bc9d-eb061eaaae11`, 9 sản phẩm/8 khách/19 đơn/6 nhân viên/12 bàn.

Script: `scripts/fnb_industry_master_audit.mjs` (giữ lại vĩnh viễn, theo mẫu `nail_industry_master_audit.mjs`). Kết quả cuối: **7 PASS · 1 WARN · 0 FAIL**.

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `templates/pos.html` (`loadTables()`/`addTable()`) | Tên bàn tiếng Việt có dấu (vd "Bàn 1") bị lọc/hiển thị sai do so sánh chuỗi thủ công từng biến thể có/không dấu (`'bàn'.includes('ban')` = `false` trong JS vì dấu là code point Unicode khác hẳn) — bàn tạo bằng tiếng Việt biến mất khỏi lưới hiển thị dù ghi DB thành công. Phát hiện khi rà selector trước khi viết script test, KHÔNG phải lúc chạy script. | **Fixed** — thêm hàm dùng chung `stripDiacritics()`, áp dụng cho cả 4 nhánh ngành (nail/spa/karaoke-hotel/fnb) ở cả 2 nơi thay vì liệt kê tay từng biến thể. |
| 2 | `templates/pos.html:1135` (`renderMenu()` click handler) | **Lỗi thật nghiêm trọng**: `currentProductId` lấy thẳng từ `data-product-id` (chuỗi DOM) KHÔNG ép kiểu số, trong khi `products.id` trong MongoDB luôn là số nguyên (`next_mongo_id()`). Mọi lần thêm món vào bàn thật → `POST /api/pos/tables/<id>/orders` với `product_id` là chuỗi → `db.products.find_one({'id': "123", ...})` không khớp số nguyên `123` → **luôn trả 403 "Product not found"** → JS âm thầm fallback sang giỏ hàng chỉ lưu `localStorage`, KHÔNG ghi DB thật. PoC xác nhận bằng script debug: trước fix có `console.warn("Flask API save failed...")` + 403; sau fix không còn. | **Fixed** — `currentProductId = parseInt(el.getAttribute('data-product-id')) \|\| null;`, khớp đúng pattern `currentProductPrice` đã làm ngay dòng kế bên. |
| 3 | `templates/pos.html:1489` (`selectTable()`) + `app.py` `_assert_owns_table()`/`api_payment_start`/`api_payment_confirm`/`api_table_notify` | **Lỗi thật nghiêm trọng, chặn đứng toàn bộ luồng thanh toán**: `selectedTableId` giữ nguyên dạng chuỗi từ `data-table-id`, gửi thẳng vào JSON body của `/api/payment/start` và `/api/payment/confirm`. `_assert_owns_table()` so sánh `db.dining_tables.find_one({'id': table_id})` với `table_id` là chuỗi trong khi `dining_tables.id` luôn là số nguyên → **luôn trả 403 "Table not found."** → nút "Thanh toán"/"Chia đôi" không bao giờ hoạt động được cho bất kỳ bàn thật nào (chỉ bàn nháp local/seeded mới né được vì đi đường `local_checkout` riêng). Cùng lỗi lặp lại ở `payment_pending.html` (đọc `table_id` từ `URLSearchParams`, cũng luôn là chuỗi) khi gọi `/api/payment/confirm`. PoC: trước fix `/api/payment/start` trả `{"message":"Table not found.","success":false}` (403); sau fix trả `{"success":true,"redirect_url":...}` và toàn bộ luồng cash/split thanh toán thành công tới `/payment_success`. | **Fixed** — 2 lớp: (1) client `pos.html` ép `selectedTableId` sang số nguyên ngay tại `selectTable()` (giữ nguyên dạng chuỗi cho bàn nháp `seeded-`/`local-`); (2) server `_assert_owns_table()` (hàm dùng chung cho 4 route) tự ép kiểu `table_id` nếu là chuỗi số thuần, cộng thêm helper `_coerce_table_id()` áp dụng trong `api_payment_confirm`/`api_table_notify` cho các câu query Mongo khác dùng lại `table_id` sau bước xác thực quyền sở hữu. Fix ở tầng server đảm bảo an toàn ngay cả khi 1 client khác (vd `api_us_payment_start` — nút Square) gửi `table_id` sai kiểu tương tự. |
| — | Toàn bộ luồng F&B | Đã kiểm: đăng nhập + tải POS (bàn+menu), chọn bàn + thêm món, thanh toán tiền mặt qua luồng thật `/api/payment/start` → `/payment_pending` → `/api/payment/confirm` → `/payment_success`, chọn phương thức Chia đôi (Split), khách quét QR tự gọi món (`/api/submit_qr_order`) → Kitchen Display nhận đơn real-time qua SSE KHÔNG cần reload, đặt bàn công khai (khách vãng lai không đăng nhập) qua `/reserve/<business_id>`, trang chấm công + chia tip pool (`/chamcong_fnb`), module dùng chung cho ngách F&B (`/customers`, `/ai_bot`, `/nhanvien`, `/report`). Sau khi fix 3 lỗi trên: **7/8 cụm test PASS, 0 FAIL**. | Đã xác minh bằng PoC thật (không chỉ đọc code), verify lại 2 lần sau mỗi fix. |
| 4 | Toàn bộ trang đã đăng nhập (không riêng F&B) | `/favicon.ico` trả 404 — không phải bug riêng F&B: dự án KHÔNG dùng shared base template (`{% extends %}`), mỗi trang tự viết `<head>` riêng; các trang landing công khai có `<link rel="icon">` qua component `seo_meta.html`, nhưng ~90 trang sau đăng nhập (`pos.html`, `dashboard.html`, `crm.html`, `kitchen_display.html`...) không khai báo, nên trình duyệt tự động xin `/favicon.ico` và luôn nhận 404 (xác nhận qua `curl -I`). Chỉ là 1 dòng console warning vô hại, không ảnh hưởng chức năng — đã thấy XUẤT HIỆN GIỐNG HỆT khi chạy lại regression Nails (`pos_nail.html`), xác nhận đây là vấn đề TOÀN HỆ THỐNG chứ không phải lỗi riêng của Pha 2. | **Deferred** — để dành cho Pha 6 (module dùng chung), vì sửa đúng cách cần thêm `<link rel="icon">` nhất quán trên hàng chục file thay vì vá lẻ tẻ trong phạm vi 1 ngách. |

**Regression check**: chạy lại `nail_industry_master_audit.mjs` sau khi sửa `app.py`/`pos.html` (Nails dùng `pos_nail.html` — template hoàn toàn riêng, không đụng `pos.html`, nhưng `_assert_owns_table`/`_coerce_table_id` là code Python dùng chung) — **9/10 PASS, 1 WARN (đúng lỗi favicon giống hệt trên, không phải lỗi mới), 0 FAIL**. Xác nhận fix F&B không phá vỡ Nails.

---

## Pha 3 — Spa

Bản đồ chức năng: Spa dùng kiến trúc "1 ngành = 1 file" riêng — `blueprints/spa_bp.py` (route `/spa`, `/add_spa`, `/booking/qr/<spa_id>`, `/create_appointment`, `/chamcong/spa`), template `templates/spa.html` (giỏ hàng + checkout qua `/api/sales/checkout`, KHÔNG dùng chung `pos.html` với F&B/Retail), `templates/booking.html` (đặt lịch công khai), `templates/chamcong_spa.html`. Demo tenant có sẵn từ trước: `demo.spa.596348@bitpawdemo.com` / business_id `3cd48d09-8028-486d-82da-038db3ac2892` (8 dịch vụ/8 khách/4 nhân viên).

Script: `scripts/spa_industry_master_audit.mjs` (giữ lại vĩnh viễn). Kết quả cuối: **5 PASS · 1 WARN · 0 FAIL**.

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `templates/spa.html` (`updatePaymentFormVisibility()`) | **Lỗi thật NGHIÊM TRỌNG, chặn đứng toàn bộ luồng thanh toán Spa**: hàm gọi `document.getElementById('cryptoAddressBox').classList.add('hidden')` ngay dòng đầu tiên, nhưng phần tử `#cryptoAddressBox` **không tồn tại ở bất kỳ đâu trong HTML** — ném `TypeError: Cannot read properties of null` ngay lập tức. Hàm này được gọi ngay khi bấm nút "Checkout Now" (`openCheckoutModalBtn`), TRƯỚC dòng lệnh hiện modal thanh toán → exception chặn đứng toàn bộ hàm → **modal thanh toán KHÔNG BAO GIỜ hiện ra, với BẤT KỲ phương thức thanh toán nào (cash/card/QR/crypto...)**, không có bất kỳ thông báo lỗi nào cho người dùng — chỉ im lặng không có gì xảy ra khi bấm nút. Xác nhận bằng debug script: trước fix `modalVisible: false` sau khi click; sau fix `modalVisible: true`, thanh toán thành công tới `/api/sales/checkout`. | **Fixed** — thêm `<div id="cryptoAddressBox">` còn thiếu (hiển thị địa chỉ ví USDT demo, khớp đúng ý đồ code JS sẵn có ở dòng lân cận `qrCodeBlock`/`redirectBlock`), thêm i18n key `spa_crypto_address_label` (VI+EN). |
| 2 | `templates/spa.html:711` (grid dịch vụ `#servicesGrid`) | Ảnh dịch vụ vỡ 100% (16 lỗi 404 mỗi lần tải trang, x2 vì DOM re-render): template luôn bọc `s.image` bằng `url_for('static', filename='uploads/' + s.image)`, giả định `image` luôn là tên file upload cục bộ — nhưng dữ liệu demo (và về nguyên tắc, bất kỳ URL ảnh ngoài nào) lưu URL ĐẦY ĐỦ (`https://images.unsplash.com/...`), tạo ra URL vỡ dạng `/static/uploads/https://images.unsplash.com/...`. Cùng field `products.image` ở `pos.html` (F&B/Retail/Karaoke/Hotel) xử lý ĐÚNG bằng cách gán thẳng `p.image` vào `src` không qua `url_for` — `spa.html` là nơi DUY NHẤT làm sai kiểu này. | **Fixed** — thêm điều kiện `{{ s.image if s.image.startswith('http') else url_for(...) }}`, hỗ trợ cả URL ngoài lẫn file upload cục bộ, khớp đúng hành vi `pos.html` đã làm đúng. |
| 3 | `blueprints/spa_bp.py:110` (`checkout_spa()`) | Dead code: route form-POST cũ hoàn toàn KHÔNG được gọi từ bất kỳ template nào (`spa.html` thật sự dùng `/api/sales/checkout`, đã xác nhận bằng grep toàn bộ `templates/`). Route này còn mang lỗi lệch kiểu `product_id` giống lỗi #2/#3 của Pha 2 F&B (`request.form['product_id']` là chuỗi, so trực tiếp với `id` số nguyên trong Mongo) — nhưng vì không route/link nào gọi tới nên KHÔNG có tác động thật. | **Deferred** — không sửa bug trong code chết; đề xuất xoá hẳn `checkout_spa()` ở 1 đợt dọn dẹp code thừa riêng (Pha 6), không tự ý xoá route đang hoạt động (dù không ai gọi) giữa lúc đang audit tính năng khác. |
| — | Toàn bộ luồng Spa | Đã kiểm: đăng nhập + tải trang dịch vụ, thêm dịch vụ vào giỏ + mở modal checkout, thanh toán tiền mặt qua `/api/sales/checkout`, đặt lịch công khai qua QR (`/booking/qr/<spa_id>`) kèm regression-test lại đúng lỗ hổng cách ly đa tiệm đã vá trước đây (`/booking` thiếu `spa_id` → xác nhận trả về 0 dịch vụ, không trộn dữ liệu tiệm khác), lịch hẹn hiện đúng trên `/calendar` chủ tiệm, trang chấm công (`/chamcong/spa`), module dùng chung (`/customers`, `/ai_bot`, `/nhanvien`, `/report`). Sau khi fix 2 lỗi #1-#2: **5/6 cụm test PASS, 0 FAIL**. | Đã xác minh bằng chạy thật (không chỉ đọc code), verify lại sau mỗi fix. |
| 4 | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — CÙNG lỗi cross-cutting đã ghi nhận ở Pha 2 (không phải bug riêng Spa). | **Deferred** — gộp chung xử lý ở Pha 6. |

---

## Pha 4 — Retail

Bản đồ chức năng: kiến trúc "1 ngành = 1 file" — `blueprints/retail_bp.py` (route `/retail_pos`), template `templates/retail_pos.html` (lưới sản phẩm + giỏ hàng + quét mã vạch USB, checkout qua `/api/sales/checkout` dùng chung, hoàn tiền qua `/api/orders/<id>/refund` dùng chung). Demo tenant có sẵn từ trước: `demo.retail.596348@bitpawdemo.com` / business_id `c13211e0-a360-473c-afb0-69f7e0adcf55`.

Script: `scripts/retail_industry_master_audit.mjs` (giữ lại vĩnh viễn). Kết quả cuối: **5 PASS · 1 WARN · 0 FAIL**.

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | Dữ liệu (MongoDB `products`, business_id retail) | Phát hiện 4 bản ghi "Audit Test Product"/"Audit Test Product 2" (id 255/257/259/261) tồn đọng từ 1 lượt test trước đây (không thuộc phiên audit hiện tại, không rõ nguồn), vi phạm nguyên tắc "dọn sạch payload test khỏi DB ngay sau khi verify" đã áp dụng xuyên suốt. Không có `order_items` nào tham chiếu tới các id này (an toàn để xoá). | **Fixed** — xoá 4 bản ghi rác, xác nhận lại còn đúng 8 sản phẩm demo thật. |
| 2 | Dữ liệu demo (thiếu, không phải bug code) | Không sản phẩm demo nào có field `barcode` — tính năng quét mã vạch (`#barcodeInput` → `/api/products/lookup_barcode`) chỉ test được nhánh lỗi "không tìm thấy", không test được nhánh thành công thật. | **Fixed** — gán barcode thật cho 2 sản phẩm demo (Coca-Cola/Mì Hảo Hảo), script audit giờ test đủ cả 2 nhánh. |
| — | Toàn bộ luồng Retail (code) | `retail_pos.html` là bản POS **sạch nhất trong 3 mẫu non-Nail đã audit** (F&B/Spa/Retail) — không phát hiện lỗi lệch kiểu dữ liệu (product id đã `parseInt()` đúng ngay từ đầu), không phần tử DOM nào bị thiếu, ảnh sản phẩm không dùng (chỉ hiện icon/tên/giá/mã vạch nên không dính lỗi ảnh vỡ như Spa). Đã kiểm: đăng nhập, tìm kiếm/lọc, thêm giỏ hàng (click + quét mã vạch), thanh toán tiền mặt qua `/api/sales/checkout`, hoàn tiền một phần qua `/api/orders/<id>/refund`, module dùng chung. **5/6 cụm test PASS, 0 FAIL.** | Đã xác minh bằng chạy thật (không chỉ đọc code). |
| 3 | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — CÙNG lỗi cross-cutting đã ghi nhận ở Pha 2/3 (không phải bug riêng Retail). | **Deferred** — gộp chung xử lý ở Pha 6. |

---

## Pha 5 — Karaoke / Hotel / Production / Technical / Office-HR

### Karaoke

Bản đồ chức năng: kiến trúc riêng — route `/karaoke` (`karaoke.html`), API thật `/api/karaoke/rooms*` (tính giờ phòng, làm tròn 15 phút, tự tạo sản phẩm "Phí Giờ Karaoke" nếu chưa có), đặt phòng công khai `/karaoke/reserve/<business_id>` + quản trị `/karaoke/reservations` (có chặn trùng giờ theo phòng). Demo tenant sẵn có: `demo.karaoke.071443@bitpawdemo.com` / business_id `0cc47d38-b306-46f3-9da1-cdf2d840d79b` (7 phòng).

Script: `scripts/karaoke_industry_master_audit.mjs`. Kết quả: **3 PASS · 1 WARN · 0 FAIL**.

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `app.py` route `/toggle_room/<int:room_id>` | Dead code — không template nào gọi tới nữa (`karaoke.html` dùng `/api/karaoke/rooms/<id>/start` + `/checkout` hiện đại hơn). Route cũ không có lỗi lệch kiểu (dùng `<int:room_id>` converter) nhưng thừa, trùng logic. | **Deferred** — dọn dẹp code thừa ở Pha 6, không tự ý xoá giữa lúc audit tính năng khác. |
| 2 | `app.py` `INDUSTRY_CONFIG['karaoke']['modules']` khai `'pos_ordering'` | Không có UI tương ứng trong `karaoke.html` — không có giỏ hàng gọi đồ uống/đồ ăn trong lúc chơi, chỉ tính tiền phòng theo giờ khi chốt phòng. | **WIP-confirmed** — spec vs. implementation gap, không phải bug. |
| — | Toàn bộ luồng Karaoke | Đã kiểm: mở phòng (Start) → chốt phòng tính giờ tự động tạo order+transaction thật, đặt phòng công khai qua QR (khách vãng lai) → xuất hiện đúng trên trang quản trị lọc theo ngày, chấm công, module dùng chung. Route API thật (không phải route cũ `/toggle_room`) đã được viết cẩn thận, tự tạo sản phẩm phí phòng nếu thiếu, atomic tránh race condition khi 2 người cùng bấm Start. **3/4 cụm test PASS, 0 FAIL.** | Đã xác minh bằng chạy thật. |
| 3 | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — cùng lỗi cross-cutting đã ghi nhận từ Pha 2. | **Deferred** — Pha 6. |

### Hotel

Bản đồ chức năng: `/hotel_rooms` (sơ đồ phòng, nhận/trả phòng, phụ thu dịch vụ đi kèm, dọn phòng), `/hotel/reserve/<business_id>` + `/hotel/reservations` (đặt phòng công khai + quản trị, có chặn trùng lịch). Demo tenant: `demo.hotel.071443@bitpawdemo.com` / business_id `885e1075-9191-4b1e-91ee-d100e961257d` (7 phòng).

Script: `scripts/hotel_industry_master_audit.mjs`. Kết quả: **4 PASS · 1 WARN · 0 FAIL**.

| # | Mô tả | Trạng thái |
|---|---|---|
| — | Toàn bộ luồng Hotel: nhận phòng (atomic, chặn race condition) → thêm phụ thu dịch vụ đi kèm (minibar) → trả phòng tự tính đúng số đêm × giá phòng + tổng phụ thu (đã verify bằng số: 650.000đ tiền phòng + 150.000đ phụ thu = 800.000đ tổng, khớp chính xác) → dọn phòng (housekeeping status flow "Đang ở" → "Đang dọn" → "Trống") → đặt phòng công khai qua QR → hiện đúng trên trang quản trị. Toàn bộ route dùng `<int:room_id>` URL converter nên KHÔNG dính lỗi lệch kiểu dữ liệu như các route JSON-body ở Pha 2. **4/5 cụm test PASS, 0 FAIL — không tìm thấy lỗi code thật nào.** | Đã xác minh bằng chạy thật với số liệu cụ thể. |
| — | (Sửa test script, không phải bug ứng dụng) | Lần chạy đầu tiên FAIL do chính script test dùng `text=Trống` để tìm phòng trống — nhãn trạng thái đi qua `t('hr_status_empty')` (i18n), không phải chữ cứng. Sửa lại dùng class CSS `.status-trong` (không dịch) — PASS ngay. | Đã sửa script, không đụng code ứng dụng. |
| — | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — cùng lỗi cross-cutting. | **Deferred** — Pha 6. |

### Production (Sản Xuất)

Bản đồ chức năng: `/production_output` (ghi nhận sản lượng công nhân theo công đoạn), `/production/materials` (quản lý nguyên vật liệu + công thức tiêu hao NVL/đơn vị sản lượng — tự động trừ kho khi ghi sản lượng khớp công thức, cho phép âm kho kèm cảnh báo thay vì chặn cứng). Demo tenant: `demo.production.393328@bitpawdemo.com` (7 công nhân).

Script: `scripts/production_industry_master_audit.mjs`. Kết quả: **2 PASS · 1 WARN · 0 FAIL**.

| # | Mô tả | Trạng thái |
|---|---|---|
| — | Toàn bộ luồng Production, đặc biệt tính năng phức tạp nhất: tạo nguyên vật liệu (tồn 100m) → tạo công thức (1 đơn vị sản lượng tiêu 2m) → ghi nhận thêm 10 đơn vị sản lượng cho ĐÚNG công đoạn có công thức → xác nhận tồn kho tự động trừ CHÍNH XÁC 80m (100 - 10×2) qua API thật, không lệch. `material_id` được ép kiểu `int()` đúng ngay tại điểm nhận dữ liệu ở CẢ client (`parseInt`) lẫn server — không dính lỗi lệch kiểu như Pha 2. **2/3 cụm test PASS, 0 FAIL — không tìm thấy lỗi code thật nào.** Đã dọn sạch dữ liệu test (2 bản ghi sản lượng, 1 NVL, 1 công thức) khỏi DB demo ngay sau khi verify. | Đã xác minh bằng số liệu cụ thể, không chỉ đọc code. |
| — | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — cùng lỗi cross-cutting. | **Deferred** — Pha 6. |

### Technical (Kỹ Thuật)

Ngách MỎNG nhất (chỉ `attendance` + `dispatch_gps` trong `INDUSTRY_CONFIG`) — trang chủ đăng nhập thẳng vào chấm công (`chamcong_kythuat.html`), không có module bán hàng/đặt lịch riêng. Demo tenant: `demo.technical.393328@bitpawdemo.com` (5 kỹ thuật viên).

Script: `scripts/technical_industry_master_audit.mjs`. Kết quả: **2 PASS · 1 WARN · 0 FAIL**.

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `templates/chamcong_kythuat.html:899` | **Lỗi thật**: nút "Xem trên bản đồ" (GPS check-in) kiểm tra field `r.toa_do` — field này KHÔNG TỒN TẠI trong schema thật (`db.chamcong` lưu GPS bằng 2 field riêng `latitude`/`longitude`, xác nhận qua `app.py:11493`) → điều kiện luôn `false` → nút **không bao giờ hiện ra** cho bất kỳ bản ghi nào, dù có toạ độ hay không. Cộng thêm URL đích hoàn toàn sai định dạng: `http://googleusercontent.com/maps.google.com/?q=...` (không phải URL Google Maps hợp lệ). Xác nhận thêm: `submitTech()` (hàm gửi chấm công của chính trang này) KHÔNG hề gọi `navigator.geolocation` — không có nơi nào trong toàn bộ code thực sự gửi toạ độ khi kỹ thuật viên check-in tại hiện trường. | **Fixed một phần** — sửa điều kiện kiểm tra thành `r.latitude`/`r.longitude` và URL thành `https://www.google.com/maps?q=...` (đúng chuẩn, sẵn sàng hoạt động ngay khi có dữ liệu toạ độ thật). Việc CAPTURE toạ độ khi check-in (gọi `navigator.geolocation`, gửi kèm payload) là tính năng CHƯA TỪNG được xây — ghi WIP-confirmed, không tự ý xây thêm ngoài phạm vi sửa bug. |
| — | Toàn bộ luồng Technical | Đăng nhập redirect đúng `/chamcong_kythuat`, danh sách kỹ thuật viên lọc đúng theo `linh_vuc`, ghi nhận chấm công + công việc hoàn thành thành công, hiện đúng trong lịch sử. **2/3 cụm test PASS, 0 FAIL** (sau khi sửa 1 bug test-script race condition — xem ghi chú dưới). | Đã xác minh bằng chạy thật. |
| — | (Sửa test script, không phải bug ứng dụng) | Lần chạy đầu báo "chỉ 1 kỹ thuật viên" — do `#employeeGrid` có sẵn 1 `<div>` khung xương loading TĨNH trong HTML ban đầu (trước khi JS tải xong), script bắt nhầm khung xương đó. Sửa dùng class `.cascade-item` (chỉ có ở thẻ nhân viên thật) — PASS đúng 5/5. | Đã sửa script. |
| — | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — cùng lỗi cross-cutting. | **Deferred** — Pha 6. |

### Office (Văn Phòng)

Ngách mỏng cùng nhóm Technical (`attendance` + `payroll`) — bảng chấm công kiểu Excel (mỗi nhân viên 1 dòng: giờ vào/ra/OT/trạng thái, khoá lại sau khi lưu), xin nghỉ phép siêu tốc, bảng vinh danh Kudos. Demo tenant: `demo.office.784966@bitpawdemo.com`.

Script: `scripts/office_industry_master_audit.mjs`. Kết quả: **3 PASS · 1 WARN · 0 FAIL**.

| # | Mô tả | Trạng thái |
|---|---|---|
| — | Toàn bộ luồng Office: bảng chấm công Excel-style (ghi giờ vào/ra/OT/trạng thái → khoá dòng đúng cách sau khi lưu, chặn sửa lại chấm công đã chốt), duyệt nghỉ phép siêu tốc, bảng vinh danh Kudos, module dùng chung. **3/4 cụm test PASS, 0 FAIL — không tìm thấy lỗi code thật nào.** | Đã xác minh bằng chạy thật. |
| — | (Sửa test script 2 lần, không phải bug ứng dụng) | (1) `<option>` không bao giờ được Playwright coi "visible" — sửa dùng `waitForFunction` đếm số lượng option thay vì `waitForSelector` mặc định. (2) Script ban đầu luôn chọn dòng ĐẦU TIÊN trong bảng — lần chạy lại trong cùng ngày trúng đúng dòng đã bị khoá từ lần chạy trước (chặn sửa lại chấm công đã lưu, hành vi ĐÚNG của ứng dụng) → sửa script tự tìm dòng CHƯA khoá. | Đã sửa script. Đã dọn sạch mọi bản ghi chấm công/nghỉ phép do test tạo ra khỏi DB demo. |
| — | Toàn bộ trang đã đăng nhập | `/favicon.ico` 404 — cùng lỗi cross-cutting. | **Deferred** — Pha 6. |

---

## Pha 7 — Chạy lại TOÀN BỘ để verify + Chuẩn bị lên CH Play

Theo yêu cầu "test hết lại toàn bộ, ra báo cáo lại, đưa lên CH Play" — chạy lại nguyên vẹn cả 12 script đã có (không sửa gì trước khi chạy) để xác nhận không có gì bị hỏng qua toàn bộ các lần sửa code trước đó, sau đó kiểm tra riêng phần build mobile app cho Google Play.

### Kết quả chạy lại toàn bộ (không sửa code trước khi chạy)

| Script | Kết quả | So với lần audit gốc |
|---|---|---|
| `nail_industry_master_audit.mjs` | 9 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `fnb_industry_master_audit.mjs` | 7 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `spa_industry_master_audit.mjs` | 5 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `retail_industry_master_audit.mjs` | 5 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `karaoke_industry_master_audit.mjs` | 3 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `hotel_industry_master_audit.mjs` | 4 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `production_industry_master_audit.mjs` | 2 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `technical_industry_master_audit.mjs` | 2 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `office_industry_master_audit.mjs` | 3 PASS · 1 WARN · 0 FAIL | Giống hệt |
| `shared_modules_pha6_audit.mjs` | 3 PASS · 0 WARN · 0 FAIL | Giống hệt |
| `landing_pages_audit.mjs` | ~60-64 PASS, số WARN dao động (1-6) tuỳ lượt chạy | WARN đều là `net::ERR_CONNECTION_RESET` (CDN Google Fonts/FontAwesome) — xác nhận qua chạy lại 4 lần liên tiếp, không có FAIL thật nào lặp lại ở cùng 1 trang. **Flaky mạng đã biết, không phải bug.** |
| `security_crash_resilience_audit.mjs` | 10/10 input dị dạng xử lý gọn (4xx/5xx đúng), server sống xuyên suốt | Giống hệt |

**Kết luận: KHÔNG có lỗi mới, KHÔNG có regression** sau toàn bộ các lần sửa code xuyên suốt Pha 0 → Pha 6. Log Flask server (`/tmp/flask_server.log`) không có traceback/Exception nào suốt toàn bộ 12 lượt chạy liên tiếp. Đã dọn sạch dữ liệu test phát sinh (2 khuyến mãi, 1 lead checkout, các bản ghi NVL/sản lượng/chấm công test) khỏi DB ngay sau khi verify, khôi phục lại `brand_name` gốc của tenant F&B.

### Chuẩn bị đưa lên CH Play (Google Play) — `mobile_app/` (Flutter WebView wrapper)

| # | Hạng mục | Tình trạng trước | Đã làm | Trạng thái |
|---|---|---|---|---|
| 1 | Icon ứng dụng | Vẫn là **logo mặc định của Flutter** (hình chữ "F" xanh) ở cả 5 mức độ phân giải — chưa từng đổi sang logo thật của BitPaw | Dùng `static/icon.jpg` (logo mascot BitPaw 1024×1024 có sẵn, đang dùng cho favicon/schema web) để tạo lại toàn bộ `ic_launcher.png` cho `mipmap-mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi` | **Fixed** |
| 2 | Ký bản release (signing) | `build.gradle.kts` ký bản release bằng **debug keystore** (`// TODO: Add your own signing config`) — Google Play **chắc chắn từ chối** bản build ký kiểu này | Tạo keystore release thật (`android/app/bitpaw-release.jks`, RSA 2048-bit, hiệu lực ~27 năm), file `android/key.properties` (đã thêm vào `.gitignore`, KHÔNG commit), sửa `build.gradle.kts` tự động dùng keystore thật khi có, fallback về debug key khi không có (không phá build debug bình thường) | **Fixed — nhưng xem mục 3** |
| 3 | Xác minh build release thật | — | Thử `flutter build apk --release` và `gradlew assembleRelease` trực tiếp — **thất bại ở tầng môi trường máy**, không liên quan tới code: `java.io.IOException: Unable to establish loopback connection` khi Gradle daemon cố mở kết nối loopback nội bộ. Đã xác nhận đây là lỗi môi trường CÓ SẴN từ trước (không phải do sửa `build.gradle.kts`) bằng cách thử `assembleDebug` (hoàn toàn không đụng tới) — **lỗi giống hệt**. Nhiều khả năng cùng nguyên nhân với vụ Avast từng chặn kết nối cục bộ của Python/OpenAI SDK trong dự án này (đã ghi nhận trước đó) — nay ảnh hưởng tới Gradle/JDK. | **Chưa xác minh được cục bộ** — không tự ý đổi cấu hình bảo mật hệ thống (tắt Avast/mở firewall) để né lỗi này. Khuyến nghị: build qua CI (GitHub Actions/Codemagic) hoặc máy khác không bị chặn loopback — cấu hình code đã đúng chuẩn, chỉ cần môi trường build khác là chạy được. |
| 4 | `AndroidManifest.xml` | — | Rà soát: chỉ xin đúng 1 quyền `INTERNET` (không có quyền thừa cần giải trình trong form Data Safety), `usesCleartextTraffic="false"` (chỉ HTTPS), `android:label="BitPaw OS"` đúng, trỏ đúng `https://bitpawsoftware.com/login` (không phải localhost). | Đã xác nhận sạch, không cần sửa. |
| 5 | **Nội dung Điều khoản/Chính sách bảo mật thật** | Toàn bộ 3 link (Điều khoản/Bảo mật/Thanh toán) trên `landing.html` vẫn hiện `"Chính sách đang được cập nhật..."` (đã ghi nhận từ Pha 1, KIỂM TRA LẠI vẫn còn nguyên) | Theo lựa chọn của chủ dự án (hỏi qua AskUserQuestion): soạn bản nháp dựa trên hành vi THẬT của app (đã audit toàn phiên) thay vì văn bản mẫu chung chung — xem chi tiết đầy đủ ở mục "Pha 1 — Landing Pages" phía trên (đã cập nhật trạng thái Fixed). Đã verify bằng Playwright thật trên cả 11 trang landing, cả VI/EN, không còn placeholder, 0 lỗi JS. | **Fixed (bản nháp)** — vẫn cần chủ doanh nghiệp/luật sư điền các chỗ `[...]` (tên pháp nhân, mã số thuế, địa chỉ, email liên hệ) và duyệt lại nội dung trước khi nộp lên Google Play — đây là nội dung do AI soạn, KHÔNG phải tư vấn pháp lý. |
| — | Việc nộp lên Play Console (tạo listing, trả lời form Data Safety, đóng phí đăng ký nhà phát triển, tải AAB lên) | — | — | **Ngoài khả năng thực hiện thay** — cần tài khoản Google Play Console thật của chủ dự án, không phải thao tác code. |

## Pha 6 — Module dùng chung

Phương pháp: dùng 1 agent nghiên cứu (đọc code, KHÔNG sửa gì) để lập bản đồ toàn bộ ~40 template dùng chung còn lại (CRM/Marketing mở rộng, Tài chính/Báo cáo, Thanh toán, Hệ thống/Admin, trang gốc dùng chung) — xác nhận route thật, có link từ sidebar hay không, và đánh giá "real feature" vs "WIP/orphan". Sau đó tự tay verify + fix những phát hiện có khả năng là bug thật, và test sâu bằng Playwright cho 3 luồng có giá trị cao nhất (tiền/dữ liệu thật, dễ chạm tới nhất): Brand Settings, Checkout công khai, Quản lý Khuyến mãi.

Script: `scripts/shared_modules_pha6_audit.mjs`. Kết quả: **3 PASS · 0 WARN · 0 FAIL** (sau khi fix 2 bug thật + bổ sung 1 dữ liệu cấu hình còn thiếu).

| # | File:dòng | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `app.py` `brand_settings()` (dòng ~6866) + `templates/brand_settings.html` (dòng ~495, JS) | **Lỗi thật, ảnh hưởng MỌI tenant không phải Spa**: cả route server (`redirect(url_for('spa'))`) LẪN JS phía client (`window.location.href = "{{ url_for('spa') }}"` sau khi lưu qua `/api/brand_settings`) đều hardcode điều hướng về `/spa` bất kể ngành thật của tenant. Do form thật sự lưu qua AJAX (`fetch('/api/brand_settings')`, không phải form-POST truyền thống), **cái JS mới là nơi user thật sự chạm phải** — route server chỉ là đường dự phòng cũ ít dùng. PoC xác nhận: đăng nhập tài khoản F&B, lưu Brand Settings → bị đẩy sang `/spa` (POS Spa, sai hoàn toàn dữ liệu ngành). | **Fixed** — sửa cả 2 nơi: server redirect về lại chính `brand_settings` (GET re-render), JS bỏ hẳn điều hướng (trang đã tự cập nhật preview tại chỗ, không cần chuyển trang). Verify bằng PoC thật: tài khoản F&B lưu xong ở lại đúng `/brand_settings`, không còn bị đẩy sang `/spa`. |
| 2 | `templates/chamcong_kythuat.html` (dòng ~110-112) | 3 link điều hướng ("Radar Kanban", "Quản lý Kho", "Quay lại") dùng href tương đối trần (`quanly_dichvu.html`, `quanly_kho.html`, `chamcong.html`) thay vì route Flask thật (`/quanly_dichvu`, `/quanly_kho`, `/chamcong`) — không có route nào phục vụ file `.html` trực tiếp nên bấm vào sẽ 404. Đây là ĐƯỜNG DẪN DUY NHẤT trong UI dẫn tới `quanly_dichvu`/`quanly_kho` từ ngách Kỹ Thuật (2 trang này không có trong sidebar chính). | **Fixed** — đổi cả 3 thành `{{ url_for(...) }}` đúng route. |
| 3 | Dữ liệu cấu hình (MongoDB `payment_methods`, toàn hệ thống — KHÔNG theo tenant) | Collection `payment_methods` (cấu hình QR ngân hàng nhận tiền cho trang `/checkout` công khai — trang bán gói SaaS cho khách hàng MỚI, trước khi họ có tài khoản) **hoàn toàn trống (0 bản ghi)**. Hệ quả: nút "Gửi đăng ký" trên `/checkout` bị disable vĩnh viễn cho MỌI gói trừ gói "agency" (gói duy nhất ẩn phần thanh toán) — không khách hàng tiềm năng nào đăng ký được các gói POS/HRM/E-Com dù form điền đầy đủ hợp lệ. PoC xác nhận: nút `#btnSubmit` ở trạng thái `disabled` khi collection trống. | **Fixed** — thêm 1 bản ghi ngân hàng demo (Vietcombank, is_active=true) qua đúng schema `/api/superadmin/payment_methods` đã định nghĩa. Verify: nút submit hoạt động, `/api/checkout/signup` trả về 200, màn hình thành công hiện đúng. **Lưu ý triển khai thật**: cần chủ hệ thống (super_admin) tự nhập tài khoản ngân hàng thật qua `/super_admin` trước khi go-live — bản ghi demo này chỉ phục vụ audit local. |
| 4 | `templates/index.html` (khối `{% if session.get('user_id') %}`, dòng ~839-1575) | **Phát hiện lớn nhất Pha 6**: ~700 dòng UI "launcher grid" (thẻ dẫn tới `customer_nurturing`, `campaign_builder`, `super_admin`, `report`, `ai_bot`...) chỉ render khi có session đăng nhập — nhưng truy vết TOÀN BỘ nơi gọi `render_template('index.html', ...)` trong `app.py` xác nhận: `root()` và `home()` (route `/`, `/index`, `/index.html`) đều kiểm tra và **redirect user đã đăng nhập đi nơi khác TRƯỚC KHI** chạm dòng render cuối cùng — dòng render đó chỉ chạy khi CHƯA đăng nhập. Kết luận: khối ~700 dòng này là **UI hoàn toàn không thể chạm tới** trong luồng điều hướng hiện tại — không phải bug gây lỗi, nhưng khiến `customer_nurturing.html`/`campaign_builder.html` mất đi đường dẫn discover DUY NHẤT được ghi nhận (2 trang này không có trong sidebar chính, không route nào khác link tới). | **Deferred** — đây là quyết định kiến trúc điều hướng (giữ nguyên UI chết để tái sử dụng sau, xoá hẳn, hay wire lại vào sidebar), không phải 1 dòng fix; không tự ý xoá 700 dòng markup hay thay đổi cấu trúc điều hướng giữa lúc audit. |
| 5 | `templates/admin_payment_management.html` (route `/payment_transactions`) | Trang xem/đối soát TOÀN BỘ giao dịch thanh toán thật (`/api/payment_transactions`, `/update_payment_status/<id>` đều hoạt động đúng) — nhưng **không có link nào trong toàn bộ app dẫn tới trang này**, kể cả từ `super_admin.html`. Đây là khoảng trống điều hướng nghiêm trọng hơn các orphan khác vì đây là nơi DUY NHẤT admin có thể tra cứu/huỷ giao dịch thật. | **Deferred** — cần quyết định sản phẩm (thêm link ở đâu: sidebar chung hay chỉ `super_admin.html`), không tự ý thêm link giữa lúc audit chức năng khác. |
| 6 | `templates/omnichannel_connect_placeholder.html` (dòng ~88) + `app.py:10541` | Form OAuth mô phỏng (đã tự ghi rõ "CỔNG XÁC THỰC MÔ PHỎNG") gửi `access_token` qua `method="GET"` (lộ trong URL/lịch sử trình duyệt/access log) và lưu vào **1 file SQLite riêng** (`database.db`, qua `sqlite3.connect()` thẳng) trong khi toàn bộ phần còn lại của app dùng MongoDB — dữ liệu này nằm ngoài tầm với của `backup_restore.html`. Vì đây là tính năng MÔ PHỎNG (chưa kết nối OAuth thật của Messenger/Zalo), rủi ro thực tế thấp, nhưng SAI PATTERN nếu sau này thay bằng OAuth thật mà không sửa lại 2 điểm này trước. | **WIP-confirmed** — ghi nhận rủi ro pattern để tránh lặp lại khi nối OAuth thật, không sửa ngay vì tính năng đang ở dạng mô phỏng có chủ đích. |
| 7 | `templates/omnichannel_connect.html` (dòng ~1118) | `triggerImport()` gọi `document.getElementById("btn-import")` không có null-check, nhưng KHÔNG có phần tử `id="btn-import"` nào trong file và không nút nào gọi `triggerImport()` — code chết, vô hại hiện tại nhưng sẽ ném `TypeError` nếu sau này có ai nối nút vào hàm này mà không kiểm tra lại. | **Deferred** — dọn dẹp code thừa, không ảnh hưởng chức năng hiện tại. |
| — | Toàn bộ luồng đã test sâu: Brand Settings (F&B lưu xong ở đúng trang), Checkout công khai (điền form → nhận QR ngân hàng → gửi đăng ký → màn hình thành công), Quản lý Khuyến mãi (tạo mã giảm giá → hiện đúng trong danh sách ngay). **3/3 cụm test PASS, 0 FAIL** sau khi fix. Đã dọn sạch toàn bộ dữ liệu test (2 mã khuyến mãi, 1 lead đăng ký, khôi phục lại brand_name gốc của tenant F&B) khỏi DB ngay sau khi verify. | Đã xác minh bằng chạy thật, không chỉ đọc code. |
| — | Còn lại ~30 template (CRM automation, ecommerce_sync, chat/app_chat, report_consolidated, quanly_congno/thuchi, payment_gateway/history/success, backup_restore, map_dashboard, calendar, staff_management, leave_requests...) | Đã xác nhận qua agent nghiên cứu: route thật tồn tại, gọi đúng API thật (không phải mock/placeholder giả), field name JS↔server khớp nhau. Không phát hiện bug rõ ràng khi đọc code, nhưng CHƯA chạy Playwright thật cho từng trang (khác với các mục 1-7 ở trên đã verify bằng PoC). | **WIP-confirmed / chưa test sâu** — ghi nhận để phiên audit sau có thể tiếp tục nếu cần, không tự nhận là "đã test" khi chỉ mới đọc code. |

## Pha 8 — Nails: chạy Playwright toàn bộ chức năng + soát giao diện từng màn hình

Yêu cầu: chạy lại toàn bộ chức năng ngành Nails bằng Playwright, fix sạch lỗi còn lại, và **nhìn từng màn hình** (desktop 1440×900 + mobile 390×844) để sửa mọi chỗ giao diện bể. Script mới `scripts/nail_visual_audit.mjs` (13 trang chủ tiệm + 5 modal POS + 3 trang công khai × 2 kích thước = 42 màn hình: đo tràn ngang thật, ảnh vỡ, lỗi JS, request lỗi, chụp ảnh để soát bằng mắt) + kiểm tra POS ở 9 kích thước từ 390px tới 1920px. Kết quả cuối visual audit: **42/42 màn hình sạch**.

### Lỗi chức năng / dữ liệu thật

| # | File | Mô tả | Trạng thái |
|---|---|---|---|
| 1 | `templates/app_nhanvien.html:81` | **App nhân viên trắng trơn**: commit `e63333f` ("strip heavy 3D effects") xoá thuộc tính `data-tilt…` nhưng xoá luôn dấu `>` đóng thẻ → trình duyệt nuốt thẻ kế tiếp làm thuộc tính rác, **form đăng nhập (mã NV, nút START SHIFT, tab Sign In/New Account) không hiện ra** — nhân viên không thể chấm công. Đã quét lại toàn bộ template bằng HTML parser: đây là chỗ duy nhất. | **Fixed** |
| 2 | `app.py` `/login`, `/register` | Rate-limit `5 per 15 minutes` áp cho cả GET → chỉ cần **mở/tải lại trang đăng nhập 5 lần** (vd quay lại sau khi gõ sai) là bị 429, chưa kịp thử mật khẩu lần nào. Đổi thành chỉ đếm POST. Verify: 8 lần GET đều 200; POST sai mật khẩu vẫn bị chặn từ lần thứ 6 (429); trang vẫn mở được trong lúc bị khoá. | **Fixed** |
| 3 | `setup_demo_nails.py`, `setup_demo_other_industries.py` + DB | Seed ghi hạng khách `'VIP'` — không thuộc bộ hạng Normal/Silver/Gold/Platinum mà app (`_tier_for_spend`) và CRM dùng → badge mất style, thẻ "VIP (Gold/Platinum)" luôn = 0, bộ lọc hạng không tìm thấy, biểu đồ hạng thiếu. Sửa seed tính hạng theo đúng ngưỡng của app; chuyển đổi 34 bản ghi demo `VIP` → Platinum 25 / Silver 9 (theo đúng ngưỡng USD/VND). | **Fixed** |
| 4 | `templates/leave_requests.html`, `templates/expense_requests.html` | Viết cứng 100% tiếng Việt (+ tiền `₫` cứng ở đơn hoàn ứng) → tenant tiếng Anh/AUD thấy giao diện lẫn 2 thứ tiếng, số tiền sai đơn vị. Thêm i18n vi/en theo `default_lang`, tiền theo `tenant_currency`. | **Fixed** |
| 5 | `app.py` `/report_consolidated`, `/api/my_branches` | Tên chi nhánh gốc mặc định ghi cứng "Chi nhánh chính" hiện nguyên chữ Việt cho tenant tiếng Anh (báo cáo chuỗi + ô chọn chi nhánh dashboard). Thêm `_localized_branch_name()` (tên chủ tiệm tự đặt giữ nguyên). | **Fixed** |
| 6 | `templates/brand_settings.html` | Nút **Huỷ** vẫn trỏ cứng `url_for('spa')` (cùng lớp lỗi với redirect sau khi lưu đã vá ở Pha 6) → tenant Nails/F&B/Retail bấm Huỷ bị đẩy sang POS Spa. Đổi về Dashboard. Nhãn "Store / Spa Name", "Cover Image (For Spa page)" → trung tính theo ngành. | **Fixed** |
| 7 | `app.py` (route mới `/favicon.ico`) | 78/94 template không khai báo `<link rel="icon">` → **mọi trang** sinh lỗi console 404 `/favicon.ico` (mục WARN "cosmetic" kéo dài từ Pha 2 tới Pha 7 ở cả 9 ngành). Trả về logo `static/logo_b.jpg` (cache 7 ngày). | **Fixed** |

### Lỗi giao diện (soát bằng mắt từng ảnh chụp)

| # | Màn hình | Mô tả | Trạng thái |
|---|---|---|---|
| 8 | POS `/sell` — thanh tác vụ nhanh | 6 nút cần ~760px nhưng ở 1440px chỉ còn ~530px: "Checked-In" bị cắt chữ, **Custom Item + Payment History bị đẩy khuất hoàn toàn** (không thanh cuộn). Topbar tự xuống dòng khi <1900px (thanh tác vụ chiếm trọn hàng 2), tablet thu gọn nút, điện thoại thành lưới 3×2. | **Fixed** — verify 9 kích thước 390→1920px: 0 nút bị khuất |
| 9 | POS `/sell` — nút **Pay Now** | Nút nằm cuối vùng cuộn 46vh của khung tóm tắt → ở 1440×900 (và iPad 1024×768) **thu ngân không thấy nút thanh toán** nếu không cuộn trong khung nhỏ. Tách nút ra footer ghim đáy cột vé; khung tóm tắt được co lại; giỏ hàng luôn giữ trọn ≥1 dịch vụ trên màn đủ cao. | **Fixed** — Pay Now hiển thị ở cả 9 kích thước |
| 10 | POS `/sell` — iPad dọc 768px | Cột vé 34% chỉ ~250px: 5 nút công cụ dính chữ ("DISCOUNTREFUNDQUOTE"), tên dịch vụ cắt còn "A…". Nới cột vé 44% + thu nhãn nút ở 768–1023px. | **Fixed** |
| 11 | POS — modal Online Booking QR | Mã QR lệch trái (class `inline-block` + `block` xung đột, `mx-auto` vô hiệu). | **Fixed** |
| 12 | POS — modal Payment (mobile) | Nút Confirm Payment chữ xuống 2 dòng, icon ✓ lơ lửng mép trái. | **Fixed** |
| 13 | **40 template** (calendar, crm, staff, leave, expense, brand_settings, pos_nail, payment_*...) | Toast "đã ẩn" chỉ dịch xuống bằng đúng chiều cao của nó (`translateY(100%)`) trong khi đang cách đáy 30px → **1 viên thuốc rỗng màu đen luôn nằm giữa đáy màn hình** (ở trang Khách hàng còn đè lên phân trang "Page 1 / 5"). Đổi thành `translateY(calc(100% + 40px))`. | **Fixed** |
| 14 | `components/app_sidebar.html` (dùng chung 33 trang) | (a) `/ai_bot` có thẻ hồ sơ doanh nghiệp làm sidebar cao ~1220px > màn hình 900px: nửa dưới menu + Đăng xuất tràn ra ngoài nền sidebar. Gộp logo/hồ sơ/menu vào 1 vùng cuộn, Đăng xuất ghim đáy, sticky ở desktop. (b) Mobile: nút ☰ (fixed) **đè lên tiêu đề trang ở mọi trang** (vd "Payroll" chỉ còn "ayroll") — chừa 72px phía trên `<main>` trên mobile. | **Fixed** |
| 15 | `/ai_bot` | Desktop: trang rộng 1584px > 1440px (đốm trang trí `absolute` tràn mép) → cuộn ngang + 180px khoảng trống phía dưới. Mobile: 2 cột cố định w-1/4 + w-3/4 ép vào 390px — danh sách khách ~60px, bong bóng chat mỗi dòng 1 chữ, nút Manual/AI bị đẩy ra ngoài màn hình. Xếp chồng 2 cột trên mobile. | **Fixed** |
| 16 | `/bangluong` (mobile) | Bảng lương 12 cột ép vào 390px: tiêu đề cột chồng nhau, "$1,335.70" đè "$86.04", Thực lãnh cắt còn "$1,4". Bọc trong vùng cuộn ngang min-width 760px. | **Fixed** |
| 17 | `/calendar` | Chữ "Waiting for cashier to load on POS" (nowrap) làm bảng rộng hơn khung, bị cắt ở mép phải. Cho xuống tối đa 2 dòng (sửa cả bản render server lẫn bản render JS). | **Fixed** |
| 18 | `/ai_studio` | Badge "STEP 3" vỡ 2 dòng; ô kết quả kịch bản AI chỉ còn ~1 dòng chữ (thẻ cao cố định 250px). Mobile: nhãn "Load Algorithm:" đẩy khuất tab FB Reels/YT Shorts. | **Fixed** |
| 19 | `/customers` (mobile) | Header chật, nút "Add Customer" tràn ra ngoài mép thẻ. Cho header xuống dòng. | **Fixed** |
| 20 | `/booking/nail/qr/<id>` (mobile) | Ô chọn thợ: chữ "No preference (salon will assign)" chạy đè dưới mũi tên dropdown. | **Fixed** |

### Môi trường / độ ổn định test (không phải lỗi app)

| # | Mô tả | Xử lý |
|---|---|---|
| 21 | Thỉnh thoảng 1 response HTML lớn bị treo ~20s rồi `ERR_CONNECTION_RESET` trên dev server Werkzeug máy Windows này. Đã khoanh vùng: Flask test client in-process 0/80 lần chậm (view logic sạch); qua socket thật xảy ra cả ở `/landing` (trang tĩnh, không DB) chứ không riêng `/sell` → lỗi tầng mạng loopback của máy (Werkzeug dev server + Avast quét HTTP), không ảnh hưởng production Vercel. | Thêm `scripts/lib/nail_nav.mjs` → `gotoSell()` tự tải lại khi lưới dịch vụ không render (6 script, 18 chỗ) + retry điều hướng trong visual audit. Không đổi cấu hình bảo mật hệ thống. |
| 22 | `page.screenshot` thỉnh thoảng ném `UNKNOWN: unknown error, open …png` (file bị khoá khi Avast quét) → làm FAIL cả bước nghiệp vụ (vd Test 7 Payroll) dù logic đúng. | `safeScreenshot()` thử lại 3 lần rồi chỉ cảnh báo, không làm FAIL test. |
| 23 | Script test cũ không còn khớp UI: `verify_us_nail_pos.mjs` (UI `.svc-card`/`#modifierModal` đã bỏ — đã xoá, trùng chức năng với master audit), `verify_nail_pos_acceptance.mjs` (`switchTab` cũ), `nail_gap_completeness_audit.mjs` (selector In báo giá, Test huỷ lịch dựa vào dữ liệu có sẵn). | Đã cập nhật / xoá. |

### Vẫn còn treo (cần quyết định sản phẩm)

- **Cấp tài khoản đăng nhập cho thợ Nails**: app nhân viên đăng nhập bằng mã NV, nhưng luồng "New Account" yêu cầu "Company Code" và danh sách ngành chỉ có "Spa & Nails" — chưa có quy trình rõ ràng để chủ tiệm cấp quyền đăng nhập cho thợ. Cần chốt luồng nghiệp vụ trước khi xây.

## Pha 9 — Test lại toàn bộ + chuẩn bị CH Play & App Store

Chạy lại 20 script Playwright (9 ngành + Nails sâu + dùng chung + landing + bảo mật): **0 FAIL, 0 traceback**; WARN favicon cũ ở cả 9 ngành đã hết (vd F&B 8 PASS · 0 WARN, Landing 66/66). Visual audit Nails 42/42 sạch, POS 12/12 kích thước. Chi tiết kế hoạch nộp store, việc chủ dự án cần làm và nội dung điền form: **[STORE_SUBMISSION_PLAN.md](STORE_SUBMISSION_PLAN.md)**.

| # | Lỗi | Trạng thái |
|---|---|---|
| 1 | App mobile chỉ có WebView Android → bản iOS crash khi mở; `ios/` không có project Xcode | **Fixed**: `webview_flutter` đa nền tảng + tạo project iOS (bundle `com.bitpawsoftware.bitpawMobile`, icon thật, mô tả quyền) |
| 2 | Xoá tài khoản có API nhưng không màn hình nào gọi (Apple 5.1.1(v), Google Play) | **Fixed**: `/account/delete` + link sidebar; verify end-to-end (sai mật khẩu bị chặn, đúng mật khẩu → khoá đăng nhập ngay) |
| 3 | Thiếu URL chính sách bảo mật; văn bản pháp lý còn placeholder | **Fixed**: `/privacy-policy`, `/terms`, `/payment-policy`; điền email/ngày/pháp nhân. Mã số thuế/địa chỉ trên footer nghi là dữ liệu mẫu → không đưa vào văn bản, cần chủ dự án xác nhận |
| 4 | Trong app vẫn mua được gói phần mềm ngoài IAP (Apple 3.1.1) | **Fixed**: UA `BitPawMobileApp` → chặn `/checkout`, `/api/checkout/*`, landing/bảng giá; web thường không đổi |
| 5 | Camera/GPS chấm công, chọn file, link tel:/mailto:/WhatsApp không chạy trong app | **Fixed** (quyền Android + Info.plist iOS, `file_picker`, `url_launcher`) |
| 6 | POS bỏ qua ngôn ngữ người dùng đã chọn (cookie) → iPad AU mở tiếng Việt | **Fixed** |
| 7 | Bảng lương trên điện thoại thấp bị ép còn 0px; POS điện thoại 360×640 đẩy mất nút Pay Now khi giỏ cao | **Fixed** |
| 8 | Màn khởi động trắng loé; file build máy local bị commit vào git | **Fixed** |
| 9 | Script test FAIL ngẫu nhiên do file ảnh bị khoá (Avast) ở 9 script ngành | **Fixed**: dùng chung `safeScreenshot()` |
| 10 | Máy dev không build được .aab/.ipa (Gradle loopback, iOS cần macOS) | **Xử lý**: GitHub Actions `.github/workflows/mobile-build.yml`. Ký release cần chủ dự án thêm 4 secret keystore (không tự tải khoá bí mật lên GitHub) |

## Pha 10 — Quét toàn bộ 9 ngành + bảo mật + chịu tải (Playwright)

Công cụ mới (giữ trong repo để chạy lại): `scripts/full_site_audit.mjs` (mọi route GET của app.py × 9 tenant demo, desktop + mobile: HTTP, lỗi JS, request lỗi, ảnh vỡ, tràn ngang, **nút gọi hàm không tồn tại**, link nội bộ hỏng), `scripts/security_full_audit.py` (truy cập không đăng nhập 396 route/method, IDOR chéo tenant bằng bản ghi mồi, CSRF, header, open redirect, reflected XSS), `scripts/load_test_local.py` (N người dùng đồng thời, mỗi người 1 IP), `scripts/ensure_indexes.py` (index MongoDB).

### Kết quả cuối (chạy tuần tự, restart server sạch trước mỗi bước, 0 traceback toàn bộ)

| Hạng mục | Kết quả |
|---|---|
| Quét 9 ngành (~1.000 lượt trang) | Còn đúng 4 mục/ngành, đều **không phải lỗi**: `/table_order` 400 (cần `table_id` từ QR — đúng thiết kế), `/super_admin` 403 với chủ tiệm thường (đúng phân quyền), `/map_dashboard` ô bản đồ OpenStreetMap bị máy này chặn kết nối (môi trường). 0 link hỏng thật |
| Bảo mật | Không đăng nhập: 396 phép thử, 1 mục gắn cờ = `/api/checkout/payment_methods` (cố ý công khai: tài khoản nhận tiền hiện trên trang đăng ký gói). **IDOR 0/51, CSRF 0/5, XSS phản xạ 0/9, open redirect: không** |
| Tải 30 người dùng × 60s | 2.013 request, **0 lỗi server, 0 timeout** |
| Tải 100 người dùng × 90s | 3.337 request, **0 lỗi 5xx**, 1 lỗi kết nối (reset môi trường). Trần ~36 req/s là giới hạn dev server Werkzeug 1 tiến trình trên Windows + mỗi truy vấn tới Atlas ~49ms từ máy này; production (Vercel) tự nhân bản theo tải |
| Hồi quy 15 bộ test (9 ngành + Nails + dùng chung + landing + yêu cầu store) | Tất cả PASS (Spa 1 WARN = reset kết nối môi trường) |

### Lỗi thật đã sửa trong pha này

| # | Mức | Lỗi | Sửa |
|---|---|---|---|
| 1 | 🔴 Cao | **Stored XSS**: tên khách đặt lịch online (công khai, không cần đăng nhập) chèn thô vào modal "Checked-In" của POS và trang Customer Nurturing -> script chạy trong phiên chủ tiệm. PoC xác nhận trước khi sửa | Escape 81 chỗ ở 32 template (dữ liệu người dùng ghép vào innerHTML; trong `onclick="fn('...')"` dùng escape chuỗi JS + thuộc tính). PoC sau sửa: 7/7 trang chặn |
| 2 | 🟠 | Stored XSS + lỗi hiển thị bảng Kanban Kỹ thuật (`/quanly_dichvu`): job thiếu `noi_dung` làm DỪNG cả vòng render (bảng trống); mọi trường chèn thô | Escape toàn bộ trường, bỏ chuỗi khỏi onclick |
| 3 | 🟠 | CSRF bootstrap chèn cuối `<body>` -> mọi POST gọi ngay lúc tải trang thiếu token, bị 400 (vd chat presence) | Chèn ngay sau `<head>` |
| 4 | 🟠 | Chống dò mật khẩu chỉ đếm trong bộ nhớ từng instance (Vercel nhiều instance) | Đếm lần **đăng nhập sai** trong MongoDB (dùng chung mọi instance, TTL 15 phút): 20 lần/IP, 10 lần/email -> 429. Áp cho `/login` và `/api/auth/token` |
| 5 | 🟡 | Thiếu header chống clickjacking/Referrer/Permissions | `X-Frame-Options: SAMEORIGIN`, CSP `frame-ancestors 'self'`, `Referrer-Policy`, `Permissions-Policy` |
| 6 | 🟡 | `/debug-sentry` công khai cố ý ném 500 (spam làm đầy hạn mức Sentry) | Chỉ superadmin |
| 7 | 🟠 Hiệu năng | Code KHÔNG tạo index nào; nhiều truy vấn nóng quét toàn collection (chamcong 1.226 bản ghi, `dining_tables.qr_token` cho QR công khai, `users.id`, `businesses.id`...) | `scripts/ensure_indexes.py` (idempotent) — đã tạo 30 index trên DB |
| 8 | 🟠 | `/qr_menu` luôn 404 (redirect tới bàn "demo" đã gỡ) — link QR Menu ở sidebar F&B, landing F&B, AI Studio đều hỏng; thực đơn QR mặc định lọc `retail` nên nhà hàng F&B ra menu trống | Chủ tiệm -> bàn đầu tiên của tiệm; khách vãng lai -> thực đơn mẫu tài khoản demo F&B; channel_type theo sản phẩm thật của tiệm |
| 9 | 🟠 | `/diemdanh`: ReferenceError (TDZ) làm dừng toàn bộ script (bản dịch, nút đổi ngôn ngữ...) | Gọi đồng hồ sau khi script nạp xong |
| 10 | 🟠 | Nút "Management" ở POS Spa và Karaoke bấm không có tác dụng (hàm nằm trong `<script type="module">`) | Gắn `window.toggleMgmtMenu` |
| 11 | 🟡 | `/customer_nurturing` crash khi khách chưa mua lần nào (`last_purchase` null) | Chặn null |
| 12 | 🟡 | `/sell` của ngành khác Nails gọi `/api/products/null`; link "Sales" ở AI Studio trỏ nhầm `/sell` | Về trang chủ ngay khi thiếu product_id; link đúng `retail_pos` |
| 13 | 🟡 | 6 ảnh Unsplash đã bị xoá (404) ở POS Nails, AI Studio, 7 sản phẩm demo; 2 GIF Giphy chết trong chat | Thay ảnh cùng chủ đề còn sống (code + DB); bỏ GIF chết |
| 14 | 🟡 Giao diện mobile | Header POS Spa tràn 701px; nút "+" Hotel Rooms bị cắt; bản đồ Dispatch Radar cao 0px (chú thích đè danh sách), icon tìm kiếm đè chữ; ô xin nghỉ Office tràn; header báo cáo chuỗi tràn | Sửa CSS từng trang |
| 15 | 🟡 Dữ liệu | Script Pha 6 để lại tên thương hiệu "QA Audit F&B Brand" cho tenant F&B; ~45 bản ghi QA tồn đọng ở 12 collection; 2 phòng khách sạn bị khách test chiếm | Script tự khôi phục tên gốc; dọn sạch DB (kể cả 427 đơn của bài test tải) |

### Việc cần chủ dự án làm (cần tài khoản)

- **Redis cho rate limiter** (Upstash miễn phí đủ dùng): đặt `REDIS_URL` trên project Vercel phục vụ domain (`bitpaw-saas-web`). Hiện limiter chung (1200 req/giờ/IP) vẫn đếm riêng từng instance; riêng chống dò mật khẩu đã dùng MongoDB nên không phụ thuộc việc này.
- **Khi tăng mạnh số tiệm**: nâng MongoDB Atlas khỏi gói miễn phí (giới hạn ~500 kết nối, mỗi instance Vercel giữ vài kết nối); cân nhắc dịch vụ realtime chuyên dụng thay SSE (mỗi màn POS mở giữ 1 function Vercel tới 25s).
- Chạy `python scripts/ensure_indexes.py` khi tạo DB mới/khôi phục backup.

## Pha 11 — Nhận diện thương hiệu trên Google (09/10/2026)

Google AI Overview mô tả sai: gộp phần mềm quản lý với nền tảng việc làm bitpawos.com vì site này tự gọi mình là "BitPaw OS"; tìm "Hồ Đình Sang" không ra gì.

| # | Vấn đề | Đã sửa |
|---|---|---|
| 1 | Phần mềm quản lý mang tên "BitPaw OS" (trùng bitpawos.com) trên web, app mobile, ảnh store | Đổi thành **BitPaw Software** (292 chỗ; dưới icon app: "BitPaw POS"); tạo lại ảnh store |
| 2 | 3 bản JSON-LD chép tay ở `seo_meta.html`/`base.html`/`index.html`, mô tả "hệ sinh thái" mơ hồ | 1 nguồn `components/entity_schema.html`: Person + 3 Organization tách bạch, `disambiguatingDescription`, `@id` trên đúng domain từng thương hiệu |
| 3 | Không có trang công khai nào về người sáng lập | `/ho-dinh-sang` (VI+EN, ProfilePage); `/founder`, `/about` → 301 |
| 4 | Không có `robots.txt`; sitemap cũ | `/robots.txt` (chặn trang nội bộ), sitemap 15 URL www |
| 5 | Landing không liên kết sang 2 thương hiệu anh em | Dải footer `components/brand_family.html` trên 11 landing |

Regression: landing 64 PASS · 2 WARN (ERR_CONNECTION_RESET môi trường local) · 0 FAIL; store compliance 21/21 PASS.
Việc chủ dự án làm trên bitpawos.com / bitpawnetwork.com + Search Console: `audit-results/SEO_ENTITY_GUIDE.md`.

## Pha 12 — Bản Desktop bán được khi mất mạng (09/10/2026)

Quyết định kiến trúc (chủ dự án chọn): **giữ 1 hệ thống cloud chung** (như KiotViet/Sapo/Square), không tách mỗi tiệm 1 server riêng; bản Desktop (.exe) bán tiếp được khi mất mạng rồi tự đồng bộ.

| # | Lỗi | Đã sửa |
|---|---|---|
| 1 | 🔴 `api_nail_pos_checkout` đọc bảng giá từ Atlas TRƯỚC khối bắt lỗi mất mạng -> mất mạng hẳn thì trả 500, nhánh lưu bill offline (`sync_worker`) **không bao giờ chạy** (chỉ chạy khi rớt mạng đúng giữa lúc ghi đơn) | Bảng giá + thợ + % hoa hồng lưu xuống máy mỗi lần mở POS lúc có mạng (`sync_worker.cache_catalog`); mất mạng -> tính tiền bằng bản trên máy |
| 2 | 🟠 Mỗi bill khi mất mạng chờ ~10s (2 lần timeout Atlas 5s) | Sau lần rớt mạng đầu, 60s tiếp theo bill lưu thẳng xuống máy (0.01s) |
| 3 | 🟠 Mở lại / tải lại POS khi mất mạng ra lưới dịch vụ trống | `/sell` (Desktop) lấy bảng giá đã lưu khi mất mạng |
| 4 | 🟠 Đơn đồng bộ offline không có bản ghi sổ cái `transactions` (mất khỏi Sổ quỹ/Báo cáo lãi lỗ), không trừ kho, thiếu tên khách/phụ phí thẻ | Đồng bộ ghi đủ trong cùng transaction; trừ kho không chặn (hàng đã giao) |
| 5 | 🟡 Cashier không biết đang offline / còn bao nhiêu bill chưa lên hệ thống | Badge "Mất mạng · N bill chờ đồng bộ" (`/api/desktop/sync_status`), hoá đơn ghi "Offline #XXXX" |
| 6 | 🟡 Launcher crash nếu cổng 5001 bị chiếm; chờ cứng 0.8s; đăng nhập mất mỗi lần tắt app (không mở được POS khi mất mạng lúc mở máy) | Tự lấy cổng trống, chờ server sẵn sàng thật, lưu hồ sơ webview + session Desktop 30 ngày |

Kiểm thử: `scripts/desktop_offline_e2e.py` 15/15 PASS (giả lập mất mạng Atlas, bán 2 bill, mở lại POS, đồng bộ, đối chiếu orders/order_items/chamcong/transactions, dọn sạch). Regression Nails web 10/10 PASS.
Chưa làm được trên máy này: build `.exe` thật (`auto_build.py`, cần pywebview + PyInstaller) — build và thử rút dây mạng trên máy quầy trước khi giao tiệm.

## Pha 13 — Test lại ngách Nails theo 3 vai: thợ, chủ tiệm, khách (09/10/2026)

Script mới `scripts/nail_persona_e2e.mjs` (36 bước, đối chiếu DB thật, tự tạo + xoá sạch thợ test) và `scripts/i18n_raw_key_audit.mjs` (tìm khoá dịch thô hiện trên màn hình, 28 trang × 2 ngôn ngữ, kể cả sau khi bấm EN/VI).

| # | Mức | Vai | Lỗi | Đã sửa |
|---|---|---|---|---|
| 1 | 🔴 Lương | Thợ | Báo cáo công việc ở app nhân viên cho thợ tự gõ "Revenue/Tips" -> ghi thẳng `chamcong.tien_tua/tien_tips` -> `/bangluong` cộng vào lương (thợ gõ $500 tips là được trả) | Nails/Spa (ăn hoa hồng theo bill POS): ẩn 2 ô, luôn gửi 0 |
| 2 | 🔴 Lương | Thợ / Chủ tiệm | Chấm công trùng: đăng xuất/đăng nhập lại chấm "Có mặt" lần 2 -> +1 ngày, +8h; chủ tiệm nhập ca có giờ thật trong ngày thợ đã check-in -> 8h mặc định + giờ thật | Server: 1 check-in/người/ngày; ca có `so_gio` chuyển lượt check-in cùng ngày thành "Check-in" (giữ ảnh/GPS, không tính giờ) |
| 3 | 🟠 Bảo mật | Thợ | Tự đăng ký nhân viên bằng mã công ty `BITPAW2026` ghi cứng (hiện ngay trong placeholder, giống mọi tiệm); mã NV random 4 số có thể trùng (báo nhầm "lỗi kết nối"); không có lựa chọn Nails (thợ tự đăng ký không hiện trong POS) | Bỏ tự đăng ký; hướng dẫn nhờ chủ tiệm thêm ở Quản lý nhân viên |
| 4 | 🟠 | Thợ | Đơn xin nghỉ / hoàn ứng lưu nháp lúc mất mạng bị đồng bộ nhầm vào `/api/hr/chamcong` -> đơn không bao giờ tới chủ tiệm | Đồng bộ đúng API theo loại đơn |
| 5 | 🟡 | Thợ | Điểm khen nhận số bất kỳ (999999, số âm) | Giới hạn 1–5/lần |
| 6 | 🟡 | Thợ | Đơn hoàn ứng hiện "25₫" ở tiệm Úc/Mỹ; nội dung đơn chưa escape | Tiền theo `tenant_currency`; escape |
| 7 | 🟡 | Thợ | `/diemdanh` ghi cứng ngành "Kỹ Thuật" -> check-in của thợ Nails không hiện ở màn chấm công Nails | Ghi đúng ngành của nhân viên |
| 8 | 🟠 Giao diện | Chủ tiệm | Sidebar hiện chữ thô `menu_dashboard`, `menu_pos_service`... trên `/map_dashboard` (hàm dịch của trang ghi đè sidebar bằng tên khoá khi thiếu bản dịch); 57 trang dùng chung kiểu code này | Hàm dịch các trang bỏ qua sidebar + giữ chữ gốc khi thiếu khoá; sidebar tự dịch khi bấm EN/VI và theo ngôn ngữ trang |
| 9 | 🟠 Giao diện | Chủ tiệm | Bản đồ `/map_dashboard` trắng (tile.openstreetmap.org từ chối kết nối, CARTO trả ảnh "API KEY REQUIRED"); luôn mở ở Việt Nam kể cả tiệm Úc/Mỹ | Ảnh nền Esri (tự đổi sang OSM nếu lỗi); mở theo quốc gia của tiệm |

Đã kiểm tra, KHÔNG lỗi: trang đặt lịch của khách tính giờ tối thiểu đúng múi giờ địa phương; khách chưa đăng nhập bị chặn ở 8 trang + 6 API nội bộ; portal chat không bị dò `customer_id`; đặt trùng thợ trùng giờ bị chặn 409; dữ liệu đặt lịch dị dạng trả 400.

Kết quả: persona 36/36 PASS · khoá dịch thô 0/56 lượt · quét toàn trang 117/120 sạch (3 còn lại là đúng thiết kế: `/table_order` thiếu mã bàn 400, `/super-admin` 403) · hồi quy 8 script Nails cũ đều PASS (master 10/10, chu trình kinh doanh 9/9, module dùng chung 9/9, gap 8/8, AI CSKH 7/7, realtime 6/6, POS acceptance, giao diện 42/42 màn hình).
Còn để ý: đặt lịch công khai không chặn giờ đã qua ở server (UI đã chặn); app nhân viên chạy dưới phiên đăng nhập của chủ tiệm (máy tiệm) — tài khoản đăng nhập riêng cho thợ vẫn là quyết định sản phẩm (Pha 8).
