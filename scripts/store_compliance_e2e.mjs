// Kiểm tra yêu cầu của CH Play + App Store trên server local (xem audit-results/STORE_SUBMISSION_PLAN.md):
// trang chính sách công khai, ẩn bán gói phần mềm trong app (UA BitPawMobileApp), xoá tài khoản end-to-end.
// Cần tài khoản test tạo bằng scripts/store_test_account.py (xem docstring file đó).
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:5001';
const ACC = JSON.parse(fs.readFileSync(process.env.ACC, 'utf8'));
const OUT = process.env.OUT;
const res = [];
const rec = (name, ok, detail = '') => { res.push({ name, ok }); console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`); };
const b = await chromium.launch({ channel: 'chrome', headless: true });
const nav = async (page, url) => {
  for (let i = 0; i < 3; i++) {
    try { return await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 25000 }); } catch (e) { if (i === 2) throw e; }
  }
};

// 1) Trang chính sách công khai
const web = await b.newPage({ viewport: { width: 390, height: 844 } });
const legal = [
  ['/privacy-policy?lang=en', 'BitPaw Technology LLC'], ['/privacy-policy?lang=vi', 'bitpawsoftware@gmail.com'],
  ['/terms?lang=en', 'BitPaw Technology LLC'], ['/terms?lang=vi', 'BitPaw Technology LLC'],
  ['/payment-policy?lang=en', 'bitpawsoftware@gmail.com'],
];
for (const [url, must] of legal) {
  const r = await nav(web, url);
  const txt = await web.innerText('body');
  const noPlaceholder = !/\[(Tax ID|Contact email|Last updated date|Ngày cập nhật|Email liên hệ)/.test(txt);
  rec(`Trang ${url} HTTP 200, có "${must}", không còn [placeholder]`, r.status() === 200 && txt.includes(must) && noPlaceholder, `HTTP ${r.status()}`);
}
await web.screenshot({ path: `${OUT}/store_privacy_policy_mobile.png` });
await nav(web, '/account/delete?lang=en');
rec('/account/delete khi CHƯA đăng nhập: có nút Sign in + email yêu cầu xoá',
  (await web.locator('a.btn').count()) === 1 && (await web.innerText('body')).includes('bitpawsoftware@gmail.com'));
await web.screenshot({ path: `${OUT}/store_account_delete_logged_out.png` });
await web.close();

// 2) Chính sách store trong app (User-Agent của app)
for (const plat of ['iOS', 'Android']) {
  const ctx = await b.newContext({ userAgent: `BitPawMobileApp/1.0.0 (${plat}; WebView)`, viewport: { width: 390, height: 844 } });
  const p = await ctx.newPage();
  await nav(p, '/checkout');
  const t = await p.innerText('body');
  rec(`[${plat} app] /checkout bị ẩn (không bán gói trong app, không link mua ngoài)`,
    /available in the app|không khả dụng trong ứng dụng/i.test(t) && !/\$\d|VNĐ|price/i.test(t));
  if (plat === 'iOS') await p.screenshot({ path: `${OUT}/store_ios_checkout_blocked.png` });
  const api = await ctx.request.post(BASE + '/api/checkout/signup', { data: {} });
  rec(`[${plat} app] POST /api/checkout/signup -> 403`, api.status() === 403, `HTTP ${api.status()}`);
  for (const u of ['/solutions/nail', '/landing']) {
    await nav(p, u);
    rec(`[${plat} app] ${u} -> chuyển về /login`, new URL(p.url()).pathname === '/login', p.url().replace(BASE, ''));
  }
  await ctx.close();
}

// 3) Trình duyệt web thường: KHÔNG bị ảnh hưởng
const normal = await b.newPage();
await nav(normal, '/checkout');
rec('[Web thường] /checkout vẫn hiển thị trang đăng ký gói bình thường',
  !/available in the app/i.test(await normal.innerText('body')) && new URL(normal.url()).pathname === '/checkout');
await nav(normal, '/solutions/nail');
rec('[Web thường] /solutions/nail vẫn là landing (không bị đẩy về login)', new URL(normal.url()).pathname === '/solutions/nail');
await normal.close();

// 4) Xoá tài khoản end-to-end (trong app Android)
const ctx = await b.newContext({ userAgent: 'BitPawMobileApp/1.0.0 (Android; WebView)', viewport: { width: 390, height: 844 } });
const page = await ctx.newPage();
const login = async () => {
  await nav(page, '/login');
  await page.fill('#loginEmail', ACC.email);
  await page.fill('#loginPassword', ACC.password);
  await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
  await page.waitForTimeout(1500);
};
await login();
rec('Đăng nhập tài khoản test thành công', !page.url().includes('/login'), page.url().replace(BASE, ''));
await nav(page, '/calendar');
rec('Sidebar có link "Delete account"', (await page.locator('#app-sidebar a[href="/account/delete"]').count()) === 1);
await nav(page, '/account/delete?lang=en');
await page.fill('#delPassword', 'wrong-password-123');
await page.check('#delConfirm');
await page.click('#delBtn');
await page.waitForFunction(() => document.getElementById('delMsg').textContent.trim().length > 0, null, { timeout: 10000 });
rec('Sai mật khẩu -> báo lỗi, KHÔNG xoá', (await page.textContent('#delMsg')).includes('incorrect'), await page.textContent('#delMsg'));
await page.screenshot({ path: `${OUT}/store_account_delete_wrong_pw.png` });
await page.fill('#delPassword', ACC.password);
await page.click('#delBtn');
await page.waitForFunction(() => document.getElementById('delMsg').classList.contains('ok'), null, { timeout: 10000 }).catch(() => {});
rec('Mật khẩu đúng -> "Your account has been deleted"', (await page.textContent('#delMsg')).includes('deleted'), await page.textContent('#delMsg'));
await page.screenshot({ path: `${OUT}/store_account_delete_done.png` });
await page.waitForURL(/\/login/, { timeout: 8000 }).catch(() => {});
await login();
rec('Sau khi xoá: đăng nhập lại bị từ chối', page.url().includes('/login'), page.url().replace(BASE, ''));
await b.close();
const fail = res.filter((r) => !r.ok).length;
console.log(`\nTổng kết: ${res.length - fail} PASS · ${fail} FAIL`);
