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

## Pha 14 — Tách ngành nghề + làm lại QR + chạy lại toàn bộ (09/10/2026)

### Tách ngành nghề (`industry_access.py` — 1 bảng quy định duy nhất trang/API nào thuộc ngành nào)

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | Tiệm ngành nào cũng mở được trang/API riêng của 8 ngành kia (Nails mở /pos sơ đồ bàn, /karaoke, /hotel_rooms, /kitchen_display, chấm công ngành khác...) | `_industry_isolation_guard`: trang -> về trang chủ ngành mình, API -> 403 |
| 2 | 🔴 Dữ liệu | Mở `/pos` là tự tạo 200 bàn ăn cho BẤT KỲ tiệm nào -> 8 tiệm không phải F&B + 4 tài khoản đã xoá có 2.600 bàn rác | Chỉ F&B được tạo bàn; `scripts/cleanup_cross_industry_tables.py` đã sao lưu (`~/bitpaw_backups/`) rồi xoá 2.600 bàn (không bàn nào có đơn/đặt chỗ) |
| 3 | 🟠 | Spa bấm "POS" ở sidebar vào nhầm POS nhà hàng | Link POS theo ngành (`industry_pos_url`) |
| 4 | 🟠 | Nút "Chấm công" của Khách sạn / Kỹ thuật / Sản xuất / Văn phòng mở trang chấm công CHUNG thay vì trang riêng của ngành | `industry_chamcong_url` (khachsan / kythuat / congnhan / vanphong) |
| 5 | 🟠 | Trang công khai không kiểm tra ngành của tiệm: QR đặt lịch kiểu Spa của tiệm Nails, đặt bàn/đặt phòng/menu QR của tiệm khác ngành | QR đặt lịch tự chuyển đúng trang Nails/Spa; đặt bàn/phòng/menu sai ngành -> 404 |
| 6 | 🟡 | Trang thanh toán xong quay về /pos cho mọi ngành; /fnb_dashboard có thẻ dẫn sang Spa/Karaoke/Khách sạn; trang Kho có nút "Điều phối kỹ thuật" cho mọi ngành | Theo đúng ngành |

### QR + giao diện khách thấy

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 7 | 🔴 | Nút In QR (đặt lịch Nails, QR bàn F&B) in ra tờ TRẮNG: SVG có thẻ `svg:rect` nhúng vào trang in không hiển thị | SVG dạng path + viewBox, mức sửa lỗi Q |
| 8 | 🟠 | Tờ in QR đơn sơ (nền trắng, chữ "BITPAW SOFTWARE", không tên tiệm); Spa không có chỗ nào lấy QR đặt lịch | Poster A4 theo ngành `/qr/poster/booking`, `/qr/poster/table/<id>` (tên tiệm, logo/monogram, 3 bước, khung QR, VI/EN); mục "QR đặt lịch" trong sidebar Nails/Spa; modal QR POS làm lại |
| 9 | 🟡 | Trang đặt lịch: ô địa chỉ bắt buộc dù khách tới tiệm; tên tiệm chỉ là dòng chữ nhỏ dưới logo BitPaw | Địa chỉ không bắt buộc; logo/tên tiệm làm tiêu đề |
| 10 | 🟡 | Menu QR: mọi món ghi "+ Đã thêm vào giỏ" khi chưa thêm; đầu trang "BitPaw Menu" thay vì tên quán | "+ Thêm vào giỏ"; tên quán |
| 11 | 🟡 Bảo mật | `/api/checkout/payment_methods` (công khai có chủ đích) trả mọi trường của collection | Chỉ trả trường chuyển khoản công khai |

### Chạy lại toàn bộ (`scripts/run_full_regression.sh`, tổng hợp: `audit-results/full_regression_2026-10-09.tsv`)
Tách ngành 9 ngành 58/58 · 9 ngành master đều PASS (Nails 10/10) · bộ Nails 8 script + đóng vai 36/36 · module dùng chung 3/3 · landing 66/66 · store 21/21 · Desktop offline 15/15 · bảo mật (403 route không đăng nhập, IDOR 52, CSRF 5, XSS 9) 0 cờ · chịu lỗi: server sống · chịu tải 100 người dùng/60s: 1.897 request, 0 lỗi · chữ dịch thô 9 ngành: 0 · quét toàn trang 9 ngành: chỉ còn 3 trang đúng thiết kế/ngành (`/table_order` thiếu mã bàn 400, `/super-admin` 403).
Các FAIL lần chạy đầu đều do script test (bỏ qua lỗi reset kết nối môi trường local, `/qr_menu` chuyển sang bàn đầu tiên, nhật ký hoạt động hiện tên thao tác) — đã sửa script và chạy lại xanh.

## Pha 15 — Kiểm tra lại toàn bộ + bộ slide 9 ngành (09/10/2026)

- Chạy lại `scripts/run_full_regression.sh`: 45/45 bộ đạt (F&B có 1 lần lệch thời điểm chuyển trang của script, chạy lại 8/8). Tách ngành 86/86, bảo mật 0 lỗ hổng, chịu tải 100 người dùng 1.884 request 0 lỗi server, quét toàn trang 1.026 lượt trang 9 ngành.
- 🟡 Dữ liệu: tiệm demo (khách tiềm năng nhìn thấy) lẫn 46 bản ghi do script kiểm thử để lại ("QA Test Tech", "QA IDOR bait", "E2E Business Cycle Khách", "QA Audit Stage"...). Đã sao lưu (`~/bitpaw_backups/demo_test_leftovers_2026-10-09.json`) rồi xoá; `scripts/cleanup_demo_test_leftovers.py` chạy tự động cuối mỗi lượt kiểm thử tổng.
- Bộ slide chức năng 9 ngành (Nails chi tiết nhất): `audit-results/showcase/` — ảnh chụp bằng `scripts/showcase_screenshots.mjs` (chỉ xem, không ghi dữ liệu).

## Pha 16 — Đóng vai chủ tiệm + nhân viên cho cả 9 ngành (17/10/2026)

Script mới `scripts/staff_owner_persona_all_industries.mjs`: mỗi ngành, chủ tiệm tạo nhân viên (đúng bộ phận), giao job (Kỹ thuật); nhân viên dùng app nhân viên chấm công camera + GPS, khung bằng chứng, báo cáo, xin nghỉ, hoàn ứng, khen, đổi ca / nhận + hoàn thành job; chủ tiệm duyệt đơn, duyệt đổi ca, xem trang chấm công ngành + bảng lương (8h × đơn giá). Đã đưa vào `run_full_regression.sh`.

| # | Mức | Ngành | Lỗi | Đã sửa |
|---|---|---|---|---|
| 1 | 🟠 | Bán lẻ | Không có trang chấm công riêng: nút "Chấm công" mở trang CHỌN module của các ngành khác (bấm vào đâu cũng bị chặn về trang chủ) -> nhân viên bán lẻ không chốt ca / chấm công được | `chamcong_retail.html` (ca, giờ, chia tip, đổi ca); `/chamcong` chung chuyển thẳng về trang chấm công đúng ngành |
| 2 | 🟠 | Kỹ thuật, Sản xuất | App nhân viên so khớp "Kỹ Thuật"/"Sản Xuất" (hoa) trong khi dữ liệu là "Kỹ thuật"/"Sản xuất" -> thợ không bao giờ thấy ô ảnh bằng chứng + chữ ký khách khi báo cáo | So khớp không phân biệt hoa/thường |
| 3 | 🟠 | F&B, Karaoke, Bán lẻ | Nhân viên gửi "xin đổi ca" từ app -> lưu `cho_doi_ca` nhưng không trang nào của chủ tiệm hiển thị; Karaoke/Bán lẻ không có mục xin đổi ca | Danh sách "Yêu cầu đổi ca từ nhân viên" (Duyệt / Từ chối, duyệt ghi chấm công "Nghỉ đổi ca") trên trang chấm công F&B/Karaoke/Bán lẻ; app nhân viên mở mục đổi ca cho 3 ngành |
| 4 | 🟡 | Mọi ngành | Bảng lương đọc công thức ngành từ bộ nhớ trình duyệt dùng chung (`bp_industry_mode`) trước ngành thật của tiệm -> máy từng mở bảng lương tiệm khác ngành tính sai công thức | Lưu lựa chọn theo từng tiệm, mặc định đúng ngành |

Chạy lại toàn bộ (`audit-results/full_regression_2026-10-17.tsv`, 49 bộ): các FAIL lần đầu đều là quá thời gian chờ / ngắt kết nối của máy dev (Werkzeug + Avast) — chạy lại đạt hết: tách ngành 86/86, đóng vai 9 ngành 126/126, Nails 36/36, bảo mật 0 lỗ hổng, quét toàn trang + chữ dịch thô 9 ngành sạch. Dọn 14 bản ghi test khỏi tiệm demo (sao lưu `~/bitpaw_backups/demo_test_leftovers_2026-10-17.json`).

## Pha 17 — Bộ icon riêng cho ngành Nails (17/10/2026)

Icon chức năng của Nails là glyph Font Awesome đơn sắc, nhỏ, giống mọi app khác (và từng vỡ thành ký tự rác khi CDN font chậm). Thay bằng bộ icon SVG vẽ riêng theo đồ nghề tiệm nail (`templates/components/nail_icons.html`): lọ sơn, móng almond, bàn chân, cọ vẽ, giọt sáp, viên đá, chồng xu lương..., mỗi chức năng một "ô sơn gel" màu riêng có vệt bóng.

Áp dụng: POS Nails (6 tab nhanh, 5 ô thao tác trên vé, tab Vé/Hàng chờ, chip danh mục — icon tự chọn theo tên danh mục chủ tiệm đặt, 4 nút cách thanh toán, ô giỏ trống), sidebar của tiệm Nails (32 mục; ngành khác giữ nguyên), trang Salon Staff Management + Calculate Pay. Chip danh mục chuyển sang `data-cat` + escape tên (tên có dấu nháy từng làm hỏng nút).
Kiểm thử: Nails master 10/10, chu trình kinh doanh 9/9, module dùng chung 9/9, gap 8/8, đóng vai 36/36 + 14/14, giao diện 42 màn hình sạch, chữ dịch thô 0, tách ngành Nails/F&B/Spa đạt; F&B kiểm tra không bị đổi icon.

## Pha 18 — Đóng vai khách + chủ tiệm + thợ Nails, đo độ trễ tin nhắn thật (17/10/2026)

Script mới `scripts/nail_customer_experience_latency.mjs` (2-3 trình duyệt cùng lúc: khách trên điện thoại, chủ tiệm trên máy POS, thợ): đo thời gian từ lúc bấm gửi tới lúc bên kia THẤY tin, rải 8 lần qua chu kỳ kết nối lại của SSE.

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | Khách nhắn tới tiệm: 3/8 tin KHÔNG BAO GIỜ hiện ở `/ai_bot` (1/8 tiệm->khách ở `/portal`; chat nội bộ trễ tới 10s). Mỗi stream SSE tự đóng sau 25s, trình duyệt chờ ~3s mới nối lại, watch() mới bỏ qua thay đổi trong khe đó | `_sse_change_signal` gửi `id: <resume token>` mỗi nhịp + `retry: 1000`; khi nối lại đọc `Last-Event-ID` -> `watch(resume_after=...)` phát lại tin trong khe; token hết hạn thì báo client tải lại 1 lần. Sau sửa: 0/24 tin mất, trung vị ~0.3s, chậm nhất <0.8s |
| 2 | 🔴 | Chủ tiệm trả lời khách trong `/ai_bot` -> khách đang chat trên trang đặt lịch KHÔNG BAO GIỜ thấy (widget không nghe kênh nào) | Widget đặt lịch nghe `/api/portal/stream` + `/api/portal/messages` của hội thoại `business_id:SĐT`, hiện tin "Salon staff / Nhân viên tiệm" (hồng) — tới khách sau ~0.4s |
| 3 | 🔴 | AI đặt lịch qua chat KHÔNG BAO GIỜ thành công: tool gửi `service_id` dạng chuỗi, DB lưu số nguyên; prompt không có id dịch vụ, không biết hôm nay là ngày nào ("mai 3h" không đặt được) | `ai_function_tools.book_appointment` ép kiểu id + khớp theo tên; `_booking_assistant_facts()` đưa giờ địa phương (máy khách gửi `client_now`) + danh sách `service_id`; thêm `customer_name` |
| 4 | 🟠 | AI đặt TRÙNG: khách hỏi "mai 3h còn chỗ không" AI đặt luôn, khách nói "ok đặt giúp" AI đặt thêm lần nữa | Chặn trùng trong tool (cùng khách + dịch vụ + giờ còn hiệu lực -> trả lịch cũ); persona: câu hỏi còn chỗ không phải xác nhận, hỏi tên + xác nhận trước |
| 5 | 🟠 | Khách SĐT Úc/Mỹ (04xx...) bị coi là "chưa có SĐT" (regex chỉ nhận số VN): hội thoại không lưu, tiệm không thấy khách nhắn, AI không đặt được lịch | Nhận số 8-15 chữ số (có thể +); lưu SĐT đã bỏ khoảng trắng |
| 6 | 🟠 | Khách nói tiếng Anh nhận trả lời tiếng Việt (lượt đầu ép "Trả lời tiếng Việt"); widget chào tiếng Việt + nhãn "SĐT Zalo" trên trang đặt lịch tiếng Anh | Theo `<html lang>` của trang; persona: trả lời đúng ngôn ngữ khách |
| 7 | 🟠 | Hộp thư chủ tiệm hiện nguyên câu chỉ dẫn nội bộ cho AI ("Khách hàng (SĐT..) vừa nhắn: ... book_appointment") thay vì chữ khách gõ | Widget gửi kèm `customer_message`, server lưu đúng chữ khách |
| 8 | 🟠 | Thợ Nails không có chỗ nào xem hôm nay làm mấy khách / được bao nhiêu hoa hồng + tips | Thẻ "My earnings" trong app thợ (hôm nay + tháng này, từng bill), tự cập nhật qua `/api/stream/payroll` — hiện sau ~0.6s khi chủ tiệm thanh toán bill |
| 9 | 🟠 | Server (Vercel) chạy giờ UTC: tiệm ở Úc thanh toán trước ~10-11h sáng -> hoa hồng/tips ghi sang NGÀY HÔM QUA (sai lương ngày, lệch ranh giới tháng); hoàn tiền cũng vậy | POS Nails gửi `client_local_date`; server dùng nếu đúng định dạng và lệch ≤1 ngày so với UTC (`_client_local_date`) |
| 10 | 🟡 | Trang đặt lịch trên điện thoại rộng 421px thay vì 390px (quầng sáng trang trí thò ra) -> trượt ngang, khung chat bị cắt nút đóng | Quầng sáng không thò ra mép trên màn hình nhỏ |
| 11 | 🟡 | AI trả `**chữ đậm**` / xuống dòng -> khách và chủ tiệm thấy nguyên dấu `**`, danh sách dính 1 dòng | Escape rồi đổi `**..**` -> `<strong>`, `\n` -> `<br>` (widget + `/ai_bot`) |
| 12 | 🟡 | Thẻ hồ sơ trong `/ai_bot` của tiệm thật: "No Business Profile Yet · 0 Staff · Joined 2026-05-29" (đọc file SQLite cục bộ, ngày viết cứng) | Đọc `businesses` + đếm `employees` trên MongoDB |
| 13 | 🟡 | Nút "Sales Demo Tools" (mô phỏng bán phần mềm BitPaw) chen đầu hộp thư khách thật | Chỉ hiện khi hộp thư trống hoặc bật Demo Mode |
| 14 | 🟡 | Dữ liệu: hộp thư demo Nails có 20 hội thoại test (cả 2 payload XSS PoC cũ) — `nail_ai_bot_customer_care_e2e` không tự dọn | Đã sao lưu (`~/bitpaw_backups/nail_demo_bot_inbox_2026-10-17.json`) + xoá; script tự dọn từ nay |

