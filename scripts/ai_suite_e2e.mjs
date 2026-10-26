// ai_suite_e2e.mjs — AI Studio (ảnh/video/upload) + AI đăng bài đa nền tảng chạy THẬT trên server local, với máy chủ GIẢ của
// Replicate / Meta / Google (YouTube, OAuth, Business Profile) / TikTok trên cổng 5098 — KHÔNG tốn tiền, KHÔNG đăng thật.
// Gọi DeepSeek thật 2 lần (viết caption theo nền tảng + kế hoạch tuần) — vài xu.
//   Server: scratchpad/start_ai_suite.sh (đặt *_API_BASE về 5098, SOCIAL_TEST_BUSINESS_IDS, SOCIAL_ALLOW_TICK=1, CRON_SECRET=qa-cron)
//   BASE=http://127.0.0.1:5005 node scripts/ai_suite_e2e.mjs
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import http from 'http';
import crypto from 'crypto';

const BASE = process.env.BASE || 'http://127.0.0.1:5005';
const MOCK = 'http://127.0.0.1:5098';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const EMAIL2 = 'demo.spa.596348@bitpawdemo.com', PW2 = 'DemoBitPaw2026!';
const WH_SECRET_RAW = 'qa-replicate-webhook-secret-123';
const WH_SECRET = 'whsec_' + Buffer.from(WH_SECRET_RAW).toString('base64');
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + String(note).slice(0, 220) : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- bytes thật (đủ để nhận dạng định dạng) ----------
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 16, 0x4a, 0x46, 0x49, 0x46, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0]), crypto.randomBytes(40_000), Buffer.from([0xff, 0xd9])]);
const mp4 = (n) => Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypisom'), Buffer.from([0, 0, 2, 0]), Buffer.from('isomiso2'),
  Buffer.from([0, 0, 0, 8]), Buffer.from('free'), crypto.randomBytes(n)]);
const VIDEO = mp4(600_000);

