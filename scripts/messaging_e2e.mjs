// messaging_e2e.mjs — xương sống nhắn tin (SMS Twilio + email) chạy thật, với máy chủ Twilio GIẢ trên máy (không gửi SMS thật).
//   Server local phải chạy với TWILIO_API_BASE=http://127.0.0.1:5099 (scratchpad/restart_msg.sh)
//   node scripts/messaging_e2e.mjs
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import http from 'http';
import crypto from 'crypto';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const SID = 'ACtest0000000000000000000000000001', TOKEN = 'test_auth_token_123';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const pyEnv = { ...process.env, PYTHONIOENCODING: 'utf-8', TWILIO_API_BASE: 'http://127.0.0.1:5099', EMAIL_DISABLED: '1' };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: pyEnv }).trim().split(/\r?\n/).pop();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- Twilio giả: ghi lại mọi tin gửi
const sent = [];
const stub = http.createServer((req, res) => {
  let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
    const params = Object.fromEntries(new URLSearchParams(body));
    sent.push({ path: req.url, auth: req.headers.authorization, ...params });
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ sid: 'SM' + crypto.randomBytes(8).toString('hex'), status: 'queued' }));
  });
}).listen(5099);
const twilioSig = (url, params) => crypto.createHmac('sha1', TOKEN).update(url + Object.keys(params).sort().map((k) => k + params[k]).join('')).digest('base64');

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
// múi giờ đang trong giờ hành chính (để tin được gửi ngay, không bị dời sang sáng mai)
const tz = py(`
from datetime import datetime
from zoneinfo import ZoneInfo
c=['Australia/Sydney','Australia/Perth','America/New_York','America/Los_Angeles','Pacific/Honolulu','Pacific/Auckland','Europe/London','Asia/Ho_Chi_Minh']
print(next((z for z in c if 10 <= datetime.now(ZoneInfo(z)).hour < 18), 'Australia/Sydney'))`);
const backup = py(`
import json
from mongo_client import db
print(json.dumps(db.messaging_settings.find_one({'business_id': ${B}}, {'_id': 0}) or {}))`);

// 1) Trang cài đặt
await p.goto(BASE + '/settings/messaging', { waitUntil: 'networkidle' });
await p.waitForFunction(() => document.getElementById('hookSms').textContent.includes('/api/twilio/sms/'), null, { timeout: 10000 }).catch(() => {});
rec('Mở trang Nhắn tin & SMS không lỗi', errs.length === 0 && (await p.textContent('#smsPill')).length > 3, (await p.textContent('#smsPill')).trim());

// 2) Lưu kết nối Twilio + tự động
await p.fill('#sid', SID); await p.fill('#tok', TOKEN); await p.fill('#from', '+61 2 5550 1234'); await p.setChecked('#smsOn', true);
await p.setChecked('#remOn', true); await p.selectOption('#remHours', '24');
await p.setChecked('#revOn', true); await p.fill('#revUrl', 'https://g.page/r/golden-lotus/review'); await p.selectOption('#revDelay', '60');
await p.setChecked('#mcOn', true); await p.fill('#shopPhone', '02 9555 0100');
await p.selectOption('#tz', tz); await p.selectOption('#ws', '9'); await p.selectOption('#we', '20'); await p.selectOption('#lang', 'en');
await p.click('#saveBtn'); await p.waitForTimeout(1200);
const pill = (await p.textContent('#smsPill')).trim();
const saved = JSON.parse(py(`
import json
from mongo_client import db
d = db.messaging_settings.find_one({'business_id': ${B}}, {'_id': 0})
t = db.nurture_channel_tokens.find_one({'business_id': ${B}, 'platform': 'twilio'}, {'_id': 0})
print(json.dumps({'from': d.get('twilio_from'), 'shop': d.get('shop_phone'), 'tz': d.get('timezone'), 'enc': bool(t and t.get('access_token_enc')), 'plain': bool(t and '${TOKEN}' in str(t))}))`));
rec('Lưu kết nối — Đã kết nối, số chuẩn +61, token MÃ HOÁ', /Connected|Đã kết nối/.test(pill) && saved.from === '+61255501234' && saved.shop === '+61295550100' && saved.enc && !saved.plain, JSON.stringify(saved));

