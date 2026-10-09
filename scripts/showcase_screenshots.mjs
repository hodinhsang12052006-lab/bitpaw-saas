// Chụp bộ ảnh giới thiệu chức năng (slide) cho cả 9 ngành từ server LOCAL, tài khoản demo từng ngành.
// CHỈ XEM — không bấm xác nhận thanh toán / không chấm công / không lưu gì vào DB.
//   node scripts/showcase_screenshots.mjs <thư mục ảnh>
// Ảnh JPEG: desktop 1440x900, điện thoại 430x932 (@2x).
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';
import { gotoSell } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const OUT = path.resolve(process.argv[2] || 'audit-results/showcase');
fs.mkdirSync(OUT, { recursive: true });
const RESTART = `${process.env.HOME || process.env.USERPROFILE}/restart_flask.sh`;
const T = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'],
  fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!'],
};
const DESK = { viewport: { width: 1440, height: 900 } };
const PHONE = { viewport: { width: 430, height: 932 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const HIDE = '#cskh-widget-root,.cskh-launcher,#bpFab,.bp-fab,#bp-ai-sales-root,.ai-sales-launcher{display:none!important}';
const done = [];
const browser = await chromium.launch({ channel: 'chrome', headless: true });
let logins = 0;

async function shot(page, name, { full = false } = {}) {
  try {
    await page.addStyleTag({ content: HIDE }).catch(() => {});
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, `${name}.jpg`), type: 'jpeg', quality: 74, fullPage: full });
    done.push(name); console.log('📸', name);
  } catch (e) { console.log('⚠️ ', name, e.message.split('\n')[0]); }
}
async function go(page, p, wait = 900) {
  for (let i = 0; i < 3; i++) {
    try { await page.goto(BASE + p, { waitUntil: 'networkidle', timeout: 40000 }); await page.waitForTimeout(wait); return true; } catch (e) { /* máy dev reset kết nối -> thử lại */ }
  }
  return false;
}
async function login(ind, opts = DESK, lang = 'vi') {
  if (logins >= 4 && fs.existsSync(RESTART)) { execFileSync('bash', [RESTART], { stdio: 'ignore' }); logins = 0; }
  logins++;
  const ctx = await browser.newContext(opts);
  await ctx.addCookies([{ name: 'bitpaw_lang', value: lang, url: BASE }]);
  const page = await ctx.newPage();
  await page.addInitScript((l) => { try { localStorage.setItem('bitpaw_lang', l); } catch (e) {} }, lang);
  await go(page, '/login', 300);
  await page.fill('#loginEmail', T[ind][0]);
  await page.fill('#loginPassword', T[ind][1]);
  await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
  await page.waitForTimeout(1200);
  if (page.url().includes('/login')) throw new Error(`đăng nhập ${ind} thất bại`);
  return page;
}
const step = async (label, fn) => { try { await fn(); } catch (e) { console.log('⚠️ ', label, e.message.split('\n')[0]); } };

