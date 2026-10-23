// roster_plus_e2e.mjs — Lịch ca nâng cấp (kiểu Deputy/7shifts): ca trống nhân viên tự nhận (nguyên tử), nhân viên tự khai ngày bận,
// đổi ca gắn ca thật (đồng nghiệp đồng ý -> chủ duyệt -> tự đổi người + báo), tăng ca 1,5× (AU 38h / US 40h), % lương/doanh thu,
// tự xếp không lấp chỗ đã đăng ca trống, chép tuần giữ ca trống, giao diện chủ + app nhân viên (iPhone).
//   node scripts/roster_plus_e2e.mjs   (CHỈ local; tự dọn)
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

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

const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const plus = (k) => { const d = new Date(); d.setDate(d.getDate() + k); return d; };
const D2 = iso(plus(2)), D3 = iso(plus(3)), D4 = iso(plus(4)), YDAY = iso(plus(-1));
const weekdayOf = (s) => (new Date(s + 'T00:00:00').getDay() + 6) % 7;   // T2 = 0

const TAG = 'RP' + String(Date.now()).slice(-4);
const E = [1, 2, 3].map((i) => `${TAG}${i}`);
for (const [i, c] of E.entries()) await api('/api/hr/employees', 'POST', { ma_nv: c, ho_ten: `Plus Tester ${i + 1}`, linh_vuc: 'Nails', chuc_vu: `${TAG} Tech`, luong_gio: 25 });
await api(`/api/roster/staff/${E[1]}`, 'POST', { email: 'roster.plus.qa@example.com' });
await api(`/api/roster/staff/${E[0]}`, 'POST', { email: 'roster.plus.qa0@example.com' });
const openIds = [];
const savedNeeds = py(`
import json
from mongo_client import db
print(json.dumps(db.roster_needs.find_one({'business_id': ${B}}, {'_id': 0}) or None))`);
let cleaned = false;
const cleanup = () => {
  if (cleaned) return; cleaned = true;
  py(`
import json
from mongo_client import db
codes = ${JSON.stringify(E)}
db.roster_shifts.delete_many({'business_id': ${B}, '$or': [{'ma_nv': {'$in': codes}}, {'id': {'$in': ${JSON.stringify(openIds)}}}, {'role': '${TAG}'}]})
db.roster_swaps.delete_many({'business_id': ${B}, '$or': [{'from_ma_nv': {'$in': codes}}, {'to_ma_nv': {'$in': codes}}]})
db.outbound_messages.delete_many({'business_id': ${B}, 'to': {'$regex': 'roster.plus.qa'}})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
db.staff.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
saved = json.loads(${JSON.stringify(savedNeeds)})
if saved: db.roster_needs.replace_one({'business_id': ${B}}, {**saved, 'business_id': ${B}}, upsert=True)
else: db.roster_needs.delete_many({'business_id': ${B}})
print('cleaned')`);
};
process.on('exit', cleanup);
const mkOpen = async (date, start, end, role = TAG) => { const r = await api('/api/roster/shifts', 'POST', { open: true, date, start, end, role }); if (r.data) openIds.push(r.data.id); return r; };

// ---- ca trống
let r = await mkOpen(D2, '10:00', '14:00');
rec('Chủ đăng ca trống (không gắn ai)', r.success && r.data.status === 'open' && r.data.ma_nv === null);
let g = await api('/api/roster?week=' + D2);
rec('Lưới tuần trả về ca trống, giờ/chi phí nhân viên không tính ca trống', g.open_shifts.some((s) => s.id === r.data.id) && g.staff.filter((s) => E.includes(s.ma_nv)).every((s) => s.hours === 0));
let my = await api('/api/roster/my?ma_nv=' + E[0]);
rec('App nhân viên thấy ca trống trong 14 ngày tới', my.open_shifts.some((s) => s.id === r.data.id));
const open1 = r.data.id;
r = await api(`/api/roster/open/${open1}/claim`, 'POST', { ma_nv: E[0] });
const c1 = py(`
from mongo_client import db
s = db.roster_shifts.find_one({'id': ${open1}}); print(s['ma_nv'], s['status'], s.get('source'))`);
rec('Nhân viên bấm "Nhận ca" -> ca thành của họ, đã công bố', r.success && c1 === `${E[0]} published claimed`, c1);
r = await api(`/api/roster/open/${open1}/claim`, 'POST', { ma_nv: E[1] });
rec('Người thứ 2 nhận cùng ca -> 409 "không còn trống"', r.status === 409);