Độ trễ sau sửa (máy local, MongoDB Atlas thật): khách -> hộp thư tiệm trung vị 0.29s (tối đa 0.48s); tiệm -> khách 0.30s / 0.41s (widget) ; chat nội bộ 0.33s; đặt lịch QR -> lịch 2.8s (trang lịch tự tải lại); check-in -> badge POS 0.3s; bill -> thu nhập thợ 0.6s; AI trả lời 1.5-3.4s.

Ghi chú môi trường: Python trên máy dev không xác minh được chứng chỉ TLS của DeepSeek (Avast quét HTTPS chèn CA riêng) -> AI trả câu "đang xử lý hơi chậm". Chạy server local với `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` = bundle gồm certifi + kho chứng chỉ Windows; không đụng cấu hình hệ thống. Không ảnh hưởng production.

Còn treo (không sửa lần này): toàn app dùng `datetime.now()` không múi giờ — ngoài hoa hồng Nails đã sửa, các mốc khác (lịch sử đơn, báo cáo ngày) của tiệm ở Úc/Mỹ vẫn theo giờ UTC trên Vercel. Cần thêm múi giờ cho từng tiệm (quyết định kiến trúc). Công tắc "AI ACTIVE / MANUAL CHAT" trong `/ai_bot` chỉ đổi giao diện, chưa tắt AI trả lời khách thật.

## Pha 19 — Tải về đúng ngành + từng AI chạy chuyên nghiệp (17-18/10/2026)

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | Nút "Download for Windows" trỏ tới file zip 142 KB trên Google Drive (bản build hỏng 265 KB, không có app bên trong); bản Desktop cũ cần chuỗi kết nối MongoDB trên máy khách + server license `license.bitpawsoftware.com` không tồn tại -> không file nào khách tải về chạy được | App Windows theo ngành `desktop_app/shell.py` (~18 MB, WebView2 mở hệ thống cloud đúng ngành, đọc ngành từ tên file BitPaw-Nails.exe..., không chứa khoá/mật khẩu). `/download/<ngành>/windows` -> GitHub Releases, chưa phát hành thì hiện trang mời dùng bản web. **Còn treo: chủ dự án upload 9 file `dist/releases/*.exe` lên GitHub Releases** |
| 2 | 🟠 | Landing ngành không có chỗ tải/dùng ngay; nút Đăng ký/Đăng nhập không mang ngành; link "Mac App Store" trỏ trang chủ apps.apple.com | Khu "Tải về & dùng ngay" trên 10 landing (Windows / Web / QR điện thoại), mọi nút mang `?industry=`, form đăng ký chọn sẵn ngành; popup landing chính chọn ngành trước |
| 3 | 🔴 | AI Copilot: 4 nút Tips gửi NGUYÊN câu hỏi nội bộ cho KHÁCH như tin của tiệm; sau mỗi tin nhân viên lại gọi 1 "BitPaw AI Advisor" (bán phần mềm, ép tiếng Anh) | Copilot riêng `/api/ai/copilot` (khách không thấy) tư vấn bằng số liệu thật (`ai_copilot.business_snapshot`), nháp trả lời cho tin mới của khách |
| 4 | 🟠 | Công tắc "AI ACTIVE / MANUAL" chỉ đổi màu chữ | `ai_paused` theo từng khách; nhân viên trả lời tự tắt AI; widget báo 1 lần "nhân viên sẽ trả lời" |
| 5 | 🟠 | Bot tư vấn landing: khách hỏi tiếng Anh nhận tiếng Việt; lời chào trộn Việt-Anh trong 1 câu; prompt cũ trong JS dặn "TUYỆT ĐỐI không nhận là AI"; dòng chèn `<br><span>` hiện mã HTML thô; landing Office trên điện thoại không có nút mở chat | Server chốt ngôn ngữ theo tin mới nhất (cả tiếng Việt không dấu); lời chào theo ngôn ngữ trang; gỡ prompt cũ; chữ thường; thêm thanh dưới + nút nổi cho landing Office |

Kiểm thử: `landing_download_audit` 44/44, `ai_copilot_e2e` 18/18, `landing_sales_bot_audit` 18/18.

## Pha 20 — Soát toàn bộ giao diện + cổng thanh toán (18/10/2026)

Cổng thanh toán (`scripts/payment_gateway_audit.py`, chỉ server local, tiệm demo, tự dọn dữ liệu): **39/39**.

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | Số tiền `NaN`/`Infinity` (JSON hoặc chuỗi) lọt qua mọi kiểm tra: hoàn tiền "NaN" qua được kiểm tra số dư, tip/giá Infinity làm tổng bill vô hạn | JSON NaN/Infinity -> 400 trước khi vào route; mọi số tiền qua `_money()` (hữu hạn, có trần) |
| 2 | 🔴 | Hoàn tiền: lý do không phải chữ gây lỗi SAU khi hoá đơn đã chuyển "đã hoàn" -> hoá đơn hoàn mà không có bản ghi hoàn | Kiểm tra trước khi đổi trạng thái |
| 3 | 🔴 | `/api/payment/confirm` với mã giao dịch bịa vẫn tạo đơn, bỏ qua chống bấm 2 lần | Bắt buộc giao dịch pending thật |
| 4 | 🟠 | `/payment_pending?table_id=<bàn tiệm khác>` hiện số tài khoản nhận tiền của tiệm khác | Bàn phải thuộc tiệm đang đăng nhập |
| 5 | 🟠 | Tiền tệ đơn hàng lấy từ client: tiệm VND gửi "USD" -> điểm thưởng tính như 100.000 USD | Lấy theo tiệm |
| 6 | 🟠 | Huỷ được giao dịch đã thu tiền (giao dịch "failed" nhưng doanh thu vẫn ghi) | Chỉ huỷ pending/processing |
| 7 | 🟠 | POS Nails: phí cà thẻ không giới hạn (âm -> thợ nhận tip thẻ nhiều hơn khách trả) | 0–10% |
| 8 | 🟠 | Mua gói BitPaw: giá do trình duyệt gửi (sửa thành 1đ); gói Agency (giá 0) không bao giờ gửi được; không giới hạn số lần gửi; màn hình hứa "tự kích hoạt khi tiền về" (thực tế cấp mã thủ công) | Giá theo bảng ở server, Agency gửi được, 10 lần/giờ, câu chữ đúng thực tế |
| 9 | 🟡 | Lưu cấu hình cổng nhận mọi kiểu/kích thước; đổi trạng thái giao dịch thành chuỗi bất kỳ; lỗi Square lộ độ dài Device ID; tài khoản nhận tiền superadmin không kiểm tra (logo `javascript:`) | Kiểm tra kiểu + danh sách 12 loại cổng; chỉ 4 trạng thái; bỏ chi tiết; kiểm tra BIN/số TK/https |
| 10 | 🟡 | POS F&B/bán lẻ làm tròn tip & tổng về số nguyên (AUD/USD mất số lẻ) | Làm tròn theo loại tiền |
| 11 | 🟡 | 14 trang định dạng AUD như VND (₫, không số lẻ) | Tiền đô cho USD + AUD |
| 12 | 🟡 | 10 chỗ trả chữ trắng trơn (QR gọi món hỏng, bàn không tồn tại, không phải superadmin...) — khách thấy như web sập | `message_page.html` đúng giao diện, song ngữ |
| 13 | 🟡 | Tia quét trang trí trên 59 trang nằm ĐÈ nội dung (z-index 9998), trên điện thoại trông như màn hình lỗi | Nằm dưới nội dung, tắt trên điện thoại / giảm chuyển động |

Ghi chú: lần chạy đầu của bài test thanh toán gom nhầm 1 món có sẵn (1 Bia Sài Gòn, dữ liệu sót từ test hôm trước) trên Bàn 1 tiệm F&B demo — đã khôi phục ngay; script giờ dùng bàn tạm riêng.

### Pha 20 (tiếp) — soi bằng mắt từng màn hình

Quét `full_site_audit` 3 lượt × 9 ngành (≈1.090 lượt mở trang, desktop + điện thoại, chụp toàn trang mọi trang trong menu), so từng điểm ảnh trước/sau (`scripts/compare_screenshots.py`): sau khi sửa, chỉ còn 3 trang cố ý chặn (`/table_order` thiếu mã bàn, `/super_admin` ×2) — nay hiện trang thông báo có giao diện.

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 14 | 🔴 | Trên điện thoại, 27 trang (màn chấm công = trang chủ của chủ tiệm ở cả 9 ngành, AI Copilot, Dashboard, báo cáo...) bị trình duyệt nới khung nhìn 678px rồi **thu nhỏ cả trang ~57%** — quầng sáng trang trí rộng 600-700px thò ra ngoài, `<body class="overflow-hidden">` không chặn được | `html { overflow-x: hidden }` (CSS dùng chung + sidebar cho trang Tailwind CDN) — đo lại trên giả lập điện thoại: cả 9 ngành `innerWidth` = 390 |
| 15 | 🟠 | File CSS dùng chung nặng **8,5 MB** (70.022 quy tắc) — safelist Tailwind không có mốc nên sinh mọi mức trong suốt × 4 trạng thái | Safelist có mốc + đủ màu ghép động (thêm rose/amber/fuchsia đang thiếu): **929 KB** (-89%); so điểm ảnh 264 ảnh: không trang nào mất style |
| 16 | 🟠 | Biểu đồ "Phân hạng khách" (CRM) luôn rỗng — canvas bị ép 200px trong khi Chart.js giữ tỉ lệ vuông | Khung cao cố định, `maintainAspectRatio:false` |
| 17 | 🟡 | Thông báo (toast) ẩn bằng cách đẩy xuống dưới mép màn hình trên 40 trang -> lộ ra thành ô viền rỗng / chữ "Notification" khi chiều cao màn hình đổi (thanh địa chỉ điện thoại) | Ẩn thật (opacity/visibility) khi chưa có thông báo |
| 18 | 🟡 | Trang thành công: tên cửa hàng viết cứng "BitPaw Restaurant & Cafe"/"BitPaw Nails & Beauty Salon" trên hoá đơn; bill tiền mặt ghi "Paid online via cash gateway"; hứa "đã gửi email xác nhận" (không có email nào); mô tả "BitPaw Premium Service"; tiệm Nails hiện câu "đơn F&B đã đóng, bàn đã giải phóng"; "$107.5" thiếu số lẻ | Tên thật của tiệm, "đã nhận tại quầy", bỏ câu email, mô tả theo ngành, ghi chú chung, "$107.50" |
| 19 | 🟡 | Trang chờ thanh toán: 3 nút chung 1 hàng, chữ gãy 3 dòng / tràn khỏi nút trên điện thoại | Nút chính cả hàng, 2 nút phụ chia đôi |
| 20 | 🟡 | Cổng thanh toán: tiệm ở Úc/Mỹ mở sẵn tab VietQR; ~55 câu tiếng Việt viết cứng hiện cả khi dùng tiếng Anh | Tab theo khu vực tiệm; dịch đủ (giao diện + mô tả + thông báo) |
| 21 | 🟡 | Trang mua gói còn câu "tài khoản tự kích hoạt khi giao dịch hoàn tất" | Sửa đúng quy trình cấp License Key thủ công |

Còn treo: bảng nhân viên trên điện thoại dùng cuộn ngang (không có gợi ý "vuốt để xem thêm"); nhiều trang khác của app còn lẫn tiếng Việt khi chọn tiếng Anh (đã dịch đủ trang cổng thanh toán; các trang khác cần 1 đợt dịch riêng).

## Pha 21 — Nails quy mô 60 thợ: có chạy ổn không (18/10/2026)

Dựng tiệm thử riêng (`scripts/nail_scale_seed.py`): **60 thợ, 1.500 khách, 10.800 bill / 30 ngày (360 bill/ngày), 16.575 dòng chấm công, 2.360 lịch hẹn**. Đo bằng `scripts/nail_scale_audit.mjs` (chỉ server local) + 3 script kiểm tra riêng. Xoá sạch tiệm thử sau khi đo.

