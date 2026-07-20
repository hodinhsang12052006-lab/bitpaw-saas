
# BitPaw — Rollout Mobile UI + SEO Entity cho 8 landing ngách

> ✅ Đã **triển khai thật và verify xong** trên `landing_fnb.html` và `landing_spa.html` (BƯỚC 3). 6 trang còn lại (`hotel`, `karaoke`, `office`, `retail`, `hr`, `production`, `technical`) dùng BƯỚC 1 + BƯỚC 2 dưới đây để tự nhân bản — cấu trúc HTML của cả 8 trang giống hệt nhau (cùng xuất phát từ 1 template gốc), nên checklist áp dụng y hệt cho tất cả.

---

## BƯỚC 1 — 12 key dịch (Bottom Nav + FAB Sheet)

Đã đếm lại chính xác: **12 key** (không phải 13) — đây là toàn bộ chữ mới xuất hiện trong `mobile_bottom_nav.html` + `smart_fab.html`. Định dạng JSON chuẩn bên dưới dán thẳng được vào object `vi: {...}` / `en: {...}` hiện có của từng trang (JSON là tập con hợp lệ của cú pháp object JS).

```json
{
  "vi": {
    "bnav_home": "Trang chủ",
    "bnav_solutions": "Giải pháp",
    "bnav_pricing": "Bảng giá",
    "bnav_more": "Thêm",
    "solsheet_title": "Khám Phá Giải Pháp",
    "fab_label": "Liên hệ",
    "fabsheet_title": "Liên Hệ Ngay",
    "fabsheet_chat": "Chat với Trợ Lý AI",
    "fabsheet_zalo": "Tư Vấn Zalo",
    "fabsheet_messenger": "Messenger",
    "fabsheet_call": "Gọi Hotline",
    "fabsheet_email": "Gửi Email"
  },
  "en": {
    "bnav_home": "Home",
    "bnav_solutions": "Solutions",
    "bnav_pricing": "Pricing",
    "bnav_more": "More",
    "solsheet_title": "Explore Solutions",
    "fab_label": "Contact",
    "fabsheet_title": "Get in Touch",
    "fabsheet_chat": "Chat with AI Assistant",
    "fabsheet_zalo": "Zalo Consulting",
    "fabsheet_messenger": "Messenger",
    "fabsheet_call": "Call Hotline",
    "fabsheet_email": "Send Email"
  }
}
```

**Cách dán:** mỗi trang ngách có 1 khối `const translations = { vi: {...}, en: {...} };` riêng (KHÔNG dùng chung `translations/en.json`/`vi.json` như trang `/landing` chính). Mở khối `"vi"` ở trên, copy 12 dòng `"key": "value"`, dán vào **ngay trước dấu `}` đóng** của object `vi: {...}` hiện có trong trang. Làm y hệt cho `en`.

---

## BƯỚC 2 — Checklist tích hợp (copy-paste cho MỖI trang ngách)

Đã verify: cả 8 trang còn lại dùng chung 1 template gốc → id/class/vị trí dưới đây khớp 100% cho tất cả (đã kiểm tra trực tiếp từng file, section bảng giá luôn là `id="calculator"`).

**1. Gắn `id="hamburgerBtn"`** vào đúng nút hamburger đang có sẵn (tìm `onclick="toggleMobileMenu()"` kèm icon `fa-bars` trong `<header>`):
```html
<button id="hamburgerBtn" onclick="toggleMobileMenu()" class="lg:hidden ...">
```

**2. Chèn 2 include NGAY SAU `</div>` đóng `#mobile-menu`, TRƯỚC `<main>`:**
```jinja
{% set pricing_anchor = 'calculator' %}
{% include 'components/mobile_bottom_nav.html' %}
{% include 'components/smart_fab.html' %}
```

**3. Chèn script — NGAY SAU dòng `{% include 'components/cskh_global.html' %}`:**
```jinja
<script src="{{ url_for('static', filename='js/bp_mobile_ui.js') }}"></script>
```

**Đồng thời trong `<head>`, thêm link CSS (bất kỳ đâu sau `tailwind.output.css`):**
```jinja
<link href="{{ url_for('static', filename='css/bp_mobile_ui.css') }}" rel="stylesheet">
```

*(Tuỳ chọn — nếu muốn Hero full-screen kiểu app + CTA pulse: thêm class `bp-hero` vào `<section>` hero, `bp-hero-copy`/`bp-hero-actions` vào khối text/nút, `bp-cta-pulse` vào nút CTA chính. Không bắt buộc, chỉ ảnh hưởng UI không ảnh hưởng chức năng.)*

---

## BƯỚC 3 — SEO Entity set-block: F&B và Spa (đã áp dụng thật vào file)

