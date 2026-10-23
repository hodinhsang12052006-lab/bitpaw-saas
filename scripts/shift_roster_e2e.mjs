// shift_roster_e2e.mjs — Lịch ca tuần: tự xếp theo nhu cầu (né nghỉ phép/ngày bận/giờ tối đa), trùng ca, chép tuần,
// công bố + báo nhân viên, app nhân viên thấy ca, đối chiếu đi trễ/vắng.   node scripts/shift_roster_e2e.mjs  (CHỈ local; tự dọn)
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = 'http://127.0.0.1:5001';
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

const TAG = 'QR' + String(Date.now()).slice(-4);
const E = [1, 2, 3, 4].map((i) => `${TAG}${i}`);
for (const [i, c] of E.entries()) await api('/api/hr/employees', 'POST', { ma_nv: c, ho_ten: `Roster Tester ${i + 1}`, linh_vuc: 'Nails', chuc_vu: `${TAG} Tech`, luong_gio: 25 });
const savedNeeds = py(`
import json
from mongo_client import db
print(json.dumps(db.roster_needs.find_one({'business_id': ${B}}, {'_id': 0}) or None))`);
const W = '2027-03-01', SAT = '2027-03-06';   // tuần tương lai (thứ 2) — không đụng lịch thật
py(`
from mongo_client import db, next_mongo_id
db.leave_requests.insert_one({'id': next_mongo_id('leave_requests'), 'business_id': ${B}, 'ma_nv': '${E[2]}', 'ho_ten': 'Roster Tester 3', 'from_date': '${SAT}', 'to_date': '${SAT}', 'leave_type': 'Annual', 'reason': 'qa', 'status': 'approved'})
print('ok')`);
await api(`/api/roster/staff/${E[3]}`, 'POST', { unavailable_days: [5] });   // người 4 bận thứ 7
await api(`/api/roster/staff/${E[0]}`, 'POST', { max_hours: 8 });            // người 1 tối đa 8 giờ/tuần
let r = await api(`/api/roster/staff/${E[1]}`, 'POST', { email: 'bad-email' });
rec('Email sai định dạng -> từ chối', r.status === 400);
await api(`/api/roster/staff/${E[1]}`, 'POST', { email: 'roster.qa@example.com', phone: '' });

r = await api('/api/roster/needs', 'POST', { max_hours_week: 38, needs: [
    { weekday: 0, start: '09:00', end: '17:00', count: 5, role: TAG },
    { weekday: 5, start: '09:00', end: '17:00', count: 3, role: TAG },
    { weekday: 6, start: '10:00', end: '16:00', count: 2, role: TAG },
    { weekday: 9, start: 'x', end: '17:00', count: 2 },   // rác -> bị lọc
] });
rec('Lưu nhu cầu người (lọc dòng sai)', r.success && r.needs.length === 3);

r = await api('/api/roster/auto', 'POST', { week: W });
const g = await api('/api/roster?week=' + W);
const mine = g.shifts.filter((s) => E.includes(s.ma_nv));
const by = (c) => mine.filter((s) => s.ma_nv === c);
rec('Tự xếp: tạo đúng 7 ca nháp', r.success && r.created === 7 && mine.every((s) => s.status === 'draft' && s.source === 'auto'), `created ${r.created}`);
rec('Không xếp ai vào ngày nghỉ phép đã duyệt', !by(E[2]).some((s) => s.date === SAT));
rec('Không xếp vào thứ nhân viên báo bận', !by(E[3]).some((s) => s.date === SAT));
rec('Tôn trọng giờ tối đa/tuần (người 1 ≤ 8h)', by(E[0]).length === 1 && g.staff.find((x) => x.ma_nv === E[0]).hours === 8);
const sat = r.unfilled.find((u) => u.date === SAT), mon = r.unfilled.find((u) => u.date === W);
rec('Báo rõ khung thiếu người + lý do (T7 thiếu 2: nghỉ phép/bận/đủ giờ)', sat && sat.missing === 2 && sat.reasons.leave === 1 && sat.reasons.unavailable === 1 && sat.reasons.max_hours === 1 && mon && mon.missing === 1, JSON.stringify(sat));
rec('Chia đều: CN giao cho 2 người ít giờ nhất', by(E[2]).some((s) => s.date === '2027-03-07') && by(E[3]).some((s) => s.date === '2027-03-07'));
rec('Chi phí lương ước tính = giờ × lương giờ', g.labor_cost >= (8 * 4 + 8 + 6 * 2) * 25, `${g.labor_cost} ${g.currency}`);

