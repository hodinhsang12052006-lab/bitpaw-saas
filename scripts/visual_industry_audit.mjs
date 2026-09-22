// scripts/visual_industry_audit.mjs
// Click-through THẬT theo từng bước nghiệp vụ của từng ngành nghề (không chỉ mở trang).
// Chụp ảnh SAU MỖI HÀNH ĐỘNG, quay video toàn phiên, để Claude tự xem ảnh (vision inspection)
// sau khi chạy xong — script này KHÔNG tự phán đúng/sai giao diện, chỉ thu thập bằng chứng.
//
// Cách dùng: node scripts/visual_industry_audit.mjs <industry_code>
//   node scripts/visual_industry_audit.mjs nail
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const SHOT_DIR = 'audit-results/screenshots';
const VIDEO_DIR = 'audit-results/videos';
const MANIFEST_FILE = 'audit-results/visual_manifest.json';
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

function loadManifest() {
  if (fs.existsSync(MANIFEST_FILE)) {
    try { return JSON.parse(fs.readFileSync(MANIFEST_FILE, 'utf-8')); } catch (_) { return []; }
  }
  return [];
}
function saveManifest(m) {
  fs.writeFileSync(MANIFEST_FILE, JSON.stringify(m, null, 2), 'utf-8');
}

let manifest = loadManifest();
let stepCounter = manifest.length;

async function shot(page, industry, label, errBucket) {
  stepCounter += 1;
  const fname = `V${String(stepCounter).padStart(3, '0')}_${industry}_${label.replace(/[^a-zA-Z0-9_\-]/g, '_')}.png`;
  await page.waitForTimeout(400);
  try {
    await page.screenshot({ path: path.join(SHOT_DIR, fname), fullPage: false });
  } catch (e) {
    console.log(`  [screenshot FAILED] ${label}: ${e.message}`);
  }
  const entry = {
    n: stepCounter, industry, label, file: fname,
    url: page.url(),
    consoleErrors: (errBucket ? errBucket.console.splice(0) : []),
    apiErrors: (errBucket ? errBucket.api.splice(0) : []),
  };
  manifest.push(entry);
  saveManifest(manifest);
  console.log(`  [shot] #${stepCounter} ${label} -> ${fname}`);
}