// ======================= NAILS (đầy đủ nhất) =======================
await step('nail desktop', async () => {
  const p = await login('nail', DESK, 'en');
  await go(p, '/chamcong/nail', 1500); await shot(p, 'nail_01_rotation_board');
  await gotoSell(p, BASE); await p.waitForTimeout(800); await shot(p, 'nail_02_pos_grid');
  const cards = p.locator('#serviceGrid .service-card');
  await cards.nth(0).click(); await cards.nth(3).click(); await cards.nth(6).click();
  await p.waitForTimeout(2600);
  await p.evaluate(() => window.switchLeftTab && window.switchLeftTab('ticket'));
  const sels = p.locator('#cartItems .cart-item select');
  for (let i = 0; i < Math.min(await sels.count(), 3); i++) {
    const opts = await sels.nth(i).locator('option').all();
    if (opts.length > 1 + (i % 2)) await sels.nth(i).selectOption(await opts[1 + (i % 2)].getAttribute('value'));
  }
  await p.fill('#cardTip', '8').catch(() => {});
  await p.waitForTimeout(400); await shot(p, 'nail_03_ticket_techs');
  await p.click('#checkoutBtn', { force: true }); await p.waitForTimeout(900);
  await p.click('.pay-method-btn[data-method="split"]').catch(() => {}); await p.waitForTimeout(600);
  await shot(p, 'nail_04_payment_split');
  await p.keyboard.press('Escape'); await gotoSell(p, BASE);
  await p.evaluate(() => openBookingQrModal()); await p.waitForTimeout(1500); await shot(p, 'nail_05_booking_qr_modal');
  await go(p, '/qr/poster/booking?lang=en', 800); await p.setViewportSize({ width: 900, height: 1270 }); await shot(p, 'nail_06_qr_poster');
  await p.setViewportSize(DESK.viewport);
  await go(p, '/calendar', 1200); await shot(p, 'nail_07_calendar');
  await go(p, '/customers', 1500); await shot(p, 'nail_08_crm');
  await go(p, '/bangluong', 2500); await shot(p, 'nail_09_payroll');
  await go(p, '/ai_bot', 1500); await shot(p, 'nail_10_ai_copilot');
  await go(p, '/report_consolidated', 2000); await shot(p, 'nail_11_reports');
  await go(p, '/leave_requests', 1000); await shot(p, 'nail_12_leave_requests');
  await go(p, '/staff', 1500); await shot(p, 'nail_13_staff');
  await p.context().close();
});
await step('nail phone', async () => {
  const p = await login('nail', PHONE, 'en');
  const bookingUrl = await (async () => { await gotoSell(p, BASE); return p.evaluate(() => BOOKING_QR_URL); })();
  await shot(p, 'nail_m1_pos_phone');
  // App nhân viên: vào thẳng màn chính bằng trạng thái lưu trên máy (không chấm công thật)
  const emp = await p.evaluate(async () => ((await (await fetch('/api/hr/employees')).json()).data || []).find((e) => (e.linh_vuc || '').includes('Nails')));
  await go(p, '/app_nhanvien', 600); await shot(p, 'nail_m2_staff_login');
  await p.evaluate((e) => {
    localStorage.setItem('bp_emp_name', e.ho_ten); localStorage.setItem('bp_emp_code', e.ma_nv);
    localStorage.setItem('bp_emp_linhvuc', e.linh_vuc || 'Nails'); localStorage.setItem('bp_emp_avatar', e.avatar_url || '');
    localStorage.setItem('bp_da_diem_danh', new Date().toDateString());
  }, emp);
  await go(p, '/app_nhanvien', 2000); await shot(p, 'nail_m3_staff_home');
  await p.evaluate(() => switchAppTab('apps')); await p.waitForTimeout(800); await shot(p, 'nail_m4_staff_requests');
  await p.evaluate(() => { localStorage.removeItem('bp_da_diem_danh'); }); await go(p, '/app_nhanvien', 1500); await shot(p, 'nail_m5_staff_checkin');
  await p.evaluate(() => ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar'].forEach((k) => localStorage.removeItem(k)));
  const c = await (await browser.newContext(PHONE)).newPage();
  await go(c, new URL(bookingUrl).pathname, 1500); await shot(c, 'nail_m6_customer_booking');
  await c.context().close(); await p.context().close();
});

// ======================= CÁC NGÀNH KHÁC =======================
const OTHERS = {
  fnb: [['/pos', 'fnb_01_floor_plan', 1800], ['/kitchen_display', 'fnb_02_kitchen_display', 1500], ['/reservations', 'fnb_03_reservations', 1200], ['/chamcong/fnb', 'fnb_04_attendance', 1500]],
  spa: [['/spa', 'spa_01_pos', 1800], ['/add_spa', 'spa_02_add_treatment', 1000], ['/calendar', 'spa_03_calendar', 1200], ['/chamcong/spa', 'spa_04_attendance', 1500]],
  retail: [['/retail_pos', 'retail_01_pos', 1800], ['/quanly_kho', 'retail_02_inventory', 1500], ['/inventory_alert', 'retail_03_restock', 1500], ['/report', 'retail_04_reports', 2000]],
  karaoke: [['/karaoke', 'karaoke_01_rooms', 1800], ['/karaoke/reservations', 'karaoke_02_reservations', 1200], ['/chamcong/karaoke', 'karaoke_03_attendance', 1500]],
  hotel: [['/hotel_rooms', 'hotel_01_rooms', 1800], ['/hotel/reservations', 'hotel_02_reservations', 1200], ['/chamcong/khachsan', 'hotel_03_attendance', 1500]],
  production: [['/production_output', 'production_01_output', 1800], ['/production/materials', 'production_02_materials', 1500], ['/chamcong/congnhan', 'production_03_attendance', 1500]],
  technical: [['/chamcong/kythuat', 'technical_01_dispatch', 1800], ['/map_dashboard', 'technical_02_map', 3000], ['/technical/parts', 'technical_03_parts', 1500]],
  office: [['/chamcong/vanphong', 'office_01_attendance', 1800], ['/bangluong', 'office_02_payroll', 2500], ['/leave_requests', 'office_03_leave', 1200]],
};
for (const [ind, pages] of Object.entries(OTHERS)) {
  await step(ind, async () => {
    const p = await login(ind, DESK, 'en');
    for (const [url, name, wait] of pages) { await go(p, url, wait); await shot(p, name); }
    if (ind === 'fnb') {
      await go(p, '/pos', 1500);
      const tid = await p.evaluate(async () => (await (await fetch('/api/pos/tables')).json()).data?.[0]?.id ?? null);
      await go(p, `/qr/poster/table/${tid}?lang=en`, 800); await p.setViewportSize({ width: 900, height: 1270 }); await shot(p, 'fnb_05_table_poster');
      await go(p, '/qr_menu', 500);
      const q = await (await browser.newContext(PHONE)).newPage(); await go(q, new URL(p.url()).pathname, 1500); await shot(q, 'fnb_m1_qr_menu'); await q.context().close();
    }
    if (ind === 'spa') {
      await go(p, '/qr/poster/booking?lang=en', 800); await p.setViewportSize({ width: 900, height: 1270 }); await shot(p, 'spa_05_qr_poster');
    }
    await p.context().close();
  });
}
// Trang công khai
await step('landing', async () => {
  const p = await (await browser.newContext(DESK)).newPage();
  await go(p, '/solutions/nail', 1500); await shot(p, 'landing_nail');
  await go(p, '/landing', 1500); await shot(p, 'landing_main');
  await p.context().close();
});
await browser.close();
fs.writeFileSync(path.join(OUT, 'index.json'), JSON.stringify(done, null, 2));
console.log(`\nXong: ${done.length} ảnh -> ${OUT}`);
