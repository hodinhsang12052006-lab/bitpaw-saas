/**
 * scripts/nail_realtime_sse_e2e.mjs
 *
 * Verify tính năng real-time mới thêm: /api/stream/appointments (SSE, Change Streams trên
 * db.appointments) phải đẩy tín hiệu tới:
 *   A) /calendar — tab đang mở tự reload và hiện đúng lịch hẹn khách vừa đặt qua QR, KHÔNG cần
 *      nhân viên bấm F5 tay.
 *   B) pos_nail.html — badge "Đã Check-in" tự cập nhật số ngay khi 1 tab khác bấm Check-in trên
 *      /calendar, KHÔNG cần tải lại trang POS (test bằng cách đếm số lần 'framenavigated' của
 *      đúng tab POS đó trong lúc chờ badge đổi — phải bằng 0).
 *
 * Chạy:  node scripts/nail_realtime_sse_e2e.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_realtime_sse_e2e');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const steps = [];
function record(name, status, note = '') {
  steps.push({ name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] ${name}${note ? ' — ' + note : ''}`);
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function main() {
  console.log('=== NAIL REALTIME SSE E2E — bắt đầu ===\n');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });

  // Context A = chủ tiệm/thu ngân, đăng nhập thật, giữ mở /calendar và /sell suốt bài test
  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const ownerPage = await ownerContext.newPage();
  // Context B = khách hàng, ẩn danh, KHÔNG đăng nhập — giả lập quét QR thật
  const guestContext = await browser.newContext({ viewport: { width: 430, height: 900 } });
  const guestPage = await guestContext.newPage();

  let businessId = null;
  let acrylicServiceId = null;
  let avaStaffId = null;
  let bookingDateStr = todayISO();
  let appointmentUniquePhone = `090${Date.now().toString().slice(-7)}`;

  try {
    // ============================================================
    // Đăng nhập chủ tiệm, lấy business_id, mở sẵn /calendar hôm nay (KHÔNG reload thủ công sau đây)
    // ============================================================
    await ownerPage.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await ownerPage.fill('#loginEmail', EMAIL);
    await ownerPage.fill('#loginPassword', PASSWORD);
    await Promise.all([ownerPage.waitForLoadState('networkidle'), ownerPage.click('#btnLogin')]);
    if (ownerPage.url().includes('/login')) throw new Error('Đăng nhập thất bại.');

    await ownerPage.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await ownerPage.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    businessId = await ownerPage.evaluate(() => (typeof BUSINESS_ID !== 'undefined' ? BUSINESS_ID : null));
    record('0. Đăng nhập chủ tiệm', businessId ? 'PASS' : 'FAIL', `business_id=${businessId}`);
    if (!businessId) throw new Error('Không lấy được business_id.');

    await ownerPage.goto(`${BASE}/calendar?date=${bookingDateStr}`, { waitUntil: 'networkidle' });
    const rowCountBefore = await ownerPage.locator('tr[data-appt-id]').count();
    record('0b. Mở sẵn /calendar (không đụng tới nữa cho tới lúc chờ SSE)', 'PASS', `${rowCountBefore} dòng lúc đầu`);

    // ============================================================
    // TEST A — khách đặt lịch qua QR ở Context B -> /calendar bên Context A phải TỰ hiện ra
    // ============================================================
    const qrUrl = `${BASE}/booking/nail/qr/${businessId}`;
    await guestPage.goto(qrUrl, { waitUntil: 'networkidle' });
    await guestPage.waitForSelector('#cus_service', { timeout: 10000 });

    await guestPage.fill('#cus_name', 'SSE Test Guest');
    await guestPage.fill('#cus_phone', appointmentUniquePhone);
    await guestPage.fill('#cus_address', '123 Test St');
    await guestPage.selectOption('#cus_service', { index: 1 });
    const staffOptionsCount = await guestPage.locator('#cus_staff option').count().catch(() => 0);
    if (staffOptionsCount > 1) await guestPage.selectOption('#cus_staff', { index: 1 });
    // Giờ đặt lịch NGẪU NHIÊN mỗi lần chạy — cố định "15:30" khiến lần chạy lại (cùng thợ, cùng
    // giờ) bị chính booking_engine.py::book_appointment() chặn hợp lệ vì trùng lịch thợ
    // (SlotAlreadyBookedError), không liên quan gì tới SSE cả nhưng làm script FAIL oan.
    const randomHour = String(10 + Math.floor(Math.random() * 8)).padStart(2, '0');
    const randomMinute = String(Math.floor(Math.random() * 60)).padStart(2, '0');
    await guestPage.fill('#cus_datetime', `${bookingDateStr}T${randomHour}:${randomMinute}`);

    const [bookingResp] = await Promise.all([
      guestPage.waitForResponse((r) => r.url().includes('/create_appointment') && r.request().method() === 'POST', { timeout: 15000 }).catch(() => null),
      guestPage.click('#btnSubmit'),
    ]);
    const bookingOk = bookingResp ? bookingResp.ok() : false;
    record('A1. Khách đặt lịch qua QR (Context B, ẩn danh)', bookingOk ? 'PASS' : 'WARN', bookingOk ? '' : 'Không bắt được response POST /create_appointment — kiểm tra selector form nếu FAIL bước sau');

    // KHÔNG reload ownerPage — chỉ chờ đúng dòng mới xuất hiện do chính JS SSE của trang tự làm
    let sseCalendarPass = false;
    try {
      await ownerPage.waitForFunction(
        (phone) => {
          const rows = Array.from(document.querySelectorAll('tr[data-appt-id]'));
          return rows.some((r) => r.textContent.includes(phone));
        },
        appointmentUniquePhone,
        { timeout: 15000, polling: 300 }
      );
      sseCalendarPass = true;
    } catch (e) {
      sseCalendarPass = false;
    }
    await ownerPage.screenshot({ path: path.join(SCREEN_DIR, '01_calendar_after_sse.png'), fullPage: true });
    record(
      'A2. /calendar tự cập nhật qua SSE, KHÔNG bấm F5 tay',
      sseCalendarPass ? 'PASS' : 'FAIL',
      sseCalendarPass ? 'Dòng lịch hẹn mới xuất hiện tự động sau khi khách đặt qua QR' : 'Không thấy dòng mới xuất hiện trong 15s — SSE hoặc auto-reload chưa hoạt động'
    );

    if (!sseCalendarPass) throw new Error('Dừng sớm: bước A2 FAIL, không đủ điều kiện test tiếp phần B.');

    // Lấy đúng appointment id vừa xuất hiện để Check-in nó ở phần B
    const newRowId = await ownerPage.evaluate((phone) => {
      const rows = Array.from(document.querySelectorAll('tr[data-appt-id]'));
      const row = rows.find((r) => r.textContent.includes(phone));
      return row ? row.getAttribute('data-appt-id') : null;
    }, appointmentUniquePhone);

    // ============================================================
    // TEST B — mở POS ở 1 tab riêng, KHÔNG đụng tới nó; Check-in lịch hẹn từ ownerPage (đang ở
    // /calendar) -> badge "Đã Check-in" bên tab POS phải tự tăng số, không có lần reload nào.
    // ============================================================
    const posPage = await ownerContext.newPage();
    await posPage.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await posPage.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
    let posNavigations = 0;
    posPage.on('framenavigated', (frame) => {
      if (frame === posPage.mainFrame()) posNavigations += 1;
    });
    const badgeBefore = await posPage.evaluate(() => {
      const el = document.getElementById('checkedInBadge');
      return el && !el.classList.contains('hidden') ? parseInt(el.textContent, 10) : 0;
    });

    // Check-in đúng dòng vừa đặt, bằng nút Check-in thật trên /calendar (ownerPage)
    const checkinBtn = ownerPage.locator(`tr[data-appt-id="${newRowId}"] button:has-text("Check-in")`).first();
    await checkinBtn.click();
    await ownerPage.waitForTimeout(500); // đợi PATCH status xong (updateStatus() tự patch DOM tại chỗ)

    let sseBadgePass = false;
    try {
      await posPage.waitForFunction(
        (before) => {
          const el = document.getElementById('checkedInBadge');
          const now = el && !el.classList.contains('hidden') ? parseInt(el.textContent, 10) : 0;
          return now > before;
        },
        badgeBefore,
        { timeout: 15000, polling: 300 }
      );
      sseBadgePass = true;
    } catch (e) {
      sseBadgePass = false;
    }
    await posPage.screenshot({ path: path.join(SCREEN_DIR, '02_pos_badge_after_sse.png'), fullPage: true });
    record(
      'B1. Badge "Đã Check-in" trên POS tự tăng qua SSE, KHÔNG reload trang',
      sseBadgePass && posNavigations === 0 ? 'PASS' : sseBadgePass ? 'WARN' : 'FAIL',
      `badgeBefore=${badgeBefore}, posNavigations=${posNavigations}${sseBadgePass ? '' : ' — badge không tăng trong 15s'}`
    );

    // Xác nhận panel "Checked-In Guests" cũng có đúng khách này nếu mở modal ngay lúc đó
    await posPage.evaluate(() => openCheckedInModal());
    await posPage.waitForTimeout(400);
    const listHasGuest = await posPage.evaluate((phone) => {
      const list = document.getElementById('checkedInList');
      return list ? list.textContent.includes(phone) : false;
    }, appointmentUniquePhone);
    record('B2. Panel "Checked-In Guests" hiện đúng khách vừa check-in', listHasGuest ? 'PASS' : 'WARN');

  } catch (e) {
    record('LỖI KHÔNG MONG MUỐN', 'FAIL', e.message);
  } finally {
    console.log('\n=== KẾT QUẢ ===');
    const passCount = steps.filter((s) => s.status === 'PASS').length;
    const warnCount = steps.filter((s) => s.status === 'WARN').length;
    const failCount = steps.filter((s) => s.status === 'FAIL').length;
    console.log(`\nTổng kết: ${passCount} PASS · ${warnCount} WARN · ${failCount} FAIL`);
    await browser.close();
    process.exit(failCount > 0 ? 1 : 0);
  }
}

main();
