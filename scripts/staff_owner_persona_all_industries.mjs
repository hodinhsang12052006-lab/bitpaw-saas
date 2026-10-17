/**
 * scripts/staff_owner_persona_all_industries.mjs — ĐÓNG VAI chủ tiệm + nhân viên cho CẢ 9 NGÀNH.
 * Mỗi ngành, trên tiệm demo của ngành đó:
 *   CHỦ TIỆM tạo 1 nhân viên test (đúng bộ phận của ngành), giao 1 job (Kỹ thuật).
 *   NHÂN VIÊN (app nhân viên trên máy của tiệm): đăng nhập mã NV -> chấm công camera + GPS -> khung bằng chứng
 *     đúng ngành (ảnh / chữ ký) -> báo cáo công việc -> xin nghỉ -> hoàn ứng -> khen đồng nghiệp ->
 *     đổi ca (F&B) / nhận + hoàn thành job (Kỹ thuật) -> đăng xuất.
 *   CHỦ TIỆM duyệt đơn nghỉ + hoàn ứng, mở trang chấm công của ngành thấy nhân viên, bảng lương có nhân viên
 *     với lương giờ đúng 8h × đơn giá (ngành tính lương theo giờ).
 * Đối chiếu DB thật; nhân viên test + mọi dữ liệu liên quan được XOÁ khi kết thúc từng ngành.
 *   node scripts/staff_owner_persona_all_industries.mjs        (ONLY=nail,fnb để chạy vài ngành)
 */
import { chromium } from 'playwright';
import fs from 'fs';
import { execFileSync } from 'child_process';

const BASE = 'http://127.0.0.1:5001';
const T = {
  nail: ['demo.nails.au.006758@bitpawdemo.com', 'DemoNails2026!', 'Nails', '/chamcong/nail'],
  fnb: ['demo.fnb.343602@bitpawdemo.com', 'DemoBitPaw2026!', 'F&B', '/chamcong/fnb'],
  spa: ['demo.spa.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Spa', '/chamcong/spa'],
  retail: ['demo.retail.596348@bitpawdemo.com', 'DemoBitPaw2026!', 'Retail', '/chamcong/retail'],
  karaoke: ['demo.karaoke.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Karaoke', '/chamcong/karaoke'],
  hotel: ['demo.hotel.071443@bitpawdemo.com', 'DemoBitPaw2026!', 'Khách sạn', '/chamcong/khachsan'],
  production: ['demo.production.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Sản xuất', '/chamcong/congnhan'],
  technical: ['demo.technical.393328@bitpawdemo.com', 'DemoBitPaw2026!', 'Kỹ thuật', '/chamcong/kythuat'],
  office: ['demo.office.784966@bitpawdemo.com', 'DemoBitPaw2026!', 'Văn phòng', '/chamcong/vanphong'],
};
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : Object.keys(T);
const POS_PAID = new Set(['nail', 'spa']);                    // hoa hồng/tip từ bill POS -> không tự khai tiền
const HOURLY = new Set(['nail', 'spa', 'fnb', 'hotel', 'retail', 'karaoke', 'production', 'technical']);
const EVIDENCE = { photo: new Set(['nail', 'spa', 'fnb', 'technical', 'production']), signature: new Set(['technical', 'production']) };
const RESTART = `${process.env.HOME || process.env.USERPROFILE}/restart_flask.sh`;
const NOISE = /ERR_CONNECTION_RESET|ERR_ABORTED|ERR_NETWORK_CHANGED|net::ERR_FAILED/;