function attachErrorBucket(page) {
  const bucket = { console: [], api: [] };
  page.on('console', (msg) => { if (msg.type() === 'error') bucket.console.push(msg.text().slice(0, 300)); });
  page.on('response', (resp) => { if (resp.status() >= 400) bucket.api.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`); });
  page.on('dialog', async (dialog) => { console.log(`  [dialog] ${dialog.type()}: ${dialog.message().slice(0, 100)}`); await dialog.accept(); });
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

// ===================== FLOWS THEO NGÀNH NGHỀ =====================

async function flowNail(page, err) {
  const email = 'demo.nails.au.006758@bitpawdemo.com', pass = 'DemoNails2026!';
  await login(page, email, pass);
  await shot(page, 'nail', '01_after_login', err);

  await page.goto(`${BASE}/chamcong/nail`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'nail', '02_employee_list', err);

  const row = page.locator('div[data-ma-nv="NV0048"]').first();
  if (await row.count() > 0) {
    await row.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'nail', '03_commission_screen', err);

    await page.fill('#ten_dv', 'SNS Dipping Powder Full Set').catch(() => {});
    await page.fill('#val_total', '75').catch(() => {});
    await page.fill('#val_split', '60').catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, 'nail', '04_commission_filled', err);

    const submitBtn = page.locator('#btnSubmitPos');
    if (await submitBtn.count() > 0) {
      await submitBtn.click({ force: true });
      await page.waitForTimeout(1200);
      await shot(page, 'nail', '05_commission_saved', err);
    }
  } else {
    console.log('  [WARN] Không tìm thấy nhân viên NV0048 trong danh sách');
  }

  // /sell cho ngành nail render pos_nail.html (POS Terminal riêng), KHÔNG phải sell.html
  // chung (đã xác nhận qua vision inspection lần chạy trước — không phải bug, là route theo
  // ngành, xem app.py: sell() trả về pos_nail.html khi business_mode == 'nail').
  await page.goto(`${BASE}/sell`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'nail', '06_pos_terminal', err);

  const serviceCard = page.locator('.service-card[data-service-id]').first();
  if (await serviceCard.count() > 0) {
    await serviceCard.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'nail', '07_service_added_to_ticket', err);

    // Quy trình thật của nail POS: Service (thêm dịch vụ) -> Turn Details (gán KTV cho từng
    // dịch vụ, phục vụ tính tua) -> Close Ticket (thuế/tip/khách hàng + nút thanh toán thật).
    // #checkoutBtn/tổng tiền nằm ở tab Close Ticket, KHÔNG phải Turn Details.
    const turnDetailsTab = page.locator('.workspace-tab-btn[data-tab="turnDetails"]');
    if (await turnDetailsTab.count() > 0) {
      await turnDetailsTab.click({ force: true });
      await page.waitForTimeout(500);
      await shot(page, 'nail', '07b_turn_details_tab', err);
    }
    const closeTicketTab = page.locator('.workspace-tab-btn[data-tab="closeTicket"]');
    if (await closeTicketTab.count() > 0) {
      await closeTicketTab.click({ force: true });
      await page.waitForTimeout(500);
      await shot(page, 'nail', '07c_close_ticket_tab', err);
    }

    const checkoutBtn = page.locator('#checkoutBtn');
    if (await checkoutBtn.count() > 0 && !(await checkoutBtn.isDisabled())) {
      // #checkoutBtn có animation CSS liên tục (glow pulse khi enabled, cố ý thu hút chú ý) khiến
      // Playwright coi là "not stable" -> phải click({force:true}) để bỏ qua actionability check.
      await checkoutBtn.click({ force: true });
      await page.waitForTimeout(600);
      await shot(page, 'nail', '08_payment_modal', err);

      const confirmPay = page.locator('#confirmPaymentBtn');
      if (await confirmPay.count() > 0 && !(await confirmPay.isDisabled())) {
        await confirmPay.click({ force: true });
        await page.waitForTimeout(1500);
        await shot(page, 'nail', '09_payment_confirmed', err);
      }
    }
  } else {
    console.log('  [WARN] Không tìm thấy service-card trong POS Terminal nail');
  }

  await page.goto(`${BASE}/customers`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'nail', '08_customers', err);
}

async function flowSpa(page, err) {
  const email = 'demo.spa.596348@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/spa`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'spa', '01_catalog', err);

  const addBtn = page.locator('.btn-add-cart').first();
  if (await addBtn.count() > 0) {
    await addBtn.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'spa', '02_added_to_cart', err);
  }

  const cartIcon = page.locator('#cartIcon');
  if (await cartIcon.count() > 0) {
    await cartIcon.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'spa', '03_cart_open', err);
  }

  const checkoutOpenBtn = page.locator('#openCheckoutModalBtn');
  if (await checkoutOpenBtn.count() > 0) {
    await checkoutOpenBtn.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'spa', '04_checkout_modal', err);

    const cashTile = page.locator('.payment-method[data-method="cash"]').first();
    if (await cashTile.count() > 0) await cashTile.click({ force: true });
    await page.fill('#custName', 'Test Customer').catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, 'spa', '05_payment_form_filled', err);

    const payBtn = page.locator('#finalPayBtn');
    if (await payBtn.count() > 0) {
      await payBtn.click({ force: true });
      await page.waitForTimeout(1500);
      await shot(page, 'spa', '06_payment_result', err);
    }
  }

  await page.goto(`${BASE}/add_spa`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  await shot(page, 'spa', '07_add_service_form', err);
  await page.fill('#spaName', 'Audit Test Facial').catch(() => {});
  await page.fill('#priceDisplay', '50').catch(() => {});
  await page.waitForTimeout(300);
  await shot(page, 'spa', '08_add_service_filled', err);
  const spaSubmit = page.locator('#submitBtn');
  if (await spaSubmit.count() > 0) {
    await spaSubmit.click({ force: true });
    await page.waitForTimeout(1200);
    await shot(page, 'spa', '09_service_added_result', err);
  }
}

async function flowFnb(page, err) {
  const email = 'demo.fnb.515732@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/pos`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'fnb', '01_table_grid', err);

  const table = page.locator('.table-item[data-table-id="5704"]').first();
  if (await table.count() > 0) {
    await table.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'fnb', '02_table_selected', err);

    const menuCard = page.locator('#menuGrid .glass-card[data-product-id]').first();
    if (await menuCard.count() > 0) {
      await menuCard.click({ force: true });
      await page.waitForTimeout(500);
      await shot(page, 'fnb', '03_order_modal', err);

      const confirmBtn = page.locator('#confirmOrderBtn');
      if (await confirmBtn.count() > 0) {
        await confirmBtn.click({ force: true });
        await page.waitForTimeout(800);
        await shot(page, 'fnb', '04_item_added_to_order', err);
      }
    }

    const checkoutBtn = page.locator('#posCheckoutBtn');
    if (await checkoutBtn.count() > 0) {
      await checkoutBtn.click({ force: true });
      await page.waitForTimeout(1500);
      await shot(page, 'fnb', '05_checkout_result', err);
    }
  } else {
    console.log('  [WARN] Không tìm thấy bàn 5704');
  }

  await page.goto(`${BASE}/table/5704`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'fnb', '06_customer_order_view', err);

  const addToCartBtn = page.locator('.add-to-cart-btn').first();
  if (await addToCartBtn.count() > 0) {
    await addToCartBtn.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'fnb', '07_customer_added_to_cart', err);
  }
  const cartButton = page.locator('#cartButton');
  if (await cartButton.count() > 0) {
    await cartButton.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'fnb', '08_customer_cart_open', err);
  }

  await page.goto(`${BASE}/kitchen_display`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'fnb', '09_kitchen_display', err);
}

