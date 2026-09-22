// scripts/zota_bitpaw_pos_audit.mjs
// Playwright E2E verification for ZOTA POS & BITPAW HYBRID TERMINAL
// Viewport: 1366x768, records full video to audit-results/videos/pos_nail_hybrid.webm

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com';
const PASS = 'DemoNails2026!';

const SHOT_DIR = path.join('audit-results', 'screenshots', 'pos_hybrid');
const VIDEO_DIR = path.join('audit-results', 'videos');
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

async function main() {
  console.log('=== KHỞI ĐỘNG KIỂM THỬ PLAYWRIGHT E2E CHO ZOTA & BITPAW HYBRID POS ===');
  
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    recordVideo: {
      dir: VIDEO_DIR,
      size: { width: 1366, height: 768 }
    }
  });

  const page = await context.newPage();

  async function takeShot(name) {
    await page.waitForTimeout(500);
    const p = path.join(SHOT_DIR, name);
    await page.screenshot({ path: p, fullPage: false });
    console.log(`  -> [Screenshot] ${name}`);
  }

  // STEP 0: ĐĂNG NHẬP
  console.log('1. Đăng nhập tài khoản Salon Nails...');
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('#loginEmail', EMAIL);
  await page.fill('#loginPassword', PASS);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null),
    page.click('#btnLogin')
  ]);
  await page.waitForTimeout(1000);
  console.log(`  -> Đã đăng nhập. URL hiện tại: ${page.url()}`);

  // STEP 1: TRUY CẬP POS NAIL SPLIT-SCREEN
  console.log('2. Truy cập /sell (Zota & BitPaw Hybrid POS Terminal)...');
  await page.goto(`${BASE}/sell`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.pos-split-layout', { timeout: 10000 });
  await page.waitForTimeout(1000);
  await takeShot('01_pos_hybrid_terminal_initial.png');

  // STEP 2: CỤM TÍNH NĂNG ĐỘC QUYỀN BITPAW SUITE
  console.log('3. Kiểm tra cụm tính năng độc quyền BitPaw Suite...');
  
  // 2.1: Nail Radar
  console.log('  -> Mở BitPaw Nail Radar...');
  await page.click('#btnOpenNailRadar');
  await page.waitForSelector('#nailRadarModal.active', { timeout: 5000 });
  await page.waitForTimeout(800);
  await takeShot('02_bitpaw_nail_radar_modal.png');
  await page.click("#nailRadarModal button:has-text('Đóng')");
  await page.waitForTimeout(400);

  // 2.2: Omnichannel Chat
  console.log('  -> Mở Omnichannel Chat Inbox...');
  await page.click('#btnOpenOmnichannel');
  await page.waitForSelector('#omnichannelModal.active', { timeout: 5000 });
  await page.fill('#chatReplyInput', 'Dạ tiệm có chỗ làm móng Ombre lúc 10h sáng mai cho bạn ạ!');
  await page.click("#omnichannelModal button:has(.fa-paper-plane)");
  await page.waitForTimeout(600);
  await takeShot('03_bitpaw_omnichannel_chat_modal.png');
  await page.click("#omnichannelModal button:has(.fa-xmark)");
  await page.waitForTimeout(400);

  // 2.3: AI Studio
  console.log('  -> Mở BitPaw AI Studio & Campaign...');
  await page.click('#btnOpenAiStudio');
  await page.waitForSelector('#aiStudioModal.active', { timeout: 5000 });
  await page.click("#aiStudioModal button[data-camp='flash_friday']");
  await page.waitForTimeout(600);
  await takeShot('04_bitpaw_ai_studio_modal.png');
  await page.click("#aiStudioModal button:has-text('Đóng')");
  await page.waitForTimeout(400);

  // 2.4: CRM Nurturing
  console.log('  -> Mở CRM Nurturing (Khách sắp rời bỏ)...');
  await page.click('#btnOpenCrmNurture');
  await page.waitForSelector('#crmNurturingModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('05_bitpaw_crm_nurturing_modal.png');
  await page.click("#crmNurturingModal button:has-text('Đóng')");
  await page.waitForTimeout(400);

  // STEP 3: CỤM VẬN HÀNH ZOTA POS (BOOKINGS & WAITING QUEUE & CASH)
  console.log('4. Kiểm tra cụm vận hành Zota POS...');

  // 3.1: Booking List & 1-Click Check-in
  console.log('  -> Mở Lịch Hẹn Trực Tuyến (Bookings)...');
  await page.click('#btnOpenBookings');
  await page.waitForSelector('#bookingModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('06_zota_booking_modal.png');

  // Check-in booking 1 (Emily Brown) vào vé
  console.log('  -> Nhấn Check-in khách hẹn vào vé làm việc...');
  await page.click("#bookingsContainer button:has-text('Check-in')");
  await page.waitForTimeout(800);
  await takeShot('07_booking_checked_in_to_ticket.png');

  // 3.2: Waiting Queue
  console.log('  -> Mở Hàng Chờ Khách Walk-in (Waiting Queue)...');
  await page.click('#btnOpenWaitingQueue');
  await page.waitForSelector('#waitingQueueModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('08_zota_waiting_queue_modal.png');
  await page.click("#waitingQueueModal button:has-text('Đóng')");
  await page.waitForTimeout(400);

  // 3.3: No Sale
  console.log('  -> Kích hoạt No-Sale (Mở két tiền mặt)...');
  await page.click('#btnNoSale');
  await page.waitForTimeout(600);
  await takeShot('09_no_sale_triggered.png');

  // 3.4: Cash Payout
  console.log('  -> Mở Cash Payout (Chi tiêu từ két)...');
  await page.click('#btnOpenPayout');
  await page.waitForSelector('#payoutModal.active', { timeout: 5000 });
  await page.fill('#payoutAmount', '45');
  await page.fill('#payoutReason', 'Mua 2 can Acetone & nước ngọt mời khách');
  await page.waitForTimeout(500);
  await takeShot('10_cash_payout_modal.png');
  await page.click("#payoutModal button:has-text('Huỷ')");
  await page.waitForTimeout(400);

  // STEP 4: SERVICE MATRIX & MODIFIER MODAL
  console.log('5. Thêm dịch vụ với Modifier Modal & Món tự do Open Item...');
  // Click on second service card
  const cards = page.locator('.svc-card');
  if (await cards.count() > 1) {
    await cards.nth(1).click();
    await page.waitForSelector('#modifierModal.active', { timeout: 5000 });
    // Select shape Coffin and length Long
    await page.click("#shapeOptionsList .opt-chip[data-shape='Coffin']");
    await page.click("#lengthOptionsList .opt-chip[data-length='Long']");
    await page.check('#modOptGelColor');
    await page.waitForTimeout(600);
    await takeShot('11_modifier_nail_options_modal.png');
    await page.click('#btnConfirmModifier');
    await page.waitForTimeout(600);
  }

  // Open Item
  console.log('  -> Thêm món vẽ tự do (Open Item)...');
  await page.click('#btnOpenItemDirect');
  await page.waitForSelector('#customItemModal.active', { timeout: 5000 });
  await page.fill('#customItemName', 'Vẽ Móng Nghệ Thuật Hoa 3D & Đính Đá');
  await page.fill('#customItemPrice', '35');
  await page.waitForTimeout(500);
  await page.click('#btnConfirmOpenItem');
  await page.waitForTimeout(600);
  await takeShot('12_open_item_custom_added.png');

  // STEP 5: MULTI-TECH PER-ITEM ASSIGNMENT
  console.log('6. Gán 2 thợ khác nhau cho 2 dịch vụ trên cùng 1 bill...');
  const techSelects = page.locator('.cart-row select');
  if (await techSelects.count() >= 2) {
    await techSelects.nth(0).selectOption({ index: 0 });
    await techSelects.nth(1).selectOption({ index: 1 });
  }
  await page.waitForTimeout(600);
  await takeShot('13_multi_tech_cart_assigned.png');

  // STEP 6: HOLD TICKET, SPLIT BILL, TIP MATRIX & DUAL PRICING
  console.log('7. Thao tác Treo vé, Tách bill, Tip Matrix & Dual Pricing...');
  // Hold & unhold
  await page.click('#btnHoldTicket');
  await page.waitForTimeout(500);
  await page.click('#btnHoldTicket');
  await page.waitForTimeout(500);
  await takeShot('14_hold_and_resume_ticket.png');

  // Split bill modal
  await page.click('#btnSplitBill');
  await page.waitForSelector('#splitBillModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('15_split_bill_modal.png');
  await page.click("#splitBillModal button:has-text('Đóng')");
  await page.waitForTimeout(400);

  // Tip Chip 18% & check Take-off fee
  await page.click("button.tip-chip:has-text('18%')");
  await page.check('#chkTakeOffFee');
  await page.waitForTimeout(600);
  await takeShot('16_tip_matrix_and_dual_pricing.png');

  // STEP 7: PAYMENT MODAL & THERMAL RECEIPT
  console.log('8. Mở modal Thanh Toán với Dual Pricing & Hoàn tất hoá đơn...');
  await page.click('#btnPayNow');
  await page.waitForSelector('#paymentModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('17_payment_modal_dual_pricing.png');

  // Confirm payment
  await page.click('#btnConfirmPayment');
  await page.waitForSelector('#receiptModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await takeShot('18_thermal_receipt_completed.png');
  await page.click('#receiptCloseBtn');
  await page.waitForTimeout(500);

  // STEP 8: ATTENDANCE CALENDAR GRID
  console.log('9. Chuyển sang module Lịch Chấm Công & Bảng Lương (Calendar Grid)...');
  await page.goto(`${BASE}/chamcong_nail`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#calendarGridCells', { timeout: 10000 });
  await page.waitForSelector('.cal-cell:not(.empty)', { timeout: 10000 });
  await page.waitForTimeout(800);
  await takeShot('19_calendar_grid_month_view.png');

  // Switch to Week View
  console.log('  -> Chuyển sang Lưới Tuần (Week View)...');
  await page.click('#btnCalModeWeek');
  await page.waitForTimeout(600);
  await takeShot('20_calendar_grid_week_view.png');

  // Switch back to Month & Open Day Detail modal
  console.log('  -> Mở Drawer / Modal Chi Tiết Ngày Làm Việc...');
  await page.click('#btnCalModeMonth');
  await page.waitForTimeout(400);
  const cells = page.locator('.cal-cell:not(.empty)');
  if (await cells.count() > 0) {
    await cells.nth(Math.min(await cells.count() - 1, 10)).click();
    await page.waitForSelector('#calDayDetailModal.active', { timeout: 5000 });
    await page.waitForTimeout(700);
    await takeShot('21_calendar_day_detail_modal.png');
  }

  // Kết thúc & đóng context để xuất video
  console.log('\nĐang kết xuất video ghi hình phiên kiểm thử E2E...');
  const videoObj = page.video();
  await page.close();
  await context.close();
  await browser.close();

  if (videoObj) {
    const videoPath = await videoObj.path();
    const finalVideoPath = path.join(VIDEO_DIR, 'pos_nail_hybrid.webm');
    try {
      fs.copyFileSync(videoPath, finalVideoPath);
      console.log(`  -> Video đã lưu tại: ${finalVideoPath}`);
    } catch(e) {
      console.log(`  -> Video path: ${videoPath}`);
    }
  }

  console.log('\n=== TẤT CẢ CÁC BƯỚC KIỂM THỬ PLAYWRIGHT E2E ĐÃ HOÀN TẤT THÀNH CÔNG! ===');
}

main().catch(err => {
  console.error('Lỗi trong quá trình kiểm thử:', err);
  process.exit(1);
});