const results = [];
const rec = (ind, role, name, ok, note = '') => {
  results.push({ ind, role, name, ok, note });
  console.log(`${ok ? '✅' : '❌'} [${ind}][${role}] ${name}${note ? ' — ' + note : ''}`);
};
const db = (...a) => JSON.parse(execFileSync('python', ['scripts/_nail_persona_db.py', ...a], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split('\n').pop());
const api = (page, method, url, body) => page.evaluate(async ({ method, url, body }) => {
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let json = null; try { json = await r.json(); } catch (e) { /* not json */ }
  return { status: r.status, json };
}, { method, url, body });
async function go(page, p) {
  for (let i = 0; i < 3; i++) { try { await page.goto(BASE + p, { waitUntil: 'networkidle', timeout: 40000 }); return; } catch (e) { if (i === 2) throw e; } }
}
function watch(page, bucket) {
  page.on('pageerror', (e) => bucket.push('pageerror: ' + e.message.split('\n')[0]));
  page.on('console', (m) => { if (m.type() === 'error' && !NOISE.test(m.text()) && !m.text().startsWith('Failed to load resource')) bucket.push(m.text().slice(0, 140)); });
  page.on('response', (r) => { if (r.status() >= 500 && r.url().startsWith(BASE)) bucket.push(`HTTP ${r.status()} ${r.url().replace(BASE, '')}`); });
}

const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
const todayGB = new Date().toLocaleDateString('en-GB');
let logins = 0;

for (const ind of ONLY) {
  const [email, pw, linhVuc, ccPage] = T[ind];
  const MA_NV = 'QA' + String(Math.floor(1000 + Math.random() * 9000));
  const HO_TEN = `QA Persona ${ind} ${MA_NV}`;
  const { business_id: BID } = db('business', email);
  let colleague = null; let kudoBefore = 0;
  try {
    if (logins >= 4 && fs.existsSync(RESTART)) { execFileSync('bash', [RESTART], { stdio: 'ignore' }); logins = 0; }
    logins++;
    // ---------- CHỦ TIỆM ----------
    const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const owner = await ownerCtx.newPage();
    const ownerErr = []; watch(owner, ownerErr);
    await go(owner, '/login');
    await owner.fill('#loginEmail', email); await owner.fill('#loginPassword', pw);
    await Promise.all([owner.waitForLoadState('networkidle').catch(() => {}), owner.click('#btnLogin')]);
    await owner.waitForTimeout(800);
    if (owner.url().includes('/login')) throw new Error('đăng nhập chủ tiệm thất bại (giới hạn đăng nhập?)');
    const created = await api(owner, 'POST', '/api/hr/employees', { ma_nv: MA_NV, ho_ten: HO_TEN, linh_vuc: linhVuc, chuc_vu: 'QA', luong_gio: 20 });
    rec(ind, 'Chủ', `Tạo nhân viên ${MA_NV} (${linhVuc}, $20/giờ)`, created.json?.success === true, `HTTP ${created.status}`);
    const emps = (await api(owner, 'GET', '/api/hr/employees')).json?.data || [];
    colleague = emps.find((e) => e.ma_nv !== MA_NV && !/^QA/.test(e.ma_nv));
    kudoBefore = colleague ? db('kudo', BID, colleague.ma_nv).diem_kudo : 0;
    let taskId = null;
    if (ind === 'technical') {
      const t = await api(owner, 'POST', '/api/tasks', { ten_khach: `QA Persona Khách ${MA_NV}`, dia_chi: '12 Lê Lợi, Q1', sdt: '0900000000', noi_dung: 'Sửa máy lạnh không lạnh' });
      taskId = t.json?.data?.id;
      rec(ind, 'Chủ', 'Giao 1 job sửa chữa', !!taskId, `job #${taskId}`);
    }

    // ---------- NHÂN VIÊN ----------
    const staffCtx = await browser.newContext({
      viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, permissions: ['camera', 'geolocation'],
      geolocation: { latitude: 10.7769, longitude: 106.7009 }, storageState: await ownerCtx.storageState(),
    });
    const staff = await staffCtx.newPage();
    const staffErr = []; watch(staff, staffErr);
    await go(staff, '/app_nhanvien');
    await staff.fill('#login_manv', MA_NV);
    await staff.click('#btn_login_submit');
    await staff.waitForSelector('#checkinScreen:not(.hidden)', { timeout: 10000 });
    await staff.click('[onclick="startCameraAndGPS()"]', { force: true });   // nút có hiệu ứng nhịp thở
    await staff.waitForSelector('#captureBtn:not([disabled])', { timeout: 15000 });
    await staff.click('#captureBtn');
    await staff.waitForSelector('#mainApp:not(.hidden)', { timeout: 15000 });
    await staff.waitForTimeout(800);
    let st = db('state', BID, MA_NV);
    const ci = st.chamcong.find((r) => r.trang_thai === 'Có mặt');
    rec(ind, 'Thợ', 'Chấm công camera + GPS (có ảnh, toạ độ)', !!ci?.anh_checkin && /^10\.77/.test(ci?.toa_do || ''), ci ? ci.toa_do : 'không có bản ghi');

    const photoVis = await staff.locator('#photo_evidence_box').isVisible();
    const sigVis = await staff.locator('#signature_evidence_box').isVisible().catch(() => false);
    rec(ind, 'Thợ', 'Khung bằng chứng đúng ngành (ảnh / chữ ký)',
      photoVis === EVIDENCE.photo.has(ind) && sigVis === EVIDENCE.signature.has(ind), `ảnh=${photoVis} chữ ký=${sigVis}`);
    const moneyVis = await staff.locator('#work_money').isVisible();
    rec(ind, 'Thợ', POS_PAID.has(ind) ? 'Ẩn ô tự khai tiền (hoa hồng theo bill POS)' : 'Có ô doanh thu / tips cho báo cáo', moneyVis === !POS_PAID.has(ind));
    await staff.fill('#work_content', `QA persona report ${MA_NV}`);
    if (moneyVis) { await staff.fill('#work_money', '50'); await staff.fill('#work_tip', '5'); }
    if (sigVis) {   // ký tên khách lên khung chữ ký (cuộn tới khung trước — ngoài màn hình thì chuột vẽ trượt)
      await staff.locator('#signature_evidence_box canvas').scrollIntoViewIfNeeded();
      const box = await staff.locator('#signature_evidence_box canvas').boundingBox();
      if (box) { await staff.mouse.move(box.x + 20, box.y + 20); await staff.mouse.down(); await staff.mouse.move(box.x + 120, box.y + 50, { steps: 8 }); await staff.mouse.up(); }
      rec(ind, 'Thợ', 'Khách ký tên lên khung chữ ký', await staff.evaluate(() => !isSignatureEmpty()));
    }
    await staff.click('#btn_submit_report');
    await staff.waitForTimeout(1800);
    st = db('state', BID, MA_NV);
    const rep = st.chamcong.find((r) => (r.ghi_chu || '').includes(`QA persona report ${MA_NV}`));
    rec(ind, 'Thợ', 'Gửi báo cáo công việc', !!rep && (POS_PAID.has(ind) ? !rep.tien_tua : true) && (!sigVis || /Chữ Ký/.test(rep.ghi_chu || '')),
      rep ? `tua=${rep.tien_tua} tips=${rep.tien_tips}${sigVis ? (/Chữ Ký/.test(rep.ghi_chu) ? ' · có chữ ký' : ' · THIẾU chữ ký') : ''}` : 'không thấy');

    await staff.evaluate(() => switchAppTab('apps'));
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    await staff.fill('#app_leave_date', tomorrow);
    await staff.fill('#app_leave_reason', 'QA persona nghỉ phép');
    await staff.click('[onclick="sendLeaveRequest()"]');
    await staff.fill('#app_expense_amount', '30');
    await staff.fill('#app_expense_desc', 'QA persona mua vật tư');
    await staff.click('[onclick="sendExpenseRequest()"]');
    await staff.waitForTimeout(1500);
    st = db('state', BID, MA_NV);
    rec(ind, 'Thợ', 'Gửi đơn xin nghỉ + hoàn ứng', st.leave.length === 1 && st.expense.length === 1);
    if (colleague) {
      await staff.selectOption('#app_kudo_receiver', colleague.ma_nv);
      await staff.click('[onclick="sendKudo()"]'); await staff.waitForTimeout(1000);
      rec(ind, 'Thợ', 'Khen đồng nghiệp +1', db('kudo', BID, colleague.ma_nv).diem_kudo === kudoBefore + 1);
    }
    const swapVis = await staff.locator('#box_swap').isVisible();
    const SWAP = new Set(['fnb', 'karaoke', 'retail']);
    rec(ind, 'Thợ', SWAP.has(ind) ? 'Có mục xin đổi ca (ngành làm theo ca)' : 'Không có mục đổi ca (ngành không đổi ca)', swapVis === SWAP.has(ind));
    if (swapVis && colleague) {
      await staff.selectOption('#app_swap_receiver', colleague.ma_nv);
      await staff.click('[onclick="sendSwapRequest()"]'); await staff.waitForTimeout(1000);
      rec(ind, 'Thợ', 'Gửi yêu cầu đổi ca cho đồng nghiệp', db('state', BID, MA_NV).swaps.length === 1);
    }
    if (taskId) {
      await staff.evaluate(() => switchAppTab('jobs')); await staff.waitForTimeout(1200);
      const card = staff.locator(`#available_jobs_container [data-task-id="${taskId}"]`);
      rec(ind, 'Thợ', 'Thấy job mới trong danh sách việc', await card.count() === 1);
      await card.locator('[data-action="nhan"]').click(); await staff.click('#btn-confirm-yes'); await staff.waitForTimeout(1500);
      const mine = staff.locator(`#my_jobs_container [data-task-id="${taskId}"]`);
      rec(ind, 'Thợ', 'Nhận job -> chuyển sang "việc của tôi"', await mine.count() === 1 && db('state', BID, MA_NV).tasks[0]?.trang_thai === 'Đã Nhận');
      await mine.locator('[data-action="hoanthanh"]').click(); await staff.click('#btn-confirm-yes'); await staff.waitForTimeout(1500);
      rec(ind, 'Thợ', 'Hoàn thành job', db('state', BID, MA_NV).tasks[0]?.trang_thai === 'Hoàn Thành');
    }
    await staff.evaluate(() => switchAppTab('profile'));
    await staff.click('[onclick="dangXuat()"]'); await staff.click('#btn-confirm-yes');
    await staff.waitForEvent('load', { timeout: 10000 }).catch(() => {}); await staff.waitForTimeout(600);
    rec(ind, 'Thợ', 'Đăng xuất', await staff.locator('#authScreen').isVisible());
    rec(ind, 'Thợ', 'Không lỗi JS / lỗi server trong app nhân viên', staffErr.length === 0, staffErr.slice(0, 3).join(' | '));
    await staffCtx.close();

    // ---------- CHỦ TIỆM duyệt + kiểm tra ----------
    st = db('state', BID, MA_NV);
    await go(owner, '/leave_requests');
    await owner.click(`button[onclick="respond(${st.leave[0]?.id}, 'approved')"]`, { timeout: 8000 }).catch(() => {});
    await owner.waitForTimeout(1000);
    await go(owner, '/expense_requests');
    await owner.click(`button[onclick="respond(${st.expense[0]?.id}, 'approved')"]`, { timeout: 8000 }).catch(() => {});
    await owner.waitForTimeout(1000);
    st = db('state', BID, MA_NV);
    rec(ind, 'Chủ', 'Duyệt đơn nghỉ + hoàn ứng', st.leave[0]?.status === 'approved' && st.expense[0]?.status === 'approved');
    await go(owner, ccPage); await owner.waitForTimeout(1500);
    rec(ind, 'Chủ', `Trang chấm công ngành (${ccPage}) có nhân viên mới`, (await owner.content()).includes(HO_TEN));
    if (st.swaps.length) {   // chủ tiệm duyệt yêu cầu đổi ca ngay trên trang chấm công
      const row = owner.locator(`#swapRequestsBox [data-swap-id="${st.swaps[0].id}"]`);
      const seen = await row.count() === 1;
      if (seen) { await row.locator('[data-swap-act="ok"]').click(); await owner.waitForTimeout(1500); }
      const after = db('state', BID, MA_NV);
      rec(ind, 'Chủ', 'Thấy + duyệt yêu cầu đổi ca của nhân viên', seen && after.swaps[0]?.trang_thai === 'Đã chốt' && after.chamcong.some((r) => r.trang_thai === 'Nghỉ đổi ca'));
    }
    let pay = null;
    for (let i = 0; i < 2 && !pay; i++) {   // trang lớn đôi khi bị reset kết nối trên máy dev -> tải lại 1 lần
      await go(owner, '/bangluong');
      await owner.waitForFunction((c) => typeof globalPayrollData !== 'undefined' && globalPayrollData.some((p) => p.ma_nv === c), MA_NV, { timeout: 15000 }).catch(() => {});
      pay = await owner.evaluate((c) => (typeof globalPayrollData !== 'undefined' ? globalPayrollData : []).find((p) => p.ma_nv === c), MA_NV);
    }
    const expect = HOURLY.has(ind) ? 8 * 20 : null;
    rec(ind, 'Chủ', HOURLY.has(ind) ? 'Bảng lương: lương giờ = 8h × $20' : 'Bảng lương có nhân viên', !!pay && (expect === null || Math.abs(pay.luong_hien_thi - expect) < 0.01),
      pay ? `lương chính ${pay.luong_hien_thi} · thực lãnh ${pay.thuc_lanh}` : 'không thấy');
    rec(ind, 'Chủ', 'Không lỗi JS / lỗi server ở các trang chủ tiệm', ownerErr.length === 0, ownerErr.slice(0, 3).join(' | '));
    await ownerCtx.close();
  } catch (e) {
    rec(ind, '—', 'LỖI KHÔNG MONG MUỐN', false, e.message.split('\n').filter((l) => /waiting for|Timeout|Error/.test(l)).slice(0, 2).join(' / '));
  } finally {
    if (colleague) execFileSync('python', ['-c', `import sys; sys.path.insert(0,'.'); from mongo_client import db; db.employees.update_one({'business_id': ${JSON.stringify(BID)}, 'ma_nv': ${JSON.stringify(colleague.ma_nv)}}, {'$set': {'diem_kudo': ${kudoBefore}}})`]);
    console.log(`   dọn ${ind}:`, JSON.stringify(db('cleanup', BID, MA_NV, HO_TEN)));
  }
}
await browser.close();
const fail = results.filter((r) => !r.ok).length;
fs.writeFileSync('audit-results/staff_owner_persona_report.json', JSON.stringify({ ran_at: new Date().toISOString(), results }, null, 2));
console.log(`\nTổng kết: ${results.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
