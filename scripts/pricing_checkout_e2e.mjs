// pricing_checkout_e2e.mjs — bảng giá THEO NGÀNH (plans.py), USD/AUD (Mỹ + Úc), tháng/năm trên landing, /checkout tính giá ở server, trang pháp lý.
//   node scripts/pricing_checkout_e2e.mjs        (CHỈ server local; tự xoá yêu cầu đăng ký thử)
import { chromium, devices } from 'playwright';
import { execFileSync } from 'child_process';

const BASE = process.env.BASE || 'http://127.0.0.1:5001';
const steps = [];
const rec = (n, ok, note = '') => { steps.push({ n, ok }); console.log(`${ok ? '✅' : '❌'} ${n}${note ? ' — ' + note : ''}`); };
const py = (code) => execFileSync('python', ['-c', code], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }).trim().split(/\r?\n/).pop();
const TAG = 'QA Pricing ' + Date.now();
const b = await chromium.launch({ channel: 'chrome' });

// 1) Landing: khách Mỹ -> USD, khách Úc (múi giờ Sydney) -> AUD; nút chuyển; link đăng ký mang theo tiền tệ
// trang chủ mặc định ngành Nails: Pro $129 (A$199), phí cài $499 (A$749)
for (const [label, opt, cur, price] of [['Mỹ', { timezoneId: 'America/Los_Angeles', locale: 'en-US' }, 'USD', '$129'],
                                         ['Úc', { timezoneId: 'Australia/Sydney', locale: 'en-AU' }, 'AUD', 'A$199']]) {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, ...opt });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(BASE + '/landing', { waitUntil: 'load' }); await p.waitForTimeout(800);
  const st = await p.evaluate(() => ({ cur: document.getElementById('bang-gia').dataset.currency,
    pro: document.querySelector('.bppr-card.hot .bppr-price b').textContent, href: document.querySelector('.bppr-card.hot .bppr-cta').getAttribute('href'),
    tax: document.querySelector('[data-tax]').textContent }));
  rec(`Landing — khách ${label} thấy ${cur}`, st.cur === cur && st.pro === price && st.href === `/checkout?plan=pro&industry=nail&currency=${cur}&billing=month` && st.tax.length > 5 && errs.length === 0, JSON.stringify(st));
  if (cur === 'USD') {
    const hot = () => p.evaluate(() => ({ pro: document.querySelector('.bppr-card.hot .bppr-price b').textContent, setup: document.querySelector('.bppr-card.hot .bppr-setup').textContent.replace(/\s+/g, ' ').trim(),
      href: document.querySelector('.bppr-card.hot .bppr-cta').getAttribute('href') }));
    // đổi ngành: Nhà hàng Pro $159; trả năm $133/tháng (làm tròn lên) và tổng năm = 10 tháng ($1,590), link mang billing=year
    await p.click('#bang-gia [data-ind="fnb"]');
    const fnb = await hot();
    rec('Landing — chọn ngành Nhà hàng: Pro $159, phí cài $799', fnb.pro === '$159' && /\$799/.test(fnb.setup) && fnb.href.includes('industry=fnb'), JSON.stringify(fnb));
    await p.click('#bang-gia [data-bill="year"]');
    const yr = await hot();
    rec('Landing — trả năm: $133/tháng, tổng năm $1,590 (= 10 tháng, khớp checkout)', yr.pro === '$133' && /\$1,590/.test(yr.setup) && yr.href.endsWith('billing=year'), JSON.stringify(yr));
    await p.click('#bang-gia [data-bill="month"]'); await p.click('#bang-gia [data-ind="nail"]');
    await p.click('#bang-gia [data-cur="AUD"]');
    const after = await p.evaluate(() => ({ pro: document.querySelector('.bppr-card.hot .bppr-price b').textContent, setup: document.querySelector('.bppr-card.hot .bppr-setup strong').textContent }));
    rec('Landing — bấm AUD đổi giá ngay', after.pro === 'A$199' && after.setup === 'A$749', JSON.stringify(after));
    await p.reload({ waitUntil: 'load' }); await p.waitForTimeout(500);
    rec('Landing — nhớ lựa chọn AUD khi tải lại', await p.evaluate(() => document.getElementById('bang-gia').dataset.currency) === 'AUD');
    const links = await p.evaluate(() => ['terms', 'privacy', 'payment-policy'].map((k) => !!document.querySelector(`footer a[href="/${k}"], a[href="/${k}"]`)));
    rec('Chân trang dẫn tới /terms, /privacy, /payment-policy', links.every(Boolean), JSON.stringify(links));
  }
  await ctx.close();
}