| # | Mức | Lỗi khi tiệm có 60 thợ | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | **Bảng lương không mở được trên web thật**: tải TOÀN BỘ lịch sử chấm công rồi cộng ở trình duyệt — 1 tháng đã 5,2 MB (116% trần 4,5 MB/phản hồi của Vercel), mỗi tháng thêm ~5 MB | `/api/hr/payroll_summary` cộng sẵn trên server (7 KB cho 60 thợ); đối chiếu cách tính cũ: 60/60 thợ × 2 tháng, lệch 0 |
| 2 | 🔴 | **Cả tiệm bị chặn 429 giữa giờ làm**: giới hạn 1.200 lượt/giờ đếm theo IP + route, cả tiệm chung 1 Wi-Fi. Mỗi bill làm 60 điện thoại cùng tải lại "My earnings" -> ~10 bill là hết lượt; luồng real-time (SSE) tự nối lại mỗi 25s cũng bị đếm (~9 máy là chạm trần, trình duyệt bỏ hẳn luồng). Đo thật: request thứ **1.201 bị 429** | Tiệm đã đăng nhập 6.000/giờ (khách lạ/bot giữ 1.200), không đếm lượt nối lại SSE; đo lại: 1.250 lượt + 1.210 lượt nối SSE -> 0 lần 429, khách lạ vẫn bị chặn ở lượt 1.201 |
| 3 | 🟠 | Mỗi bill của cả tiệm báo cho MỌI điện thoại thợ tải lại thu nhập (60 máy × ~200 KB) | `/api/stream/payroll?ma_nv=` chỉ báo cho đúng thợ có bill + gộp tín hiệu 1,2s; kiểm tra: thợ khác nhận 0 tín hiệu |
| 4 | 🟠 | "My earnings": lấy 600 dòng mới nhất -> thợ đông khách (>600 dòng/tháng) bị **thiếu tổng tháng** | Lấy đúng tháng này (`?month=&year=`, dùng index) |
| 5 | 🟠 | Chia tips theo giờ cộng 8h cho MỌI dòng chấm công, kể cả dòng hoa hồng từng bill -> thợ làm 270 bill/tháng bị tính ~2.160 "giờ", nhận phần tips gấp nhiều lần người làm cùng giờ | Dùng đúng giờ làm hợp lệ (cùng quy tắc tính lương); lưu tips theo nhóm 8 thay vì tuần tự 60 lượt |
| 6 | 🟠 | CRM + POS tải toàn bộ khách mỗi lần mở (1.500 khách = 459 KB; ~7.500 khách là vượt trần Vercel); POS bắt thu ngân cuộn 1.500 dòng để chọn khách | CRM lọc/phân trang/thống kê ở server (6 KB/trang); POS ô tìm tên/SĐT (≤20 kết quả, 3 KB) |
| 7 | 🟡 | Xuất phiếu lương 1 thợ tải toàn bộ lịch sử (~3.300 dòng/năm) và gộp mọi tháng vào 1 phiếu | Xuất theo tháng đang xem, ghi rõ tháng trên phiếu + tên file |
| 8 | 🟡 | Index webhook Square đặt sai trường; chấm công thiếu index theo ngày | Index `metadata.square_checkout_id` + `(business_id, ngay_cham)` |

Đo lại sau khi sửa (server local, Atlas thật, tiệm 60 thợ):
- 12 màn hình chính (POS, chấm công, bảng lương, lịch, nhân viên, CRM, dashboard, báo cáo, lịch sử thanh toán, AI, nghỉ phép, đặt lịch công khai) mở xong **0,5–2,3 s**, không phản hồi nào quá 54 KB.
- Bán 1 bill 2 dịch vụ 2 thợ: ~0,8–1,3 s; hoa hồng đúng tới từng xu (QS001 $95×40% = $38, QS002 $60×40% = $24, tip thẻ $10 − 3% phí = $9,70 chia đôi $4,85).
- Đồng thời: 60 thợ mở "My earnings" (lỗi 0, chậm nhất 4,5 s) · **60 thợ chấm công vào ca cùng 1 lúc** (lỗi 0, chậm nhất 8,5 s — máy local 1 tiến trình; trên Vercel mỗi request chạy instance riêng) · 5 thu ngân bán cùng lúc (lỗi 0, chậm nhất 1,4 s) · 20 lượt lịch hẹn + khách (lỗi 0).
- Toàn vẹn dữ liệu: 0 mã trùng ở orders/order_items/chamcong/transactions; mỗi bill đúng 1 giao dịch.
- Hồi quy Nails: persona 38/38 · master 10/10 · gap 8/8 · business cycle 9/9 · realtime SSE 6/6 · POS acceptance không lỗi.

Còn treo / cần theo dõi:
- Mỗi điện thoại thợ mở app giữ 2 luồng SSE (thu nhập + chợ việc) — 60 máy = ~120 hàm Vercel chạy liên tục khi app đang mở: không lỗi nhưng tốn thời lượng hàm; nếu hoá đơn Vercel tăng, đổi sang 1 luồng gộp hoặc dịch vụ realtime riêng.
- Giới hạn tần suất trên Vercel chỉ chính xác khi có `REDIS_URL` (không có thì mỗi instance đếm riêng).
- Trang Công nợ + CRM Automation vẫn tải toàn bộ khách (~300 byte/khách -> chạm trần Vercel khoảng 12–15 nghìn khách) — cần phân trang như CRM khi có tiệm lớn tới mức đó.
- Không thử 60 ảnh chấm công tải lên cùng lúc (`.env` local trỏ kho ảnh thật).

## Pha 22 — Kiểm thử TẢI Nails: hàng trăm/nghìn khách đặt lịch + tính tiền cùng lúc (18/10/2026)

Cách test (`scripts/nail_load_test.py`, chỉ server local, `EMAIL_DISABLED=1` để không gửi email thật, tiệm thử 60 thợ, xoá sau khi đo): mỗi "khách" là 1 phiên + 1 IP riêng, mở trang đặt lịch thật (CSRF + cookie như trình duyệt) rồi gửi; sau mỗi pha **đọc lại database để đối soát**, không chỉ đếm HTTP 200. Kèm: `_booking_race_check.py` (30 khách bấm đặt CÙNG 1 khoảnh khắc × 10 vòng), `_checkout_contention_check.py` (A/B tranh chấp kho), `_count_db_ops.py` (đếm lệnh DB/thao tác), `_verify_load_fixes.py` (6 tình huống biên). Theo dõi RAM/CPU/luồng của tiến trình server suốt bài test.

| # | Mức | Lỗi (đo trên code cũ) | Đã sửa | Đo lại |
|---|---|---|---|---|
| 1 | 🔴 | **Đặt trùng thợ**: 30 khách bấm cùng lúc 1 thợ 1 giờ -> 9/10 vòng nhiều người cùng được nhận, có vòng **29 người cùng 1 chỗ** (kiểm-tra-rồi-ghi không nguyên tử) | `slot_key` + index unique (business_id, slot_key); huỷ lịch gỡ khoá, mở lại lịch đã huỷ khi giờ đã có người -> 409; giờ chuẩn hoá (10:00 = 10:00:00) | 10/10 vòng đúng 1 người |
| 2 | 🔴 | **Điểm thưởng tiệm AUD luôn = 0, khách không bao giờ lên hạng** (chỉ 'USD' được coi là đô; AUD tính như VND: int($95 × 1/10000) = 0) | Mọi tiền tệ khác VND dùng bảng $ (1 điểm/$1, Silver $80 / Gold $400 / Platinum $1.200); sửa luôn luồng thanh toán bàn quên truyền tiền tệ | 30 khách quen: đủ điểm, đúng hạng Platinum |
| 3 | 🔴 | **CRM mất tiền của khách**: 1.000 bill, khách quen trả song song -> tổng chi tiêu mất **$585** (đọc-cộng-ghi đè lên nhau); khách mới trả 2 bill cùng lúc có thể thành 2 hồ sơ | `$inc` nguyên tử + index unique (business_id, phone); ghi hạng có điều kiện | Mất $0, điểm lệch 0, 1 hồ sơ/khách |
| 4 | 🔴 | **1 bill gửi 2 lần (mạng chập chờn, bấm lại) = 2 đơn**: thu tiền 2 lần, trả hoa hồng 2 lần | POS gửi `client_request_id` mỗi lần bấm thanh toán; index unique; gửi lại trả đúng đơn cũ | 1 đơn |
| 5 | 🟠 | **Spam đặt lịch**: 1 IP + 1 SĐT gửi 300 lịch giả -> **300/300 vào thẳng Lịch** của chủ tiệm | 30 lượt/giờ/IP + tối đa 3 lịch sắp tới/SĐT (giới hạn mềm — gửi dồn cùng lúc có thể lọt 1–2) | 4/300 lọt |
| 6 | 🟠 | **Tính tiền nghẽn giờ cao điểm**: dịch vụ Nails có trường stock nên mọi bill sửa bản ghi dịch vụ TRONG transaction -> 20 bill cùng 1 dịch vụ hot: 1,9 bill/giây, bill chậm nhất chờ **33 giây** | Trừ kho nguyên tử TRƯỚC transaction, hoàn kho nếu bill không ghi; cấp id hàng loạt | 7,1 bill/giây, chậm nhất 3 giây; kho vẫn không bán âm (còn 1 + 10 bill cùng lúc -> đúng 1 bán được) |
| 7 | 🟠 | Mỗi lượt đặt lịch gửi 1 email Gmail cho chủ tiệm ngay trong request -> 1.000 lượt = 1.000 thư, cả hệ thống dùng chung 1 Gmail (~500 thư/ngày) -> thư quên mật khẩu của mọi tiệm ngừng đi | Tối đa 30 thư báo lịch/tiệm/ngày (lịch vẫn lưu đủ); `EMAIL_DISABLED=1` cho server test | — |
| 8 | 🟡 | Lịch của chủ tiệm kêu chuông + toast cho TỪNG lịch mới (1.000 lịch = 1.000 tiếng chuông) | Tối đa 1 lần/5 giây | — |
| 9 | 🟡 | CRM thêm khách trùng SĐT trả lỗi 500 khó hiểu (sau khi có index unique) | 409 "Số điện thoại này đã có trong danh sách khách hàng." | ✅ |

Kết quả 1.000 khách đặt lịch (100 người cùng lúc) + 1.000 bill (20 máy cùng lúc), code mới: 0 lịch trùng thợ, DB khớp từng lịch; tiền orders = transactions = $117.718,00, hoa hồng + tip $49.390,62 khớp từng xu với số POS báo; RAM server 171→193 MB rồi về 187 MB (không rò rỉ), CPU trung bình 0,2 nhân. Hồi quy Nails: xem cuối mục.

Giới hạn của máy test (không phải lỗi code): từ máy này Atlas chỉ đạt ~105 lệnh/giây dù 20 hay 50 luồng -> số giây/bill ở trên là của máy local, không phải của web thật.

**Database đang chạy gói Atlas dùng chung (M0/Flex)**: tối đa 500 kết nối, không xem được RAM/ổ đĩa, `hostInfo` bị chặn; thông lượng đo được khớp trần ~100 lệnh/giây của gói M0 — trần này là của CẢ HỆ THỐNG (mọi tiệm cộng lại):
- 1 lượt đặt lịch ≈ 13 lệnh DB (mở trang 5 + gửi 6–8), 1 bill ≈ 16–18 lệnh -> cả hệ thống ~7 lượt đặt lịch/giây hoặc ~6 bill/giây. Tiệm 60 thợ giờ cao điểm (~60 bill/giờ) chỉ dùng ~0,3% — ổn; nhưng 1 đợt khuyến mãi 1.000 khách đặt trong 1 phút sẽ làm chậm MỌI tiệm khác ~2 phút.
- **Dung lượng 512 MB (M0)**: ~3,3 KB/bill (đơn + giao dịch + dịch vụ + chấm công + điểm) -> ~155.000 bill cho cả hệ thống; riêng 1 tiệm 60 thợ (360 bill/ngày) đầy trong ~14 tháng. Khi đầy, MỌI lệnh ghi bị từ chối (không tính tiền, không đặt lịch được).
- **500 kết nối**: 1 tiến trình server giữ ~56 kết nối khi tải cao (đo), mỗi instance Vercel tối thiểu ~6–7 (giám sát 3 node). Luồng real-time (SSE) giữ instance 25 giây: 60 điện thoại thợ × 2 luồng ≈ 120 instance ≈ 700–850 kết nối > 500 -> có thể bị từ chối kết nối khi cả tiệm cùng mở app. Chưa đo trên web thật (không kiểm thử tải production).
- Khuyến nghị (chủ dự án quyết định, có chi phí): nâng Atlas lên M10 (dedicated: không giới hạn lệnh/giây kiểu M0, 10 GB, 1.500 kết nối) trước khi nhận tiệm cỡ 60 thợ hoặc chạy khuyến mãi đặt lịch lớn.

Còn treo: F&B/Bán lẻ (`api_sales_checkout`) vẫn trừ kho trong transaction — cùng kiểu nghẽn khi nhiều đơn cùng 1 món hot; Lịch 1 ngày ~2,6 KB/lịch hẹn (200 lịch = 500 KB, ~1.700 lịch/ngày mới chạm trần Vercel).

Hồi quy Nails sau khi sửa (server `EMAIL_DISABLED=1`): persona 38/38 · master 10/10 · gap 8/8 · business cycle 9/9 · realtime SSE 6/6 · AI bot đặt lịch/CSKH 7/7 · POS acceptance không lỗi · 6/6 bill tạo từ giao diện POS thật có mã chống gửi trùng · `_verify_load_fixes` 6/6.

## Pha 23 — Test lại toàn bộ: tải app Windows, 9 ngành, chủ + nhân viên, máy tính + điện thoại, lỗi "đợi vài giây mới lỗi" (18/10/2026)

Cách test (chỉ server local, `EMAIL_DISABLED=1`):
- **App Windows** (`scripts/desktop_app_e2e.mjs`): chạy THẬT 9 file `dist/releases/BitPaw-<Ngành>.exe`, nối vào chính cửa sổ WebView2 qua cổng debug -> trang đăng nhập đúng ngành, đăng nhập, ngồi 20 giây, chụp ảnh; ca mất mạng -> trang báo + tự vào lại khi có mạng.
- **Điện thoại thật** (`scripts/lib/device.mjs`, `DEVICE=mobile`): giả lập iPhone 13 (UA iOS, cảm ứng, isMobile) — chạy lại ĐÚNG các kịch bản của máy tính.
- **Lỗi xuất hiện muộn** (`scripts/linger_audit.mjs`): mở từng trang trong menu, ngồi lại 35 giây (quá 1 chu kỳ real-time 25s), ghi mọi lỗi JS / request lỗi / thông báo lỗi kèm GIÂY THỨ MẤY nó hiện. Tự kiểm script bằng trang mồi (lỗi ở giây 5, 8, 10): bắt đủ cả 3 trên 2 thiết bị.
- **Chủ tiệm tự thêm nhân viên** (`scripts/hr_onboarding_e2e.mjs`): bằng giao diện, 9 ngành × 2 thiết bị.
- Mỗi bộ test ghi lại PID server trước/sau — phát hiện ngay nếu server bị khởi động lại giữa chừng.

