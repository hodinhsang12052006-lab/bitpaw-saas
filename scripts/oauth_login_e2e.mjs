// oauth_login_e2e.mjs — Đăng nhập/đăng ký bằng Google + Facebook với MÁY CHỦ OAUTH GIẢ LẬP local (cổng 5098).
// Server phải chạy với GOOGLE_CLIENT_ID/SECRET, FACEBOOK_APP_ID/SECRET (giá trị test) + OAUTH_TEST_BASE=http://127.0.0.1:5098
// (scratchpad/restart_oauth.sh). Không đụng Google/Facebook thật.   node scripts/oauth_login_e2e.mjs
import { chromium } from 'playwright';
import http from 'http';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const STAMP = String(Date.now()).slice(-6);
const NEW_EMAIL = `oauth.new.${STAMP}@example.com`, LINK_EMAIL = `oauth.link.${STAMP}@example.com`;

// ---- máy chủ OAuth giả lập: user hiện tại do test chọn qua /set
let who = { google: null, facebook: null };
const codes = {}, seen = { pkce: 0, secret: 0 };
const stub = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://127.0.0.1:5098');
  const [, prov, step] = u.pathname.split('/');
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    if (step === 'authorize') {  // "trang đồng ý": đồng ý ngay, trả code + state về redirect_uri
      const code = 'code_' + Math.random().toString(36).slice(2);
      codes[code] = { prov, user: who[prov], challenge: u.searchParams.get('code_challenge') };
      const back = new URL(u.searchParams.get('redirect_uri'));
      back.searchParams.set('code', code); back.searchParams.set('state', u.searchParams.get('state'));
      res.writeHead(302, { Location: back.toString() }); return res.end();
    }
    if (step === 'token') {
      const params = new URLSearchParams(prov === 'google' ? body : u.search.slice(1));
      const c = codes[params.get('code')];
      if (!c || params.get('client_secret') !== 'test-secret') { res.writeHead(400); return res.end('{"error":"invalid_grant"}'); }
      seen.secret++;
      if (prov === 'google' && params.get('code_verifier')) seen.pkce++;
      delete codes[params.get('code')];
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ access_token: 'at_' + Buffer.from(JSON.stringify(c.user)).toString('base64url') }));
    }
    if (step === 'userinfo') {
      const tok = (req.headers.authorization || '').replace('Bearer at_', '');
      const user = JSON.parse(Buffer.from(tok, 'base64url').toString());
      res.writeHead(200, { 'Content-Type': 'application/json' }); return res.end(JSON.stringify(user));
    }
    res.writeHead(404); res.end();
  });
}).listen(5098);

const b = await chromium.launch({ channel: 'chrome' });
const fresh = async () => (await b.newContext({ viewport: { width: 1280, height: 860 } })).newPage();

// 0) nút hiện trên trang đăng nhập
let p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
rec('Trang đăng nhập có nút Google + Facebook', await p.locator('#btnGoogle').count() >= 1 && await p.locator('#btnFacebook').count() >= 1);
{ // app di động (WebView): Google chặn OAuth trong WebView -> không hiện nút
  const actx = await b.newContext({ userAgent: 'Mozilla/5.0 (Linux; Android 14) BitPawMobileApp/1.0.0 (Android; WebView)' });
  const ap = await actx.newPage(); await ap.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  rec('Trong app di động không hiện nút Google/Facebook (Google chặn WebView)', await ap.locator('#btnGoogle').count() === 0 && await ap.locator('#btnFacebook').count() === 0);
  await actx.close();
}

