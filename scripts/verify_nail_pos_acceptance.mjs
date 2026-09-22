// scripts/verify_nail_pos_acceptance.mjs
// Final acceptance test for pos_nail.html (real, live file): full real transaction ->
// verify DB persistence -> Payment History drawer -> reprint. Per user's explicit request.
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:5001';
const SHOT_DIR = 'audit-results/screenshots/nail_pos_final';
fs.mkdirSync(SHOT_DIR, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));
page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console: ' + msg.text()); });

let stt = 0;
async function shot(label) {
  stt += 1;
  const fname = `${String(stt).padStart(2, '0')}_${label}.png`;
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOT_DIR}/${fname}` });
  console.log(`  [shot] ${fname}`);
}

console.log('=== Login ===');
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
await page.fill('#loginEmail', 'demo.nails.au.006758@bitpawdemo.com');
await page.fill('#loginPassword', 'DemoNails2026!');
await Promise.all([
  page.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => null),
  page.click('#btnLogin'),
]);
await page.waitForTimeout(1000);

console.log('=== 1) POS overview (new Dark Slate theme) ===');
await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
await page.waitForSelector('.service-card', { timeout: 15000 });
await page.waitForTimeout(600);
await shot('pos_overview_dark_slate');

console.log('=== 2) Add item -> assign tech ===');
await page.locator('.service-card').first().click({ force: true });
await page.waitForTimeout(500);
await page.locator('.workspace-tab-btn[data-tab="ticketItems"], .workspace-tab-btn[data-tab="turnDetails"]').first().click({ force: true }).catch(async () => {
  // fallback: find whichever tab shows the cart
  await page.evaluate(() => switchTab('turnDetails'));
});
await page.waitForTimeout(500);
await shot('item_added_ticket_items_tab');

const techSelect = page.locator('select[onchange^="assignTech"]').first();
const techCount = await techSelect.locator('option').count();
console.log('  Technician options available:', techCount);
if (techCount > 1) {
  const val = await techSelect.locator('option').nth(1).getAttribute('value');
  await techSelect.selectOption(val);
  console.log('  Assigned technician:', val);
}
await page.waitForTimeout(400);
await shot('tech_assigned');

console.log('=== 3) Close Ticket -> select tip -> Pay ===');
await page.locator('.workspace-tab-btn[data-tab="closeTicket"]').click({ force: true });
await page.waitForTimeout(400);
await page.fill('#cashTip', '8');
await page.fill('#cardTip', '4');
await page.waitForTimeout(300);
await shot('close_ticket_with_tips');

await page.locator('#checkoutBtn').click({ force: true });
await page.waitForTimeout(500);
await shot('payment_modal');

const checkoutRespPromise = page.waitForResponse((r) => r.url().includes('/api/nail_pos/checkout'), { timeout: 15000 });
await page.locator('#confirmPaymentBtn').click({ force: true });
const checkoutResp = await checkoutRespPromise;
const checkoutJson = await checkoutResp.json();
console.log('=== 4) DATABASE PERSISTENCE CHECK ===');
console.log('  Checkout response:', JSON.stringify(checkoutJson, null, 2));
await page.waitForTimeout(800);
await shot('receipt_after_payment');

if (!checkoutJson.success || !checkoutJson.order_id) {
  console.log('  [FAIL] Bill was NOT saved to database.');
  process.exitCode = 1;
} else {
  console.log(`  [OK] Bill #${checkoutJson.order_id} saved to database. Total: $${checkoutJson.total_amount}`);
}

await page.evaluate(() => { const m = document.getElementById('receiptModal'); if (m) m.classList.remove('active'); });
await page.waitForTimeout(300);

console.log('=== 5) Open Payment History drawer, confirm bill appears ===');
await page.evaluate(() => { openOrderHistoryModal(); });
await page.waitForTimeout(1000);
await shot('payment_history_drawer');
const historyText = await page.locator('#historyBody').innerText();
const foundInHistory = checkoutJson.order_id && historyText.includes(`#${checkoutJson.order_id}`);
console.log('  Bill found in history list:', foundInHistory);
if (!foundInHistory) {
  console.log('  [FAIL] New bill does not appear in Payment History.');
  process.exitCode = 1;
}

console.log('=== 6) Reprint the bill from history ===');
if (foundInHistory) {
  await page.locator(`button[onclick="reprintOrderFromHistory(${checkoutJson.order_id})"]`).click({ force: true }).catch(async () => {
    await page.evaluate((id) => reprintOrderFromHistory(id), checkoutJson.order_id);
  });
  await page.waitForTimeout(700);
  await shot('reprinted_bill');
  const reprintVisible = await page.locator('#receiptModal.active').count();
  console.log('  Reprint opened receipt modal:', reprintVisible > 0);
}

console.log('\nErrors:', errors.length ? errors : '(none)');
console.log(`\nTotal screenshots: ${stt} -> ${SHOT_DIR}/`);
await browser.close();
