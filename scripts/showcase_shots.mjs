// showcase_shots.mjs — chụp ẢNH PHẦN MỀM THẬT cho khung laptop/điện thoại 3D trên landing (components/device_showcase.html).
// Dùng tiệm demo Úc (AUD) để ảnh hiện $ đúng thị trường Mỹ/Úc. Chỉ thao tác phía trình duyệt (thêm dịch vụ vào
// phiếu tạm, chọn ngày xem giờ trống) — KHÔNG bấm thanh toán/lưu, không ghi database.
//   BASE=http://127.0.0.1:5001 node scripts/showcase_shots.mjs   (CHỈ local)
//   -> PNG gốc ở audit-results/showcase_raw (không commit), WebP nén ở static/images/showcase/ (Pillow: PC 1600px, điện thoại 600px).
import { chromium, devices } from 'playwright';
import fs from 'fs';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = process.env.OUT || 'audit-results/showcase_raw';
const NAILS = ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'];
const SPA = ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'];
const NAILS_BID = '000b2c16-ab4e-42bd-944a-29c925cad09b';
const SPA_BID = '3cd48d09-8028-486d-82da-038db3ac2892';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ channel: 'chrome' });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
// ẩn bong bóng chat nổi (che nội dung trong ảnh tĩnh) + toast tạm
const HIDE = '#bitpawCskhFloating,#chatWidget,.toast,#toast,[id*="toast" i]{display:none!important}';

async function session(acct, dev) {
  const ctx = await b.newContext({ ...(dev === 'pc' ? { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 } : { ...iphone, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 }),
    timezoneId: 'Australia/Sydney', locale: 'en-AU' });
  const p = await ctx.newPage();
  if (acct) {
    await p.goto(BASE + '/login'); await p.fill('#loginEmail', acct[0]); await p.fill('#loginPassword', acct[1]);
    await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
  }
  return { ctx, p };
}
async function shot(p, path, name) {
  await p.goto(BASE + path + (path.includes('?') ? '&' : '?') + 'lang=en', { waitUntil: 'networkidle', timeout: 30000 });
  await p.addStyleTag({ content: HIDE }); await p.waitForTimeout(900);
  return name;
}
const save = async (p, name) => { await p.addStyleTag({ content: HIDE }); await p.waitForTimeout(400); await p.screenshot({ path: `${OUT}/${name}.png` }); console.log('saved', name); };

// 1) Nails — PC: POS có phiếu đang mở (3 dịch vụ + thợ), hồ sơ nhân viên, CRM khách hàng
{
  const { ctx, p } = await session(NAILS, 'pc');
  await shot(p, '/sell');
  const cards = p.locator('.service-card[data-service-id]');
  for (const i of [0, 3, 6]) { if (await cards.count() > i) { await cards.nth(i).click(); await p.waitForTimeout(250); } }
  const sel = p.locator('#cartItems select');
  const n = await sel.count();
  for (let i = 0; i < n; i++) { const opts = await sel.nth(i).locator('option').count(); if (opts > 1) await sel.nth(i).selectOption({ index: 1 + (i % (opts - 1)) }); }
  await p.waitForTimeout(2600);   // đợi toast "đã thêm" tắt
  await save(p, 'nails_pos_pc');
  await shot(p, '/nhanvien'); await save(p, 'nails_staff_pc');
  await shot(p, '/customers'); await save(p, 'nails_crm_pc');
  await shot(p, '/report'); await save(p, 'nails_report_pc');
  await ctx.close();
}
// 2) Nails — iPhone: báo cáo, danh sách thợ + tính lương, CRM
{
  const { ctx, p } = await session(NAILS, 'mob');
  await shot(p, '/report'); await save(p, 'nails_report_mob');
  await shot(p, '/chamcong/nail'); await save(p, 'nails_staff_mob');
  await shot(p, '/customers'); await save(p, 'nails_crm_mob');
  await ctx.close();
}
// 3) Trang đặt lịch công khai (khách của tiệm) — chọn dịch vụ + ngày mai để hiện giờ trống thật
{
  const { ctx, p } = await session(null, 'mob');
  await shot(p, `/booking/qr/${NAILS_BID}`);
  await p.waitForFunction(() => document.querySelectorAll('#cus_service option').length > 1, null, { timeout: 15000 }).catch(() => {});
  await p.selectOption('#cus_service', { index: 1 }).catch(() => {});
  // ngày làm việc gần nhất còn giờ trống
  for (let d = 1; d <= 6; d++) {
    const day = new Date(Date.now() + d * 864e5).toLocaleDateString('en-CA', { timeZone: 'Australia/Sydney' });
    await p.fill('#cus_date', day); await p.dispatchEvent('#cus_date', 'change'); await p.waitForTimeout(1500);
    if (await p.locator('#slotChips .slot-chip').count() > 3) break;
  }
  await p.evaluate(() => { const el = document.getElementById('cus_service'); window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 70); });
  await save(p, 'nails_booking_mob');
  await ctx.close();
}
// 3b) Trang đặt lịch của spa demo
{
  const { ctx, p } = await session(null, 'mob');
  await shot(p, `/booking/qr/${SPA_BID}`);
  await p.waitForFunction(() => document.querySelectorAll('#cus_service option').length > 1, null, { timeout: 15000 }).catch(() => {});
  await p.selectOption('#cus_service', { index: 1 }).catch(() => {});
  for (let d = 1; d <= 6; d++) {
    const day = new Date(Date.now() + d * 864e5).toLocaleDateString('en-CA', { timeZone: 'Australia/Sydney' });
    await p.fill('#cus_date', day); await p.dispatchEvent('#cus_date', 'change'); await p.waitForTimeout(1500);
    if (await p.locator('#slotChips .slot-chip').count() > 3) break;
  }
  await p.evaluate(() => { const el = document.getElementById('cus_service'); window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 70); });
  await save(p, 'spa_booking_mob');
  await ctx.close();
}
// 4) Spa — PC + iPhone: màn hình bán dịch vụ có ảnh
{
  const { ctx, p } = await session(SPA, 'pc');
  await shot(p, '/spa'); await save(p, 'spa_pos_pc');
  await ctx.close();
  const m = await session(SPA, 'mob');
  await shot(m.p, '/spa'); await save(m.p, 'spa_pos_mob');
  await m.ctx.close();
}
await b.close();
// nén WebP cho landing
execFileSync('python', ['-c', `
import os
from PIL import Image
src, dst = r'${OUT}', 'static/images/showcase'
os.makedirs(dst, exist_ok=True)
for f in sorted(os.listdir(src)):
    if not f.endswith('.png'): continue
    im = Image.open(os.path.join(src, f)).convert('RGB')
    w = 1600 if f.endswith('_pc.png') else 600
    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    im.save(os.path.join(dst, f[:-4] + '.webp'), 'WEBP', quality=80, method=6)
    print(f[:-4] + '.webp', im.size)
`], { stdio: 'inherit' });
