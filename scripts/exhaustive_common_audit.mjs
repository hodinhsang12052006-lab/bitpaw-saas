// scripts/exhaustive_common_audit.mjs
// Quét các module dùng chung / quản trị: đặt lịch hẹn, tự chấm công, Super Admin, cụm AI,
// hạ tầng thanh toán. Screenshot: audit-results/screenshots/common/<stt>_<action>.png
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const SHOT_DIR = 'audit-results/screenshots/common';
const VIDEO_DIR = 'audit-results/videos';
const MANIFEST_FILE = 'audit-results/exhaustive_manifest.json';
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(VIDEO_DIR, { recursive: true });

function loadManifest() {
  if (fs.existsSync(MANIFEST_FILE)) { try { return JSON.parse(fs.readFileSync(MANIFEST_FILE, 'utf-8')); } catch (_) { return []; } }
  return [];
}
function saveManifest(m) { fs.writeFileSync(MANIFEST_FILE, JSON.stringify(m, null, 2), 'utf-8'); }
let manifest = loadManifest();
let stt = 0;

async function shot(page, label, errBucket) {
  stt += 1;
  const fname = `${String(stt).padStart(3, '0')}_${label.replace(/[^a-zA-Z0-9_\-]/g, '_')}.png`;
  await page.waitForTimeout(350);
  try { await page.screenshot({ path: path.join(SHOT_DIR, fname), fullPage: false }); } catch (e) { console.log(`  [screenshot FAILED] ${label}: ${e.message}`); }
  manifest.push({
    n: stt, industry: 'common', label, file: `common/${fname}`, url: page.url(),
    consoleErrors: (errBucket ? errBucket.console.splice(0) : []),
    apiErrors: (errBucket ? errBucket.api.splice(0) : []),
  });
  saveManifest(manifest);
  console.log(`  [shot] #${stt} ${label}`);
}

function attachErrorBucket(page) {
  const bucket = { console: [], api: [] };
  page.on('console', (msg) => { if (msg.type() === 'error') bucket.console.push(msg.text().slice(0, 300)); });
  page.on('response', (resp) => { if (resp.status() >= 400) bucket.api.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`); });
  page.on('dialog', async (dialog) => {
    console.log(`  [dialog] ${dialog.type()}: ${dialog.message().slice(0, 100)}`);
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
async function safeClick(page, selector) {
  const loc = typeof selector === 'string' ? page.locator(selector) : selector;
  if (await loc.count() === 0) return false;
  try { await loc.first().click({ force: true, timeout: 5000 }); return true; } catch (e) { console.log(`  [click FAILED] ${e.message.split('\n')[0]}`); return false; }
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 }, locale: 'vi-VN',
    recordVideo: { dir: VIDEO_DIR, size: { width: 1366, height: 768 } },
  });
  const page = await context.newPage();
  const err = attachErrorBucket(page);

  // ---- 1) Lịch hẹn (duyệt booking) — dùng tài khoản Spa (có tính năng đặt lịch) ----
  await login(page, 'demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!');
  await page.goto(`${BASE}/calendar`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, '01_calendar_booking_admin', err);

  // ---- 2) Tự chấm công của nhân viên (diemdanh / app_nhanvien) ----
  await page.goto(`${BASE}/diemdanh`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, '02_diemdanh_self_checkin', err);

  await page.goto(`${BASE}/app_nhanvien`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await shot(page, '03_app_nhanvien_self_portal', err);

  // ---- 3) Cụm AI/Marketing (chỉ xem, không bấm generate thật để tránh tốn phí AI thật) ----
  for (const [p, label] of [
    ['/ai_bot', '04_ai_bot'],
    ['/ai-studio', '05_ai_studio'],
    ['/omnichannel_connect', '06_omnichannel_connect'],
    ['/customer_nurturing', '07_customer_nurturing'],
    ['/campaign_builder', '08_campaign_builder'],
    ['/crm_automation', '09_crm_automation'],
  ]) {
    await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    await shot(page, label, err);
  }

  // ---- 4) Hạ tầng thanh toán (chỉ xem) ----
  for (const [p, label] of [
    ['/payment_gateway', '10_payment_gateway_config'],
    ['/payment_history', '11_payment_history'],
    ['/payment_transactions', '12_payment_transactions_admin'],
  ]) {
    await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    await shot(page, label, err);
  }

  // ---- 5) Vận hành chung khác ----
  for (const [p, label] of [
    ['/inventory_alert', '13_inventory_alert'],
    ['/report_consolidated', '14_report_consolidated'],
    ['/promotions', '15_promotions'],
    ['/expense_list', '16_expense_list'],
    ['/backup_restore', '17_backup_restore'],
    ['/brand_settings', '18_brand_settings'],
    ['/ecommerce_sync', '19_ecommerce_sync'],
    ['/user_logs', '20_user_logs'],
    ['/bangluong', '21_bangluong'],
    ['/cauhinh_luong', '22_cauhinh_luong'],
    ['/baocao_loinhuan', '23_baocao_loinhuan'],
  ]) {
    await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    await shot(page, label, err);
  }

  // ---- 6) Super Admin (dùng credentials thật của chủ hệ thống — chỉ xem, không đổi cấu hình) ----
  const superEmail = process.env.SUPERADMIN_EMAIL || 'hodinhsang30052003@gmail.com';
  const superPass = process.env.SUPERADMIN_PASSWORD || '0794678904Az@';
  await login(page, superEmail, superPass);
  await page.goto(`${BASE}/super_admin`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot(page, '24_super_admin_dashboard', err);

  const videoObj = page.video();
  await context.close();
  await browser.close();
  if (videoObj) {
    try {
      const autoPath = await videoObj.path();
      const target = path.join(VIDEO_DIR, 'common.webm');
      if (fs.existsSync(target)) fs.unlinkSync(target);
      fs.renameSync(autoPath, target);
      console.log(`  [video] -> ${target}`);
    } catch (e) { console.log(`  [video RENAME FAILED] ${e.message}`); }
  }
  console.log(`\n=== common admin flow done. Total shots: ${stt} ===`);
}

main();
