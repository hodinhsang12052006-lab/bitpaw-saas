/**
 * scripts/nail_customer_experience_latency.mjs
 *
 * Đóng vai KHÁCH + CHỦ TIỆM cùng lúc (2-3 trình duyệt riêng) và ĐO độ trễ thật của mọi kênh tin nhắn /
 * real-time ngành Nails — trả lời câu hỏi "khách nhắn có tới ngay không, tiệm trả lời khách có thấy ngay
 * không":
 *   C1  Khách SĐT Úc (04xx) chat với trợ lý đặt lịch -> hội thoại có vào hộp thư /ai_bot của tiệm không
 *   C2  Khách chat -> AI trả lời mất bao lâu; tin khách hiện ở /ai_bot sau bao lâu
 *   C3  Chủ tiệm trả lời trong /ai_bot -> khách (đang mở widget) có thấy không, sau bao lâu
 *   C4  8 lần khách nhắn rải đều 60s -> /ai_bot (đo cả khoảng SSE tự kết nối lại mỗi 25s)
 *   C5  8 lần tiệm nhắn -> trang /portal của khách
 *   C6  8 lần chat nội bộ /chat giữa 2 máy
 *   C7  Khách đặt lịch qua QR -> /calendar tự hiện; Check-in -> badge POS tự tăng
 *
 * Chạy:  node scripts/nail_customer_experience_latency.mjs     (server local 127.0.0.1:5001)
 * Kết quả: audit-results/nail_customer_experience_latency.json + ảnh trong audit-results/screenshots/
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';
import { gotoSell, safeScreenshot } from './lib/nail_nav.mjs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';
const SAMPLES = Number(process.env.SAMPLES || 8);
const GAP_MS = Number(process.env.GAP_MS || 6500);
const TIMEOUT_MS = 20000;
const ONLY = (process.env.ONLY || '').split(',').filter(Boolean);
const run = (k) => !ONLY.length || ONLY.includes(k);

const SHOTS = path.resolve('audit-results/screenshots/nail_customer_experience_latency');
fs.mkdirSync(SHOTS, { recursive: true });
const TOKEN = `UXLAT${Date.now().toString().slice(-6)}`;
const AU_PHONE = `04${Date.now().toString().slice(-8)}`;
const VN_PHONE = `09${Date.now().toString().slice(-8)}`;
const BOOK_PHONE = `08${Date.now().toString().slice(-8)}`;

const report = { ranAt: new Date().toISOString(), token: TOKEN, steps: [], latency: {} };
function record(name, status, note = '') {
  report.steps.push({ name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : status === 'INFO' ? 'ℹ️' : '❌';
  console.log(`${icon} [${status}] ${name}${note ? ' — ' + note : ''}`);
}
const shot = (page, f) => safeScreenshot(page, { path: path.join(SHOTS, f), fullPage: false });
function db(...args) {
  const out = execFileSync('python', ['scripts/_nail_latency_db.py', ...args], { encoding: 'utf-8' }).trim().split('\n');
  return JSON.parse(out[out.length - 1]);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function stats(arr) {
  const ok = arr.filter((x) => x != null).sort((a, b) => a - b);
  const miss = arr.length - ok.length;
  if (!ok.length) return { n: arr.length, miss, min: null, median: null, max: null };
  return { n: arr.length, miss, min: ok[0], median: ok[Math.floor(ok.length / 2)], max: ok[ok.length - 1], all: arr };
}
const fmt = (s) => `n=${s.n} · nhanh nhất ${s.min}ms · trung vị ${s.median}ms · chậm nhất ${s.max}ms · KHÔNG tới trong ${TIMEOUT_MS / 1000}s: ${s.miss}`;

// Đo: gọi send() rồi chờ predicate(token) đúng trên trang nhận; trả ms hoặc null nếu quá TIMEOUT_MS
async function measure(receiver, send, predicate, arg) {
  const t0 = Date.now();
  await send();
  try {
    await receiver.waitForFunction(predicate, arg, { timeout: TIMEOUT_MS, polling: 50 });
    return Date.now() - t0;
  } catch { return null; }
}

async function login(page) {
  // Máy dev Windows: thỉnh thoảng 1 script CDN trong <head> treo làm trang không bao giờ "domcontentloaded"
  // (server đã trả /login ngay, xem log) — thử lại 1 lần thay vì FAIL cả bài đo.
  for (let i = 1; i <= 2; i++) {
    try { await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 }); break; }
    catch (e) { if (i === 2) throw e; }
  }
  await page.fill('#loginEmail', EMAIL);
  await page.fill('#loginPassword', PASSWORD);
  await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
  if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại');
}

async function openWidget(page, phone) {
  await page.goto(`${BASE}/booking/nail/qr/${report.businessId}`, { waitUntil: 'networkidle' });
  await page.waitForSelector('#mascot-toggle-btn', { timeout: 10000 });
  await page.click('#mascot-toggle-btn');
  await page.waitForTimeout(500);
  await page.fill('#chatPhone', phone);
}

async function widgetAsk(page, text) {
  const before = await page.locator('.chat-ai').count();
  await page.fill('#chatMsg', text);
  const t0 = Date.now();
  await page.click('#mascot-chat-form button[type="submit"]');
  try {
    await page.waitForFunction((b) => document.querySelectorAll('.chat-ai').length > b, before, { timeout: 45000, polling: 50 });
    const ms = Date.now() - t0;
    const all = page.locator('.chat-ai');
    return { ms, text: (await all.nth((await all.count()) - 1).innerText()).trim() };
  } catch { return { ms: null, text: '' }; }
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const owner = await ownerCtx.newPage();
  const custCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const cust = await custCtx.newPage();
  const errors = [];
  for (const [who, p] of [['owner', owner], ['customer', cust]]) {
    p.on('pageerror', (e) => errors.push(`${who}: ${e.message}`));
  }

  try {
    await login(owner);
    await gotoSell(owner, BASE);
    report.businessId = await owner.evaluate(() => (typeof BUSINESS_ID !== 'undefined' ? BUSINESS_ID : null));
    record('Đăng nhập chủ tiệm', report.businessId ? 'PASS' : 'FAIL', `business_id=${report.businessId}`);

    // ---------------- C1: khách SĐT Úc ----------------
    if (run('C1')) {
      await openWidget(cust, AU_PHONE);
      await shot(cust, 'c1_widget_open_mobile.png');
      const r = await widgetAsk(cust, 'Hi, do you have a slot for gel manicure tomorrow at 3pm?');
      await shot(cust, 'c1_au_phone_reply.png');
      await sleep(1500);
      const saved = db('bot', report.businessId, AU_PHONE);
      report.latency.ai_reply_au_ms = r.ms;
      record('C1. Khách SĐT Úc (04xx) — AI trả lời', r.ms ? 'PASS' : 'FAIL', `${r.ms}ms · "${r.text.slice(0, 160)}"`);
      record('C1b. Hội thoại khách SĐT Úc có vào hộp thư /ai_bot của tiệm', saved.customer ? 'PASS' : 'FAIL',
        saved.customer ? `${saved.count} tin` : 'KHÔNG lưu — tiệm không bao giờ thấy khách này nhắn');
      // Khách xác nhận -> AI phải ĐẶT LỊCH THẬT (book_appointment) cho SĐT Úc
      const r2 = await widgetAsk(cust, 'Yes please book it, my name is Chloe. Gel Manicure & Cuticle Care tomorrow 3pm, any technician.');
      let booked = db('appt', report.businessId, AU_PHONE);
      if (!booked.count) {
        const r3 = await widgetAsk(cust, 'Yes, confirm the booking.');
        r2.text += ' || ' + r3.text;
        booked = db('appt', report.businessId, AU_PHONE);
      }
      await shot(cust, 'c1_au_booked.png');
      report.latency.ai_booking_reply_ms = r2.ms;
      record('C1c. Khách SĐT Úc nhờ AI đặt lịch -> đúng 1 lịch hẹn thật (không trùng)', booked.count === 1 ? 'PASS' : 'FAIL',
        `${JSON.stringify(booked.appointments)} · AI: "${r2.text.slice(0, 220)}"`);
    }

    // ---------------- C2 + C3: khách nhắn <-> chủ tiệm trả lời ----------------
    let custId = null;
    if (run('C2') || run('C3') || run('C4') || run('C5')) {
      await owner.goto(`${BASE}/ai_bot`, { waitUntil: 'networkidle' });
      await openWidget(cust, VN_PHONE);
      const t0 = Date.now();
      const inboxP = owner.waitForFunction((ph) => document.getElementById('customerList')?.textContent.includes(ph),
        VN_PHONE, { timeout: 45000, polling: 50 }).then(() => Date.now() - t0).catch(() => null);
      const r = await widgetAsk(cust, `Chị muốn làm gel tay chiều mai 3h, còn chỗ không em? ${TOKEN}`);
      const inboxMs = await inboxP;
      report.latency.ai_reply_ms = r.ms;
      report.latency.customer_to_inbox_first_ms = inboxMs;
      await shot(cust, 'c2_customer_ai_reply.png');
      record('C2. AI trả lời khách', r.ms ? (r.ms < 8000 ? 'PASS' : 'WARN') : 'FAIL', `${r.ms}ms · "${r.text.slice(0, 160)}"`);
      record('C2b. Khách mới hiện trong hộp thư /ai_bot của tiệm (không F5)', inboxMs ? 'PASS' : 'FAIL', `${inboxMs}ms sau khi khách bấm gửi`);
      custId = `${report.businessId}:${VN_PHONE}`;

      if (inboxMs) {
        await owner.locator('.customer-item', { hasText: VN_PHONE }).first().click();
        await owner.waitForTimeout(800);
        await shot(owner, 'c3_owner_inbox_open.png');
        const inboxText = await owner.locator('#chatBox').innerText();
        record('C2c. Hộp thư chủ tiệm hiện đúng chữ khách gõ (không lộ câu chỉ dẫn nội bộ cho AI)',
          inboxText.includes(`Chị muốn làm gel tay chiều mai 3h`) && !/book_appointment|vừa nhắn:/.test(inboxText) ? 'PASS' : 'FAIL',
          inboxText.slice(0, 160).replace(/\s+/g, ' '));
        const reply = `Dạ chị ơi 3h chiều mai còn chỗ nha ${TOKEN}R`;
        const ms = await measure(cust, async () => {
          await owner.fill('#userInput', reply);
          await owner.click('#btnSend');
        }, (tk) => document.getElementById('chat-messages-container')?.textContent.includes(tk), `${TOKEN}R`);
        report.latency.owner_reply_to_widget_ms = ms;
        await shot(cust, 'c3_customer_after_owner_reply.png');
        await shot(owner, 'c3_owner_after_reply.png');
        record('C3. Chủ tiệm trả lời ở /ai_bot -> khách đang mở widget thấy', ms ? 'PASS' : 'FAIL',
          ms ? `${ms}ms` : `khách KHÔNG nhận được trong ${TIMEOUT_MS / 1000}s`);
      }
    }

    // ---------------- C4: khách -> /ai_bot, rải đều qua chu kỳ SSE ----------------
    if (run('C4') && custId) {
      await owner.goto(`${BASE}/ai_bot`, { waitUntil: 'networkidle' });
      await owner.locator('.customer-item', { hasText: VN_PHONE }).first().click();
      await owner.waitForTimeout(800);
      const arr = [];
      for (let i = 0; i < SAMPLES; i++) {
        const tk = `${TOKEN}C${i}`;
        arr.push(await measure(owner, () => cust.evaluate(([cid, c]) => fetch('/api/portal/messages', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_id: cid, content: c }),
        }), [custId, `Khách nhắn thử ${tk}`]), (t) => document.getElementById('chatBox')?.textContent.includes(t), tk));
        await sleep(GAP_MS);
      }
      const s = stats(arr);
      report.latency.customer_to_ai_bot = s;
      record('C4. Khách nhắn -> tiệm thấy trong /ai_bot', s.miss ? 'FAIL' : (s.max < 2000 ? 'PASS' : 'WARN'), fmt(s));
    }

    // ---------------- C5: tiệm -> /portal của khách ----------------
    if (run('C5') && custId) {
      await cust.goto(`${BASE}/portal?id=${encodeURIComponent(custId)}`, { waitUntil: 'networkidle' });
      await shot(cust, 'c5_portal_mobile.png');
      const arr = [];
      for (let i = 0; i < SAMPLES; i++) {
        const tk = `${TOKEN}P${i}`;
        arr.push(await measure(cust, () => owner.evaluate(([cid, c]) => fetch('/api/bot/messages', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ customer_id: cid, content: c }),
        }), [custId, `Tiệm trả lời ${tk}`]), (t) => document.getElementById('chatBox')?.textContent.includes(t), tk));
        await sleep(GAP_MS);
      }
      const s = stats(arr);
      report.latency.owner_to_portal = s;
      await shot(cust, 'c5_portal_after.png');
      record('C5. Tiệm nhắn -> khách thấy trên /portal', s.miss ? 'FAIL' : (s.max < 2000 ? 'PASS' : 'WARN'), fmt(s));
    }

    // ---------------- C6: chat nội bộ ----------------
    if (run('C6')) {
      const ctx2 = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
      const staff = await ctx2.newPage();
      await login(staff);
      await owner.goto(`${BASE}/chat`, { waitUntil: 'networkidle' });
      await staff.goto(`${BASE}/app_chat`, { waitUntil: 'networkidle' });
      await owner.waitForTimeout(1500);
      const arr = [];
      for (let i = 0; i < SAMPLES; i++) {
        const tk = `${TOKEN}I${i}`;
        arr.push(await measure(owner, () => staff.evaluate((c) => fetch('/api/chat/messages', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room: 'KenhChung', content: c }),
        }), `Thợ báo: khách bàn 3 tới rồi ${tk}`), (t) => document.getElementById('chatBox')?.textContent.includes(t), tk));
        await sleep(GAP_MS);
      }
      const s = stats(arr);
      report.latency.internal_chat = s;
      await shot(owner, 'c6_internal_chat.png');
      record('C6. Chat nội bộ (thợ -> chủ)', s.miss ? 'FAIL' : (s.max < 2000 ? 'PASS' : 'WARN'), fmt(s));
      await ctx2.close();
    }

    // ---------------- C7: đặt lịch QR -> lịch / POS ----------------
    if (run('C7')) {
      const today = new Date();
      const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const midnight = new Date(); midnight.setHours(23, 55, 0, 0);
      const maxOff = Math.max(35, Math.min(330, Math.floor((midnight - Date.now()) / 60000)));
      const dt = new Date(Date.now() + (30 + Math.floor(Math.random() * (maxOff - 30))) * 60000);
      await owner.goto(`${BASE}/calendar?date=${iso(dt)}`, { waitUntil: 'networkidle' });
      await cust.goto(`${BASE}/booking/nail/qr/${report.businessId}`, { waitUntil: 'networkidle' });
      await cust.fill('#cus_name', `UX Latency ${TOKEN}`);
      await cust.fill('#cus_phone', BOOK_PHONE);
      if (await cust.locator('#cus_address').count()) await cust.fill('#cus_address', '1 Test St');
      await cust.selectOption('#cus_service', { index: 1 });
      if ((await cust.locator('#cus_staff option').count()) > 1) await cust.selectOption('#cus_staff', { index: 1 });
      await cust.fill('#cus_datetime', `${iso(dt)}T${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`);
      await shot(cust, 'c7_booking_form_mobile.png');
      const ms = await measure(owner, () => cust.click('#btnSubmit'),
        (ph) => Array.from(document.querySelectorAll('tr[data-appt-id]')).some((r) => r.textContent.includes(ph)), BOOK_PHONE);
      report.latency.booking_to_calendar_ms = ms;
      await shot(cust, 'c7_booking_done_mobile.png');
      record('C7. Khách đặt lịch QR -> /calendar tự hiện', ms ? (ms < 4000 ? 'PASS' : 'WARN') : 'FAIL', ms ? `${ms}ms (gồm cả tải lại trang lịch)` : 'không hiện');

      if (ms) {
        const pos = await ownerCtx.newPage();
        await gotoSell(pos, BASE);
        const before = await pos.evaluate(() => { const el = document.getElementById('checkedInBadge'); return el && !el.classList.contains('hidden') ? parseInt(el.textContent, 10) : 0; });
        const rowId = await owner.evaluate((ph) => Array.from(document.querySelectorAll('tr[data-appt-id]')).find((r) => r.textContent.includes(ph))?.getAttribute('data-appt-id'), BOOK_PHONE);
        const ms2 = await measure(pos, () => owner.locator(`tr[data-appt-id="${rowId}"] button:has-text("Check-in")`).first().click(),
          (b) => { const el = document.getElementById('checkedInBadge'); return (el && !el.classList.contains('hidden') ? parseInt(el.textContent, 10) : 0) > b; }, before);
        report.latency.checkin_to_pos_badge_ms = ms2;
        await shot(pos, 'c7_pos_badge.png');
        record('C7b. Check-in ở lịch -> badge POS tự tăng', ms2 ? (ms2 < 3000 ? 'PASS' : 'WARN') : 'FAIL', ms2 ? `${ms2}ms` : 'không tăng');
        await pos.close();
      }
    }
  } catch (e) {
    record('LỖI KHÔNG MONG MUỐN', 'FAIL', e.stack?.split('\n').slice(0, 3).join(' | '));
  } finally {
    record('Lỗi JS trên trang', errors.length ? 'WARN' : 'PASS', errors.slice(0, 5).join(' | '));
    if (report.businessId) {
      try { record('Dọn dữ liệu test', 'INFO', JSON.stringify(db('cleanup', report.businessId, TOKEN, AU_PHONE, VN_PHONE, BOOK_PHONE))); }
      catch (e) { record('Dọn dữ liệu test', 'WARN', e.message); }
    }
    fs.writeFileSync(path.resolve('audit-results/nail_customer_experience_latency.json'), JSON.stringify(report, null, 2));
    const fail = report.steps.filter((s) => s.status === 'FAIL').length;
    console.log(`\nTổng: ${report.steps.filter((s) => s.status === 'PASS').length} PASS · ${report.steps.filter((s) => s.status === 'WARN').length} WARN · ${fail} FAIL`);
    await browser.close();
    process.exit(fail ? 1 : 0);
  }
}

main();