// 3) Gửi thử
await p.selectOption('#tCh', 'sms'); await p.fill('#tTo', '0400 111 222'); await p.click('#tBtn'); await p.waitForTimeout(1500);
const t1 = sent.find((m) => m.To === '+61400111222');
rec('Gửi thử SMS — tới Twilio đúng số/người gửi/xác thực', !!t1 && t1.From === '+61255501234' && t1.path.includes(`/Accounts/${SID}/Messages.json`) && t1.auth === 'Basic ' + Buffer.from(SID + ':' + TOKEN).toString('base64'), t1 ? t1.Body : (await p.textContent('#tNote')));

// 4) Nhắc lịch hẹn (giờ địa phương của tiệm)
const apptId = py(`
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from mongo_client import db, next_mongo_id
i = next_mongo_id('appointments')
t = (datetime.now(ZoneInfo('${tz}')) + timedelta(hours=5)).replace(tzinfo=None, second=0, microsecond=0)
db.appointments.insert_one({'id': i, 'business_id': ${B}, 'customer_name': 'QA Mia Tran', 'customer_phone': '0400 123 456', 'status': 'confirmed', 'book_time': t.isoformat(), 'qa_messaging': True})
print(i)`);
// 5) Đơn đã thanh toán 2 giờ trước (giờ máy chủ) -> xin đánh giá
py(`
from datetime import datetime, timedelta
from mongo_client import db, next_mongo_id
db.orders.insert_one({'id': next_mongo_id('orders'), 'business_id': ${B}, 'status': 'completed', 'total_amount': 85.0, 'customer_name': 'QA Leo Nguyen', 'customer_phone': '0400 765 432', 'created_at': (datetime.now() - timedelta(hours=2)).isoformat(), 'qa_messaging': True})
print('ok')`);
// (trang cài đặt vừa mở đã tự chạy bộ gửi qua menu -> route bị giới hạn 3 phút; chạy thẳng hàm gửi phía server)
const pump = JSON.parse(py(`
import json, messaging
print(json.dumps(messaging.pump(${B})))`));
await sleep(500);
const rem = sent.find((m) => m.To === '+61400123456');
rec('Nhắc lịch — SMS tới khách (số Úc 04xx) bằng tiếng Anh, đúng giờ tiệm', !!rem && /reminder/i.test(rem.Body) && /Golden Lotus/.test(rem.Body), rem ? rem.Body : JSON.stringify(pump));
const rev = sent.find((m) => m.To === '+61400765432');
rec('Xin đánh giá — SMS có link Google + "Reply STOP"', !!rev && rev.Body.includes('https://g.page/r/golden-lotus/review') && /Reply STOP/.test(rev.Body), rev ? rev.Body : '');
const pump2 = await p.evaluate(async () => (await fetch('/api/messages/pump', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json());
rec('Bộ gửi chạy liên tục không gửi trùng (giới hạn 3 phút + chống trùng)', pump2.skipped === true && sent.filter((m) => m.To === '+61400123456').length === 1);

// 6) Webhook STOP (có chữ ký) -> từ chối; chữ ký sai -> 403
{
  const url = `${BASE}/api/twilio/sms/${bid}`;
  const params = { From: '+61400765432', To: '+61255501234', Body: 'STOP', MessageSid: 'SMx' };
  const bad = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': 'bogus' }, body: new URLSearchParams(params) });
  rec('Webhook SMS — chữ ký giả bị chặn (403)', bad.status === 403);
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': twilioSig(url, params) }, body: new URLSearchParams(params) });
  const xml = await r.text();
  const opted = py(`
from mongo_client import db
print(db.message_optouts.count_documents({'business_id': ${B}, 'channel': 'sms', 'address': '+61400765432'}))`);
  rec('Trả lời STOP — xác nhận ngừng nhận + ghi danh sách từ chối', r.status === 200 && /unsubscribed/i.test(xml) && opted === '1', xml.slice(0, 120));
  const q = py(`
import messaging
print(messaging.queue(${B}, 'sms', '+61400765432', 'promo test', 'promo'))`);
  rec('Số đã STOP — không xếp thêm tin nào', q === 'None');
}

// 7) Cuộc gọi nhỡ: chuyển tới máy tiệm 20s, không ai nghe -> nhắn khách link đặt lịch
{
  const url = `${BASE}/api/twilio/voice/${bid}`;
  const params = { From: '+61400999888', To: '+61255501234', CallSid: 'CAx' };
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': twilioSig(url, params) }, body: new URLSearchParams(params) });
  const xml = await r.text();
  rec('Cuộc gọi tới — chuyển máy tiệm (+61295550100) 20 giây', /<Dial timeout="20"[^>]*>\+61295550100<\/Dial>/.test(xml), xml.slice(0, 160));
  const url2 = url + '/after'; const p2 = { ...params, DialCallStatus: 'no-answer' };
  const r2 = await fetch(url2, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': twilioSig(url2, p2) }, body: new URLSearchParams(p2) });
  await sleep(400);
  const mc = sent.find((m) => m.To === '+61400999888');
  rec('Không ai nghe — khách nhận SMS xin lỗi + link đặt lịch', r2.status === 200 && !!mc && mc.Body.includes(`/booking/nail/qr/${bid}`), mc ? mc.Body : '');
}

// 8) Chiến dịch AI (tiếng Anh, SMS): duyệt -> tới ngày thì gửi
{
  const camp = await p.evaluate(async () => (await fetch('/api/ai/nurture/generate-campaign', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ segment: 'CHURN', goal: 'RECALL', channel: 'SMS', tone: 'friendly' }) })).json());
  const tpl = camp.template || {};
  rec('Tạo chiến dịch — 1 lần AI, mẫu tiếng Anh, điền dữ liệu từng khách', camp.success && camp.channel === 'SMS' && /\{first_name\}/.test(tpl['3days'] || '') && !/[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(JSON.stringify(tpl)), `${camp.target_count} khách · ${camp.messages_count} tin · "${(tpl['3days'] || '').slice(0, 70)}"`);
  if (camp.success && camp.messages_count) {
    const first = JSON.parse(py(`
import json
from mongo_client import db
m = db.campaign_messages.find_one({'campaign_id': '${camp.campaign_id}', 'step_delay': 3}, {'_id': 0, 'id': 1, 'message_body': 1, 'customer_id': 1})
print(json.dumps(m))`));
    rec('Tin đã điền — không còn chỗ trống {…}', first && !/\{\w+\}/.test(first.message_body), first ? first.message_body.slice(0, 90) : '');
    // khách có số điện thoại để test gửi
    py(`
from mongo_client import db
db.customers.update_one({'business_id': ${B}, 'id': ${first.customer_id}}, {'$set': {'qa_old_phone': db.customers.find_one({'business_id': ${B}, 'id': ${first.customer_id}}, {'phone': 1, '_id': 0}).get('phone'), 'phone': '0400 555 777'}})
print('ok')`);
    const ap = await p.evaluate(async (id) => (await fetch('/api/ai/nurture/approve-message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: id, action: 'APPROVED' }) })).json(), first.id);
    rec('Duyệt — báo đúng ngày + khung giờ + kênh sẽ gửi', ap.success && /Approved\. It will be sent on .+ between 9:00–20:00 .+ by sms/.test(ap.message), ap.message);
    // tua thời gian +4 ngày (đã quá 3 ngày) rồi chạy bộ gửi
    const st = JSON.parse(py(`
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import messaging
now = datetime.now(timezone.utc) + timedelta(days=4)
loc = now.astimezone(ZoneInfo('${tz}'))
now = now.replace(hour=(now.hour + (13 - loc.hour)) % 24) if not (9 <= loc.hour < 20) else now
print(json.dumps(messaging.pump(${B}, now_utc=now)))`));
    await sleep(400);
    const nm = sent.find((m) => m.To === '+61400555777');
    rec('Tới ngày — tin chăm sóc gửi SMS cho khách + "Reply STOP"', !!nm && /Reply STOP/.test(nm.Body) && nm.Body.startsWith(first.message_body.slice(0, 20)), nm ? nm.Body.slice(0, 100) : JSON.stringify(st));
    py(`
from mongo_client import db
c = db.customers.find_one({'business_id': ${B}, 'id': ${first.customer_id}}, {'qa_old_phone': 1, '_id': 0})
db.customers.update_one({'business_id': ${B}, 'id': ${first.customer_id}}, {'$set': {'phone': c.get('qa_old_phone')}, '$unset': {'qa_old_phone': ''}})
db.campaign_messages.delete_many({'campaign_id': '${camp.campaign_id}'}); db.nurturing_campaigns.delete_many({'id': '${camp.campaign_id}'})
print('ok')`);
  }
}

// 9) Đề xuất AI = số liệu thật (không còn "Có 12 khách VIP..." viết sẵn)
{
  const r = await p.evaluate(async () => (await fetch('/api/ai/nurture/recommendations')).json());
  const txt = (r.data || []).map((x) => x.text).join(' | ');
  rec('Đề xuất AI — từ số liệu thật của tiệm, tiếng Anh', r.success && r.data.length > 0 && !/Có 12 khách|25 lịch hẹn trống/.test(txt) && !/[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(txt), txt.slice(0, 160));
}

// 10) Báo cáo ngày cho chủ tiệm (số thật hôm qua, theo giờ tiệm)
{
  const rep = JSON.parse(py(`
import json, os
os.environ['MESSAGING_DEMO_REPORTS'] = '1'
from datetime import datetime, timezone
import messaging
from mongo_client import db
s = messaging.get_settings(${B})
n = messaging.produce_owner_report(${B}, s, datetime.now(timezone.utc).replace(hour=23))
m = db.outbound_messages.find_one({'business_id': ${B}, 'kind': 'owner_report'}, {'_id': 0, 'body': 1, 'subject': 1}, sort=[('id', -1)])
print(json.dumps(m or {}))`));
  rec('Báo cáo ngày — doanh thu A$, tiền mặt, khách mới, lịch hôm nay', /Sales: A\$[\d,]+\.\d\d from \d+ bills/.test(rep.body || '') && /Cash to have in the drawer/.test(rep.body || ''), (rep.body || '').split('\n').slice(0, 3).join(' | '));
}

// 11) Link huỷ đăng ký email: đúng -> từ chối; sai -> 400
{
  const tok = py(`
import messaging
print(messaging.unsubscribe_token(${B}, 'qa.client@example.com'))`);
  const ok = await fetch(`${BASE}/unsubscribe?b=${encodeURIComponent(bid)}&e=qa.client%40example.com&t=${tok}`);
  const bad = await fetch(`${BASE}/unsubscribe?b=${encodeURIComponent(bid)}&e=qa.client%40example.com&t=wrong`);
  const n = py(`
from mongo_client import db
print(db.message_optouts.count_documents({'business_id': ${B}, 'channel': 'email', 'address': 'qa.client@example.com'}))`);
  rec('Huỷ đăng ký email — link đúng thì ngừng gửi, link sai bị từ chối', ok.status === 200 && bad.status === 400 && n === '1');
}

// 12) Cron không có khoá -> 401; trang nhật ký hiện tin đã gửi
{
  const c = await fetch(`${BASE}/api/cron/messages`);
  rec('Cron gửi tin — không có CRON_SECRET bị chặn', c.status === 401);
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(800);
  const rows = await p.$$eval('#logBody tr', (r) => r.map((x) => x.innerText).join('\n'));
  rec('Nhật ký — hiện nhắc lịch / đánh giá / cuộc gọi nhỡ, số điện thoại được che', /Reminder/.test(rows) && /Review request/.test(rows) && /Missed call/.test(rows) && /•/.test(rows) && !/0400 123 456|\+61400123456/.test(rows), rows.split('\n').slice(0, 2).join(' / '));
}
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// dọn dữ liệu test
py(`
import json
from mongo_client import db
bid = ${B}
db.appointments.delete_many({'business_id': bid, 'qa_messaging': True})
db.orders.delete_many({'business_id': bid, 'qa_messaging': True})
db.outbound_messages.delete_many({'business_id': bid})
db.message_optouts.delete_many({'business_id': bid})
db.inbound_messages.delete_many({'business_id': bid})
db.nurture_channel_tokens.delete_many({'business_id': bid, 'platform': 'twilio'})
old = json.loads('''${backup}''')
db.messaging_settings.delete_many({'business_id': bid})
if old: db.messaging_settings.insert_one(old)
print('cleaned')`);
await b.close(); stub.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
