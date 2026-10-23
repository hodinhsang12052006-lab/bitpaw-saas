// POS Spa: gán kỹ thuật viên cho TỪNG dịch vụ -> hoa hồng vào chấm công/bảng lương; tiền tệ đúng của tiệm; tiền mặt ghi
// "đã thu" (có giao dịch, cộng điểm); không còn chờ giả 2 giây; hoàn tiền tự thu hồi hoa hồng. Dọn dữ liệu thử cuối bài.
//   DEVICE=desktop|mobile node scripts/spa_therapist_pos_e2e.mjs     (CHỈ server local)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import { ownerContextOptions, DEVICE } from './lib/device.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.spa.596348@bitpawdemo.com';
const py = (code) => JSON.parse(execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop());
const results = [];
const rec = (name, ok, note = '') => { results.push({ name, ok }); console.log(`${ok ? '✅' : '❌'} [${DEVICE}] ${name}${note ? ' — ' + note : ''}`); };
const PHONE = '0493' + String(Date.now()).slice(-6);

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await browser.newContext(ownerContextOptions());
const page = await ctx.newPage();
const errs = [];
page.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
let orderId = null;
try {
  await page.goto(BASE + '/login');
  await page.fill('#loginEmail', EMAIL); await page.fill('#loginPassword', 'DemoBitPaw2026!');
  await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
  await page.goto(BASE + '/spa', { waitUntil: 'networkidle' });
  const cards = page.locator('.product-card');
  for (let i = 0; i < 2; i++) { await cards.nth(i).locator('.btn-add-cart').click(); await page.waitForTimeout(250); }
  await page.click('#cartIcon'); await page.waitForTimeout(400);
  const sel = page.locator('#cartItemsList .cart-tech');
  const n = await sel.count();
  rec('Mỗi dịch vụ trong giỏ có ô chọn kỹ thuật viên', n === 2, `${n} ô`);
  const techs = await sel.first().locator('option').evaluateAll((os) => os.map((o) => o.value).filter(Boolean));
  await sel.nth(0).selectOption(techs[0]); await sel.nth(1).selectOption(techs[1] || techs[0]);
  const cartTxt = await page.locator('#cartItemsList').innerText();
  const totalTxt = await page.locator('#cartTotal, [id*="cartTotal"]').first().innerText().catch(() => '');
  rec('Giỏ hàng ghi đúng tiền tệ của tiệm ($, không phải ₫)', /\$\d/.test(cartTxt) && !/₫/.test(cartTxt + totalTxt), `tổng ${totalTxt}`);
  await page.click('#openCheckoutModalBtn'); await page.waitForTimeout(400);
  const mainTotal = await page.locator('#checkoutTotalMain').innerText();
  const vndSel = await page.locator('#currencySelector').isVisible();
  rec('Hộp thanh toán: tổng bằng $ của tiệm, không quy đổi VND/USD', /^\$\d/.test(mainTotal) && !vndSel, mainTotal);
  await page.click('.payment-method[data-method="cash"]');
  await page.fill('#custName', 'QA Spa Therapist Khach'); await page.fill('#custEmail', 'qa.spa.therapist@example.com'); await page.fill('#custPhone', PHONE);
  const t0 = Date.now();
  const [resp] = await Promise.all([page.waitForResponse((r) => r.url().includes('/api/sales/checkout'), { timeout: 15000 }), page.click('#finalPayBtn')]);
  const body = await resp.json();
  const ms = Date.now() - t0;
  orderId = body.order_id;
  await page.waitForSelector('#resultModal:not(.hidden)', { timeout: 8000 }).catch(() => {});
  rec('Thanh toán tiền mặt xong ngay (không còn chờ giả 2 giây)', body.success && ms < 1900, `${ms} ms · order #${orderId}`);
  const st = py(`
import json
from mongo_client import db
bid = db.users.find_one({'email': '${EMAIL}'})['business_id']
o = db.orders.find_one({'business_id': bid, 'id': ${orderId}}, {'_id': 0})
cc = list(db.chamcong.find({'business_id': bid, 'ghi_chu': {'$regex': r'^\\[SPA POS\\] Order #${orderId}(?!\\d)'}}, {'_id': 0}))
items = list(db.order_items.find({'order_id': ${orderId}}, {'_id': 0}))
from app import _get_business_commission_rate
rate = float(_get_business_commission_rate(bid))
exp = {}
for it in items:
    exp[it.get('ma_nv')] = exp.get(it.get('ma_nv'), 0) + it['total_price'] * rate / 100
print(json.dumps({'status': o['status'], 'tx': db.transactions.count_documents({'business_id': bid, 'order_id': ${orderId}}),
  'cc': [(r['ma_nv'], r['tien_tua']) for r in cc], 'exp': {k: round(v, 2) for k, v in exp.items()}, 'rate': rate,
  'cust': (db.customers.find_one({'business_id': bid, 'phone': '${PHONE}'}, {'_id': 0, 'loyalty_points': 1}) or {}).get('loyalty_points')}))
`);
  rec('Bill tiền mặt ghi "đã thu" + có giao dịch + khách được cộng điểm', st.status === 'completed' && st.tx === 1 && st.cust > 0, `status=${st.status} tx=${st.tx} điểm=${st.cust}`);
  const okComm = st.cc.length === Object.keys(st.exp).length && st.cc.every(([m, v]) => Math.abs(v - st.exp[m]) < 0.01);
  rec('Hoa hồng từng kỹ thuật viên ghi vào chấm công đúng từng xu', okComm, `${st.rate}% · ${st.cc.map(([m, v]) => `${m} $${v}`).join(', ')}`);
  // có trong bảng lương tháng
  const d = new Date();
  const pay = await page.evaluate(async (q) => (await fetch(q)).json(), `/api/hr/payroll_summary?month=${d.getMonth() + 1}&year=${d.getFullYear()}`);
  const inPay = st.cc.every(([m]) => (pay.data[m]?.hoa_hong || 0) > 0);
  rec('Hoa hồng hiện trong Bảng lương tháng của từng kỹ thuật viên', inPay, st.cc.map(([m]) => `${m}: $${pay.data[m]?.hoa_hong}`).join(', '));
  // hoàn tiền 100% -> thu hồi hoa hồng
  const total = body.total_amount;
  const ref = await page.evaluate(async ([id, amt]) => (await fetch(`/api/orders/${id}/refund`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount: amt, reason: 'QA spa therapist refund' }) })).json(), [orderId, total]);
  const net = py(`
import json
from mongo_client import db
bid = db.users.find_one({'email': '${EMAIL}'})['business_id']
rows = list(db.chamcong.find({'business_id': bid, 'ghi_chu': {'$regex': r'Order #${orderId}(?!\\d)'}}, {'_id': 0, 'tien_tua': 1}))
print(json.dumps({'n': len(rows), 'net': round(sum(r['tien_tua'] for r in rows), 2)}))
`);
  rec('Hoàn tiền 100% -> hoa hồng tự thu hồi về 0', ref.success && ref.commission_clawback > 0 && Math.abs(net.net) < 0.01, `${net.n} dòng, ròng $${net.net}`);
  rec('Không lỗi JS', errs.length === 0, errs.join(' | '));
} catch (e) {
  rec('LỖI KHÔNG MONG MUỐN', false, e.message.split('\n')[0]);
} finally {
  if (orderId) {
    console.log('   dọn:', JSON.stringify(py(`
import json
from mongo_client import db
bid = db.users.find_one({'email': '${EMAIL}'})['business_id']
ids = [${orderId}] + [o['id'] for o in db.orders.find({'business_id': bid, 'metadata.original_order_id': ${orderId}}, {'id': 1})]
out = {'chamcong': db.chamcong.delete_many({'business_id': bid, 'ghi_chu': {'$regex': r'Order #${orderId}(?!\\d)'}}).deleted_count,
  'orders': db.orders.delete_many({'business_id': bid, 'id': {'$in': ids}}).deleted_count,
  'order_items': db.order_items.delete_many({'order_id': {'$in': ids}}).deleted_count,
  'transactions': db.transactions.delete_many({'business_id': bid, 'order_id': {'$in': ids}}).deleted_count,
  'customers': db.customers.delete_many({'business_id': bid, 'phone': '${PHONE}'}).deleted_count,
  'loyalty_events': db.loyalty_events.delete_many({'business_id': bid, 'customer_phone': '${PHONE}'}).deleted_count}
print(json.dumps(out))
`)));
  }
  await browser.close();
}
console.log(`\nTổng kết: ${results.filter((r) => r.ok).length} PASS · ${results.filter((r) => !r.ok).length} FAIL`);