r = await api('/api/roster/shifts', 'POST', { ma_nv: E[1], date: W, start: '12:00', end: '14:00' });
rec('Thêm ca trùng giờ -> chặn (409)', r.status === 409);
r = await api('/api/roster/shifts', 'POST', { ma_nv: E[2], date: SAT, start: '18:00', end: '20:00' });
rec('Thêm ca vào ngày nghỉ phép -> chặn (409)', r.status === 409);
r = await api('/api/roster/shifts', 'POST', { ma_nv: E[3], date: '2027-03-02', start: '22:00', end: '06:00', role: 'Night' });
rec('Ca qua đêm 22:00–06:00 hợp lệ (8 giờ)', r.success);

r = await api('/api/roster/copy', 'POST', { week: '2027-03-08' });
rec('Chép tuần trước sang tuần sau (8 ca)', r.success && r.copied === 8, `copied ${r.copied}`);

r = await api('/api/roster/publish', 'POST', { week: W });
const outbox = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([{'to': m['to'], 'ch': m['channel'], 'body': m['body']} for m in db.outbound_messages.find({'business_id': ${B}, 'kind': 'roster'}, {'_id': 0})]))`));
rec('Công bố: ca chuyển published + gửi lịch cho người có email', r.success && r.published === 8 && r.notified === 1 && outbox.some((m) => m.to === 'roster.qa@example.com' && /Roster/.test(m.body) && /09:00-17:00/.test(m.body)), JSON.stringify({ pub: r.published, n: r.notified, nc: r.no_contact.length }));
rec('Người chưa có liên hệ được liệt kê để chủ tiệm biết', r.no_contact.length === 3);

// ---- bảng lương cá nhân qua email (trang /bangluong)
r = await api('/api/payroll/pay_summaries', 'POST', { month: 10, year: 2026, currency: 'AUD', labels: { col1: 'Hourly wage', col2: 'Commission', col3: 'Tips' },
    rows: [{ ma_nv: E[1], col1: 800, col2: 120.5, col3: 40, net: 960.5 }, { ma_nv: E[0], col1: 100, col2: 0, col3: 0, net: 100 }] });
const pay = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([{'to': m['to'], 'subject': m['subject'], 'body': m['body']} for m in db.outbound_messages.find({'business_id': ${B}, 'kind': 'pay_summary'}, {'_id': 0})]))`));
rec('Gửi bảng lương: email đúng người, đúng số, ghi rõ không phải phiếu lương chính thức', r.success && r.sent === 1 && r.no_email.includes('Roster Tester 1') && pay.length === 1 && pay[0].to === 'roster.qa@example.com' && /A\$960\.50/.test(pay[0].body) && /not a formal payslip/.test(pay[0].body), JSON.stringify({ sent: r.sent, subj: pay[0] && pay[0].subject }));
r = await api('/api/payroll/pay_summaries', 'POST', { month: 13, year: 2026, rows: [] });
rec('Kỳ lương sai -> từ chối', r.status === 400);

// ---- tuần hiện tại: app nhân viên + đối chiếu đi trễ/vắng
const now = new Date(); const pad = (n) => String(n).padStart(2, '0');
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
const st = new Date(now.getTime() - 60 * 60000), en = new Date(now.getTime() + 120 * 60000), late = new Date(st.getTime() + 12 * 60000);
await api('/api/roster/shifts', 'POST', { ma_nv: E[0], date: today, start: hm(st), end: hm(en), role: 'Nails' });
await api('/api/roster/shifts', 'POST', { ma_nv: E[1], date: today, start: hm(st), end: hm(en) });
r = await api('/api/roster/publish', 'POST', { week: today });
py(`
from mongo_client import db, next_mongo_id
db.chamcong.insert_one({'id': next_mongo_id('chamcong'), 'business_id': ${B}, 'ma_nv': '${E[0]}', 'ngay_cham': '${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()}', 'gio_den': '${hm(late)}', 'trang_thai': 'Có mặt', 'nganh_nghe': 'Nails'})
print('ok')`);
const att = await api('/api/roster/attendance?week=' + today);
const a1 = att.rows.find((x) => x.ma_nv === E[0]), a2 = att.rows.find((x) => x.ma_nv === E[1]);
rec('Đối chiếu chấm công: check-in trễ 12 phút -> "trễ 12"', a1 && a1.status === 'late' && a1.late_min === 12, JSON.stringify(a1));
rec('Không check-in sau giờ vào ca 30 phút -> "vắng"', a2 && a2.status === 'no_show');
const my = await api('/api/roster/my?ma_nv=' + E[0]);
rec('API app nhân viên: chỉ thấy ca đã công bố của mình', my.success && my.data.length === 1 && my.data[0].date === today);

