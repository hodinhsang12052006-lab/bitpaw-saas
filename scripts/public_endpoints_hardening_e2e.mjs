// public_endpoints_hardening_e2e.mjs — Pha 28: các trang/API KHÔNG cần đăng nhập mà khách của quán dùng
// (menu QR tại bàn, gọi nhân viên, đặt bàn/phòng). Kiểm: id bàn số (đoán được) bị từ chối với người lạ, chỉ mã QR ngẫu nhiên
// dùng được; form đặt chỗ chặn tiệm bịa, bẫy bot, ngày giờ sai, trường quá dài, gửi dồn dập; trang hiện TÊN QUÁN + đúng ngôn ngữ.
//   node scripts/public_endpoints_hardening_e2e.mjs   (CHỈ local; IP thử 198.18.x.x; tự dọn dữ liệu)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const FNB = '39821fa8-e42a-4052-bc9d-eb061eaaae11';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const TAG = String(Date.now()).slice(-6);
const RUN = (Number(TAG) % 200) + 20;
const IP = (n) => `198.18.${RUN}.${n}`;
const NAME = `PubSec ${TAG}`;
const START = new Date().toISOString().slice(0, 19);

const table = JSON.parse(py(`
import json
from mongo_client import db
t = db.dining_tables.find_one({'business_id': '${FNB}'}, {'_id': 0, 'id': 1, 'qr_token': 1, 'name': 1}, sort=[('id', 1)])
print(json.dumps(t))`));

let cleaned = false;
const cleanup = () => {
  if (cleaned) return; cleaned = true;
  console.log(py(`
from mongo_client import db
ips = ['198.18.${RUN}.%d' % i for i in range(1, 60)]
a = db.table_reservations.delete_many({'business_id': '${FNB}', 'customer_name': {'$regex': '^PubSec ${TAG}'}}).deleted_count
b = db.user_logs.delete_many({'business_id': '${FNB}', 'user_email': 'table_${table.id}', 'created_at': {'$gte': '${START}'}}).deleted_count
db.security_strikes.delete_many({'ip': {'$in': ips}}); db.security_events.delete_many({'ip': {'$in': ips}}); db.security_bans.delete_many({'ip': {'$in': ips}})
print('cleaned reservations', a, 'notify logs', b)`));
};
process.on('exit', cleanup);

const b = await chromium.launch({ channel: 'chrome' });
const ctxFor = (ip) => b.newContext({ extraHTTPHeaders: { 'X-Forwarded-For': ip }, locale: 'en-US' });

// ---- 1. Menu QR: id số đoán được không mở được với người lạ; mã QR thật thì được
let ctx = await ctxFor(IP(1)); let p = await ctx.newPage();
let res = await p.goto(`${BASE}/qr_menu/${table.id}`);
rec('Người lạ mở /qr_menu/<id số> -> 404 (không lộ mã QR của bàn)', res.status() === 404 && !(await p.content()).includes(table.qr_token));
res = await p.goto(`${BASE}/qr_menu/${table.qr_token}`, { waitUntil: 'networkidle' });
const menuHasShop = await p.innerText('h1').catch(() => '');
rec('Mã QR thật mở menu, đầu trang là TÊN QUÁN', res.status() === 200 && !/BitPaw/i.test(menuHasShop) && menuHasShop.length > 2, menuHasShop);
const api = async (url, body) => p.evaluate(async ([u, bd]) => {
  const r = await fetch(u, bd ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bd) } : {});
  return { s: r.status, j: await r.json().catch(() => ({})) };
}, [url, body]);

// ---- 2. API gọi món / gọi nhân viên / xem menu: chỉ nhận mã QR
let r = await api('/api/submit_qr_order', { table_id: table.id, items: [{ id: 1, quantity: 1 }], total: 1 });
rec('Gửi đơn bằng id bàn số (dò id 1..N vào bếp mọi quán) -> 404', r.s === 404, `HTTP ${r.s}`);
r = await api('/api/table/notify', { table_id: table.id, type: 'staff' });
rec('"Gọi nhân viên" bằng id bàn số -> 404', r.s === 404, `HTTP ${r.s}`);
r = await api(`/api/public/pos/products?table_id=${table.id}`);
rec('Xem menu bằng id bàn số -> 404', r.s === 404, `HTTP ${r.s}`);
r = await api(`/api/public/pos/products?table_id=${table.qr_token}&channel_type=retail`);
rec('Xem menu bằng mã QR -> 200', r.s === 200 && r.j.success === true, `HTTP ${r.s}`);
r = await api('/api/table/notify', { table_id: table.qr_token, type: 'staff', table_name: '<img src=x onerror=alert(1)>' });
const logName = py(`
from mongo_client import db
d = db.user_logs.find_one({'business_id': '${FNB}', 'user_email': 'table_${table.id}', 'created_at': {'$gte': '${START}'}}, {'_id': 0, 'description': 1})
print((d or {}).get('description', ''))`);
rec('"Gọi nhân viên" bằng mã QR -> 200; tên bàn lấy từ hệ thống, không lấy chữ khách gửi', r.s === 200 && !logName.includes('<img') && logName.includes(String(table.name)), logName);
await ctx.close();

