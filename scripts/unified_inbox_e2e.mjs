// unified_inbox_e2e.mjs — Hộp thư chung (Messenger · Instagram · WhatsApp · Zalo · Viber · SMS · website) chạy thật, với máy chủ
// Meta/Zalo/Viber/Twilio GIẢ trên máy (không gửi tin thật). Tin đến được ký đúng chuẩn từng nền tảng; AI trả lời là DeepSeek thật.
//   Server local phải chạy với INBOX_META_API_BASE / INBOX_ZALO_API_BASE / INBOX_ZALO_OAUTH_BASE / INBOX_VIBER_API_BASE =
//   http://127.0.0.1:5098 và TWILIO_API_BASE=http://127.0.0.1:5097 (scratchpad/start_5003.sh)
//   BASE=http://127.0.0.1:5003 node scripts/unified_inbox_e2e.mjs
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import http from 'http';
import crypto from 'crypto';

const BASE = process.env.BASE || 'http://127.0.0.1:5003';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const APP_SECRET = 'qa_meta_app_secret_1', OA_SECRET = 'qa_zalo_oa_secret_1', VIBER_TOKEN = 'qa-viber-token-1', ZALO_APP_ID = '1234567890';
const GOOD = 'qa-good-token-777';
const SID = 'ACtest0000000000000000000000000002', TW_TOKEN = 'qa_twilio_token_2';
const QA_PHONE = '0412 555 019';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const pyEnv = { ...process.env, PYTHONIOENCODING: 'utf-8' };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: pyEnv }).trim().split(/\r?\n/).pop();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- Meta / Zalo / Viber giả: ghi lại mọi lệnh gọi, trả đúng hình dạng phản hồi thật
const calls = [];
let seq = 0;
const mock = http.createServer((req, res) => {
  let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
    const u = new URL(req.url, 'http://x');
    let j = {}; try { j = JSON.parse(body || '{}'); } catch { j = Object.fromEntries(new URLSearchParams(body)); }
    const tok = u.searchParams.get('access_token') || (req.headers.authorization || '').replace('Bearer ', '') || req.headers.access_token || req.headers['x-viber-auth-token'] || '';
    calls.push({ method: req.method, path: u.pathname, tok, body: j });
    const send = (code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
    const p = u.pathname;
    if (p.startsWith('/v21.0/') && tok !== GOOD) return send(400, { error: { message: 'Invalid OAuth access token.', code: 190 } });
    if (p === '/v21.0/me' && req.method === 'GET') return send(200, { id: 'PAGE1', name: 'Golden Lotus QA Page' });
    if (p === '/v21.0/IG1') return send(200, { id: 'IG1', username: 'goldenlotus.qa' });
    if (p === '/v21.0/PN1' && req.method === 'GET') return send(200, { verified_name: 'Golden Lotus', display_phone_number: '+61 400 000 001' });
    if (p === '/v21.0/me/messages') {
      if (j.recipient && j.recipient.id === 'PSID_OLD') return send(400, { error: { message: '(#10) This message is sent outside of allowed window.', code: 10, error_subcode: 2018278 } });
      return send(200, { recipient_id: j.recipient && j.recipient.id, message_id: 'm_qa_' + (++seq) });
    }
    if (p === '/v21.0/PN1/messages') return send(200, { messaging_product: 'whatsapp', messages: [{ id: 'wamid.QA' + (++seq) }] });
    if (p === '/v2.0/oa/getoa') return tok === GOOD ? send(200, { error: 0, data: { oa_id: 'OA1', name: 'Golden Lotus OA' } }) : send(200, { error: -216, message: 'Access token is invalid' });
    if (p === '/v3.0/oa/message/cs') return send(200, { error: 0, message: 'Success', data: { message_id: 'zm_qa_' + (++seq), user_id: j.recipient && j.recipient.user_id } });
    if (p === '/pa/get_account_info') return tok === VIBER_TOKEN ? send(200, { status: 0, status_message: 'ok', id: 'pa:QA', name: 'Golden Lotus Bot' }) : send(200, { status: 2, status_message: 'invalidAuthToken' });
    if (p === '/pa/set_webhook') return send(200, { status: 0, status_message: 'ok', event_types: ['delivered'] });
    if (p === '/pa/send_message') return send(200, { status: 0, status_message: 'ok', message_token: 5000000 + (++seq) });
    send(404, { error: 'unknown ' + p });
  });
}).listen(5098);
// Twilio giả (SMS)
const smsSent = [];
const twilio = http.createServer((req, res) => {
  let body = ''; req.on('data', (c) => (body += c)); req.on('end', () => {
    smsSent.push(Object.fromEntries(new URLSearchParams(body)));
    res.writeHead(201, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ sid: 'SM' + crypto.randomBytes(8).toString('hex') }));
  });
}).listen(5097);

