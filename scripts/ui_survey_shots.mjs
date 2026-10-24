// ui_survey_shots.mjs — chụp màn hình các trang chính (iPhone 13 + máy tính) để soát giao diện từng li từng tí.
//   OUT=<thư mục> node scripts/ui_survey_shots.mjs [nhãn]   (CHỈ local)
import { chromium, devices } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const OUT = process.env.OUT || 'audit-results/ui_survey';
const TAG = process.argv[2] || 'before';
fs.mkdirSync(OUT, { recursive: true });
const NAIL = ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'];
const SETS = [
  ['public', null, ['/login', '/', '/solutions/nail', '/checkout', '/booking/nail/qr/000b2c16-ab4e-42bd-944a-29c925cad09b']],
  ['customer', null, ['/reserve/39821fa8-e42a-4052-bc9d-eb061eaaae11', '/karaoke/reserve/0cc47d38-b306-46f3-9da1-cdf2d840d79b',
                       '/hotel/reserve/885e1075-9191-4b1e-91ee-d100e961257d', '/booking/qr/3cd48d09-8028-486d-82da-038db3ac2892', '/qr_menu',
                       '/qr_menu/not-a-real-table', '/portal', '/forgot-password-check']],
  ['nail', NAIL, ['/chamcong/nail', '/pos', '/calendar', '/customers', '/ai_bot', '/roster', '/report', '/nhanvien', '/bangluong', '/settings/booking', '/app_nhanvien', '/setup', '/dashboard']],
  ['spa', ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'], ['/spa', '/chamcong/spa']],
  ['fnb', ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'], ['/fnb_dashboard', '/pos']],
  ['hotel', ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'], ['/hotel_rooms']],
  ['karaoke', ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'], ['/karaoke']],
  ['technical', ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'], ['/chamcong/kythuat', '/map_dashboard']],
];
const only = (process.env.ONLY || '').split(',').filter(Boolean);
const b = await chromium.launch({ channel: 'chrome' });
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
for (const [label, acct, paths] of SETS) {
  if (only.length && !only.includes(label)) continue;
  for (const [dev, opts] of [['mob', iphone], ['pc', { viewport: { width: 1440, height: 900 } }]]) {
    const ctx = await b.newContext(opts); const p = await ctx.newPage();
    if (acct) {
      await p.goto(BASE + '/login'); await p.fill('#loginEmail', acct[0]); await p.fill('#loginPassword', acct[1]);
      await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
    }
    for (const path of paths) {
      try {
        await p.goto(BASE + path, { waitUntil: 'networkidle', timeout: 25000 });
        await p.waitForTimeout(1200);
        const name = `${TAG}_${label}_${dev}_${path.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)}.png`;
        await p.screenshot({ path: `${OUT}/${name}` });
      } catch (e) { console.log('fail', label, dev, path, e.message.slice(0, 80)); }
    }
    await ctx.close();
  }
}
await b.close();
console.log('done');