// 2) iPhone: bảng giá không tràn ngang, gói Pro lên đầu
{
  const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
  const ctx = await b.newContext({ ...iphone, timezoneId: 'Australia/Melbourne' });
  const p = await ctx.newPage();
  await p.goto(BASE + '/landing', { waitUntil: 'load' }); await p.waitForTimeout(800);
  await p.locator('#bang-gia').scrollIntoViewIfNeeded(); await p.waitForTimeout(600);
  const st = await p.evaluate(() => ({ ov: document.documentElement.scrollWidth - innerWidth, first: document.querySelector('#bang-gia .bppr-card').getBoundingClientRect().top > document.querySelector('#bang-gia .bppr-card.hot').getBoundingClientRect().top, cur: document.getElementById('bang-gia').dataset.currency }));
  rec('iPhone (Úc) — AUD, không tràn ngang, Pro hiện đầu tiên', st.ov <= 1 && st.first && st.cur === 'AUD', JSON.stringify(st));
  await ctx.close();
}

// 3) /checkout: Nails Pro AUD -> A$749 + A$199 = A$948; gửi yêu cầu; server lưu đúng giá
{
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, timezoneId: 'Australia/Sydney' });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(BASE + '/checkout?plan=pro&currency=AUD&industry=nail', { waitUntil: 'load' });
  const sum = await p.evaluate(() => ({ setup: sumSetup.textContent, m: sumMonthly.textContent, t: sumTotal.textContent, country: custCountry.value, ind: custIndustry.value }));
  rec('Checkout — Nails Pro AUD: A$749 + A$199 = A$948', sum.setup === 'A$749' && sum.m === 'A$199' && sum.t === 'A$948 AUD' && sum.country === 'AU' && sum.ind === 'nail', JSON.stringify(sum));
  // đổi ngành ngay trên form -> giá đổi theo ngành; trả năm -> kỳ đầu = 10 tháng
  await p.selectOption('#custIndustry', 'fnb');
  const fsum = await p.evaluate(() => ({ setup: sumSetup.textContent, m: sumMonthly.textContent, t: sumTotal.textContent }));
  rec('Checkout — đổi sang Nhà hàng: A$1,199 + A$239', fsum.setup === 'A$1,199' && fsum.m === 'A$239' && fsum.t === 'A$1,438 AUD', JSON.stringify(fsum));
  await p.click('[data-bill="year"]');
  const ysum = await p.evaluate(() => ({ m: sumMonthly.textContent, t: sumTotal.textContent }));
  rec('Checkout — trả năm: A$2,390 (10 tháng) + phí cài = A$3,589', ysum.m === 'A$2,390' && ysum.t === 'A$3,589 AUD', JSON.stringify(ysum));
  await p.click('[data-bill="month"]'); await p.selectOption('#custIndustry', 'nail');
  await p.click('#btnSubmit');
  rec('Checkout — thiếu thông tin thì báo lỗi, không gửi', (await p.textContent('#err')).length > 5);
  await p.fill('#custName', 'QA Owner'); await p.fill('#custShop', TAG); await p.fill('#custEmail', 'qa.pricing@bitpawdemo.com'); await p.fill('#custPhone', '+61 400 000 000');
  await p.click('#btnSubmit');
  rec('Checkout — chưa tick đồng ý Điều khoản thì không gửi', /Terms|Điều khoản/.test(await p.textContent('#err')));
  await p.check('#agree');
  const [resp] = await Promise.all([p.waitForResponse((r) => r.url().endsWith('/api/checkout/signup')), p.click('#btnSubmit')]);
  const body = await resp.json();
  await p.waitForSelector('#doneBox:not([hidden])', { timeout: 5000 }).catch(() => {});
  const done = await p.textContent('#doneText');
  rec('Checkout — gửi thành công, báo số yêu cầu + chưa trừ tiền', body.success && /Nothing has been charged|Chưa có khoản/.test(done) && errs.length === 0, done.slice(0, 120));
  const row = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps(db.saas_signups.find_one({'shop_name': '${TAG}'}, {'_id': 0, 'plan': 1, 'currency': 1, 'setup_fee': 1, 'monthly_fee': 1, 'total_price': 1, 'country': 1, 'industry': 1})))`));
  rec('DB — lưu đúng gói/tiền tệ/giá tính ở server', row && row.plan === 'pro' && row.currency === 'AUD' && row.setup_fee === 749 && row.monthly_fee === 199 && row.total_price === 948 && row.country === 'AU' && row.industry === 'nail', JSON.stringify(row));
  // trình duyệt gửi giá giả -> server bỏ qua; gói/tiền tệ lạ -> 400
  const forged = await p.evaluate(async (tag) => (await fetch('/api/checkout/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_name: 'QA', shop_name: tag + ' forged', email: 'qa.pricing@bitpawdemo.com', phone: '+1 555 000 0000', plan: 'empire', currency: 'USD', total_price: 1, setup_fee: 1 }) })).json(), TAG);
  rec('Gửi giá giả $1 -> server vẫn tính giá Empire Nails $1,499 + $249', forged.success && forged.data.setup_fee === 1499 && forged.data.monthly_fee === 249, JSON.stringify(forged.data));
  const yearly = await p.evaluate(async (tag) => (await fetch('/api/checkout/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_name: 'QA', shop_name: tag + ' yearly', email: 'qa.pricing@bitpawdemo.com', phone: '+1 555 000 0000', plan: 'pro', industry: 'office', currency: 'USD', billing: 'year' }) })).json(), TAG);
  const yrow = JSON.parse(py(`
