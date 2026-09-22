// scripts/exhaustive_industry_audit.mjs
// Kiểm thử cạn kiệt theo ngành nghề: quét tab phụ, nút phụ, modal, filter, form.
// Screenshot: audit-results/screenshots/<industry>/<stt>_<action>.png (stt reset mỗi ngành)
// Video: audit-results/videos/<industry>.webm (đổi tên từ file Playwright tự sinh)
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const SHOT_ROOT = 'audit-results/screenshots';
const VIDEO_DIR = 'audit-results/videos';
const MANIFEST_FILE = 'audit-results/exhaustive_manifest.json';
fs.mkdirSync(SHOT_ROOT, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

function loadManifest() {
  if (fs.existsSync(MANIFEST_FILE)) {
    try { return JSON.parse(fs.readFileSync(MANIFEST_FILE, 'utf-8')); } catch (_) { return []; }
  }
  return [];
}
function saveManifest(m) { fs.writeFileSync(MANIFEST_FILE, JSON.stringify(m, null, 2), 'utf-8'); }
let manifest = loadManifest();

let stt = 0;
function shotDir(industry) {
  const dir = path.join(SHOT_ROOT, industry);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

async function shot(page, industry, label, errBucket) {
  stt += 1;
  const fname = `${String(stt).padStart(3, '0')}_${label.replace(/[^a-zA-Z0-9_\-]/g, '_')}.png`;
  await page.waitForTimeout(350);
  try {
    await page.screenshot({ path: path.join(shotDir(industry), fname), fullPage: false });
  } catch (e) {
    console.log(`  [screenshot FAILED] ${label}: ${e.message}`);
  }
  const entry = {
    n: stt, industry, label, file: `${industry}/${fname}`, url: page.url(),
    consoleErrors: (errBucket ? errBucket.console.splice(0) : []),
    apiErrors: (errBucket ? errBucket.api.splice(0) : []),
  };
  manifest.push(entry);
  saveManifest(manifest);
  console.log(`  [shot] #${stt} ${label}`);
  return entry;
}

function attachErrorBucket(page) {
  const bucket = { console: [], api: [] };
  page.on('console', (msg) => { if (msg.type() === 'error') bucket.console.push(msg.text().slice(0, 300)); });
  page.on('response', (resp) => { if (resp.status() >= 400) bucket.api.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`); });
  page.on('dialog', async (dialog) => {
    console.log(`  [dialog] ${dialog.type()}: ${dialog.message().slice(0, 100)}`);
    // window.print() sinh ra dialog kiểu 'beforeunload' hiếm khi, nhưng để an toàn tuyệt đối
    // không treo Playwright, luôn dismiss() cho loại không phải confirm/prompt cần accept.
    if (dialog.type() === 'confirm' || dialog.type() === 'prompt') await dialog.accept();
    else await dialog.dismiss().catch(() => {});
  });
  return bucket;
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.fill('#loginEmail', email);
  await page.fill('#loginPassword', password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => null),
    page.click('#btnLogin'),
  ]);
  await page.waitForTimeout(600);
}

async function safeClick(page, selector, opts = {}) {
  const loc = typeof selector === 'string' ? page.locator(selector) : selector;
  if (await loc.count() === 0) return false;
  try {
    await loc.first().click({ force: true, timeout: 5000, ...opts });
    return true;
  } catch (e) {
    console.log(`  [click FAILED] ${typeof selector === 'string' ? selector : '(locator)'}: ${e.message.split('\n')[0]}`);
    return false;
  }
}
async function safeFill(page, selector, value) {
  const loc = page.locator(selector);
  if (await loc.count() === 0) return false;
  try { await loc.first().fill(value); return true; } catch (e) { return false; }
}

// ===================== NAIL =====================
async function flowNail(page, err) {
  const ind = 'nail';
  await login(page, 'demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!');
  await shot(page, ind, '01_after_login', err);

  await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '02_employee_list', err);

  const row = page.locator('div[data-ma-nv="NV0048"]').first();
  if (await row.count() > 0) {
    await safeClick(page, row);
    await page.waitForTimeout(500);
    await shot(page, ind, '03_commission_screen', err);

    await safeFill(page, '#ten_dv', 'SNS Dipping Powder Full Set');
    await safeFill(page, '#val_total', '75');
    await safeFill(page, '#val_split', '60');
    await page.waitForTimeout(300);
    await shot(page, ind, '04_commission_calc_live', err);

    await safeClick(page, '#btnSubmitPos');
    await page.waitForTimeout(1000);
    await shot(page, ind, '05_commission_saved', err);

    // Quay lại danh sách bằng backToList()
    await safeClick(page, 'button:has-text("Quay lại"), [onclick="backToList()"]');
    await page.waitForTimeout(500);
    await shot(page, ind, '06_back_to_list', err);
  }

  // Export CSV/PNG cho 1 nhân viên (data-action="export")
  const exportBtn = page.locator('button[data-action="export"]').first();
  if (await exportBtn.count() > 0) {
    await safeClick(page, exportBtn);
    await page.waitForTimeout(800);
    await shot(page, ind, '07_export_clicked', err);
  }

  await page.goto(`${BASE}/sell`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '08_pos_terminal', err);

  // Search dịch vụ
  const searchToggle = page.locator('[onclick*="toggleSearch"], #serviceSearchWrap, .fa-magnifying-glass').first();
  if (await searchToggle.count() > 0) await safeClick(page, searchToggle);
  const searchInput = page.locator('#serviceSearchInput');
  if (await searchInput.count() > 0) {
    await searchInput.fill('Manicure').catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, ind, '09_service_search', err);
    await searchInput.fill('').catch(() => {});
  }

  const serviceCard = page.locator('.service-card[data-service-id]').first();
  if (await serviceCard.count() > 0) {
    await safeClick(page, serviceCard);
    await page.waitForTimeout(500);
    await shot(page, ind, '10_service_added_to_ticket', err);
  }

  await safeClick(page, '.workspace-tab-btn[data-tab="turnDetails"]');
  await page.waitForTimeout(500);
  await shot(page, ind, '11_turn_details_tab', err);

  // Gán kỹ thuật viên cho dịch vụ (select trong cart-item)
  const techSelect = page.locator('#cartItems select').first();
  if (await techSelect.count() > 0) {
    const opts = await techSelect.locator('option').all();
    if (opts.length > 1) {
      const val = await opts[1].getAttribute('value');
      await techSelect.selectOption(val).catch(() => {});
      await page.waitForTimeout(300);
      await shot(page, ind, '12_technician_assigned', err);
    }
  }

  await safeClick(page, '.workspace-tab-btn[data-tab="closeTicket"]');
  await page.waitForTimeout(500);
  await shot(page, ind, '13_close_ticket_tab', err);

  const checkoutBtn = page.locator('#checkoutBtn');
  if (await checkoutBtn.count() > 0 && !(await checkoutBtn.isDisabled())) {
    await safeClick(page, checkoutBtn);
    await page.waitForTimeout(600);
    await shot(page, ind, '14_payment_modal', err);

    // Thử tab Chia đôi (split) để xem form phụ
    const splitTile = page.locator('.pay-method-btn[data-method="split"]');
    if (await splitTile.count() > 0) {
      await safeClick(page, splitTile);
      await page.waitForTimeout(300);
      await shot(page, ind, '15_payment_split_view', err);
      await safeClick(page, '.pay-method-btn[data-method="cash"]');
      await page.waitForTimeout(300);
    }

    const confirmPay = page.locator('#confirmPaymentBtn');
    if (await confirmPay.count() > 0 && !(await confirmPay.isDisabled())) {
      await safeClick(page, confirmPay);
      await page.waitForTimeout(1500);
      await shot(page, ind, '16_payment_confirmed_receipt', err);
    }
  }

  await page.goto(`${BASE}/customers`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '17_customers_list', err);
  const custSearch = page.locator('input[placeholder*="Tên"], input[placeholder*="Name"]').first();
  if (await custSearch.count() > 0) {
    await custSearch.fill('a').catch(() => {});
    await page.waitForTimeout(500);
    await shot(page, ind, '18_customers_search', err);
  }

  await page.goto(`${BASE}/staff`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '19_staff_list', err);
}

// ===================== SPA =====================
async function flowSpa(page, err) {
  const ind = 'spa';
  await login(page, 'demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/spa`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '01_catalog', err);

  const catFilter = page.locator('#categoryFilter');
  if (await catFilter.count() > 0) {
    const opts = await catFilter.locator('option').all();
    if (opts.length > 1) {
      const val = await opts[1].getAttribute('value');
      await catFilter.selectOption(val).catch(() => {});
      await page.waitForTimeout(400);
      await shot(page, ind, '02_category_filter', err);
      await catFilter.selectOption('all').catch(() => {});
    }
  }
  const searchInput = page.locator('#searchInput');
  if (await searchInput.count() > 0) {
    await searchInput.fill('Facial').catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, ind, '03_search', err);
    await searchInput.fill('').catch(() => {});
  }

  const addBtns = page.locator('.btn-add-cart');
  const addCount = await addBtns.count();
  if (addCount > 0) { await safeClick(page, addBtns.nth(0)); await page.waitForTimeout(400); }
  if (addCount > 1) { await safeClick(page, addBtns.nth(1)); await page.waitForTimeout(400); }
  await shot(page, ind, '04_two_items_added', err);

  await safeClick(page, '#cartIcon');
  await page.waitForTimeout(500);
  await shot(page, ind, '05_cart_open', err);

  const incrBtn = page.locator('.cart-qty-btn, .qty-control .incr, .cart-qty-up').first();
  if (await incrBtn.count() > 0) { await safeClick(page, incrBtn); await page.waitForTimeout(300); await shot(page, ind, '06_qty_increased', err); }

  const removeBtn = page.locator('.cart-remove-btn').first();
  if (await removeBtn.count() > 0) { await safeClick(page, removeBtn); await page.waitForTimeout(300); await shot(page, ind, '07_item_removed', err); }

  await safeClick(page, '#openCheckoutModalBtn');
  await page.waitForTimeout(600);
  await shot(page, ind, '08_checkout_modal', err);

  for (const method of ['stripe', 'vnpay', 'momo', 'cash']) {
    const tile = page.locator(`.payment-method[data-method="${method}"]`);
    if (await tile.count() > 0) {
      await safeClick(page, tile);
      await page.waitForTimeout(300);
      await shot(page, ind, `09_payment_method_${method}`, err);
    }
  }
  await safeClick(page, '.payment-method[data-method="cash"]');
  await safeFill(page, '#custName', 'Test Customer');
  await page.waitForTimeout(300);
  await safeClick(page, '#finalPayBtn');
  await page.waitForTimeout(1500);
  await shot(page, ind, '10_payment_result', err);

  await page.goto(`${BASE}/add_spa`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  await shot(page, ind, '11_add_service_form', err);
  await safeFill(page, '#spaName', 'Audit Test Facial');
  await safeFill(page, '#priceDisplay', '55');
  await page.waitForTimeout(300);
  await safeClick(page, '#submitBtn');
  await page.waitForTimeout(1200);
  await shot(page, ind, '12_service_added', err);

  // Xoá dịch vụ vừa tạo (delete link có confirm dialog)
  const delLink = page.locator(`a[href*="delete_spa"]`, { hasText: '' }).filter({ has: page.locator('xpath=..') });
  const deleteLinks = page.locator('a[href*="delete_spa"]');
  if (await deleteLinks.count() > 0) {
    await safeClick(page, deleteLinks.last());
    await page.waitForTimeout(1000);
    await shot(page, ind, '13_service_deleted', err);
  }

  await page.goto(`${BASE}/chamcong/spa`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '14_chamcong_spa', err);
}

// ===================== FNB =====================
async function flowFnb(page, err) {
  const ind = 'fnb';
  await login(page, 'demo.fnb.515732@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/pos`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, ind, '01_table_grid', err);

  await safeFill(page, '#newTableName', 'Bàn Audit Test');
  await safeClick(page, '#addTableBtn');
  await page.waitForTimeout(1000);
  await shot(page, ind, '02_table_added', err);

  const table = page.locator('.table-item').first();
  await safeClick(page, table);
  await page.waitForTimeout(600);
  await shot(page, ind, '03_table_selected', err);

  // Xem QR / copy link / in QR trên 1 bàn khác
  const qrBtn = page.locator('[onclick*="viewQR"]').first();
  if (await qrBtn.count() > 0) {
    await safeClick(page, qrBtn);
    await page.waitForTimeout(600);
    await shot(page, ind, '04_qr_modal', err);
    await page.keyboard.press('Escape').catch(() => {});
    await safeClick(page, 'body');
  }

  const menuCard = page.locator('#menuGrid .glass-card[data-product-id]').first();
  await safeClick(page, menuCard);
  await page.waitForTimeout(500);
  await shot(page, ind, '05_order_modal', err);
  await safeClick(page, '#increaseQty');
  await page.waitForTimeout(200);
  await shot(page, ind, '06_qty_increased_in_modal', err);
  await safeClick(page, '#confirmOrderBtn');
  await page.waitForTimeout(800);
  await shot(page, ind, '07_item_added_to_order', err);

  // Thêm món khác nữa
  const menuCard2 = page.locator('#menuGrid .glass-card[data-product-id]').nth(1);
  await safeClick(page, menuCard2);
  await page.waitForTimeout(400);
  await safeClick(page, '#confirmOrderBtn');
  await page.waitForTimeout(800);
  await shot(page, ind, '08_second_item_added', err);

  // Áp dụng tip 18%
  await safeClick(page, '.tip-btn[data-tip-percent="18"]');
  await page.waitForTimeout(300);
  await shot(page, ind, '09_tip_applied', err);

  await safeClick(page, '#posCheckoutBtn');
  await page.waitForTimeout(1500);
  await shot(page, ind, '10_checkout_result', err);

  // Trang khách tự order qua QR (dùng bàn vừa test)
  await page.goto(`${BASE}/table/5704`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '11_customer_qr_order_view', err);
  const addToCartBtn = page.locator('.add-to-cart-btn').first();
  await safeClick(page, addToCartBtn);
  await page.waitForTimeout(400);
  await shot(page, ind, '12_customer_added_to_cart', err);
  await safeClick(page, '#cartButton');
  await page.waitForTimeout(400);
  await shot(page, ind, '13_customer_cart_open', err);

  const callStaffBtn = page.locator('#callStaffBtn');
  if (await callStaffBtn.count() > 0) {
    await safeClick(page, callStaffBtn);
    await page.waitForTimeout(500);
    await shot(page, ind, '14_call_staff_clicked', err);
  }
  const submitOrderBtn = page.locator('#submitOrderBtn');
  if (await submitOrderBtn.count() > 0) {
    await safeClick(page, submitOrderBtn);
    await page.waitForTimeout(1000);
    await shot(page, ind, '15_customer_order_submitted', err);
  }

  await page.goto(`${BASE}/kitchen_display`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '16_kitchen_display', err);

  await page.goto(`${BASE}/reservations`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '17_table_reservations_admin', err);
}

// ===================== RETAIL =====================
async function flowRetail(page, err) {
  const ind = 'retail';
  await login(page, 'demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/retail_pos`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '01_product_grid', err);

  const catFilter = page.locator('#categoryFilter');
  if (await catFilter.count() > 0) {
    const opts = await catFilter.locator('option').all();
    if (opts.length > 1) {
      const val = await opts[1].getAttribute('value');
      await catFilter.selectOption(val).catch(() => {});
      await page.waitForTimeout(400);
      await shot(page, ind, '02_category_filter', err);
      await catFilter.selectOption('all').catch(() => {});
    }
  }
  const searchInput = page.locator('#searchInput');
  if (await searchInput.count() > 0) {
    await searchInput.fill('Coca').catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, ind, '03_search', err);
    await searchInput.fill('').catch(() => {});
  }

  const cards = page.locator('.product-card:not(.out-of-stock)');
  if (await cards.count() > 0) { await safeClick(page, cards.nth(0)); await page.waitForTimeout(300); }
  if (await cards.count() > 1) { await safeClick(page, cards.nth(1)); await page.waitForTimeout(300); }
  await shot(page, ind, '04_items_added', err);

  await safeClick(page, '#cartIcon');
  await page.waitForTimeout(500);
  await shot(page, ind, '05_cart_open', err);

  const qtyPlus = page.locator('.cart-qty-btn[data-delta="1"]').first();
  if (await qtyPlus.count() > 0) { await safeClick(page, qtyPlus); await page.waitForTimeout(300); await shot(page, ind, '06_qty_increased', err); }

  await safeClick(page, '#openCheckoutBtn');
  await page.waitForTimeout(600);
  await shot(page, ind, '07_checkout_modal', err);
  await safeClick(page, '.pm-option[data-method="bank"]');
  await page.waitForTimeout(300);
  await shot(page, ind, '08_payment_method_bank', err);
  await safeClick(page, '.pm-option[data-method="cash"]');
  await safeClick(page, '#confirmCheckoutBtn');
  await page.waitForTimeout(1800);
  await shot(page, ind, '09_checkout_done', err);

  // Mở modal Hoàn tiền (Refund) qua Management dropdown
  const mgmtBtn = page.locator('#mgmtMenuWrap, [onclick*="toggleMgmtMenu"]').first();
  if (await mgmtBtn.count() > 0) {
    await safeClick(page, mgmtBtn);
    await page.waitForTimeout(300);
    await shot(page, ind, '10_management_dropdown', err);
    const refundLink = page.locator('[onclick*="openRefundModal"]');
    if (await refundLink.count() > 0) {
      await safeClick(page, refundLink);
      await page.waitForTimeout(500);
      await shot(page, ind, '11_refund_modal', err);
      await safeClick(page, '#cancelRefundBtn');
      await page.waitForTimeout(300);
    }
  }

  await page.goto(`${BASE}/add`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  await shot(page, ind, '12_add_product_form', err);
  await safeFill(page, '#productName', 'Audit Test Product 2');
  await safeFill(page, '#priceDisplay', '15000');
  await safeFill(page, '#productStock', '50');
  await page.waitForTimeout(300);
  await safeClick(page, '#submitBtn');
  await page.waitForTimeout(1200);
  await shot(page, ind, '13_product_added_result', err);
}

// ===================== KARAOKE =====================
async function flowKaraoke(page, err) {
  const ind = 'karaoke';
  await login(page, 'demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/karaoke`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, ind, '01_room_grid', err);

  const startBtn = page.locator('.start-room').first();
  await safeClick(page, startBtn);
  await page.waitForTimeout(1000);
  await shot(page, ind, '02_room_started', err);

  const checkoutBtn = page.locator('.checkout-room').first();
  await safeClick(page, checkoutBtn);
  await page.waitForTimeout(600);
  await shot(page, ind, '03_checkout_modal', err);
  await safeFill(page, '#custPhone', '0912345678');
  await page.waitForTimeout(300);
  await shot(page, ind, '04_phone_filled', err);
  await safeClick(page, '#confirmCheckoutBtn');
  await page.waitForTimeout(1200);
  await shot(page, ind, '05_checkout_done', err);

  await page.goto(`${BASE}/karaoke/reservations`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '06_reservations_list', err);

  const copyLinkBtn = page.locator('[onclick*="copyLink"]');
  if (await copyLinkBtn.count() > 0) {
    await safeClick(page, copyLinkBtn);
    await page.waitForTimeout(300);
    await shot(page, ind, '07_copy_link_clicked', err);
  }

  const row = page.locator('tr[data-res-id]').first();
  if (await row.count() > 0) {
    const approveBtn = row.locator('button', { hasText: 'Duyệt' });
    if (await approveBtn.count() > 0) {
      await safeClick(page, approveBtn);
      await page.waitForTimeout(800);
      await shot(page, ind, '08_reservation_approved', err);
    }
  } else {
    console.log('  [INFO] Không có reservation nào để test duyệt/huỷ');
  }
}

// ===================== HOTEL =====================
async function flowHotel(page, err) {
  const ind = 'hotel';
  await login(page, 'demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/hotel_rooms`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, ind, '01_room_grid', err);

  const emptyRoom = page.locator('.room-card.status-trong').first();
  if (await emptyRoom.count() > 0) {
    await safeClick(page, emptyRoom);
    await page.waitForTimeout(600);
    await shot(page, ind, '02_checkin_modal', err);
    await safeFill(page, '#guestName', 'Audit Test Guest 2');
    await safeFill(page, '#guestPhone', '0911111111');
    await page.waitForTimeout(300);
    await safeClick(page, '[onclick="submitCheckin()"]');
    await page.waitForTimeout(1200);
    await shot(page, ind, '03_checked_in', err);
  }

  const occupiedRoom = page.locator('.room-card.status-occupied').first();
  if (await occupiedRoom.count() > 0) {
    // Thêm phụ thu trước khi trả phòng
    const addChargeBtn = occupiedRoom.locator('[onclick*="openAddChargeModal"]');
    if (await addChargeBtn.count() > 0) {
      await safeClick(page, addChargeBtn);
      await page.waitForTimeout(500);
      await shot(page, ind, '04_add_charge_modal', err);
      await safeFill(page, '#newChargeDesc', 'Minibar');
      await safeFill(page, '#newChargeAmount', '50000');
      await page.waitForTimeout(300);
      await safeClick(page, '[onclick="submitAddCharge()"]');
      await page.waitForTimeout(1000);
      await shot(page, ind, '05_charge_added', err);
    }

    await safeClick(page, occupiedRoom);
    await page.waitForTimeout(600);
    await shot(page, ind, '06_checkout_summary_with_charge', err);
    await safeClick(page, '#confirmCheckoutBtn');
    await page.waitForTimeout(1200);
    await shot(page, ind, '07_checkout_done', err);
  }

  const dirtyRoom = page.locator('.room-card.status-dirty').first();
  if (await dirtyRoom.count() > 0) {
    const cleanBtn = dirtyRoom.locator('[onclick*="markClean"]');
    await safeClick(page, cleanBtn);
    await page.waitForTimeout(800);
    await shot(page, ind, '08_marked_clean', err);
  }

  // Modal Thêm phòng (admin) — chỉ mở xem, không lưu để tránh tạo rác dữ liệu thật
  const addRoomBtn = page.locator('[onclick="openAddRoomModal()"]');
  if (await addRoomBtn.count() > 0) {
    await safeClick(page, addRoomBtn);
    await page.waitForTimeout(500);
    await shot(page, ind, '09_add_room_modal', err);
    await safeClick(page, '[onclick="closeModal(\'addRoomModal\')"]');
  }

  const bulkRateBtn = page.locator('[onclick="openBulkRateModal()"]');
  if (await bulkRateBtn.count() > 0) {
    await safeClick(page, bulkRateBtn);
    await page.waitForTimeout(500);
    await shot(page, ind, '10_bulk_rate_modal', err);
    await safeClick(page, '[onclick="closeModal(\'bulkRateModal\')"]');
  }

  await page.goto(`${BASE}/hotel/reservations`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '11_reservations_list', err);
}

// ===================== PRODUCTION =====================
async function flowProduction(page, err) {
  const ind = 'production';
  await login(page, 'demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/production_output`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, ind, '01_initial', err);

  const workerSelect = page.locator('#logWorker');
  if (await workerSelect.count() > 0) {
    const opts = await workerSelect.locator('option').all();
    if (opts.length > 1) await workerSelect.selectOption(await opts[1].getAttribute('value')).catch(() => {});
  }
  await safeFill(page, '#logStage', 'Đóng gói');
  await safeFill(page, '#logQty', '15');
  const shiftSelect = page.locator('#logShift');
  if (await shiftSelect.count() > 0) {
    const opts = await shiftSelect.locator('option').all();
    if (opts.length > 1) await shiftSelect.selectOption(await opts[1].getAttribute('value')).catch(() => {});
  }
  await page.waitForTimeout(300);
  await shot(page, ind, '02_form_filled', err);
  await safeClick(page, 'button[onclick="submitOutput()"]');
  await page.waitForTimeout(1200);
  await shot(page, ind, '03_logged', err);

  const dateFilter = page.locator('#filterDate');
  if (await dateFilter.count() > 0) {
    await dateFilter.fill('2026-09-01').catch(() => {});
    await page.waitForTimeout(500);
    await shot(page, ind, '04_date_filter_applied', err);
  }

  await page.goto(`${BASE}/production/materials`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '05_materials_page', err);

  await safeFill(page, '#newMaterialName', 'Vải Cotton');
  await safeFill(page, '#newMaterialUnit', 'm');
  await page.waitForTimeout(200);
  await shot(page, ind, '06_add_material_filled', err);
  const addMatBtn = page.locator('button', { hasText: /THÊM NVL/i });
  await safeClick(page, addMatBtn);
  await page.waitForTimeout(1000);
  await shot(page, ind, '07_material_added', err);
}

// ===================== TECHNICAL =====================
async function flowTechnical(page, err) {
  const ind = 'technical';
  await login(page, 'demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/chamcong/kythuat`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '01_attendance', err);

  await page.goto(`${BASE}/technical/parts`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '02_parts_list', err);
  await safeFill(page, '#newPartName', 'Audit Bearing 2');
  await safeFill(page, '#newPartStock', '8');
  await safeFill(page, '#newPartPrice', '50000');
  await page.waitForTimeout(300);
  await safeClick(page, 'button[onclick="addPart()"]');
  await page.waitForTimeout(1000);
  await shot(page, ind, '03_part_added', err);

  const newRow = page.locator('.row-card', { hasText: 'Audit Bearing 2' }).first();
  if (await newRow.count() > 0) {
    const restockInput = newRow.locator('input[id^="restock-"]');
    if (await restockInput.count() > 0) {
      await restockInput.fill('3').catch(() => {});
      await page.waitForTimeout(200);
      const restockBtn = newRow.locator('.btn-mini').first();
      await safeClick(page, restockBtn);
      await page.waitForTimeout(800);
      await shot(page, ind, '04_part_restocked', err);
    }
    const deleteBtn = newRow.locator('.btn-mini', { hasText: /Xoá|Delete/i });
    await safeClick(page, deleteBtn);
    await page.waitForTimeout(1000);
    await shot(page, ind, '05_part_deleted', err);
  }

  // Điều phối KTV (dispatch): quanly_dichvu -> Tạo lệnh + gán KTV
  await page.goto(`${BASE}/quanly_dichvu`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '06_dispatch_service_page', err);
  const addJobBtn = page.locator('button, div', { hasText: /THÊM MÓN|DỊCH VỤ MỚI/i }).first();
  if (await addJobBtn.count() > 0) {
    await safeClick(page, addJobBtn);
    await page.waitForTimeout(500);
    await shot(page, ind, '07_add_job_area', err);
  }

  await page.goto(`${BASE}/quanly_kho`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '08_dispatch_materials_page', err);

  await page.goto(`${BASE}/map_dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, ind, '09_gps_dispatch_radar', err);
}

// ===================== OFFICE =====================
async function flowOffice(page, err) {
  const ind = 'office';
  await login(page, 'demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/chamcong/vanphong`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, ind, '01_attendance_grid', err);

  await safeClick(page, '[onclick="markAllPresent()"]');
  await page.waitForTimeout(600);
  await shot(page, ind, '02_mark_all_present', err);

  const saveBtns = page.locator('button[id^="btn_"]');
  const saveCount = await saveBtns.count();
  for (let i = 0; i < Math.min(saveCount, 2); i++) {
    await safeClick(page, saveBtns.nth(i));
    await page.waitForTimeout(700);
  }
  await shot(page, ind, '03_rows_saved', err);

  // Xin phép siêu tốc
  const npSelect = page.locator('#nv_xin_phep');
  if (await npSelect.count() > 0) {
    const opts = await npSelect.locator('option').all();
    if (opts.length > 1) await npSelect.selectOption(await opts[1].getAttribute('value')).catch(() => {});
  }
  await safeFill(page, '#ly_do_nghi', 'Khám bệnh');
  await page.waitForTimeout(300);
  await shot(page, ind, '04_quick_leave_form_filled', err);
  await safeClick(page, '[onclick="duyetNghiPhep()"]');
  await page.waitForTimeout(1000);
  await shot(page, ind, '05_quick_leave_approved', err);

  await page.goto(`${BASE}/leave_requests`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '06_leave_requests_pending_tab', err);
  await safeClick(page, '.filter-tab[data-status="approved"]');
  await page.waitForTimeout(500);
  await shot(page, ind, '07_leave_requests_approved_tab', err);
  await safeClick(page, '.filter-tab[data-status="all"]');
  await page.waitForTimeout(500);
  await shot(page, ind, '08_leave_requests_all_tab', err);

  await page.goto(`${BASE}/expense_requests`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, ind, '09_expense_requests', err);
}

const FLOWS = {
  nail: flowNail, spa: flowSpa, fnb: flowFnb, retail: flowRetail,
  karaoke: flowKaraoke, hotel: flowHotel, production: flowProduction,
  technical: flowTechnical, office: flowOffice,
};

async function main() {
  const industry = process.argv[2];
  const flow = FLOWS[industry];
  if (!flow) {
    console.error(`Usage: node exhaustive_industry_audit.mjs <${Object.keys(FLOWS).join('|')}>`);
    process.exit(1);
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    locale: 'vi-VN',
    recordVideo: { dir: VIDEO_DIR, size: { width: 1366, height: 768 } },
  });
  const page = await context.newPage();
  const err = attachErrorBucket(page);

  try {
    await flow(page, err);
  } catch (e) {
    console.error(`FLOW ERROR (${industry}):`, e.message);
    await shot(page, industry, 'ERROR_STATE', err).catch(() => {});
  }

  const videoObj = page.video();
  await context.close();
  await browser.close();

  // Đổi tên file video Playwright tự sinh (hash ngẫu nhiên) -> <industry>.webm
  if (videoObj) {
    try {
      const autoPath = await videoObj.path();
      const target = path.join(VIDEO_DIR, `${industry}.webm`);
      if (fs.existsSync(target)) fs.unlinkSync(target);
      fs.renameSync(autoPath, target);
      console.log(`  [video] -> ${target}`);
    } catch (e) {
      console.log(`  [video RENAME FAILED] ${e.message}`);
    }
  }

  console.log(`\n=== ${industry} flow done. Total shots so far: ${stt} ===`);
}

main();
