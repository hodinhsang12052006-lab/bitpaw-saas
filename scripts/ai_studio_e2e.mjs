// ai_studio_e2e.mjs — AI Studio chạy THẬT qua giao diện (DeepSeek thật), không còn nội dung giả/mock.
//   node scripts/ai_studio_e2e.mjs      (CHỈ server local; cần DEEPSEEK_API_KEY trong .env)
import { chromium } from 'playwright';
import { execFileSync } from 'child_process';
import fs from 'fs';

const BASE = 'http://127.0.0.1:5001';
const EMAIL = 'demo.nails.au.006758@bitpawdemo.com', PW = 'DemoNails2026!';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const ERR = '⚠️ The AI could not answer';

const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 950 }, acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] });
const p = await ctx.newPage();
const errs = []; p.on('pageerror', (e) => errs.push(e.message));
const dialogs = []; p.on('dialog', async (d) => { dialogs.push(d.message()); await d.accept(); });
await p.goto(BASE + '/login');
await p.fill('#loginEmail', EMAIL); await p.fill('#loginPassword', PW);
await Promise.all([p.waitForLoadState('networkidle').catch(() => {}), p.click('#btnLogin')]);
const bid = py(`
from mongo_client import db
print(db.users.find_one({'email': '${EMAIL}'})['business_id'])`);
const hadBrand = py(`
from mongo_client import db
print(1 if db.ai_brand_profiles.find_one({'business_id': ${JSON.stringify(bid)}}) else 0)`) === '1';

await p.goto(BASE + '/ai-studio', { waitUntil: 'networkidle' });
rec('Mở AI Studio không lỗi JS', errs.length === 0, errs.slice(0, 2).join(' | '));

// Đợi kết quả AI trong ô/ modal (tối đa 90 s)
async function waitAi(selector) {
  await p.waitForFunction((sel) => { const el = document.querySelector(sel); return el && el.value && !el.value.startsWith('Writing with DeepSeek') && !el.closest('.hidden'); }, selector, { timeout: 90000 }).catch(() => {});
  return p.$eval(selector, (el) => el.value);
}
async function modalRun(label, fnCall, must) {
  const t0 = Date.now();
  await p.evaluate(() => { document.getElementById('aiResultText').value = ''; });
  await p.evaluate(fnCall);
  await p.waitForFunction(() => { const m = document.getElementById('aiModal'); const v = document.getElementById('aiResultText').value; return !m.classList.contains('hidden') && v && document.getElementById('aiLoading').classList.contains('hidden'); }, null, { timeout: 90000 }).catch(() => {});
  const v = await p.$eval('#aiResultText', (el) => el.value);
  rec(`${label} — AI trả lời thật`, v.length > 150 && !v.startsWith(ERR) && (!must || must.test(v)), `${((Date.now() - t0) / 1000).toFixed(1)}s · ${v.length} ký tự · "${v.slice(0, 70).replace(/\n/g, ' ')}"`);
  await p.evaluate(() => closeAiModal());
  return v;
}

// 1) Brand DNA lưu server
await p.click('button[onclick="openBrandModal()"]').catch(async () => p.evaluate(() => openBrandModal()));
await p.waitForSelector('#brandModal:not(.hidden)');
await p.fill('#brandName', 'Lotus Nails Sydney'); await p.fill('#brandUsp', 'Gel-X extensions that last 4 weeks, no damage');
await p.fill('#brandAudience', 'Busy women 25-45 in Sydney CBD'); await p.fill('#brandBlacklist', 'cheapest, guaranteed');
await p.click('#brandSaveBtn'); await p.waitForTimeout(800);
await p.evaluate(() => { localStorage.removeItem('bitpaw_brand_name'); localStorage.removeItem('bitpaw_brand_usp'); });
await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(600);
const brand = await p.evaluate(() => ({ name: localStorage.getItem('bitpaw_brand_name'), usp: localStorage.getItem('bitpaw_brand_usp') }));
rec('Brand DNA lưu server — xoá bộ nhớ máy rồi tải lại vẫn còn', brand.name === 'Lotus Nails Sydney' && /Gel-X/.test(brand.usp || ''), JSON.stringify(brand));

// 2) Lời thoại: tải file .srt -> bỏ số thứ tự + mốc thời gian
const srt = '1\n00:00:00,000 --> 00:00:03,000\nStop scrolling if your gel nails lift after a week.\n\n2\n00:00:03,000 --> 00:00:08,000\nHere is the 3-step prep we use on every client.\n';
await p.setInputFiles('#subtitleFile', { name: 'video.srt', mimeType: 'text/plain', buffer: Buffer.from(srt) });
await p.waitForTimeout(400);
const orig = await p.evaluate(() => getOriginalText());
rec('Tải file .srt — lấy đúng lời thoại, bỏ số + mốc thời gian', orig.includes('Stop scrolling') && orig.includes('3-step prep') && !orig.includes('-->') && !/^\d+$/m.test(orig), JSON.stringify(orig));