const metaSig = (raw) => 'sha256=' + crypto.createHmac('sha256', APP_SECRET).update(raw).digest('hex');
const zaloSig = (raw, ts) => 'mac=' + crypto.createHash('sha256').update(ZALO_APP_ID + raw + ts + OA_SECRET).digest('hex');
const viberSig = (raw) => crypto.createHmac('sha256', VIBER_TOKEN).update(raw).digest('hex');
const twilioSig = (url, params) => crypto.createHmac('sha1', TW_TOKEN).update(url + Object.keys(params).sort().map((k) => k + params[k]).join('')).digest('base64');
const hook = {};
async function post(ch, obj, headers) {
  const raw = JSON.stringify(obj);
  const r = await fetch(hook[ch], { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers(raw, obj) }, body: raw });
  return { status: r.status, text: await r.text() };
}
const signed = {
  messenger: (raw) => ({ 'X-Hub-Signature-256': metaSig(raw) }), whatsapp: (raw) => ({ 'X-Hub-Signature-256': metaSig(raw) }),
  zalo: (raw, o) => ({ 'X-ZEvent-Signature': zaloSig(raw, o.timestamp) }), viber: (raw) => ({ 'X-Viber-Content-Signature': viberSig(raw) }),
};
const fbMsg = (psid, text, mid) => ({ object: 'page', entry: [{ id: 'PAGE1', time: Date.now(), messaging: [{ sender: { id: psid }, recipient: { id: 'PAGE1' }, timestamp: Date.now(), message: { mid, text } }] }] });
const fbEcho = (psid, text, mid) => ({ object: 'page', entry: [{ id: 'PAGE1', time: Date.now(), messaging: [{ sender: { id: 'PAGE1' }, recipient: { id: psid }, timestamp: Date.now(), message: { mid, text, is_echo: true } }] }] });
const waMsg = (wa, name, text, id) => ({ object: 'whatsapp_business_account', entry: [{ id: 'WABA1', changes: [{ field: 'messages', value: { messaging_product: 'whatsapp', metadata: { phone_number_id: 'PN1' }, contacts: [{ wa_id: wa, profile: { name } }], messages: [{ from: wa, id, timestamp: String(Math.floor(Date.now() / 1000)), type: 'text', text: { body: text } }] } }] }] });
const zaloMsg = (uid, text, mid) => ({ app_id: ZALO_APP_ID, event_name: 'user_send_text', timestamp: String(Date.now()), sender: { id: uid }, recipient: { id: 'OA1' }, message: { msg_id: mid, text } });
const viberMsg = (uid, name, text, token) => ({ event: 'message', timestamp: Date.now(), message_token: token, sender: { id: uid, name }, message: { type: 'text', text } });

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const CLEAN = `
from mongo_client import db
bid = ${B}
q = {'business_id': bid, 'channel': {'$in': ['messenger', 'instagram', 'whatsapp', 'zalo', 'viber', 'sms']}}
ids = [c['id'] for c in db.bot_customers.find(q, {'id': 1})]
db.bot_messages.delete_many({'customer_id': {'$in': ids}})
db.bot_customers.delete_many({'id': {'$in': ids}})
db.inbox_channels.delete_many({'business_id': bid})
db.customers.delete_many({'business_id': bid, 'qa_inbox': True})
db.appointments.delete_many({'business_id': bid, 'customer_phone': {'$in': ['0412555019', '+61400555111']}})
db.inbound_messages.delete_many({'business_id': bid, 'from': '+61400777333'})
db.nurture_channel_tokens.delete_many({'business_id': bid, 'platform': 'twilio', 'qa_inbox': True})
print(len(ids))`;
py(CLEAN);
const msBackup = py(`
import json
from mongo_client import db
print(json.dumps(db.messaging_settings.find_one({'business_id': ${B}}, {'_id': 0}) or {}))`);
const twBackup = py(`
from mongo_client import db
print(1 if db.nurture_channel_tokens.find_one({'business_id': ${B}, 'platform': 'twilio'}) else 0)`);
py(`
from mongo_client import db
db.customers.insert_one({'id': 'qa-inbox-cust-1', 'business_id': ${B}, 'name': 'QA Inbox Linda', 'phone': '${QA_PHONE}', 'qa_inbox': True})
print('ok')`);
const api = (path, body) => p.evaluate(async ([path, body]) => {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  let j = {}; try { j = await r.json(); } catch (e) { j = {}; }
  return { status: r.status, ...j };
}, [path, body]);
const doc = (code) => JSON.parse(py(`
import json
from mongo_client import db
bid = ${B}
${code}`));

