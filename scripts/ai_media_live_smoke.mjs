// ai_media_live_smoke.mjs — GỌI REPLICATE THẬT (tốn tiền thật, ~US$0.12): 1 ảnh nháp (flux-schnell ~$0.003), 1 video nháp
// (wan-2.2-t2v-fast 480p ~$0.05), 1 lần làm ảnh chuyển động (wan-2.2-i2v-fast ~$0.065). Xác nhận tên tham số model đúng với
// Replicate hiện tại, file tải về lưu bền + link công khai phát được. Xong thì XOÁ file/job/sổ chi phí của lần thử.
//   Server local KHÔNG đặt REPLICATE_API_BASE (dùng token thật trong .env). Chỉ chạy khi chủ dự án đồng ý chi phí.
//   BASE=http://127.0.0.1:5006 node scripts/ai_media_live_smoke.mjs
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5006';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + String(note).slice(0, 260) : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const b = await chromium.launch({ channel: 'chrome' });
const p = await (await b.newContext()).newPage();
await p.goto(BASE + '/login'); await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const api = (path, method = 'GET', body) => p.evaluate(async ([path, method, body]) => {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let j = {}; try { j = await r.json(); } catch (e) { j = {}; }
  return { status: r.status, ...j };
}, [path, method, body]);
const jobIds = [];
async function run(label, body, maxWaitS) {
  const t0 = Date.now();
  const r = await api('/api/ai_studio/media/jobs', 'POST', body);
  let job = r.job || {};
  if (job.id) jobIds.push(job.id);
  while (job.id && !['succeeded', 'failed', 'canceled'].includes(job.status) && (Date.now() - t0) / 1000 < maxWaitS) {
    await sleep(4000); job = (await api(`/api/ai_studio/media/jobs/${job.id}`)).job || job;
  }
  const secs = ((Date.now() - t0) / 1000).toFixed(0);
  let play = null;
  const link = job.play_url || job.public_url;
  if (link) {
    const u = link.startsWith('http') ? link : BASE + link;
    const res = await fetch(u, { headers: job.kind === 'video' ? { Range: 'bytes=0-' } : {} });
    const buf = Buffer.from(await res.arrayBuffer());
    play = { status: res.status, type: res.headers.get('content-type'), bytes: buf.length, total: res.headers.get('content-range') };
  }
  rec(`${label} — Replicate thật, ${secs}s`, job.status === 'succeeded' && play && [200, 206].includes(play.status), JSON.stringify({ status: job.status, model: job.model, err: job.error || r.message, play }));
  return job;
}
const img = await run('Ảnh nháp (flux-schnell, 1:1)', { kind: 'image', preset: 'draft', prompt: 'Close-up of a manicured hand with glossy nude gel nails on a marble table, soft daylight, product photography', aspect: '1:1' }, 90);
await run('Video nháp từ chữ (wan 2.2 t2v fast, 480p, 9:16)', { kind: 'video', preset: 'draft', prompt: 'Slow dolly shot across a calm, bright nail salon with plants and pastel chairs, morning light', duration: 5 }, 420);
if (img.file_id) await run('Làm ảnh vừa tạo chuyển động (wan 2.2 i2v fast)', { kind: 'video', preset: 'draft', prompt: 'gentle light shimmer moving across the nails, subtle camera push-in', image_file_id: img.file_id, duration: 5 }, 420);
const usage = py(`
import json
from mongo_client import db
rows = list(db.ai_usage.find({'job_id': {'$in': ${JSON.stringify(jobIds)}}}, {'_id': 0, 'kind': 1, 'units': 1, 'cost_usd': 1, 'model': 1}))
print(json.dumps(rows))`);
rec('Sổ chi phí ghi đúng từng lần (chi phí thật ước tính)', JSON.parse(usage).length === jobIds.length, usage);
// dọn: file + job + sổ chi phí của lần thử (không để rác trong DB dùng chung với production)
const cleaned = py(`
from mongo_client import db
from gridfs import GridFS
from bson import ObjectId
ids = ${JSON.stringify(jobIds)}
fs = GridFS(db, collection='media'); n = 0
for j in db.ai_media_jobs.find({'id': {'$in': ids}}, {'file_id': 1}):
    if j.get('file_id'):
        try: fs.delete(ObjectId(j['file_id'])); n += 1
        except Exception: pass
n += db.ai_media_jobs.delete_many({'id': {'$in': ids}}).deleted_count
n += db.ai_usage.delete_many({'job_id': {'$in': ids}}).deleted_count
n += db.generated_media.delete_many({'job_id': {'$in': ids}}).deleted_count
n += db.ai_media_quota.delete_many({'business_id': ${JSON.stringify(EMAIL)}}).deleted_count if 'ai_media_quota' in db.list_collection_names() else 0
print(n)`);
console.log('dọn', cleaned, 'bản ghi');
const pass = steps.filter((s) => s.ok).length;
console.log(`\nTổng: ${pass} PASS · ${steps.length - pass} FAIL`);
await b.close();
process.exit(steps.length - pass ? 1 : 0);