// ---- giao diện quản lý
await p.goto(BASE + '/roster', { waitUntil: 'networkidle' }); await p.waitForTimeout(600);
const grid = await p.textContent('#grid');
rec('Trang /roster: lưới tuần có nhân viên + ca hôm nay', grid.includes('Roster Tester 1') && grid.includes(hm(st)));
const attTxt = await p.textContent('#attBox');
rec('Trang /roster: bảng đi trễ/vắng hiển thị', /Late|Trễ/.test(attTxt) && /No-show|Vắng/.test(attTxt));
await p.click(`.add[data-emp="${E[3]}"][data-date="${today}"]`);
await p.fill('#fStart', '06:00'); await p.fill('#fEnd', '07:00');
await Promise.all([p.waitForResponse((x) => x.url().includes('/api/roster?')), p.click('#dlgSave')]); await p.waitForTimeout(300);
rec('Thêm ca bằng hộp thoại -> ca nháp hiện trên lưới', await p.locator('.chip.draft', { hasText: '06:00–07:00' }).count() === 1);
await p.screenshot({ path: 'audit-results/screenshots/shift_roster_desktop.png' }).catch(() => {});
await Promise.all([p.waitForResponse((x) => x.url().includes('/api/roster?')), p.click('#nextW')]); await p.waitForTimeout(300);
const lbl = await p.textContent('#weekLbl');
rec('Chuyển tuần hoạt động', !lbl.includes('…'), lbl);

// app nhân viên trên iPhone
{
  const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
  const mctx = await b.newContext({ ...iphone, storageState: await ctx.storageState() });
  const m = await mctx.newPage(); const merr = []; m.on('pageerror', (e) => merr.push(e.message));
  await m.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
  await m.evaluate(() => { ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar', 'bp_da_diem_danh'].forEach((k) => localStorage.removeItem(k)); });
  await m.reload({ waitUntil: 'networkidle' });
  await m.fill('#login_manv', E[0].toLowerCase()); await m.click('#btn_login_submit');
  await m.waitForSelector('#checkin_shift:not(.hidden)', { timeout: 8000 }).catch(() => {});
  const pill = await m.textContent('#checkin_shift').catch(() => '');
  rec('App nhân viên (iPhone): màn check-in báo "ca hôm nay"', pill.includes(hm(st)), pill);
  const card = await m.textContent('#myShiftsList').catch(() => '');
  rec('App nhân viên: danh sách "My shifts" có ca hôm nay', /Today/.test(card) && card.includes(hm(st)), card.replace(/\s+/g, ' ').trim().slice(0, 90));
  await m.screenshot({ path: 'audit-results/screenshots/shift_roster_staff_app.png' }).catch(() => {});
  rec('App nhân viên không lỗi JS', merr.length === 0, merr.slice(0, 2).join(' | '));
  await mctx.close();
}
rec('Trang quản lý không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// ---- dọn
py(`
import json
from mongo_client import db
codes = ${JSON.stringify(E)}
db.roster_shifts.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
db.chamcong.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
db.leave_requests.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
db.outbound_messages.delete_many({'business_id': ${B}, 'kind': {'$in': ['roster', 'pay_summary']}})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': {'$in': codes}})
saved = json.loads(${JSON.stringify(savedNeeds)})
if saved: db.roster_needs.replace_one({'business_id': ${B}}, {**saved, 'business_id': ${B}}, upsert=True)
else: db.roster_needs.delete_many({'business_id': ${B}})
print('cleaned', db.roster_shifts.count_documents({'business_id': ${B}}))`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