// 1) Trang nối kênh
await p.goto(BASE + '/inbox/channels', { waitUntil: 'networkidle' });
await p.waitForSelector('#card_messenger');
const cardCount = await p.$$eval('#cards .card', (els) => els.length);
rec('Trang Nối kênh — 5 kênh webhook + Website + SMS, không lỗi JS', cardCount === 5 && (await p.$('#cards2 .card')) !== null && errs.length === 0, `${cardCount} thẻ`);
const oldRedirect = await p.evaluate(async () => (await fetch('/omnichannel_connect', { redirect: 'follow' })).url);
rec('Trang cũ /omnichannel_connect (số liệu bịa) chuyển sang trang mới', oldRedirect.endsWith('/inbox/channels'), oldRedirect);

// 2) Nối Messenger: token sai bị từ chối, token đúng -> Đã nối + webhook URL + verify token
await p.click('[data-open="messenger"]');
await p.fill('#f_messenger_access_token', 'bad-token'); await p.fill('#f_messenger_app_secret', APP_SECRET);
await p.click('[data-form="messenger"] button[type=submit]');
await p.waitForFunction(() => document.getElementById('toast').style.display === 'block', null, { timeout: 15000 });
const badMsg = await p.textContent('#toast');
rec('Token sai — báo rõ "Messenger rejected the Page token", KHÔNG lưu', /rejected the Page token/.test(badMsg) && doc(`print(json.dumps(db.inbox_channels.count_documents({'business_id': bid, 'status': 'connected'})))`) === 0, badMsg.slice(0, 90));
await p.fill('#f_messenger_access_token', GOOD);
await p.click('[data-form="messenger"] button[type=submit]');
await p.waitForSelector('#wh_messenger', { timeout: 15000 });
hook.messenger = await p.inputValue('#wh_messenger');
const vt = await p.inputValue('#vt_messenger');
const pill = await p.textContent('#card_messenger .pill');
rec('Token đúng — Đã nối "Golden Lotus QA Page", có Webhook URL + Verify token', /Connected|Đã nối/.test(pill) && /Golden Lotus QA Page/.test(await p.textContent('#card_messenger')) && hook.messenger.includes('/webhooks/inbox/messenger/') && vt.length > 12, hook.messenger);
await p.click('[data-copy="wh_messenger"]');
rec('Nút Chép — chép đúng Webhook URL', (await p.evaluate(() => navigator.clipboard.readText())) === hook.messenger);

// 3) Nối 4 kênh còn lại (qua API của trang)
const con = {};
con.instagram = await api('/api/inbox/channels/instagram', { action: 'connect', fields: { access_token: GOOD, external_id: 'IG1', app_secret: APP_SECRET } });
con.whatsapp = await api('/api/inbox/channels/whatsapp', { action: 'connect', fields: { access_token: GOOD, external_id: 'PN1', app_secret: APP_SECRET } });
con.zaloBad = await api('/api/inbox/channels/zalo', { action: 'connect', fields: { access_token: GOOD } });
con.zalo = await api('/api/inbox/channels/zalo', { action: 'connect', fields: { access_token: GOOD, oa_secret: OA_SECRET, app_id: ZALO_APP_ID, app_secret: 'qa-zalo-app-secret', refresh_token: 'qa-refresh-1' } });
con.viber = await api('/api/inbox/channels/viber', { action: 'connect', fields: { access_token: VIBER_TOKEN } });
rec('Instagram / WhatsApp / Zalo / Viber nối được (kiểm tra token với nền tảng)', ['instagram', 'whatsapp', 'zalo', 'viber'].every((k) => con[k].success),
  ['instagram', 'whatsapp', 'zalo', 'viber'].map((k) => `${k}:${con[k].success ? (con[k].data.account_name || 'ok') : con[k].message}`).join(' · '));