| # | Mức | Lỗi | Đã sửa | Đo lại |
|---|---|---|---|---|
| 1 | 🔴 | **Chấm công camera**: nút Chụp mở ngay khi GPS bắt được vị trí, không đợi camera -> chụp lúc video 0×0 (bắt được: F&B, Khách sạn, Sản xuất readyState=0) -> ảnh chấm công RỖNG, hoặc tải lên lỗi rồi HUỶ chấm công sau vài giây | Mở nút khi CẢ GPS + camera sẵn sàng; video `muted` + `play()`; chặn gửi ảnh rỗng | Camera 640×480 lúc mở nút ở 9 ngành; persona 147/147 máy tính + 147/147 iPhone |
| 2 | 🔴 | **8/9 ngành không có cách thêm nhân viên** dùng app nhân viên / chấm công / lương (chỉ Nails có nút tới /nhanvien; menu "Staff Management" là danh sách hoa hồng POS khác). Form thêm nhân viên thiếu phòng ban Retail/Karaoke, mặc định "Văn Phòng" -> nhân viên không có trong Bảng lương (đo: 25 FAIL ở 8 ngành) | Menu "Nhân viên & tài khoản app" cho mọi ngành; trang Staff Management giải thích + nút mở; thêm Retail/Karaoke; chọn sẵn đúng ngành | 54/54 máy tính + 54/54 iPhone |
| 3 | 🟠 | Đăng nhập giới hạn 5 lần/15 phút/IP tính cả lần ĐÚNG -> cả tiệm chung Wi-Fi, lần thứ 6 bị khoá 15 phút (gặp thật khi test 9 app Windows) | Chỉ đếm lần SAI (20/IP; MongoDB: 20/IP, 10/email) | 25/25 đăng nhập đúng qua; sai bị chặn lần 21/IP, lần 11/email |
| 4 | 🟠 | Điện thoại: thông báo "đã thêm vào vé/giỏ" nằm ĐÈ nút PAY NOW/Checkout (POS Nails, Bán lẻ, F&B/Spa, gọi món QR) -> chạm thanh toán ngay sau khi thêm món thì trúng thông báo, hộp thanh toán không mở | Thông báo lên trên + chạm xuyên qua | Chạm PAY NOW ngay sau khi thêm -> hộp thanh toán mở |
| 5 | 🟠 | Bán lẻ trên điện thoại: mỗi lần quét mã vạch giỏ hàng tự bật che kín màn hình; nút đóng giỏ rộng 16px | Điện thoại không tự mở giỏ; nút đóng 44×44 | Bán lẻ iPhone 6/6 |
| 6 | 🟠 | Màn bếp: phiếu chỉ mất khi bếp bấm "Hoàn thành" -> 65 phiếu OVERDUE từ 27/9 trên tiệm demo | Chỉ hiện phiếu trong 12 giờ (KHÔNG tự đóng khi bàn thanh toán — quán trả tiền trước vẫn cần phiếu) | — |
| 7 | 🟡 | 3 script test tự chạy `~/restart_flask.sh` mỗi 4 lần đăng nhập: GIẾT mọi tiến trình Python rồi bật server khác (không `EMAIL_DISABLED`) -> sập các bài test chạy song song; đây chính là nguyên nhân "đăng nhập nhân viên chập chờn" các đợt trước | Bỏ (đăng nhập giờ chỉ đếm lần sai) | Không còn server bị khởi động lại giữa lượt |
| 8 | 🟡 | Chat CSKH công khai: SĐT gửi dạng số -> 503 | Nhận số, sai kiểu -> 400 | — |
| 9 | 🟡 | Bảng lương trên điện thoại: câu "chưa có dữ liệu" bị cắt nửa (nằm trong vùng cuộn ngang 760px) | Ghim trong khung nhìn | — |
| 10 | 🟡 | Test F&B để lại đơn bàn + phiếu bếp (bàn 1–2 "Đang phục vụ" trên tiệm demo); 36 bản ghi test khác trong 12 tiệm demo | Test F&B tự khôi phục trạng thái bàn/phiếu bếp; dọn dữ liệu demo | — |

Cần chủ dự án quyết định:
- File `.exe` **chưa ký số** -> Windows SmartScreen cảnh báo "Windows protected your PC" khi khách mở (cần chứng chỉ ký mã — có phí). 9 file chưa được upload GitHub Releases -> nút tải về hiện trang "sắp phát hành".
- POS Spa không gán kỹ thuật viên cho từng dịch vụ -> hoa hồng Spa phải nhập tay ở màn Chấm công Spa (nhập 2 lần).
- 2 danh sách nhân viên (`/staff` hoa hồng POS vs `/nhanvien` nhân sự/app) — đã có hướng dẫn qua lại; về lâu dài nên gộp.
- Dữ liệu demo Spa (tiệm AUD) có khách chi tiêu kiểu VND ($1.500.000) -> CRM demo hiện tổng $5,4 triệu.

Kết quả cuối (sau khi sửa):
- **App Windows**: 9/9 file `.exe` chạy thật — 38/38 (mở đúng ngành, đăng nhập, 20 giây không lỗi, cửa sổ vừa khung; mất mạng -> trang báo song ngữ, có mạng lại tự vào trong ~10 giây).
- **Chủ tiệm, nghiệp vụ 9 ngành**: tất cả PASS trên máy tính VÀ iPhone (Nails 10, F&B 8, Spa 6, Bán lẻ 6, Karaoke 4, Khách sạn 5, Sản xuất 3, Kỹ thuật 3, Văn phòng 4 — mỗi thiết bị).
- **Nhân viên 9 ngành** (đăng nhập, chấm công camera + GPS, báo cáo, xin nghỉ, hoàn ứng, khen, đăng xuất): 147/147 máy tính + 147/147 iPhone.
- **Chủ tiệm tự thêm nhân viên**: 54/54 máy tính + 54/54 iPhone (trước khi sửa: 25 FAIL).
- **Lỗi xuất hiện muộn** (ngồi 35 giây mỗi trang): 9 ngành × ~15 trang × 2 thiết bị + trang nhân sự — 0 lỗi muộn (các lỗi duy nhất ghi được là lúc server bị script test cũ giết — đã bỏ script đó, chạy lại sạch).
- **Quét toàn trang**: 1.101 lượt mở trang × 9 ngành, chỉ 3 trang chặn có chủ đích/ngành (/table_order thiếu mã bàn, /super_admin), 0 link nội bộ hỏng.
- **Phía khách & hệ thống**: tải về 44/44 · landing 66/66 · bot tư vấn 18/18 · cổng thanh toán 39/39 · màn thanh toán 16/16 · AI Copilot 18/18 · Nails (gap 8/8, chu trình 9/9, real-time 6/6, bot CSKH 7/7, persona 38/38, POS acceptance sạch) · cách ly dữ liệu giữa ngành 30/30 + 28/28 + 28/28 · khoá dịch thô 0 (28 trang × 2 ngôn ngữ) · input dị dạng: server sống, 0 lỗi 5xx.
- Dọn: 36 bản ghi test trong 12 tiệm demo (có sao lưu), 69 phiếu bếp treo + 2 bàn "đang phục vụ" giả ở F&B demo, tin nhắn test lọt vào hộp thư khách tiềm năng, thư mục tạm của 9 app Windows.

## Pha 24 — Logo chữ B mới, tải về đúng thiết bị (Windows/Android/máy POS/iPhone/iPad), làm hết các mục "cần quyết định" (18–23/10/2026)

**Logo**: ảnh gốc `static/brand/bitpaw-b-source.webp` -> `scripts/make_brand_icons.py` sinh 45 file (cắt đúng ô chữ B, bỏ dấu ✦ của trình tạo ảnh): `static/logo_b.jpg` (22 template + `/favicon.ico` dùng tên này), favicon.ico 16–64px, icon PWA 192/512 + maskable, apple-touch-icon, icon file `.exe`, icon app Android/iOS (mobile_app), và PawNail (`app/icon.jpg` = favicon tab "PawNail Jobs", `app/favicon.ico`, `public/icons/*`). Server tự chèn khai báo icon + manifest vào MỌI trang HTML (94 template).

**Tải về** (`/download`, `/download/<ngành>`, khu tải trên 10 landing): tự nhận diện Windows/máy POS Windows, Mac, Chromebook, điện thoại Android, máy tính bảng Android, máy POS Android (Sunmi/PAX/Clover…), iPhone, iPad (kể cả iPadOS tự xưng Mac). Windows -> `.exe` đúng tên ngành; Android/máy POS -> `.apk` ký bản chính thức (Android 7+, quyền camera + GPS chấm công); iPhone/iPad -> cài web app ra màn hình chính (Apple không cho cài file ngoài App Store) có hướng dẫn theo từng máy, nhận ra cả trình duyệt trong Zalo/Facebook. File cài nằm trên chính website (CDN Vercel, `vercel.json`) — không cần GitHub Releases; link có `?v=<sha>` để CDN không trả bản cũ. Mã QR trên landing trỏ về trang tải -> điện thoại quét là ra đúng bản.

| # | Mức | Lỗi | Đã sửa | Đo lại |
|---|---|---|---|---|
| 1 | 🔴 | Sau commit "backup" (chứa phần đang làm dở), web thật: cả 2 nút tải Windows/Android ra "đang cập nhật" (503) — Flask kiểm tra file trên ổ đĩa nhưng trên Vercel file cài do CDN phục vụ, không nằm trong gói Flask; `.exe` còn không vào git (`*.exe` bị ignore) -> `/dl/*.exe` 404 | `downloads_manifest.json` (+ `scripts/publish_downloads.py`), commit `.exe` bằng `-f`, link có phiên bản | Web thật: 9 `.exe` + `.apk` đều 200, đúng tên file, SHA-256 trùng bản build; `.exe` tải từ web thật chạy 6/6 |
| 2 | 🔴 | Mỗi bill có SĐT khách chờ ~4 giây ngay tại quầy: đẩy sự kiện "đơn hoàn tất" tới Redis không cấu hình (mặc định localhost) — chưa có chương trình nào đọc sự kiện này | Không cấu hình REDIS_URL -> bỏ qua; Redis chết -> ngắt mạch 60 giây | Thanh toán Spa 5,2s -> 1,1s |
| 3 | 🔴 | POS Spa: bill tiền mặt lưu "pending" và KHÔNG có bước nào chuyển sang đã thu -> không vào sổ giao dịch, khách không được cộng điểm; có thêm 2 giây chờ giả "xác minh thanh toán" | Xác nhận tiền mặt = đã thu; bỏ chờ giả | status completed, có giao dịch, +240 điểm |
| 4 | 🔴 | POS Spa coi mọi tiệm là VND: tiệm Úc thấy dịch vụ $135 thành "135₫" và "≈ $0.0054" (tỉ giá cứng 25.000), mặc định VNPay, hiện mục thanh toán Việt Nam, SĐT gợi ý dạng VN | Tiền tệ của tiệm ở giỏ/tóm tắt/hộp thanh toán; tiệm đô mặc định tiền mặt, ẩn VietQR/VNPAY/MoMo | Giỏ + hộp thanh toán $240.00 |
| 5 | 🟠 | POS Spa không gán kỹ thuật viên -> hoa hồng phải nhập tay lần 2 | Chọn kỹ thuật viên cho từng dịch vụ; hoa hồng vào chấm công/lương; hoàn tiền tự thu hồi | 40% × $135 = $54, × $105 = $42 đúng từng xu; hoàn 100% -> ròng $0 |
| 6 | 🟠 | 2 danh sách nhân viên tách rời (/staff hoa hồng POS vs nhân sự/app) | Thêm ở đâu cũng có ở chỗ kia; thêm ở /staff được mã đăng nhập app NV0001…, đúng phòng ban | 45/45 (9 ngành) |
| 7 | 🟡 | Ô nhập Tên/Email/SĐT ở hộp thanh toán Spa là hộp trắng mặc định (class chưa từng định nghĩa) | Ô tối đồng bộ nền | — |
| 8 | 🟡 | Dữ liệu demo Spa (AUD) có khách chi tiêu kiểu VND -> CRM hiện $5,4 triệu, khách kẹt hạng Normal | Quy đổi (có sao lưu) | Tổng $6.390, hạng Silver/Gold/Platinum |
| 9 | 🟡 | Trang tải: hướng dẫn cài lẫn tiếng Anh trên trang tiếng Việt | 1 nguồn ngôn ngữ chung | 32/32 |

Build: lỗi Gradle "Unable to establish loopback connection" trên máy này đã gỡ được (JDK 17 + đường dẫn có dấu cách) -> `flutter build apk --release` chạy ~6 phút.

Còn treo / cần chủ dự án:
- Chữ ký số `.exe` (Windows SmartScreen) cần MUA chứng chỉ ký mã — trang tải đã hướng dẫn "More info → Run anyway".
- File `.apk` đã kiểm cấu trúc/chữ ký/quyền bằng công cụ Android SDK nhưng CHƯA chạy trên máy Android thật/giả lập (máy này không có trình giả lập; cài thêm cần tải ~1,5 GB).
- Thẻ thanh toán của POS Spa là form nhập số thẻ GIẢ LẬP (không xử lý thẻ thật, không gửi số thẻ đi đâu) — nên thay bằng cổng thẻ thật (Square/Stripe) hoặc bỏ.

**Chạy lại toàn bộ (vòng 3, 23/10, server local)** — không có lỗi chức năng mới:
- 9 ngành × desktop + iPhone (bộ master): 18/18 lượt sạch (F&B mobile 8/8 sau khi sửa script chờ đúng trang `/payment_pending`).
- Chủ + thợ Nails (persona) 147/147 ×2 · tuyển nhân sự 54/54 ×2 · gộp 2 danh sách nhân viên 45/45 ×2 · kỹ thuật viên Spa 9/9 ×2.
- App Windows (.exe) 38/38 · tải đúng thiết bị 32/32 · khu tải trên landing 47/47 (thêm kiểm link APK) · 11 landing 66/66 · bot bán hàng 18/18.
- Lỗi xuất hiện muộn (ở lại trang 20–30 lượt/ngành): 9/9 ngành, 284 lượt, 0 lỗi muộn.
- Thanh toán 39/39 + 16/16 · AI copilot 18/18 · Nails 8+9+6+7+38 · i18n 28 trang × 2 ngôn ngữ, 0 khoá dịch thô · cách ly dữ liệu giữa tiệm 30+28+28 · input dị dạng: 0 lỗi 500, server còn sống.
- Quét toàn trang 9 ngành (~1.140 lượt trang, 0 link nội bộ hỏng): chỉ còn `/super_admin` 403 với chủ tiệm và `/table_order` 400 khi không có mã QR bàn — đúng thiết kế. `/download/android` từng bị trình quét báo lỗi vì trình duyệt TẢI FILE thay vì mở trang (đúng) -> sửa trình quét.
- Dọn: 20 bản ghi QA còn sót ở tiệm demo + 476 cảnh báo rate-limit giả từ 127.0.0.1 (có sao lưu).

## Pha 25 — Landing mượt + chuyên nghiệp + đóng vai khách, nội dung trung thực (23/10/2026)

