// spa_pos_e2e.mjs — POS Spa làm lại (25/10/2026): tên tiệm thật, lọc nhóm, thêm liệu trình, gán kỹ thuật viên, tip 15%, thu thẻ,
// DB đúng (tổng, tip, hoa hồng + tip chia theo phần doanh thu, khách mới có tên), hoàn tiền thu hồi cả tip, xoá dịch vụ chỉ qua POST,
// điện thoại (thanh phiếu thu dưới đáy), tiếng Việt. Tự dọn mọi dữ liệu test (đơn, dòng hàng, sổ cái, chấm công, khách).
//   node scripts/spa_pos_e2e.mjs   (CHỈ server local)
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const [EMAIL, PW] = ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!'];
const BID = '3cd48d09-8028-486d-82da-038db3ac2892';
const PHONE = '0400' + String(Date.now()).slice(-6);
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const b = await chromium.launch({ channel: 'chrome' });
let orderId = null;

async function login(ctx) {
  const p = await ctx.newPage();
  await p.goto(BASE + '/login'); await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
  await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
  return p;
}

try {
  // ---------- máy tính ----------
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-AU', timezoneId: 'Australia/Sydney' });
  await ctx.addInitScript(() => { try { localStorage.setItem('bitpaw_lang', 'en'); } catch (e) {} });
  const p = await login(ctx); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(BASE + '/spa', { waitUntil: 'networkidle' });
  const head = await p.evaluate(() => ({ shop: document.querySelector('.shop').textContent.trim(), tiles: document.querySelectorAll('.tile').length,
    del: [...document.querySelectorAll('.tile-del')].filter((x) => !x.hidden).length, ov: document.documentElement.scrollWidth - innerWidth }));
  rec('Tên tiệm thật trên đầu trang (không còn "BitPaw")', head.shop === 'Serenity Wellness Spa', head.shop);
  rec('Không có nút xoá trên màn bán hàng (chỉ hiện khi bấm "Edit list")', head.tiles >= 4 && head.del === 0, JSON.stringify(head));
  await p.click('.chip[data-cat="Massage"]');
  const massage = await p.evaluate(() => [...document.querySelectorAll('.tile')].filter((x) => !x.hidden).map((x) => x.dataset.cat));
  rec('Lọc nhóm "Massage" theo dữ liệu thật của tiệm', massage.length >= 1 && massage.every((c) => c === 'Massage'), massage.length + ' tiles');
  await p.click('.chip[data-cat=""]');
  await p.fill('#q', 'swedish'); await p.keyboard.press('Enter');     // Enter = thêm liệu trình đầu tiên đang hiện
  await p.fill('#q', ''); await p.dispatchEvent('#q', 'input');
  await p.click('.tile[data-name="Signature Facial Treatment"] .tile-hit');
  const t1 = await p.evaluate(() => ({ n: document.querySelectorAll('.line').length, sub: document.getElementById('sSub').textContent, badge: document.querySelector('.tile.in .badge')?.textContent }));
  rec('Thêm 2 liệu trình (Enter trong ô tìm + chạm thẻ): tạm tính $184.00', t1.n === 2 && t1.sub === '$184.00' && t1.badge === '×1', JSON.stringify(t1));
  const techs = await p.evaluate(() => [...document.querySelectorAll('#lines select')[0].options].map((o) => o.value).filter(Boolean));
  await p.selectOption('#lines li:nth-child(1) select', techs[0]);
  await p.selectOption('#lines li:nth-child(2) select', techs[1] || techs[0]);
  await p.click('#tipSeg [data-tip="15"]');
  await p.fill('#phone', PHONE); await p.fill('#cname', 'QA Spa Client');
  await p.waitForTimeout(900);
  await p.click('#paySeg [data-pay="card"]');
  const t2 = await p.evaluate(() => ({ tip: document.getElementById('sTip').textContent, total: document.getElementById('sTotal').textContent, btn: document.getElementById('chargeBtn').textContent.trim(),
    note: document.getElementById('payNote').textContent, hint: document.getElementById('custHint').textContent }));
  rec('Tip 15% = $27.60, tổng $211.60, nút "Charge $211.60", hướng dẫn quẹt thẻ trên máy của tiệm', t2.tip === '$27.60' && t2.total === '$211.60' && /211\.60/.test(t2.btn) && /terminal/i.test(t2.note), JSON.stringify(t2));
  rec('Khách mới được nhận ra theo SĐT', /New client/.test(t2.hint), t2.hint);
  await p.click('#chargeBtn');
  await p.waitForSelector('#done:not([hidden])', { timeout: 15000 });
  const done = await p.evaluate(() => ({ amt: document.getElementById('dAmt').textContent, rcpt: document.getElementById('dReceipt').innerText }));
  orderId = Number((done.rcpt.match(/#(\d+)/) || [])[1]) || null;
  rec('Thu xong: màn "Payment recorded" $211.60 + số bill', done.amt === '$211.60' && !!orderId, JSON.stringify(done).slice(0, 160));

  const db = JSON.parse(py(`
import json
from mongo_client import db
o = db.orders.find_one({'id': ${orderId}, 'business_id': '${BID}'}, {'_id': 0})
cc = list(db.chamcong.find({'business_id': '${BID}', 'ghi_chu': {'$regex': r'^\\[SPA POS\\] Order #${orderId}(?!\\d)'}}, {'_id': 0, 'ma_nv': 1, 'tien_tua': 1, 'tien_tips': 1}))
c = db.customers.find_one({'business_id': '${BID}', 'phone': '${PHONE}'}, {'_id': 0, 'name': 1, 'id': 1})
le = db.loyalty_events.find_one({'business_id': '${BID}', 'customer_id': c and c.get('id')}, {'_id': 0, 'message': 1})
print(json.dumps({'total': o and o['total_amount'], 'pm': o and o['payment_method'], 'tip': o and o['metadata'].get('tip_amount'), 'cc': cc, 'cust': c, 'msg': le and le.get('message')}))`));
  const tipSum = Math.round(db.cc.reduce((a, x) => a + (x.tien_tips || 0), 0) * 100) / 100;
  rec('DB: bill $211.60, thẻ, tip $27.60', db.total === 211.6 && db.pm === 'card' && db.tip === 27.6, JSON.stringify({ total: db.total, pm: db.pm, tip: db.tip }));
  rec('DB: tip chia cho kỹ thuật viên theo phần doanh thu, tổng đúng $27.60', db.cc.length >= 1 && tipSum === 27.6 && (db.cc.length === 1 || db.cc.every((x) => x.tien_tips > 0)), JSON.stringify(db.cc));
  rec('DB: khách mới lưu đúng tên nhập ("QA Spa Client", không phải "Khách 1234")', db.cust && db.cust.name === 'QA Spa Client', JSON.stringify(db.cust));
  rec('Tin cảm ơn/điểm thưởng cho khách tiệm Úc viết tiếng Anh', /^Thanks for visiting/.test(db.msg || ''), db.msg);

  // hoàn tiền toàn bộ -> thu hồi cả hoa hồng lẫn tip
  const rf = await p.evaluate(async (id) => (await fetch(`/api/orders/${id}/refund`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ amount: 211.6, reason: 'QA spa e2e' }) })).json(), orderId);
  const claw = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps(list(db.chamcong.find({'business_id': '${BID}', 'ghi_chu': {'$regex': r'^\\[REFUND\\] Deduction for Order #${orderId}(?!\\d)'}}, {'_id': 0, 'tien_tua': 1, 'tien_tips': 1}))))`));
  const clawTip = Math.round(claw.reduce((a, x) => a + (x.tien_tips || 0), 0) * 100) / 100;
  rec('Hoàn tiền 100% thu hồi cả tip (−$27.60)', rf.success && clawTip === -27.6, JSON.stringify({ ok: rf.success, claw }));

  // xoá dịch vụ: link GET cũ không còn tác dụng
  const getDel = await p.evaluate(async () => (await fetch('/delete_spa/999999', { redirect: 'manual' })).status);
  rec('Xoá dịch vụ bằng GET bị từ chối (405)', getDel === 405, 'HTTP ' + getDel);
  await p.click('#editBtn');
  rec('"Edit list" hiện nút Remove trên từng thẻ', await p.evaluate(() => [...document.querySelectorAll('.tile-del')].every((x) => !x.hidden)));
  await p.click('#editBtn');
  await p.click('#newBtn');
  rec('"New sale" về phiếu trống', await p.evaluate(() => document.querySelectorAll('.line').length === 0 && !document.getElementById('ticketMain').hidden));
  // tiếng Việt
  await p.click('#langBtn');
  const vi = await p.evaluate(() => ({ sub: document.querySelector('.sub').textContent, charge: document.querySelector('#chargeBtn [data-t]').textContent }));
  rec('Chuyển tiếng Việt', vi.sub === 'Quầy lễ tân · POS Spa' && vi.charge === 'Thu', JSON.stringify(vi));
  await p.click('#langBtn');
  rec('Không lỗi JS (máy tính)', errs.length === 0, errs.join(' | '));
  await ctx.close();

  // ---------- iPhone ----------
  const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
  const m = await b.newContext({ ...iphone, locale: 'en-AU', timezoneId: 'Australia/Sydney' });
  await m.addInitScript(() => { try { localStorage.setItem('bitpaw_lang', 'en'); } catch (e) {} });
  const mp = await login(m); const merrs = []; mp.on('pageerror', (e) => merrs.push(e.message));
  await mp.goto(BASE + '/spa', { waitUntil: 'networkidle' });
  const m1 = await mp.evaluate(() => ({ ov: document.documentElement.scrollWidth - innerWidth, bar: document.getElementById('barText').textContent,
    add: document.querySelector('.tile .add-ic').getBoundingClientRect().height }));
  rec('iPhone: không tràn ngang, nút + cao ≥ 44px, thanh "Ticket is empty"', m1.ov <= 1 && m1.add >= 44 && /empty/i.test(m1.bar), JSON.stringify(m1));
  await mp.click('.tile[data-name="Hot Stone Therapy"] .tile-hit');
  const m2 = await mp.evaluate(() => document.getElementById('barText').textContent + ' ' + document.getElementById('barTotal').textContent);
  rec('iPhone: thêm 1 liệu trình -> thanh dưới "View ticket · 1 item $110.00"', /View ticket · 1 item/.test(m2) && /\$110\.00/.test(m2), m2);
  await mp.click('#sheetBar'); await mp.waitForTimeout(400);
  const m3 = await mp.evaluate(() => { const r = document.getElementById('chargeBtn').getBoundingClientRect(); return { open: document.getElementById('ticket').classList.contains('open'), inView: r.bottom <= innerHeight && r.top >= 0, h: r.height }; });
  rec('iPhone: mở phiếu thu, nút Charge nằm trong màn hình, cao ≥ 48px', m3.open && m3.inView && m3.h >= 48, JSON.stringify(m3));
  await mp.click('#closeSheet');
  rec('Không lỗi JS (iPhone)', merrs.length === 0, merrs.join(' | '));
  await m.close();
} finally {
  // dọn dữ liệu test
  if (orderId) {
    console.log('cleanup', py(`