import json
from mongo_client import db
print(json.dumps(db.saas_signups.find_one({'shop_name': '${TAG} yearly'}, {'_id': 0, 'billing': 1, 'total_price': 1, 'monthly_fee': 1, 'setup_fee': 1})))`));
  rec('Văn phòng Pro trả năm: server lưu $299 + 10×$89 = $1,189', yearly.success && yrow && yrow.billing === 'year' && yrow.monthly_fee === 89 && yrow.setup_fee === 299 && yrow.total_price === 1189, JSON.stringify(yrow));
  const bad = await p.evaluate(async () => (await fetch('/api/checkout/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_name: 'QA', shop_name: 'x', email: 'qa@x.com', phone: '+1 555 000 0000', plan: 'gold', currency: 'VND' }) })).status);
  rec('Gói/tiền tệ không hợp lệ -> 400', bad === 400);
  const sa = await p.evaluate(async () => (await fetch('/api/superadmin/saas_signups')).status);
  rec('Danh sách đăng ký super admin — người lạ không xem được', sa === 401 || sa === 302 || sa === 403 || sa === 200 && false, 'HTTP ' + sa);
  await ctx.close();
}

// 4) Trang pháp lý: EN + VI, đủ mục quan trọng Mỹ/Úc, đúng pháp nhân
for (const [path, must] of [['/terms', ['Bitpaw Technology LLC', 'Australian Consumer Law', 'TCPA', 'New South Wales', 'California']],
                            ['/privacy', ['Australian Privacy Principles', 'California', 'DeepSeek', 'face template', 'oaic.gov.au']],
                            ['/payment-policy', ['USD', 'AUD', 'GST', 'Square', 'PCI DSS']]]) {
  for (const lang of ['en', 'vi']) {
    const r = await fetch(`${BASE}${path}?lang=${lang}`); const t = await r.text();
    const miss = lang === 'en' ? must.filter((m) => !t.includes(m)) : (t.includes('Bitpaw Technology LLC') && t.includes('Có hiệu lực') ? [] : ['bản VI']);
    rec(`${path} (${lang}) — đủ nội dung`, r.status === 200 && miss.length === 0 && !/đang được cập nhật|being updated/.test(t), miss.join(', '));
  }
}

py(`
from mongo_client import db
print(db.saas_signups.delete_many({'shop_name': {'$regex': '^${TAG}'}}).deleted_count)`);
await b.close();
const fail = steps.filter((s) => !s.ok).length;
console.log(`\nTổng: ${steps.length - fail} PASS · ${fail} FAIL`);
process.exit(fail ? 1 : 0);
