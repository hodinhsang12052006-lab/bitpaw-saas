import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:5001';
const OUT_DIR = 'audit-results/screenshots/nail_pos_final';
fs.mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));
page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console: ' + msg.text()); });

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
await page.fill('#loginEmail', 'demo.nails.au.006758@bitpawdemo.com');
await page.fill('#loginPassword', 'DemoNails2026!');
await Promise.all([
  page.waitForNavigation({ waitUntil: 'networkidle', timeout: 20000 }).catch(() => null),
  page.click('#btnLogin'),
]);
await page.waitForTimeout(1000);

await page.goto(`${BASE}/sell`, { waitUntil: 'networkidle' });
await page.waitForSelector('.service-card', { timeout: 15000 });
await page.waitForTimeout(700);
await page.screenshot({ path: `${OUT_DIR}/pos_rayo_bezel_ui.png` });
console.log('Screenshot saved.');

// Also grab Ticket Items tab (shows the fixed toolbar icons close-up)
await page.locator('.service-card').first().click({ force: true });
await page.waitForTimeout(400);
await page.evaluate(() => switchTab('turnDetails'));
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT_DIR}/pos_rayo_toolbar_closeup.png` });

console.log('Errors:', errors.length ? errors : '(none)');
await browser.close();
