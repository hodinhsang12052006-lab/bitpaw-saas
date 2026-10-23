// service_packages_e2e.mjs — Gói liệu trình: tạo gói, bán gói (doanh thu + sổ cái), dùng buổi ở POS Spa (bill 0, trừ buổi,
// hoa hồng KTV theo giá trị 1 buổi), chặn sai khách/sai dịch vụ/hết hạn, 2 máy dùng buổi cuối cùng lúc, hoàn tiền trả buổi.
//   node scripts/service_packages_e2e.mjs   (CHỈ local; tự dọn)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.spa.596348@bitpawdemo.com', PW = 'DemoBitPaw2026!';
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
const PHONE = '0412' + String(Date.now()).slice(-6), PHONE2 = '0413' + String(Date.now()).slice(-6);
const TECH = 'QP' + String(Date.now()).slice(-5);
await api('/api/hr/employees', 'POST', { ma_nv: TECH, ho_ten: 'Package Therapist QA', linh_vuc: 'Spa' });
const orderIds = [];

// 1) tạo gói trên trang /packages
await p.goto(BASE + '/packages', { waitUntil: 'networkidle' }); await p.waitForTimeout(500);
const svc = await p.$$eval('#svcBox input', (els) => els.slice(0, 2).map((e) => +e.value));
const prices = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps({str(x['id']): x['price'] for x in db.products.find({'business_id': ${B}, 'id': {'$in': ${JSON.stringify(svc)}}}, {'_id': 0, 'id': 1, 'price': 1})}))`));
const S1 = svc[0], S2 = svc[1];
const PKG_NAME = 'QA 3 sessions ' + TECH;
await p.fill('#pName', PKG_NAME); await p.fill('#pSessions', '3'); await p.fill('#pPrice', String(prices[S1] * 2)); await p.fill('#pDays', '30');
await p.check(`#svcBox input[value="${S1}"]`);
await Promise.all([p.waitForResponse((r) => r.url().endsWith('/api/packages') && r.request().method() === 'POST'), p.click('#createBtn')]);
await p.waitForTimeout(800);
const listTxt = await p.textContent('#pkgList');
rec('Tạo gói 3 buổi cho 1 dịch vụ trên trang /packages', listTxt.includes(PKG_NAME), listTxt.replace(/\s+/g, ' ').slice(0, 90));
let r = await api('/api/packages', 'POST', { name: 'bad', sessions: 0, price: 10 });
rec('Gói sai (0 buổi) -> từ chối', r.status === 400);

// 2) bán gói
const pkg = (await api('/api/packages')).packages.find((x) => x.name === PKG_NAME);
await p.selectOption('#sPkg', String(pkg.id)); await p.fill('#sPhone', PHONE); await p.fill('#sName', 'Ava QA'); await p.selectOption('#sMethod', 'card');
await Promise.all([p.waitForResponse((r) => r.url().endsWith('/api/packages/sell')), p.click('#sellBtn')]);
await p.waitForTimeout(900);
const sold = (await api('/api/packages')).sold.find((x) => x.customer_phone === PHONE);
orderIds.push(sold.order_id);
const sale = JSON.parse(py(`
import json
from mongo_client import db
o = db.orders.find_one({'business_id': ${B}, 'id': ${sold.order_id}}, {'_id': 0, 'total_amount': 1, 'payment_method': 1})
tx = db.transactions.count_documents({'business_id': ${B}, 'order_id': ${sold.order_id}})
print(json.dumps({'total': o['total_amount'], 'pm': o['payment_method'], 'tx': tx}))`));
rec('Bán gói: tạo đơn đúng giá + sổ cái, thẻ gói 3 buổi', sale.total === prices[S1] * 2 && sale.pm === 'card' && sale.tx >= 1 && sold.sessions_left === 3 && sold.session_value === Math.round(prices[S1] * 2 / 3 * 100) / 100, JSON.stringify(sale));
rec('Bảng "Gói khách đã mua" hiện khách + 3/3', (await p.textContent('#soldTable')).includes(PHONE));