Tham khảo video "3 skill thiết kế cho Claude" (Emil Kowalski = chuyển động có chủ đích, Impeccable = bố cục/khoảng cách/chữ, Taste = tránh web đại trà) — áp dụng nguyên tắc, không cài gì thêm. Lớp dùng chung mới `templates/components/landing_polish.html` (gắn cuối 11 landing) + `components/whats_new.html`.

| # | Mức | Vấn đề (khách thấy) | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | 9 trang ngành: khách chọn EN (vd ở trang Nails) rồi sang trang khác vẫn **toàn tiếng Việt** (150–200 đoạn); chọn VN/EN không được lưu | Lưu + áp dụng lựa chọn ở mọi trang; khu tải về + chân trang theo đúng ngôn ngữ trang (trước đó Nails tiếng Anh mà khu tải tiếng Việt) |
| 2 | 🔴 | Trang chính: "10M+ đơn/tháng, 99.9% uptime, 5.000+ tài khoản thợ, 30% giảm thất thoát" + 3 lời khen 5 sao có tên (1 gắn "The Coffee House Q7") — không kiểm chứng được | Số thật (9 ngành · 4 nền tảng · 1000+ bill/lịch đã thử tải · 0 phí tải app); khối "Một ngày ở tiệm, trước/sau" ghi rõ "Ví dụ minh hoạ — không phải lời chứng thực" |
| 3 | 🔴 | 11 trang: "Business Registration: 888999777" (số giả), huy hiệu "AWS Cloud 99.99% SLA" (web chạy Vercel + MongoDB Atlas) | Gỡ số giả; huy hiệu đúng hạ tầng |
| 4 | 🔴 | HRM: "FaceID chống fake 100%", "sinh trắc học", "AI tự xếp ca" — chưa có trong sản phẩm (app chỉ có GPS + ảnh tải lên) | Sửa tiêu đề tab, mô tả Google, hero, FAQ SEO cho đúng; thân trang còn ~40 chỗ -> chờ quyết định (xây FaceID thật hoặc viết lại) |
| 5 | 🟠 | three.js (~600 KB, WebGL 60 khung/giây không nghỉ) chỉ để vẽ nền sao; hạt gần camera thành **ô vuông hồng to**; xoay theo chuột giật (hệ số 0,5) | Nền sao 2D tròn nhẹ (~150 chấm, 30 khung/giây, dừng khi tab ẩn, tắt khi "giảm chuyển động"); xoá three.js khỏi 11 trang (6 trang gọi THREE không kiểm tra -> sẽ chết AOS/FAQ/bảng tính nếu chỉ gỡ thư viện) |
| 6 | 🟠 | Khối hiện khi cuộn trễ tới 0,8 s rồi chạy 0,8–1 s, trượt 100 px -> cuộn nhanh thấy mảng trống | Trễ ≤150 ms, chạy 0,5 s, trượt 18 px; lưới an toàn: khối vào màn hình mà AOS chưa bật thì tự hiện |
| 7 | 🟠 | iPhone: nút "Liên hệ" dạng viên thuốc **che nút "Dùng thử miễn phí"** ở màn đầu | Nút tròn chỉ icon; ẩn ở màn đầu + khi đang cuộn xuống, hiện khi dừng |
| 8 | 🟠 | Máy tính: 6 nút tròn màu đứng dọc, nút gọi rung liên tục | Mascot + lên đầu + 1 nút "Liên hệ" bung ngang 4 kênh (cả trang trong app dùng cskh_widget.js) |
| 9 | 🟡 | iPhone: trang dài 24–38 màn hình; khối mascot chiếm trọn 1 màn không chữ; 9 thẻ ngành mỗi thẻ ~1 màn | Lưới ≥4 thẻ thành hàng vuốt ngang, 9 ngành 2 cột, mascot 300 px -> ngắn đi 25–30% (trang chính 37→27 màn, Nails 31→23) |
| 10 | 🟡 | Hiệu ứng nghiêng thẻ 15° (cả trên cảm ứng); thư viện destroy() lỗi "null.style" | 6°, chỉ khi có chuột; tự khởi tạo (data-bp-tilt) |
| 11 | 🟡 | Hero trang chính: "Tự Động Hóa Vận Hành Đa Ngành… B2B SaaS Empire V3.0" — khách không biết bán gì cho ai | "Một phần mềm cho cả tiệm · Bán hàng · lịch hẹn · lương thợ · chăm khách — bản riêng cho 9 ngành" + nút "Dùng thử miễn phí"/"Xem bản cho ngành của tôi" |
| 12 | 🟡 | "bám đuổi" (27 chỗ, nghe như rình rập khách), "BitPaw Software Software" (7 chỗ), chân trang tiếng Việt khi đang tiếng Anh | Sửa giọng văn; chân trang song ngữ |
| 13 | 🟡 | Khách không biết những gì vừa làm xong | Khối "Mới cập nhật · 10/2026" mỗi trang — CHỈ điều đã chạy + đã kiểm (từ Pha 12–24) |

Kiểm thử (server local, Chrome 1440 + iPhone 13, VI + EN): landing_polish 11/11 + nhớ ngôn ngữ 7/7 · landing_fab 7/7 · landing_mobile_blank 22/22 (0 màn trống) · landing_pages 66/66 · landing_download 47/47 · landing_sales_bot 18/18 (script cuộn qua màn đầu như khách thật) · download_device 32/32 · i18n 28 trang × 2, 0 khoá thô · quét toàn trang Nails 126 lượt, 0 link hỏng (3 cảnh báo cũ đúng thiết kế: /super_admin 403, /table_order 400) · trang trong app có nút Liên hệ mới: 0 lỗi JS.

Còn treo / cần chủ dự án: bảng giá USD + phí cài $999–4.999 trên trang tiếng Việt; pháp nhân + địa chỉ SF/Sydney ở chân trang (xác nhận thật hay thay); HRM ~40 chỗ FaceID, Kỹ thuật (GPS realtime, ký số, trừ kho phụ tùng), Karaoke (gọi món tại phòng) — xây thật hoặc viết lại; Điều khoản/Chính sách vẫn placeholder.


## Pha 26 — Khách Mỹ + Úc: giá USD/AUD, pháp lý thật, AI chạy thật, xây những gì landing đã hứa (23/10/2026)

Yêu cầu: "chủ yếu tiếp khách Mỹ và Úc, USD + AUD… AI bắt buộc làm được hết… thiếu chức năng nào cứ bơm… trang nào hứa quá thì xây hoặc viết lại… điều khoản và chính sách làm luôn". Pháp nhân BitPaw Technology LLC (SF + Sydney) là thật.

**A. Giá + pháp lý (commit 3a1b46e)**

| # | Mức | Vấn đề | Đã làm |
|---|---|---|---|
| 1 | 🔴 | Bảng giá VND/USD lẫn lộn, không có AUD; nút đăng ký không lưu gói | 3 gói Essential / Pro / Empire bằng USD + AUD (phí cài + tháng, ghi chú thuế GST/sales tax), tự chọn AUD cho khách Úc; trang /checkout viết lại, giá tính ở máy chủ, đơn đăng ký vào Super Admin |
| 2 | 🔴 | Điều khoản / Chính sách bảo mật / Thanh toán vẫn "đang cập nhật" | Viết đầy đủ EN + VI theo luật Mỹ + Úc: ACL, Privacy Act/APPs, CCPA, TCPA/Spam Act, xử lý AI ở nước ngoài, đồng ý chấm công khuôn mặt, GST, Square/PCI |

**B. AI + nhắn tin chạy thật (commit 61d79d0)**

| # | Mức | Vấn đề | Đã làm |
|---|---|---|---|
| 3 | 🔴 | AI Studio: 7 công cụ trả nội dung soạn sẵn khi AI lỗi, nút "xuất gói" giả, lịch sử ghi doanh thu giả | Báo lỗi thật; bộ video không mặt (cảnh + phụ đề .srt + đọc thử); lưu Brand DNA |
| 4 | 🔴 | Chăm sóc khách tự động: chuỗi tin được duyệt nhưng **không bao giờ gửi**; gợi ý là chữ cố định | messaging.py: SMS Twilio + email, STOP/START/HELP, khung giờ theo giờ tiệm, hàng đợi chống trùng; nhắc lịch, xin đánh giá Google, nhắn lại cuộc gọi nhỡ, báo cáo ngày cho chủ; gợi ý từ dữ liệu thật |
| 5 | 🔴 | Lịch sử mua của khách trong AI luôn rỗng (`'$_product'`) | Sửa truy vấn |
| 6 | 🔴 | HRM quảng cáo FaceID nhưng chỉ cần gõ mã nhân viên | Chấm công khuôn mặt thật: mẫu số hoá trên máy, bắt chớp mắt, so khớp ở máy chủ, vé 3 phút, có xin đồng ý, tắt = xoá hết |
| 7 | 🟠 | Điều phối thợ dùng toạ độ Nha Trang khi việc thiếu vị trí | Tra toạ độ từ địa chỉ (Nominatim, có cache) |

**C+D. Xây những gì landing hứa + chức năng ngành (commit 6c7f37c + commit này)**

| # | Ngành | Trước | Bây giờ (đã kiểm) |
|---|---|---|---|
| 8 | Karaoke | "Gọi đồ uống tại phòng" — không có | Mỗi phòng 1 mã QR có chữ ký; khách gọi món trên điện thoại, nhân viên thêm món ở quầy; bill = giờ + món; kho trừ khi tính tiền — 17/17 |
| 9 | HRM/Office/F&B/Spa | "AI tự xếp ca" — không có lịch ca nào | /roster: khai nhu cầu người theo khung giờ → tự xếp né nghỉ phép, ngày bận, giờ tối đa (38 h Úc / 40 h Mỹ); chép tuần; công bố → app nhân viên + SMS/email; đi trễ/vắng so với check-in thật; ước tính lương — 28/28 |
| 10 | HRM/Office | "Chống fake GPS / chấm công Wifi" — chưa chặn gì | "Chỉ chấm công tại tiệm": chủ đặt vị trí + bán kính; ngoài bán kính bị từ chối (trừ sai số GPS máy báo), bản offline chỉ đánh dấu — 11/11 |
| 11 | Office/HRM | "Gửi phiếu lương bảo mật" — không có | Nút "Gửi bảng lương": email cho từng người số của riêng họ (ghi rõ không thay phiếu lương theo luật) |
| 12 | Kỹ thuật | Khách không biết thợ tới lúc nào | Thợ bấm "ON MY WAY" → khách nhận SMS + link theo dõi (chỉ tên gọi, phút dự kiến, bản đồ; tới nơi/vị trí cũ/xong việc thì ẩn vị trí); chưa có Twilio thì mở app nhắn tin của máy — 14/14 |
| 13 | Spa/Nails | "Thẻ liệu trình số" — không có | Gói nhiều buổi: tạo, bán tại quầy (doanh thu + sổ cái), dùng buổi ở POS Spa (bill 0, trừ buổi nguyên tử, hoa hồng KTV theo giá trị 1 buổi), chặn sai khách/sai dịch vụ/hết hạn, 2 máy dùng buổi cuối chỉ 1 thành công, hoàn tiền trả buổi — 15/15 |
| 14 | Sản xuất/Bán lẻ/F&B | Cảnh báo tồn kho chỉ trên màn hình | Hàng dưới ngưỡng "nguy cấp" vào email báo cáo mỗi sáng của chủ |

**E. Viết lại nội dung hứa quá (11 landing + JSON trang chính + FAQ SEO)**
- Bỏ: FaceID/sinh trắc, "chống fake 100%", vệ tinh, "AI dự báo nghỉ việc / lãi lỗ / bảo trì máy", "AI Radar ép nhận lệnh", Wifi MAC, AES-256, "API mở sang CRM/ERP", kho trên từng xe thợ, định lượng nguyên liệu F&B, đồng bộ OTA/Shopee/TikTok (ghi rõ "đang trong lộ trình"), giường/phòng spa, thẻ khoá phòng, phụ thu trả phòng trễ tự động, "Đế chế… Radar AI… tại Việt Nam".
- Thay bằng đúng những gì đang chạy (và đã có test): GPS + ảnh + khuôn mặt, giới hạn bán kính, lịch ca, gói liệu trình, thợ đang đến, gọi món QR phòng, AI soạn tin **để chủ duyệt** rồi gửi qua SMS/email có STOP.
- 38 link hiện tên file (`bangluong.html`…) → "Dùng thử →". Chữ cảnh báo KCS ở màn công nhân không còn hứa "tự gửi báo cáo".
- landing_spa có 2 bộ từ điển (1 bộ nằm nhầm trong `titles` của popup chính sách) — sửa đúng bộ đang dùng.
- App nhân viên (giao diện tiếng Anh) còn chữ Việt "Sếp", "NHẬN JOB NÀY"… → tiếng Anh.

Còn treo / ghi nhận: đồng bộ Shopee/TikTok Shop/Lazada và OTA khách sạn cần duyệt đối tác (đã ghi "lộ trình" trên trang); trừ kho theo định lượng cho F&B; in nhãn mã vạch; kho theo xe thợ; trang Nails vẫn chào "tặng phần mềm khi làm website" — khác với bảng giá USD/AUD ở trang chính (chủ dự án quyết giữ hay bỏ ưu đãi này).

Lỗi thật tìm thêm khi chạy lại toàn bộ (đã sửa): (1) Thanh toán Spa của tiệm Mỹ/Úc KHÔNG có nút Tiền mặt (nằm trong nhóm "Việt Nam" bị ẩn), chỉ còn cổng thẻ/ví giả lập có ô nhập số thẻ → nay tiệm đô có nhóm "Thu tại quầy": Tiền mặt / Thẻ (máy quẹt của tiệm) / Chuyển khoản. (2) Bấm phương thức thanh toán ở Spa đổi tiền tệ sang VND với cả tiệm AUD → hộp kết quả hiện "₫". (3) Khách sạn: mọi lần trả phòng ghi "tiền mặt" → lễ tân chọn tiền mặt/thẻ/chuyển khoản, báo cáo tách đúng. (4) Bài test F&B bán món thật mà không trả kho → kho demo cạn, thanh toán bị chặn "không đủ hàng" (hệ thống chặn đúng) → snapshot/khôi phục tồn kho. (5) Tiệm Nails demo bị bật sẵn chấm công khuôn mặt từ lượt test cũ → tắt lại. (6) Lúc viết lại chữ landing, 4 trang bị lỗi 500/JS do chuỗi có url_for('…') — sửa và thêm kiểm tra HTTP 200 cho cả 11 trang.