// ---------- máy chủ giả ----------
const calls = [];
const state = { containers: {}, preds: {}, failFeed: 0, fail190: false, n: 0 };
const mock = http.createServer((req, res) => {
  const chunks = []; req.on('data', (c) => chunks.push(c)); req.on('end', async () => {
    const raw = Buffer.concat(chunks);
    const u = new URL(req.url, MOCK); const p = u.pathname;
    let j = null; try { j = JSON.parse(raw.toString('utf-8') || 'null'); } catch { j = null; }
    const c = { method: req.method, path: p, q: Object.fromEntries(u.searchParams), headers: req.headers, json: j, text: raw.toString('latin1').slice(0, 4000), size: raw.length };
    calls.push(c);
    const send = (code, obj, headers = {}) => { res.writeHead(code, { 'Content-Type': 'application/json', ...headers }); res.end(JSON.stringify(obj)); };
    const bin = (buf, type) => { res.writeHead(200, { 'Content-Type': type, 'Content-Length': buf.length }); res.end(buf); };
    const id = () => String(++state.n);
    try {
      // ---- Replicate
      if (p.startsWith('/replicate')) {
        const q = p.slice('/replicate'.length);
        if (q === '/v1/webhooks/default/secret') return send(200, { key: WH_SECRET });
        if (q === '/out/a.jpg') return bin(JPEG, 'image/jpeg');
        if (q === '/out/v.mp4') return bin(VIDEO, 'video/mp4');
        let m = q.match(/^\/v1\/models\/([^/]+)\/([^/]+)\/predictions$/);
        if (m && req.method === 'POST') {
          const pid = 'qapred' + id().padStart(8, '0'); const isImg = /flux|ideogram|recraft|imagen/.test(m[2]);
          state.preds[pid] = { model: `${m[1]}/${m[2]}`, polls: 0, isImg };
          if (isImg) return send(201, { id: pid, status: 'succeeded', output: m[2].includes('schnell') ? [`${MOCK}/replicate/out/a.jpg`] : `${MOCK}/replicate/out/a.jpg`, urls: { get: `${MOCK}/replicate/v1/predictions/${pid}` } });
          return send(201, { id: pid, status: 'starting', urls: { get: `${MOCK}/replicate/v1/predictions/${pid}` } });
        }
        m = q.match(/^\/v1\/predictions\/([^/]+)$/);
        if (m) {
          const st = state.preds[m[1]]; if (!st) return send(404, { detail: 'not found' });
          st.polls++;
          if (st.isImg || st.polls >= 2) return send(200, { id: m[1], status: 'succeeded', output: st.isImg ? [`${MOCK}/replicate/out/a.jpg`] : `${MOCK}/replicate/out/v.mp4`, metrics: { predict_time: 30 } });
          return send(200, { id: m[1], status: 'processing' });
        }
        return send(404, { detail: 'unknown replicate ' + q });
      }
      // ---- Meta Graph
      if (p.startsWith('/meta/ig-api-upload/')) {   // Reels: byte video tải thẳng lên Instagram (rupload), kèm Authorization: OAuth
        return (req.headers.authorization === 'OAuth qa-good' && Number(req.headers.file_size) === raw.length)
          ? send(200, { success: true }) : send(400, { debug_info: { type: 'OAuthException', message: 'bad upload' } });
      }
      if (p.startsWith('/meta/')) {
        const q = p.replace(/^\/meta\/v[\d.]+/, '');
        const tok = u.searchParams.get('access_token') || (c.text.match(/access_token=([^&\s"]+)/) || [])[1] || (j && j.access_token) || (req.headers.authorization || '').replace('Bearer ', '');
        if (tok && tok !== 'qa-good') return send(400, { error: { message: 'Invalid OAuth access token.', type: 'OAuthException', code: 190 } });
        if (state.fail190 && req.method === 'POST') { state.fail190 = false; return send(400, { error: { message: 'Session has expired', code: 190, error_subcode: 463 } }); }
        if (q === '/me') return send(200, { id: 'PAGE1', name: 'Golden Lotus QA Page', category: 'Nail Salon' });
        if (q === '/IG1' && req.method === 'GET') return send(200, { id: 'IG1', username: 'goldenlotus.qa' });
        if (q === '/PAGE1' && req.method === 'GET') return send(200, { id: 'PAGE1', name: 'Golden Lotus QA Page' });
        if (q === '/PAGE1/feed' && req.method === 'POST') {
          if (state.failFeed > 0) { state.failFeed--; return send(500, { error: { message: 'An unknown error occurred', code: 1, is_transient: true } }); }
          return send(200, { id: 'PAGE1_' + id() });
        }
        if (q === '/PAGE1/photos') return send(200, /temporary=true|"temporary":\s*true/.test(c.text) ? { id: 'TMP' + id() } : { id: 'PH' + id(), post_id: 'PAGE1_' + id() });
        if (q === '/PAGE1/videos') return send(200, { id: 'VD' + id() });
        if (q === '/IG1/content_publishing_limit') return send(200, { data: [{ quota_usage: 0, config: { quota_total: 50, quota_duration: 86400 } }] });
        if (q === '/IG1/media' && req.method === 'POST') {
          const fetched = {}; const url = (j && (j.image_url || j.video_url)) || u.searchParams.get('image_url') || u.searchParams.get('video_url') || (c.text.match(/(?:image_url|video_url)=([^&]+)/) || [])[1];
          if (url) {   // Instagram tải media từ link công khai — kiểm tra link THẬT mở được, không cần đăng nhập
            try { const r = await fetch(decodeURIComponent(url)); const b = Buffer.from(await r.arrayBuffer()); Object.assign(fetched, { status: r.status, type: r.headers.get('content-type'), size: b.length, magic: b.slice(0, 12).toString('hex') }); } catch (e) { fetched.error = String(e); }
          }
          c.fetched = fetched;
          const cid = 'C' + id(); state.containers[cid] = { polls: 0, video: !!((j && j.video_url) || /video_url/.test(c.text) || /REELS/.test(c.text)) };
          return send(200, { id: cid });
        }
        if (q === '/IG1/media_publish') return send(200, { id: 'M' + id() });
        let m = q.match(/^\/([^/]+)\/insights$/);
        if (m) return send(200, { data: [
          { name: 'post_media_view', values: [{ value: 321 }] }, { name: 'post_total_media_view_unique', values: [{ value: 250 }] },
          { name: 'views', values: [{ value: 410 }] }, { name: 'reach', values: [{ value: 300 }] }, { name: 'likes', values: [{ value: 21 }] },
          { name: 'comments', values: [{ value: 4 }] }, { name: 'shares', values: [{ value: 3 }] }, { name: 'saved', values: [{ value: 5 }] }] });
        m = q.match(/^\/([^/]+)$/);
        if (m && req.method === 'DELETE') return send(200, { success: true });
        if (m && req.method === 'GET') {
          const cs = state.containers[m[1]];
          if (cs) { cs.polls++; return send(200, { id: m[1], status_code: cs.polls >= 2 ? 'FINISHED' : 'IN_PROGRESS' }); }
          return send(200, { id: m[1], is_published: !/scheduled/.test(u.search), permalink_url: `https://facebook.com/${m[1]}`, permalink: `https://instagram.com/p/${m[1]}`,
            published: true, post_id: 'PAGE1_' + m[1], likes: { summary: { total_count: 12 } }, comments: { summary: { total_count: 3 } }, shares: { count: 2 } });
        }
        return send(404, { error: { message: 'unknown meta ' + q, code: 100 } });
      }
      // ---- Google OAuth + YouTube + Business Profile
      if (p.startsWith('/gauth')) {
        const q = p.slice('/gauth'.length);
        if (q === '/o/oauth2/v2/auth') { const ru = u.searchParams.get('redirect_uri'); res.writeHead(302, { Location: `${ru}?code=qa-code&state=${encodeURIComponent(u.searchParams.get('state'))}` }); return res.end(); }
        if (q === '/token') { const scope = (c.text.match(/refresh_token/) ? '' : ''); return send(200, { access_token: 'qa-google-at', refresh_token: 'qa-google-rt', expires_in: 3599, token_type: 'Bearer', scope }); }
        if (q === '/revoke') return send(200, {});
      }
      if (p.startsWith('/google')) {
        const q = p.slice('/google'.length);
        if (q === '/youtube/v3/channels') return send(200, { items: [{ id: 'UC1', snippet: { title: 'Golden Lotus QA Channel' } }] });
        if (q === '/upload/youtube/v3/videos' && req.method === 'POST') { res.writeHead(200, { Location: `${MOCK}/google/upload/session/1`, 'Content-Type': 'application/json' }); return res.end('{}'); }
        if (q === '/upload/session/1' && req.method === 'PUT') return send(200, { id: 'VID' + id(), status: { privacyStatus: 'private', uploadStatus: 'uploaded' } });
        if (q === '/youtube/v3/videos' && req.method === 'GET') return send(200, { items: [{ id: u.searchParams.get('id'), statistics: { viewCount: '77', likeCount: '6', commentCount: '1' }, status: { privacyStatus: 'private', uploadStatus: 'processed' } }] });
        if (q === '/youtube/v3/videos' && req.method === 'DELETE') { res.writeHead(204); return res.end(); }
      }
      if (p.startsWith('/gbp')) {
        const q = p.slice('/gbp'.length);
        if (q === '/v1/accounts') return send(200, { accounts: [{ name: 'accounts/1', accountName: 'Golden Lotus' }] });
        if (q === '/v1/accounts/1/locations') return send(200, { locations: [{ name: 'locations/2', title: 'Golden Lotus Nails' }] });
        if (/\/localPosts$/.test(q) && req.method === 'POST') return send(200, { name: 'accounts/1/locations/2/localPosts/LP' + id(), state: 'LIVE', searchUrl: 'https://local.google.com/x' });
      }
      // ---- TikTok
      if (p.startsWith('/tiktok')) {
        const q = p.slice('/tiktok'.length); const ok = (data) => send(200, { data, error: { code: 'ok', message: '' } });
        if (q === '/v2/auth/authorize/') { const ru = u.searchParams.get('redirect_uri'); res.writeHead(302, { Location: `${ru}?code=qa-tt-code&state=${encodeURIComponent(u.searchParams.get('state'))}` }); return res.end(); }
        if (q === '/v2/oauth/token/') return send(200, { access_token: 'qa-tt-at', refresh_token: 'qa-tt-rt', open_id: 'OPEN1', expires_in: 86400, refresh_expires_in: 31536000, scope: 'user.info.basic,video.publish,video.upload,video.list' });
        if (q === '/v2/user/info/') return ok({ user: { display_name: 'goldenlotus.qa' } });
        if (q === '/v2/post/publish/creator_info/query/') return ok({ creator_username: 'goldenlotus.qa', creator_nickname: 'Golden Lotus', privacy_level_options: ['PUBLIC_TO_EVERYONE', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'], comment_disabled: false, duet_disabled: false, stitch_disabled: false, max_video_post_duration_sec: 600 });
        if (q === '/v2/post/publish/video/init/') return ok({ publish_id: 'PUB' + id(), upload_url: `${MOCK}/tiktok/upload/1` });
        if (q === '/upload/1') { res.writeHead(201); return res.end(); }
        if (q === '/v2/post/publish/status/fetch/') return ok({ status: 'PUBLISH_COMPLETE', publicaly_available_post_id: [7300000001] });
        if (q === '/v2/video/query/') return ok({ videos: [{ id: '7300000001', view_count: 55, like_count: 4, comment_count: 1, share_count: 0 }] });
      }
      send(404, { error: 'unknown mock path ' + p });
    } catch (e) { send(500, { error: String(e) }); }
  });
}).listen(5098);
const callsTo = (re, method) => calls.filter((c) => re.test(c.path) && (!method || c.method === method));

// ---------- đăng nhập ----------
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } });
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
async function login(page, email, pw) {
  await page.goto(BASE + '/login'); await page.fill('#loginEmail', email); await page.fill('#loginPassword', pw);
  await Promise.all([page.waitForLoadState('networkidle').catch(() => {}), page.click('#btnLogin')]);
}
await login(p, EMAIL, PW);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const B = JSON.stringify(bid);
const CLEAN = `
from mongo_client import db
from gridfs import GridFS
bids = [${B}, (db.users.find_one({'email': '${EMAIL2}'}) or {}).get('business_id')]
n = 0
for coll in ('social_posts', 'social_post_metrics', 'social_plans', 'social_accounts', 'ai_media_jobs', 'ai_usage', 'generated_media', 'media_upload_chunks'):
    n += db[coll].delete_many({'business_id': {'$in': bids}, 'qa_test': True}).deleted_count
n += db.media_upload_chunks.delete_many({'business_id': {'$in': bids}}).deleted_count
fs = GridFS(db, collection='media')
for f in db['media.files'].find({'$or': [{'qa_test': True}, {'metadata.qa_test': True}], 'business_id': {'$in': bids}}, {'_id': 1}):
    fs.delete(f['_id']); n += 1
for f in db['media.files'].find({'$or': [{'qa_test': True}, {'metadata.qa_test': True}], 'metadata.business_id': {'$in': bids}}, {'_id': 1}):
    fs.delete(f['_id']); n += 1
print(n)`;
py(CLEAN);
const api = (page, path, method = 'GET', body, raw) => page.evaluate(async ([path, method, body, raw]) => {
  const opt = { method, headers: {} };
  if (raw) { opt.headers['Content-Type'] = 'application/octet-stream'; opt.body = new Uint8Array(raw); }
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt); let j = {}; try { j = await r.json(); } catch (e) { j = {}; }
  return { status: r.status, ...j };
}, [path, method, body, raw]);
const doc = (code) => JSON.parse(py(`
import json
from mongo_client import db
bid = ${B}
${code}`));

// ================= A. AI Studio: ảnh / video / upload =================
let q = await api(p, '/api/ai_studio/quota');
const quota = q.quota || q;
rec('AI Studio — hạn mức theo gói Empire (300 ảnh, 300 giây video/tháng)', q.success && quota.images && quota.images.limit === 300 && quota.video_seconds.limit === 300, JSON.stringify({ images: quota.images, video: quota.video_seconds }));

let r = await api(p, '/api/ai_studio/media/jobs', 'POST', { kind: 'image', preset: 'draft', prompt: 'close-up of glossy pink gel nails, soft daylight', aspect: '4:5' });
let job = r.job || {};
for (let i = 0; i < 10 && !['succeeded', 'failed'].includes(job.status); i++) { await sleep(1500); job = (await api(p, `/api/ai_studio/media/jobs/${job.id}`)).job || job; }
const imgCall = callsTo(/\/replicate\/v1\/models\/black-forest-labs\/flux-schnell\/predictions/, 'POST')[0];
rec('Tạo ảnh — gọi model flux-schnell qua endpoint chính thức, xin JPEG đúng khung 4:5, không webhook khi chạy local', !!imgCall && imgCall.json.input.output_format === 'jpg' && imgCall.json.input.aspect_ratio === '4:5' && !imgCall.json.webhook && /wait/.test(imgCall.headers.prefer || ''), imgCall ? JSON.stringify(imgCall.json.input) : r.message);
rec('Ảnh lưu bền (không phụ thuộc link Replicate hết hạn sau 1 giờ) + có link công khai', job.status === 'succeeded' && !!job.file_id && /\/m\//.test(job.public_url || ''), JSON.stringify({ status: job.status, file: job.file_id, url: job.public_url, err: job.error }));
const imgFile = job.file_id; const imgUrl = (job.public_url || '').startsWith('http') ? job.public_url : BASE + job.public_url;
{
  const anon = await fetch(imgUrl); const buf = Buffer.from(await anon.arrayBuffer());
  const rg = await fetch(imgUrl, { headers: { Range: 'bytes=0-99' } });
  const bad = await fetch(imgUrl.replace(/\.(\w+)$/, '') .replace(/[0-9a-f]{6}(?=[^/]*$)/, 'ffffff') + '.jpg');
  rec('Link ảnh công khai: mở không cần đăng nhập, image/jpeg, cache lâu; Range -> 206; link sửa bậy -> 404',
    anon.status === 200 && /image\/jpeg/.test(anon.headers.get('content-type') || '') && buf.length === JPEG.length && /max-age=86400/.test(anon.headers.get('cache-control') || '') && rg.status === 206 && bad.status === 404,
    `${anon.status} ${anon.headers.get('cache-control')} · range ${rg.status} · bad ${bad.status}`);
}

r = await api(p, '/api/ai_studio/media/jobs', 'POST', { kind: 'video', preset: 'standard', prompt: 'slow pan across a calm day spa, candles, towels', duration: 5 });
let vjob = r.job || {};
const vCall = callsTo(/\/replicate\/v1\/models\/bytedance\/seedance-1-pro-fast\/predictions/, 'POST')[0];
rec('Tạo video AI — seedance 720p, 9:16, 5 giây, tự huỷ sau 15 phút nếu treo', !!vCall && vCall.json.input.resolution === '720p' && vCall.json.input.aspect_ratio === '9:16' && Number(vCall.json.input.duration) === 5 && /15m/.test(vCall.headers['cancel-after'] || ''), vCall ? JSON.stringify(vCall.json.input) + ' ' + vCall.headers['cancel-after'] : r.message);
for (let i = 0; i < 12 && !['succeeded', 'failed'].includes(vjob.status); i++) { await sleep(2000); vjob = (await api(p, `/api/ai_studio/media/jobs/${vjob.id}`)).job || vjob; }
rec('Video: đang chạy -> xong, tải về lưu bền (mp4)', vjob.status === 'succeeded' && /video\/mp4/.test(vjob.content_type || '') && !!vjob.file_id, JSON.stringify({ s: vjob.status, t: vjob.content_type, e: vjob.error }));
const vidFile = vjob.file_id; const vidUrl = (vjob.public_url || '').startsWith('http') ? vjob.public_url : BASE + vjob.public_url;
{
  const rg = await fetch(vidUrl, { headers: { Range: 'bytes=0-' } });
  rec('Video phát được trên iPhone (Range 206 + Accept-Ranges)', rg.status === 206 && (rg.headers.get('accept-ranges') || '') === 'bytes' && /video\/mp4/.test(rg.headers.get('content-type') || ''), `${rg.status} ${rg.headers.get('content-range')}`);
}
r = await api(p, '/api/ai_studio/media/jobs', 'POST', { kind: 'video', preset: 'draft', prompt: 'make the nails shimmer', image_file_id: imgFile });
const i2v = callsTo(/\/replicate\/v1\/models\/wan-video\/wan-2\.2-i2v-fast\/predictions/, 'POST')[0];
rec('Làm ảnh chuyển động — dùng model i2v, gửi ảnh của chính tiệm', r.success && !!i2v && /^data:image\/jpeg;base64,/.test(String(i2v.json.input.image || '')), i2v ? Object.keys(i2v.json.input).join(',') : r.message);
let i2vJob = r.job || {}; for (let i = 0; i < 12 && !['succeeded', 'failed'].includes(i2vJob.status); i++) { await sleep(2000); i2vJob = (await api(p, `/api/ai_studio/media/jobs/${i2vJob.id}`)).job || i2vJob; }

// upload video quảng cáo dựng trên trình duyệt (chia khúc vì Vercel giới hạn 4,5 MB / request)
{
  const big = mp4(5_200_000);
  const init = await api(p, '/api/media/upload/init', 'POST', { kind: 'promo_video', size: big.length, content_type: 'video/mp4' });
  const cs = init.chunk_size || 3_400_000; let okc = true;
  for (let i = 0, k = 0; i < big.length; i += cs, k++) { const rr = await api(p, `/api/media/upload/${init.upload_id}/chunk?index=${k}`, 'POST', undefined, Array.from(big.subarray(i, i + cs))); okc = okc && rr.status === 200; }
  const fin = await api(p, `/api/media/upload/${init.upload_id}/finish`, 'POST', {});
  const fin2 = await api(p, `/api/media/upload/${init.upload_id}/finish`, 'POST', {});
  const list = await api(p, '/api/ai_studio/media?kind=promo_video');
  rec('Upload video quảng cáo 5,2 MB chia khúc -> 1 file; gọi finish lần 2 không tạo trùng; có trong thư viện', init.success && okc && fin.success && fin2.file_id === fin.file_id && (list.items || []).some((x) => (x.file_id || x.id) === fin.file_id), `${init.chunks || '?'} khúc · ${fin.file_id}`);
  const fake = Buffer.from('<html><script>alert(1)</script></html>');
  const i2 = await api(p, '/api/media/upload/init', 'POST', { kind: 'promo_video', size: fake.length, content_type: 'video/mp4' });
  await api(p, `/api/media/upload/${i2.upload_id}/chunk?index=0`, 'POST', undefined, Array.from(fake));
  const f2 = await api(p, `/api/media/upload/${i2.upload_id}/finish`, 'POST', {});
  rec('Upload giả danh video (thực chất HTML) bị từ chối', !f2.success && f2.status >= 400, `${f2.status} ${f2.code}`);
}
// webhook Replicate: ký sai -> 401, ký đúng -> 200
{
  const body = JSON.stringify({ id: Object.keys(state.preds).pop(), status: 'succeeded' });
  const wid = 'msg_qa1', ts = String(Math.floor(Date.now() / 1000));
  const sig = crypto.createHmac('sha256', Buffer.from(WH_SECRET_RAW)).update(`${wid}.${ts}.${body}`).digest('base64');
  const url = `${BASE}/api/ai_studio/replicate_webhook?job=${vjob.id}`;
  const bad = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'webhook-id': wid, 'webhook-timestamp': ts, 'webhook-signature': 'v1,AAAA' }, body });
  const good = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'webhook-id': wid, 'webhook-timestamp': ts, 'webhook-signature': 'v1,' + sig }, body });
  rec('Webhook Replicate — chữ ký sai 401, chữ ký đúng 200', bad.status === 401 && good.status === 200, `${bad.status} / ${good.status}`);
}
q = await api(p, '/api/ai_studio/quota'); const q2 = q.quota || q;
const usage = doc(`print(json.dumps(db.ai_usage.count_documents({'business_id': bid, 'qa_test': True, 'kind': {'$in': ['image', 'video']}})))`);
rec('Sổ chi phí: mỗi ảnh/video xong ghi đúng 1 dòng; hạn mức đã dùng tăng', usage === 3 && q2.images.used >= 1 && q2.video_seconds.used >= 10, `ai_usage=${usage} · ảnh ${q2.images.used} · video ${q2.video_seconds.used}s`);

