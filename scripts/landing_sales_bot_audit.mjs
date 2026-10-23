/**
 * scripts/landing_sales_bot_audit.mjs — bot tư vấn (bán phần mềm) trên landing từng ngành, gọi DeepSeek thật.
 * Mỗi ngành: lời chào đúng ngành + đúng ngôn ngữ trang (không trộn Việt-Anh trong 1 câu), hỏi 1 câu nghiệp vụ,
 * kiểm tra câu trả lời nói đúng ngành, đúng ngôn ngữ, không hiện mã HTML thô, không nhận là người thật.
 *   node scripts/landing_sales_bot_audit.mjs [nail,fnb,...]   (server local 127.0.0.1:5001)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const OUT = path.resolve('audit-results/screenshots/landing_sales_bot_audit');
fs.mkdirSync(OUT, { recursive: true });
const CASES = {
  nail: ['en', 'How do you handle technician turns and tips?', /turn|tip|technician/i],
  spa: ['vi', 'Phần mềm quản lý liệu trình của khách thế nào?', /liệu trình|buổi/i],
  fnb: ['en', 'Can customers order from their table with a QR code?', /qr|table|kitchen/i],
  karaoke: ['vi', 'Tính tiền giờ phòng hát như thế nào?', /giờ|phút|phòng/i],
  hotel: ['en', 'Do you show which rooms are free?', /room/i],
  retail: ['vi', 'Có quét mã vạch và cảnh báo hết hàng không?', /mã vạch|kho|hết hàng|tồn/i],
  production: ['en', 'Can workers log output per shift?', /shift|output|worker/i],
  technical: ['vi', 'Thợ đi sửa chữa có chụp ảnh nghiệm thu được không?', /ảnh|chữ ký|nghiệm thu|thợ/i],
  office: ['en', 'How does staff clock in?', /clock|camera|gps|attendance/i],
};
const only = (process.argv[2] || '').split(',').filter(Boolean);
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok, note }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const isVi = (t) => /[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(t);

const browser = await chromium.launch({ channel: 'chrome' });
for (const [ind, [lang, q, topic]] of Object.entries(CASES)) {
  if (only.length && !only.includes(ind)) continue;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await ctx.addInitScript((l) => { try { localStorage.setItem('bitpaw_lang', l); } catch (e) { /* */ } }, lang);
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(`${BASE}/solutions/${ind}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  // Điện thoại: mascot ẩn, khách mở chat qua nút nổi .bp-fab -> "Chat với Trợ Lý AI" (đúng đường người thật bấm).
  // Nút nổi cố ý ẩn ở màn hình đầu (không che nút "Dùng thử") và khi đang cuộn xuống -> cuộn qua màn đầu, dừng lại rồi bấm.
  await p.waitForLoadState('load').catch(() => {});
  await p.evaluate(() => scrollTo(0, innerHeight * 1.2));
  await p.waitForSelector('.bp-fab:not(.bpx-hide)', { state: 'visible', timeout: 15000 });
  await p.waitForTimeout(400);
  await p.click('.bp-fab');
  await p.locator('#bpFabSheet .bp-sheet-item').first().click();
  await p.waitForSelector('#chatWidget:not(.hidden-chat)', { timeout: 5000 }).catch(() => {});
  await p.waitForTimeout(500);
  const greet = (await p.locator('.chat-ai').first().innerText()).trim();
  const greetOk = lang === 'vi' ? isVi(greet) : !isVi(greet);
  await p.fill('#chatPhone', `04${Date.now().toString().slice(-8)}`);
  const before = await p.locator('.chat-ai').count();
  await p.fill('#chatMsg', q);
  await p.click('#mascot-chat-form button[type="submit"]');
  await p.waitForFunction((b) => document.querySelectorAll('.chat-ai').length > b, before, { timeout: 45000 }).catch(() => {});
  const reply = (await p.locator('.chat-ai').last().innerText()).trim();
  await p.screenshot({ path: path.join(OUT, `${ind}_${lang}.png`) }).catch(() => {});
  const langOk = lang === 'vi' ? isVi(reply) : !isVi(reply.replace(/Zalo.*$/, ''));
  rec(`${ind} (${lang}) lời chào đúng ngôn ngữ, không trộn`, greetOk, greet.slice(0, 110));
  rec(`${ind} (${lang}) trả lời đúng ngành + ngôn ngữ, không HTML thô, không giả người thật`,
    topic.test(reply) && langOk && !/<br>|<span|class=/.test(reply) && !/(I am|I'm) (a )?(real )?human|tôi là người thật/i.test(reply) && errs.length === 0,
    reply.replace(/\s+/g, ' ').slice(0, 230));
  await ctx.close();
}
await browser.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
fs.writeFileSync('audit-results/landing_sales_bot_audit.json', JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2));
process.exit(fail ? 1 : 0);
