/**
 * scripts/ai_copilot_e2e.mjs — AI Copilot của chủ tiệm (/ai_bot) + trợ lý đặt lịch của khách, chạy THẬT DeepSeek.
 * Đóng vai khách (điện thoại, widget trang đặt lịch) + chủ tiệm (máy POS) cùng lúc:
 *   1. Khách nhắn -> chủ tiệm mở hội thoại -> Copilot soạn sẵn câu trả lời đúng tiệm/đúng ngôn ngữ, bấm "Dùng & sửa".
 *   2. 4 nút Tips + câu hỏi tự do: trả lời RIÊNG cho chủ tiệm bằng số liệu thật, KHÔNG ghi gì vào hội thoại khách.
 *   3. Công tắc AI: tắt -> khách nhắn không có AI chen vào (chỉ 1 lần báo nhân viên sẽ trả lời), bật lại -> AI trả lời.
 *   4. Nhân viên trả lời -> tự chuyển sang "nhân viên trả lời", khách thấy tin của tiệm.
 *   node scripts/ai_copilot_e2e.mjs   (server local 127.0.0.1:5001, DEEPSEEK_API_KEY)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';
const OUT = path.resolve('audit-results/screenshots/ai_copilot_e2e');
fs.mkdirSync(OUT, { recursive: true });
const PHONE = `09${Date.now().toString().slice(-8)}`;
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok, note }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const db = (...a) => { const o = execFileSync('python', ['scripts/_nail_latency_db.py', ...a], { encoding: 'utf-8' }).trim().split('\n'); return JSON.parse(o[o.length - 1]); };
const shot = (p, f) => p.screenshot({ path: path.join(OUT, f) }).catch(() => {});

const browser = await chromium.launch({ channel: 'chrome' });
const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const owner = await ownerCtx.newPage();
const custCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
const cust = await custCtx.newPage();
const errors = [];
owner.on('pageerror', (e) => errors.push('owner: ' + e.message));
cust.on('pageerror', (e) => errors.push('customer: ' + e.message));
let bid = null;

async function custSay(text, waitAi = true) {
  const before = await cust.locator('.chat-ai, .chat-shop').count();
  await cust.fill('#chatMsg', text);
  await cust.click('#mascot-chat-form button[type="submit"]');
  if (!waitAi) { await cust.waitForTimeout(4000); return null; }
  await cust.waitForFunction((b) => document.querySelectorAll('.chat-ai, .chat-shop').length > b, before, { timeout: 45000 }).catch(() => {});
  const all = cust.locator('.chat-ai');
  return (await all.nth((await all.count()) - 1).innerText()).trim();
}

try {
  await owner.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await owner.fill('#loginEmail', EMAIL);
  await owner.fill('#loginPassword', PASSWORD);
  await Promise.all([owner.waitForLoadState('networkidle'), owner.click('#btnLogin')]);
  bid = db('bot', 'x', 'x') && (await owner.evaluate(async () => (await (await fetch('/api/hr/employees')).json()).data?.[0]?.business_id));
  rec('Đăng nhập chủ tiệm', !!bid, bid);

  // Khách nhắn qua widget trang đặt lịch
  await cust.goto(`${BASE}/booking/nail/qr/${bid}`, { waitUntil: 'networkidle' });
  await cust.click('#mascot-toggle-btn');
  await cust.waitForTimeout(400);
  await cust.fill('#chatPhone', PHONE);
  const first = await custSay('Hi, how much is a gel manicure and can I come tomorrow around 2pm?');
  rec('Khách hỏi giá + giờ -> trợ lý trả lời', !!first && first.length > 20, first?.slice(0, 140));

  await owner.goto(`${BASE}/ai_bot`, { waitUntil: 'networkidle' });
  await owner.locator('.customer-item', { hasText: PHONE }).first().click();
  await owner.waitForTimeout(1500);
  rec('AI đã trả lời khách -> không hiện nháp thừa', await owner.locator('#aiClosingAlert').isHidden());

  // 2. Tips riêng: không ghi gì vào hội thoại khách
  const before = db('bot', bid, PHONE).count;
  const insight = {};
  for (const [topic, sel] of [['revenue', 'Revenue Tips'], ['retention', 'Customer Care Tips'], ['inventory', 'Inventory Tips'], ['staffing', 'Staffing Tips']]) {
    const t0 = Date.now();
    await owner.locator('button', { hasText: sel }).click();
    await owner.waitForFunction(() => { const t = document.getElementById('copilotAnswer')?.innerText || '';
      return t.length > 60 && !/reading your shop|đang đọc số liệu/i.test(t); }, null, { timeout: 60000 }).catch(() => {});
    insight[topic] = { ms: Date.now() - t0, text: await owner.locator('#copilotAnswer').innerText() };
    await shot(owner, `02_tip_${topic}.png`);
  }
  const after = db('bot', bid, PHONE).count;
  rec('4 nút Tips trả lời RIÊNG cho chủ tiệm — khách không nhận gì', after === before, `tin trong hội thoại khách: ${before} -> ${after}`);
  const dataDriven = (t) => /\$\s?\d/.test(t) && /(Acrylic|Ava|Penelope|Gel|Pedicure|Manicure|Callus|Combo)/i.test(t);
  for (const [topic, r] of Object.entries(insight)) {
    rec(`Tips "${topic}": dựa trên số liệu thật của tiệm`, dataDriven(r.text) && !/bitpaw software|phần mềm bitpaw/i.test(r.text),
      `${r.ms}ms · ${r.text.replace(/\s+/g, ' ').slice(0, 170)}`);
  }
  await owner.fill('#copilotQuestion', 'Which technician should I schedule on Saturday and why?');
  await owner.press('#copilotQuestion', 'Enter');
  await owner.waitForFunction(() => { const t = document.getElementById('copilotAnswer')?.innerText || '';
    return /saturday|thứ bảy|ava|chloe/i.test(t); }, null, { timeout: 60000 }).catch(() => {});
  const free = await owner.locator('#copilotAnswer').innerText();
  rec('Hỏi Copilot câu tự do -> trả lời theo số liệu thợ thật', /ava|chloe|sophia|emily|isabella|grace/i.test(free), free.replace(/\s+/g, ' ').slice(0, 170));

  // 3. Công tắc AI thật
  await owner.locator('label:has(#aiToggleSwitch)').click();
  await owner.waitForTimeout(800);
  const paused = await owner.evaluate(async (cid) => (await (await fetch('/api/bot/customers')).json()).data.find((c) => c.id === cid)?.ai_paused, `${bid}:${PHONE}`);
  rec('Tắt công tắc AI -> lưu thật cho khách này', paused === true, `ai_paused=${paused}`);
  const aiBubblesBefore = await cust.locator('.chat-ai').count();
  await custSay('Is Ava available tomorrow?', false);
  await custSay('Hello?', false);
  const aiBubblesAfter = await cust.locator('.chat-ai').count();
  const handoffText = await cust.locator('.chat-ai').last().innerText();
  rec('AI tắt: khách nhắn 2 tin -> AI không chen vào, chỉ báo 1 lần "nhân viên sẽ trả lời"',
    aiBubblesAfter - aiBubblesBefore === 1 && /staff|team|nhân viên/i.test(handoffText), `+${aiBubblesAfter - aiBubblesBefore} bong bóng: "${handoffText.slice(0, 90)}"`);
  await owner.waitForFunction((t) => document.getElementById('chatBox')?.innerText.includes(t), 'Is Ava available tomorrow?', { timeout: 10000 }).catch(() => {});
  rec('Chủ tiệm thấy tin khách gửi khi AI tắt', (await owner.locator('#chatBox').innerText()).includes('Is Ava available tomorrow?'));

  // 1. Copilot soạn sẵn câu trả lời
  await owner.waitForFunction(() => { const t = document.getElementById('aiClosingText')?.innerText || '';
    return t.length > 20 && !/drafting|đang soạn/i.test(t); }, null, { timeout: 45000 }).catch(() => {});
  const draft = await owner.locator('#aiClosingText').innerText();
  const draftOk = draft.length > 20 && !/bitpaw|software|phần mềm/i.test(draft) && /[a-z]/i.test(draft);
  await shot(owner, '01_reply_draft.png');
  rec('Copilot soạn sẵn câu trả lời cho khách (đúng tiệm, không phải bot bán phần mềm)', draftOk, draft.slice(0, 200));
  await owner.click('#btnUseDraft');
  const inputVal = await owner.inputValue('#userInput');
  rec('Bấm "Dùng & sửa" -> câu trả lời vào ô nhập để sửa (không còn "[AI Closing] Send special offer")',
    inputVal === draft.trim() && !inputVal.includes('[AI Closing]'), inputVal.slice(0, 80));


  // 4. Nhân viên trả lời -> khách thấy, công tắc ở "nhân viên"
  await owner.fill('#userInput', inputVal + ' Ava is free tomorrow at 2pm.');
  await owner.click('#btnSend');
  const seen = await cust.waitForFunction(() => /Ava is free tomorrow at 2pm/.test(document.getElementById('chat-messages-container')?.innerText || ''), null, { timeout: 15000 }).then(() => true).catch(() => false);
  await shot(cust, '03_customer_sees_staff.png');
  rec('Nhân viên trả lời -> khách thấy ngay trên widget', seen);
  const label = await owner.locator('#chatBox').innerText();
  rec('Tin của tiệm có nhãn AI / Nhân viên', /Staff|Nhân viên/.test(label) && /\bAI\b/.test(label));

  // Bật lại AI -> AI trả lời
  await owner.locator('label:has(#aiToggleSwitch)').click();
  await owner.waitForTimeout(800);
  const back = await custSay('Great, also how much is a pedicure?');
  rec('Bật lại AI -> AI trả lời khách', !!back && /\$|pedicure/i.test(back), back?.slice(0, 120));
  await shot(owner, '04_owner_after.png');
} catch (e) {
  rec('LỖI', false, e.message.split('\n')[0]);
} finally {
  rec('Không lỗi JS', errors.length === 0, errors.slice(0, 3).join(' | '));
  if (bid) console.log('Dọn:', JSON.stringify(db('cleanup', bid, 'NO_TOKEN_' + Date.now(), PHONE)));
  // thư báo chủ tiệm "khách đang chờ" do bước tắt AI tạo ra (khách thử của bài này)
  if (bid) execFileSync('python', ['-c', `from mongo_client import db; print(db.outbound_messages.delete_many({'business_id': '${bid}', 'kind': 'staff_alert', 'body': {'$regex': '${PHONE}'}}).deleted_count)`],
                        { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  await browser.close();
  const fail = steps.filter((s) => !s.ok).length;
  console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
  fs.writeFileSync('audit-results/ai_copilot_e2e.json', JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2));
  process.exit(fail ? 1 : 0);
}