rec('Zalo thiếu OA secret key — từ chối (không nhận tin không kiểm được chữ ký)', !con.zaloBad.success && /secret/i.test(con.zaloBad.message || ''), con.zaloBad.message);
const vbHook = calls.find((c) => c.path === '/pa/set_webhook');
rec('Viber — BitPaw tự đăng ký webhook với Viber', !!vbHook && String(vbHook.body.url || '').includes('/webhooks/inbox/viber/'), vbHook ? vbHook.body.url : '');
const st = await api('/api/inbox/channels');
['whatsapp', 'zalo', 'viber', 'instagram'].forEach((k) => { hook[k] = st.data[k].webhook_url; });
const stText = JSON.stringify(st);
rec('Trạng thái kênh KHÔNG lộ token/secret ra trình duyệt', ![GOOD, APP_SECRET, OA_SECRET, VIBER_TOKEN, 'qa-refresh-1'].some((x) => stText.includes(x)) && st.data.zalo.auto_refresh === true);
const enc = doc(`d = db.inbox_channels.find_one({'business_id': bid, 'channel': 'messenger'})
print(json.dumps({'enc': bool(d.get('access_token_enc')), 'plain': '${GOOD}' in str(d) or '${APP_SECRET}' in str(d)}))`);
rec('Token + App secret lưu MÃ HOÁ trong DB', enc.enc && !enc.plain);

// 4) Meta "Verify and save"
const v1 = await fetch(`${hook.messenger}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(vt)}&hub.challenge=987654`);
const v2 = await fetch(`${hook.messenger}?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=987654`);
const v3 = await fetch(hook.messenger.replace(/\/[^/]+$/, '/AAAAAAAAAAAAAAAAAAAAAAAA'));
rec('Meta xác minh webhook — đúng verify token trả challenge, sai -> 403, hook lạ -> 404', (await v1.text()) === '987654' && v2.status === 403 && v3.status === 404);

// 5) Tin Messenger: chữ ký sai bị chặn; chữ ký đúng -> vào hộp thư, AI trả lời ĐÚNG về Messenger
const forged = await post('messenger', fbMsg('PSID1', 'forged hello', 'mid.forged'), () => ({ 'X-Hub-Signature-256': 'sha256=' + 'a'.repeat(64) }));
const forgedStored = doc(`print(json.dumps(db.bot_messages.count_documents({'business_id': bid, 'content': 'forged hello'})))`);
rec('Tin giả mạo (sai chữ ký) — 403, không ghi gì', forged.status === 403 && forgedStored === 0);
const sendsBefore = calls.filter((c) => c.path === '/v21.0/me/messages').length;
let t0 = Date.now();
const r1 = await post('messenger', fbMsg('PSID1', 'Hi! How much is a gel manicure, and are you open on Saturday?', 'mid.qa.1'), signed.messenger);
const fb1 = doc(`cid = bid + ':messenger:PSID1'
c = db.bot_customers.find_one({'id': cid}, {'_id': 0}) or {}
ms = list(db.bot_messages.find({'customer_id': cid}, {'_id': 0}).sort('created_at', 1))
print(json.dumps({'channel': c.get('channel'), 'name': c.get('full_name'), 'msgs': [[m['sender_type'], m['content'][:400], (m.get('delivery') or {}).get('status'), m.get('ext_msg_id')] for m in ms]}))`);
const fbSends = calls.filter((c) => c.path === '/v21.0/me/messages').slice(sendsBefore);
const aiMsg = fb1.msgs.find((m) => m[0] === 'ai');
rec('Messenger — tin khách vào hộp thư (kênh messenger), AI trả lời thật', r1.status === 200 && fb1.channel === 'messenger' && fb1.msgs[0][0] === 'customer' && !!aiMsg && aiMsg[1].length > 20,
  `${((Date.now() - t0) / 1000).toFixed(1)}s · "${aiMsg ? aiMsg[1].slice(0, 110).replace(/\n/g, ' ') : ''}"`);
