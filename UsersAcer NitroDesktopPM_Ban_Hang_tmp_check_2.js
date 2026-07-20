
        // Tự động nhận diện khách nước ngoài / Việt Kiều theo ngôn ngữ trình duyệt. Chỉ áp dụng
        // cho khách MỚI, CHƯA từng tự chọn ngôn ngữ (không có cookie/localStorage bitpaw_lang) —
        // tránh ghi đè lựa chọn thủ công của khách đã từng đổi cờ VN/EN trước đó.
        (function () {
            const hasSavedPref = !!localStorage.getItem('bitpaw_lang') || document.cookie.includes('bitpaw_lang=');
            if (hasSavedPref) {
                console.log('[BitPaw i18n] Khách đã có lựa chọn ngôn ngữ trước đó — giữ nguyên, không tự động đổi.');
                return;
            }
            const browserLang = (navigator.language || navigator.userLanguage || '').toLowerCase();
            const isVietnamese = browserLang.indexOf('vi') === 0;
            if (!isVietnamese) {
                console.log(`[BitPaw i18n] Phát hiện khách quốc tế / Việt Kiều (navigator.language = "${browserLang}") — tự động chuyển giao diện sang Tiếng Anh.`);
                if (typeof changeLanguage === 'function') {
                    changeLanguage('en');
                } else {
                    console.warn('[BitPaw i18n] Không tìm thấy hàm chuyển ngôn ngữ — kiểm tra lại thứ tự nạp script.');
                }
            } else {
                console.log(`[BitPaw i18n] Phát hiện khách Việt Nam (navigator.language = "${browserLang}") — giữ nguyên Tiếng Việt.`);
            }
        })();
    