// ---- 3. Form đặt bàn công khai
ctx = await ctxFor(IP(2)); p = await ctx.newPage();
res = await p.goto(`${BASE}/reserve/${FNB}`, { waitUntil: 'networkidle' });
const h1 = await p.innerText('h1'); const body = await p.innerText('body');
rec('Trang đặt bàn: tên QUÁN, tiếng Anh cho trình duyệt tiếng Anh, không còn số mẫu kiểu VN', res.status() === 200 && h1 !== 'BitPaw' && /Your name/.test(body) && !/09x+/.test(await p.content()), h1);
r = await api('/api/public/reservations/no-such-business-' + TAG, { name: NAME, phone: '0412 345 678', party_size: 2, reserved_time: '2030-01-01T19:00:00' });
rec('Đặt bàn vào mã tiệm bịa -> 404 (trước: ghi được đơn rác)', r.s === 404, `HTTP ${r.s}`);
const d = new Date(Date.now() + 3 * 864e5).toISOString().slice(0, 10);
r = await api(`/api/public/reservations/${FNB}`, { name: NAME + ' bot', phone: '0412 345 678', party_size: 2, reserved_time: `${d}T19:00:00`, company_website: 'http://spam.example' });
const botRows = Number(py(`
from mongo_client import db
print(db.table_reservations.count_documents({'business_id': '${FNB}', 'customer_name': '${NAME} bot'}))`));
rec('Bot điền ô bẫy -> "thành công" giả, không ghi đơn', r.s === 200 && r.j.id === 0 && botRows === 0);
r = await api(`/api/public/reservations/${FNB}`, { name: NAME, phone: '0412 345 678', party_size: 2, reserved_time: "2030-01-01T19:00:00'); DROP" });
rec('Ngày giờ sai định dạng -> 400', r.s === 400, `HTTP ${r.s}`);
r = await api(`/api/public/reservations/${FNB}`, { name: NAME, phone: '0412 345 678', party_size: 2, reserved_time: '2020-01-01T19:00:00' });
rec('Ngày đã qua -> 400', r.s === 400, `HTTP ${r.s}`);
r = await api(`/api/public/reservations/${FNB}`, { name: NAME, phone: 'abc', party_size: 2, reserved_time: `${d}T19:00:00` });
rec('SĐT không hợp lệ -> 400 (tiếng Anh)', r.s === 400 && /valid phone/i.test(r.j.message || ''), r.j.message);
r = await api(`/api/public/reservations/${FNB}`, { name: NAME + ' ' + 'x'.repeat(5000), phone: '0412 345 678', party_size: 99999, reserved_time: `${d}T19:00:00`, note: 'n'.repeat(20000) });
const row = JSON.parse(py(`
import json
from mongo_client import db
x = db.table_reservations.find_one({'business_id': '${FNB}', 'customer_name': {'$regex': '^${NAME} x'}}, {'_id': 0, 'customer_name': 1, 'party_size': 1, 'note': 1})
print(json.dumps({'n': len((x or {}).get('customer_name') or ''), 'p': (x or {}).get('party_size'), 'note': len((x or {}).get('note') or '')}))`));
rec('Trường quá dài bị cắt (tên 80, ghi chú 500), số khách tối đa 200', r.s === 200 && row.n === 80 && row.note === 500 && row.p === 200, JSON.stringify(row));
await ctx.close();

// ---- 4. Gửi dồn dập: 20 lượt/giờ/IP
ctx = await ctxFor(IP(3)); p = await ctx.newPage();
await p.goto(`${BASE}/reserve/${FNB}`);
let codes = [];
for (let i = 0; i < 22; i++) codes.push((await api(`/api/public/reservations/${FNB}`, { name: '', phone: '' })).s);
rec('Lượt thứ 21 trong 1 giờ từ cùng IP -> 429', codes.slice(0, 20).every((c) => c === 400) && codes[20] === 429, codes.slice(18).join(','));
await ctx.close();

// ---- 5. Trang đặt chỗ của tiệm không tồn tại; karaoke / khách sạn mang tên quán
ctx = await ctxFor(IP(4)); p = await ctx.newPage();
res = await p.goto(`${BASE}/hotel/reserve/no-such-business-${TAG}`);
rec('Trang đặt phòng của tiệm không tồn tại -> 404 "Business not found"', res.status() === 404 && /Business not found/.test(await p.innerText('body')));
res = await p.goto(`${BASE}/karaoke/reserve/0cc47d38-b306-46f3-9da1-cdf2d840d79b`);
const kh1 = await p.innerText('h1');
res = await p.goto(`${BASE}/hotel/reserve/885e1075-9191-4b1e-91ee-d100e961257d`);
const hh1 = await p.innerText('h1');
rec('Trang đặt phòng karaoke / khách sạn hiện tên quán', kh1 !== 'BitPaw' && hh1 !== 'BitPaw' && kh1.length > 2 && hh1.length > 2, `${kh1} | ${hh1}`);
await ctx.close();
await b.close();

cleanup();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\n${steps.length - fail}/${steps.length} PASS`);
process.exit(fail ? 1 : 0);
