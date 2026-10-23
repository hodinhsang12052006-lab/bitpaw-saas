// Test THẬT 9 app Windows theo ngành (dist/releases/BitPaw-<Ngành>.exe) như khách tải về chạy:
//  - chép file ra thư mục tạm (đúng tên file khách tải), chạy, nối vào CHÍNH cửa sổ WebView2 của app qua cổng debug
//  - app phải mở /login?industry=<đúng ngành>&src=desktop, đăng nhập tài khoản demo ngành đó -> vào đúng màn chính
//  - ngồi lại 20 giây trong app: không lỗi JS / request lỗi; chụp ảnh cửa sổ app
//  - Nails: thêm ca mất mạng -> trang báo mất kết nối; có mạng lại -> app tự vào lại trong <= 15 giây
// Hồ sơ WebView để ở thư mục tạm (APPDATA giả) — không đụng %APPDATA% thật. Server: local 127.0.0.1:5001.
//   node scripts/desktop_app_e2e.mjs [nail,spa,...]
import { chromium } from 'playwright';
import { spawn, execSync } from 'child_process';
import fs from 'fs';
import http from 'http';
import os from 'os';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const REL = path.resolve(process.env.REL_DIR || 'dist/releases');  // REL_DIR=<thư mục file tải từ web thật>
const WORK = path.join(os.tmpdir(), 'bitpaw_exe_test');
const OUT = path.resolve('audit-results/screenshots/desktop_app_e2e');
fs.mkdirSync(OUT, { recursive: true });
const APPS = {
  nail: ['BitPaw-Nails.exe', 'demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'],
  spa: ['BitPaw-Spa.exe', 'demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  fnb: ['BitPaw-FnB.exe', 'demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'],
  karaoke: ['BitPaw-Karaoke.exe', 'demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  hotel: ['BitPaw-Hotel.exe', 'demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  retail: ['BitPaw-Retail.exe', 'demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  production: ['BitPaw-Production.exe', 'demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  technical: ['BitPaw-Technical.exe', 'demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  office: ['BitPaw-Office.exe', 'demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!'],
};
const only = (process.argv[2] || Object.keys(APPS).join(',')).split(',');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function launch(code, baseUrl, port) {
  const [file] = APPS[code];
  const dir = path.join(WORK, code);
  fs.mkdirSync(dir, { recursive: true });
  const exe = path.join(dir, file);
  if (!fs.existsSync(exe)) fs.copyFileSync(path.join(REL, file), exe);
  const appdata = path.join(dir, 'AppData');
  fs.mkdirSync(appdata, { recursive: true });
  const t0 = Date.now();
  const child = spawn(exe, [], {
    env: { ...process.env, BITPAW_URL: baseUrl, APPDATA: appdata, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}` },
    detached: false, stdio: 'ignore',
  });
  return { child, t0 };
}

async function attach(port, timeoutMs = 45000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 3000 });
      for (let i = 0; i < 20; i++) {
        const pg = b.contexts().flatMap((c) => c.pages()).find((p) => !p.url().startsWith('devtools'));
        if (pg) return { b, pg };
        await sleep(500);
      }
    } catch (e) { /* app đang khởi động */ }
    await sleep(700);
  }
  throw new Error('Không nối được vào cửa sổ app (WebView2) sau ' + timeoutMs / 1000 + 's');
}

function kill(child) {
  try { execSync(`taskkill /PID ${child.pid} /T /F`, { stdio: 'ignore' }); } catch (e) { /* đã thoát */ }
}

let port = 9400;
for (const code of only) {
  const [file, email, pw] = APPS[code];
  const rec = { code, file, checks: [] };
  const check = (name, ok, detail = '') => { rec.checks.push({ name, ok: !!ok, detail }); console.log(`${ok ? '✅' : '❌'} [${file}] ${name}${detail ? ' — ' + detail : ''}`); };
  const { child, t0 } = launch(code, BASE, ++port);
  let b;
  try {
    const att = await attach(port);
    b = att.b;
    const pg = att.pg;
    // app mở cửa sổ trống (about:blank) trước rồi mới điều hướng — đợi trang thật
    await pg.waitForURL((x) => x.protocol.startsWith('http'), { timeout: 20000 }).catch(() => {});
    await pg.waitForLoadState('load').catch(() => {});
    const openSec = ((Date.now() - t0) / 1000).toFixed(1);
    const errs = [];
    pg.on('pageerror', (e) => errs.push('JS: ' + String(e).slice(0, 150)));
    pg.on('response', (r) => { if (r.url().startsWith(BASE) && r.status() >= 400) errs.push(`${r.status()} ${r.url().replace(BASE, '').slice(0, 90)}`); });
    const u = new URL(pg.url());
    check('Mở đúng trang đăng nhập của ngành', u.pathname === '/login' && u.searchParams.get('industry') === code && u.searchParams.get('src') === 'desktop',
      `${pg.url().replace(BASE, '')} · mở sau ${openSec}s`);
    await pg.screenshot({ path: path.join(OUT, `${code}_1_login.png`) });
    await pg.fill('#loginEmail', email);
    await pg.fill('#loginPassword', pw);
    await Promise.all([pg.waitForURL((x) => !x.pathname.startsWith('/login'), { timeout: 30000 }).catch(() => {}), pg.click('#btnLogin')]);
    await pg.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    const home = pg.url().replace(BASE, '');
    check('Đăng nhập trong app -> vào màn chính của ngành', !home.startsWith('/login') && !home.startsWith('/setup'), home);
    const t1 = Date.now();
    await pg.waitForTimeout(20000);
    check('Ngồi 20 giây trong app: không lỗi JS / request lỗi', errs.length === 0, errs.slice(0, 3).join(' | ') || `${((Date.now() - t1) / 1000).toFixed(0)}s sạch`);
    const vp = await pg.evaluate(() => ({ w: innerWidth, h: innerHeight, sw: document.scrollingElement.scrollWidth, title: document.title }));
    check('Cửa sổ app hiển thị đủ, không tràn ngang', vp.sw <= vp.w + 1, `${vp.w}x${vp.h} · "${vp.title}"`);
    await pg.screenshot({ path: path.join(OUT, `${code}_2_home.png`) });
  } catch (e) {
    check('App chạy được', false, e.message.slice(0, 200));
  } finally {
    if (b) await b.close().catch(() => {});
    kill(child);
    await sleep(1500);
  }
  results.push(rec);
}

// Ca mất mạng (Nails): server chưa chạy -> trang báo mất mạng; bật server -> app tự vào lại
if (only.includes('nail')) {
  const rec = { code: 'nail_offline', file: 'BitPaw-Nails.exe', checks: [] };
  const check = (name, ok, detail = '') => { rec.checks.push({ name, ok: !!ok, detail }); console.log(`${ok ? '✅' : '❌'} [mất mạng] ${name}${detail ? ' — ' + detail : ''}`); };
  const OFF = 'http://127.0.0.1:5999';
  const { child } = launch('nail', OFF, ++port);
  let b; let srv;
  try {
    const att = await attach(port);
    b = att.b;
    const pg = att.pg;
    await pg.waitForFunction(() => /No internet/.test(document.body?.innerText || ''), null, { timeout: 20000 }).catch(() => {});
    const txt = await pg.evaluate(() => document.body.innerText);
    check('Không có mạng -> trang báo mất kết nối song ngữ', /No internet/.test(txt) && /Không có kết nối/.test(txt), txt.slice(0, 60).replace(/\n/g, ' '));
    await pg.screenshot({ path: path.join(OUT, 'nail_0_offline.png') });
    srv = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'text/html' }); res.end('<title>back online</title>ok'); }).listen(5999);
    const t = Date.now();
    const ok = await pg.waitForURL((x) => x.href.startsWith(OFF + '/login'), { timeout: 16000 }).then(() => true).catch(() => false);
    check('Có mạng lại -> app tự mở lại trang đăng nhập (không cần tắt bật)', ok, ok ? `${((Date.now() - t) / 1000).toFixed(1)}s` : pg.url());
  } catch (e) {
    check('App chạy được khi mất mạng', false, e.message.slice(0, 200));
  } finally {
    if (b) await b.close().catch(() => {});
    kill(child);
    if (srv) srv.close();
  }
  results.push(rec);
}
fs.writeFileSync('audit-results/desktop_app_e2e.json', JSON.stringify(results, null, 1));
const all = results.flatMap((r) => r.checks);
console.log(`\nTổng kết app Windows: ${all.filter((c) => c.ok).length} PASS · ${all.filter((c) => !c.ok).length} FAIL`);