r = await mkOpen(D3, '10:00', '14:00');
const race = await Promise.all([E[1], E[2]].map((c) => api(`/api/roster/open/${r.data.id}/claim`, 'POST', { ma_nv: c })));
rec('2 người bấm nhận cùng lúc -> đúng 1 người được', race.filter((x) => x.success).length === 1 && race.filter((x) => x.status === 409).length === 1, race.map((x) => x.status).join(','));

// ---- ngày bận + giờ tối đa
r = await api('/api/roster/my_availability', 'POST', { ma_nv: E[2], unavailable_days: [weekdayOf(D4), 9, 'x'] });
rec('Nhân viên tự khai ngày bận (lọc giá trị rác)', r.success && JSON.stringify(r.unavailable_days) === JSON.stringify([weekdayOf(D4)]));
r = await mkOpen(D4, '09:00', '12:00');
const open3 = r.data.id;
r = await api(`/api/roster/open/${open3}/claim`, 'POST', { ma_nv: E[2] });
rec('Nhận ca vào ngày đã báo bận -> chặn', r.status === 409 && /unavailable/i.test(r.message), r.message);
await api(`/api/roster/staff/${E[1]}`, 'POST', { max_hours: 5, email: 'roster.plus.qa@example.com' });
r = await mkOpen(D4, '13:00', '17:00');
const raceWinner = race.findIndex((x) => x.success) === 0 ? E[1] : E[2];
r = await api(`/api/roster/open/${r.data.id}/claim`, 'POST', { ma_nv: E[1] });
rec('Nhận ca vượt giờ tối đa/tuần -> chặn', raceWinner === E[1] ? (r.status === 409 && /hours/.test(r.message)) : r.success, `${raceWinner} · ${r.message || 'ok'}`);

// ---- đổi ca gắn ca thật
r = await api('/api/roster/swap', 'POST', { ma_nv: E[0], shift_id: open1, to_ma_nv: E[2], note: 'dentist' });
const swap1 = r.data && r.data.id;
rec('Xin đổi 1 ca cụ thể cho đồng nghiệp -> chờ đồng nghiệp', r.success && r.data.status === 'pending_peer');
r = await api('/api/roster/swap', 'POST', { ma_nv: E[0], shift_id: open1, to_ma_nv: E[1] });
rec('Xin đổi lần 2 cùng ca -> chặn trùng', r.status === 409);
r = await api('/api/roster/swap', 'POST', { ma_nv: E[1], shift_id: open1, to_ma_nv: E[2] });
rec('Xin đổi ca KHÔNG phải của mình -> từ chối', r.status === 400);
r = await api(`/api/roster/swap/${swap1}/respond`, 'POST', { ma_nv: E[1], accept: true });
rec('Người không được nhờ bấm đồng ý -> từ chối', r.status === 409);
r = await api(`/api/roster/swap/${swap1}/respond`, 'POST', { ma_nv: E[2], accept: true });
rec('Đồng nghiệp đồng ý -> chờ chủ duyệt', r.success && r.status === 'pending_owner');
g = await api('/api/roster?week=' + D2);
rec('Chủ thấy yêu cầu chờ duyệt trên trang lịch ca', g.swaps_pending.some((w) => w.id === swap1));
r = await api(`/api/roster/swap/${swap1}/decide`, 'POST', { approve: true });
const after = py(`
from mongo_client import db
s = db.roster_shifts.find_one({'id': ${open1}}); print(s['ma_nv'], s.get('swapped_from'))`);
rec('Chủ duyệt -> ca tự chuyển sang đồng nghiệp', r.success && after === `${E[2]} ${E[0]}`, after);
const notes = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([m['to'] + ' | ' + m['body'] for m in db.outbound_messages.find({'business_id': ${B}, 'kind': 'roster', 'to': {'$regex': 'roster.plus.qa'}}, {'_id': 0})]))`));
rec('Người xin đổi được báo đã duyệt (email)', notes.some((n) => n.startsWith('roster.plus.qa0@') && /Approved/.test(n) && /Plus Tester 3/.test(n)), notes.length + ' tin');

r = await api('/api/roster/swap', 'POST', { ma_nv: E[2], shift_id: open1, to_ma_nv: E[1] });
const swap2 = r.data && r.data.id;
const askNote = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([m['body'] for m in db.outbound_messages.find({'business_id': ${B}, 'kind': 'roster', 'to': 'roster.plus.qa@example.com'}, {'_id': 0})]))`));
rec('Đồng nghiệp được nhờ nhận tin báo (email)', askNote.some((t) => /asked you to take their shift/.test(t)));
r = await api(`/api/roster/swap/${swap2}/respond`, 'POST', { ma_nv: E[1], accept: false });
rec('Đồng nghiệp từ chối -> yêu cầu đóng', r.success && r.status === 'declined');
const pastId = Number(py(`
from mongo_client import db, next_mongo_id
i = next_mongo_id('roster_shifts')
db.roster_shifts.insert_one({'id': i, 'business_id': ${B}, 'ma_nv': '${E[0]}', 'ho_ten': 'Plus Tester 1', 'date': '${YDAY}', 'start': '09:00', 'end': '12:00', 'role': '', 'status': 'published'})
print(i)`));
r = await api('/api/roster/swap', 'POST', { ma_nv: E[0], shift_id: pastId, to_ma_nv: E[1] });
rec('Xin đổi ca đã qua -> từ chối', r.status === 400);

