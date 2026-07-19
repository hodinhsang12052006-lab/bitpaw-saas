// Shared CSKH click-tracking + contact-form handler.
// Trước đây 21 file template tự duplicate y hệt đoạn JS này, mỗi bản gọi thẳng
// Supabase (`supabaseClient.from('cskh_clicks')/('cskh_requests')`) — giờ gom về
// 1 file tĩnh duy nhất, gọi qua 2 API Flask dùng chung sẵn có (/api/cskh/click,
// /api/cskh/request, đã migrate sang MongoDB). Chỉ cần include file này, không cần
// định nghĩa lại logic ở từng trang — miễn trang đó có sẵn link/nút [data-channel]
// và/hoặc form #supportForm (#supportName/#supportPhone/#supportMessage) là hoạt động.
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-channel]').forEach(link => {
        link.addEventListener('click', () => {
            const channel = link.getAttribute('data-channel');
            fetch('/api/cskh/click', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel, user_id: window.BITPAW_USER_ID || null })
            }).catch(e => console.warn('CSKH click tracking failed', e));
        });
    });

    const supportForm = document.getElementById('supportForm');
    if (!supportForm) return;

    supportForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nameEl = document.getElementById('supportName');
        const phoneEl = document.getElementById('supportPhone');
        const messageEl = document.getElementById('supportMessage');
        const name = nameEl ? nameEl.value.trim() : '';
        const phone = phoneEl ? phoneEl.value.trim() : '';
        const message = messageEl ? messageEl.value.trim() : '';
        const notify = (msg, isError) => {
            if (window.showToast) window.showToast(msg, isError);
            else alert(msg);
        };
        if (!name || !phone || !message) {
            notify('Vui lòng điền đầy đủ thông tin!', true);
            return;
        }
        try {
            const res = await fetch('/api/cskh/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, phone, message })
            });
            const json = await res.json();
            if (!json.success) throw new Error(json.error || json.message || 'Gửi yêu cầu thất bại.');
            notify('Đã gửi yêu cầu hỗ trợ thành công!', false);
            supportForm.reset();
        } catch (err) {
            notify('Lỗi: ' + err.message, true);
        }
    });
});