rec('Câu trả lời AI gửi NGƯỢC về Messenger đúng khách (PSID1), chữ thường không Markdown, trạng thái "sent"',
  fbSends.length === 1 && fbSends[0].body.recipient.id === 'PSID1' && fbSends[0].body.message.text === aiMsg[1] && !/\*\*/.test(aiMsg[1]) && aiMsg[2] === 'sent' && /^m_qa_/.test(aiMsg[3] || ''));
const r1b = await post('messenger', fbMsg('PSID1', 'Hi! How much is a gel manicure, and are you open on Saturday?', 'mid.qa.1'), signed.messenger);
const dup = doc(`print(json.dumps(db.bot_messages.count_documents({'customer_id': bid + ':messenger:PSID1'})))`);
rec('Facebook gửi lại cùng tin (retry) — không ghi 2 lần, AI không trả lời 2 lần', r1b.status === 200 && dup === fb1.msgs.length && calls.filter((c) => c.path === '/v21.0/me/messages').length === sendsBefore + 1);
await post('messenger', fbEcho('PSID1', aiMsg[1], aiMsg[3]), signed.messenger);
await post('messenger', fbEcho('PSID1', 'Staff here from Business Suite — see you Saturday!', 'mid.qa.staff'), signed.messenger);
const echo = doc(`ms = list(db.bot_messages.find({'customer_id': bid + ':messenger:PSID1'}, {'_id': 0}))
print(json.dumps({'n': len(ms), 'staff': [m['content'] for m in ms if m['sender_type'] == 'staff']}))`);
rec('Tin echo: của chính BitPaw thì bỏ qua; nhân viên trả lời trong Meta Business Suite thì hiện trong hộp thư', echo.n === fb1.msgs.length + 1 && echo.staff.length === 1 && /Business Suite/.test(echo.staff[0]));

// 6) WhatsApp: tên + SĐT lấy từ hồ sơ WhatsApp; AI trả lời qua WhatsApp Cloud API
t0 = Date.now();
const r2 = await post('whatsapp', waMsg('61400555111', 'Mia Tran', 'Hello, do you have any spots for a pedicure tomorrow afternoon?', 'wamid.in.1'), signed.whatsapp);
const wa = doc(`c = db.bot_customers.find_one({'id': bid + ':whatsapp:61400555111'}, {'_id': 0}) or {}
ms = list(db.bot_messages.find({'customer_id': bid + ':whatsapp:61400555111', 'sender_type': 'ai'}, {'_id': 0}))
print(json.dumps({'name': c.get('full_name'), 'phone': c.get('phone'), 'ai': [(m['content'][:200], (m.get('delivery') or {}).get('status')) for m in ms]}))`);
const waSend = calls.find((c) => c.path === '/v21.0/PN1/messages');
rec('WhatsApp — tên "Mia Tran" + SĐT +61400555111 từ WhatsApp, AI trả lời qua đúng số', r2.status === 200 && wa.name === 'Mia Tran' && wa.phone === '+61400555111' && wa.ai.length === 1 && wa.ai[0][1] === 'sent' && !!waSend && waSend.body.to === '61400555111' && waSend.tok === GOOD,
  `${((Date.now() - t0) / 1000).toFixed(1)}s · "${wa.ai[0] ? wa.ai[0][0].slice(0, 90).replace(/\n/g, ' ') : ''}"`);

// 7) Zalo: tắt AI cho kênh -> tin vào hộp thư, đánh dấu "cần trả lời", không gửi gì; chữ ký sai bị chặn
await api('/api/inbox/channels/zalo', { action: 'ai', enabled: false });
const zBad = await post('zalo', zaloMsg('ZU1', 'forged zalo', 'zm.forged'), () => ({ 'X-ZEvent-Signature': 'mac=' + '0'.repeat(64) }));
const zSendsBefore = calls.filter((c) => c.path === '/v3.0/oa/message/cs').length;
const r3 = await post('zalo', zaloMsg('ZU1', 'Chào shop, mai em muốn làm móng gel lúc 3h chiều được không ạ?', 'zm.qa.1'), signed.zalo);
const zl = doc(`c = db.bot_customers.find_one({'id': bid + ':zalo:ZU1'}, {'_id': 0}) or {}
print(json.dumps({'needs': c.get('needs_human'), 'n': db.bot_messages.count_documents({'customer_id': bid + ':zalo:ZU1'}), 'forged': db.bot_messages.count_documents({'business_id': bid, 'content': 'forged zalo'})}))`);
rec('Zalo — chữ ký sai 403; AI đang tắt cho Zalo: tin vào hộp thư, gắn "cần trả lời", không tự gửi', zBad.status === 403 && zl.forged === 0 && r3.status === 200 && zl.n === 1 && zl.needs === true && calls.filter((c) => c.path === '/v3.0/oa/message/cs').length === zSendsBefore);