async function flowRetail(page, err) {
  const email = 'demo.retail.596348@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/retail_pos`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'retail', '01_product_grid', err);

  const card = page.locator('.product-card:not(.out-of-stock)').first();
  if (await card.count() > 0) {
    await card.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'retail', '02_added_to_cart', err);
  }

  const cartIcon = page.locator('#cartIcon');
  if (await cartIcon.count() > 0) {
    await cartIcon.click({ force: true });
    await page.waitForTimeout(500);
    await shot(page, 'retail', '03_cart_open', err);
  }

  const openCheckout = page.locator('#openCheckoutBtn');
  if (await openCheckout.count() > 0) {
    await openCheckout.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'retail', '04_checkout_modal', err);

    const cashTile = page.locator('.pm-option[data-method="cash"]').first();
    if (await cashTile.count() > 0) await cashTile.click({ force: true });
    await page.waitForTimeout(300);
    await shot(page, 'retail', '05_payment_selected', err);

    const confirmBtn = page.locator('#confirmCheckoutBtn');
    if (await confirmBtn.count() > 0) {
      await confirmBtn.click({ force: true });
      await page.waitForTimeout(1800);
      await shot(page, 'retail', '06_checkout_done', err);
    }
  }

  await page.goto(`${BASE}/add`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  await shot(page, 'retail', '07_add_product_form', err);
  await page.fill('#productName', 'Audit Test Product').catch(() => {});
  const catSelect = page.locator('#productCategory');
  if (await catSelect.count() > 0) {
    const options = await catSelect.locator('option').all();
    if (options.length > 1) {
      const val = await options[1].getAttribute('value');
      await catSelect.selectOption(val);
    }
  }
  await page.fill('#priceDisplay', '19.99').catch(() => {});
  await page.waitForTimeout(300);
  await shot(page, 'retail', '08_add_product_filled', err);
  const prodSubmit = page.locator('#submitBtn');
  if (await prodSubmit.count() > 0) {
    await prodSubmit.click({ force: true });
    await page.waitForTimeout(1200);
    await shot(page, 'retail', '09_product_added_result', err);
  }
}

async function flowKaraoke(page, err) {
  const email = 'demo.karaoke.071443@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/karaoke`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, 'karaoke', '01_room_grid', err);

  const startBtn = page.locator('.start-room').first();
  if (await startBtn.count() > 0) {
    await startBtn.click({ force: true });
    await page.waitForTimeout(1000);
    await shot(page, 'karaoke', '02_room_started', err);

    const checkoutBtn = page.locator('.checkout-room').first();
    if (await checkoutBtn.count() > 0) {
      await checkoutBtn.click({ force: true });
      await page.waitForTimeout(600);
      await shot(page, 'karaoke', '03_checkout_modal', err);

      const confirmBtn = page.locator('#confirmCheckoutBtn');
      if (await confirmBtn.count() > 0) {
        await confirmBtn.click({ force: true });
        await page.waitForTimeout(1200);
        await shot(page, 'karaoke', '04_checkout_done', err);
      }
    }
  } else {
    console.log('  [WARN] Không tìm thấy phòng trống để bắt đầu');
  }

  await page.goto(`${BASE}/karaoke/reservations`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'karaoke', '05_reservations', err);
}

async function flowHotel(page, err) {
  const email = 'demo.hotel.071443@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/hotel_rooms`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, 'hotel', '01_room_grid', err);

  const emptyRoom = page.locator('.room-card.status-trong').first();
  if (await emptyRoom.count() > 0) {
    await emptyRoom.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'hotel', '02_checkin_modal', err);

    await page.fill('#guestName', 'Audit Test Guest').catch(() => {});
    await page.fill('#guestPhone', '0900000000').catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, 'hotel', '03_checkin_filled', err);

    // submitCheckin() không có id ổn định trên nút -> tìm theo onclick
    const checkinSubmit = page.locator('[onclick="submitCheckin()"]');
    if (await checkinSubmit.count() > 0) {
      await checkinSubmit.click({ force: true });
      await page.waitForTimeout(1200);
      await shot(page, 'hotel', '04_checked_in', err);
    }

    const occupiedRoom = page.locator('.room-card.status-occupied').first();
    if (await occupiedRoom.count() > 0) {
      await occupiedRoom.click({ force: true });
      await page.waitForTimeout(600);
      await shot(page, 'hotel', '05_checkout_summary', err);

      const confirmCheckout = page.locator('#confirmCheckoutBtn');
      if (await confirmCheckout.count() > 0) {
        await confirmCheckout.click({ force: true });
        await page.waitForTimeout(1200);
        await shot(page, 'hotel', '06_checkout_done', err);
      }
    }
  } else {
    console.log('  [WARN] Không tìm thấy phòng trống (status-trong)');
  }

  await page.goto(`${BASE}/hotel/reservations`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'hotel', '07_reservations', err);
}