// ---- tăng ca + % lương/doanh thu (tuần tương lai riêng)
const W2 = '2027-04-05';
for (const d of ['2027-04-05', '2027-04-06', '2027-04-07', '2027-04-08', '2027-04-09']) await api('/api/roster/shifts', 'POST', { ma_nv: E[2], date: d, start: '08:00', end: '16:12' });
g = await api('/api/roster?week=' + W2);
const ot = g.overtime.find((o) => o.ho_ten === 'Plus Tester 3');
rec(`Tăng ca: 41 giờ > ${g.overtime_limit} giờ -> cảnh báo + phụ trội 1,5×`, ot && ot.hours === 41 && ot.over === 41 - g.overtime_limit && ot.extra_cost === (41 - g.overtime_limit) * 25 * 0.5, JSON.stringify(ot));
rec('Chi phí có tăng ca = lương thường + phụ trội', Math.abs(g.labor_cost_with_ot - (g.labor_cost + g.overtime.reduce((a, o) => a + o.extra_cost, 0))) < 0.01);
rec('% lương/doanh thu 7 ngày tính đúng (hoặc trống khi chưa có doanh thu)', g.sales_last_7_days > 0 ? Math.abs(g.labor_pct - Math.round(g.labor_cost_with_ot / g.sales_last_7_days * 1000) / 10) < 0.11 : g.labor_pct === null, `${g.labor_pct}% of ${g.sales_last_7_days}`);

// ---- tự xếp không lấp chỗ đã đăng ca trống; chép tuần giữ ca trống
const W3 = '2027-05-03', W3wed = '2027-05-05';
await api('/api/roster/needs', 'POST', { max_hours_week: 38, needs: [{ weekday: 2, start: '09:00', end: '17:00', count: 1, role: TAG }] });
await mkOpen(W3wed, '09:00', '17:00');
r = await api('/api/roster/auto', 'POST', { week: W3 });
g = await api('/api/roster?week=' + W3);
const cov = g.coverage.find((c) => c.date === W3wed);
rec('Tự xếp không tạo ca nháp chồng lên ca trống đã đăng', r.created === 0 && cov && cov.open === 1 && cov.short === 1, JSON.stringify({ created: r.created, cov }));
r = await api('/api/roster/copy', 'POST', { week: '2027-05-10' });
const copiedOpen = Number(py(`
from mongo_client import db
print(db.roster_shifts.count_documents({'business_id': ${B}, 'date': '2027-05-12', 'status': 'open', 'role': '${TAG}'}))`));
rec('Chép tuần: ca trống vẫn là ca trống', copiedOpen === 1);