// 3) Viết lại kịch bản (có lời thoại gốc)
await p.fill('#userPrompt', 'Make a 30-second TikTok for our Gel-X service, friendly tone');
await p.click('button[onclick="startDeepSeekRewrite(this)"]');
const script = await waitAi('#aiScript');
rec('GENERATE — kịch bản mới từ lời thoại + Brand DNA', script.length > 300 && !script.startsWith(ERR) && /Lotus|Gel-X/i.test(script), `${script.length} ký tự · "${script.slice(0, 80).replace(/\n/g, ' ')}"`);

// 4) Các công cụ (modal)
await modalRun('A/B 5 câu hook', () => testHooks(), /1[.)]|hook/i);
await modalRun('Creator brief (có hướng dẫn #ad)', () => generateKOCBrief(), /#ad|disclos|paid partnership/i);
await modalRun('Đăng đa kênh (FB/blog/email)', () => repurposeContent(), /email|subject/i);
await modalRun('Kế hoạch dựng video', () => analyzeVideoEdit(), /hook|b-roll|music/i);
await modalRun('Kế hoạch đăng bài + hashtag', () => analyzeAlgorithm(), /#/);

// 5) Bộ dựng video Faceless: kịch bản từng cảnh + tải phụ đề .srt thật
{
  await p.evaluate(() => buildFacelessKit(document.querySelector('button[onclick="buildFacelessKit(this)"]')));
  await p.waitForFunction(() => document.getElementById('aiLoading').classList.contains('hidden') && document.getElementById('aiResultText').value.length > 0, null, { timeout: 90000 }).catch(() => {});
  const kit = await p.$eval('#aiResultText', (el) => el.value);
  const btns = await p.$$eval('#aiModalActions > *', (els) => els.map((e) => e.textContent.trim()));
  rec('Video Kit — có từng cảnh + nút phụ đề/giọng đọc/cảnh quay', /SCENE 1/.test(kit) && btns.some((t) => /captions/i.test(t)) && btns.some((t) => /footage/i.test(t)), `${btns.length} nút · "${kit.slice(0, 70).replace(/\n/g, ' ')}"`);
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 10000 }).catch(() => null), p.click('#aiModalActions button:has-text("captions")').catch(() => {})]);
  let srtOut = ''; if (dl) { const f = await dl.path(); srtOut = fs.readFileSync(f, 'utf-8'); }
  rec('Video Kit — tải file captions.srt đúng định dạng', !!dl && dl.suggestedFilename() === 'captions.srt' && /^1\n\d\d:\d\d:\d\d,\d{3} --> /.test(srtOut), srtOut.split('\n').slice(0, 3).join(' | '));
  const foot = await p.$eval('#aiModalActions a', (a) => a.href).catch(() => '');
  rec('Video Kit — link tìm cảnh quay miễn phí (Pexels)', foot.startsWith('https://www.pexels.com/search/videos/'), foot);
  await p.evaluate(() => closeAiModal());
}

// 6) Nghe thử: gọi speechSynthesis thật của máy (không còn nút "Playing..." giả)
{
  await p.evaluate(() => { window.__spoken = null; if (window.speechSynthesis) { const o = speechSynthesis.speak.bind(speechSynthesis); speechSynthesis.speak = (u) => { window.__spoken = u.text; o(u); }; } });
  await p.click('button[onclick="speakScript(this)"]');
  const spoken = await p.evaluate(() => window.__spoken);
  rec('Nghe thử — đọc thành tiếng bằng giọng của máy', !!spoken && spoken.length > 50, spoken ? spoken.slice(0, 60) : 'không đọc');
  await p.evaluate(() => speechSynthesis.cancel());
}

// 7) Ma trận 30 ngày
{
  await p.evaluate(() => openMatrixModal());
  await p.fill('#matrixGoal', 'Get 40 new Gel-X clients this month in Sydney');
  await p.click('button[onclick="generateMatrix(this)"]');
  await p.waitForFunction(() => document.getElementById('matrixLoading').classList.contains('hidden') && document.getElementById('matrixResult').value.length > 0, null, { timeout: 120000 }).catch(() => {});
  const m = await p.$eval('#matrixResult', (el) => el.value);
  rec('Ma trận nội dung 30 ngày — dạng bảng', m.includes('|') && !m.startsWith(ERR) && m.length > 500, `${m.length} ký tự`);
  await p.evaluate(() => closeMatrixModal());
}

