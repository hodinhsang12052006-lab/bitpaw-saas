// booking_settings_e2e.mjs — Cài đặt đặt lịch (booking_rules.py) dùng chung cho form online + trợ lý AI:
// giờ mở cửa -> giờ trống công khai, ngày nghỉ, tự xác nhận / chờ duyệt (form + trang thành công), câu AI chưa trả lời được,
// trang đặt lịch không còn hứa "Open 24/7".   node scripts/booking_settings_e2e.mjs   (CHỈ local; tự dọn, trả cài đặt cũ)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import { pickSlot, isoDate } from './lib/booking_slot.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
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

const saved = py(`
import json
from mongo_client import db
print(json.dumps(db.booking_settings.find_one({'business_id': ${B}}, {'_id': 0}) or None))`);
const PHONE = '+6149158' + String(Date.now()).slice(-4);
let cleaned = false;
const cleanup = () => {
  if (cleaned) return; cleaned = true;
  py(`
import json
from mongo_client import db
saved = json.loads(${JSON.stringify(saved)})
if saved: db.booking_settings.replace_one({'business_id': ${B}}, {**saved, 'business_id': ${B}}, upsert=True)
else: db.booking_settings.delete_many({'business_id': ${B}})
db.appointments.delete_many({'business_id': ${B}, 'customer_phone': '${PHONE}'})
db.bot_messages.delete_many({'business_id': ${B}, 'customer_id': ${B} + ':${PHONE}'})
print('cleaned')`);
};
process.on('exit', cleanup);

// ---- 1. API cài đặt: đọc + giờ mở cửa + ngày nghỉ
let s = await api('/api/booking/settings');
rec('Đọc cài đặt: có giờ mở cửa, dịch vụ kèm thời lượng, số thợ (Nails = nhân viên ngành Nails)', s.success && s.rules.hours && s.services.length > 0 && s.services.every((x) => x.duration > 0) && s.staff_count > 0, `staff ${s.staff_count}`);
const hours = { ...s.rules.hours, mon: null, tue: ['10:00', '12:00'] };
let r = await api('/api/booking/settings', 'POST', { hours, auto_confirm: true });
rec('Lưu: Thứ 2 nghỉ, Thứ 3 chỉ 10:00–12:00', r.success && r.rules.hours.mon === null && r.rules.hours.tue[1] === '12:00');
r = await api('/api/booking/settings', 'POST', { hours: { ...hours, wed: ['18:00', '09:00'] } });
rec('Giờ đóng trước giờ mở -> từ chối', r.status === 400);

const nextDow = (dow) => { const d = new Date(); d.setDate(d.getDate() + 7 + ((dow - d.getDay() + 7) % 7)); return isoDate(d); };
const MON = nextDow(1), TUE = nextDow(2);
const svc = s.services.find((x) => x.duration === 60) || s.services[0];
let pub = await (await p.request.get(`${BASE}/api/public/booking_slots/${bid}?date=${MON}&service_id=${svc.id}`)).json();
rec('Giờ trống công khai: Thứ 2 báo "nghỉ"', pub.open === false && pub.slots.length === 0);
pub = await (await p.request.get(`${BASE}/api/public/booking_slots/${bid}?date=${TUE}&service_id=${svc.id}`)).json();
const okTue = pub.slots.length > 0 && pub.slots.every((t) => t >= '10:00' && t <= '11:00');
rec('Thứ 3 chỉ ra giờ 10:00–11:00 (dịch vụ 60 phút phải xong trước 12:00)', okTue, pub.slots.join(','));