// 1) người mới bằng Google -> trang hoàn tất -> mã kích hoạt -> vào app
const LIC = `OAUTH-TEST-${STAMP}`;
py(`
from mongo_client import db, next_mongo_id
db.license_codes.insert_one({'license_key': '${LIC}', 'trang_thai': 'Sẵn sàng', 'nganh_nghe': 'spa', 'note': 'oauth e2e'})
print('ok')`);
who.google = { sub: 'g-' + STAMP, email: NEW_EMAIL, email_verified: true, name: 'Olivia OAuth' };
await p.click('#btnGoogle');
await p.waitForURL(/\/auth\/complete/, { timeout: 15000 }).catch(() => {});
rec('Google người mới -> trang "Hoàn tất đăng ký" (đúng tên + email)', p.url().includes('/auth/complete') && (await p.textContent('body')).includes(NEW_EMAIL));
await p.fill('#license_key', 'WRONG-CODE'); await p.fill('#business_name', 'Olivia Day Spa');
await p.click('button[type=submit]'); await p.waitForLoadState('domcontentloaded');
rec('Mã kích hoạt sai -> báo lỗi rõ, không tạo tài khoản', /Invalid activation code|không hợp lệ/i.test(await p.textContent('body')) &&
    py(`
from mongo_client import db
print(db.users.count_documents({'email': '${NEW_EMAIL}'}))`) === '0');
await p.fill('#license_key', LIC); await p.fill('#business_name', 'Olivia Day Spa');
await Promise.all([p.waitForNavigation({ timeout: 20000 }).catch(() => {}), p.click('button[type=submit]')]);
await p.waitForLoadState('networkidle').catch(() => {});
const made = JSON.parse(py(`
import json
from mongo_client import db
u = db.users.find_one({'email': '${NEW_EMAIL}'}, {'_id': 0, 'id': 1, 'oauth': 1, 'password_hash': 1, 'role': 1})
bz = db.businesses.find_one({'id': (u or {}).get('id')}, {'_id': 0, 'name': 1, 'industry_code': 1})
lic = db.license_codes.find_one({'license_key': '${LIC}'}, {'_id': 0, 'trang_thai': 1})
print(json.dumps({'u': u, 'b': bz, 'lic': lic}))`));
rec('Tạo tài khoản: liên kết Google, không mật khẩu, tiệm đúng ngành theo mã, mã đã dùng', made.u && made.u.oauth.google === 'g-' + STAMP && !made.u.password_hash &&
    made.b.name === 'Olivia Day Spa' && made.b.industry_code === 'spa' && made.lic.trang_thai === 'Đã kích hoạt', JSON.stringify(made.b));
