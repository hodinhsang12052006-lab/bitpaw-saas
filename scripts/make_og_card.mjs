// make_og_card.mjs — vẽ ảnh xem trước khi chia sẻ link (Facebook/Zalo/iMessage) 1200x630: static/brand/og-card.png
// (thay ảnh linh vật cho1.jpg cũ). Chạy lại khi đổi khẩu hiệu:  node scripts/make_og_card.mjs
import { chromium } from 'playwright';
import fs from 'fs';

const mark = fs.readFileSync('static/brand/mark.svg', 'utf8');
const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;700;800&display=swap" rel="stylesheet">
<style>
  * { margin: 0; box-sizing: border-box; }
  body { width: 1200px; height: 630px; background: #0b1120; color: #f8fafc; font-family: Inter, system-ui, sans-serif;
         display: flex; flex-direction: column; justify-content: center; padding: 0 96px; position: relative; overflow: hidden; }
  body::before { content: ''; position: absolute; inset: 0; background: radial-gradient(900px 480px at 85% 10%, rgba(34,211,238,.14), transparent 60%); }
  .brand { display: flex; align-items: center; gap: 22px; margin-bottom: 44px; position: relative; }
  .brand svg { width: 84px; height: 84px; }
  .brand span { font-size: 46px; font-weight: 800; letter-spacing: -.02em; }
  h1 { font-size: 64px; line-height: 1.08; font-weight: 800; letter-spacing: -.025em; max-width: 940px; position: relative; }
  h1 em { font-style: normal; color: #22d3ee; }
  p { margin-top: 26px; font-size: 28px; color: #94a3b8; font-weight: 500; position: relative; }
  .line { position: absolute; left: 96px; right: 96px; bottom: 64px; height: 1px; background: rgba(148,163,184,.2); }
  .url { position: absolute; left: 96px; bottom: 26px; font-size: 22px; color: #64748b; font-weight: 500; }
</style></head><body>
  <div class="brand">${mark}<span>BitPaw</span></div>
  <h1>Run your whole business<br><em>in one app</em></h1>
  <p>Checkout · Bookings · Staff &amp; payroll · Customer care</p>
  <div class="line"></div><div class="url">bitpawsoftware.com</div>
</body></html>`;
const b = await chromium.launch({ channel: 'chrome' });
const p = await b.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await p.setContent(html, { waitUntil: 'networkidle' });
await p.evaluate(() => document.fonts.ready);
await p.screenshot({ path: 'static/brand/og-card.png' });
await b.close();
console.log('static/brand/og-card.png');