// ---- giao diện chủ: hàng ca trống, duyệt đổi ca
const uiShift = Number(py(`
from mongo_client import db, next_mongo_id
i = next_mongo_id('roster_shifts')
db.roster_shifts.insert_one({'id': i, 'business_id': ${B}, 'ma_nv': '${E[0]}', 'ho_ten': 'Plus Tester 1', 'date': '${D3}', 'start': '06:00', 'end': '08:00', 'role': '', 'status': 'published'})
print(i)`));
r = await api('/api/roster/swap', 'POST', { ma_nv: E[0], shift_id: uiShift, to_ma_nv: E[2] });
const uiSwap = r.data && r.data.id;
if (uiSwap) await api(`/api/roster/swap/${uiSwap}/respond`, 'POST', { ma_nv: E[2], accept: true });
await p.goto(BASE + '/roster?x=1', { waitUntil: 'networkidle' });
await p.waitForTimeout(500);
const gridTxt = await p.textContent('#grid');
rec('Trang /roster: có hàng "Ca trống"', /Open shifts|Ca trống/.test(gridTxt));
const swapVisible = await p.isVisible('#swapBox');
rec('Trang /roster: hộp "đổi ca chờ duyệt" hiện khi có yêu cầu', !uiSwap || swapVisible);
if (uiSwap && swapVisible) {
  await Promise.all([p.waitForResponse((x) => x.url().includes('/decide')), p.click(`#swapList .swap[data-id="${uiSwap}"] button[data-ok="1"]`)]);
  await p.waitForTimeout(500);
  rec('Bấm "Duyệt" trên giao diện -> thông báo thành công', /Approved|Đã duyệt/.test(await p.textContent('#msg')));
}
const pct = await p.textContent('#cPct');
rec('Thẻ chi phí lương có dòng % doanh thu', /sales|doanh thu/.test(pct), pct);
await p.click(`.add[data-emp="__open__"]`);
rec('Hộp thoại thêm ca: chọn sẵn "Ca trống"', (await p.inputValue('#fEmp')) === '__open__');
await p.click('#dlgCancel');
await p.screenshot({ path: 'audit-results/screenshots/roster_plus_owner.png' }).catch(() => {});

// ---- app nhân viên (iPhone): ca trống + nhận ca + ngày bận
{
  const extra = await mkOpen(D3, '15:00', '18:00');
  const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
  const mctx = await b.newContext({ ...iphone, storageState: await ctx.storageState() });
  const m = await mctx.newPage(); const merr = []; m.on('pageerror', (e) => merr.push(e.message));
  await m.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
  await m.evaluate(() => { ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar', 'bp_da_diem_danh'].forEach((k) => localStorage.removeItem(k)); });
  await m.reload({ waitUntil: 'networkidle' });
  await m.fill('#login_manv', E[0].toLowerCase()); await m.click('#btn_login_submit');
  await m.waitForSelector('#btnOffDuty', { state: 'visible', timeout: 8000 }).catch(() => {});
  await m.click('#btnOffDuty');   // ngày nghỉ: xem lịch/nhận ca mà không chấm công
  rec('Màn chấm công có lối "Xem lịch ca" (không phải chấm công)', await m.isVisible('#offDutyBar') && !(await m.isVisible('#workZone')));
  await m.waitForSelector('#openShiftsBox:not(.hidden)', { timeout: 8000 }).catch(() => {});
  const openTxt = await m.textContent('#openShiftsList').catch(() => '');
  rec('App nhân viên: thấy danh sách ca trống + nút Nhận ca', openTxt.includes('15:00–18:00') && /Claim|Nhận ca/.test(openTxt), openTxt.replace(/\s+/g, ' ').slice(0, 80));
  await Promise.all([m.waitForResponse((x) => x.url().includes('/claim')), m.click(`#openShiftsList [data-claim="${extra.data.id}"]`)]);
  await m.waitForTimeout(800);
  const mine = await m.textContent('#myShiftsList');
  rec('Bấm Nhận ca -> ca chuyển vào "My shifts"', mine.includes('15:00–18:00'));
  const swapBtns = await m.locator('#myShiftsList [data-swapshift]').count();
  rec('Mỗi ca của tôi có nút đổi ca', swapBtns >= 1);
  await m.click('#availTitle');
  await Promise.all([m.waitForResponse((x) => x.url().includes('/my_availability')), m.click('#availDays [data-day="6"]')]);
  await m.waitForTimeout(600);
  const un = py(`
from mongo_client import db
print(db.employees.find_one({'business_id': ${B}, 'ma_nv': '${E[0]}'}).get('unavailable_days'))`);
  rec('Bấm thứ trong "Ngày tôi không làm được" -> lưu', un === '[6]', un);
  const body = await m.innerText('body');
  rec('App nhân viên (EN) không còn chữ lóng/tiếng Việt cũ', !/ném thiệp|chốt kèo|Sếp|Vệ tinh Radar/.test(body));
  await m.screenshot({ path: 'audit-results/screenshots/roster_plus_staff_app.png' }).catch(() => {});
  rec('App nhân viên không lỗi JS', merr.length === 0, merr.slice(0, 2).join(' | '));
  await mctx.close();
}
rec('Trang quản lý không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// ---- dọn
cleanup();
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