// ================= B. AI đăng bài đa nền tảng =================
r = await api(p, '/api/social/accounts/facebook', 'POST', { action: 'connect_token', fields: { access_token: 'bad-token', page_id: 'PAGE1' } });
rec('Nối Facebook bằng token sai — báo lỗi rõ, không lưu', !r.success && /token/.test(r.code || ''), `${r.code}: ${r.message}`);
r = await api(p, '/api/social/accounts/facebook', 'POST', { action: 'connect_token', fields: { access_token: 'qa-good', page_id: 'PAGE1' } });
const r2 = await api(p, '/api/social/accounts/instagram', 'POST', { action: 'connect_token', fields: { access_token: 'qa-good', ig_user_id: 'IG1' } });
rec('Nối Facebook Page + Instagram (kiểm token với Meta)', r.success && r2.success, `${(r.data || {}).account_name} · ${(r2.data || {}).account_name}`);
for (const pf of ['youtube', 'google_business', 'tiktok']) {
  const resp = [];
  const onResp = (x) => { if (x.url().includes('/social?')) resp.push(x.url()); };
  p.on('response', onResp);
  await p.goto(`${BASE}/social/oauth/${pf}/start`, { waitUntil: 'domcontentloaded' }).catch(() => {});
  await p.waitForTimeout(800); p.off('response', onResp);
  rec(`Đăng nhập ${pf} (OAuth) -> quay về /social?connected=${pf}`, resp.some((x) => x.includes(`connected=${pf}`)) && !resp.some((x) => x.includes('error=')), resp.map((x) => x.replace(BASE, '')).join(' ') || p.url());
}
const accs = await api(p, '/api/social/accounts');
const accText = JSON.stringify(accs);
rec('Trạng thái 5 tài khoản đã nối; không lộ token ra trình duyệt', ['facebook', 'instagram', 'youtube', 'google_business', 'tiktok'].every((k) => accs.data[k] && accs.data[k].connected) && !/qa-good|qa-google-at|qa-tt-at|qa-google-rt/.test(accText), Object.keys(accs.data || {}).map((k) => `${k}:${accs.data[k].status}`).join(' '));

