/**
 * scripts/payment_ui_screens.mjs — chụp mọi màn hình thanh toán (desktop 1440 + điện thoại 390, giả lập điện thoại thật)
 * để soi bằng mắt: cấu hình cổng, lịch sử giao dịch, chờ thanh toán / thành công (tiệm AUD), trang mua gói BitPaw,
 * các trang thông báo lỗi. Đồng thời đo: lỗi JS, tràn ngang, khung nhìn bị nới, tiền AUD hiện đúng "$".
 *   node scripts/payment_ui_screens.mjs     (server local)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = path.resolve('audit-results/screenshots/payment_ui_screens');
fs.mkdirSync(OUT, { recursive: true });
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok, note }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };

const PAGES = [
  ['payment_gateway', '/payment_gateway', true],
  ['payment_history', '/payment_history', true],
  ['payment_pending_aud', '/payment_pending?txn_id=NAIL-TEST1&amount=107.5&method=cash&industry=nail&currency=AUD', true],
  ['payment_success_aud', '/payment_success?txn_id=NAIL-TEST1&method=cash&amount=107.5&currency=AUD&industry=nail', true],
  ['checkout_pos_plan', '/checkout?plan=pos', false],
  ['checkout_agency_plan', '/checkout?plan=agency', false],
  ['msg_table_order', '/table_order', false],
  ['msg_qr_menu_bad', '/qr_menu/khong-ton-tai', false],
];

const browser = await chromium.launch({ channel: 'chrome' });
for (const [label, vp] of [['desktop', { viewport: { width: 1440, height: 900 } }],
  ['mobile', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }]]) {
  const ctx = await browser.newContext(vp);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '/login');
  await page.fill('#loginEmail', 'demo.nails.au.006758@bitpawdemo.com');
  await page.fill('#loginPassword', 'DemoNails2026!');
  await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
  for (const [name, url, authed] of PAGES) {
    const p = authed ? page : await (await browser.newContext(vp)).newPage();
    const before = errors.length;
    p.on('pageerror', (e) => errors.push(e.message));
    const resp = await p.goto(BASE + url, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => null);
    await p.waitForTimeout(1200);
    const m = await p.evaluate(() => ({ inner: innerWidth, sw: document.documentElement.scrollWidth, text: document.body.innerText }));
    await p.screenshot({ path: path.join(OUT, `${label}_${name}.png`), fullPage: true }).catch(() => {});
    const notes = [];
    if (m.inner !== vp.viewport.width) notes.push(`khung nhìn ${m.inner}px`);
    if (m.sw > m.inner + 1) notes.push(`tràn ngang ${m.sw}px`);
    if (errors.length > before) notes.push('lỗi JS: ' + errors.slice(before).join(' | ').slice(0, 120));
    if (name.endsWith('_aud') && /107[.,]5?0?đ|₫/.test(m.text)) notes.push('AUD hiện thành đ/₫');
    if (name === 'payment_success_aud' && /BitPaw Nails & Beauty Salon|BitPaw Restaurant/.test(m.text)) notes.push('tên tiệm viết cứng');
    if (name === 'payment_success_aud' && /confirmation email/i.test(m.text)) notes.push('hứa gửi email');
    rec(`${label} ${name}`, notes.length === 0, `HTTP ${resp && resp.status()} ${notes.join(' · ')}`);
  }
  await ctx.close();
}
await browser.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
