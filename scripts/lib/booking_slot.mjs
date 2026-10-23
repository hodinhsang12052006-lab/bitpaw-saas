// Trang đặt lịch công khai (booking.html) giờ dùng ô NGÀY + nút GIỜ TRỐNG thật (booking_rules.py: giờ mở cửa, thời lượng,
// số thợ có ca, lịch đã kín) thay cho ô datetime-local gõ tự do. Các script e2e cũ gõ thẳng #cus_datetime (giờ là ô ẩn)
// -> dùng chung hàm này.
//
// pickSlot(page, 'YYYY-MM-DD', { random, prefer: 'HH:MM', days: 7, sameDayOnly }) -> 'YYYY-MM-DDTHH:MM' hoặc null.
// Chọn dịch vụ (và thợ nếu muốn) TRƯỚC khi gọi — giờ trống tính theo dịch vụ/thợ đang chọn.
const pad = (n) => String(n).padStart(2, '0');
export const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export async function pickSlot(page, dateStr, opts = {}) {
  const days = opts.sameDayOnly ? 1 : (opts.days ?? 7);
  for (let k = 0; k < days; k++) {
    const d = new Date(dateStr + 'T00:00:00');
    d.setDate(d.getDate() + k);
    const ds = isoDate(d);
    await page.fill('#cus_date', ds);
    await page.dispatchEvent('#cus_date', 'change');
    await page.waitForFunction(() => {
      const c = document.getElementById('slotChips');
      return c && !c.querySelector('.fa-spin') && (c.querySelector('.slot-chip') || (document.getElementById('slotHint').textContent || '').length > 0);
    }, null, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(150);
    const times = await page.$$eval('#slotChips .slot-chip', (els) => els.map((e) => e.dataset.t)).catch(() => []);
    if (!times.length) continue;
    const t = opts.prefer && times.includes(opts.prefer) ? opts.prefer
      : opts.random ? times[Math.floor(Math.random() * times.length)] : times[0];
    await page.click(`#slotChips .slot-chip[data-t="${t}"]`);
    return `${ds}T${t}`;
  }
  return null;
}
