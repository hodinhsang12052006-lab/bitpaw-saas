// iPhone 13: POS bán lẻ — thêm hàng, mở giỏ, Checkout, chọn tiền mặt, xác nhận: báo cú chạm nào bị che và bởi phần tử nào.
// CHỈ server local. Đơn tạo ra được hoàn tiền/không — đây là tiệm demo, đơn thử in rõ mã để dọn.
import { chromium, devices } from 'playwright';

const BASE = 'http://127.0.0.1:5001';
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ ...iphone, deviceScaleFactor: 2 });
const p = await ctx.newPage();
await p.goto(BASE + '/login');
await p.fill('#loginEmail', 'demo.retail.596348@bitpawdemo.com'); await p.fill('#loginPassword', 'DemoBitPaw2026!');
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
await p.goto(BASE + '/retail_pos', { waitUntil: 'networkidle' });
async function step(label, sel) {
  const info = await p.evaluate((s) => {
    const el = document.querySelector(s); if (!el) return { missing: true };
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], vh: innerHeight, display: cs.display, vis: cs.visibility,
             onTop: !top ? 'ngoài màn hình' : (top === el || el.contains(top)) ? 'chính nó' : `${top.tagName}#${top.id}.${String(top.className).slice(0, 60)}` };
  }, sel);
  console.log(label, sel, JSON.stringify(info));
  const ok = await p.click(sel, { timeout: 4000 }).then(() => true).catch((e) => { console.log('   ✗ không chạm được:', e.message.split('\n').find((l) => /intercepts|outside|not visible|not stable/.test(l)) || e.message.split('\n')[0]); return false; });
  await p.waitForTimeout(400);
  return ok;
}
await p.locator('.product-card').nth(0).click(); await p.waitForTimeout(200);
await step('1', '#cartIcon');
await step('2', '#openCheckoutBtn');
await step('3', '.pm-option[data-method="cash"]');
await step('4', '#confirmCheckoutBtn');
await p.screenshot({ path: 'audit-results/screenshots/mobile_retail_checkout_probe.png' });
await b.close();