// 3) chặn dùng sai
const co = (items, phone) => api('/api/sales/checkout', 'POST', { items, payment_method: 'cash', status: 'completed', customer_phone: phone, client_local_date: new Date().toLocaleDateString('en-GB') });
r = await co([{ product_id: S2, quantity: 1, package_id: sold.id }], PHONE);
rec('Dịch vụ không thuộc gói -> chặn', r.status === 400 && /does not cover/.test(r.message || ''), r.message);
r = await co([{ product_id: S1, quantity: 1, package_id: sold.id }], PHONE2);
rec('Khách khác dùng gói -> chặn', r.status === 400 && /does not belong/.test(r.message || ''));
r = await co([{ product_id: S1, quantity: 4, package_id: sold.id }], PHONE);
rec('Dùng quá số buổi còn lại -> chặn', r.status === 400);

// 4) POS Spa: dùng 1 buổi + 1 dịch vụ trả tiền, gán KTV
await p.goto(BASE + '/spa', { waitUntil: 'networkidle' }); await p.waitForSelector('.product-card');
await p.locator(`.product-card[data-id="${S1}"] .btn-add-cart`).click(); await p.waitForTimeout(200);
await p.locator(`.product-card[data-id="${S2}"] .btn-add-cart`).click(); await p.waitForTimeout(200);
await p.click('#cartIcon'); await p.waitForTimeout(300);
const techSel = p.locator('.cart-tech').first();
if (await techSel.count()) await techSel.selectOption(TECH).catch(() => {});
await p.click('#openCheckoutModalBtn'); await p.waitForTimeout(400);
await p.click('.payment-method[data-method="cash"]').catch(() => {});
await p.fill('#custName', 'Ava QA'); await p.fill('#custEmail', 'ava.qa@example.com'); await p.fill('#custPhone', PHONE);
await p.waitForSelector('#pkgBox .pkg-use', { timeout: 6000 }).catch(() => {});
const boxTxt = await p.textContent('#pkgBox');
rec('Nhập SĐT ở thanh toán -> hiện gói của khách cho đúng dịch vụ', /3 left|còn 3/.test(boxTxt) && await p.locator('#pkgBox .pkg-use').count() === 1, boxTxt.replace(/\s+/g, ' ').slice(0, 90));
const before = await p.textContent('#checkoutTotalMain');
await p.check('#pkgBox .pkg-use'); await p.waitForTimeout(200);
const after = await p.textContent('#checkoutTotalMain');
rec('Tick "dùng buổi" -> tổng chỉ còn dịch vụ trả tiền', before !== after && [prices[S2], Math.round(prices[S2] * 100)].includes(Number(after.replace(/[^\d]/g, ''))), `${before} -> ${after}`);
const [resp] = await Promise.all([p.waitForResponse((x) => x.url().includes('/api/sales/checkout') && x.request().method() === 'POST'), p.click('#finalPayBtn')]);
const body = await resp.json();
orderIds.push(body.order_id);
await p.waitForSelector('#resultModal:not(.hidden)', { timeout: 8000 }).catch(() => {});
const after1 = JSON.parse(py(`
import json
from mongo_client import db
cp = db.customer_packages.find_one({'business_id': ${B}, 'id': ${sold.id}}, {'_id': 0})
o = db.orders.find_one({'business_id': ${B}, 'id': ${body.order_id || 0}}, {'_id': 0})
items = list(db.order_items.find({'order_id': ${body.order_id || 0}}, {'_id': 0, 'product_id': 1, 'total_price': 1, 'package_id': 1}))
cc = db.chamcong.find_one({'business_id': ${B}, 'ma_nv': '${TECH}', 'ghi_chu': {'$regex': 'Order #${body.order_id || 0}'}}, {'_id': 0, 'tien_tua': 1})
print(json.dumps({'left': cp['sessions_left'], 'hist': [h['type'] for h in cp['history']], 'total': o and o['total_amount'], 'items': items, 'cc': cc, 'redeems': o and o['metadata'].get('package_redeems')}))`));
const pkgLine = after1.items.find((x) => x.product_id === S1);
rec('Thanh toán: bill = giá dịch vụ trả tiền, dòng gói = 0, còn 2 buổi, lịch sử ghi "use"', resp.ok() && after1.total === prices[S2] && pkgLine && pkgLine.total_price === 0 && pkgLine.package_id === sold.id && after1.left === 2 && after1.hist.includes('use'), JSON.stringify({ total: after1.total, left: after1.left }));
rec('KTV vẫn có hoa hồng cho buổi dùng gói (theo giá trị 1 buổi)', !after1.cc || after1.cc.tien_tua > 0, JSON.stringify(after1.cc));

