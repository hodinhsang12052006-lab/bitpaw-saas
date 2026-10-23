// landing_fab_audit.mjs — iPhone: nút Liên hệ nổi không che nút chính ở màn đầu, ẩn khi cuộn xuống, hiện nút tròn khi dừng, chạm mở bảng liên hệ. node scripts/landing_fab_audit.mjs <thư mục ảnh> (server local)
import { chromium, devices } from 'playwright';
const OUT = process.argv[2];
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext(iphone); const p = await ctx.newPage();
let bad = 0; const ok = (c, m) => { if (!c) bad++; console.log((c ? '✅ ' : '❌ ') + m); };
for (const pg of ['landing', 'solutions/nail', 'solutions/hotel']) {
  await p.goto('http://127.0.0.1:5001/' + pg, { waitUntil: 'load' }); await p.waitForTimeout(1200);
  const covered = await p.evaluate(() => { const f = document.querySelector('.bp-fab'); const s = getComputedStyle(f); return s.opacity > 0.5 && s.pointerEvents !== 'none'; });
  ok(!covered, `${pg}: màn hình đầu không có nút nổi che nút chính`);
  await p.mouse.wheel(0, 1500); await p.waitForTimeout(150);
  const whileScroll = await p.evaluate(() => getComputedStyle(document.querySelector('.bp-fab')).opacity);
  await p.waitForTimeout(1100);
  const idle = await p.evaluate(() => { const f = document.querySelector('.bp-fab'); const r = f.getBoundingClientRect(); return { o: getComputedStyle(f).opacity, w: Math.round(r.width), h: Math.round(r.height) }; });
  ok(+idle.o > 0.9 && idle.w === 52, `${pg}: đang cuộn xuống ẩn (opacity ${whileScroll}), dừng thì hiện nút tròn ${idle.w}x${idle.h}`);
  if (pg === 'landing') {
    await p.screenshot({ path: `${OUT}/fab_idle.png` });
    await p.tap('.bp-fab'); await p.waitForTimeout(500);
    ok(await p.evaluate(() => document.getElementById('bpFabSheet').classList.contains('open') || getComputedStyle(document.getElementById('bpFabSheet')).transform !== 'none'), 'chạm nút tròn mở bảng Liên hệ');
    await p.screenshot({ path: `${OUT}/fab_sheet.png` });
  }
}
await b.close(); console.log(bad ? `❌ ${bad}` : '✅ đạt');
