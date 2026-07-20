// =============================================================================
// BitPaw — MOBILE "APP-LIKE EXPERIENCE" MODULE (shared, DRY)
// Điều khiển: Bottom Tab Bar, Solutions Bottom Sheet, Smart FAB + Action Sheet.
// Dùng chung cho landing.html VÀ mọi landing ngách — nạp 1 lần bằng
// <script src="...bp_mobile_ui.js">, không copy/paste JS này vào từng trang.
//
// Tự chứa (self-contained), không phụ thuộc framework nào ngoài các hàm toàn
// cục đã có sẵn CỦA TỪNG TRANG CHỦ (mỗi trang tự định nghĩa lấy):
//   - toggleMobileMenu()  — bắt buộc phải tồn tại (mọi landing đều đã có sẵn).
//   - window.toggleChat() — do static/js/cskh_widget.js cung cấp (đã include
//     qua components/cskh_global.html), dùng để mở chatbox Mascot AI.
//
// Tham số hoá qua thuộc tính data-* trên HTML (không qua biến JS toàn cục),
// để bản thân file .js này không cần biết gì về Jinja/từng trang:
//   - #bpTabPricing data-target="<id của section bảng giá, KHÔNG có dấu #>"
//     (mặc định "bang-gia" nếu bỏ trống — xem components/mobile_bottom_nav.html)
// =============================================================================
(function () {
    let bpOpenSheetId = null; // sheet nào đang mở, để đóng đúng khi bấm ESC
    const SHEET_BACKDROP_MAP = { bpSolutionsSheet: 'bpSolutionsBackdrop', bpFabSheet: 'bpFabBackdrop' };

    window.bpOpenSheet = function (sheetId, backdropId) {
        const sheet = document.getElementById(sheetId);
        const backdrop = document.getElementById(backdropId);
        if (!sheet || !backdrop) return;
        sheet.classList.add('bp-open');
        backdrop.classList.add('bp-open');
        document.body.style.overflow = 'hidden';
        bpOpenSheetId = sheetId;
    };

    window.bpCloseSheet = function (sheetId, backdropId) {
        const sheet = document.getElementById(sheetId);
        const backdrop = document.getElementById(backdropId);
        if (!sheet || !backdrop) return;
        sheet.classList.remove('bp-open');
        backdrop.classList.remove('bp-open');
        document.body.style.overflow = '';
        bpOpenSheetId = null;
    };

    // Bấm ESC đóng bottom sheet đang mở (hỗ trợ bàn phím ngoài/tablet)
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && bpOpenSheetId) {
            window.bpCloseSheet(bpOpenSheetId, SHEET_BACKDROP_MAP[bpOpenSheetId]);
        }
    });

    // Tab "Home": cuộn mượt lên đầu trang + đóng mọi sheet đang mở
    window.bpGoHome = function () {
        window.bpCloseSheet('bpFabSheet', 'bpFabBackdrop');
        window.bpCloseSheet('bpSolutionsSheet', 'bpSolutionsBackdrop');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Tab "Pricing": cuộn mượt tới section bảng giá — id lấy từ data-target của
    // chính nút bấm (mỗi trang landing có thể đặt tên section khác nhau, vd
    // "bang-gia" ở landing.html, "calculator" ở landing_nail.html).
    window.bpGoPricing = function (btn) {
        window.bpCloseSheet('bpFabSheet', 'bpFabBackdrop');
        window.bpCloseSheet('bpSolutionsSheet', 'bpSolutionsBackdrop');
        const targetId = (btn && btn.dataset && btn.dataset.target) || 'bang-gia';
        const target = document.getElementById(targetId);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    // Action Sheet -> "Chat với Trợ Lý AI": đóng sheet rồi gọi lại đúng
    // window.toggleChat() đã có sẵn trong static/js/cskh_widget.js
    window.bpOpenMascotChat = function () {
        window.bpCloseSheet('bpFabSheet', 'bpFabBackdrop');
        setTimeout(function () {
            if (typeof window.toggleChat === 'function') window.toggleChat();
        }, 260); // chờ animation đóng sheet xong mới mở chatbox, tránh giật 2 lớp overlay chồng nhau
    };

    // Scrollspy nhẹ: tô sáng tab "Home" khi ở đầu trang, "Pricing" khi cuộn
    // tới đúng section của nó — chỉ có tác dụng trên mobile (bottom nav chỉ
    // hiển thị ở đó, nhưng listener vẫn gắn an toàn ở mọi kích thước màn hình).
    function bpInitScrollspy() {
        const tabHome = document.getElementById('bpTabHome');
        const tabPricing = document.getElementById('bpTabPricing');
        if (!tabHome || !tabPricing) return;
        const targetId = tabPricing.dataset.target || 'bang-gia';
        const pricingSection = document.getElementById(targetId);

        function update() {
            const nearTop = window.scrollY < 80;
            let inPricing = false;
            if (pricingSection) {
                const rect = pricingSection.getBoundingClientRect();
                inPricing = rect.top < window.innerHeight * 0.5 && rect.bottom > 80;
            }
            tabHome.classList.toggle('active', nearTop && !inPricing);
            tabPricing.classList.toggle('active', inPricing);
        }
        window.addEventListener('scroll', update, { passive: true });
        update();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bpInitScrollspy);
    } else {
        bpInitScrollspy();
    }
})();
