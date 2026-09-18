/**
 * printReceipt(options) — mở 1 cửa sổ khổ giấy nhiệt (80mm) format sẵn hoá đơn rồi tự in.
 * Dùng chung cho mọi ngành KHÔNG có hoá đơn in (Retail/Spa/Nails/Karaoke/Hotel) — F&B đã có
 * hoá đơn riêng ở payment_success.html, không dùng file này.
 *
 * options:
 *   businessName: string
 *   subtitle: string (tuỳ chọn — "Bàn 3", "Phòng VIP 1", "KTV: Lan"...)
 *   items: [{name, qty, price, total}]
 *   subtotal, discount, tax, tip, total: number
 *   paymentMethod: string (hiển thị nguyên văn, đã dịch sẵn ở nơi gọi)
 *   currency: string (mặc định 'đ')
 *   footerNote: string (tuỳ chọn)
 */
function printReceipt(options) {
    const {
        businessName = 'BitPaw OS',
        subtitle = '',
        items = [],
        subtotal = 0,
        discount = 0,
        tax = 0,
        tip = 0,
        total = 0,
        paymentMethod = '',
        currency = 'đ',
        footerNote = 'Cảm ơn quý khách!',
    } = options || {};

    const fmt = (n) => Number(n || 0).toLocaleString('vi-VN') + currency;
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));

    const itemsHtml = items.map((it) => `
        <tr>
            <td style="text-align:left; padding:2px 0;">${esc(it.name)}${it.qty > 1 ? ' x' + it.qty : ''}</td>
            <td style="text-align:right; padding:2px 0; white-space:nowrap;">${fmt(it.total != null ? it.total : (it.price || 0) * (it.qty || 1))}</td>
        </tr>
    `).join('');

    const now = new Date();
    const dateStr = now.toLocaleString('vi-VN');

    const html = `
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Hoá đơn</title>
<style>
    * { box-sizing: border-box; }
    body { font-family: 'Courier New', monospace; width: 80mm; margin: 0 auto; padding: 10px; color: #000; font-size: 12px; }
    h1 { font-size: 15px; text-align: center; margin: 0 0 2px; }
    .sub { text-align: center; font-size: 11px; margin-bottom: 8px; }
    .meta { font-size: 10px; text-align: center; margin-bottom: 8px; color: #333; }
    hr { border: none; border-top: 1px dashed #000; margin: 6px 0; }
    table { width: 100%; border-collapse: collapse; }
    .row { display: flex; justify-content: space-between; padding: 2px 0; }
    .total-row { font-weight: bold; font-size: 14px; }
    .footer { text-align: center; margin-top: 10px; font-size: 11px; }
    @media print { body { padding: 0; } }
</style>
</head>
<body>
    <h1>${esc(businessName)}</h1>
    ${subtitle ? `<div class="sub">${esc(subtitle)}</div>` : ''}
    <div class="meta">${dateStr}</div>
    <hr>
    <table>${itemsHtml}</table>
    <hr>
    <div class="row"><span>Tạm tính</span><span>${fmt(subtotal)}</span></div>
    ${discount > 0 ? `<div class="row"><span>Giảm giá</span><span>-${fmt(discount)}</span></div>` : ''}
    ${tax > 0 ? `<div class="row"><span>Thuế</span><span>${fmt(tax)}</span></div>` : ''}
    ${tip > 0 ? `<div class="row"><span>Tip</span><span>${fmt(tip)}</span></div>` : ''}
    <hr>
    <div class="row total-row"><span>TỔNG CỘNG</span><span>${fmt(total)}</span></div>
    ${paymentMethod ? `<div class="row"><span>Thanh toán</span><span>${esc(paymentMethod)}</span></div>` : ''}
    <div class="footer">${esc(footerNote)}</div>
</body>
</html>`;

    const printWindow = window.open('', '_blank', 'width=380,height=600');
    if (!printWindow) {
        // Trình duyệt chặn popup — không phải lỗi, chỉ báo cho thu ngân biết để tự bật popup
        alert('Trình duyệt đang chặn cửa sổ in. Vui lòng cho phép popup để in hoá đơn.');
        return;
    }
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => {
        printWindow.print();
    }, 300);
}