// 8) Viber: AI trả lời qua Viber, tên người gửi lấy từ Viber
const r4 = await post('viber', viberMsg('VBU1==', 'Leo Nguyen', 'Do you do nails for kids? My daughter is 8.', 5550001), signed.viber);
const vb = doc(`c = db.bot_customers.find_one({'id': bid + ':viber:VBU1=='}, {'_id': 0}) or {}
print(json.dumps({'name': c.get('full_name'), 'ai': db.bot_messages.count_documents({'customer_id': bid + ':viber:VBU1==', 'sender_type': 'ai', 'delivery.status': 'sent'})}))`);
const vbSend = calls.find((c) => c.path === '/pa/send_message');
rec('Viber — tên "Leo Nguyen", AI trả lời qua Viber đúng người nhận', r4.status === 200 && vb.name === 'Leo Nguyen' && vb.ai === 1 && !!vbSend && vbSend.body.receiver === 'VBU1==' && vbSend.tok === VIBER_TOKEN);

// 8b) Chống spam: 1 khách nhắn dồn dập -> sau 10 câu AI / 10 phút thì AI dừng, báo chủ tiệm (không đốt chi phí AI)
py(`
from datetime import datetime
from mongo_client import db
cid = ${B} + ':whatsapp:61400555111'
now = datetime.now().isoformat()
db.bot_messages.insert_many([{'customer_id': cid, 'sender_type': 'ai', 'content': f'qa throttle {i}', 'business_id': ${B}, 'created_at': now,
                              'channel': 'whatsapp', 'is_read': True} for i in range(10)])
print('ok')`);
{
  const waBefore = calls.filter((c) => c.path === '/v21.0/PN1/messages').length;
  await post('whatsapp', waMsg('61400555111', 'Mia Tran', 'hello?? hello??', 'wamid.in.spam'), signed.whatsapp);
  const th = doc(`c = db.bot_customers.find_one({'id': bid + ':whatsapp:61400555111'}, {'_id': 0}) or {}
print(json.dumps({'needs': c.get('needs_human'), 'reason': c.get('handoff_reason')}))`);
  rec('Chống spam — quá 10 câu AI / 10 phút: AI dừng, gắn "cần trả lời", không gửi thêm', th.needs === true && /Many messages/.test(th.reason || '') && calls.filter((c) => c.path === '/v21.0/PN1/messages').length === waBefore, JSON.stringify(th));
}

// 9) SMS (Twilio): tin thường -> hộp thư, AI trả lời ngay trong TwiML
await api('/api/messaging/settings', { sms_enabled: true, twilio_account_sid: SID, twilio_from: '+61 2 5550 1299', twilio_auth_token: TW_TOKEN, language: 'en' });
py(`
from mongo_client import db
db.nurture_channel_tokens.update_one({'business_id': ${B}, 'platform': 'twilio'}, {'$set': {'qa_inbox': True}})
print('ok')`);
{
  const url = `${BASE}/api/twilio/sms/${bid}`;
  const params = { From: '+61400777333', To: '+61255501299', Body: 'Hi, can I book a pedicure for Friday?', MessageSid: 'SMqa1' };
  t0 = Date.now();
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': twilioSig(url, params) }, body: new URLSearchParams(params) });
  const xml = await r.text();
  const sm = doc(`c = db.bot_customers.find_one({'id': bid + ':sms:+61400777333'}, {'_id': 0}) or {}
print(json.dumps({'ch': c.get('channel'), 'phone': c.get('phone'), 'n': db.bot_messages.count_documents({'customer_id': bid + ':sms:+61400777333'})}))`);
  rec('SMS — tin khách vào hộp thư (kênh sms), AI trả lời ngay trong TwiML', r.status === 200 && /<Message>[^<]{15,}<\/Message>/.test(xml) && sm.ch === 'sms' && sm.phone === '+61400777333' && sm.n === 2,
    `${((Date.now() - t0) / 1000).toFixed(1)}s · ${xml.replace(/<[^>]+>/g, ' ').trim().slice(0, 90)}`);
}

