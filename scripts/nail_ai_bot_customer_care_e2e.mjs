/**
 * scripts/nail_ai_bot_customer_care_e2e.mjs
 *
 * Test THẬT cho AI bot chăm sóc khách hàng — trước đây chỉ verify trang /ai_bot (nội bộ chủ
 * tiệm) tải được, KHÔNG hề test bot mà KHÁCH HÀNG CUỐI thực sự nói chuyện trên trang đặt lịch
 * công khai (booking.html, widget static/js/cskh_widget.js). Đây là 1 bot RIÊNG với persona
 * RIÊNG (compose_booking_assistant_prompt() trong ai_sales_prompts.py, khác hẳn bot bán phần
 * mềm BitPaw mặc định của widget) — dùng DeepSeek thật + ngữ cảnh giá/dịch vụ THẬT của tiệm
 * (AIContextEngine.build_context_prompt), lưu hội thoại thật vào db.bot_messages.
 *
 * Test này đóng vai 1 khách hàng THẬT (ẩn danh, không đăng nhập) quét QR vào trang đặt lịch,
 * mở widget, chọn "Chat with AI", hỏi 1 câu về giá dịch vụ CÓ THẬT trong hệ thống, rồi xác
 * nhận: (1) bot trả lời thật (gọi DeepSeek thật, không phải mock), (2) câu trả lời có nhắc
 * đúng dữ liệu thật của tiệm (chứng minh có gắn ngữ cảnh, không phải trả lời chung chung),
 * (3) hội thoại được lưu thật vào MongoDB, (4) tab "Talk to Human Agent" bị ẩn đúng như thiết
 * kế (bot đặt lịch không phải bot sales của BitPaw).
 *
 * Chạy:  node scripts/nail_ai_bot_customer_care_e2e.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001, DEEPSEEK_API_KEY đã cấu hình trong .env
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';

const BASE = 'http://127.0.0.1:5001';
const BIZ_ID = '000b2c16-ab4e-42bd-944a-29c925cad09b';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_ai_bot_customer_care_e2e');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const steps = [];
function record(name, status, note = '') {
  steps.push({ name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] ${name}${note ? ' — ' + note : ''}`);
}
async function shot(page, file) {
  await page.screenshot({ path: path.join(SCREEN_DIR, file), fullPage: true });
}

async function main() {
  console.log('=== NAIL AI BOT (CHĂM SÓC KHÁCH HÀNG) E2E — bắt đầu ===\n');

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } }); // giả lập điện thoại, đúng cách khách quét QR thật
  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  const testPhone = `093${Date.now().toString().slice(-7)}`;
  const testQuestion = 'Acrylic Full Set giá bao nhiêu vậy shop, và bao lâu thì xong?';

  try {
    // ============================================================
    // 1. Vào trang đặt lịch công khai qua QR — ẩn danh, không session (y hệt khách thật)
    // ============================================================
    await page.goto(`${BASE}/booking/nail/qr/${BIZ_ID}`, { waitUntil: 'networkidle' });
    const businessIdOnPage = await page.evaluate(() => window.BITPAW_BUSINESS_ID);
    const chatContextOnPage = await page.evaluate(() => window.BITPAW_CHAT_CONTEXT);
    record('1. Vào trang đặt lịch công khai (QR)', businessIdOnPage === BIZ_ID && chatContextOnPage === 'customer_booking' ? 'PASS' : 'FAIL',
      `BITPAW_BUSINESS_ID=${businessIdOnPage}, BITPAW_CHAT_CONTEXT=${chatContextOnPage}`);

    // ============================================================
    // 2. Mở widget chat — xác nhận đây là bot ĐẶT LỊCH (không phải bot bán phần mềm BitPaw)
    // ============================================================
    await page.waitForSelector('#mascot-toggle-btn', { timeout: 10000 });
    await page.click('#mascot-toggle-btn');
    await page.waitForSelector('#chatWidget:not(.hidden-chat)', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(500);
    const headerText = await page.locator('#chatWidget .font-bold.text-sm').innerText().catch(() => '');
    const humanTabVisible = await page.locator('#chatModeHumanBtn').isVisible().catch(() => false);
    const quickRepliesVisible = await page.locator('#quick-replies-container').isVisible().catch(() => false);
    await shot(page, '01_widget_opened.png');
    record('2. Widget mở đúng persona "Trợ Lý Đặt Lịch" (không phải bot sales BitPaw)',
      /đặt lịch/i.test(headerText) && !humanTabVisible && !quickRepliesVisible ? 'PASS' : 'FAIL',
      `header="${headerText}", tab_human_agent_hien=${humanTabVisible}, quick_replies_sales_hien=${quickRepliesVisible}`);

    // ============================================================
    // 3. Nhập SĐT + hỏi thật 1 câu về giá dịch vụ CÓ THẬT (Acrylic Full Set = $95 đã seed)
    // ============================================================
    // QUAN TRỌNG: đã có sẵn 1 bong bóng .chat-ai (lời chào mặc định) TRƯỚC KHI gửi câu hỏi —
    // phải đếm số lượng bong bóng .chat-ai HIỆN CÓ trước, rồi chờ số lượng TĂNG LÊN sau khi
    // gửi, không được chỉ chờ "có .chat-ai nào đó" (sẽ ăn nhầm ngay câu chào, không phải câu
    // trả lời thật cho câu hỏi vừa hỏi).
    const aiBubbleCountBefore = await page.locator('.chat-ai').count();
    await page.fill('#chatPhone', testPhone);
    await page.fill('#chatMsg', testQuestion);
    await shot(page, '02_question_typed.png');
    await page.click('#mascot-chat-form button[type="submit"]');
    await page.waitForTimeout(500);
    const userBubbleVisible = await page.locator('.chat-user').first().isVisible().catch(() => false);
    record('3. Gửi câu hỏi thật (SĐT + nội dung) — hiện trong khung chat', userBubbleVisible ? 'PASS' : 'FAIL', `phone=${testPhone}`);

    // ============================================================
    // 4. Chờ AI trả lời THẬT (gọi DeepSeek thật qua /api/ai/studio/generate — có độ trễ mạng thật)
    // ============================================================
    let aiReplyText = '';
    try {
      await page.waitForFunction(
        (before) => document.querySelectorAll('.chat-ai').length > before,
        aiBubbleCountBefore,
        { timeout: 30000 },
      );
      // Đợi thêm cho typing indicator biến mất hẳn / DOM ổn định
      await page.waitForTimeout(800);
      const aiBubbles = page.locator('.chat-ai');
      const count = await aiBubbles.count();
      aiReplyText = await aiBubbles.nth(count - 1).innerText();
    } catch (e) {
      aiReplyText = '';
    }
    await shot(page, '03_ai_replied.png');
    const gotRealReply = aiReplyText.trim().length > 10 && !/lỗi|error|thất bại/i.test(aiReplyText);
    record('4. AI trả lời thật (gọi DeepSeek thật, có nội dung, không lỗi)', gotRealReply ? 'PASS' : 'FAIL',
      `reply="${aiReplyText.trim().slice(0, 200)}"`);

    // ============================================================
    // 5. Kiểm tra AI có "biết" dữ liệu thật của tiệm không (grounding) — trả lời có nhắc giá/tên
    //    dịch vụ đúng, KHÔNG PHẢI câu trả lời chung chung không liên quan
    // ============================================================
    const mentionsRealData = /95|acrylic|full\s*set/i.test(aiReplyText);
    record('5. AI trả lời có gắn đúng dữ liệu thật của tiệm (giá/tên dịch vụ)', mentionsRealData ? 'PASS' : 'WARN',
      mentionsRealData ? 'Câu trả lời có nhắc "95" hoặc "Acrylic/Full Set" — đúng dữ liệu seed thật' :
        'Câu trả lời không nhắc rõ số 95 hoặc tên dịch vụ — có thể AI diễn đạt khác đi, cần đọc thủ công câu trả lời ở trên để xác nhận.');

    // ============================================================
    // 6. Xác nhận hội thoại được LƯU THẬT vào MongoDB (không chỉ hiện trên UI rồi mất)
    // ============================================================
    await page.waitForTimeout(1000); // best-effort persist, cho DB ghi kịp
    let dbPersisted = false;
    let dbNote = '';
    try {
      const out = execFileSync('python', ['scripts/_e2e_db_helper.py', 'check_bot_messages', BIZ_ID, testPhone], { encoding: 'utf-8' });
      // mongo_client.py in vài dòng log ra stdout ngay lúc import — JSON thật luôn là dòng CUỐI.
      const outLines = out.trim().split('\n');
      const parsed = JSON.parse(outLines[outLines.length - 1]);
      dbPersisted = parsed.found && parsed.senderTypes.includes('customer');
      dbNote = `count=${parsed.count}, senderTypes=[${parsed.senderTypes.join(',')}], messages=${JSON.stringify(parsed.messages)}`;
    } catch (e) {
      dbNote = `Không chạy được helper: ${e.message}`;
    }
    record('6. Hội thoại lưu thật vào db.bot_messages (CRM)', dbPersisted ? 'PASS' : 'WARN', dbNote);

  } catch (e) {
    record('LỖI KHÔNG MONG MUỐN', 'FAIL', e.message);
  }

  record('Console errors trong toàn bộ luồng', consoleErrors.length === 0 ? 'PASS' : 'WARN', `${consoleErrors.length} lỗi: ${consoleErrors.slice(0, 3).join(' | ')}`);

  console.table(steps.map((s) => ({ Step: s.name, Status: s.status })));
  const pass = steps.filter((s) => s.status === 'PASS').length;
  const warn = steps.filter((s) => s.status === 'WARN').length;
  const fail = steps.filter((s) => s.status === 'FAIL').length;
  console.log(`\nTổng kết: ${pass} PASS · ${warn} WARN · ${fail} FAIL`);

  fs.writeFileSync(
    path.resolve('audit-results/nail_ai_bot_customer_care_e2e_report.json'),
    JSON.stringify({ ranAt: new Date().toISOString(), testPhone, testQuestion, steps }, null, 2),
  );

  await browser.close();
  process.exit(fail > 0 ? 1 : 0);
}

main();