rec('Đăng ký xong vào thẳng app (không phải trang đăng nhập)', !/\/login|\/auth\//.test(p.url()), p.url().replace(BASE, ''));

// 2) lần sau: Google cùng tài khoản -> đăng nhập thẳng
p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await Promise.all([p.waitForNavigation({ timeout: 20000 }).catch(() => {}), p.click('#btnGoogle')]);
await p.waitForLoadState('networkidle').catch(() => {});
rec('Google lần 2 -> đăng nhập thẳng vào app', !/\/login|\/auth\//.test(p.url()), p.url().replace(BASE, ''));

// 3) tài khoản email/mật khẩu sẵn có -> Facebook cùng email (đã xác minh) -> liên kết + đăng nhập
py(`
from mongo_client import db
from werkzeug.security import generate_password_hash
import uuid
uid = str(uuid.uuid4())
db.users.insert_one({'id': uid, 'email': '${LINK_EMAIL}', 'password_hash': generate_password_hash('Pw-Linked-123!'), 'business_id': uid, 'role': 'admin'})
db.businesses.insert_one({'id': uid, 'name': 'Linked Nails', 'industry_code': 'nail'})
db.system_settings.update_one({'key': 'business_mode_' + uid}, {'$set': {'key': 'business_mode_' + uid, 'value': 'nail'}}, upsert=True)
print(uid)`);
who.facebook = { id: 'fb-' + STAMP, email: LINK_EMAIL, name: 'Liam Linked' };
p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await Promise.all([p.waitForNavigation({ timeout: 20000 }).catch(() => {}), p.click('#btnFacebook')]);
await p.waitForLoadState('networkidle').catch(() => {});
const linked = py(`
from mongo_client import db
print((db.users.find_one({'email': '${LINK_EMAIL}'}, {'oauth': 1}) or {}).get('oauth', {}).get('facebook'))`);
rec('Facebook cùng email -> liên kết vào tài khoản sẵn có + đăng nhập', linked === 'fb-' + STAMP && !/\/login|\/auth\//.test(p.url()), p.url().replace(BASE, ''));

// 4) Google email CHƯA xác minh trùng tài khoản sẵn có -> KHÔNG được liên kết (chống chiếm tài khoản)
who.google = { sub: 'g-evil-' + STAMP, email: LINK_EMAIL, email_verified: false, name: 'Attacker' };
p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await Promise.all([p.waitForNavigation({ timeout: 20000 }).catch(() => {}), p.click('#btnGoogle')]);
await p.waitForLoadState('domcontentloaded');
const evil = py(`
from mongo_client import db
print((db.users.find_one({'email': '${LINK_EMAIL}'}, {'oauth': 1}) or {}).get('oauth', {}).get('google'))`);
rec('Email chưa xác minh -> từ chối liên kết, không vào được tài khoản người khác', evil === 'None' && /\/login/.test(p.url()) && /not verified|chưa xác minh/i.test(await p.textContent('body')));

// 5) callback giả mạo (state sai / không bắt đầu từ đây) -> từ chối
p = await fresh();
await p.goto(BASE + '/auth/google/callback?code=abc&state=forged', { waitUntil: 'domcontentloaded' });
rec('Callback giả (state sai) -> từ chối, ở lại trang đăng nhập', /\/login/.test(p.url()) && /expired|not started/i.test(await p.textContent('body')));

// 6) chặn open-redirect qua ?next=
who.google = { sub: 'g-' + STAMP, email: NEW_EMAIL, email_verified: true, name: 'Olivia OAuth' };
p = await fresh();
await p.goto(BASE + '/auth/google/start?next=https://evil.example.com/steal', { waitUntil: 'domcontentloaded' }).catch(() => {});
await p.waitForLoadState('networkidle').catch(() => {});
rec('next=https://evil… bị bỏ qua (không chuyển ra ngoài)', p.url().startsWith(BASE), p.url().slice(0, 60));

// 7) Facebook không chia sẻ email + người mới -> báo rõ
who.facebook = { id: 'fb-noemail-' + STAMP, name: 'No Email' };
p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await Promise.all([p.waitForNavigation({ timeout: 20000 }).catch(() => {}), p.click('#btnFacebook')]);
await p.waitForLoadState('domcontentloaded');
rec('Facebook không có email -> báo dùng email để đăng ký', /did not share an email/i.test(await p.textContent('body')));
rec('Đổi code lấy token ở máy chủ (có client secret) + Google có PKCE', seen.secret >= 4 && seen.pkce >= 2, JSON.stringify(seen));

// 8) tài khoản chỉ có Google mà đăng nhập bằng mật khẩu -> báo lỗi gọn, không 500
p = await fresh();
await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
await p.fill('#loginEmail', NEW_EMAIL); await p.fill('#loginPassword', 'whatever123');
const [resp] = await Promise.all([p.waitForResponse((r) => r.url().endsWith('/login') && r.request().method() === 'POST'), p.click('#btnLogin')]);
rec('Tài khoản Google-only đăng nhập mật khẩu -> báo sai, không lỗi 500', resp.status() < 500);

// dọn
py(`
from mongo_client import db
for em in ('${NEW_EMAIL}', '${LINK_EMAIL}'):
    u = db.users.find_one({'email': em}, {'id': 1})
    if u:
        db.businesses.delete_many({'id': u['id']}); db.system_settings.delete_many({'key': 'business_mode_' + u['id']})
        db.user_logs.delete_many({'user_email': em}); db.business_memberships.delete_many({'owner_user_id': u['id']})
    db.users.delete_many({'email': em})
db.license_codes.delete_many({'license_key': '${LIC}'})
print('cleaned')`);
stub.close(); await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