// ---- 2. Tự xác nhận vs chờ duyệt (form công khai + trang thành công)
const book = async (expectTitle) => {
  const c = await b.newContext({ viewport: { width: 390, height: 844 } });
  const g = await c.newPage(); const gerr = []; g.on('pageerror', (e) => gerr.push(e.message));
  await g.goto(`${BASE}/booking/nail/qr/${bid}`, { waitUntil: 'networkidle' });
  const chips = await g.textContent('.shop-chips').catch(() => '');
  await g.fill('#cus_name', 'Settings QA'); await g.fill('#cus_phone', PHONE);
  if (await g.locator('#cus_address').count()) await g.fill('#cus_address', 'QA');
  await g.selectOption('#cus_service', String(svc.id));
  const picked = await pickSlot(g, TUE, { sameDayOnly: true });
  const [resp] = await Promise.all([g.waitForResponse((x) => x.url().includes('/create_appointment')), g.click('#btnSubmit')]);
  const j = await resp.json().catch(() => ({}));
  await g.waitForTimeout(900);
  const title = await g.textContent('#successTitle').catch(() => '');
  const text = await g.textContent('#successText').catch(() => '');
  await c.close();
  return { chips, picked, j, title, text, gerr };
};
let x = await book();
rec('Tự xác nhận (mặc định): lịch "confirmed" + màn "You\'re booked!"', x.j.status === 'confirmed' && /booked/i.test(x.title) && /confirmed/.test(x.text), `${x.picked} · ${x.title}`);
rec('Trang đặt lịch không còn hứa "Open 24/7"; chip "Instant confirmation" đúng cài đặt', !/24\/7/.test(x.chips) && /Instant confirmation/.test(x.chips), x.chips.replace(/\s+/g, ' '));
rec('Màn thành công không còn chữ "Satellite Station"', !/Satellite/.test(x.text));
await api('/api/booking/settings', 'POST', { auto_confirm: false });
x = await book();
rec('Chờ duyệt: lịch "pending" + màn "Request sent"', x.j.status === 'pending' && /Request sent/.test(x.title) && /will confirm/.test(x.text), x.title);
rec('Chip trang đặt lịch đổi thành "The salon confirms your request"', /salon confirms/.test(x.chips));
rec('Trang đặt lịch không lỗi JS', x.gerr.length === 0, x.gerr.slice(0, 2).join(' | '));
const ai = py(`
import booking_rules
print('pending' in booking_rules.describe_for_ai(${B}) and 'never "confirmed"' in booking_rules.describe_for_ai(${B}))`);
rec('Trợ lý AI được báo: lịch online là yêu cầu chờ duyệt', ai === 'True');
await api('/api/booking/settings', 'POST', { auto_confirm: true });

// ---- 3. Câu AI chưa trả lời được -> hiện cho chủ tiệm
py(`
from datetime import datetime
from mongo_client import db, next_mongo_id
db.bot_messages.insert_one({'id': next_mongo_id('bot_messages'), 'business_id': ${B}, 'customer_id': ${B} + ':${PHONE}', 'sender_type': 'system',
  'content': '❓ Khách hỏi (AI chưa có dữ liệu): Do you have parking nearby? QA${PHONE.slice(-4)}', 'created_at': datetime.now().isoformat()})
print('ok')`);
s = await api('/api/booking/settings');
rec('API trả "câu AI chưa trả lời được" (30 ngày)', (s.gaps || []).some((g) => g.question.includes('QA' + PHONE.slice(-4))));
await p.goto(BASE + '/settings/booking', { waitUntil: 'networkidle' }); await p.waitForTimeout(500);
rec('Trang Cài đặt đặt lịch: hiện danh sách câu chưa trả lời + ô "Xác nhận lịch online"', await p.isVisible('#gapsBox') && (await p.textContent('#gaps')).includes('parking') && (await p.inputValue('#autoc')) === '1');
await p.selectOption('#autoc', '0');
await Promise.all([p.waitForResponse((x2) => x2.url().includes('/api/booking/settings') && x2.request().method() === 'POST'), p.click('#saveBtn')]);
s = await api('/api/booking/settings');
rec('Đổi "Chờ tiệm duyệt" trên giao diện -> lưu thật', s.rules.auto_confirm === false);
await p.screenshot({ path: 'audit-results/screenshots/booking_settings_page.png' }).catch(() => {});
rec('Trang cài đặt không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

{ // trả cài đặt cũ qua API (xoá cache luật đặt lịch của server ngay), rồi dọn DB
  const old = JSON.parse(saved);
  if (old) await api('/api/booking/settings', 'POST', { hours: old.hours, auto_confirm: old.auto_confirm !== false, info: old.info || {} });
}
cleanup();
await b.close();
const fail = steps.filter((z) => !z.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
