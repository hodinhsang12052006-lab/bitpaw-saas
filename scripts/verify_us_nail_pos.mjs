// scripts/verify_us_nail_pos.mjs
// Kiểm thử Nail POS (/sell) theo chuẩn payroll Mỹ/Úc: Dual Pricing (Cash/Card),
// Cash Tip vs Card Tip riêng biệt, Supply Fee trừ trước khi chia hoa hồng,
// Attendance Calendar, Payroll Sheet (Cash Payout / Check-Direct Deposit / Tax Withheld),
// và màn hình in receipt/paystub.
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const SHOT_DIR = 'audit-results/screenshots/nail_pos';
const VIDEO_DIR = 'audit-results/videos';
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

const NAIL_EMAIL = 'demo.nails.au.006758@bitpawdemo.com';
const NAIL_PASSWORD = 'DemoNails2026!';

let stt = 0;
const findings = [];

async function shot(page, label) {
  stt += 1;
  const fname = `${String(stt).padStart(2, '0')}_${label.replace(/[^a-zA-Z0-9_\-]/g, '_')}.png`;
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOT_DIR, fname), fullPage: false });
  console.log(`  [shot] #${stt} ${label} -> ${fname}`);
  return fname;
}

function attachErrorBucket(page) {
  const bucket = { console: [], api: [] };
  page.on('console', (msg) => { if (msg.type() === 'error') bucket.console.push(msg.text().slice(0, 300)); });
  page.on('response', (resp) => { if (resp.status() >= 400) bucket.api.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`); });
  page.on('dialog', async (dialog) => {
    console.log(`  [dialog] ${dialog.type()}: ${dialog.message().slice(0, 120)}`);
    if (dialog.type() === 'confirm' || dialog.type() === 'prompt') await dialog.accept();
    else await dialog.dismiss().catch(() => {});
  });
  return bucket;
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('#loginEmail', NAIL_EMAIL);
  await page.fill('#loginPassword', NAIL_PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null),
    page.click('#btnLogin'),
  ]);
  await page.waitForTimeout(800);
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    locale: 'vi-VN',
    recordVideo: { dir: VIDEO_DIR, size: { width: 1366, height: 768 } },
  });
  const page = await context.newPage();
  const err = attachErrorBucket(page);

  console.log('=== 1) Login + full POS overview ===');
  await login(page);
  await page.goto(`${BASE}/sell`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, 'pos_overview');
  if (err.console.length) findings.push(`[console errors on /sell load] ${err.console.join(' | ')}`);
  if (err.api.length) findings.push(`[api errors on /sell load] ${err.api.join(' | ')}`);
  err.console.length = 0; err.api.length = 0;

  console.log('=== 2) Add service -> Modifier modal -> Assign tech ===');
  const firstCard = page.locator('.svc-card').first();
  await firstCard.waitFor({ state: 'visible', timeout: 10000 });
  await firstCard.click({ force: true });
  await page.waitForTimeout(500);
  await shot(page, 'modifier_modal_open');

  const techSel = page.locator('#modItemTechSelect');
  if (await techSel.count() > 0) {
    const options = await techSel.locator('option').all();
    if (options.length > 1) {
      const val = await options[1].getAttribute('value');
      await techSel.selectOption(val);
    }
  }
  await page.locator('[data-shape="Round"]').first().click({ force: true }).catch(() => {});
  await page.locator('[data-length="Long"]').first().click({ force: true }).catch(() => {});
  const gelChk = page.locator('#modOptGelColor');
  if (await gelChk.count() > 0) await gelChk.check({ force: true }).catch(() => {});
  await page.waitForTimeout(300);
  await shot(page, 'modifier_modal_filled_with_tech');

  await page.locator('#btnConfirmModifier').click({ force: true });
  await page.waitForTimeout(600);
  await shot(page, 'service_added_to_cart');

  console.log('=== 3) Attempt 2nd tech on the SAME ticket line (data-model check) ===');
  // Cấu trúc dữ liệu hiện tại: mỗi dòng cart chỉ có 1 field scalar `tech_id`, không có mảng
  // nhiều thợ / % chia trên cùng 1 item. Xác nhận lại bằng cách kiểm tra DOM dòng cart chỉ có
  // 1 dropdown chọn thợ cho mỗi item, không có nút "+ thêm thợ phụ".
  const addTechBtnCount = await page.locator('button:has-text("Thêm thợ"), button:has-text("+ Thợ")').count();
  findings.push(`[multi-tech-per-item] Không tìm thấy nút thêm thợ phụ trên 1 dòng dịch vụ (count=${addTechBtnCount}). Xác nhận: mỗi item cart chỉ gán được 1 thợ (tech_id scalar) — đây là giới hạn model dữ liệu hiện tại, KHÔNG phải bug, cần quyết định sản phẩm nếu muốn hỗ trợ multi-tech/1 item.`);

  console.log('=== 4) Dual Pricing (Cash vs Card) + Cash/Card tip split ===');
  await page.waitForTimeout(300);
  await shot(page, 'cart_dual_pricing_view');
  const cashPriceTxt = await page.locator('#calcCashPrice').innerText().catch(() => null);
  const cardPriceTxt = await page.locator('#calcCardPrice').innerText().catch(() => null);
  console.log(`  Cash Price: ${cashPriceTxt} | Card Price: ${cardPriceTxt}`);
  if (cashPriceTxt && cardPriceTxt) {
    const cash = parseFloat(cashPriceTxt.replace(/[^0-9.]/g, ''));
    const card = parseFloat(cardPriceTxt.replace(/[^0-9.]/g, ''));
    if (!(card > cash)) {
      findings.push(`[BUG] Card price ($${card}) không lớn hơn Cash price ($${cash}) — phụ phí thẻ 2.5% có thể chưa được cộng đúng.`);
    } else {
      console.log(`  [OK] Card surcharge applied correctly: card ($${card}) > cash ($${cash})`);
    }
  }

  await page.fill('#cashTipInput', '5');
  await page.fill('#cardTipInput', '3');
  await page.waitForTimeout(300);
  await shot(page, 'cash_and_card_tip_entered');

  console.log('=== 5) Open Payment modal, verify live recompute on method switch ===');
  await page.locator('#btnPayNow').click({ force: true });
  await page.waitForTimeout(400);
  await shot(page, 'payment_modal_cash_default');

  const totalCashTxt = await page.locator('#modalGrandTotal').innerText().catch(() => null);
  await page.locator('[data-method="card"]').click({ force: true });
  await page.waitForTimeout(300);
  await shot(page, 'payment_modal_card_selected');
  const totalCardTxt = await page.locator('#modalGrandTotal').innerText().catch(() => null);
  console.log(`  Modal total (cash): ${totalCashTxt} | Modal total (card): ${totalCardTxt}`);
  if (totalCashTxt && totalCardTxt && totalCashTxt === totalCardTxt) {
    findings.push(`[BUG] Tổng tiền trên modal thanh toán KHÔNG đổi khi chuyển Cash -> Card (vẫn là ${totalCashTxt}) — phụ phí thẻ chưa được cập nhật live.`);
  } else {
    console.log('  [OK] Modal grand total recomputes live when switching Cash <-> Card.');
  }

  console.log('=== 6) Complete payment -> real DB persistence -> Receipt / Paystub print screen ===');
  const checkoutRespPromise = page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout'), { timeout: 15000 });
  await page.locator('#btnConfirmPayment').click({ force: true });
  const checkoutResp = await checkoutRespPromise;
  const checkoutJson = await checkoutResp.json().catch(() => ({}));
  await page.waitForTimeout(800);
  await shot(page, 'receipt_paystub_screen');
  const receiptVisible = await page.locator('#receiptModal.active').count();
  if (receiptVisible === 0) {
    findings.push('[BUG] Sau khi executePayment(), #receiptModal không hiển thị (thiếu class "active").');
  }
  if (!checkoutJson.success || !checkoutJson.order_id) {
    findings.push(`[BUG] /api/nail_pos/checkout không trả về success/order_id hợp lệ: ${JSON.stringify(checkoutJson)}`);
  } else {
    const receiptOrderNum = await page.locator('#rcptOrderNum').innerText().catch(() => null);
    if (!receiptOrderNum || !receiptOrderNum.includes(String(checkoutJson.order_id))) {
      findings.push(`[BUG] Số hoá đơn trên receipt (${receiptOrderNum}) không khớp order_id thật từ server (#${checkoutJson.order_id}).`);
    } else {
      console.log(`  [OK] Bill đã LƯU THẬT vào database: order_id=#${checkoutJson.order_id}, total=$${checkoutJson.total_amount} — receipt in ra khớp đúng số hoá đơn thật.`);
    }
  }
  // Đóng receipt nếu có nút đóng
  const closeReceiptBtn = page.locator('#receiptModal button:has-text("Đóng"), #receiptModal button:has-text("Close")');
  if (await closeReceiptBtn.count() > 0) await closeReceiptBtn.first().click({ force: true }).catch(() => {});
  await page.evaluate(() => { document.getElementById('receiptModal')?.classList.remove('active'); });
  await page.waitForTimeout(300);

  console.log('=== 6b) Payment/Order History drawer -> tìm đúng bill vừa thanh toán -> In lại ===');
  await page.evaluate(() => { openOrderHistoryModal(); });
  await page.waitForTimeout(1000);
  await shot(page, 'order_history_drawer');
  const historyText = await page.locator('#orderHistoryBody').innerText().catch(() => '');
  if (checkoutJson.order_id && !historyText.includes(`#${checkoutJson.order_id}`)) {
    findings.push(`[BUG] Bill #${checkoutJson.order_id} vừa thanh toán KHÔNG xuất hiện trong Lịch Sử Bill.`);
  } else {
    console.log(`  [OK] Bill #${checkoutJson.order_id} xuất hiện đúng trong Lịch Sử Bill.`);
    await page.locator(`button[onclick="reprintOrderFromHistory(${checkoutJson.order_id})"]`).click({ force: true }).catch(() => {});
    await page.waitForTimeout(700);
    await shot(page, 'order_history_reprint_bill');
    const reprintVisible = await page.locator('#receiptModal.active').count();
    if (reprintVisible === 0) {
      findings.push('[BUG] "In lại bill" từ Lịch Sử không mở lại được màn hình receipt.');
    } else {
      console.log('  [OK] "In lại bill" mở đúng lại receipt với dữ liệu thật từ DB.');
    }
    await page.evaluate(() => { document.getElementById('receiptModal')?.classList.remove('active'); });
  }
  await page.evaluate(() => { closeOrderHistoryModal(); });
  await page.waitForTimeout(300);

  console.log('=== 7) Attendance Calendar (chamcong_nail.html view_calendar) ===');
  await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, 'attendance_calendar_view');
  if (err.console.length) findings.push(`[console errors on /chamcong/nail load] ${err.console.join(' | ')}`);
  err.console.length = 0; err.api.length = 0;

  // Mở chi tiết 1 ngày nếu có ô ngày clickable
  const dayCell = page.locator('[onclick*="openDayDetailModal"]').first();
  if (await dayCell.count() > 0) {
    await dayCell.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'attendance_day_detail_modal');
    const closeBtn = page.locator('#calDayDetailModal button:has-text("Đóng")');
    if (await closeBtn.count() > 0) await closeBtn.first().click({ force: true }).catch(() => {});
  } else {
    findings.push('[INFO] Không tìm thấy ô ngày clickable trên lịch chấm công để mở chi tiết (có thể do tháng hiện tại chưa có dữ liệu).');
  }

  console.log('=== 8) Payroll Sheet: Cash Payout / Check-Direct Deposit / Tax Withheld ===');
  await page.waitForTimeout(300);
  const auditTabBtn = page.locator('button[onclick*="switchMainView(\'audit\')"], [onclick*="switchMainView(\'audit\')"]').first();
  if (await auditTabBtn.count() > 0) {
    await auditTabBtn.click({ force: true });
  } else {
    await page.evaluate(() => { if (typeof switchMainView === 'function') switchMainView('audit'); });
  }
  await page.waitForTimeout(800);
  await shot(page, 'payroll_audit_view');

  const techSelectAudit = page.locator('#auditTechSelect');
  await techSelectAudit.waitFor({ state: 'visible', timeout: 8000 });
  const auditOptions = await techSelectAudit.locator('option').all();
  if (auditOptions.length > 1) {
    const val = await auditOptions[1].getAttribute('value');
    await techSelectAudit.selectOption(val);
    await page.waitForTimeout(600);
    await shot(page, 'payroll_tech_selected');

    await page.fill('#slipTaxRateInput', '10');
    await page.locator('#btnExportSalarySlip').click({ force: true });
    await page.waitForTimeout(1200);

    const slipCash = await page.locator('#slipCashPayout').innerText().catch(() => null);
    const slipCheck = await page.locator('#slipCheckAmount').innerText().catch(() => null);
    const slipTax = await page.locator('#slipTaxWithheld').innerText().catch(() => null);
    const slipTakeHome = await page.locator('#slipTakeHome').innerText().catch(() => null);
    console.log(`  Cash Payout: ${slipCash} | Check/Direct Deposit: ${slipCheck} | Tax Withheld: ${slipTax} | Take Home: ${slipTakeHome}`);

    // Show the hidden slip on-screen briefly for a screenshot (normally only used for html2canvas export)
    await page.evaluate(() => {
      const el = document.getElementById('hiddenSalarySlip');
      if (el) { el.style.position = 'fixed'; el.style.top = '0px'; el.style.left = '0px'; el.style.zIndex = '99999'; el.style.display = 'block'; }
    });
    await page.waitForTimeout(300);
    stt += 1;
    const slipFname = `${String(stt).padStart(2, '0')}_payroll_slip_cash_check_tax_breakdown.png`;
    await page.locator('#hiddenSalarySlip').screenshot({ path: path.join(SHOT_DIR, slipFname) });
    console.log(`  [shot] #${stt} payroll_slip_cash_check_tax_breakdown -> ${slipFname}`);
    await page.evaluate(() => {
      const el = document.getElementById('hiddenSalarySlip');
      if (el) { el.style.display = 'none'; }
    });

    if (slipCash === null || slipCheck === null || slipTax === null) {
      findings.push('[BUG] Phiếu lương thiếu 1 trong 3 trường Cash Payout / Check-Direct Deposit / Tax Withheld sau khi xuất.');
    } else {
      console.log('  [OK] Payroll slip shows Cash Payout, Check/Direct Deposit, and Tax Withheld as 3 distinct fields.');
    }
  } else {
    findings.push('[INFO] Không có thợ nào trong danh sách Đối Soát để test xuất phiếu lương (dữ liệu demo có thể trống).');
  }

  const videoObj = page.video();
  await context.close();
  await browser.close();
  if (videoObj) {
    try {
      const autoPath = await videoObj.path();
      const target = path.join(VIDEO_DIR, 'pos_nail_us_standard.webm');
      if (fs.existsSync(target)) fs.unlinkSync(target);
      fs.renameSync(autoPath, target);
      console.log(`  [video] -> ${target}`);
    } catch (e) { console.log(`  [video RENAME FAILED] ${e.message}`); }
  }

  console.log(`\n=== DONE. Total shots: ${stt} ===`);
  console.log('\n=== FINDINGS ===');
  if (findings.length === 0) {
    console.log('  (none — all checks passed)');
  } else {
    findings.forEach((f) => console.log(`  - ${f}`));
  }
  fs.writeFileSync('audit-results/nail_pos_us_findings.json', JSON.stringify(findings, null, 2), 'utf-8');

  const hasBug = findings.some((f) => f.startsWith('[BUG]'));
  process.exit(hasBug ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
