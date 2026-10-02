/**
 * scripts/nail_visual_audit.mjs
 *
 * Quét GIAO DIỆN toàn bộ trang ngành Nails ở 2 kích thước (máy tính 1440px + điện thoại 390px):
 * chụp ảnh toàn trang để soi bằng mắt, đồng thời tự dò các lỗi bể giao diện đo được bằng máy:
 *   - tràn ngang (trang rộng hơn màn hình → xuất hiện thanh cuộn ngang) + phần tử gây tràn
 *   - ảnh vỡ (img tải lỗi)
 *   - lỗi JS (console error / pageerror) và request lỗi (HTTP >= 400, cùng domain)
 *   - chữ bị cắt cụt ngoài ý muốn (nút/nhãn có nội dung tràn khung, không phải truncate cố ý)
 * Cộng thêm 1 lượt mở từng modal chính của POS /sell để soi modal trên cả 2 kích thước.
 *
 * Chạy:  node scripts/nail_visual_audit.mjs
 * Ảnh:   audit-results/screenshots/nail_visual_audit/
 * Báo cáo: audit-results/nail_visual_audit_report.json
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { gotoSell, safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';
const BUSINESS_ID = process.env.NAIL_DEMO_BUSINESS_ID || '000b2c16-ab4e-42bd-944a-29c925cad09b';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_visual_audit');
const REPORT_JSON = path.resolve('audit-results/nail_visual_audit_report.json');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const OWNER_PAGES = [
  ['chamcong', '/chamcong/nail'],
  ['pos_sell', '/sell'],
  ['calendar', '/calendar'],
  ['customers', '/customers'],
  ['ai_bot', '/ai_bot'],
  ['ai_studio', '/ai_studio'],
  ['staff', '/staff'],
  ['bangluong', '/bangluong'],
  ['leave_requests', '/leave_requests'],
  ['expense_requests', '/expense_requests'],
  ['report_consolidated', '/report_consolidated'],
  ['brand_settings', '/brand_settings'],
  ['app_nhanvien', '/app_nhanvien'],
];
const PUBLIC_PAGES = [
  ['landing_nail', '/solutions/nail'],
  ['booking_public', `/booking/nail/qr/${BUSINESS_ID}`],
  ['login', '/login'],
];
const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  mobile: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};

// Chạy TRONG trang: đo các lỗi bể giao diện có thể phát hiện bằng máy.
function measureLayout() {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  // Overflow của <body> lan lên viewport khi <html> để visible: nếu viewport bị hidden/clip theo
  // trục X thì người dùng KHÔNG cuộn ngang được -> scrollWidth lớn chỉ là phần trang trí bị cắt.
  const htmlOx = getComputedStyle(document.documentElement).overflowX;
  const viewportOx = htmlOx !== 'visible' ? htmlOx : getComputedStyle(document.body).overflowX;
  const userScrollableX = viewportOx !== 'hidden' && viewportOx !== 'clip';
  const out = { scrollWidth: doc.scrollWidth, viewportWidth: vw, viewportOverflowX: viewportOx, overflowX: userScrollableX && doc.scrollWidth > vw + 1, offenders: [], brokenImages: [], clipped: [] };

  const describe = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    if (cls) s += '.' + cls;
    return s;
  };
  const visible = (el) => {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || +st.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // Phần tử nằm trong 1 vùng cuộn ngang cố ý (overflow-x auto/scroll) thì không tính là lỗi.
  const insideHScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true;
    }
    return false;
  };

  if (out.overflowX) {
    for (const el of document.body.querySelectorAll('*')) {
      if (!visible(el) || insideHScroller(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width < doc.scrollWidth) {
        out.offenders.push({ el: describe(el), right: Math.round(r.right), width: Math.round(r.width), text: (el.innerText || '').trim().slice(0, 40) });
      }
    }
    // Chỉ giữ phần tử "lá" nhất (bỏ cha nếu con đã nằm trong danh sách) cho dễ đọc
    out.offenders = out.offenders.slice(-12);
  }

  for (const img of document.images) {
    if (img.complete && img.naturalWidth === 0 && visible(img) && img.src) out.brokenImages.push(img.src.slice(0, 120));
  }

  for (const el of document.body.querySelectorAll('button, a, label, th, td, h1, h2, h3, h4, .badge, span')) {
    if (!visible(el) || el.children.length > 2) continue;
    const st = getComputedStyle(el);
    if (st.textOverflow === 'ellipsis' || (el.className || '').toString().includes('truncate') || (el.className || '').toString().includes('line-clamp')) continue;
    const txt = (el.innerText || '').trim();
    if (!txt) continue;
    const clippedX = el.scrollWidth > el.clientWidth + 2 && (st.overflow === 'hidden' || st.overflowX === 'hidden');
    const clippedY = el.scrollHeight > el.clientHeight + 4 && (st.overflow === 'hidden' || st.overflowY === 'hidden') && el.clientHeight > 0;
    if (clippedX || clippedY) out.clipped.push({ el: describe(el), text: txt.slice(0, 40), sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight });
  }
  out.clipped = out.clipped.slice(0, 15);
  return out;
}

async function auditPage(context, vpName, key, url, results) {
  const page = await context.newPage();
  const consoleErrors = [];
  const badResponses = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => consoleErrors.push('PAGEERROR ' + String(e).slice(0, 200)));
  page.on('response', (r) => {
    const u = r.url();
    if (r.status() >= 400 && u.startsWith(BASE)) badResponses.push(`${r.status()} ${u.replace(BASE, '')}`);
  });
  page.on('dialog', (d) => d.dismiss().catch(() => {}));

  let finalUrl = '';
  try {
    // Dev server Werkzeug trên Windows thỉnh thoảng reset kết nối (môi trường, không phải lỗi app) -> thử lại
    for (let attempt = 1; ; attempt++) {
      try { await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 20000 }); break; }
      catch (err) {
        if (attempt >= 3) throw err;
        consoleErrors.length = 0; badResponses.length = 0; // lỗi của lần tải bị reset không thuộc về trang
        console.log(`   ↻ thử tải lại ${url} (lần ${attempt + 1})`);
      }
    }
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(800);
    finalUrl = page.url().replace(BASE, '');
    const layout = await page.evaluate(measureLayout);
    const file = `${vpName}_${key}.png`;
    await safeScreenshot(page, { path: path.join(SCREEN_DIR, file), fullPage: true });
    const issues = [];
    if (layout.overflowX) issues.push(`TRÀN NGANG ${layout.scrollWidth}px > ${layout.viewportWidth}px`);
    if (layout.brokenImages.length) issues.push(`${layout.brokenImages.length} ảnh vỡ`);
    if (consoleErrors.length) issues.push(`${consoleErrors.length} lỗi JS`);
    if (badResponses.length) issues.push(`${badResponses.length} request lỗi`);
    if (layout.clipped.length) issues.push(`${layout.clipped.length} chữ bị cắt`);
    results.push({ viewport: vpName, key, url, finalUrl, screenshot: file, issues, layout, consoleErrors, badResponses });
    console.log(`${issues.length ? '⚠️ ' : '✅'} [${vpName}] ${key} ${url}${finalUrl !== url ? ' → ' + finalUrl : ''} ${issues.join(' | ')}`);
  } catch (e) {
    results.push({ viewport: vpName, key, url, finalUrl, issues: ['EXCEPTION ' + e.message.slice(0, 150)] });
    console.log(`❌ [${vpName}] ${key} ${url} EXCEPTION ${e.message.slice(0, 150)}`);
  }
  await page.close();
}

// Mở lần lượt các modal chính của POS /sell và chụp từng cái (viewport, không full page).
async function auditSellModals(context, vpName, results) {
  const page = await context.newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 200)));
  page.on('dialog', (d) => d.dismiss().catch(() => {}));
  await gotoSell(page, BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#serviceGrid .service-card', { timeout: 15000 });
  await page.waitForTimeout(600);
  // Có 1 dịch vụ trong giỏ để modal thanh toán mở được
  await page.locator('#serviceGrid .service-card').first().click();
  await page.waitForTimeout(300);

  const modals = [
    ['custom_item', 'window.openCustomItemModal && openCustomItemModal()', '#customItemModal'],
    ['discount', 'window.openDiscountModal && openDiscountModal()', '#discountModal'],
    ['booking_qr', 'window.openBookingQrModal && openBookingQrModal()', '#bookingQrModal'],
    ['order_history', 'window.openOrderHistoryModal && openOrderHistoryModal()', '#orderHistoryModal'],
    ['payment', "document.getElementById('checkoutBtn') && document.getElementById('checkoutBtn').click()", '#paymentModal'],
  ];
  for (const [key, js, sel] of modals) {
    try {
      await page.evaluate(js);
      await page.waitForSelector(`${sel}.active`, { timeout: 4000 });
      await page.waitForTimeout(500);
      const box = await page.evaluate((s) => {
        const m = document.querySelector(s);
        const inner = m && (m.querySelector('.modal-content, .modal-box, .modal-container, [class*="modal"]') || m.firstElementChild);
        const r = (inner || m).getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), vw: innerWidth, vh: innerHeight };
      }, sel);
      const file = `${vpName}_sell_modal_${key}.png`;
      await safeScreenshot(page, { path: path.join(SCREEN_DIR, file) });
      const issues = [];
      if (box.left < -1 || box.right > box.vw + 1) issues.push(`MODAL TRÀN NGANG (left ${box.left}, right ${box.right}, vw ${box.vw})`);
      results.push({ viewport: vpName, key: 'sell_modal_' + key, url: '/sell', screenshot: file, issues, box });
      console.log(`${issues.length ? '⚠️ ' : '✅'} [${vpName}] /sell modal ${key} ${issues.join(' | ')}`);
      // đóng modal: thử nút đóng chuẩn, rồi Escape, rồi gỡ class
      await page.evaluate((s) => document.querySelector(s).classList.remove('active'), sel);
      await page.waitForTimeout(250);
    } catch (e) {
      results.push({ viewport: vpName, key: 'sell_modal_' + key, url: '/sell', issues: ['KHÔNG MỞ ĐƯỢC: ' + e.message.slice(0, 120)] });
      console.log(`❌ [${vpName}] /sell modal ${key} không mở được: ${e.message.slice(0, 120)}`);
    }
  }
  if (errs.length) console.log(`   lỗi JS khi mở modal: ${errs.join(' | ')}`);
  await page.close();
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];

  // Đăng nhập 1 lần duy nhất (tránh rate limit 5 lần/15 phút), dùng lại session cho cả 2 kích thước
  const loginCtx = await browser.newContext(VIEWPORTS.desktop);
  const lp = await loginCtx.newPage();
  await lp.goto(BASE + '/login', { waitUntil: 'networkidle' });
  await lp.fill('#loginEmail', EMAIL);
  await lp.fill('#loginPassword', PASSWORD);
  await Promise.all([lp.waitForLoadState('networkidle'), lp.click('#btnLogin')]);
  if (lp.url().includes('/login')) throw new Error('Đăng nhập thất bại (rate limit?)');
  const storage = await loginCtx.storageState();
  await loginCtx.close();

  for (const [vpName, vpOpts] of Object.entries(VIEWPORTS)) {
    const ownerCtx = await browser.newContext({ ...vpOpts, storageState: storage });
    for (const [key, url] of OWNER_PAGES) await auditPage(ownerCtx, vpName, key, url, results);
    await auditSellModals(ownerCtx, vpName, results);
    await ownerCtx.close();

    const publicCtx = await browser.newContext(vpOpts);
    for (const [key, url] of PUBLIC_PAGES) await auditPage(publicCtx, vpName, key, url, results);
    await publicCtx.close();
  }

  await browser.close();
  fs.writeFileSync(REPORT_JSON, JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2));
  const withIssues = results.filter((r) => r.issues && r.issues.length);
  console.log(`\nTổng: ${results.length} màn hình · ${withIssues.length} có vấn đề cần xem · ảnh tại ${SCREEN_DIR}`);
}

main().catch((e) => { console.error('CRASHED:', e); process.exit(1); });