// 8) Chẩn đoán kênh: thiếu số liệu -> nhắc dán số; có số -> phân tích đúng số đã dán
{
  await p.evaluate(() => openDoctorModal());
  await p.fill('#channelLink', 'https://www.tiktok.com/@lotusnails');
  const before = dialogs.length;
  await p.click('button[onclick="diagnoseChannel(this)"]'); await p.waitForTimeout(300);
  rec('Chẩn đoán kênh — chưa có số liệu thì yêu cầu dán số (không bịa)', dialogs.length > before && /Paste the numbers/.test(dialogs[dialogs.length - 1]));
  await p.fill('#channelStats', "Video 1: Gel-X before/after — 1240 views, 38% watched, 52 likes, 4 comments, Tue 7pm\nVideo 2: Price list talking — 310 views, 9% watched, 6 likes, 0 comments, Mon 11am\nVideo 3: Nail art time-lapse — 2890 views, 61% watched, 140 likes, 12 comments, Sat 10am");
  await p.click('button[onclick="diagnoseChannel(this)"]');
  await p.waitForFunction(() => document.getElementById('doctorLoading').classList.contains('hidden') && document.getElementById('doctorResult').value.length > 0, null, { timeout: 90000 }).catch(() => {});
  const d = await p.$eval('#doctorResult', (el) => el.value);
  rec('Chẩn đoán kênh — dựa đúng số liệu đã dán', !d.startsWith(ERR) && /(310|9%|2,?890|61%)/.test(d), `"${d.slice(0, 80).replace(/\n/g, ' ')}"`);
  await p.evaluate(() => closeDoctorModal());
}

// 9) Xuất gói đăng (máy tính): chép + tải .txt, lưu lịch sử "Ready to post"
{
  await p.evaluate(() => openMobileOptimizerModal());
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 10000 }).catch(() => null), p.click('button[onclick="exportMobilePackage(this)"]')]);
  await p.waitForTimeout(400);
  const clip = await p.evaluate(() => navigator.clipboard.readText().catch(() => ''));
  const hist = await p.evaluate(() => (JSON.parse(localStorage.getItem('bitpaw_ai_history') || '[]')[0] || {}).title || '');
  rec('Xuất gói đăng — chép clipboard + tải .txt + lịch sử', !!dl && /\.txt$/.test(dl.suggestedFilename()) && clip.length > 100 && /Ready to post/.test(hist), `${dl && dl.suggestedFilename()} · clipboard ${clip.length} ký tự`);
  const fakeRev = await p.evaluate(() => /12\.5M|24M|850K|5\.2M/.test(document.body.innerText));
  rec('Lịch sử không còn "doanh thu" giả', !fakeRev);
}

// 10) Copy & Close chép thật
{
  await p.evaluate(() => { document.getElementById('aiModal').classList.remove('hidden'); document.getElementById('aiResultText').value = 'COPY-TEST 123'; });
  await p.click('button[onclick="copyAndCloseAiModal(this)"]'); await p.waitForTimeout(700);
  rec('Copy & Close — chép đúng nội dung rồi đóng', (await p.evaluate(() => navigator.clipboard.readText())) === 'COPY-TEST 123' && await p.evaluate(() => document.getElementById('aiModal').classList.contains('hidden')));
}

// 11) AI lỗi -> báo lỗi rõ, KHÔNG hiện nội dung mẫu
{
  await p.route('**/api/ai_studio/generate_text', (r) => r.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'DeepSeek timeout (test)' }) }));
  await p.fill('#userPrompt', 'Write a promo for Mother\'s Day');
  await p.click('button[onclick="startDeepSeekRewrite(this)"]');
  await p.waitForFunction(() => !document.getElementById('aiScript').value.startsWith('Writing'), null, { timeout: 15000 });
  const v = await p.$eval('#aiScript', (el) => el.value);
  rec('AI lỗi — báo rõ lý do, không hiện nội dung mẫu', v.startsWith(ERR) && v.includes('DeepSeek timeout (test)') && !/VIRAL REWRITE SCRIPT|BITPAW AI STUDIO SYSTEM/.test(v), v.slice(0, 80).replace(/\n/g, ' '));
  await p.unroute('**/api/ai_studio/generate_text');
}

// 12) Không có lời thoại vẫn viết được từ công cụ nhanh
{
  await p.evaluate(() => createNewProject());
  await p.evaluate(() => populatePrompt('facebook'));
  await p.click('button[onclick="startDeepSeekRewrite(this)"]');
  const v = await waitAi('#aiScript');
  rec('Công cụ nhanh (Facebook post) chạy được không cần video', v.length > 200 && !v.startsWith(ERR), `${v.length} ký tự`);
}
rec('Không lỗi JS suốt quá trình', errs.length === 0, errs.slice(0, 3).join(' | '));

if (!hadBrand) py(`
from mongo_client import db
print(db.ai_brand_profiles.delete_many({'business_id': ${JSON.stringify(bid)}}).deleted_count)`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
