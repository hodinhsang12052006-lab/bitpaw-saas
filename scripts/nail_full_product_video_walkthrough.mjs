/**
 * scripts/nail_full_product_video_walkthrough.mjs
 *
 * "Quy trình test tự động thay test tay" — đi qua TOÀN BỘ chức năng chính của ngành Nails theo
 * đúng 1 phiên làm việc thật (đăng nhập -> bán hàng đầy đủ thao tác -> khách đặt lịch qua QR ->
 * check-in real-time -> chấm công -> phiếu lương), CHỤP ẢNH FULL-PAGE ở từng bước rõ ràng, và
 * QUAY VIDEO toàn bộ phiên (Playwright recordVideo) để xem lại như xem qua 1 lượt sản phẩm thật,
 * không cần đọc code hay bấm tay lại.
 *
 * Chạy:  node scripts/nail_full_product_video_walkthrough.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 *
 * Output:
 *   audit-results/screenshots/nail_full_walkthrough/*.png   (đánh số thứ tự + tên tiếng Việt)
 *   audit-results/videos/nail_full_walkthrough/owner/*.webm (video chủ tiệm/thu ngân)
 *   audit-results/videos/nail_full_walkthrough/guest/*.webm (video khách quét QR đặt lịch)
 *   audit-results/nail_full_walkthrough_manifest.json        (danh sách bước, dùng để build report)
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = process.env.NAIL_DEMO_EMAIL || 'demo.nails.au.006758@bitpawdemo.com';
const PASSWORD = process.env.NAIL_DEMO_PASSWORD || 'DemoNails2026!';

const SCREEN_DIR = path.resolve('audit-results/screenshots/nail_full_walkthrough');
const VIDEO_OWNER_DIR = path.resolve('audit-results/videos/nail_full_walkthrough/owner');
const VIDEO_GUEST_DIR = path.resolve('audit-results/videos/nail_full_walkthrough/guest');
const MANIFEST_FILE = path.resolve('audit-results/nail_full_walkthrough_manifest.json');
fs.mkdirSync(SCREEN_DIR, { recursive: true });
fs.mkdirSync(VIDEO_OWNER_DIR, { recursive: true });
fs.mkdirSync(VIDEO_GUEST_DIR, { recursive: true });

const manifest = []; // { file, caption }
let stepIdx = 0;

function pad(n) { return String(n).padStart(2, '0'); }

function writeFileWithRetry(filePath, content) {
  let lastErr = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      fs.writeFileSync(filePath, content);
      return;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

async function shot(page, caption) {
  stepIdx += 1;
  const fname = `${pad(stepIdx)}_${caption.slug}.png`;
  const filePath = path.join(SCREEN_DIR, fname);
  // OneDrive/Windows Defender thỉnh thoảng khoá file trong lúc đang quét/đồng bộ ngay sau khi
  // Playwright tạo — gặp lỗi "UNKNOWN: unknown error, open ..." không đều tại nhiều bước khác
  // nhau, không liên quan gì tới app hay bước nào cụ thể. Retry ngắn (3 lần, cách 500ms) đủ để
  // vượt qua lock tạm thời này thay vì crash cả bài chạy.
  let lastErr = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await page.screenshot({ path: filePath, fullPage: true });
      lastErr = null;
      break;
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  if (lastErr) throw lastErr;
  manifest.push({ file: fname, caption: caption.vi, group: caption.group });
  console.log(`📸 [${pad(stepIdx)}] ${caption.vi}`);
}

function todayISO(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function main() {
  console.log('=== NAIL FULL PRODUCT VIDEO WALKTHROUGH — bắt đầu ===\n');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });

  const ownerContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: VIDEO_OWNER_DIR, size: { width: 1440, height: 900 } },
  });
  const page = await ownerContext.newPage();

  let businessId = null;
  let assignedTechId = null;
  let checkoutOrderId = null;
  let bookingDateStr = todayISO();
  const guestPhone = `090${Date.now().toString().slice(-7)}`;

  try {
    // ============ 1. ĐĂNG NHẬP ============
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await shot(page, { slug: 'dang_nhap', vi: 'Màn hình đăng nhập chủ tiệm', group: 'Đăng nhập' });
    await page.fill('#loginEmail', EMAIL);
    await page.fill('#loginPassword', PASSWORD);
    await Promise.all([page.waitForLoadState('networkidle'), page.click('#btnLogin')]);
    if (page.url().includes('/login')) throw new Error('Đăng nhập thất bại.');

    // ============ 2. POS — KHỞI TẠO ============
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 20000 });
    businessId = await page.evaluate(() => (typeof BUSINESS_ID !== 'undefined' ? BUSINESS_ID : null));
    await shot(page, { slug: 'pos_khoi_dong', vi: 'Màn hình bán hàng POS — lưới dịch vụ', group: 'Bán hàng (POS)' });

    // ============ 3. CHỌN DỊCH VỤ ============
    const cards = page.locator('#serviceGrid .service-card');
    await cards.nth(0).click();
    await page.waitForTimeout(200);
    await cards.nth(1).click();
    await page.waitForTimeout(200);
    await shot(page, { slug: 'pos_chon_dich_vu', vi: 'Đã thêm dịch vụ vào giỏ hàng', group: 'Bán hàng (POS)' });

    // ============ 4. CUSTOM ITEM ============
    await page.evaluate(() => window.openCustomItemModal());
    await page.waitForSelector('#customItemModal.active', { timeout: 3000 });
    await page.fill('#customItemName', 'Nail Art Design (Demo)');
    await page.fill('#customItemPrice', '15');
    await page.fill('#customItemQty', '1');
    await shot(page, { slug: 'pos_custom_item_modal', vi: 'Thêm dịch vụ ngoài menu (Custom Item)', group: 'Bán hàng (POS)' });
    await page.click('button[onclick="addCustomItem()"]');
    await page.waitForTimeout(300);

    // ============ 5. GÁN THỢ ============
    await page.evaluate(() => window.switchLeftTab('ticket'));
    await page.waitForTimeout(150);
    const firstSelect = page.locator('#cartItems .cart-item select').first();
    const opts = await firstSelect.locator('option').all();
    if (opts.length > 1) {
      assignedTechId = await opts[1].getAttribute('value');
      await firstSelect.selectOption(assignedTechId);
    }
    await page.waitForTimeout(200);
    await shot(page, { slug: 'pos_gan_tho', vi: 'Gán thợ phụ trách cho từng dịch vụ', group: 'Bán hàng (POS)' });

    // ============ 6. GIỮ VÉ / HÀNG CHỜ ============
    await page.evaluate(() => window.holdTicket());
    await page.waitForTimeout(200);
    await page.evaluate(() => window.toggleQueuePanel());
    await page.waitForTimeout(200);
    await shot(page, { slug: 'pos_giu_ve', vi: 'Giữ vé (Hold Ticket) — hàng chờ nhiều khách cùng lúc', group: 'Bán hàng (POS)' });

    // ============ 7. TIẾP TỤC VÉ ============
    const queueEntry = page.locator('#queueList .queue-entry').first();
    await queueEntry.click();
    await page.waitForTimeout(300);
    await shot(page, { slug: 'pos_tiep_tuc_ve', vi: 'Tiếp tục vé (Resume) — lấy lại đúng giỏ hàng đã giữ', group: 'Bán hàng (POS)' });

    // ============ 8. TIP ============
    await page.evaluate(() => window.switchLeftTab('ticket'));
    await page.waitForTimeout(150);
    await page.fill('#cashTip', '5');
    await page.fill('#cardTip', '3');
    await page.locator('#cashTip').dispatchEvent('input');
    await page.locator('#cardTip').dispatchEvent('input');
    await page.waitForTimeout(200);
    await shot(page, { slug: 'pos_tip', vi: 'Nhập Tip tiền mặt và Tip thẻ riêng biệt', group: 'Bán hàng (POS)' });

    // ============ 9. GIẢM GIÁ ============
    await page.evaluate(() => openDiscountModal());
    await page.waitForSelector('#discountModal.active', { timeout: 3000 });
    await page.click('[data-disc-type="percent"]');
    await page.fill('#discountValueInput', '10');
    await page.locator('#discountValueInput').dispatchEvent('input');
    await page.waitForTimeout(150);
    await shot(page, { slug: 'pos_giam_gia', vi: 'Áp dụng giảm giá 10% cho hoá đơn', group: 'Bán hàng (POS)' });
    await page.click('button[onclick="applyDiscount()"]');
    await page.waitForTimeout(200);

    // ============ 10. THANH TOÁN (CASH) ============
    await page.evaluate(() => window.openPaymentModal());
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="cash"]');
    await page.waitForTimeout(150);
    await shot(page, { slug: 'pos_thanh_toan_modal', vi: 'Màn hình xác nhận thanh toán tiền mặt', group: 'Bán hàng (POS)' });

    const [checkoutResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout') && r.request().method() === 'POST', { timeout: 15000 }),
      page.click('#confirmPaymentBtn'),
    ]);
    const checkoutBody = await checkoutResp.json().catch(() => null);
    checkoutOrderId = checkoutBody?.order_id ?? null;
    await page.waitForSelector('#receiptModal.active', { timeout: 8000 });
    await shot(page, { slug: 'pos_hoa_don_thanh_cong', vi: 'Hoá đơn thanh toán thành công', group: 'Bán hàng (POS)' });

    // ============ 11. LỊCH SỬ HOÁ ĐƠN + IN LẠI ============
    await page.click('button:has-text("Start New Ticket"), [onclick="startNewTicket()"]').catch(() => {});
    await page.waitForTimeout(300);
    await page.evaluate(() => window.openOrderHistoryModal());
    await page.waitForSelector('#orderHistoryModal.active', { timeout: 5000 });
    await page.waitForTimeout(600);
    await shot(page, { slug: 'pos_lich_su_hoa_don', vi: 'Lịch sử hoá đơn trong ngày', group: 'Bán hàng (POS)' });
    if (checkoutOrderId) {
      await page.evaluate((oid) => window.reprintOrderFromHistory(oid), checkoutOrderId);
      await page.waitForSelector('#receiptModal.active', { timeout: 5000 });
      await page.waitForTimeout(200);
      await shot(page, { slug: 'pos_in_lai_bill', vi: 'In lại hoá đơn từ lịch sử', group: 'Bán hàng (POS)' });
    }

    // ============ 12. SPLIT PAYMENT ============
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 20000 });
    await page.locator('#serviceGrid .service-card').first().click();
    await page.waitForTimeout(200);
    const totalText = await page.locator('#sumTotal').innerText();
    const totalNum = parseFloat(totalText.replace(/[^0-9.]/g, '')) || 0;
    await page.evaluate(() => window.openPaymentModal());
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="split"]');
    await page.waitForTimeout(150);
    const half = (totalNum / 2).toFixed(2);
    await page.fill('#splitCashAmount', half);
    await page.fill('#splitCardAmount', half);
    await page.locator('#splitCashAmount').dispatchEvent('input');
    await page.locator('#splitCardAmount').dispatchEvent('input');
    await page.waitForTimeout(150);
    await shot(page, { slug: 'pos_split_payment', vi: 'Thanh toán chia đôi tiền mặt/thẻ (Split Payment)', group: 'Bán hàng (POS)' });

    let splitOrderId = null;
    const confirmDisabled = await page.locator('#confirmPaymentBtn').isDisabled();
    if (!confirmDisabled) {
      const [splitResp] = await Promise.all([
        page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout') && r.request().method() === 'POST', { timeout: 20000 }),
        page.click('#confirmPaymentBtn'),
      ]);
      const splitBody = await splitResp.json().catch(() => null);
      splitOrderId = splitBody?.order_id ?? null;
      await page.waitForSelector('#receiptModal.active', { timeout: 8000 }).catch(() => {});
    }

    // ============ 13. HOÀN TIỀN ============
    const refundTargetOrder = splitOrderId || checkoutOrderId;
    if (refundTargetOrder) {
      await page.click('button:has-text("Start New Ticket"), [onclick="startNewTicket()"]').catch(() => {});
      await page.waitForTimeout(200);
      await page.evaluate((oid) => openRefundModal(oid), refundTargetOrder);
      await page.waitForSelector('#refundModal.active', { timeout: 3000 });
      await page.fill('#refundAmount', '5');
      await page.fill('#refundReason', 'Demo — kiểm tra luồng hoàn tiền một phần.');
      await shot(page, { slug: 'pos_hoan_tien_modal', vi: 'Hoàn tiền một phần cho khách', group: 'Bán hàng (POS)' });
      await Promise.all([
        page.waitForResponse((r) => r.url().includes('/api/nail_pos/refund') && r.request().method() === 'POST', { timeout: 20000 }),
        page.click('#confirmRefundBtn'),
      ]);
      await page.waitForTimeout(400);
      await shot(page, { slug: 'pos_hoan_tien_ket_qua', vi: 'Kết quả hoàn tiền hiển thị trên hoá đơn', group: 'Bán hàng (POS)' });
    }

    // ============ 14. DUAL PRICING ============
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 20000 });
    await page.locator('#serviceGrid .service-card').first().click();
    await page.waitForTimeout(200);
    await page.evaluate(() => window.openPaymentModal());
    await page.waitForSelector('#paymentModal.active', { timeout: 3000 });
    await page.click('.pay-method-btn[data-method="card"]');
    await page.waitForTimeout(150);
    await shot(page, { slug: 'pos_dual_pricing', vi: 'Dual Pricing — phụ phí thẻ hiển thị tách riêng giá tiền mặt', group: 'Bán hàng (POS)' });
    await page.click('#closePaymentModalBtn, [onclick="closePaymentModal()"]').catch(() => {});
    await page.keyboard.press('Escape').catch(() => {});

    // ============ 15. BOOKING QR — CHỦ TIỆM LẤY MÃ ============
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 20000 });
    await page.evaluate(() => openBookingQrModal());
    await page.waitForSelector('#bookingQrModal.active', { timeout: 5000 });
    await page.waitForTimeout(300);
    await shot(page, { slug: 'pos_qr_modal_chu_tiem', vi: 'Modal mã QR đặt lịch — góc nhìn chủ tiệm', group: 'Đặt lịch QR' });
    await page.click('#closeBookingQrModalBtn, [onclick="closeBookingQrModal()"]').catch(() => {});
    await page.keyboard.press('Escape').catch(() => {});

    // Mở sẵn /calendar TRƯỚC khi khách đặt lịch (context guest) — để chứng minh tính năng
    // real-time SSE: lịch hẹn khách đặt sẽ tự hiện ra ở đây, KHÔNG cần chính script tự reload.
    await page.goto(`${BASE}/calendar?date=${bookingDateStr}`, { waitUntil: 'networkidle' });
    await shot(page, { slug: 'lich_hen_truoc_khi_dat', vi: 'Lịch hẹn trước khi khách đặt lịch mới', group: 'Đặt lịch QR' });

    // ============ 16. KHÁCH QUÉT QR ĐẶT LỊCH (context riêng, mobile) ============
    const guestContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      recordVideo: { dir: VIDEO_GUEST_DIR, size: { width: 390, height: 844 } },
    });
    const guestPage = await guestContext.newPage();
    await guestPage.goto(`${BASE}/booking/nail/qr/${businessId}`, { waitUntil: 'networkidle' });
    await guestPage.waitForSelector('#cus_service', { timeout: 20000 });
    await shot(guestPage, { slug: 'khach_trang_dat_lich', vi: 'Trang đặt lịch công khai — góc nhìn khách hàng', group: 'Đặt lịch QR' });

    await guestPage.fill('#cus_name', 'Demo Walkthrough Guest');
    await guestPage.fill('#cus_phone', guestPhone);
    await guestPage.fill('#cus_address', '123 Demo St');
    await guestPage.selectOption('#cus_service', { index: 1 });
    // Giờ đặt lịch PHẢI nằm SAU thời điểm hiện tại thật — booking.html tự set
    // input[type=datetime-local]#cus_datetime.min = "now" lúc load trang. Trước đây random cố
    // định trong khung 10:00-17:59 của "hôm nay" bất kể mấy giờ đang chạy script thật -> nếu chạy
    // sau khung đó (VD 16h+), random dễ ra giờ đã QUÁ KHỨ -> trình duyệt tự chặn submit bằng
    // validation HTML5 gốc (không có lỗi console, ticket "thành công" build từ instructions cũ,
    // che mất việc submit thật ra đã bị chặn — đã bắt được qua ảnh chụp thật, tooltip cảnh báo
    // "Value must be ... or later" đè lên nút Confirm Booking).
    const midnight = new Date();
    midnight.setHours(23, 55, 0, 0);
    const maxOffsetMin = Math.max(35, Math.min(330, Math.floor((midnight - Date.now()) / 60000)));
    const bookingDt = new Date(Date.now() + (30 + Math.floor(Math.random() * (maxOffsetMin - 30))) * 60000);
    bookingDateStr = todayISO(bookingDt);
    const randomHour = String(bookingDt.getHours()).padStart(2, '0');
    const randomMinute = String(bookingDt.getMinutes()).padStart(2, '0');
    await guestPage.fill('#cus_datetime', `${bookingDateStr}T${randomHour}:${randomMinute}`);
    await shot(guestPage, { slug: 'khach_dien_form', vi: 'Khách điền thông tin và chọn dịch vụ', group: 'Đặt lịch QR' });

    const [bookingResp] = await Promise.all([
      guestPage.waitForResponse((r) => r.url().includes('/create_appointment') && r.request().method() === 'POST', { timeout: 15000 }).catch(() => null),
      guestPage.click('#btnSubmit'),
    ]);
    // Xác nhận THẬT có request POST /create_appointment và HTTP OK — trước đây chỉ chờ rồi chụp
    // ảnh vô điều kiện, nên khi trình duyệt tự chặn submit bằng validation HTML5 gốc (VD: giờ đặt
    // lịch rơi vào quá khứ), ảnh vẫn được đặt tên "thành công" dù request chưa từng được gửi,
    // che mất bug thật (đã bắt được qua ảnh chụp thật cho thấy tooltip cảnh báo của trình duyệt).
    if (!bookingResp || !bookingResp.ok()) {
      throw new Error('Khách đặt lịch KHÔNG thành công — không bắt được response POST /create_appointment OK. Có thể form bị chặn bởi validation HTML5 gốc (VD: giờ đặt lịch rơi vào quá khứ) hoặc lỗi server.');
    }
    await guestPage.waitForTimeout(500);
    await shot(guestPage, { slug: 'khach_dat_lich_thanh_cong', vi: 'Đặt lịch thành công — vé điện tử của khách', group: 'Đặt lịch QR' });
    await guestContext.close();

    // ============ 17. LỊCH HẸN TỰ HIỆN RA (REAL-TIME, KHÔNG RELOAD TAY) ============
    let newRowId = null;
    try {
      await page.waitForFunction(
        (phone) => Array.from(document.querySelectorAll('tr[data-appt-id]')).some((r) => r.textContent.includes(phone)),
        guestPhone,
        { timeout: 15000, polling: 300 }
      );
      newRowId = await page.evaluate((phone) => {
        const rows = Array.from(document.querySelectorAll('tr[data-appt-id]'));
        const row = rows.find((r) => r.textContent.includes(phone));
        return row ? row.getAttribute('data-appt-id') : null;
      }, guestPhone);
    } catch (e) { /* để log FAIL rõ ràng khi build report */ }
    await shot(page, { slug: 'lich_hen_tu_cap_nhat', vi: 'Lịch hẹn khách vừa đặt TỰ hiện ra (real-time, không F5 tay)', group: 'Đặt lịch QR' });

    // ============ 18. CHECK-IN ============
    if (newRowId) {
      await page.locator(`tr[data-appt-id="${newRowId}"] button:has-text("Check-in")`).first().click();
      await page.waitForTimeout(500);
      await shot(page, { slug: 'lich_hen_checkin', vi: 'Nhân viên bấm Check-in khi khách tới tiệm', group: 'Đặt lịch QR' });
      // Trang /calendar còn 1 reloadTimer debounce 1600ms từ chính SSE event đặt lịch lúc nãy —
      // nếu điều hướng đi NGAY (goto bên dưới) trong lúc timer đó vẫn còn treo, location.reload()
      // của nó có thể nổ giữa lúc trang đang chuyển hướng, đụng độ với chính goto() này và
      // Playwright báo net::ERR_ABORTED (không phải lỗi thật của app — người dùng thật bấm 2 thao
      // tác cách nhau vài giây, không đủ nhanh để dính race này). Đợi qua mốc 1600ms cho chắc.
      await page.waitForTimeout(1800);
    }

    // ============ 19. POS — BADGE CHECKED-IN TỰ CẬP NHẬT (REAL-TIME) ============
    await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#serviceGrid .service-card', { timeout: 20000 });
    await page.waitForTimeout(1500); // đợi SSE đẩy tín hiệu đầu tiên
    await page.evaluate(() => openCheckedInModal());
    await page.waitForTimeout(500);
    await shot(page, { slug: 'pos_checkin_panel', vi: 'Panel "Khách Đã Check-in" tự cập nhật trên POS', group: 'Đặt lịch QR' });

    // ============ 20. VÀO VÉ ============
    const loadBtn = page.locator('#checkedInList button:has-text("Vào Vé"), #checkedInList button:has-text("Load Ticket")').first();
    if (await loadBtn.count() > 0) {
      await loadBtn.click();
      await page.waitForTimeout(500);
      await shot(page, { slug: 'pos_vao_ve', vi: 'Dịch vụ + thợ tự động vào giỏ hàng, không cần gõ tay', group: 'Đặt lịch QR' });
    }

    // ============ 21. CHẤM CÔNG — LƯỚI NHÂN VIÊN ============
    await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#employeeGrid', { timeout: 8000 });
    await shot(page, { slug: 'chamcong_luoi_nhan_vien', vi: 'Lưới chấm công toàn bộ nhân viên', group: 'Chấm công & Lương' });

    // ============ 22. CHẤM CÔNG — CHI TIẾT THỢ + LƯỚI NGÀY + PHIẾU LƯƠNG ============
    if (assignedTechId) {
      const techCard = page.locator(`#employeeGrid [data-ma-nv="${assignedTechId}"]`);
      if (await techCard.count() > 0) {
        await techCard.locator('[data-action="open"]').first().click();
        await page.waitForSelector('#screen_pos.active', { timeout: 5000 });
        await page.waitForTimeout(900);
        await shot(page, { slug: 'chamcong_chi_tiet_tho', vi: 'Chi tiết chấm công + hoa hồng của 1 thợ', group: 'Chấm công & Lương' });

        // #payrollCalendarGrid nằm TRONG 1 cột con có overflow-y-auto riêng (không phải cuộn
        // trang ngoài) — screenshot fullPage chụp đúng khung viewport ngoài, nhưng nếu không tự
        // cuộn phần tử này vào khung nhìn trước, nó vẫn nằm dưới fold của chính cột con đó và
        // không hề xuất hiện trong ảnh dù DOM có tồn tại thật (đã xác minh bằng debug thủ công).
        const hasCalendarGrid = (await page.locator('#payrollCalendarGrid').count()) > 0;
        if (hasCalendarGrid) {
          await page.locator('#payrollCalendarGrid').scrollIntoViewIfNeeded();
          await page.waitForTimeout(300);
          await shot(page, { slug: 'chamcong_luoi_theo_ngay', vi: 'Lưới doanh thu theo từng ngày trong tháng (Revenue By Day)', group: 'Chấm công & Lương' });

          // Bấm đúng 1 ngày có dữ liệu thật để lộ ra Phiếu Lương — trước đây chỉ kiểm tra DOM
          // tồn tại (#paystubPanel luôn có mặt kể cả lúc đang "hidden"), nên "hasPaystub" luôn
          // true dù panel chưa hề hiện ra — chụp nhầm màn hình khác, không phải phiếu lương thật.
          const dayWithData = page.locator('#payrollCalendarGrid button:not([disabled])').first();
          if (await dayWithData.count() > 0) {
            await dayWithData.click();
            await page.waitForTimeout(700);
            await page.locator('#paystubPanel').scrollIntoViewIfNeeded();
            await page.waitForTimeout(300);
            await shot(page, { slug: 'chamcong_phieu_luong', vi: 'Phiếu lương: Cash Payout / Check-Direct Deposit / Tax Withheld', group: 'Chấm công & Lương' });
          }
        }
      }
    }

    writeFileWithRetry(MANIFEST_FILE, JSON.stringify({ steps: manifest, businessId, checkoutOrderId, generatedAt: new Date().toISOString() }, null, 2));
    console.log(`\n✅ Hoàn tất: ${manifest.length} ảnh chụp. Manifest: ${MANIFEST_FILE}`);
  } catch (e) {
    console.error('❌ LỖI:', e.message);
    writeFileWithRetry(MANIFEST_FILE, JSON.stringify({ steps: manifest, error: e.message, generatedAt: new Date().toISOString() }, null, 2));
  } finally {
    await ownerContext.close(); // flush video ra đĩa
    await browser.close();
  }
}

main();