from mongo_client import db
import re
oid = ${orderId}
ids = [oid] + [o['id'] for o in db.orders.find({'business_id': '${BID}', 'metadata.original_order_id': oid}, {'id': 1})]
cids = [c['id'] for c in db.customers.find({'business_id': '${BID}', 'phone': '${PHONE}'}, {'id': 1})]
r = {
 'loyalty_by_id': db.loyalty_events.delete_many({'business_id': '${BID}', 'customer_id': {'$in': cids}}).deleted_count,
 'orders': db.orders.delete_many({'business_id': '${BID}', 'id': {'$in': ids}}).deleted_count,
 'items': db.order_items.delete_many({'order_id': {'$in': ids}}).deleted_count,
 'tx': db.transactions.delete_many({'business_id': '${BID}', '$or': [{'order_id': {'$in': ids}}, {'reference_id': {'$in': ids}}]}).deleted_count,
 'cc': db.chamcong.delete_many({'business_id': '${BID}', 'ghi_chu': {'$regex': r'(SPA POS|REFUND)\\] (Order|Deduction for Order) #' + str(oid) + r'(?!\\d)'}}).deleted_count,
 'cust': db.customers.delete_many({'business_id': '${BID}', 'phone': '${PHONE}'}).deleted_count,
 'loyalty': db.loyalty_events.delete_many({'business_id': '${BID}', 'customer_phone': '${PHONE}'}).deleted_count,
}
print(r)`));
  }
  await b.close();
  const fail = steps.filter((s) => !s.ok).length;
  console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
  process.exitCode = fail ? 1 : 0;
}
