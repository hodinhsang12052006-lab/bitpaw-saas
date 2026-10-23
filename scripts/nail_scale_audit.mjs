/**
 * scripts/nail_scale_audit.mjs — đo độ ổn định của tiệm Nails LỚN (tiệm thử tạo bằng scripts/nail_scale_seed.py).
 *   SCALE_EMAIL=... SCALE_PASSWORD=... node scripts/nail_scale_audit.mjs     (server local 127.0.0.1:5001)
 * Mỗi màn hình: thời gian tải tới khi đứng yên, từng API trang gọi (thời gian + dung lượng — đánh dấu khi gần trần 4,5 MB
 * mỗi phản hồi của Vercel), lỗi JS. Thao tác: bán bill, tính lương tháng, AI Copilot. Đồng thời: N điện thoại thợ mở app +
 * vài thu ngân bán bill cùng lúc. Kết quả: audit-results/nail_scale_audit.json
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = process.env.SCALE_EMAIL;
const PASSWORD = process.env.SCALE_PASSWORD || 'QaNailScale2026!';
const VERCEL_LIMIT = 4.5 * 1024 * 1024;
const OUT = path.resolve('audit-results/screenshots/nail_scale_audit');
fs.mkdirSync(OUT, { recursive: true });
const report = { ranAt: new Date().toISOString(), pages: [], actions: [], concurrency: [] };
const kb = (n) => `${(n / 1024).toFixed(0)} KB`;

async function login(page) {
  await page.goto(BASE + '/login');
  await page.fill('#loginEmail', EMAIL);
  await page.fill('#loginPassword', PASSWORD);
  await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
  if (page.url().includes('/login')) throw new Error('login failed');
}

function trackApis(page) {
  const apis = [];
  page.on('requestfinished', async (req) => {
    const u = new URL(req.url());
    if (!u.pathname.startsWith('/api/') || u.pathname.startsWith('/api/stream')) return;
    try {
      const t = req.timing();
      const resp = await req.response();
      const body = resp ? await resp.body().catch(() => Buffer.alloc(0)) : Buffer.alloc(0);
      apis.push({ path: u.pathname + (u.search.length > 60 ? u.search.slice(0, 60) + '…' : u.search), status: resp && resp.status(),
        ms: Math.round(t.responseEnd >= 0 ? t.responseEnd : -1), bytes: body.length });
    } catch (e) { /* trang đã đóng */ }
  });
  return apis;
}

async function measurePage(ctx, name, url, waitFn) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const apis = trackApis(page);
  const t0 = Date.now();
  const resp = await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch((e) => ({ status: () => 'ERR ' + e.message.slice(0, 60) }));
  const tDom = Date.now() - t0;
  let tReady = null;
  try {
    if (waitFn) await page.waitForFunction(waitFn, null, { timeout: 90000, polling: 100 });
    else await page.waitForLoadState('networkidle', { timeout: 90000 });
    tReady = Date.now() - t0;
  } catch (e) { tReady = null; }
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) }).catch(() => {});
  const big = apis.filter((a) => a.bytes > VERCEL_LIMIT * 0.5);
  const rec = { name, url, status: typeof resp?.status === 'function' ? resp.status() : null, domMs: tDom, readyMs: tReady,
    apis: apis.sort((a, b) => b.bytes - a.bytes).slice(0, 6), errors: errors.slice(0, 3),
    flags: [...(tReady === null ? ['KHÔNG tải xong trong 90s'] : tReady > 5000 ? [`chậm ${(tReady / 1000).toFixed(1)}s`] : []),
      ...big.map((a) => `${a.path} ${kb(a.bytes)} (${Math.round((a.bytes / VERCEL_LIMIT) * 100)}% trần Vercel)`),
      ...(errors.length ? ['lỗi JS'] : [])] };
  report.pages.push(rec);
  console.log(`${rec.flags.length ? '⚠️ ' : '✅'} ${name.padEnd(22)} sẵn sàng ${tReady === null ? '—' : (tReady / 1000).toFixed(2) + 's'} · API nặng nhất: ${rec.apis[0] ? `${rec.apis[0].path} ${kb(rec.apis[0].bytes)} ${rec.apis[0].ms}ms` : '—'} ${rec.flags.join(' | ')}`);
  return page;
}

async function timeApi(page, name, fn) {
  const t0 = Date.now();
  const r = await page.evaluate(fn).catch((e) => ({ error: e.message }));
  const ms = Date.now() - t0;
  report.actions.push({ name, ms, result: r });
  console.log(`${r && r.ok ? '✅' : '⚠️ '} ${name.padEnd(40)} ${ms} ms ${r && r.note ? '· ' + r.note : ''}${r && r.error ? ' ' + r.error : ''}`);
  return r;
}

