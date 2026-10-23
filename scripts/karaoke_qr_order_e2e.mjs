// karaoke_qr_order_e2e.mjs — Karaoke: gọi món tại phòng (nhân viên + khách quét QR), bill = tiền giờ + món, trừ kho.
//   node scripts/karaoke_qr_order_e2e.mjs      (CHỈ server local; dọn sạch sau khi chạy)
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.karaoke.071443@bitpawdemo.com', PW = 'DemoBitPaw2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1366, height: 900 } });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const api = (url, method = 'GET', body) => p.evaluate(async ([u, m, bd]) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, method, body]);
const ROOM = 4;  // Phòng Đôi — 120.000đ/giờ
const stock0 = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps({str(x['id']): x.get('stock', 0) for x in db.products.find({'business_id': ${B}, 'id': {'$in': [229, 231]}}, {'_id': 0, 'id': 1, 'stock': 1})}))`));
py(`
from mongo_client import db
db.karaoke_rooms.update_one({'business_id': ${B}, 'id': ${ROOM}}, {'$set': {'status': 'Trống', 'start_time': None}})
db.karaoke_room_items.delete_many({'business_id': ${B}, 'room_id': ${ROOM}, 'order_id': None})
print('ok')`);

// link QR trước khi mở phòng
let rooms = await api('/api/karaoke/rooms');
let room = (rooms.data || []).find((r) => r.id === ROOM);
const orderUrl = room.order_url;
rec('Mỗi phòng có link QR gọi món có chữ ký', /\/karaoke\/order\/.+\/4\/[0-9a-f]{16}$/.test(orderUrl || ''), orderUrl);
const path = new URL(orderUrl).pathname;
const tok = path.split('/').pop();
const postUrl = `/api/public/karaoke_order/${bid}/${ROOM}/${tok}`;

// khách gọi khi phòng chưa mở -> 409; link giả -> 404
const anon = await b.newContext(); const ap = await anon.newPage();
const pub = (url, body) => ap.evaluate(async ([u, bd]) => { const r = await fetch(u, { method: bd ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, body]);
await ap.goto(BASE + '/landing');
let r = await pub(postUrl, { items: [{ product_id: 229, qty: 1 }] });
rec('Phòng chưa mở -> khách chưa gọi được (409)', r.status === 409);
r = await pub(`/api/public/karaoke_order/${bid}/${ROOM}/0000000000000000`, { items: [{ product_id: 229, qty: 1 }] });
rec('Link QR giả -> chặn (404)', r.status === 404);
r = await pub(`/api/public/karaoke_order/${bid}/${ROOM + 1}/${tok}`, { items: [{ product_id: 229, qty: 1 }] });
rec('Dùng mã phòng này cho phòng khác -> chặn (404)', r.status === 404);

// mở phòng, lùi giờ bắt đầu 70 phút (-> làm tròn 75 phút)
await api(`/api/karaoke/rooms/${ROOM}/start`, 'POST');
py(`
from datetime import datetime, timedelta
from mongo_client import db
db.karaoke_rooms.update_one({'business_id': ${B}, 'id': ${ROOM}}, {'$set': {'start_time': (datetime.now() - timedelta(minutes=70)).strftime('%Y-%m-%d %H:%M:%S')}})
print('ok')`);

// nhân viên thêm 2 lon bia; khách quét QR (iPhone) gọi 1 trái cây + 1 bia
r = await api(`/api/karaoke/rooms/${ROOM}/items`, 'POST', { items: [{ product_id: 229, qty: 2 }] });
rec('Nhân viên thêm món cho phòng (giá lấy ở máy chủ)', r.success && r.items_total === 50000, `tổng món ${r.items_total}`);
r = await api(`/api/karaoke/rooms/${ROOM}/items`, 'POST', { items: [{ product_id: 234, qty: 1 }] });
rec('Không thêm được "Phí giờ" như 1 món (chống tính 2 lần)', r.status === 400);
{
  const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
  const m = await (await b.newContext(iphone)).newPage(); const merr = []; m.on('pageerror', (e) => merr.push(e.message));
  await m.goto(orderUrl, { waitUntil: 'networkidle' });
  const hdr = await m.textContent('header h1');
  const rowF = m.locator('.item[data-id="231"]'); const rowB = m.locator('.item[data-id="229"]');
  await rowF.locator('.plus').click(); await rowB.locator('.plus').click();
  const total = await m.textContent('#total');
  await m.click('#sendBtn'); await m.waitForSelector('#sentNote:not([hidden])', { timeout: 8000 }).catch(() => {});
  const note = await m.textContent('#sentNote'); const ordered = await m.textContent('#ordered').catch(() => '');
  const ov = await m.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  rec('Khách quét QR trên iPhone — chọn món, thấy tổng, gửi được', /Phòng Đôi/.test(hdr) && /145\.000/.test(total) && /Đã gửi/.test(note) && /Trái cây/.test(ordered) && ov <= 1 && merr.length === 0, `${hdr.trim()} · ${total} · ${note.slice(0, 40)}`);
  await m.screenshot({ path: 'audit-results/screenshots/karaoke_qr_order_iphone.png' }).catch(() => {});
  await m.context().close();
}
rooms = await api('/api/karaoke/rooms'); room = rooms.data.find((x) => x.id === ROOM);
rec('Màn quầy thấy món mới qua QR + tổng món', room.new_qr_orders === 2 && room.items_total === 195000 && room.items_count === 4, JSON.stringify({ new: room.new_qr_orders, total: room.items_total, n: room.items_count }));

// giao diện màn quầy
await p.goto(BASE + '/karaoke', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
const card = await p.locator(`.glass-card[data-room-id="${ROOM}"]`).innerText();
rec('Thẻ phòng hiện 4 món · 195.000 ₫ + món mới qua QR + đã hát 70 phút', /4 (món|items)/.test(card) && /195\.000/.test(card) && /(qua|via) QR/.test(card) && /1 (giờ|hr|h)\w* 1\d/.test(card), card.replace(/\s+/g, ' ').slice(0, 140));
await p.locator(`.glass-card[data-room-id="${ROOM}"] button:has-text("QR")`).click(); await p.waitForTimeout(500);
rec('Nút QR hiện mã QR in được', await p.locator('#qrBox svg').count() === 1 && (await p.textContent('#qrUrl')).includes(tok));
await p.click('#qrCloseLbl');
await p.locator(`.glass-card[data-room-id="${ROOM}"] button[onclick^="openItems"]`).click(); await p.waitForTimeout(600);
const list = await p.textContent('#itemsList');
rec('Hộp món hiện đủ món + đánh dấu (QR)', /Bia Tiger/.test(list) && /Trái cây/.test(list) && /\(QR\)/.test(list), list.replace(/\s+/g, ' ').slice(0, 100));
await p.evaluate(() => closeItems()); await p.waitForTimeout(500);

// tính tiền: 75 phút x 120.000 = 150.000 + món 195.000 = 345.000
await p.locator(`.glass-card[data-room-id="${ROOM}"] .checkout-room`).click(); await p.waitForTimeout(400);
const modal = await p.textContent('#checkoutModal');
rec('Hộp thanh toán tách tiền giờ + tiền món, tổng đúng', /150\.000/.test(modal) && /195\.000/.test(modal) && /345\.000/.test(await p.textContent('#modalAmount')), (await p.textContent('#modalAmount')).trim());
const [resp] = await Promise.all([p.waitForResponse((x) => x.url().endsWith(`/api/karaoke/rooms/${ROOM}/checkout`)), p.click('#confirmCheckoutBtn')]);
const co = await resp.json();
rec('Máy chủ tính: giờ 150.000 + món 195.000 = 345.000', co.success && co.time_amount === 150000 && co.items_amount === 195000 && co.total_amount === 345000 && co.items.length === 3, JSON.stringify({ t: co.time_amount, i: co.items_amount, total: co.total_amount }));
const db1 = JSON.parse(py(`
import json
from mongo_client import db
o = db.orders.find_one({'business_id': ${B}, 'id': ${co.order_id}}, {'_id': 0, 'total_amount': 1})
items = list(db.order_items.find({'business_id': ${B}, 'order_id': ${co.order_id}}, {'_id': 0, 'product_id': 1, 'quantity': 1, 'total_price': 1}))
tx = db.transactions.count_documents({'business_id': ${B}, 'order_id': ${co.order_id}})
left = db.karaoke_room_items.count_documents({'business_id': ${B}, 'room_id': ${ROOM}, 'order_id': None})
st = {str(x['id']): x.get('stock', 0) for x in db.products.find({'business_id': ${B}, 'id': {'$in': [229, 231]}}, {'_id': 0, 'id': 1, 'stock': 1})}
print(json.dumps({'total': o['total_amount'], 'lines': len(items), 'sum': sum(i['total_price'] for i in items), 'tx': tx, 'left': left, 'stock': st}))`));
rec('Đơn hàng: 4 dòng (giờ + 3 món) khớp tổng, có giao dịch sổ quỹ', db1.total === 345000 && db1.lines === 4 && db1.sum === 345000 && db1.tx >= 1, JSON.stringify(db1));
rec('Món đã tính tiền không còn treo ở phòng; kho tự trừ (bia -3, trái cây -1)', db1.left === 0 && db1.stock['229'] === stock0['229'] - 3 && db1.stock['231'] === stock0['231'] - 1, JSON.stringify({ before: stock0, after: db1.stock }));
r = await pub(postUrl);
rec('Sau khi tính tiền: link QR không còn lộ món của khách trước', r.success && r.items.length === 0 && r.open === false);
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// dọn
py(`
from mongo_client import db
oid = ${co.order_id || 0}
db.order_items.delete_many({'business_id': ${B}, 'order_id': oid}); db.transactions.delete_many({'business_id': ${B}, 'order_id': oid}); db.orders.delete_many({'business_id': ${B}, 'id': oid})
db.karaoke_room_items.delete_many({'business_id': ${B}, 'room_id': ${ROOM}})
for pid, st in ${JSON.stringify(stock0)}.items(): db.products.update_one({'business_id': ${B}, 'id': int(pid)}, {'$set': {'stock': st}})
print('cleaned')`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