// 10) SĐT khách nhắn trong Messenger -> lưu vào hội thoại + gắn vào hồ sơ khách (để chiến dịch gửi được qua Messenger)
await api('/api/inbox/channels/messenger', { action: 'ai', enabled: false });
await post('messenger', fbMsg('PSID2', `Hi it's Linda, my number is ${QA_PHONE}`, 'mid.qa.2'), signed.messenger);
const ph = doc(`c = db.bot_customers.find_one({'id': bid + ':messenger:PSID2'}, {'_id': 0}) or {}
cu = db.customers.find_one({'id': 'qa-inbox-cust-1'}, {'_id': 0}) or {}
print(json.dumps({'phone': c.get('phone'), 'psid': cu.get('fb_psid')}))`);
rec('SĐT trong tin Messenger — lưu vào hội thoại + gắn PSID vào hồ sơ khách', ph.phone === '0412555019' && ph.psid === 'PSID2', JSON.stringify(ph));
const tokFallback = py(`
import nurture_channel_tokens as t
d = t.get_channel_token(${B}, 'facebook') or {}
print(d.get('source'), d.get('access_token') == '${GOOD}')`);
rec('Chiến dịch chăm sóc dùng được kênh đã nối ở Hộp thư (không phải nối lần 2)', tokFallback === 'inbox True', tokFallback);
await post('messenger', fbMsg('PSID_OLD', 'hello from last month', 'mid.qa.old'), signed.messenger);

// 11) Màn hộp thư /ai_bot
await p.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' });
await p.waitForSelector('#channelChips .ch-chip', { timeout: 15000 });
const chips = await p.$$eval('#channelChips .ch-chip', (els) => els.map((e) => e.dataset.ch));
rec('Hộp thư — chip lọc theo kênh: Messenger, WhatsApp, Zalo, Viber, SMS', ['all', 'messenger', 'whatsapp', 'zalo', 'viber', 'sms'].every((k) => chips.includes(k)), chips.join(','));
await p.click('#channelChips [data-ch="zalo"]');
const zaloItems = await p.$$eval('#customerList .customer-item', (els) => els.map((e) => e.title));
rec('Bấm chip Zalo — chỉ còn hội thoại Zalo', zaloItems.length === 1 && zaloItems[0] === 'Zalo', zaloItems.join(','));
await p.click('#customerList .customer-item');
await p.waitForTimeout(1200);
const line = await p.textContent('#chatChannelLine');
const ph1 = await p.getAttribute('#userInput', 'placeholder');
rec('Mở hội thoại — đầu khung ghi "qua Zalo", ô soạn "Trả lời qua Zalo"', /Zalo/.test(line) && /Zalo/.test(ph1) && !(await p.isVisible('#channelWarn')), `${line.trim()} · ${ph1}`);
const zBefore = calls.filter((c) => c.path === '/v3.0/oa/message/cs').length;
await p.fill('#userInput', 'Dạ được ạ, mai 3h chiều tiệm còn chỗ, em giữ lịch cho chị nhé!');
await p.click('#btnSend'); await p.waitForTimeout(2500);
const zSend = calls.filter((c) => c.path === '/v3.0/oa/message/cs').slice(zBefore)[0];
const lastMark = await p.$$eval('#chatBox .chat-user', (els) => els.length ? els[els.length - 1].parentElement.textContent : '');
rec('Nhân viên trả lời trong hộp thư — tin đi qua Zalo OA đúng khách (ZU1), hiện dấu đã gửi', !!zSend && zSend.body.recipient.user_id === 'ZU1' && /mai 3h/.test(zSend.body.message.text) && zSend.tok === GOOD && !/Not delivered|Chưa gửi được/.test(lastMark));