### `landing_fnb.html`
```jinja
{% set title = "BitPaw F&B | Quản Lý Nhà Hàng, Cafe, Order QR Tại Bàn & Bếp KDS" %}
{% set description = "BitPaw F&B - Giải pháp tự động hóa toàn diện cho Nhà hàng, Quán ăn & Cafe: Gọi món qua QR code động tại bàn, Màn hình hiển thị bếp KDS realtime, Smart POS thu ngân siêu tốc, đối soát định lượng kho tự động." %}
{% set keywords = "phần mềm quản lý nhà hàng, order QR tại bàn, màn hình bếp KDS, phần mềm quán cafe, smart POS nhà hàng, quản lý kho định lượng F&B" %}
{% set canonical_path = "solutions/fnb" %}
{% set og_locale = "vi_VN" %}
{% set schema_name = "BitPaw F&B" %}
{% set schema_subcategory = "Restaurant POS & Kitchen Display System (KDS) Software" %}
{% set faq_items = [
    {'q': 'BitPaw F&B có hỗ trợ khách gọi món qua QR code tại bàn không?', 'a': 'Có. Khách quét mã QR riêng của từng bàn để xem menu và gọi món trực tiếp, đơn hàng đổ thẳng về màn hình bếp (KDS) và POS thu ngân theo thời gian thực.'},
    {'q': 'Màn hình bếp KDS của BitPaw hoạt động như thế nào?', 'a': 'Mọi đơn từ order nội bộ (nhân viên) lẫn order QR của khách đều tự động tạo vé bếp và hiển thị realtime trên màn hình KDS, giúp bếp không bỏ sót món và lên món đúng thứ tự.'},
    {'q': 'Phần mềm có tự động trừ kho theo định lượng nguyên liệu không?', 'a': 'Có. Mỗi món ăn được định lượng nguyên liệu (công thức), khi bán ra hệ thống tự trừ kho theo đúng định lượng, giúp phát hiện thất thoát nguyên liệu chính xác hơn cách trừ kho theo thành phẩm.'}
] %}
{% include 'components/seo_meta.html' %}
```

### `landing_spa.html`
```jinja
{% set title = "BitPaw Spa | Quản Lý Spa, Lập Lịch Booking & Tính Hoa Hồng KTV" %}
{% set description = "BitPaw Spa management software: smart online booking system, multi-session treatment package tracking, Smart POS billing, automated staff shift scheduling, and transparent technician commission calculation for spas, beauty clinics, and wellness businesses." %}
{% set keywords = "spa management software, salon booking system, wellness business management, appointment scheduling software, spa POS system, technician commission software, beauty clinic management, spa scheduling app" %}
{% set canonical_path = "solutions/spa" %}
{% set og_locale = "vi_VN" %}
{% set schema_name = "BitPaw Spa" %}
{% set schema_subcategory = "Spa & Beauty Salon Booking and Management Software" %}
{% set faq_items = [
    {'q': 'BitPaw Spa có quản lý được lịch hẹn khách online không?', 'a': 'Có. Khách có thể tự đặt lịch hẹn online, hệ thống tự động xếp phòng/giường trống và phân ca kỹ thuật viên (KTV) theo thời gian thực, tránh trùng lịch.'},
    {'q': 'Phần mềm có theo dõi được liệu trình nhiều buổi (multi-session) của khách không?', 'a': 'Có. BitPaw Spa lưu hồ sơ liệu trình từng khách, tự động trừ số buổi còn lại mỗi lần khách sử dụng dịch vụ, giúp lễ tân và KTV luôn nắm rõ khách còn bao nhiêu buổi.'},
    {'q': 'BitPaw Spa có tự động tính hoa hồng cho kỹ thuật viên không?', 'a': 'Có. Hệ thống tự tính hoa hồng KTV theo từng dịch vụ đã thực hiện, minh bạch rõ ràng và đồng bộ trực tiếp với Smart POS thanh toán, không cần tính tay.'}
] %}
{% include 'components/seo_meta.html' %}
```

**Mẫu nhân bản cho 6 trang còn lại:** chỉ cần đổi `title`/`description`/`keywords` (lấy từ đúng nội dung hiện có ở đầu mỗi file — KHÔNG bịa mới), `canonical_path` = `"solutions/<industry_code>"` đúng route thật, `schema_name` = tên thương hiệu ngành đó, `schema_subcategory` = mô tả ngắn loại phần mềm, và viết lại 3 `faq_items` đúng nghiệp vụ ngành (không copy nguyên câu hỏi F&B/Spa sang ngành khác — sai entity, phản tác dụng SEO).

---

## Đã verify thật (không chỉ viết code)
- `landing_fnb.html` + `landing_spa.html`: Jinja parse OK, Flask render thật OK (test qua `app.test_request_context`), cả 3 JSON-LD parse hợp lệ, mobile hiện đúng Bottom Nav/FAB/ẩn hamburger/ẩn widget cũ, desktop giữ nguyên 100%, đổi ngôn ngữ EN áp dụng đúng 12 key mới trong `translations` riêng của từng trang.
