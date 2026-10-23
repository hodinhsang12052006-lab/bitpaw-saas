// face_checkin_e2e.mjs — chấm công khuôn mặt (chống chấm công hộ): API + luồng app nhân viên + tải mô hình nhận diện thật.
//   node scripts/face_checkin_e2e.mjs      (CHỈ server local; dọn sạch sau khi chạy)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const vec = (seed, noise = 0) => Array.from({ length: 128 }, (_, i) => Math.sin(seed * 31 + i * 0.7) * 0.15 + (noise ? (Math.sin(i * 13.1 + seed) * noise) : 0));

const b = await chromium.launch({ channel: 'chrome', args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
const ctx = await b.newContext({ viewport: { width: 420, height: 860 }, permissions: ['camera', 'geolocation'], geolocation: { latitude: -33.8688, longitude: 151.2093 } });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const CODE = 'QF' + String(Date.now()).slice(-5);
const api = (url, method = 'GET', body) => p.evaluate(async ([u, m, bd]) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: bd ? JSON.stringify(bd) : undefined }); let j = {}; try { j = await r.json(); } catch (e) {} return { status: r.status, ...j }; }, [url, method, body]);
await api('/api/hr/employees', 'POST', { ma_nv: CODE, ho_ten: 'QA Face Tester', linh_vuc: 'Nails' });
const before = await api('/api/hr/face/settings');

// --- API
let r = await api('/api/hr/face/settings', 'POST', { enabled: true });
rec('Chủ tiệm bật chấm công khuôn mặt', r.success && r.enabled === true, JSON.stringify({ enrolled: r.enrolled, total: r.total }));
r = await api('/api/hr/face/enroll', 'POST', { ma_nv: CODE, descriptor: vec(1) });
rec('Đăng ký mặt KHÔNG có đồng ý -> từ chối', r.status === 400 && /Consent/i.test(r.message || ''));
r = await api('/api/hr/face/enroll', 'POST', { ma_nv: CODE, descriptor: vec(1).slice(0, 50), consent: true });
rec('Mẫu khuôn mặt sai định dạng -> từ chối', r.status === 400);
r = await api('/api/hr/face/enroll', 'POST', { ma_nv: CODE, descriptor: vec(1), consent: true });
rec('Đăng ký mặt có đồng ý -> lưu + cấp vé', r.success && /^\d+\.[0-9a-f]{32}$/.test(r.token || ''));
const stored = JSON.parse(py(`
import json
from mongo_client import db
e = db.employees.find_one({'business_id': ${B}, 'ma_nv': '${CODE}'}, {'_id': 0, 'face_template': 1, 'face_consent_at': 1})
print(json.dumps({'len': len(e.get('face_template') or []), 'consent': bool(e.get('face_consent_at'))}))`));
rec('Máy chủ lưu mẫu 128 số + thời điểm đồng ý', stored.len === 128 && stored.consent);
r = await api('/api/hr/face/enroll', 'POST', { ma_nv: CODE, descriptor: vec(9), consent: true });
rec('Người khác không thể ghi đè mặt đã đăng ký (409)', r.status === 409);
const list = await api('/api/hr/employees');
const one = await api('/api/hr/employees/' + CODE);
rec('API nhân viên KHÔNG trả mẫu khuôn mặt ra trình duyệt', !JSON.stringify(list).includes('face_template') && !JSON.stringify(one).includes('face_template') && !!(one.data || {}).face_enrolled_at);
r = await api('/api/hr/face/verify', 'POST', { ma_nv: CODE, descriptor: vec(1, 0.01) });
rec('Đúng người (mặt hơi khác chút) -> khớp + vé', r.success && r.match && r.distance < 0.5 && !!r.token, `khoảng cách ${r.distance}`);
const goodToken = r.token;
r = await api('/api/hr/face/verify', 'POST', { ma_nv: CODE, descriptor: vec(7) });
rec('Người khác dùng mã của nhân viên -> KHÔNG khớp (403)', r.status === 403 && r.match === false, `khoảng cách ${r.distance}`);
const today = new Date().toLocaleDateString('en-GB');
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: today, gio_den: '09:00', trang_thai: 'Có mặt', anh_checkin: 'https://x/a.jpg' });
rec('Chấm công có ảnh nhưng KHÔNG có vé khuôn mặt -> chặn', r.status === 403 && r.face_required === true);
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: today, gio_den: '09:00', trang_thai: 'Có mặt', anh_checkin: 'https://x/a.jpg', face_token: goodToken.replace(/.$/, (c) => (c === 'a' ? 'b' : 'a')) });
rec('Vé giả (sửa 1 ký tự) -> chặn', r.status === 403);
r = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: today, gio_den: '09:00', trang_thai: 'Có mặt', anh_checkin: 'https://x/a.jpg', face_token: goodToken });
rec('Vé thật -> chấm công được, ghi "đã xác minh khuôn mặt"', r.success && r.data && r.data.face_verified === true && !('face_token' in r.data));
const manual = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: '01/01/2026', trang_thai: 'SHIFT', so_gio: 8 });
rec('Chủ tiệm nhập ca tay (không ảnh) không bị ảnh hưởng', manual.success === true);
const off = await api('/api/hr/chamcong', 'POST', { ma_nv: CODE, ngay_cham: '02/01/2026', gio_den: '09:00', trang_thai: 'Có mặt', anh_checkin: 'https://x/b.jpg', offline_sync: true });
rec('Chấm công lúc mất mạng (đồng bộ sau) -> lưu, gắn cờ "chưa xác minh"', off.success && off.data.face_verified === false && /offline/.test(off.data.face_note || ''));