async function flowProduction(page, err) {
  const email = 'demo.production.393328@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/production_output`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, 'production', '01_initial', err);

  const workerSelect = page.locator('#logWorker');
  if (await workerSelect.count() > 0) {
    const options = await workerSelect.locator('option').all();
    if (options.length > 1) {
      const val = await options[1].getAttribute('value');
      await workerSelect.selectOption(val);
    }
  }
  await page.fill('#logStage', 'Assembly Line A').catch(() => {});
  await page.fill('#logQty', '10').catch(() => {});
  const shiftSelect = page.locator('#logShift');
  if (await shiftSelect.count() > 0) {
    const shiftOptions = await shiftSelect.locator('option').all();
    if (shiftOptions.length > 1) {
      const val = await shiftOptions[1].getAttribute('value');
      await shiftSelect.selectOption(val);
    }
  }
  await page.waitForTimeout(300);
  await shot(page, 'production', '02_form_filled', err);

  const saveBtn = page.locator('button[onclick="submitOutput()"]');
  if (await saveBtn.count() > 0) {
    await saveBtn.click({ force: true });
    await page.waitForTimeout(1200);
    await shot(page, 'production', '03_logged', err);
  }

  await page.goto(`${BASE}/production/materials`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'production', '04_materials', err);
}

async function flowTechnical(page, err) {
  const email = 'demo.technical.393328@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/chamcong/kythuat`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'technical', '01_attendance', err);

  await page.goto(`${BASE}/technical/parts`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'technical', '02_parts_list', err);

  await page.fill('#newPartName', 'Audit Test Bearing').catch(() => {});
  await page.fill('#newPartStock', '5').catch(() => {});
  await page.fill('#newPartPrice', '9.99').catch(() => {});
  await page.waitForTimeout(300);
  await shot(page, 'technical', '03_add_part_filled', err);

  const addBtn = page.locator('button[onclick="addPart()"]');
  if (await addBtn.count() > 0) {
    await addBtn.click({ force: true });
    await page.waitForTimeout(1000);
    await shot(page, 'technical', '04_part_added', err);
  }

  const newRow = page.locator('.row-card', { hasText: 'Audit Test Bearing' }).first();
  if (await newRow.count() > 0) {
    const deleteBtn = newRow.locator('.btn-mini', { hasText: /Xoá|Delete/i }).first();
    if (await deleteBtn.count() > 0) {
      await deleteBtn.click({ force: true });
      await page.waitForTimeout(1000);
      await shot(page, 'technical', '05_part_deleted', err);
    }
  }
}

async function flowOffice(page, err) {
  const email = 'demo.office.784966@bitpawdemo.com', pass = 'DemoBitPaw2026!';
  await login(page, email, pass);
  await page.goto(`${BASE}/chamcong/vanphong`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, 'office', '01_attendance_grid', err);

  const markAllBtn = page.locator('[onclick="markAllPresent()"]');
  if (await markAllBtn.count() > 0) {
    await markAllBtn.click({ force: true });
    await page.waitForTimeout(600);
    await shot(page, 'office', '02_mark_all_present', err);
  }

  const firstSaveBtn = page.locator('button[id^="btn_"]').first();
  if (await firstSaveBtn.count() > 0) {
    await firstSaveBtn.click({ force: true });
    await page.waitForTimeout(1000);
    await shot(page, 'office', '03_row_saved', err);
  }

  await page.goto(`${BASE}/leave_requests`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'office', '04_leave_requests', err);

  const approveBtn = page.locator('.action-btn', { hasText: /Duyệt|Approve/i }).first();
  if (await approveBtn.count() > 0) {
    await approveBtn.click({ force: true });
    await page.waitForTimeout(1000);
    await shot(page, 'office', '05_leave_approved', err);
  }

  await page.goto(`${BASE}/expense_requests`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await shot(page, 'office', '06_expense_requests', err);
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
    console.error(`Usage: node visual_industry_audit.mjs <${Object.keys(FLOWS).join('|')}>`);
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

  await context.close();
  await browser.close();
  console.log(`\n=== ${industry} flow done. Total shots so far: ${stepCounter} ===`);
}

main();