const browser = await chromium.launch({ channel: 'chrome' });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const boot = await ctx.newPage();
await login(boot);
const BID = await boot.evaluate(async () => (await (await fetch('/api/hr/employees')).json()).data[0].business_id);
const TECHS = await boot.evaluate(async () => (await (await fetch('/api/hr/employees')).json()).data.map((e) => e.ma_nv));
console.log(`Tiệm thử ${BID} · ${TECHS.length} thợ\n--- Màn hình ---`);

await measurePage(ctx, 'pos_sell', '/sell', () => document.querySelectorAll('#serviceGrid .service-card').length > 0);
await measurePage(ctx, 'chamcong_nail', '/chamcong/nail');
await measurePage(ctx, 'bangluong', '/bangluong', () => typeof globalPayrollData !== 'undefined' && globalPayrollData.length >= 50);
await measurePage(ctx, 'calendar_today', '/calendar');
await measurePage(ctx, 'staff', '/staff');
await measurePage(ctx, 'customers', '/customers');
await measurePage(ctx, 'dashboard', '/dashboard');
await measurePage(ctx, 'report_consolidated', '/report_consolidated');
await measurePage(ctx, 'payment_history', '/payment_history');
await measurePage(ctx, 'ai_bot', '/ai_bot');
await measurePage(ctx, 'leave_requests', '/leave_requests');
await measurePage(ctx, 'booking_public', `/booking/nail/qr/${BID}`, () => document.querySelectorAll('#cus_staff option').length > 1);

console.log('--- Thao tác ---');
const pos = await ctx.newPage();
await pos.goto(BASE + '/sell', { waitUntil: 'networkidle' });
await timeApi(pos, 'Bán 1 bill (2 dịch vụ, 2 thợ, tip thẻ)', async () => {
  // Mỗi dịch vụ gán 1 thợ (giống POS thật: item.ma_nv) rồi kiểm tra CẢ 2 thợ nhận đúng dòng hoa hồng của bill này
  const svc = SERVICES.filter((s) => s.price > 0).slice(0, 2);
  const techs = ['QS001', 'QS002'];
  const today = new Date().toLocaleDateString('en-GB');
  const r = await fetch('/api/nail_pos/checkout', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: svc.map((s, i) => ({ product_id: s.id, quantity: 1, ma_nv: techs[i] })), payment_method: 'card', card_tip: 10, cc_fee_percent: 3,
      currency: 'AUD', client_local_date: today }) });
  const j = await r.json();
  const paid = [];
  for (const ma of techs) {
    const rows = ((await (await fetch(`/api/hr/chamcong?ma_nv=${ma}&ngay_cham=${encodeURIComponent(today)}`)).json()).data || [])
      .filter((x) => String(x.ghi_chu || '').includes(`Order #${j.order_id}`));
    if (rows.length === 1 && Number(rows[0].tien_tua) > 0) paid.push(`${ma} $${Number(rows[0].tien_tua).toFixed(2)} + tip $${Number(rows[0].tien_tips || 0).toFixed(2)}`);
  }
  return { ok: r.ok && j.success && paid.length === 2, note: `order #${j.order_id} · hoa hồng: ${paid.join(' · ') || 'KHÔNG THỢ NÀO NHẬN'}`, order_id: j.order_id };
});
await timeApi(pos, 'Lịch sử thanh toán POS (/api/nail_pos/orders)', async () => {
  const r = await fetch('/api/nail_pos/orders'); const t = await r.text();
  return { ok: r.ok, note: `${(t.length / 1024).toFixed(0)} KB, ${(JSON.parse(t).data || []).length} bill` };
});
await timeApi(pos, 'Bảng lương: tổng tháng 60 thợ (/api/hr/payroll_summary)', async () => {
  const d = new Date();
  const r = await fetch(`/api/hr/payroll_summary?month=${d.getMonth() + 1}&year=${d.getFullYear()}`); const t = await r.text();
  return { ok: r.ok, note: `${(t.length / 1024).toFixed(0)} KB, ${Object.keys(JSON.parse(t).data || {}).length} thợ (trước: tải toàn bộ chấm công 5,2 MB)` };
});
await timeApi(pos, 'Xuất phiếu lương 1 thợ / tháng (/api/hr/chamcong?month=)', async () => {
  const d = new Date();
  const r = await fetch(`/api/hr/chamcong?ma_nv=QS001&nganh_nghe=Nails&month=${d.getMonth() + 1}&year=${d.getFullYear()}`); const t = await r.text();
  return { ok: r.ok, note: `${(t.length / 1024).toFixed(0)} KB, ${(JSON.parse(t).data || []).length} dòng` };
});
await timeApi(pos, 'Tổng tháng 1 thợ (month_summary)', async () => {
  const d = new Date();
  const ma = (await (await fetch('/api/hr/employees')).json()).data[0].ma_nv;
  const r = await fetch(`/api/hr/chamcong/month_summary?ma_nv=${ma}&nganh_nghe=Nails&month=${d.getMonth() + 1}&year=${d.getFullYear()}`);
  return { ok: r.ok, note: `HTTP ${r.status}` };
});
await timeApi(pos, 'Khách hàng CRM 1 trang + thống kê (/api/customers?page=)', async () => {
  const r = await fetch('/api/customers?page=1&page_size=20'); const t = await r.text(); const j = JSON.parse(t);
  return { ok: r.ok, note: `${(t.length / 1024).toFixed(0)} KB, tổng ${j.total} khách (trước: tải hết 459 KB)` };
});
await timeApi(pos, 'POS tìm khách theo SĐT (/api/customers?q=)', async () => {
  const r = await fetch('/api/customers?page_size=20&q=049900012'); const t = await r.text();
  return { ok: r.ok, note: `${(t.length / 1024).toFixed(0)} KB, ${(JSON.parse(t).data || []).length} kết quả` };
});
await timeApi(pos, 'AI Copilot: tư vấn doanh thu (số liệu 10.800 bill)', async () => {
  const r = await fetch('/api/ai/copilot', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'insight', topic: 'staffing', lang: 'en' }) });
  const j = await r.json();
  return { ok: r.ok && j.success, note: (j.text || j.message || '').replace(/\s+/g, ' ').slice(0, 140) };
});