Kiểm thử (server local, Chrome + iPhone 13, VI + EN): lịch ca 28/28 · geofence 11/11 · gói liệu trình 15/15 · thợ đang đến 14/14 · karaoke QR 17/17 · khuôn mặt 22/22 · nhắn tin 21/21 · AI Studio 22/22 · AI Copilot 18/18 · giá USD/AUD 20/20 · chủ + nhân viên 9 ngành 147/147 · Nails persona 38/38 · Nails master 10/10 · bot Nails 7/7 · Spa master 6/6 · KTV Spa 9/9 · đồng bộ nhân viên 45/45 · F&B 8/8 · Hotel 5/5 · Karaoke 4/4 · Bán lẻ 6/6 · Sản xuất 3/3 · Kỹ thuật 3/3 · Văn phòng 4/4 · 11 landing 66/66 · mượt 11/11 + nhớ ngôn ngữ 7/7 · màn trống iPhone 0/22 · nút Liên hệ 7/7 · khoá dịch thô 0 (31 trang × 2) · input dị dạng 0 lỗi 500, server sống.

## Pha 27 — AI làm việc thật (đóng vai hàng trăm khách), lịch ca kiểu Deputy, tin nhắn/bản đồ không trễ, đăng nhập Google/Facebook (23–24/10/2026)

Yêu cầu: "mấy con AI đó fix, test khách như người thật… mỗi con AI cả trăm khách dùng như thế nào, vừa test vừa đánh tâm lí… lịch chấm công bơm thêm cho phong phú… app nhân viên, bản đồ, messenger trôi chảy không delay… test đăng ký đăng nhập Google, Facebook… AI phải hoạt động dựa trên những con AI đã làm được việc".

**Cách đo (không tự chấm cho mình):** bộ giả lập `scripts/ai_sim/` — DeepSeek đóng vai khách (8 kiểu tâm lý × 4 kiểu ngôn ngữ: Anh-Úc, Anh-Mỹ, Việt có dấu, Việt không dấu), gọi ĐÚNG API widget thật như trình duyệt (phiên + CSRF), 1 giám khảo AI riêng (nhiệt độ 0) chấm 7 tiêu chí + soi **cơ sở dữ liệu thật** sau mỗi cuộc chat (có lịch thật không, đúng giờ không, có trùng không). Tốc độ gọi giữ dưới giới hạn thật của server (không tắt rate-limit).

**A. Trợ lý đặt lịch của tiệm (100 khách / lượt)**

| | Trước | Sau |
|---|---|---|
| Điểm chung (0–5) | 3.70 | **4.64** |
| Trung thực | 2.79 | **4.88** |
| Hoàn thành việc khách cần | 2.92 | **4.45** |
| Lịch trong DB đúng | 45/96 | **91/96** (5 ca còn lại soi tay: 3 đúng hành vi — khách đổi ý/đổi thợ, bộ kiểm quá chặt; 2 do chính bài test lịch ca chạy song song chiếm chỗ) |
| Câu trả lời dự phòng / lỗi | — | 0 / 0 |
| Độ trễ p50 / p90 | 2.0 / 3.2 giây (nhưng bịa giờ trống) | 3.9 / 5.9 giây (kiểm giờ thật) |

| # | Mức | Lỗi thật (đo được) | Đã sửa |
|---|---|---|---|
| 1 | 🔴 | Bot tạo 151 lịch cho 100 khách; hứa giờ không có thật; khách nói "ok đặt đi" 2 lần là 2 lịch | Luật đặt lịch dùng chung `booking_rules.py` (giờ mở cửa từng thứ, bước giờ, đặt trước tối thiểu/tối đa, thời lượng từng dịch vụ, sức chứa = số thợ có ca trong Lịch ca); công cụ `check_availability` (có kiểm ĐÚNG giờ khách hỏi + giờ gần nhất), chống trùng, khách 1 người không thể 2 dịch vụ cùng giờ, đặt nhóm |
| 2 | 🔴 | Kiểm giờ trống mất **11,5 giây** (≈200 lượt gọi Atlas mỗi câu) → câu trả lời 10–28 giây | Đọc dữ liệu cả ngày 1 lần + cache luật/tên thợ 20 giây → 0,4 giây; p90 toàn câu 5,9 giây |
| 3 | 🔴 | Chuyển cho nhân viên xong là **im lặng** — khách nhắn 3–5 tin không ai đáp rồi bỏ đi | Chế độ "chờ người": AI vẫn tiếp khách (trả lời giờ mở cửa, giá, đặt lịch) nhưng không quyết vấn đề đã chuyển; câu hẹn giờ trả lời THẬT theo giờ mở cửa + SĐT tiệm; email báo chủ ngay (gửi đúng 1 thư, không chờ cả hàng đợi); hộp thư AI Bot có nhãn "Needs reply/Urgent" lên đầu |
| 4 | 🔴 | Hỏi giảm giá/voucher/bãi xe là AI tự tắt cả cuộc chat | Công cụ mới `ask_team`: ghi câu hỏi cho nhân viên, AI vẫn giúp tiếp; `handoff_to_staff` chỉ cho phàn nàn / đòi gặp quản lý |
| 5 | 🟠 | Báo "đã đặt xong" trong khi lịch đang "chờ duyệt" | Cài đặt "Xác nhận lịch online": tự xác nhận (mặc định, như Fresha) hoặc chờ tiệm duyệt; AI nói đúng theo trạng thái thật; trang đặt lịch hết hứa "Open 24/7", màn thành công hết "Satellite Station" |
| 6 | 🟠 | Thiếu địa chỉ/bãi xe thì AI không biết | Trang Cài đặt đặt lịch hiện "Câu khách hỏi mà AI chưa trả lời được (30 ngày)" để chủ điền (kiểu "content gaps" của Intercom Fin) |
| 7 | 🟡 | Hội thoại mẫu ở chế độ Demo có dịch vụ tiệm không làm (nối mi) + "ưu đãi 10%" bịa | Viết lại đúng cách AI thật làm việc |

Điểm theo kịch bản (trước → sau): phàn nàn 2.61→4.07 · hỏi 2 lần "đặt đi" 2.71→4.82 · đổi ý 2.89→4.89 · hỏi thông tin 2.93→3.61 (thiếu địa chỉ trong dữ liệu demo) · "lịch của tôi mấy giờ" 3.04→4.89 · dời lịch 3.11→4.25 · thợ chỉ định 3.57→4.82 · đặt nhóm 3.21→4.82.

**B. Copilot của chủ tiệm (40 câu hỏi có đáp án lấy thẳng từ DB)** — trước chỉ đọc 1 bản tóm tắt nên trả lời sai số: đúng số liệu **1.58 → 4.92**, đúng 3.3 → 4.33, hữu ích 4.03 → 4.8. Nay là trợ lý có 9 công cụ đọc số thật (doanh thu theo kỳ/dịch vụ/thợ/thanh toán, lịch theo ngày, tra khách, khách lâu chưa quay lại, hoa hồng + giờ ca + trễ/vắng, lịch ca, kho, gói liệu trình, hộp thư). Đã gọn câu trả lời theo loại câu hỏi (tra cứu = trả lời + tối đa 1 gợi ý). Lượt cuối (v4): đúng số liệu 5.0, ngắn gọn 3.55 → 4.42, p50 4.05 giây; "hoàn tiền đơn 123" → nói rõ không làm được, chỉ chỗ làm trong BitPaw.

**C. Bot tư vấn BitPaw (60 chủ tiệm Mỹ/Úc/Việt kiều)** — lượt cuối (v4): điểm chung 4.62, trung thực 4.57, chính xác 4.37, đồng cảm 4.95, an toàn 4.9; lưu đủ 15/15 lead khi khách đồng ý, 0 lead trùng, 0 câu dự phòng; p50 4.6 giây. (Lượt v3 bị dừng: bộ kiểm lead dò sai — khách giả lập tự bịa email/SĐT khác persona nên báo "chưa lưu" oan; đã sửa bộ kiểm + dọn 16 lead thử có email trông như thật khỏi DB.)
- Lỗi thật: lưu 1 khách 2 lần trong 1 cuộc chat → nay cập nhật lead cũ (24 giờ). Khách Úc đôi khi được báo giá USD trước → luật tiền tệ theo nơi khách ở. "You're booked in" khi mới chỉ lưu liên hệ → cấm, nói "đội sẽ liên hệ để hẹn demo".
- Form liên hệ `/api/cskh/request` chỉ nhận số VN (`^0\d{9,10}$`) → nhận số quốc tế (+1, +61). Gỡ `/api/cskh/lead-submit` (không ai gọi, ghi vào SQLite không tồn tại trên Vercel).

**D. Các AI khác**
- Chăm sóc khách tự động: tin 7 và 14 ngày có link đặt lịch thật của tiệm (như tin "rebook" của Fresha/Square); số ngày tính tới ngày gửi; dưới 190 ký tự (tiết kiệm SMS); cấm bịa "giữ chỗ quen".
- AI Studio: được nạp dịch vụ + giá thật + link đặt lịch + thông tin tiệm (như Shopify Magic) — hết "[price]".
- Copilot báo lỗi đúng ngôn ngữ chủ tiệm.

**E. Lịch ca nâng cấp (so với Deputy / 7shifts / When I Work)** — `scripts/roster_plus_e2e.mjs` 38/38
- Ca trống: chủ đăng, nhân viên bấm "Nhận ca" trên app (2 người bấm cùng lúc chỉ 1 người được); tự xếp lịch không lấp chỗ đã đăng ca trống; chép tuần giữ ca trống; tin công bố lịch báo số ca trống.
- Đổi ca gắn ca thật: xin đổi đúng 1 ca → đồng nghiệp đồng ý → chủ duyệt → lịch tự đổi người, cả 2 được báo (SMS/email). Chặn: ca không phải của mình, ca đã qua, trùng yêu cầu, người nhận bị trùng ca/ngày bận/vượt giờ.
- Nhân viên tự khai "ngày tôi không làm được" (tự xếp lịch né).
- Tăng ca: quá 38 giờ (Úc) / 40 giờ (Mỹ) → cảnh báo + phụ trội 1,5×; thẻ chi phí lương có % so với doanh thu 7 ngày.
- App nhân viên: thêm lối "Xem lịch ca & yêu cầu (không chấm công)" — trước đây màn chấm công chặn hết, ngày nghỉ không nhận ca/trả lời đổi ca được. Hết chữ lóng ("Đã ném thiệp nhờ vả. Chờ Rep!", "chốt kèo", "Sếp", "Vệ tinh Radar") — 40+ thông báo theo ngôn ngữ tiệm.

**F. Tin nhắn + bản đồ không trễ (đo thật, local)**
- Messenger: p50 437 → **225 ms**, p90 552 → 284 ms, chậm nhất 1134 → 455 ms, 0 tin lạc; tab rảnh 32 → 14 request/phút (tin mới kèm luôn nội dung, không tải lại cả danh sách).
- Bản đồ thợ: đổi vị trí → chấm dời sau p50 **127 ms**, p90 179 ms, 0 lần tải lại cả danh sách, 0 lỗi JS (`scripts/map_latency_probe.mjs`).

**G. Đăng nhập Google / Facebook** — `scripts/oauth_login_e2e.mjs` 14/14 với máy chủ OAuth giả lập: người mới → trang hoàn tất (mã kích hoạt), lần 2 vào thẳng, liên kết theo email đã xác minh, từ chối email chưa xác minh, chặn state giả + open-redirect, Facebook không email, PKCE + đổi code ở máy chủ, tài khoản chỉ-Google đăng nhập mật khẩu không lỗi. Trong app di động nút không hiện (Google chặn OAuth trong WebView). Chính sách bảo mật EN/VI thêm mục dữ liệu Google/Facebook (Limited Use) + cách ngắt kết nối/xoá. **Cần anh/chị làm:** tạo OAuth client Google + app Facebook, dán 5 biến vào Vercel — hướng dẫn từng bước: `docs/OAUTH_SETUP.md`.

**H. Dọn dữ liệu thử + công cụ test**
- Bài audit Nails/Spa để lại lịch "QA Audit Khach Hang" trong tiệm demo (Copilot còn đọc ra) → đã xoá + script tự dọn. 4 lịch thử cũ đã xoá.
- 7 script đặt lịch cũ gõ ô datetime tự do → dùng chung `scripts/lib/booking_slot.mjs` (chọn nút giờ trống thật). 57 script nhận `BASE=` để chạy song song trên server phụ.
- Lead giả lập có email/SĐT khách giả tự bịa → dọn theo đúng liên hệ trong transcript; thư báo chủ tiệm do giả lập tạo → xoá + giả lập tự dọn.

**I. Lỗi "hôm nay" sai ngày cho tiệm Mỹ/Úc (bắt được nhờ chạy hồi quy lúc nửa đêm)** 🔴
- Lịch sử bill POS Nails mặc định `new Date().toISOString()` = ngày **UTC**: tiệm Úc (UTC+10/11) mỗi sáng tới ~11 giờ mở ra bill **hôm qua**, tiệm Mỹ mỗi tối mở ra **ngày mai** (trống). Cùng lỗi ở 24 chỗ khác (ngày mặc định báo cáo/chi phí/khuyến mãi, ngày tối thiểu trang đặt bàn/khách sạn/karaoke/đặt lịch, tên file xuất Excel/PDF…) → đổi hết sang ngày địa phương.
- Máy chủ (Vercel chạy UTC) tính "hôm nay" bằng giờ máy chủ ở Lịch hẹn, Đặt bàn, Karaoke, Khách sạn, doanh thu hôm nay trên Dashboard, thu nhập thợ hôm nay, lịch sử bill, Lịch ca (tuần mặc định, đối chiếu trễ/vắng, ca của tôi) → thêm `tenant_today()` / `tenant_day_bounds()` (giờ theo tiệm, đổi khoảng ngày sang giờ máy chủ cho `created_at`).
- Bài test lịch ca + app nhân viên giờ chạy theo đúng giờ tiệm (điện thoại giả lập đặt múi giờ Sydney).