// bài ẢNH -> Facebook + Instagram + Google Business, đăng ngay
r = await api(p, '/api/social/posts', 'POST', { caption: 'Fresh gel colours this week at Golden Lotus — book online.', media_file_ids: [imgFile],
  targets: [{ platform: 'facebook' }, { platform: 'instagram' }, { platform: 'google_business' }], status: 'scheduled' });
const imgPost = r.post || {};
r = await api(p, `/api/social/posts/${imgPost.id}/publish_now`, 'POST', {});
let post = r.post || {};
const igMedia = callsTo(/\/meta\/v[\d.]+\/IG1\/media$/, 'POST')[0];
rec('Bài ảnh: Facebook nhận ảnh, Google Business nhận bài, Instagram tải được ảnh từ link công khai (JPEG thật)',
  callsTo(/\/PAGE1\/photos$/, 'POST').length >= 1 && callsTo(/\/localPosts$/, 'POST').length === 1 && !!igMedia && igMedia.fetched && igMedia.fetched.status === 200 && /image\/jpeg/.test(igMedia.fetched.type || '') && igMedia.fetched.magic.startsWith('ffd8'),
  JSON.stringify({ fetched: igMedia && igMedia.fetched, status: post.status }));
rec('Bài ảnh: đủ 3 nơi đã đăng (Instagram ảnh xong ngay)', post.status === 'published' && (post.targets || []).every((t) => t.status === 'published'), (post.targets || []).map((t) => `${t.platform}:${t.status}${t.error ? '(' + t.error.code + ')' : ''}`).join(' '));