// --- Luồng app nhân viên (camera giả + mô phỏng face-api: mở mắt -> chớp -> mở)
await api('/api/hr/face/' + CODE, 'DELETE');
py(`
from mongo_client import db
print(db.chamcong.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'}).deleted_count)`);  // lượt chấm công hôm nay của phần test API -> app không bị coi là trùng
await p.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
await p.evaluate(() => { ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar', 'bp_da_diem_danh'].forEach((k) => localStorage.removeItem(k)); });
await p.evaluate((seed) => {
  const v = Array.from({ length: 128 }, (_, i) => Math.sin(seed * 31 + i * 0.7) * 0.15);
  const seq = [0.3, 0.31, 0.3, 0.32, 0.15, 0.12, 0.3, 0.31]; let k = 0;
  window.__faceApiOverride = () => Promise.resolve({ descriptor: v, ear: seq[Math.min(k++, seq.length - 1)] });
}, 1);
await p.fill('#login_manv', CODE.toLowerCase()); await p.click('#btn_login_submit');
await p.waitForSelector('#checkinScreen:not(.hidden)', { timeout: 10000 });
await p.waitForTimeout(800);
await p.evaluate(() => startCameraAndGPS());
await p.waitForSelector('#confirm-modal:not(.hidden)', { timeout: 20000 }).catch(() => {});
const consentMsg = await p.textContent('#confirm-msg').catch(() => '');
rec('App — lần đầu: hỏi ĐỒNG Ý lưu mẫu khuôn mặt', /face template/i.test(consentMsg) && /delete it/i.test(consentMsg), consentMsg.slice(0, 80));
await p.click('#btn-confirm-yes');
await p.waitForFunction(() => /registered/i.test(document.getElementById('faceStatus').textContent), null, { timeout: 15000 }).catch(() => {});
await p.waitForFunction(() => !document.getElementById('captureBtn').disabled, null, { timeout: 15000 }).catch(() => {});
rec('App — chớp mắt xong: đăng ký + mở nút chụp', !(await p.$eval('#captureBtn', (e) => e.disabled)), await p.textContent('#faceStatus'));
const netLog = []; p.on('response', (x) => { if (/storage|chamcong/.test(x.url())) netLog.push(x.request().method() + ' ' + x.url().replace(BASE, '') + ' ' + x.status()); });
const [resp] = await Promise.all([p.waitForResponse((x) => x.url().endsWith('/api/hr/chamcong') && x.request().method() === 'POST', { timeout: 20000 }).catch(() => null), p.click('#captureBtn')]);
const body = resp ? await resp.json() : {};
rec('App — chấm công thành công, có xác minh khuôn mặt + GPS Sydney', body.success && body.data.face_verified === true && /^-33\.8/.test(body.data.toa_do || ''), JSON.stringify({ toa_do: body.data && body.data.toa_do }));

// Người khác cầm máy, gõ mã của nhân viên này
await p.evaluate(() => { ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar', 'bp_da_diem_danh'].forEach((k) => localStorage.removeItem(k)); });
await p.goto(BASE + '/app_nhanvien', { waitUntil: 'networkidle' });
await p.evaluate(() => { ['bp_emp_name', 'bp_emp_code', 'bp_emp_linhvuc', 'bp_emp_avatar', 'bp_da_diem_danh'].forEach((k) => localStorage.removeItem(k)); });
await p.reload({ waitUntil: 'networkidle' });
await p.evaluate(() => {
  const v = Array.from({ length: 128 }, (_, i) => Math.sin(7 * 31 + i * 0.7) * 0.15);
  const seq = [0.3, 0.3, 0.31, 0.3, 0.14, 0.3, 0.31]; let k = 0;
  window.__faceApiOverride = () => Promise.resolve({ descriptor: v, ear: seq[Math.min(k++, seq.length - 1)] });
});
await p.fill('#login_manv', CODE.toLowerCase()); await p.click('#btn_login_submit');
await p.waitForSelector('#checkinScreen:not(.hidden)', { timeout: 10000 });
await p.waitForTimeout(600);
await p.evaluate(() => startCameraAndGPS());
await p.waitForFunction(() => /match/i.test(document.getElementById('faceStatus').textContent), null, { timeout: 20000 }).catch(() => {});
rec('App — người khác dùng mã -> báo không khớp, nút chụp vẫn khoá', /doesn't match/i.test(await p.textContent('#faceStatus')) && await p.$eval('#captureBtn', (e) => e.disabled) && !(await p.$eval('#faceRetryBtn', (e) => e.classList.contains('hidden'))), await p.textContent('#faceStatus'));

// Ảnh tĩnh (không chớp mắt) -> không qua
{
  const res = await p.evaluate(async () => {
    window.__faceApiOverride = () => Promise.resolve({ descriptor: Array(128).fill(0.01), ear: 0.3 });  // mắt luôn mở như ảnh in
    faceRunning = true;
    try { await captureFaceWithBlink(); return 'passed'; } catch (e) { return e.message; } finally { faceRunning = false; }
  });
  rec('Ảnh in giơ trước camera (không chớp mắt) -> bị từ chối sau 25 giây', /didn't see a blink/i.test(res), res);
}

// --- Mô hình nhận diện thật tải được từ CDN và chạy trên khung hình camera
{
  const m = await b.newPage();
  await m.goto(BASE + '/login');  // trang http://127.0.0.1 là 'secure context' -> được dùng camera (about:blank thì không)
  await m.evaluate(() => { document.body.innerHTML = '<video id="v" autoplay muted playsinline width="320" height="240"></video>'; });
  const res = await m.evaluate(async () => {
    const load = (src) => new Promise((ok, no) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = () => no(new Error('script ' + src)); document.head.appendChild(s); });
    try {
      const t0 = performance.now();
      await load('https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/dist/face-api.js');
      const M = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/model/';
      await faceapi.nets.tinyFaceDetector.loadFromUri(M); await faceapi.nets.faceLandmark68Net.loadFromUri(M); await faceapi.nets.faceRecognitionNet.loadFromUri(M);
      const v = document.getElementById('v'); v.srcObject = await navigator.mediaDevices.getUserMedia({ video: true }); await v.play();
      await new Promise((r) => setTimeout(r, 500));
      const r = await faceapi.detectSingleFace(v, new faceapi.TinyFaceDetectorOptions()).withFaceLandmarks().withFaceDescriptor();
      return { ok: true, ms: Math.round(performance.now() - t0), face: !!r };
    } catch (e) { return { ok: false, err: e.message }; }
  });
  rec('Mô hình nhận diện thật (face-api) tải từ CDN + chạy trên camera', res.ok, JSON.stringify(res));
  await m.close();
}

// Tắt tính năng -> xoá mọi mẫu khuôn mặt
r = await api('/api/hr/face/settings', 'POST', { enabled: false });
const left = py(`
from mongo_client import db
print(db.employees.count_documents({'business_id': ${B}, 'face_template': {'$exists': True}}))`);
rec('Tắt chấm công khuôn mặt -> xoá MỌI mẫu khuôn mặt của tiệm', r.success && r.enabled === false && left === '0');
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

if (before.enabled) await api('/api/hr/face/settings', 'POST', { enabled: true });
py(`
from mongo_client import db
db.chamcong.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.employees.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.staff.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
db.face_checks.delete_many({'business_id': ${B}, 'ma_nv': '${CODE}'})
print('cleaned')`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