**Kiểm thử Pha 27:** chạy lại toàn bộ trên server local (Chrome + iPhone 13, VI + EN), restart sạch giữa các nhóm — cài đặt đặt lịch 16/16 · lịch ca nâng cấp 38/38 · lịch ca 28/28 · chấm công khuôn mặt 22/22 · Nails persona 38/38 · Nails audit 10/10 · AI chăm sóc khách Nails 7/7 · lịch realtime 6/6 · vòng kinh doanh Nails 9/9 · Spa audit 6/6 · Spa POS thợ 9/9 · gói liệu trình 15/15 · đồng bộ nhân viên 45/45 · F&B 8/8 · Bán lẻ 6/6 · Karaoke 4/4 · gọi món QR karaoke 17/17 · Khách sạn 5/5 · Sản xuất 3/3 · Kỹ thuật 3/3 · Văn phòng 4/4 · geofence 11/11 · thợ đang đến 14/14 · nhắn tin 21/21 · AI Copilot 18/18 · AI Studio 22/22 · bảng giá/checkout 20/20 · 0 khoá dịch thô (32 trang × 2 ngôn ngữ) · 9 ngành chủ + nhân viên 147/147 · bảo mật/input dị dạng: server sống · Google/Facebook 14/14 · giả lập AI đặt lịch sau cùng 9/9 lịch đúng, trung thực 5.0, p50 3.1 giây. Dữ liệu thử đã dọn (lịch, lead, thư báo, nhân viên, ca).


## Pha 28 — Bảo mật chống hacker + chống crack, giao diện chuyên nghiệp (mobile + PC), trải nghiệm KHÁCH của tiệm (24/10/2026)

Yêu cầu: "nâng cấp hệ thống bảo mật lên, chống hacker… crack tool là cái thứ 1… để ý chi tiết kỹ mobile… fix giao diện cho chuyên nghiệp… background cho mobile kể cả PC… nhiều icon nhìn như con nít… tâm lý khách hàng trải nghiệm nền tảng ngoài thợ với chủ tiệm nữa".

**A. Chống hacker** (`security_shield.py`, `password_reset.py`, app.py)
| Mục | Trước | Sau |
|---|---|---|
| Công cụ tấn công (sqlmap, nikto, nuclei…) / dò `.env`, `wp-login`, `.git` | trả trang bình thường, không ai biết | 403/404; 3 lần dò trong 10 phút → cấm IP 1 giờ (tái phạm 24 giờ); nhật ký + tab "Bảo mật" trong Super Admin có nút gỡ cấm |
| IP thật của khách | tin header (giả được) | chỉ tin `CF-Connecting-IP` khi request đi qua Cloudflare thật |
| CSP | không có | bắt buộc: script/kết nối chỉ từ domain mình + CDN đã duyệt; chặn iframe nhúng, đổi `<base>`, plugin — quét 219 lượt trang: 0 vi phạm, 0 lỗi JS |
| Đổi/đặt lại mật khẩu | cookie + JWT cũ sống tiếp 30 ngày | mọi phiên + app đăng xuất trong ≤30 giây; nút "Đăng xuất mọi thiết bị"; tài khoản bị khoá/đổi quyền có hiệu lực ngay |
| Quên mật khẩu | không có | link 1 lần, 30 phút, chỉ lưu mã băm, trả lời giống nhau dù email có hay không, giới hạn 5/giờ/IP + 3/giờ/email |
| Mã kích hoạt | kiểu "TEN123456" đoán được | `BP-XXXXX-XXXXX-XXXXX-XXXXX` ~100 bit; đoán sai 8 lần/giờ → khoá |
| Form công khai | bot gửi tự do | ô bẫy bot (liên hệ, đặt lịch, đặt bàn/phòng) → "thành công" giả, không ghi, IP bị trừ điểm |
| Lỗi 500 trên production | lộ nội dung lỗi Python | thông báo chung, lỗi thật chỉ vào log |
| 🔴 **Menu QR / gọi món / gọi nhân viên** | nhận id bàn SỐ TĂNG DẦN — 1 script chạy id 1..N gửi được đơn giả + chuông "gọi nhân viên" vào bếp của MỌI nhà hàng, và đọc được mã QR thật từng bàn | chỉ nhận mã QR ngẫu nhiên in trên bàn; id số chỉ mở được khi người đang đăng nhập là chính tiệm đó; tên bàn trong thông báo lấy từ hệ thống (không lấy chữ khách gửi) |
| 🔴 **Đặt bàn / phòng karaoke / phòng khách sạn công khai** | ghi được đơn vào mã tiệm bịa bất kỳ; tên/ghi chú dài vô hạn; số khách 999999; ngày giờ bất kỳ; chỉ giới hạn chung 1200/giờ | tiệm phải có thật; tên ≤80, ghi chú ≤500, số khách 1–200, ngày giờ đúng định dạng trong vòng 1 năm; 20 lượt/giờ/IP; khách sạn ≤60 đêm |
| Giới hạn tần suất | 9 API công khai chỉ có giới hạn chung | thêm riêng: liên hệ 10/giờ, góp ý 20/giờ, chat khách 120/giờ, đọc chat theo SĐT 600/giờ, khung chat của tiệm 200/giờ, gửi ảnh 30/giờ, gửi đơn QR 300/giờ (cả quán chung 1 Wi-Fi), gọi nhân viên 120/giờ |

**B. Chống crack**
- App Windows là vỏ WebView mỏng (`desktop_app/shell.py`): không chứa khoá, mật khẩu, logic bản quyền — bẻ khoá file .exe không mở thêm được gì; mọi kiểm tra quyền/gói nằm trên máy chủ. `launcher.py`/`license_manager.py` cũ không còn được đóng gói.
- Android: tắt sao lưu dữ liệu app (`allowBackup=false`, `dataExtractionRules` loại trừ hết) — không rút được phiên đăng nhập qua `adb backup`/chuyển máy. Bản build CI: `--obfuscate --split-debug-info` (khó dịch ngược).
- Mã kích hoạt ngẫu nhiên 100 bit + khoá khi đoán (mục A).

**C. Giao diện chuyên nghiệp (mobile + PC)**
- Lớp "Pro" chèn vào mọi trang ứng dụng: 1 nền xanh than thống nhất, bỏ tia laser/vạch quét/hạt bay/đốm mờ khổng lồ/vòng xoay hologram, viền neon → bóng nhẹ, chữ quá đậm/giãn rộng → vừa phải, tiêu đề chữ cầu vồng → chữ trắng, tiêu đề trên điện thoại vừa màn hình.
- Bộ icon 3D đồ chơi tắt (giữ icon nét); **592 dòng emoji làm icon** (trong nhãn, nút, menu chọn, toast, 2 ngôn ngữ) bỏ; **40 emoji đứng riêng** (thẻ ngành, ảnh món trống, avatar 👤, ✨ "Thêm dịch vụ", 🍻 F&B) → icon nét; 12 ô trống do lần bỏ emoji cũ để sót ký tự ẩn (U+FE0F) → sửa.
- Trang đăng nhập viết lại (đơn giản, có "Quên mật khẩu" thật); app nhân viên ("Employee code", "Continue" thay "START SHIFT"); trang chọn ngành có tên tiếng Anh; trang lỗi/QR hỏng chỉ 1 ngôn ngữ + icon nét; tiêu đề Spa bỏ chữ có chân; nút "Calculate Pay" hồng gradient → nút viền nhẹ; Cài đặt đặt lịch + Hồ sơ nhân viên không còn tràn màn hình điện thoại; nút ngôn ngữ không đè khung đăng nhập; menu Hotel/Karaoke/Sản xuất có bản dịch tiếng Anh.
- Giọng văn trong app: bỏ "Sếp/Boss", "Chờ xíu nha", nhân vật "kỹ sư Hậu" bịa; hoá đơn in cho khách không còn "Hẹn gặp lại sếp".
- Build lại `tailwind.output.css` (các lớp mới có thật trong CSS).

**D. Trải nghiệm KHÁCH của tiệm (người quét QR / bấm link đặt lịch)**
- Đặt lịch Nails/Spa: tên + logo TIỆM, địa chỉ + bấm gọi được, nhãn chữ thường, giờ trống dạng nút gọn, "Any available technician", dòng cam kết "SĐT chỉ dùng để xác nhận lịch". Sửa lỗi nhãn "Full name" luôn nổi lên dù ô trống (ô bẫy bot đặt nhầm chỗ).
- Đặt bàn / phòng karaoke / phòng khách sạn: viết lại thành 1 trang dùng chung — trước chỉ tiếng Việt, tiêu đề "BitPaw", số mẫu "09xxxxxxxx", ô giờ tràn ngoài màn hình; giờ tên + chữ cái/logo QUÁN, tự theo ngôn ngữ trình duyệt (Anh/Việt), báo lỗi đúng ngôn ngữ, sau khi gửi có tóm tắt.
- Menu QR / gọi món tại bàn: chữ cái/logo quán thay logo BitPaw nhấp nháy; ngôn ngữ theo trình duyệt khách (trước luôn tiếng Việt).
- Khung chat của tiệm với khách (`/portal`): tiêu đề là tên tiệm; bỏ khối "Liên hệ với Sếp" + bong bóng chat của BitPaw (khách của tiệm thấy hotline của hãng phần mềm); sửa tràn ngang trên điện thoại.
- Trợ lý chat trên trang đặt lịch: tên tiệm + "Booking assistant", đúng ngôn ngữ trang (trước "BitPaw AI Tư Vấn" tiếng Việt cho khách Úc/Mỹ).

**D2. Số liệu thật + đúng tiền tệ (soát tay 64 trang chủ tiệm × điện thoại + máy tính, `scripts/ui_survey_all.mjs`)**
- Số liệu BỊA hiện cho chủ tiệm thật: Kết nối đa kênh "10,480 khách đồng bộ +12% tuần này · AI CSKH 342 · quay lại 45.2% +14.6%" (khi 0/6 kênh); Chăm sóc khách "Good (84/100) · 42 khách cần chăm · 8.4% · +32 khách/tháng"; launcher "142 chats · +28 leads" + bảng hoạt động "David ở tiệm Nails Georgia vừa nâng cấp gói Pro" (danh sách tên/tiệm bịa, ghi rõ trong code là SIMULATED để tạo FOMO). → số thật của tiệm (tổng lead các kênh, tính từ khách thật, hội thoại hôm nay theo giờ tiệm, `/api/my_recent_activity`) hoặc "—".
- Tiệm Úc/Mỹ thấy tiền Việt ở 8 trang ("100.838,44 ₫" báo cáo lợi nhuận, "Amount (VND)", "VND/Month", "Budget (VNĐ)", "Selling price (VND)"...) → `static/js/bp-currency.js` (chỉ nạp cho tiệm khác VND) sửa nhãn đơn vị; báo cáo lợi nhuận + giỏ Spa định dạng theo tiền tệ của tiệm. Quét lại: 0 trang hiện ₫ cho tiệm AUD (trừ trang quản trị thanh toán của BitPaw có cả 2 cột VND/USD).
- Thông báo "Vui lòng đăng nhập để tiếp tục", "phiên không hợp lệ", "không có quyền", "quá nhiều lần thử" → theo ngôn ngữ người dùng.
- Trang Kết nối sàn TMĐT: ô API Key/Secret trắng trơn (lớp CSS chưa định nghĩa) → đúng kiểu; tiêu đề trang trên điện thoại không còn bị bóp thành nhiều cột.

**E. Công cụ test mới / sửa**
- `scripts/security_hardening_e2e.mjs` (35 bước), `scripts/public_endpoints_hardening_e2e.mjs` (17 bước), `scripts/csp_crawl_audit.mjs`, `scripts/ui_survey_shots.mjs` (thêm trang khách), `scripts/ui_survey_all.mjs`.
- 10 bài audit ngành kiểm "bị giới hạn" bằng cả mã HTML (trang đăng nhập mới có chữ 429 trong JS → báo nhầm) → kiểm chữ hiện trên trang.
- Bài audit F&B/Karaoke/Khách sạn để lại 33 đơn đặt chỗ "QA Audit…" trong tiệm demo → đã xoá + script tự dọn (`scripts/_cleanup_audit_reservations.py`).
- Bài đo trễ chat để lại 12 tin "latency-probe…" trong kênh chung của tiệm demo (bước dọn trống) → đã xoá + bước dọn thật.
- `shared_modules_pha6_audit` phần Checkout đã cũ (trang checkout làm lại ở Pha 26) — thay bằng `pricing_checkout_e2e` 20/20.

**⚠️ Sửa sai (25/10):** Pha 28 đã TỰ Ý thay logo chú chó Shiba của chủ dự án (`static/cho1.jpg`, 60 trang) bằng chữ B phẳng tự vẽ (`mark.svg`) và đổi ảnh chia sẻ link — chủ dự án phản đối. Đã trả lại logo chó ở cả 101 chỗ (2 chỗ vốn dùng chữ B neon của chủ cũng trả đúng ảnh gốc), xoá `mark.svg`/ảnh chia sẻ tự vẽ. Không đổi nhận diện thương hiệu khi chưa hỏi chủ.

**F. Cần anh/chị quyết định**
- Gói/quyền theo gói: hiện mọi tiệm dùng được mọi tính năng (chưa có giới hạn theo gói Essential/Pro/Empire).
- Icon app/PWA/favicon vẫn là chữ B neon cam (đã duyệt ở Pha 24) — trong app đã dùng logo phẳng xanh; có thể đổi icon app sang logo phẳng cho đồng bộ.
- 11 trang landing giữ thiết kế riêng (chữ gradient marketing) — có thể làm gọn theo cùng phong cách nếu muốn.
- `static/js/ai_sales_widget.js` không trang nào dùng (code chết) — có thể xoá.
- Chat khách vãng lai trên landing vẫn khoá theo SĐT (đánh đổi có chủ đích từ trước) — đã giới hạn tần suất; muốn chặt hơn cần thêm mã bí mật cho từng hội thoại.

**Kiểm thử Pha 28:** chạy lại trên server local (Chrome + iPhone 13, VI + EN), restart sạch giữa các nhóm — chống tấn công 35/35 · trang/API công khai 17/17 (mới) · quét CSP 219 lượt: 0 vi phạm, 0 lỗi JS · khoá dịch thô 0 (32 trang × 2 ngôn ngữ) · chủ + nhân viên 9 ngành 147/147 · Nails persona 38/38 · Nails audit 10/10 · Spa 6/6 · F&B 8/8 · Bán lẻ 6/6 · Karaoke 4/4 · Khách sạn 5/5 · Kỹ thuật 3/3 · cài đặt đặt lịch 16/16 · lịch ca 28/28 · lịch ca nâng cấp 38/38 · đăng nhập Google/Facebook 14/14 · tin nhắn SMS/email 21/21 · checkout gói 20/20 · chịu input dị dạng: server còn sống. Soát tay 64 trang chủ tiệm trên điện thoại + máy tính: 0 trang tràn ngang, 0 trang hiện ₫ cho tiệm AUD. Lần chạy đầu: lịch ca nâng cấp 36/38 (chạy song song với bài soát giao diện, chạy riêng 38/38); OAuth/tin nhắn cần server có cấu hình giả lập (chạy đúng cách: đạt).

