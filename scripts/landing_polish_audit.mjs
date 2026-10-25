// landing_polish_audit.mjs — 11 landing: không lỗi JS, không tải three.js, nền sao vẽ được, hiệu ứng hiện khối trễ ≤150ms, nút Liên hệ bung/thu, nhớ ngôn ngữ VN/EN giữa các trang. node scripts/landing_polish_audit.mjs <thư mục ảnh> (server local)
import { chromium, devices } from 'playwright';
const OUT = process.argv[2];
const PAGES = ['landing', 'nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'production', 'technical', 'office', 'hr'];
const b = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' });
let fails = 0;
const ok = (c, m) => { if (!c) fails++; console.log((c ? '✅ ' : '❌ ') + m); };
for (const pg of PAGES) {
  const p = await ctx.newPage();
  const errs = []; const reqs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  p.on('request', (r) => reqs.push(r.url()));
  await p.goto((process.env.BASE || 'http://127.0.0.1:5001') + (pg === 'landing' ? '/landing' : `/solutions/${pg}`), { waitUntil: 'load' });
  await p.waitForTimeout(1200);
  const st = await p.evaluate(() => ({
    canvasPainted: (() => { const c = document.getElementById('bg-canvas'); if (!c) return -1; try { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; } catch (e) { return 'ctx:' + e.message; } })(),
    aosInit: document.querySelectorAll('.aos-init').length, maxDelay: Math.max(0, ...[...document.querySelectorAll('[data-aos-delay]')].map((e) => +e.dataset.aosDelay)),
    faqWorks: (() => { const h = document.querySelector('.faq-header, .faq-question, [onclick*="toggleFaq"]'); return !!h; })(),
    lang: document.documentElement.lang,
  }));
  const three = reqs.some((u) => u.includes('three'));
  ok(errs.length === 0 && !three && st.canvasPainted > 50 && st.aosInit > 10 && st.maxDelay <= 150,
    `${pg}: lỗi JS=${errs.length}${errs.length ? ' (' + errs[0].slice(0, 80) + ')' : ''} · three.js=${three} · điểm sao=${st.canvasPainted} · AOS=${st.aosInit} · trễ max=${st.maxDelay}ms · lang=${st.lang}`);
  if (pg === 'nail') {
    // cuộn giữa trang: mọi khối trong màn hình phải hiện rõ sau 0.7s (không còn mảng trống)
    await p.evaluate(() => scrollTo(0, 3000)); await p.waitForTimeout(700);
    const hidden = await p.evaluate(() => [...document.querySelectorAll('[data-aos]')].filter((e) => { const r = e.getBoundingClientRect(); return r.top > 0 && r.bottom < innerHeight && getComputedStyle(e).opacity < 0.95; }).length);
    ok(hidden === 0, `nail: khối còn mờ trong màn hình sau 0,7s cuộn: ${hidden}`);
    await p.screenshot({ path: `${OUT}/nail_mid.png` });
    // nút Liên hệ
    await p.hover('#contactDialToggle'); await p.waitForTimeout(450);
    const vis = await p.evaluate(() => [...document.querySelectorAll('#contactDial .contact-btn')].filter((e) => getComputedStyle(e).opacity > 0.9).length);
    ok(vis === 4, `nút Liên hệ: rê chuột bung ${vis}/4 kênh`);
    await p.screenshot({ path: `${OUT}/dial_open.png`, clip: { x: 1100, y: 560, width: 340, height: 340 } });
    await p.mouse.move(400, 400); await p.waitForTimeout(500);
    const vis2 = await p.evaluate(() => [...document.querySelectorAll('#contactDial .contact-btn')].filter((e) => getComputedStyle(e).opacity > 0.1).length);
    ok(vis2 === 0, `nút Liên hệ: rời chuột thu lại (${vis2} còn hiện)`);
  }
  await p.close();
}
// ngôn ngữ: chọn VN ở trang Spa -> sang F&B, Hotel, Nails vẫn VN; chọn EN ở Nails -> sang Spa ra EN
const p = await ctx.newPage();
await p.goto((process.env.BASE || 'http://127.0.0.1:5001') + '/solutions/spa', { waitUntil: 'load' });
await p.evaluate(() => changeLanguage('vi')); await p.waitForTimeout(300);
for (const pg of ['fnb', 'hotel', 'nail', 'technical']) {
  await p.goto((process.env.BASE || 'http://127.0.0.1:5001') + '/solutions/' + pg, { waitUntil: 'load' }); await p.waitForTimeout(600);
  const h1 = await p.evaluate(() => document.querySelector('h1').innerText.replace(/\s+/g, ' ').slice(0, 50));
  ok(/[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(h1), `đã chọn VN -> ${pg} hiện tiếng Việt: "${h1}"`);
}
await p.evaluate(() => changeLanguage('en')); await p.waitForTimeout(300);
for (const pg of ['spa', 'karaoke', 'production']) {
  await p.goto((process.env.BASE || 'http://127.0.0.1:5001') + '/solutions/' + pg, { waitUntil: 'load' }); await p.waitForTimeout(600);
  const h1 = await p.evaluate(() => document.querySelector('h1').innerText.replace(/\s+/g, ' ').slice(0, 50));
  const foot = await p.evaluate(() => [...document.querySelectorAll('.bf-en')].some((e) => e.offsetParent));
  ok(!/[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(h1) && foot, `đã chọn EN -> ${pg} hiện tiếng Anh (cả chân trang): "${h1}"`);
}
await b.close();
console.log(`\n${fails ? '❌ ' + fails + ' lỗi' : '✅ tất cả đạt'}`);
