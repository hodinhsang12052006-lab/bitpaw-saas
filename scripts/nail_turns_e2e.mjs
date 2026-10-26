// nail_turns_e2e.mjs — Bảng xoay tua thợ Nails chạy THẬT trên server local (tiệm demo Nails Úc): vào bảng, giao khách đúng lượt
// (tua đủ / nửa tua theo giá vé), xong, bỏ lượt, hoàn tác, tổng kết cuối ngày, giao diện tablet + điện thoại. Dọn sạch sau khi chạy.
//   BASE=http://127.0.0.1:5002 node scripts/nail_turns_e2e.mjs
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + String(note).slice(0, 220) : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1180, height: 820 } });   // tablet quầy lễ tân
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login'); await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const before = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps([str(x['_id']) for x in db.nail_turns.find({'business_id': ${B}}, {'_id': 1})]))`));
const api = (path, body) => p.evaluate(async ([path, body]) => {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  let j = {}; try { j = await r.json(); } catch (e) { j = {}; }
  return { status: r.status, ...j };
}, [path, body]);

await p.goto(BASE + '/nail/turns', { waitUntil: 'load' }); await p.waitForTimeout(1500);
let board = await api('/api/nail_turns/board');
const bd = board.board || board.data || board;
const pool = (bd.not_on_board || []).concat(bd.line || []);
rec('Mở bảng xoay tua — thấy danh sách thợ Nails của tiệm', board.status === 200 && pool.length >= 2 && errs.length === 0, `${pool.length} thợ · ${errs.join(' | ')}`);
const [t1, t2, t3] = pool.slice(0, 3).map((x) => x.ma_nv);
const settings = await api('/api/nail_turns/settings');
const thr = Number(((settings.settings || settings.data || settings).full_turn_min) || 45);
for (const t of [t1, t2, t3].filter(Boolean)) await api('/api/nail_turns/action', { action: 'join', ma_nv: t });
board = await api('/api/nail_turns/board');
let nb = board.board || board.data || board;
const lineIds = (nb.line || []).map((x) => x.ma_nv);
rec('Đưa 3 thợ lên bảng (vào hàng chờ)', lineIds.includes(t1) && lineIds.includes(t2) && (!t3 || lineIds.includes(t3)), lineIds.join(','));
const nu = (x) => (typeof x === 'string' ? x : (x || {}).ma_nv);
const first = nu(nb.next_up);
let r1 = await api('/api/nail_turns/assign', { ma_nv: first, kind: 'walk_in', amount: thr + 10 });
board = await api('/api/nail_turns/board'); nb = board.board || board.data || board;
const second = nu(nb.next_up);
const firstTurnId = ((nb.busy || []).find((x) => x.ma_nv === first) || {}).current?.id;
rec('Giao khách vãng lai cho người tới lượt (giá ≥ ngưỡng = tua đủ); người kế tiếp được đẩy lên', r1.status === 200 && first && second && second !== first, `${first} -> kế tiếp ${second}`);
let r2 = await api('/api/nail_turns/assign', { ma_nv: second, kind: 'walk_in', amount: Math.max(1, thr - 20) });
let s1 = await api('/api/nail_turns/summary');
const rowOf = (s, ma) => (s.rows || []).find((x) => x.ma_nv === ma) || {};
rec('Giá dưới ngưỡng = nửa tua (người thứ 2), giá ≥ ngưỡng = tua đủ (người thứ 1)', r2.status === 200 && rowOf(s1, second).half >= 1 && rowOf(s1, first).full >= 1, JSON.stringify({ first: rowOf(s1, first), second: rowOf(s1, second) }).slice(0, 220));
const done = firstTurnId ? await api('/api/nail_turns/done', { turn_id: firstTurnId, amount: thr + 10 }) : { status: 0 };
rec('Thợ làm xong khách -> quay lại hàng chờ', done.status === 200, `${done.status} ${done.message || ''}`);
board = await api('/api/nail_turns/board'); nb = board.board || board.data || board;
const upNow = nu(nb.next_up);
const notUp = (nb.line || []).map((x) => x.ma_nv).find((x) => x !== upNow);
const outOfTurn = notUp ? await api('/api/nail_turns/assign', { ma_nv: notUp, kind: 'walk_in', amount: thr + 5 }) : { status: 0, message: 'chỉ có 1 người trong hàng' };
rec('Giao sai lượt -> hỏi xác nhận (không âm thầm phá thứ tự)', outOfTurn.status === 409 || outOfTurn.needs_override || /out of turn|sai lượt|ngoài lượt/i.test(outOfTurn.message || ''), `${outOfTurn.status} ${outOfTurn.message || ''}`);
const undo = await api('/api/nail_turns/undo', {});
rec('Hoàn tác thao tác cuối (không xoá dữ liệu, chỉ gạch bỏ)', undo.status === 200, `${undo.status} ${undo.message || ''}`);
const sum = await api('/api/nail_turns/summary');
const sumText = JSON.stringify(sum);
rec('Tổng kết cuối ngày theo thợ (số khách, số tua)', sum.status === 200 && sumText.includes(first), sumText.slice(0, 200));
await p.goto(BASE + '/nail/turns', { waitUntil: 'load' }); await p.waitForTimeout(1500);
const txt = await p.evaluate(() => document.body.innerText);
await p.screenshot({ path: 'audit-results/screenshots/nail_turns_tablet.png' }).catch(() => {});
rec('Màn hình tablet hiện tên thợ + người tới lượt, không lỗi JS', pool.slice(0, 2).every((x) => txt.includes(x.name || x.ho_ten || '')) && errs.length === 0, errs.join(' | '));
const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
const m = await (await b.newContext({ ...iphone, storageState: await ctx.storageState() })).newPage();
await m.goto(BASE + '/nail/turns', { waitUntil: 'load' }); await m.waitForTimeout(1500);
const over = await m.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const small = await m.evaluate(() => [...document.querySelectorAll('button')].filter((x) => x.offsetParent && !x.closest('#app-sidebar, aside') && x.getBoundingClientRect().height < 40).map((x) => (x.textContent || x.getAttribute('aria-label') || x.id || '?').trim().slice(0, 30) + ':' + Math.round(x.getBoundingClientRect().height)));
rec('Điện thoại: không tràn ngang, nút đủ lớn để chạm', over <= 1 && small.length === 0, `tràn ${over}px · nút nhỏ ${small.join(', ')}`);
// dọn: chỉ xoá bản ghi bảng xoay tua do lần chạy này tạo
const cleaned = py(`
from bson import ObjectId
from mongo_client import db
keep = [ObjectId(x) for x in ${JSON.stringify(before)}]
print(db.nail_turns.delete_many({'business_id': ${B}, '_id': {'$nin': keep}}).deleted_count)`);
console.log('dọn', cleaned, 'bản ghi');
const pass = steps.filter((s) => s.ok).length;
console.log(`\nTổng: ${pass} PASS · ${steps.length - pass} FAIL`);
await b.close();
process.exit(steps.length - pass ? 1 : 0);