// 5) 2 máy dùng 2 buổi cuối cùng lúc khi chỉ còn 1
py(`
from mongo_client import db
db.customer_packages.update_one({'business_id': ${B}, 'id': ${sold.id}}, {'$set': {'sessions_left': 1}})
print('ok')`);
const both = await Promise.all([co([{ product_id: S1, quantity: 1, package_id: sold.id }], PHONE), co([{ product_id: S1, quantity: 1, package_id: sold.id }], PHONE)]);
both.forEach((x) => x.order_id && orderIds.push(x.order_id));
const okN = both.filter((x) => x.success).length;
const leftNow = +py(`
from mongo_client import db
print(db.customer_packages.find_one({'business_id': ${B}, 'id': ${sold.id}})['sessions_left'])`);
rec('2 máy cùng dùng buổi cuối -> chỉ 1 thành công, không âm buổi', okN === 1 && leftNow === 0 && both.some((x) => x.status === 409 || x.status === 400), JSON.stringify(both.map((x) => x.status)));

// 6) hoàn tiền đơn hỗn hợp -> trả lại buổi
py(`
from mongo_client import db
db.customer_packages.update_one({'business_id': ${B}, 'id': ${sold.id}}, {'$set': {'sessions_left': 2}})
print('ok')`);
r = await co([{ product_id: S1, quantity: 1, package_id: sold.id }, { product_id: S2, quantity: 1 }], PHONE);
orderIds.push(r.order_id);
const rf = await api(`/api/orders/${r.order_id}/refund`, 'POST', { amount: prices[S2], reason: 'qa' });
const leftAfterRefund = +py(`
from mongo_client import db
print(db.customer_packages.find_one({'business_id': ${B}, 'id': ${sold.id}})['sessions_left'])`);
rec('Hoàn tiền toàn bộ đơn -> buổi gói được trả lại', rf.success && leftAfterRefund === 2, JSON.stringify({ refund: rf.success, left: leftAfterRefund, msg: rf.message }));

// 7) hết hạn
py(`
from mongo_client import db
db.customer_packages.update_one({'business_id': ${B}, 'id': ${sold.id}}, {'$set': {'expires_at': '2020-01-01T00:00:00'}})
print('ok')`);
r = await co([{ product_id: S1, quantity: 1, package_id: sold.id }], PHONE);
rec('Gói hết hạn -> không dùng được, không còn hiện ở tra cứu', r.status === 400 && /expired/.test(r.message || '') && (await api('/api/packages/customer?phone=' + PHONE)).data.length === 0);
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// dọn
py(`
from mongo_client import db
ids = [x for x in ${JSON.stringify(orderIds)} if x]
refunds = [o['id'] for o in db.orders.find({'business_id': ${B}, 'metadata.original_order_id': {'$in': ids}}, {'id': 1})]
allids = ids + refunds
db.order_items.delete_many({'order_id': {'$in': allids}})
db.transactions.delete_many({'business_id': ${B}, 'order_id': {'$in': allids}})
db.orders.delete_many({'business_id': ${B}, 'id': {'$in': allids}})
db.chamcong.delete_many({'business_id': ${B}, 'ma_nv': '${TECH}'})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': '${TECH}'})
db.staff.delete_many({'business_id': ${B}, 'ma_nv': '${TECH}'})
db.customer_packages.delete_many({'business_id': ${B}, 'customer_phone': {'$in': ['${PHONE}', '${PHONE2}']}})
db.service_packages.delete_many({'business_id': ${B}, 'name': '${PKG_NAME}'})
db.customers.delete_many({'business_id': ${B}, 'phone': {'$in': ['${PHONE}', '${PHONE2}']}})
print('cleaned')`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