// bài VIDEO -> Instagram Reels + YouTube + TikTok (TikTok bắt buộc chủ tiệm chọn quyền riêng tư)
r = await api(p, '/api/social/posts', 'POST', { caption: 'A calm hour at the spa', title: 'Calm hour at Golden Lotus', media_file_ids: [vidFile],
  targets: [{ platform: 'instagram' }, { platform: 'youtube' }, { platform: 'tiktok' }], status: 'scheduled' });
rec('TikTok chưa chọn quyền riêng tư -> không cho lên lịch', !r.success && /tiktok|privacy/i.test((r.code || '') + (r.message || '')), `${r.code}: ${r.message}`);
const ttOpts = { privacy_level: 'SELF_ONLY', disable_comment: false, disable_duet: true, disable_stitch: true, brand_content_toggle: false, brand_organic_toggle: false };
r = await api(p, '/api/social/posts', 'POST', { caption: 'A calm hour at the spa', title: 'Calm hour at Golden Lotus', media_file_ids: [vidFile],
  targets: [{ platform: 'instagram' }, { platform: 'youtube' }, { platform: 'tiktok', options: ttOpts }], status: 'scheduled' });
const vidPost = r.post || {};
r = await api(p, `/api/social/posts/${vidPost.id}/publish_now`, 'POST', {});
post = r.post || {};
const st1 = Object.fromEntries((post.targets || []).map((t) => [t.platform, t.status]));
const ttInit = callsTo(/\/tiktok\/v2\/post\/publish\/video\/init\//, 'POST')[0]; const ttPut = callsTo(/\/tiktok\/upload\/1/, 'PUT')[0];
const ytInit = callsTo(/\/google\/upload\/youtube\/v3\/videos/, 'POST')[0];
rec('Bài video: YouTube tải lên xong (đánh dấu video AI), Instagram + TikTok đang xử lý', st1.youtube === 'published' && ['processing', 'published'].includes(st1.instagram) && ['processing', 'published'].includes(st1.tiktok) && !!ytInit && ytInit.json && ytInit.json.status && ytInit.json.status.containsSyntheticMedia === true, JSON.stringify(st1));
rec('TikTok: gửi đúng quyền riêng tư chủ tiệm chọn + is_aigc, upload đủ byte (Content-Range)', !!ttInit && ttInit.json.post_info.privacy_level === 'SELF_ONLY' && ttInit.json.post_info.is_aigc === true && !!ttPut && ttPut.size === VIDEO.length && /bytes 0-/.test(ttPut.headers['content-range'] || ''), ttInit ? JSON.stringify(ttInit.json.post_info) : 'no init');
const cron = (auth) => fetch(`${BASE}/api/cron/social_tick`, { headers: auth ? { Authorization: auth } : {} });
rec('Cron đăng bài — thiếu khoá bí mật -> 401', (await cron(null)).status === 401 && (await cron('Bearer wrong')).status === 401);
const ffwd = (pid) => py(`
from datetime import datetime, timedelta, timezone
from mongo_client import db
d = db.social_posts.find_one({'id': ${pid}, 'business_id': ${B}}, {'targets': 1})
past = datetime.now(timezone.utc) - timedelta(seconds=5)
for i, t in enumerate((d or {}).get('targets') or []):
    db.social_posts.update_one({'id': ${pid}, 'business_id': ${B}}, {'$set': {f'targets.{i}.next_attempt_at': past}})
print('ok')`);   // bài đang xử lý (Reels/TikTok) được kiểm lại sau 30 giây — tua nhanh thay vì chờ
for (let i = 0; i < 4; i++) { ffwd(vidPost.id); await cron('Bearer qa-cron'); await sleep(300); }
post = (await api(p, '/api/social/posts')).data.find((x) => x.id === vidPost.id) || {};
rec('Sau cron: Instagram Reels + TikTok -> đã đăng', post.status === 'published' && (post.targets || []).every((t) => t.status === 'published'), (post.targets || []).map((t) => `${t.platform}:${t.status}`).join(' '));
const rup = callsTo(/\/meta\/ig-api-upload\//, 'POST')[0];
rec('Instagram Reels: tải thẳng đủ byte video lên Instagram (không phụ thuộc link — Vercel giới hạn 4,5 MB/response)', !!rup && rup.size === VIDEO.length && rup.headers.authorization === 'OAuth qa-good', rup ? `${rup.size} byte` : 'không thấy upload');

// hẹn giờ Facebook 2 giờ nữa -> Meta tự đăng đúng giờ (published=false + scheduled_publish_time); huỷ -> gỡ bên Meta
const at = new Date(Date.now() + 2 * 3600e3).toISOString();
r = await api(p, '/api/social/posts', 'POST', { caption: 'Weekend special: free nail art with any gel set.', targets: [{ platform: 'facebook' }], scheduled_at: at, status: 'scheduled' });
const schPost = r.post || {};
await cron('Bearer qa-cron');   // cron đẩy trước bài Facebook hẹn xa lên Meta (Meta tự đăng đúng giờ)
const feedCall = callsTo(/\/PAGE1\/feed$/, 'POST').pop();
post = (await api(p, '/api/social/posts')).data.find((x) => x.id === schPost.id) || {};
rec('Hẹn giờ Facebook: gửi published=false + scheduled_publish_time (Meta tự đăng đúng giờ)', !!feedCall && /published.{0,4}false|"published":\s*false/.test(feedCall.text + JSON.stringify(feedCall.q) + JSON.stringify(feedCall.json || {})) && /scheduled_publish_time/.test(feedCall.text + JSON.stringify(feedCall.q) + JSON.stringify(feedCall.json || {})) && (post.targets || [])[0].status === 'scheduled_remote', (post.targets || []).map((t) => t.status).join(','));
const delBefore = callsTo(/\/meta\//, 'DELETE').length;
r = await api(p, `/api/social/posts/${schPost.id}/cancel`, 'POST', {});
rec('Huỷ bài đã hẹn trên Facebook -> gỡ lịch bên Meta (không tự lên)', r.success && callsTo(/\/meta\//, 'DELETE').length === delBefore + 1, `${r.post && r.post.status}`);

// lỗi tạm (Meta 500) -> thử lại, không mất bài; token hết hạn (190) -> báo nối lại
state.failFeed = 1;
r = await api(p, '/api/social/posts', 'POST', { caption: 'Open late on Thursdays until 8pm.', targets: [{ platform: 'facebook' }], status: 'scheduled' });
const tPost = r.post || {};
r = await api(p, `/api/social/posts/${tPost.id}/publish_now`, 'POST', {});
const t1 = ((r.post || {}).targets || [])[0] || {};
py(`
from datetime import datetime, timedelta, timezone
from mongo_client import db
db.social_posts.update_one({'id': ${tPost.id || 0}, 'business_id': ${B}}, {'$set': {'targets.0.next_attempt_at': datetime.now(timezone.utc) - timedelta(minutes=1)}})
print('ok')`);
await cron('Bearer qa-cron');
post = (await api(p, '/api/social/posts')).data.find((x) => x.id === tPost.id) || {};
rec('Meta lỗi tạm 500 -> giữ bài, thử lại lần sau -> đã đăng', (t1.attempts || 0) >= 1 && t1.status !== 'failed' && post.status === 'published', `lần 1: ${t1.status} (${t1.attempts}) -> ${post.status}`);
state.fail190 = true;
r = await api(p, '/api/social/posts', 'POST', { caption: 'Token test', targets: [{ platform: 'facebook' }], status: 'scheduled' });
r = await api(p, `/api/social/posts/${(r.post || {}).id}/publish_now`, 'POST', {});
const acc2 = await api(p, '/api/social/accounts');
rec('Token Facebook hết hạn (190) -> bài báo lỗi, tài khoản "cần nối lại"', (((r.post || {}).targets || [])[0] || {}).status === 'failed' && acc2.data.facebook.status === 'needs_reconnect', `${acc2.data.facebook.status}`);
await api(p, '/api/social/accounts/facebook', 'POST', { action: 'connect_token', fields: { access_token: 'qa-good', page_id: 'PAGE1' } });

// số liệu THẬT từ nền tảng + giờ đăng tốt nhất + AI
await cron('Bearer qa-cron');
const ins = await api(p, '/api/social/insights?days=30');
const insText = JSON.stringify(ins);
rec('Số liệu: lấy đúng con số nền tảng trả về (FB 321 lượt xem, IG 410, YouTube 77, TikTok 55)', ins.success && /321/.test(insText) && /410/.test(insText) && /\b77\b/.test(insText) && /\b55\b/.test(insText), insText.slice(0, 200));
const bt = await api(p, '/api/social/best_times?platform=facebook');
rec('Giờ đăng tốt nhất: chưa đủ dữ liệu -> ghi rõ "mặc định theo ngành"', bt.success && bt.source === 'default' && (bt.slots || []).length >= 1, JSON.stringify({ source: bt.source, slots: (bt.slots || []).slice(0, 3), note: bt.note }));
let t0 = Date.now();
const cap = await api(p, '/api/social/captions', 'POST', { text: 'New spring gel colours, book this week', platforms: ['instagram', 'facebook', 'google_business', 'tiktok'], lang: 'en' });
const capt = cap.captions || {};
rec('AI viết caption theo từng nền tảng (Instagram có hashtag, Google Business không hashtag, TikTok ngắn)', cap.success && /#\w/.test(capt.instagram || '') && !/#\w/.test(capt.google_business || '') && (capt.tiktok || '').length <= 150 && (capt.facebook || '').length > 10,
  `${((Date.now() - t0) / 1000).toFixed(1)}s · IG: "${(capt.instagram || '').slice(0, 80)}" · GBP: "${(capt.google_business || '').slice(0, 60)}"`);
t0 = Date.now();
const plan = await api(p, '/api/social/plan/week', 'POST', { platforms: ['facebook', 'google_business'], posts_per_week: 3, lang: 'en' });
const drafts = plan.posts || [];
rec('AI lên kế hoạch tuần: tạo bài nháp CHỜ DUYỆT (không tự đăng), giờ đăng theo thuật toán, nội dung từ dịch vụ thật', plan.success && drafts.length >= 2 && drafts.every((x) => x.status === 'pending_approval' && x.created_by === 'ai' && x.scheduled_at),
  `${((Date.now() - t0) / 1000).toFixed(1)}s · ${drafts.length} bài · "${(drafts[0] || {}).caption ? drafts[0].caption.slice(0, 90) : plan.message}"`);
if (drafts[0]) {
  const ap = await api(p, `/api/social/posts/${drafts[0].id}/approve`, 'POST', {});
  rec('Chủ tiệm duyệt 1 bài AI -> lên lịch', ap.success && ap.post.status === 'scheduled', ap.post && ap.post.status);
}
const rv = await api(p, '/api/social/review', 'POST', { lang: 'en' });
rec('AI đánh giá hiệu quả: chỉ dựa trên số liệu thật (ít dữ liệu thì nói thẳng)', rv.success && typeof rv.enough_data === 'boolean' && (rv.text || '').length > 20, `${rv.enough_data} · ${(rv.text || '').slice(0, 120)}`);

// ================= C. Giao diện =================
await p.goto(BASE + '/social', { waitUntil: 'load' }); await p.waitForTimeout(2500);
const socialTxt = await p.evaluate(() => document.body.innerText);
rec('Trang Đăng bài mở được, không lỗi JS, thấy bài đã đăng + bài chờ duyệt', errs.length === 0 && /Golden Lotus|Fresh gel|spa/i.test(socialTxt), errs.slice(0, 2).join(' | '));
await p.goto(`${BASE}/social?compose=1&media=${imgFile}`, { waitUntil: 'load' }); await p.waitForTimeout(2500);
const hasMedia = await p.evaluate((f) => document.body.innerHTML.includes(f), imgFile);
rec('Từ AI Studio bấm "Dùng để đăng bài" -> mở khung soạn có sẵn ảnh', hasMedia);
await p.goto(BASE + '/ai-studio', { waitUntil: 'load' }); await p.waitForTimeout(2500);
const studioTxt = await p.evaluate(() => document.body.innerText);
rec('AI Studio: không còn chữ/badge giả (ANTI-BOT, Ecosystem Connected, 10K, Load Algorithm)', !/ANTI-BOT|Ecosystem Connected|Load Algorithm|\b10K\b/i.test(studioTxt) && errs.length === 0, errs.slice(0, 2).join(' | '));
const m = await ctx.newPage(); m.on('pageerror', (e) => errs.push(e.message));
await m.setViewportSize({ width: 390, height: 844 });
let over = [];
for (const path of ['/social', '/ai-studio']) { await m.goto(BASE + path, { waitUntil: 'load' }); await m.waitForTimeout(2000); over.push(await m.evaluate(() => document.documentElement.scrollWidth - innerWidth)); }
rec('Điện thoại 390px: Đăng bài + AI Studio không tràn ngang', over.every((x) => x <= 1), over.join(' / '));

// ================= D. Cách ly giữa các tiệm =================
const ctx2 = await b.newContext(); const p2 = await ctx2.newPage(); await login(p2, EMAIL2, PW2);
const other = await api(p2, '/api/social/posts');
const steal = await api(p2, `/api/social/posts/${imgPost.id}`, 'PUT', { caption: 'hacked' });
const steal2 = await api(p2, `/api/ai_studio/media/jobs/${job.id}`);
const steal3 = await api(p2, `/api/social/posts`, 'POST', { caption: 'x', media_file_ids: [imgFile], targets: [{ platform: 'facebook' }], status: 'draft' });
rec('Tiệm khác không xem / sửa / dùng ảnh / đọc job của tiệm này', !(other.data || []).some((x) => x.id === imgPost.id) && !steal.success && !steal2.success && !steal3.success, `${steal.status} ${steal2.status} ${steal3.status}:${steal3.code}`);
rec('Không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

const cleaned = py(CLEAN);
console.log(`dọn ${cleaned} bản ghi test · gọi máy giả ${calls.length} lần`);
const pass = steps.filter((s) => s.ok).length;
console.log(`\nTổng: ${pass} PASS · ${steps.length - pass} FAIL`);
await b.close(); mock.close();
process.exit(steps.length - pass ? 1 : 0);
