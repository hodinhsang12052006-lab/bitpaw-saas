// iPhone 13: POS bán lẻ — thêm 3 sản phẩm, mở rồi ĐÓNG giỏ, chạm ô quét mã vạch, gõ mã + Enter -> phải gọi tra mã.
import { chromium, devices } from 'playwright';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ ...iphone, deviceScaleFactor: 2 });
const p = await ctx.newPage();
p.on('request', (r) => { if (r.url().includes('lookup_barcode')) console.log('-> gọi tra mã:', r.url().replace(BASE, '')); });
p.on('pageerror', (e) => console.log('JS lỗi:', String(e).slice(0, 150)));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', 'demo.retail.596348@bitpawdemo.com'); await p.fill('#loginPassword', 'DemoBitPaw2026!');
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
await p.goto(BASE + '/retail_pos', { waitUntil: 'networkidle' });
const where = async (label) => console.log(label, JSON.stringify(await p.evaluate(() => {
  const el = document.getElementById('barcodeInput'); const r = el.getBoundingClientRect();
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  const cart = document.querySelector('#cartItemsList')?.closest('[id]');
  return { input: [Math.round(r.top), Math.round(r.height)], onTop: top === el ? 'ô quét' : `${top?.tagName}#${top?.id}.${String(top?.className).slice(0, 50)}`,
           active: document.activeElement?.id };
})));
const cards = p.locator('.product-card');
for (let i = 0; i < 3; i++) { await cards.nth(i).click(); await p.waitForTimeout(150); }
await p.click('#cartIcon'); await p.waitForTimeout(300);
await where('giỏ đang mở:');
console.log('nút đóng giỏ hiện?', await p.locator('#closeCartBtn').isVisible());
await p.click('#closeCartBtn'); await p.waitForTimeout(400);
await where('sau khi đóng giỏ:');
await p.click('#barcodeInput', { timeout: 5000 }).catch((e) => console.log('click ô quét lỗi:', e.message.split('\n').slice(0, 3).join(' | ')));
await p.type('#barcodeInput', '8934588123451');
await p.press('#barcodeInput', 'Enter');
await p.waitForTimeout(2500);
await where('sau khi quét:');
await p.screenshot({ path: 'audit-results/screenshots/mobile_retail_scan.png' });
await b.close();
