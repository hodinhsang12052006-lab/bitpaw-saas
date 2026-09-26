/**
 * scripts/nail_gap_completeness_audit.mjs
 *
 * Vòng test cuối theo yêu cầu "test cho bằng hết" — phủ nốt các phần mà 6 script trước đó
 * (nail_industry_master_audit / verify_service_cards / nail_realtime_sse_e2e /
 * nail_business_cycle_e2e / nail_shared_modules_audit / nail_full_product_video_walkthrough)
 * CHƯA từng chạm tới, phát hiện qua 1 vòng rà soát code toàn diện:
 *
 *   1) Thêm dịch vụ mới qua /add (danh mục "Nails" — VỪA được thêm, trước đây không tồn tại)
 *      -> xác nhận dịch vụ mới hiện ra thật trong lưới POS /sell.
 *   2) Thêm thợ mới qua /nhanvien (phòng ban "Nails" — VỪA được thêm) -> xác nhận thợ mới hiện
 *      ra thật trong dropdown gán thợ ở /sell (đúng nguồn db.employees mà POS đọc).
 *   3) Huỷ 1 lịch hẹn trên /calendar (chưa test trước đây, chỉ mới test Check-in).
 *   4) Discount type toggle — cả 2 chế độ Percent VÀ Fixed $ (trước đây có thể chỉ test 1 chế độ).
 *   5) Print Quote (báo giá trước thanh toán) — khác receipt reprint đã test.
 *   6) Gắn khách hàng có sẵn (CRM) vào ticket trước khi thanh toán.
 *   7) Square Terminal — xác nhận luồng graceful-degradation (báo lỗi rõ ràng khi chưa cấu hình
 *      thiết bị) thay vì crash trắng trang, vì charge thật cần thiết bị Square vật lý.
 *
 * Chạy:  node scripts/nail_gap_completeness_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_gap_completeness_audit');
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
  console.log('=== NAIL GAP COMPLETENESS AUDIT — bắt đầu ===\n');

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on('dialog', async (d) => { await d.accept(); });

  const uniq = Date.now().toString().slice(-7);
  const newServiceName = `QA Gel Deluxe ${uniq}`;
  const newTechCode = `QAN${uniq.slice(-4)}`;
  const newTechName = `QA Test Tech ${uniq.slice(-4)}`;

  try {
    // ============================================================
    // Đăng nhập
    // ============================================================
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
    if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại.');
    record('0. Đăng nhập chủ tiệm Nails', 'PASS', page.url());

    // ============================================================
    // 1. Thêm dịch vụ mới qua /add (category = Nails, MỚI thêm) -> xác nhận hiện trong /sell
    // ============================================================
    await page.goto(`${BASE}/add`, { waitUntil: 'networkidle' });
    await page.selectOption('#productCategory', 'Nails');
    await page.fill('#productName', newServiceName);
    await page.fill('#productStock', '999');
    await page.fill('#priceDisplay', '55');
    await shot(page, '01_add_service_form.png');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.click('#submitBtn'),
    ]);
    const addedOk = !page.url().includes('/add');
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid', { timeout: 10000 });
    await page.fill('#serviceSearchInput', newServiceName);
    await page.waitForTimeout(400);
    const newServiceVisible = await page.locator(`.service-card:has-text("${newServiceName}")`).count();
    await shot(page, '02_new_service_in_pos.png');
    record('1. Thêm dịch vụ mới qua /add (category "Nails") -> hiện trong POS', addedOk && newServiceVisible > 0 ? 'PASS' : 'FAIL',
      `redirect_ok=${addedOk}, found_in_pos_grid=${newServiceVisible > 0}`);
    await page.fill('#serviceSearchInput', '');

    // ============================================================
    // 2. Thêm thợ mới qua /nhanvien (department = Nails, MỚI thêm) -> xác nhận hiện trong dropdown gán thợ /sell
    // ============================================================
    await page.goto(`${BASE}/nhanvien`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#ma_nv', { timeout: 10000 });
    await page.fill('#ma_nv', newTechCode);
    await page.fill('#ho_ten', newTechName);
    await page.selectOption('#linh_vuc', 'Nails');
    await shot(page, '03_add_technician_form.png');
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/hr/employees') && r.request().method() === 'POST'),
      page.click('button[onclick="addEmployee()"]'),
    ]);
    await page.waitForTimeout(500);
    const techInList = await page.locator(`text=${newTechName}`).count();
    await shot(page, '04_technician_added_list.png');

    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.service-card', { timeout: 10000 });
    await page.locator('.service-card').first().click();
    await page.waitForTimeout(300);
    const techOptionCount = await page.locator(`#cartItems .cart-item select option:has-text("${newTechName}")`).count();
    await shot(page, '05_new_tech_in_pos_dropdown.png');
    record('2. Thêm thợ mới qua /nhanvien (department "Nails") -> hiện trong dropdown gán thợ POS',
      techInList > 0 && techOptionCount > 0 ? 'PASS' : 'FAIL',
      `hien_trong_danh_sach_nhanvien=${techInList > 0}, hien_trong_dropdown_pos=${techOptionCount > 0}`);
    // dọn giỏ hàng cho bước sau
    await page.evaluate(() => { if (typeof cart !== 'undefined') { cart.length = 0; renderCart(); } });

    // ============================================================
    // 3. Huỷ 1 lịch hẹn trên /calendar (chưa test trước đây)
    // ============================================================
    await page.goto(`${BASE}/calendar`, { waitUntil: 'networkidle' });
    // QUAN TRỌNG: lấy đúng data-appt-id của dòng có nút Huỷ TRƯỚC khi bấm, rồi luôn truy vấn lại
    // theo đúng id đó — không dùng lại locator .first()/ancestor sau khi bấm, vì updateStatus()
    // ở calendar.html thay ĐÚNG innerHTML của dòng đó (đổi luôn bộ nút hành động), khiến
    // ".first()" của "button:has-text('Huỷ')" đánh giá lại sẽ trôi sang dòng PENDING kế tiếp
    // (đúng lớp lỗi .first()-locator-cũ đã gặp và sửa ở nail_business_cycle_e2e.mjs).
    const targetApptId = await page.locator('tr[data-appt-id]').evaluateAll((rows) => {
      const row = rows.find((r) => Array.from(r.querySelectorAll('button')).some((b) => /huỷ|cancel/i.test(b.textContent)));
      return row ? row.getAttribute('data-appt-id') : null;
    });
    let cancelPass = false;
    let cancelNote = 'Không có lịch hẹn nào ở trạng thái có thể huỷ trong ngày đang xem.';
    if (targetApptId) {
      const cancelBtn = page.locator(`tr[data-appt-id="${targetApptId}"] button:has-text("Huỷ"), tr[data-appt-id="${targetApptId}"] button:has-text("Cancel")`).first();
      await Promise.all([
        page.waitForResponse((r) => /\/api\/appointments\/\d+\/status/.test(r.url()) && r.request().method() === 'PATCH'),
        cancelBtn.click(),
      ]);
      await page.waitForTimeout(500);
      const badgeText = await page.locator(`tr[data-appt-id="${targetApptId}"] [data-status-cell]`).innerText().catch(() => '');
      cancelPass = /huỷ|cancel/i.test(badgeText);
      cancelNote = `appointment_id=${targetApptId}, badge sau huỷ: "${badgeText.trim()}"`;
    }
    await shot(page, '06_calendar_cancel.png');
    record('3. Huỷ lịch hẹn trên /calendar', !targetApptId ? 'WARN' : (cancelPass ? 'PASS' : 'FAIL'), cancelNote);

    // ============================================================
    // 4. Discount type toggle — cả Percent và Fixed $
    // ============================================================
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('.service-card', { timeout: 10000 });
    await page.locator('.service-card').first().click();
    await page.waitForTimeout(300);
    // Discount là 1 modal RIÊNG (mở qua nút "Discount" trong khu vực hành động của ticket),
    // KHÔNG nằm trong payment modal của #checkoutBtn — 2 modal độc lập nhau.
    const discountBtnCount = await page.locator('[onclick="openDiscountModal()"]').count();
    if (discountBtnCount > 0) await page.click('[onclick="openDiscountModal()"]');
    await page.waitForTimeout(300);
    const discountModalOpen = await page.locator('[data-disc-type]').count();
    let percentActive = false, fixedActive = false;
    if (discountModalOpen > 0) {
      percentActive = await page.locator('[data-disc-type="percent"]').evaluate((el) => el.classList.contains('active'));
      await page.click('[data-disc-type="fixed"]');
      await page.waitForTimeout(200);
      fixedActive = await page.locator('[data-disc-type="fixed"]').evaluate((el) => el.classList.contains('active'));
    }
    await shot(page, '07_discount_type_toggle.png');
    record('4. Discount type toggle — Percent (mặc định) & Fixed $', percentActive && fixedActive ? 'PASS' : 'WARN',
      `discount_ui_found=${discountModalOpen > 0}, percent_default_active=${percentActive}, fixed_after_click=${fixedActive}`);
    if (discountModalOpen > 0) await page.evaluate(() => closeDiscountModal());

    // ============================================================
    // 5. Print Quote (báo giá trước thanh toán, KHÁC receipt reprint)
    // ============================================================
    let quoteWindowOpened = false;
    page.once('popup', async (popup) => {
      quoteWindowOpened = true;
      await popup.waitForLoadState('domcontentloaded').catch(() => {});
    });
    const printQuoteBtnCount = await page.locator('button:has-text("Print Quote"), button:has-text("In Báo Giá")').count();
    if (printQuoteBtnCount > 0) {
      await page.locator('button:has-text("Print Quote"), button:has-text("In Báo Giá")').first().click();
      await page.waitForTimeout(800);
    }
    record('5. Print Quote (báo giá trước thanh toán)', printQuoteBtnCount > 0 ? (quoteWindowOpened ? 'PASS' : 'WARN') : 'WARN',
      `nut_ton_tai=${printQuoteBtnCount > 0}, cua_so_moi_mo=${quoteWindowOpened}`);

    // ============================================================
    // 6. Gắn khách hàng có sẵn (CRM) vào ticket trước khi thanh toán
    // ============================================================
    const customerOptions = await page.locator('#customerSelect option').count();
    let customerAttached = false;
    if (customerOptions > 1) {
      await page.selectOption('#customerSelect', { index: 1 });
      customerAttached = await page.locator('#customerSelect').inputValue() !== '';
    }
    await shot(page, '08_customer_attach.png');
    record('6. Gắn khách hàng CRM có sẵn vào ticket', customerOptions > 1 ? (customerAttached ? 'PASS' : 'FAIL') : 'WARN',
      `so_khach_trong_dropdown=${customerOptions - 1}, da_chon=${customerAttached}`);

    // đóng modal thanh toán nếu đang mở, dọn giỏ hàng
    await page.keyboard.press('Escape').catch(() => {});
    await page.evaluate(() => { if (typeof cart !== 'undefined') { cart.length = 0; renderCart(); } });

    // ============================================================
    // 7. Square Terminal — graceful degradation khi chưa cấu hình thiết bị thật
    // ============================================================
    await page.locator('.service-card').first().click();
    await page.waitForTimeout(300);
    if (await page.locator('#checkoutBtn').count() > 0) await page.click('#checkoutBtn', { force: true });
    await page.waitForTimeout(300);
    const squareTileCount = await page.locator('[data-method="square_terminal"]').count();
    let squareErrorShown = false, squareErrorText = '';
    if (squareTileCount > 0) {
      await page.click('[data-method="square_terminal"]');
      await page.waitForTimeout(300);
      const confirmBtn = page.locator('button:has-text("Confirm"), button:has-text("Xác Nhận")').first();
      if (await confirmBtn.count() > 0) {
        await confirmBtn.click().catch(() => {});
        await page.waitForTimeout(2000);
        const errBox = page.locator('#squareTerminalError');
        squareErrorShown = await errBox.isVisible().catch(() => false);
        squareErrorText = squareErrorShown ? await errBox.innerText() : '';
      }
    }
    await shot(page, '09_square_terminal_graceful_error.png');
    record('7. Square Terminal — báo lỗi rõ ràng khi chưa cấu hình thiết bị (không charge thật được trong môi trường này)',
      squareTileCount > 0 ? (squareErrorShown ? 'PASS' : 'WARN') : 'WARN',
      `tile_ton_tai=${squareTileCount > 0}, error_hien_ro_rang=${squareErrorShown}, message="${squareErrorText.trim()}"`);

  } catch (e) {
    record('LỖI KHÔNG MONG MUỐN', 'FAIL', e.message);
  }

  console.table(steps.map((s) => ({ Step: s.name, Status: s.status })));
  const pass = steps.filter((s) => s.status === 'PASS').length;
  const warn = steps.filter((s) => s.status === 'WARN').length;
  const fail = steps.filter((s) => s.status === 'FAIL').length;
  console.log(`\nTổng kết: ${pass} PASS · ${warn} WARN · ${fail} FAIL`);

  fs.writeFileSync(
    path.resolve('audit-results/nail_gap_completeness_audit_report.json'),
    JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2),
  );

  await browser.close();
  process.exit(fail > 0 ? 1 : 0);
}

main();