console.log('--- Đồng thời ---');
async function concurrent(label, n, fn) {
  const t0 = Date.now();
  const res = await Promise.all(Array.from({ length: n }, (_, i) => pos.evaluate(fn, i).catch((e) => ({ ok: false, ms: -1, error: e.message }))));
  const ms = res.map((r) => r.ms).filter((x) => x >= 0).sort((a, b) => a - b);
  const fail = res.filter((r) => !r.ok).length;
  const row = { label, n, totalMs: Date.now() - t0, p50: ms[Math.floor(ms.length / 2)], max: ms[ms.length - 1], fail };
  report.concurrency.push(row);
  console.log(`${fail ? '⚠️ ' : '✅'} ${label.padEnd(46)} n=${n} trung vị ${row.p50}ms · chậm nhất ${row.max}ms · lỗi ${fail}`);
}
await concurrent('60 thợ mở "My earnings" cùng lúc', 60, async (i) => {
  const t0 = performance.now();
  const ma = `QS${String(i + 1).padStart(3, '0')}`;
  const d = new Date();
  const r = await fetch(`/api/hr/chamcong?ma_nv=${ma}&month=${d.getMonth() + 1}&year=${d.getFullYear()}`);
  await r.json();
  return { ok: r.ok, ms: Math.round(performance.now() - t0) };
});
await concurrent('60 thợ chấm công vào ca cùng lúc (8:59 sáng)', 60, async (i) => {
  // Chỉ ghi dòng chấm công (không tải ảnh lên — .env local trỏ kho ảnh THẬT); tiệm thử bị xoá sạch sau audit
  const t0 = performance.now();
  const ma = `QS${String(i + 1).padStart(3, '0')}`;
  const r = await fetch('/api/hr/chamcong', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ma_nv: ma, ngay_cham: new Date().toLocaleDateString('en-GB'), gio_den: '08:59', trang_thai: 'Có mặt', nganh_nghe: 'Nails', ghi_chu: '[SCALE CHECKIN]' }) });
  const j = await r.json();
  return { ok: r.ok && j.success, ms: Math.round(performance.now() - t0) };
});
await concurrent('5 thu ngân bán bill cùng lúc', 5, async (i) => {
  const t0 = performance.now();
  const s = SERVICES.filter((x) => x.price > 0)[i % 5];
  const r = await fetch('/api/nail_pos/checkout', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items: [{ product_id: s.id, quantity: 1 }], payment_method: 'cash', currency: 'AUD', client_local_date: new Date().toLocaleDateString('en-GB') }) });
  const j = await r.json();
  return { ok: r.ok && j.success, ms: Math.round(performance.now() - t0) };
});
await concurrent('20 lượt mở Lịch hẹn + Khách hàng cùng lúc', 20, async (i) => {
  const t0 = performance.now();
  const r = await fetch(i % 2 ? '/calendar' : '/api/customers?page=1&page_size=20');
  await r.text();
  return { ok: r.ok, ms: Math.round(performance.now() - t0) };
});

fs.writeFileSync('audit-results/nail_scale_audit.json', JSON.stringify(report, null, 2));
await browser.close();
