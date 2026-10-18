// Đo trên giả lập iPhone 13 THẬT (isMobile — trình duyệt di động được phép nới khung nhìn rộng hơn màn hình rồi thu nhỏ
// cả trang): khung nhìn thật (innerWidth), độ phóng, và các phần tử thò ra ngoài 390px kéo rộng trang.
//   TENANT=nail PAGES=/chamcong_nail,/ai_bot node scripts/mobile_viewport_probe.mjs
import { chromium, devices } from 'playwright';

const BASE = 'http://127.0.0.1:5001';
const ACC = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!'], fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'], retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!'], hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!'], technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!'],
};
const [email, pw] = ACC[process.env.TENANT || 'nail'];
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ ...iphone, deviceScaleFactor: 2 });
const p = await ctx.newPage();
await p.goto(BASE + '/login');
await p.fill('#loginEmail', email); await p.fill('#loginPassword', pw);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
for (const url of (process.env.PAGES || '/chamcong_nail').split(',')) {
  await p.goto(BASE + url, { waitUntil: 'networkidle' }).catch(() => {});
  await p.waitForTimeout(800);
  const r = await p.evaluate(() => {
    const vw = innerWidth;
    const wide = [];
    for (const el of document.querySelectorAll('body *')) {
      const cs = getComputedStyle(el);
      if (cs.position === 'fixed' && cs.pointerEvents === 'none') continue;
      const rc = el.getBoundingClientRect();
      if (rc.width > 0 && (rc.right > 392 || rc.width > 392)) {
        // chỉ giữ phần tử "gốc" (cha của nó không thò ra) để biết đúng thủ phạm
        const pr = el.parentElement.getBoundingClientRect();
        if (!(pr.right > 392 || pr.width > 392) || el.parentElement === document.body) {
          if (cs.position === 'absolute' || cs.position === 'fixed') {
            if (el.innerText && el.innerText.trim()) wide.push(`CHỮ/NÚT ${cs.position} thò ra: ${el.tagName.toLowerCase()}.${String(el.className).split(' ').slice(0, 3).join('.')} [${Math.round(rc.left)}→${Math.round(rc.right)}]`);
            continue;  // vệt sáng/khối trang trí không có chữ: bị html{overflow-x:hidden} giấu, vô hại
          }
          // tổ tiên gần nhất có overflow-x khác visible: auto/scroll = vuốt ngang xem được; hidden/clip = BỊ CẮT
          let a = el.parentElement, how = 'trang (html overflow-x hidden) -> BỊ CẮT';
          while (a && a !== document.documentElement) {
            const ox = getComputedStyle(a).overflowX;
            if (ox !== 'visible') { how = (ox === 'auto' || ox === 'scroll') ? `vuốt ngang được (${a.tagName.toLowerCase()}.${String(a.className).split(' ').slice(0, 2).join('.')})` : `BỊ CẮT bởi ${a.tagName.toLowerCase()}.${String(a.className).split(' ').slice(0, 3).join('.')} overflow-x:${ox}`; break; }
            a = a.parentElement;
          }
          wide.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${String(el.className).split(' ').slice(0, 3).join('.')} [${Math.round(rc.left)}→${Math.round(rc.right)}] => ${how}`);
        }
      }
    }
    return { innerWidth: vw, docW: document.documentElement.scrollWidth, scale: visualViewport.scale.toFixed(2), meta: document.querySelector('meta[name=viewport]')?.content, wide: wide.slice(0, 8) };
  });
  console.log(`\n${url}: innerWidth=${r.innerWidth} docW=${r.docW} scale=${r.scale} viewport-meta="${r.meta}"`);
  r.wide.forEach((w) => console.log('   ', w));
}
await b.close();