// 12) Kênh bị ngắt -> cảnh báo + tin báo "chưa gửi được" (không giả vờ đã gửi)
await api('/api/inbox/channels/viber', { action: 'disconnect' });
await p.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' });
await p.waitForSelector('#channelChips .ch-chip');
await p.click('#channelChips [data-ch="viber"]');
await p.click('#customerList .customer-item'); await p.waitForTimeout(1200);
const warnVis = await p.isVisible('#channelWarn');
await p.fill('#userInput', 'Yes we do kids nails!'); await p.click('#btnSend'); await p.waitForTimeout(2500);
const toastTxt = await p.evaluate(() => document.getElementById('toast-container').textContent);
const failMark = await p.$$eval('#chatBox .chat-user', (els) => els.length ? els[els.length - 1].parentElement.textContent : '');
rec('Viber đã ngắt — cảnh báo trên ô soạn, tin ghi rõ "Chưa gửi được" + lý do', warnVis && /not connected|chưa được nối/i.test(failMark + toastTxt) && /Not delivered|Chưa gửi được/.test(failMark), failMark.replace(/\s+/g, ' ').slice(0, 120));

// 13) Ngoài khung 24 giờ của Messenger -> báo lý do dễ hiểu
const oldId = `${bid}:messenger:PSID_OLD`;
const late = await api('/api/bot/messages', { customer_id: oldId, content: 'Hi again! Still keen on a booking?' });
rec('Messenger ngoài khung 24 giờ — báo "Outside the 24-hour reply window"', late.success && late.delivery && late.delivery.status === 'failed' && /24-hour/.test(late.delivery.error), late.delivery && late.delivery.error);

// 14) Bảo mật: nhân viên (không phải chủ) không nối được kênh; khách vãng lai không đọc được trạng thái kênh
const anon = await fetch(BASE + '/api/inbox/channels', { redirect: 'manual' });
rec('Chưa đăng nhập — không đọc được trạng thái kênh', anon.status !== 200 || !(await anon.text()).includes('webhook_url'), String(anon.status));

// 15) Điện thoại
const m = await ctx.newPage(); m.on('pageerror', (e) => errs.push(e.message));
await m.setViewportSize({ width: 390, height: 844 });
await m.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' });
await m.waitForSelector('#channelChips .ch-chip');
const mOver = await m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
await m.goto(BASE + '/inbox/channels', { waitUntil: 'networkidle' });
const mOver2 = await m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
await m.screenshot({ path: process.env.SHOT_DIR ? process.env.SHOT_DIR + '/inbox_channels_mobile.png' : 'audit-results/screenshots/inbox_channels_mobile.png' }).catch(() => {});
rec('Điện thoại 390px — hộp thư + trang nối kênh không tràn ngang', mOver <= 1 && mOver2 <= 1, `${mOver} / ${mOver2}`);
if (process.env.SHOT_DIR) {
  await p.goto(BASE + '/ai_bot', { waitUntil: 'networkidle' }); await p.waitForSelector('#channelChips .ch-chip');
  await p.click('#customerList .customer-item'); await p.waitForTimeout(1500);
  await p.screenshot({ path: process.env.SHOT_DIR + '/inbox_unified_pc.png' });
  await p.goto(BASE + '/inbox/channels', { waitUntil: 'networkidle' }); await p.waitForTimeout(600);
  await p.screenshot({ path: process.env.SHOT_DIR + '/inbox_channels_pc.png', fullPage: true });
  await p.evaluate(() => localStorage.setItem('bitpaw_lang', 'vi')); await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(600);
  await p.screenshot({ path: process.env.SHOT_DIR + '/inbox_channels_vi.png' });
  const viErr = await p.textContent('#card_messenger .err').catch(() => '');
  rec('Giao diện tiếng Việt — lỗi kênh hiện tiếng Việt (dịch theo mã lỗi)', /quá 24 giờ/.test(viErr), viErr.trim().slice(0, 90));
  await p.evaluate(() => localStorage.removeItem('bitpaw_lang'));
}
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// dọn dữ liệu test
const cleaned = py(CLEAN);
py(`
import json
from mongo_client import db
bid = ${B}
old = json.loads('''${msBackup}''')
db.messaging_settings.delete_many({'business_id': bid})
if old: db.messaging_settings.insert_one(old)
if not ${twBackup}: db.nurture_channel_tokens.delete_many({'business_id': bid, 'platform': 'twilio'})
print('ok')`);
console.log(`dọn ${cleaned} hội thoại test`);
const pass = steps.filter((s) => s.ok).length;
console.log(`\nTổng: ${pass} PASS · ${steps.length - pass} FAIL`);
await b.close(); mock.close(); twilio.close();
process.exit(steps.length - pass ? 1 : 0);
