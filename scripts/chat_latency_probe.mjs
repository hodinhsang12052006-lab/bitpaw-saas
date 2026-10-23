// chat_latency_probe.mjs — đo độ trễ THẬT của chat nội bộ: máy A gửi tin, máy B (trang /chat) thấy sau bao lâu;
// + số request máy B tự phát ra khi đứng yên (do ping "đang online" của người khác).   node scripts/chat_latency_probe.mjs [tag]
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const TAG = process.argv[2] || 'run';
const b = await chromium.launch({ channel: 'chrome' });
async function login() {
  const ctx = await b.newContext({ viewport: { width: 1280, height: 860 } });
  const p = await ctx.newPage();
  await p.goto(BASE + '/login');
  await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
  await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
  return p;
}
const recv = await login();
const send = await login();
const reqLog = [];
recv.on('request', (r) => { if (r.url().includes('/api/')) reqLog.push({ t: Date.now(), u: r.url().replace(BASE, '').split('?')[0] }); });
await recv.goto(BASE + '/chat', { waitUntil: 'networkidle' });
await send.goto(BASE + '/chat', { waitUntil: 'networkidle' });   // 2 người cùng online -> có ping presence
await recv.waitForTimeout(3000);

// 1) đứng yên 40 s: đếm request tự phát
const idleStart = Date.now();
await recv.waitForTimeout(40000);
const idle = reqLog.filter((r) => r.t >= idleStart);
const idleBy = {};
idle.forEach((r) => { idleBy[r.u] = (idleBy[r.u] || 0) + 1; });

// 2) gửi 12 tin rải đều ~6 s/tin (bắt qua các lần nối lại 25 s)
const lat = [];
for (let i = 0; i < 12; i++) {
  const text = `latency-probe-${TAG}-${Date.now()}-${i}`;
  const t0 = Date.now();
  await send.evaluate(async (txt) => {
    await fetch('/api/chat/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room: 'KenhChung', content: txt }) });
  }, text);
  try {
    await recv.waitForFunction((txt) => document.body.innerText.includes(txt), text, { timeout: 30000, polling: 50 });
    lat.push(Date.now() - t0);
  } catch (e) { lat.push(null); }
  await recv.waitForTimeout(4000 + Math.random() * 3000);
}
const ok = lat.filter((x) => x !== null).sort((a, c) => a - c);
const res = {
  tag: TAG, idle_requests_per_min: Math.round(idle.length * 60 / 40), idle_by_endpoint: idleBy,
  latency_ms: lat, p50: ok[Math.floor(ok.length / 2)], p90: ok[Math.floor(ok.length * 0.9)], max: ok[ok.length - 1], missed: lat.filter((x) => x === null).length,
};
console.log(JSON.stringify(res, null, 2));
fs.mkdirSync('audit-results/ai_sim', { recursive: true });
fs.writeFileSync(`audit-results/ai_sim/chat_latency_${TAG}.json`, JSON.stringify(res, null, 2));
// dọn tin thử
await send.evaluate(async () => {});
await b.close();