**Pha 28b (25/10) — khung chat thiếu logo chú chó, làm gọn 11 landing, nền thống nhất**
- Khung "BitPaw tư vấn" vẫn hiện chữ B: trình duyệt + Cloudflare giữ `cskh_widget.js?v=20261023` cũ (cache 4 giờ). Giờ `asset_v()` (app.py) gắn mã theo NỘI DUNG file cho widget chat, `bitpaw-pro*.css`, `bp-currency.js` — sửa file là khách nhận bản mới ngay.
- 11 landing: lớp `static/css/bitpaw-pro-lite.css` mới — bỏ nền sao chuyển động (#bg-canvas), vạch quét, lấp lánh, đốm neon; logo chú chó đứng yên; chữ gradient → 1 màu nhấn của ngành; bỏ neon/nhấp nháy/trôi. Giữ nguyên bố cục, nội dung, logo, màu từng ngành.
- Chữ: nhãn đầu trang 10 ngành ngắn + viết hoa đầu câu (vi/en); tiêu đề Nails thôi Viết Hoa Từng Chữ; bỏ xưng "Sếp" ở 5 landing (trang Văn phòng giữ — ở đó "sếp" là người quản lý thật).
- Nền: mọi trang (app, khách, landing, giới thiệu, thanh toán, tải app, pháp lý) cùng nền #0b1120.
- Kiểm thử: landing_pages 66/66 · landing_polish đạt · landing_mobile_blank 0 màn trống · landing_fab đạt · landing_download 47/47 · CSP 219 lượt 0 vi phạm. Công cụ mới: `scripts/landing_shots.mjs` (máy tính + điện thoại, FULL=1 chụp toàn trang đã hiện hết hiệu ứng cuộn).

**Pha 28c (25/10) — "thấy nào hợp lí là làm": chuẩn hoá thương hiệu + chữ landing**
- Logo trên trang = chú chó ở MỌI trang (thêm trang thanh toán gói, trang tải app). Chữ B neon giữ đúng vai trò icon của app (favicon, icon cài đặt, hộp "Thêm vào màn hình chính") — khách cài xong thấy đúng icon đó.
- 427 chuỗi tiếng Việt trên 11 landing (10 trang ngành + trang chủ `translations/vi.json`) từ "Viết Hoa Từng Chữ" → viết hoa đầu câu (menu, nút, tiêu đề mục, nhãn, chân trang); giữ viết tắt/tên riêng (POS, QR, F&B, BitPaw Karaoke, Zalo, Hàn Quốc...), không đụng nội dung mẫu (tên khách, tin mẫu, màn terminal). Công cụ: scratchpad `sentence_case.py` (chạy thử → soát → ghi).
- Trang chủ còn "Sếp/Boss" và 🔥 trong `translations/*.json` (không thuộc lượt quét template trước) → đã thay; nút "Download Desktop App" trên trang tiếng Việt → "Tải ứng dụng" / "Download app".

**Pha 28d (25/10) — gói theo ngành, khoá tính năng theo gói, ảnh phần mềm thật trên landing, nền hiệu ứng cũ**
- Chủ dự án: "background với hiệu ứng chuyên nghiệp như cũ vẫn phù hợp hơn" → bỏ lớp làm gọn của Pha 28b trên landing (`bitpaw-pro-lite.css` chỉ còn quy tắc icon); nền sao, ánh sáng, khối 3D, chữ gradient trở lại.
- **Giá theo ngành** (`plans.py`, một nguồn cho bảng giá landing, `/checkout`, trang `/plan`, Super Admin, bot bán hàng): 9 ngành × 3 gói, USD + AUD (AUD làm tròn ...9), trả năm = 10 tháng. Essential không phí cài đặt.
- **Khoá tính năng theo gói** (`app._plan_gate`): trang/API thuộc gói cao hơn → chuyển tới `/plan` (API trả 403 `upgrade_required`); menu hiện nhãn khoá; trang khách (đặt lịch, menu QR, đặt bàn) KHÔNG bao giờ bị khoá. Tiệm cũ chưa có gói = Empire (giữ nguyên quyền). Đổi gói: Super Admin → "Đổi gói cho tiệm"; mã kích hoạt mang theo gói.
- Lỗi tìm thấy khi test giá: thẻ "trả năm" hiện tổng 12 × giá/tháng (làm tròn) trong khi checkout thu 10 tháng → lệch $6; và `round()` làm tròn kiểu ngân hàng ($132.5 → $132 nhưng $107.5 → $108). Đã thống nhất: tổng năm = 10 × giá tháng, giá/tháng hiển thị làm tròn LÊN.
- Lỗi thật trên Báo cáo tài chính: mục tự nhập trên POS (`product_id = None`) hiện thành "SPNone" trong "Top selling" và bị bỏ khỏi "Doanh thu theo nhóm"; doanh thu tính theo giá niêm yết thay vì tiền thực thu. Đã sửa (`api_report_data`): gộp theo tên tự nhập, dùng tiền dòng hàng.
- **Ảnh phần mềm thật trong khung 3D** (`templates/components/device_showcase.html`, ảnh `static/images/showcase/*.webp` tạo bằng `scripts/showcase_shots.mjs` từ tiệm demo Úc): landing chính thay 3 ảnh AI (radar GPS, smart POS, omnichannel — đã gỡ khỏi repo) bằng laptop + điện thoại nghiêng theo chuột, bấm để xem ảnh lớn, đứng yên khi bật giảm chuyển động. Thêm mục "Ảnh chụp phần mềm thật" vào landing Nails và Spa.
- Chữ landing chính viết lại cho khớp ảnh + tính năng thật: bỏ "Tăng 30% năng suất", "+45% khách quay lại", "Xử lý 10.000+ đơn/ngày", "Đã trừ phí sàn 12%", "Cam kết tiết kiệm 80%", "x3 tỷ lệ chuyển đổi", "1.2M lượt xem +450 leads", "Cỗ máy in tiền", "đang chạy chiến dịch Ads… thành công", nhắm "TP.HCM", Zalo ZNS; bỏ tính năng chưa có (vệt lộ trình GPS, phạt đi trễ, đồng bộ sàn TMĐT, đối soát vận đơn). Mục 3 đổi thành "Khách hàng & báo cáo"; "Support 24/7" → trợ lý AI 24/7 + đội hỗ trợ qua email/điện thoại.
- Kiểm thử: `scripts/plan_gate_test.py` 15/15 (không ghi DB — chặn ở lớp pymongo Collection) · `pricing_checkout_e2e` 25/25 (thêm đổi ngành, trả năm) · landing_pages 66/66 · landing_polish/blank/fab đạt · landing_download 47/47 · landing_sales_bot 18/18 · i18n 0 khoá thô · chống tấn công 35/35 · API công khai 17/17 · persona Nails 38/38 · roster 38/38.

**Cần anh/chị quyết định (Pha 28d)**
- 7 tiệm demo Việt Nam (F&B, Karaoke, Khách sạn, Bán lẻ, Sản xuất, Kỹ thuật, Văn phòng) vẫn VND/tên Việt → chưa chụp được ảnh thật cho landing các ngành đó. Script đổi sang USD (`scripts/showcase_demo_usd.py`, có sao lưu) đã viết nhưng CHƯA chạy vì ghi vào database thật.
- Tiệm demo Nails Úc có 85 đơn thanh toán thử ($20,230) do `nail_industry_master_audit` tạo qua nhiều lần chạy (dòng "Nail Art Design (QA Audit)") và 11 lịch hẹn test ngày 23/09 ("Debug SSE Guest2", "Flaky2"...). Chưa xoá — cần anh/chị đồng ý (xoá làm giảm số liệu demo).
- ✅ Đã làm ở Pha 28e (anh/chị trả lời "cần anh chị quyết định là làm luôn").

**Pha 28e (25/10) — chấm điểm + làm lại màn hình Spa, email hỗ trợ, demo USD, dọn dữ liệu test, ảnh thật 9 ngành**
- Cài 3 bộ kỹ năng thiết kế (Impeccable, Taste Skill, Emil Kowalski — anh/chị đồng ý) vào `~/.claude/skills`; chấm theo 10 tiêu chí Nielsen (0–4) + chuẩn màn hình ứng dụng của Taste Skill. Không chạy file thực thi kèm theo skill.
- **POS Spa (`templates/spa.html`) làm lại**: 13/40 (kém) → 29/40 (tốt). Thêm liệu trình 16/40 → 28/40. Lỗi thật tìm thấy: bắt buộc gõ tên + email khách cho MỌI bill (kể cả tiền mặt); giá bị `parseInt` cắt số lẻ ($89.95 → $89); bộ lọc nhóm cứng 5 nhóm tiếng Việt nên không khớp nhóm thật của tiệm (chọn "Facial Care" ra trống); nút xoá dịch vụ là link GET nằm trên từng ảnh ở màn bán hàng; đầu trang ghi "BitPaw" thay tên tiệm; hộp thanh toán giả (form nhập số thẻ không xử lý, PayPal/Apple Pay/crypto với địa chỉ ví bịa, MoMo/VNPAY không chuyển hướng) mà vẫn ghi bill "đã thu"; giỏ hàng ẩn sau nút nổi; nền ảnh mờ + tia quét. Giờ: catalog trái (chạm để thêm, nhóm lấy từ dữ liệu thật, tìm + phím "/" + Enter), phiếu thu luôn hiện bên phải (điện thoại: thanh dưới mở tấm trượt), gán kỹ thuật viên từng dòng, tip 0/10/15/20%, SĐT khách tra khách quen + gói liệu trình, thu tại quầy (tiền mặt / thẻ trên máy của tiệm / chuyển khoản), màn "đã ghi nhận" + in hoá đơn; "Sửa danh sách" mới hiện nút xoá (POST + CSRF, chỉ chủ tiệm).
- Máy chủ: tip của bill chia cho kỹ thuật viên theo phần doanh thu (hoàn tiền thu hồi cả tip); khách mới lưu đúng tên thu ngân nhập (trước "Khách 1234", tiệm Mỹ/Úc nay "Client 1234" khi không nhập tên); tin cảm ơn/điểm thưởng gửi khách tiệm Mỹ/Úc viết tiếng Anh (trước tiếng Việt); `/delete_spa` chỉ nhận POST.
- **Thêm liệu trình (`add_spa.html`)**: danh mục chọn gì máy chủ cũng ghi cứng "Spa & Beauty"; giá chỉ nhận số nguyên + ký hiệu ₫ cho tiệm Úc; icon đè chữ trong ô nhập. Đã làm lại cùng hệ giao diện POS, danh mục gợi ý từ dữ liệu tiệm, giá số lẻ, lỗi hiện trên form.
- Hoá đơn in (`print_receipt.js`) cho tiệm Mỹ/Úc: "$135.00" + tiếng Anh (trước "135đ", "TỔNG CỘNG", "Tiền mặt") — áp cho Spa, khách sạn, karaoke, bán lẻ.
- Email hỗ trợ: bitpawsoftware@gmail.com → **support@bitpawsoftware.com** ở 28 file (11 landing, trang pháp lý, khung chat, bot tư vấn, schema SEO, trang thanh toán thành công — trang này trước ghi nhầm support@bitpaw.com).
- **Demo → USD**: chạy `scripts/showcase_demo_usd.py --apply` (sao lưu trước) cho 7 tiệm: giá theo mức thực tế ở Mỹ, tên món/phòng/chức vụ tiếng Anh, SĐT dải 555-01xx, toạ độ Garden Grove CA; nhóm hàng "Đồ Ăn/Đồ Uống…" → "Food/Drinks…".
- **Dọn dữ liệu test** (sao lưu trước): Nails 85 + 76 bill test + 76 bill hoàn tiền test, 11 lịch hẹn test; Spa 11 bill + 11 khách "Khách 0493…"; Bán lẻ 44 bill; Khách sạn 15 bill + 11 phụ phí minibar; Kỹ thuật/Văn phòng 21 dòng chấm công; Xưởng 2 công thức + 4 sản lượng; 1 khuyến mãi test. Công cụ dùng lại: `scripts/cleanup_demo_test_data.py` (mặc định chạy thử). `spa_industry_master_audit` + `nail_industry_master_audit` giờ tự dọn bill của chính nó.
- Lỗi thật khác lộ ra khi đổi demo sang USD: phòng khách sạn "162.5₫/night", POS bán lẻ "0₫", menu QR khách gọi món "16,25₫" — sửa theo tiền tệ của tiệm; trang "Đặt phòng" khách sạn + karaoke chỉ có tiếng Việt → song ngữ; đầu trang POS nhà hàng / karaoke / bán lẻ ghi "BitPaw" → tên tiệm; ô nhập Xưởng/Kỹ thuật gợi ý tiếng Việt → song ngữ; ô chọn nhân viên xin nghỉ (Văn phòng) chưa dịch.
- Ảnh phần mềm thật (khung 3D) thêm cho landing Nhà hàng, Karaoke, Khách sạn, Bán lẻ, Kỹ thuật, Văn phòng, Nhân sự (Nails, Spa đã có). Sản xuất chưa thêm: dữ liệu demo xưởng sau khi dọn còn quá ít.
- **Lỗi nghiêm trọng lộ ra khi demo nhà hàng thành tiệm Mỹ**: POS nhà hàng ở Mỹ (`tenant_country == 'US'`) chỉ hiện nút "Pay with Square" — KHÔNG có cách ghi nhận tiền mặt / thẻ máy riêng / chia đôi bill (ô chọn vẫn hiện nhưng vô dụng). Giờ nút thu thường luôn có, tiệm Mỹ có thêm nút Square Terminal; nhãn phương thức thanh toán đã dịch; tổng ban đầu theo tiền tệ tiệm.
- Bài test cập nhật theo demo USD: hoàn tiền bán lẻ theo 25% bill (trước cố định 1000 kiểu VND), kiểm tên bàn chấp nhận "Table N".
- Kiểm thử: `spa_pos_e2e` (mới) 21/21 · `spa_therapist_pos_e2e` 9/9 · `service_packages_e2e` 15/15 · `spa_industry_master_audit` 6/6 · audit 7 ngành USD: F&B 8/8, Karaoke 4/4, Khách sạn 5/5, Bán lẻ 6/6, Kỹ thuật 3/3, Văn phòng 4/4, Xưởng 3/3 · persona 9 ngành 147/147 · landing 66/66 · tải app 47/47 · bot tư vấn 18/18 · giá 25/25 · khoá gói 15/15 · chống tấn công 35/35 · API công khai 17/17 · CSP 219 lượt 0 vi phạm, 0 lỗi JS. Tổng dữ liệu test đã dọn: 1.103 bản ghi (3 lượt, đều sao lưu).
