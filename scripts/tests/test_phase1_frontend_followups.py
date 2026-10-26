# -*- coding: utf-8 -*-
"""Test OFFLINE cho các việc giao diện nối tiếp Phase 1 (26/10/2026):

  1) cskh_widget.js — trang đặt lịch của tiệm chưa có trợ lý chat (server trả ai_unavailable, ai_gateway.unavailable_reply):
     câu KHÔNG dùng AI theo ngôn ngữ của tiệm + SĐT tiệm, tin của khách vẫn tới tiệm qua /api/portal/messages (hội thoại đã có),
     nhân viên trả lời hiện ngay trong khung chat; hội thoại chưa có -> nói thật "chưa tới tiệm" + nút Gọi / Nhắn tin.
  2) ai_bot.html — tiêu đề + <title> "AI Inbox / Hộp thư AI"; hội thoại handoff_reason == ai_gateway.PLAN_PAUSED_REASON hiện
     "AI paused — plan" / "AI tạm dừng — gói" + link /plan.
  3) messaging_settings.html — nhãn loại tin birthday / loyalty; công tắc + ô cho birthday_enabled, birthday_days_before,
     loyalty_messages_enabled, loyalty_sms_enabled, review_cooldown_days (khớp messaging.DEFAULT_SETTINGS); câu nhắn lại cuộc gọi
     nhỡ đúng theo ngành (chỉ nail/spa/fnb/karaoke/hotel có link đặt chỗ).
  4) campaign_builder.html — giá trị kênh chữ thường sms/email/zalo/messenger + ghi chú khung 24 giờ (Messenger) / 48 giờ (Zalo).
  5) omnichannel_connect.html — không gọi /api/ai/nurture/test-connection / toggle-connection (đã 410), dẫn sang /inbox/channels.
  6) dashboard.html — danh sách cảnh báo đối soát escape transaction_id / details, nhãn "GD" dịch theo ngôn ngữ.
  7) scripts/messaging_e2e.mjs — kỳ vọng kênh chiến dịch 'sms' (chữ thường).

Không chạy Flask, KHÔNG import app.py / messaging.py / mongo_client thật (mongo_client nối thẳng DB PRODUCTION), không gọi API thật.
--browser: Chrome thật (Playwright của repo chính), mọi request do page.route trả lời (không máy chủ nào lắng nghe).

Chạy:  python scripts/tests/test_phase1_frontend_followups.py            # tĩnh + Jinja + node --check
       python scripts/tests/test_phase1_frontend_followups.py --browser  # thêm kiểm thử trên Chrome thật
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# stub TRƯỚC mọi import có thể kéo mongo_client thật / requests
sys.modules['mongo_client'] = types.SimpleNamespace(db=MagicMock(name='db'), next_mongo_id=lambda c: 1, MONGO_STATUS='CONNECTED')
sys.modules.setdefault('requests', MagicMock(name='requests'))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS = []
TEMPLATES = ('ai_bot.html', 'messaging_settings.html', 'campaign_builder.html', 'omnichannel_connect.html', 'dashboard.html')


def check(name, ok, note=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {note}' if note and not ok else ''))
    if not ok:
        FAILS.append(name)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()


def inline_scripts(html):
    """<script> inline (không src, không JSON), thay biểu thức Jinja bằng 0 để node --check được."""
    out = []
    for m in re.finditer(r'<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>', html, re.S):
        code = re.sub(r'\{\{.*?\}\}', '0', m.group(1), flags=re.S)
        code = re.sub(r'\{%.*?%\}|\{#.*?#\}', '', code, flags=re.S)
        out.append(code)
    return out


def node_check(name, code):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    r = subprocess.run(['node', '--check', f.name], capture_output=True, text=True, encoding='utf-8')
    os.unlink(f.name)
    check(f'node --check {name}', r.returncode == 0, r.stderr[-400:])


def jinja_env():
    from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
    loader = ChoiceLoader([DictLoader({'components/app_sidebar.html': '<nav id="app-sidebar"></nav>'}),
                           FileSystemLoader(os.path.join(ROOT, 'templates'))])
    return Environment(loader=loader, autoescape=select_autoescape(['html']), undefined=ChainableUndefined)


def render(tpl, lang='en', industry='nail', role='admin', **ctx):
    url_for = lambda endpoint, **kw: ('/static/' + kw['filename']) if endpoint == 'static' else '/' + endpoint  # noqa: E731
    base = dict(url_for=url_for, asset_v=lambda p: 'test', session={'role': role, 'business_id': 'biz1'},
                default_lang=lang, active_industry_code=industry, tenant_currency='AUD', tenant_country='AU',
                menu_i18n={}, sales_demo=False, is_vn_shop=(lang == 'vi'), copilot_enabled=True,
                profile={'has_profile': True, 'name': 'Lotus Nails'})
    base.update(ctx)
    return jinja_env().get_template(tpl).render(**base)


def default_settings():
    """messaging.DEFAULT_SETTINGS đọc bằng ast (không import messaging — nó nối mongo_client)."""
    tree = ast.parse(read('messaging.py'))
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == 'DEFAULT_SETTINGS' for t in n.targets):
            return ast.literal_eval(n.value)
    return {}


# ============================================================ 0. cú pháp
def test_syntax():
    node_check('static/js/cskh_widget.js', read('static/js/cskh_widget.js'))
    for tpl in TEMPLATES:
        for i, code in enumerate(inline_scripts(read('templates/' + tpl))):
            node_check(f'{tpl} script#{i}', code)
    for tpl in TEMPLATES:   # bản render thật (Jinja) cũng phải là JS hợp lệ
        for lang in ('en', 'vi'):
            try:
                html = render(tpl, lang=lang)
            except Exception as e:
                check(f'render {tpl} ({lang})', False, repr(e)[:300])
                continue
            for i, m in enumerate(re.finditer(r'<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>', html, re.S)):
                node_check(f'{tpl} rendered {lang} script#{i}', m.group(1))
    r = subprocess.run(['node', '--check', os.path.join(ROOT, 'scripts', 'messaging_e2e.mjs')], capture_output=True, text=True, encoding='utf-8')
    check('node --check scripts/messaging_e2e.mjs', r.returncode == 0, r.stderr[-300:])


# ============================================================ 1. widget: ai_unavailable
def test_widget_static():
    s = read('static/js/cskh_widget.js')
    gens = [m.start() for m in re.finditer(r'fetch\("/api/ai/studio/generate"', s)]
    check('widget: vẫn đúng 2 lời gọi /api/ai/studio/generate (server quyết định gói mỗi lượt)', len(gens) == 2, str(len(gens)))
    handled = re.findall(r"if \(resData\.ai_unavailable && CHAT_CONTEXT === 'customer_booking'\) \{\s*//[^\n]*\n\s*aiReply = await aiUnavailableReply\(resData, msgVal\);", s)
    check('widget: cả 2 lượt chat (đầu + sau) xử lý ai_unavailable TRƯỚC paused/choices', len(handled) == 2, str(len(handled)))
    check('widget: giữ hội thoại qua /api/portal/messages (GET kiểm tra + POST sender_type customer)',
          'fetch("/api/portal/messages?customer_id=" + encodeURIComponent(customerId))' in s
          and 'JSON.stringify({ customer_id: customerId, content: msg, sender_type: "customer" })' in s)
    check('widget: nút Gọi / Nhắn tin dựng bằng DOM (textContent), href tel:/sms: chỉ chữ số và +',
          '["tel:", BT.call, "fa-phone"], ["sms:", BT.text, "fa-comment-sms"]' in s and 'replace(/[^0-9+]/g, "")' in s
          and 'document.createTextNode(label)' in s)
    block =s[s.index('const BT = BOOKING_VI'):s.index('const dna = CHAT_CONTEXT')]
    for key in ('offSubtitle', 'offSaved', 'offNoThread', 'offSent', 'offNotSent', 'call', 'text'):
        check(f'widget: chuỗi {key} có cả VI và EN', len(re.findall(r'\b' + key + r':', block)) == 2)
    off = '\n'.join(l for l in block.splitlines() if re.search(r'\boff[A-Z]\w*:', l))
    check('widget: câu dự phòng không nhắc "AI", không phải lỗi chung', not re.search(r'\bAI\b|error|lỗi', off), off[:300])


# ============================================================ 2. ai_bot.html
def test_ai_bot_static():
    import ai_gateway
    s = read('templates/ai_bot.html')
    m = re.search(r"const PLAN_PAUSED_REASON = '([^']*)';", s)
    check('ai_bot: PLAN_PAUSED_REASON trong trang == ai_gateway.PLAN_PAUSED_REASON', bool(m) and m.group(1) == ai_gateway.PLAN_PAUSED_REASON,
          m.group(1) if m else 'không thấy hằng số')
    for lang, title in (('en', 'AI Inbox | BitPaw'), ('vi', 'Hộp thư AI | BitPaw')):
        html = render('ai_bot.html', lang=lang)
        t = re.search(r'<title>(.*?)</title>', html, re.S)
        check(f'ai_bot ({lang}): <title> = "{title}"', bool(t) and t.group(1).strip() == title, t.group(1) if t else '')
        h = re.search(r'<span id="inboxTitle"[^>]*>(.*?)</span>', html, re.S)
        check(f'ai_bot ({lang}): tiêu đề trang là Hộp thư AI', bool(h) and h.group(1).strip() == ('AI Inbox' if lang == 'en' else 'Hộp thư AI'))
        check(f'ai_bot ({lang}): không còn "Command Center" / "Dispatch Assistant"', 'Command Center' not in html and 'Dispatch Assistant' not in html)
        check(f'ai_bot ({lang}): khung Copilot vẫn còn', 'id="copilotPanel"' in html and 'id="cpTopicsData"' in html)
    for k in ('pageTitle', 'inboxTitle', 'inboxSubtitle', 'planPaused', 'planPausedHint', 'seePlans'):
        check(f'ai_bot: chuỗi {k} có cả VI và EN', len(re.findall(r'\b' + k + r':', s)) == 2)
    check('ai_bot: link xem gói = /plan?feature=ai_inbox', 'href="/plan?feature=ai_inbox"' in s)


# ============================================================ 3. messaging_settings.html
NEW_KEYS = {'birthday_enabled': 'bdOn', 'birthday_days_before': 'bdDays', 'loyalty_messages_enabled': 'loyOn',
            'loyalty_sms_enabled': 'loySms', 'review_cooldown_days': 'revCool'}


def test_messaging_settings_static():
    d = default_settings()
    check('messaging.DEFAULT_SETTINGS có đủ 5 khoá mới', all(k in d for k in NEW_KEYS), str(sorted(d))[:300])
    s = read('templates/messaging_settings.html')
    for k, el in NEW_KEYS.items():
        check(f'settings: {k} được đọc (fill) và gửi lên (body)', f's.{k}' in s and f'{k}:' in s and f"id=\"{el}\"" in s)
    check('settings: nhãn loại tin birthday + loyalty (VI/EN)',
          "birthday: T('Birthday', 'Sinh nhật')" in s and "loyalty: T('Rewards', 'Điểm thưởng')" in s)
    check('settings: ô review_cooldown_days giới hạn 7..365 như messaging.save_settings', 'min="7" max="365"' in s)
    check('settings: SMS báo điểm nói rõ mỗi tin tốn tiền (VI + EN)', 'Each SMS costs money' in s and 'Mỗi tin SMS đều tốn tiền' in s)
    check('settings: không còn câu cứng "60 days"/"60 ngày"', 'every 60 days' not in s and '1 lần / 60 ngày' not in s)
    for ind in ('nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'office', 'production', 'technical', ''):
        for lang in ('en', 'vi'):
            html = render('messaging_settings.html', lang=lang, industry=ind)
            p = re.search(r'<p id="mcDesc"[^>]*>(.*?)</p>', html, re.S)
            txt = p.group(1) if p else ''
            has_link = ind in ('nail', 'spa', 'fnb', 'karaoke', 'hotel')
            if lang == 'en':
                ok = (('online booking link' in txt or 'online table reservation link' in txt or 'online room booking link' in txt) if has_link
                      else ('reply or call back' in txt and 'link' not in txt))
            else:
                ok = ((' kèm link đặt' in txt) if has_link else ('trả lời tin hoặc gọi lại' in txt and 'link' not in txt))
            check(f'settings: cuộc gọi nhỡ ngành "{ind or "?"}" ({lang}) {"có link đặt chỗ" if has_link else "chỉ mời trả lời / gọi lại"}', ok, txt[:200])
    html = render('messaging_settings.html', lang='en', industry='fnb')
    check('settings: nhà hàng -> "table reservation link"', 'online table reservation link' in html)


# ============================================================ 4. campaign_builder.html
def test_campaign_builder_static():
    s = read('templates/campaign_builder.html')
    sel = re.search(r'<select id="campChannel"[^>]*>(.*?)</select>', s, re.S)
    vals = re.findall(r'<option value="([^"]+)"', sel.group(1)) if sel else []
    check('campaign: kênh chữ thường sms/email/zalo/messenger (= messaging.CHANNELS)', vals == ['sms', 'email', 'zalo', 'messenger'], str(vals))
    check('campaign: không còn giá trị SMS/EMAIL/ZALO/FACEBOOK', not re.search(r'value="(SMS|EMAIL|ZALO|FACEBOOK)"', s))
    notes = re.findall(r"campaignbuilder_channel_note: (['\"])(.*?)\1,", s)
    check('campaign: ghi chú khung trả lời có cả VI và EN', len(notes) == 2)
    for _q, n in notes:
        check('campaign: ghi chú nêu Messenger 24 giờ + Zalo 48 giờ + SMS/email', ('24' in n and '48' in n and 'SMS' in n and 'email' in n), n[:120])


# ============================================================ 5. omnichannel_connect.html
def test_omnichannel_static():
    s = read('templates/omnichannel_connect.html')
    code = '\n'.join(inline_scripts(s))
    code = re.sub(r'//[^\n]*', '', code)
    check('omni: không còn gọi /api/ai/nurture/test-connection', 'test-connection' not in code)
    check('omni: không còn gọi /api/ai/nurture/toggle-connection', 'toggle-connection' not in code)
    check('omni: có link /inbox/channels', 'href="/inbox/channels"' in s and "window.location.href = '/inbox/channels'" in s)
    for k in ('omni_moved_note', 'omni_moved_link', 'omni_log_moved'):
        check(f'omni: khoá {k} có cả VI và EN', len(re.findall(r'^\s*' + k + r':', s, re.M)) == 2)


# ============================================================ 6. dashboard.html
def test_dashboard_static():
    s = read('templates/dashboard.html')
    fn = s[s.index('async function loadReconciliationAlerts()'):s.index('// CSKH CHAT')]
    check('dashboard: transaction_id được escape', '__escHtml(a.transaction_id)' in fn)
    check('dashboard: details được escape', "__escHtml(a.details || '')" in fn)
    check('dashboard: không còn nhãn cứng "GD"', not re.search(r'\bGD\b', fn))
    check('dashboard: nhãn giao dịch có cả VI và EN', "dashboard_txn_label: 'Giao dịch'" in s and "dashboard_txn_label: 'Transaction'" in s)


# ============================================================ 7. messaging_e2e.mjs
def test_messaging_e2e_expectation():
    s = read('scripts/messaging_e2e.mjs')
    check("messaging_e2e: kỳ vọng camp.channel === 'sms'", "camp.channel === 'sms'" in s and "camp.channel === 'SMS'" not in s)


# ============================================================ 8. --browser
def find_playwright():
    d = ROOT
    for _ in range(6):
        p = os.path.join(d, 'node_modules', 'playwright')
        if os.path.isdir(p):
            return p
        d = os.path.dirname(d)
    return None


WIDGET_PAGE = '''<!DOCTYPE html><html lang="%(lang)s"><head><meta charset="utf-8"><title>t</title></head><body>
<h1>booking</h1><script>%(globals)s</script><script src="/static/js/cskh_widget.js"></script></body></html>'''

NODE_BROWSER = r'''
const { chromium } = require(process.env.PW_PATH);
const fs = require('fs'), path = require('path');
const STATIC = process.env.STATIC_DIR, PAGES = JSON.parse(fs.readFileSync(process.env.PAGES_FILE, 'utf8'));
const PLAN_PAUSED_REASON = process.env.PLAN_PAUSED_REASON;
const BASE = 'https://p1.test';
const out = []; const ok = (name, cond, note) => out.push({ name, ok: !!cond, note: note || '' });
let S;
const reset = (o) => { S = Object.assign({ gen: [], portalGet: [], portalPost: [], other: [], threads: {}, unavailable: true, contact: { name: 'Lotus Nails', phone: '+61 2 9000 0001' },
                                           posted: [], settingsPost: null, campaignPost: null, retired: [], streamEvent: false }, o || {}); };
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
  const run = async (label, fn, opts) => {
    const ctx = await browser.newContext(Object.assign({ viewport: { width: 390, height: 844 } }, (opts && opts.ctx) || {}));
    if (opts && opts.init) await ctx.addInitScript(opts.init);
    const page = await ctx.newPage();
    const errs = []; page.on('pageerror', (e) => errs.push(e.message));
    page.on('dialog', (d) => d.accept());
    await ctx.route('**/*', async (route) => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname, m = req.method();
      if (url.host !== 'p1.test') return route.abort();
      const json = (o, st) => route.fulfill({ status: st || 200, contentType: 'application/json', body: JSON.stringify(o) });
      if (PAGES[p]) return route.fulfill({ status: 200, contentType: 'text/html', body: PAGES[p] });
      if (p.startsWith('/static/')) { const f = path.join(STATIC, p.slice(8)); return fs.existsSync(f) ? route.fulfill({ path: f }) : route.fulfill({ status: 404, body: '' }); }
      if (p.includes('test-connection') || p.includes('toggle-connection')) { S.retired.push(p); return json({ success: false }, 410); }
      if (p === '/api/ai/studio/generate') {
        S.gen.push(req.postDataJSON());
        if (!S.unavailable) return json({ choices: [{ message: { content: 'Sure — what time works for you?' } }] });
        return json({ ai_unavailable: true, reason: 'plan', lang: 'en', contact: S.contact,
                      choices: [{ message: { role: 'assistant', content: "Online chat isn't available for Lotus Nails. You can still book with the form on this page." } }] });
      }
      if (p === '/api/portal/messages' && m === 'GET') {
        const cid = url.searchParams.get('customer_id'); S.portalGet.push(cid);
        const t = S.threads[cid];
        if (!t) return json({ success: false, message: 'not found' }, 404);
        return json({ success: true, data: t, shop_name: 'Lotus Nails' });
      }
      if (p === '/api/portal/messages' && m === 'POST') {
        const b = req.postDataJSON(); S.portalPost.push(b);
        const t = S.threads[b.customer_id];
        if (!t) return json({ success: false, message: 'not found' }, 404);
        t.push({ sender_type: 'customer', content: b.content, created_at: '2026-10-26T10:00:00' });
        return json({ success: true });
      }
      if (p === '/api/portal/stream') {
        if (!S.streamEvent) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 250\n\n' });
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 250\ndata: change\n\n' });
      }
      // ---- trang quản trị
      if (p === '/api/bot/customers') return json({ success: true, data: S.customers || [] });
      if (p === '/api/bot/messages') return json({ success: true, data: [] });
      if (p === '/api/messaging/settings' && m === 'GET') return json({ success: true, settings: S.settings });
      if (p === '/api/messaging/settings' && m === 'POST') { S.settingsPost = req.postDataJSON(); return json({ success: true, settings: Object.assign({}, S.settings, S.settingsPost) }); }
      if (p === '/api/messaging/log') return json({ success: true, stats: { sent: 2, queued: 0 }, optouts: 0, items: S.log || [] });
      if (p === '/api/ai/nurture/approval-queue') return json({ success: true, data: [] });
      if (p === '/api/ai/campaigns/summary') return json({ success: true, data: [] });
      if (p === '/api/ai/nurture/generate-campaign') { S.campaignPost = req.postDataJSON(); return json({ success: true, campaign_name: 'x', target_count: 1, messages_count: 3 }); }
      if (p === '/omnichannel/status') return json({ success: true, data: { messenger: { status: 'DISCONNECTED', last_sync: '', leads_count: 0 }, zalo_oa: { status: 'DISCONNECTED', last_sync: '', leads_count: 0 } } });
      if (p === '/inbox/channels') return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>channels</title><h1 id="ch">Messaging channels</h1>' });
      if (p === '/api/dashboard/reconciliation_alerts') return json({ success: true, data: S.alerts || [] });
      if (p.startsWith('/api/stream') || p.includes('stream')) return route.fulfill({ status: 204, body: '' });
      S.other.push(m + ' ' + p);
      return json({ success: true, data: [] });
    });
    try { await fn(page, ctx, errs); } catch (e) { ok(label + ': crashed', false, String(e && e.stack || e).slice(0, 600)); }
    finally { if (!(opts && opts.ignoreErrors)) ok('không lỗi JS (' + label + ')', errs.length === 0, errs.join(' | ')); await ctx.close(); }
  };
  const chat = async (page, phone, msgs) => {
    await page.click('#mascot-toggle-btn');
    await page.fill('#chatPhone', phone);
    for (const msg of msgs) {
      const n = S.gen.length;
      await page.waitForFunction(() => !document.getElementById('chatMsg').disabled);
      await page.fill('#chatMsg', msg);
      await page.click('#chatSendBtn');
      for (let i = 0; i < 50 && S.gen.length === n; i++) await page.waitForTimeout(100);
      await page.waitForTimeout(1300);
    }
  };
  const box = (page) => page.textContent('#chat-messages-container');
  const aiBubbles = (page) => page.$$eval('#chat-messages-container .chat-ai', (els) => els.map((e) => e.textContent.trim()));

  // ---- W1. EN, hội thoại đã có: tin tới tiệm qua portal, câu không AI + SĐT, nút Gọi/Nhắn tin, nhân viên trả lời hiện ra
  reset({ threads: { 'biz1:0412345678': [{ sender_type: 'customer', content: 'Hi', created_at: '2026-10-20T10:00:00' }, { sender_type: 'staff', content: 'Hello!', created_at: '2026-10-20T10:01:00' }] } });
  await run('W1 booking EN thread', async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chat(page, '0412345678', ['Can I book a gel manicure tomorrow?']);
    const posts = S.portalPost;
    ok('W1. tin của khách tới tiệm qua POST /api/portal/messages (đúng hội thoại, đúng chữ, customer)',
       posts.length === 1 && posts[0].customer_id === 'biz1:0412345678' && posts[0].content === 'Can I book a gel manicure tomorrow?' && posts[0].sender_type === 'customer', JSON.stringify(posts));
    const bubbles = await aiBubbles(page);
    const last = bubbles[bubbles.length - 1] || '';
    ok('W1. câu thân thiện: đã chuyển tới nhân viên tiệm + SĐT tiệm', /passed to the team at Lotus Nails/.test(last) && /\+61 2 9000 0001/.test(last), last);
    ok('W1. không nhắc AI, không lỗi chung', !/\bAI\b|error|slow/i.test(last), last);
    const links = await page.$$eval('#chat-messages-container [data-bp-contact] a', (as) => as.map((a) => [a.getAttribute('href'), a.textContent.trim()]));
    ok('W1. nút Gọi (tel:) + Nhắn tin (sms:) đúng số', JSON.stringify(links) === JSON.stringify([['tel:+61290000001', 'Call'], ['sms:+61290000001', 'Text']]), JSON.stringify(links));
    const sub = await page.$eval('#chatWidget .font-bold.text-sm', (h) => h.nextElementSibling.textContent.trim());
    ok('W1. phụ đề không còn "Online 24/7" -> "Messages go to the team"', sub === 'Messages go to the team', sub);
    // lượt 2: vẫn gửi qua server (server quyết gói), tin tới tiệm, chỉ 1 dòng nhỏ "Sent to the team ✓", không lặp nút
    await chat2(page, 'Also a gel removal please');
    ok('W1. lượt 2: vẫn hỏi server (/api/ai/studio/generate) rồi gửi tin vào hội thoại', S.gen.length === 2 && S.portalPost.length === 2 && S.portalPost[1].content === 'Also a gel removal please', JSON.stringify(S.portalPost));
    const notes = await page.$$eval('[data-bp-note]', (els) => els.map((e) => [e.dataset.bpNote, e.textContent]));
    ok('W1. lượt 2: dòng "Sent to the team ✓" thay vì lặp lại cả câu', JSON.stringify(notes) === JSON.stringify([['ok', 'Sent to the team ✓']]), JSON.stringify(notes));
    ok('W1. nút Gọi/Nhắn tin chỉ hiện 1 lần', (await page.$$('[data-bp-contact]')).length === 1);
    ok('W1. câu dài chỉ hiện 1 lần', (await aiBubbles(page)).filter((b) => /passed to the team/.test(b)).length === 1);
    // nhân viên trả lời trong Hộp thư AI -> hiện trong khung chat của khách
    S.threads['biz1:0412345678'].push({ sender_type: 'staff', content: 'See you tomorrow at 3pm!', created_at: '2026-10-26T10:05:00' });
    S.streamEvent = true;
    await page.waitForFunction(() => /See you tomorrow at 3pm!/.test(document.getElementById('chat-messages-container').textContent), null, { timeout: 8000 }).catch(() => {});
    const shop = await page.$$eval('#chat-messages-container .chat-shop', (els) => els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()));
    ok('W1. trả lời của nhân viên hiện ngay trong khung chat (nhãn nhân viên tiệm)', shop.some((t) => /Salon staff/.test(t) && /See you tomorrow at 3pm!/.test(t)), JSON.stringify(shop));
    ok('W1. trả lời cũ của nhân viên (trước khi khách mở chat) không bị hiện lại', !shop.some((t) => /Hello!/.test(t)), JSON.stringify(shop));
  });
  async function chat2(page, msg) {
    const n = S.gen.length;
    await page.fill('#chatMsg', msg);
    await page.click('#chatSendBtn');
    for (let i = 0; i < 50 && S.gen.length === n; i++) await page.waitForTimeout(100);
    await page.waitForTimeout(1300);
  }

  // ---- W2. hội thoại CHƯA có (server chưa lưu lượt nào): nói thật là chưa tới tiệm + nút Gọi/Nhắn tin
  reset();
  await run('W2 booking EN no thread', async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chat(page, '0499999999', ['Do you do pedicures?']);
    const bubbles = await aiBubbles(page);
    const last = bubbles[bubbles.length - 1] || '';
    ok('W2. nói thật: tin CHƯA tới tiệm, mời gọi / nhắn số tiệm hoặc dùng form', /wasn't delivered/.test(last) && /call or text \+61 2 9000 0001/.test(last) && /form on this page/.test(last), last);
    ok('W2. không hứa "the team will reply"', !/will reply|reply in this chat/.test(last), last);
    ok('W2. không POST vào hội thoại không tồn tại', S.portalPost.length === 0, JSON.stringify(S.portalPost));
    ok('W2. có nút Gọi/Nhắn tin', (await page.$$('[data-bp-contact] a')).length === 2);
    await chat2(page, 'Hello?');
    const notes = await page.$$eval('[data-bp-note]', (els) => els.map((e) => [e.dataset.bpNote, e.textContent]));
    ok('W2. lượt 2: dòng "Not delivered — please call or text …"', notes.length === 1 && notes[0][0] === 'fail' && /Not delivered — please call or text \+61 2 9000 0001/.test(notes[0][1]), JSON.stringify(notes));
  });

  // ---- W3. trang tiếng Việt (ngôn ngữ của tiệm), hội thoại đã có
  reset({ threads: { 'biz1:0912345678': [] } });
  await run('W3 booking VI', async (page) => {
    await page.goto(BASE + '/booking_vi', { waitUntil: 'load' });
    await chat(page, '0912345678', ['Cho mình đặt lịch chiều mai']);
    const bubbles = await aiBubbles(page);
    const last = bubbles[bubbles.length - 1] || '';
    ok('W3. câu tiếng Việt: đã chuyển tới nhân viên + SĐT tiệm', /Tin nhắn đã được chuyển tới nhân viên Lotus Nails/.test(last) && /\+61 2 9000 0001/.test(last), last);
    const labels = await page.$$eval('[data-bp-contact] a', (as) => as.map((a) => a.textContent.trim()));
    ok('W3. nút "Gọi" / "Nhắn tin"', JSON.stringify(labels) === JSON.stringify(['Gọi', 'Nhắn tin']), JSON.stringify(labels));
    const sub = await page.$eval('#chatWidget .font-bold.text-sm', (h) => h.nextElementSibling.textContent.trim());
    ok('W3. phụ đề tiếng Việt', sub === 'Tin nhắn chuyển tới nhân viên tiệm', sub);
  });

  // ---- W4. server đã tự lưu lượt này (tương lai): không POST trùng
  reset({ threads: { 'biz1:0412345678': [{ sender_type: 'customer', content: 'Are you open Sunday?', created_at: '2026-10-26T10:00:00' }] } });
  await run('W4 already stored', async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chat(page, '0412345678', ['Are you open Sunday?']);
    ok('W4. lượt đã có trong hội thoại -> không POST lần 2', S.portalPost.length === 0, JSON.stringify(S.portalPost));
    ok('W4. vẫn báo đã chuyển tới nhân viên', /passed to the team/.test((await aiBubbles(page)).slice(-1)[0] || ''));
  });

  // ---- W5. tiệm chưa có SĐT: không nút, câu không hứa số
  reset({ contact: { name: null, phone: null }, threads: { 'biz1:0412345678': [] } });
  await run('W5 no phone', async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chat(page, '0412345678', ['Hi']);
    const last = (await aiBubbles(page)).slice(-1)[0] || '';
    ok('W5. không SĐT: không nút Gọi/Nhắn tin', (await page.$$('[data-bp-contact]')).length === 0);
    ok('W5. không SĐT: câu vẫn thân thiện, không "call / text"', /passed to the team at Lotus Nails/.test(last) && !/call|text \+/.test(last), last);
  });

  // ---- W6. tiệm có trợ lý (Pro): luồng AI cũ không đổi, không đụng portal POST
  reset({ unavailable: false, threads: { 'biz1:0412345678': [] } });
  await run('W6 AI on', async (page) => {
    await page.goto(BASE + '/booking', { waitUntil: 'load' });
    await chat(page, '0412345678', ['Book me in']);
    ok('W6. AI bật: câu trả lời của AI hiện như cũ', /what time works for you/.test(await box(page)));
    ok('W6. AI bật: không POST portal, không nút gọi', S.portalPost.length === 0 && (await page.$$('[data-bp-contact]')).length === 0);
  });

  // ---- A. ai_bot.html: Hộp thư AI + "AI paused — plan"
  const customers = [
    { id: 'biz1:+61400000001', full_name: 'Plan Paused', channel: 'sms', last_message: 'can I book?', needs_human: true, handoff_reason: PLAN_PAUSED_REASON },
    { id: 'biz1:+61400000002', full_name: 'Wants Manager', channel: 'web', last_message: 'manager pls', needs_human: true, handoff_reason: 'Gel lifted — wants the manager' },
    { id: 'biz1:+61400000003', full_name: 'Replied Already', channel: 'web', last_message: 'thanks', needs_human: false, handoff_reason: PLAN_PAUSED_REASON },
  ];
  for (const lang of ['en', 'vi']) {
    reset({ customers });
    await run('A ai_bot ' + lang, async (page) => {
      await page.goto(BASE + '/ai_bot_' + lang, { waitUntil: 'load' });
      await page.waitForSelector('.customer-item');
      await page.waitForTimeout(300);
      const title = await page.title();
      ok(`A(${lang}). <title> Hộp thư AI`, title === (lang === 'en' ? 'AI Inbox | BitPaw' : 'Hộp thư AI | BitPaw'), title);
      ok(`A(${lang}). tiêu đề trang`, (await page.textContent('#inboxTitle')).trim() === (lang === 'en' ? 'AI Inbox' : 'Hộp thư AI'));
      const items = await page.$$eval('.customer-item', (els) => els.map((e) => ({ t: e.textContent.replace(/\s+/g, ' ').trim(),
        paused: !!e.querySelector('[data-plan-paused]'), link: (e.querySelector('[data-plan-link]') || {}).href || '' })));
      const pp = items.find((i) => /Plan Paused/.test(i.t)) || {};
      ok(`A(${lang}). hội thoại dừng vì gói: nhãn ${lang === 'en' ? '"AI paused — plan"' : '"AI tạm dừng — gói"'}`,
         pp.paused && pp.t.includes(lang === 'en' ? 'AI paused — plan' : 'AI tạm dừng — gói'), pp.t);
      ok(`A(${lang}). có link /plan?feature=ai_inbox`, /\/plan\?feature=ai_inbox$/.test(pp.link), pp.link);
      ok(`A(${lang}). không hiện chuỗi lý do tiếng Anh thô của server`, !pp.t.includes('AI replies are included in Pro'), pp.t);
      const wm = items.find((i) => /Wants Manager/.test(i.t)) || {};
      ok(`A(${lang}). lý do chuyển người khác giữ nguyên ("Needs reply" + lý do)`, !wm.paused && /Needs reply/.test(wm.t) && /Gel lifted/.test(wm.t), wm.t);
      const ra = items.find((i) => /Replied Already/.test(i.t)) || {};
      ok(`A(${lang}). đã trả lời (needs_human=false) -> không nhãn gói`, !ra.paused && !/paused|tạm dừng/.test(ra.t), ra.t);
      await page.click('[data-plan-link]');
      await page.waitForTimeout(500);
      ok(`A(${lang}). bấm link -> sang /plan`, /\/plan\?feature=ai_inbox$/.test(page.url()), page.url());
    }, { ignoreErrors: false, init: lang === 'vi' ? () => { try { localStorage.setItem('bitpaw_lang', 'vi'); } catch (e) {} } : null });
  }

  // ---- B. messaging_settings.html
  reset({ settings: { twilio_account_sid: 'AC1', twilio_from: '+61255501234', sms_enabled: true, twilio_ready: true, reminders_enabled: true, reminder_hours: 24,
                      reviews_enabled: true, google_review_url: 'https://g.page/r/x/review', review_delay_minutes: 90, review_cooldown_days: 45,
                      birthday_enabled: true, birthday_days_before: 3, loyalty_messages_enabled: true, loyalty_sms_enabled: true,
                      missed_call_enabled: false, shop_phone: '', owner_report_enabled: true, owner_report_email: '', timezone: 'Australia/Sydney',
                      send_window_start: 9, send_window_end: 20, language: 'en', webhook_sms: 'https://x/sms', webhook_voice: 'https://x/voice' },
          log: [{ kind: 'birthday', channel: 'sms', to: '+61400000001', status: 'sent', created_at: '2026-10-26T09:00:00' },
                { kind: 'loyalty', channel: 'email', to: 'ann@example.com', status: 'queued', created_at: '2026-10-26T09:01:00' }] });
  await run('B messaging_settings', async (page) => {
    await page.goto(BASE + '/settings_messaging', { waitUntil: 'load' });
    await page.waitForFunction(() => document.getElementById('revCool').value === '45');
    await page.waitForTimeout(300);
    const st = await page.evaluate(() => ({ bd: document.getElementById('bdOn').checked, days: document.getElementById('bdDays').value,
      loy: document.getElementById('loyOn').checked, sms: document.getElementById('loySms').checked, cool: document.getElementById('revCool').value,
      coolTxt: document.getElementById('revCoolTxt').textContent }));
    ok('B. cài đặt mới hiện đúng giá trị đã lưu', st.bd && st.days === '3' && st.loy && st.sms && st.cool === '45' && st.coolTxt === '45', JSON.stringify(st));
    const log = await page.textContent('#logBody');
    ok('B. nhật ký: nhãn "Birthday" + "Rewards" (không còn khoá thô)', /Birthday/.test(log) && /Rewards/.test(log) && !/\bbirthday\b|\bloyalty\b/.test(log), log);
    await page.fill('#revCool', '30');
    ok('B. đổi số ngày -> câu mô tả cập nhật', (await page.textContent('#revCoolTxt')) === '30');
    await page.selectOption('#bdDays', '0');
    await page.click('#loyOn');
    ok('B. tắt báo điểm -> ô SMS báo điểm bị khoá', await page.$eval('#loySms', (e) => e.disabled));
    await page.click('#saveBtn');
    await page.waitForTimeout(600);
    const b = S.settingsPost || {};
    ok('B. lưu: gửi đủ 5 khoá mới đúng kiểu',
       b.review_cooldown_days === 30 && b.birthday_enabled === true && b.birthday_days_before === 0 && b.loyalty_messages_enabled === false && b.loyalty_sms_enabled === false,
       JSON.stringify(b));
    await page.fill('#revCool', '3');
    S.settingsPost = null;
    await page.click('#saveBtn');
    await page.waitForTimeout(400);
    ok('B. số ngày hỏi lại < 7 -> báo lỗi, không lưu', S.settingsPost === null && /7/.test(await page.textContent('#saveNote')), await page.textContent('#saveNote'));
  });

  // ---- C. campaign_builder.html
  reset();
  await run('C campaign_builder', async (page) => {
    await page.goto(BASE + '/campaign_builder', { waitUntil: 'load' });
    ok('C. kênh mặc định sms', (await page.$eval('#campChannel', (e) => e.value)) === 'sms');
    ok('C. ghi chú khung 24 giờ / 48 giờ hiện trên trang', /24 hours/.test(await page.textContent('#campChannelNote')) && /48 hours/.test(await page.textContent('#campChannelNote')));
    await page.selectOption('#campChannel', 'messenger');
    await page.click('#btn-generate');
    await page.waitForTimeout(800);
    ok('C. tạo chiến dịch gửi channel "messenger" (chữ thường)', S.campaignPost && S.campaignPost.channel === 'messenger', JSON.stringify(S.campaignPost));
  });

  // ---- D. omnichannel_connect.html
  reset();
  await run('D omnichannel', async (page) => {
    await page.goto(BASE + '/omnichannel_connect', { waitUntil: 'load' });
    await page.waitForTimeout(500);
    ok('D. có link sang /inbox/channels', await page.$eval('#omniMovedNote a', (a) => a.getAttribute('href')) === '/inbox/channels');
    const btn = await page.$('button[onclick^="openManualConfig"]');
    ok('D. nút cấu hình thủ công có trên trang', !!btn);
    if (btn) { await btn.click(); await page.waitForURL('**/inbox/channels', { timeout: 5000 }).catch(() => {}); }
    ok('D. bấm cấu hình thủ công -> sang Kênh nhắn tin', /\/inbox\/channels$/.test(page.url()), page.url());
    await page.goto(BASE + '/omnichannel_connect', { waitUntil: 'load' });
    await page.evaluate(() => { document.getElementById('config-platform').value = 'zalo_oa'; saveChannelConfig(new Event('submit')); });
    await page.waitForURL('**/inbox/channels', { timeout: 5000 }).catch(() => {});
    ok('D. lưu cấu hình cũ -> sang Kênh nhắn tin', /\/inbox\/channels$/.test(page.url()), page.url());
    await page.goto(BASE + '/omnichannel_connect', { waitUntil: 'load' });
    await page.evaluate(() => { document.getElementById('config-platform').value = 'messenger'; testChannelConfig(); });
    await page.waitForURL('**/inbox/channels', { timeout: 5000 }).catch(() => {});
    ok('D. 0 request tới test-connection / toggle-connection (đã 410)', S.retired.length === 0, JSON.stringify(S.retired));
  }, { ignoreErrors: true });

  // ---- E. dashboard.html: cảnh báo đối soát escape + nhãn dịch
  for (const lang of ['en', 'vi']) {
    reset({ alerts: [{ id: '7"><img src=x onerror="window.__xid=1">', issue_type: 'missing_order',
                       transaction_id: '<img src=x onerror="window.__xss=1">TXN-9', details: 'Paid 12.00 AUD <img src=x onerror="window.__xss2=1"> no order' }] });
    await run('E dashboard ' + lang, async (page) => {
      await page.goto(BASE + '/dashboard', { waitUntil: 'load' });
      await page.waitForFunction(() => document.querySelectorAll('#reconciliationAlertsList > div').length > 0, null, { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(500);
      const flags = await page.evaluate(() => [window.__xss, window.__xss2, window.__xid]);
      ok(`E(${lang}). transaction_id / details / id không chạy script`, flags.every((f) => f === undefined), JSON.stringify(flags));
      const txt = await page.textContent('#reconciliationAlertsList');
      ok(`E(${lang}). nội dung hiện dạng chữ`, /<img src=x onerror="window.__xss=1">TXN-9/.test(txt) && /Paid 12.00 AUD/.test(txt), txt.slice(0, 200));
      ok(`E(${lang}). nhãn giao dịch đúng ngôn ngữ, không còn "GD"`, txt.includes(lang === 'en' ? '— Transaction ' : '— Giao dịch ') && !/\bGD\b/.test(txt), txt.slice(0, 200));
    }, { ignoreErrors: true, init: lang === 'vi' ? () => { try { localStorage.setItem('bitpaw_lang', 'vi'); } catch (e) {} } : () => { try { localStorage.setItem('bitpaw_lang', 'en'); } catch (e) {} } });
  }

  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { out.push({ name: 'browser test crashed', ok: false, note: String(e && e.stack || e).slice(0, 800) }); console.log(JSON.stringify(out)); });
'''


def test_browser():
    import ai_gateway
    pw = find_playwright()
    if not pw:
        check('Playwright có sẵn (node_modules/playwright ở repo chính)', False, 'npm i -D playwright')
        return
    booking_globals = "window.BITPAW_BUSINESS_ID='biz1';window.BITPAW_BUSINESS_NAME='Lotus Nails';window.BITPAW_CHAT_CONTEXT='customer_booking';"
    pages = {
        '/booking': WIDGET_PAGE % {'lang': 'en', 'globals': booking_globals},
        '/booking_vi': WIDGET_PAGE % {'lang': 'vi', 'globals': booking_globals},
        '/ai_bot_en': render('ai_bot.html', lang='en'),
        '/ai_bot_vi': render('ai_bot.html', lang='vi'),
        '/plan': '<!doctype html><title>plan</title><h1>Plans</h1>',
        '/settings_messaging': render('messaging_settings.html', lang='en', industry='nail'),
        '/campaign_builder': render('campaign_builder.html', lang='en'),
        '/omnichannel_connect': render('omnichannel_connect.html', lang='en'),
        '/dashboard': render('dashboard.html', lang='en'),
    }
    tmp = tempfile.mkdtemp(prefix='p1_frontend_')
    pages_file = os.path.join(tmp, 'pages.json')
    js_file = os.path.join(tmp, 'browser_test.js')
    with open(pages_file, 'w', encoding='utf-8') as f:
        json.dump(pages, f)
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(NODE_BROWSER)
    env = dict(os.environ, PW_PATH=pw, PAGES_FILE=pages_file, STATIC_DIR=os.path.join(ROOT, 'static'),
               PLAN_PAUSED_REASON=ai_gateway.PLAN_PAUSED_REASON)
    r = subprocess.run(['node', js_file], capture_output=True, text=True, encoding='utf-8', env=env, timeout=600)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check('browser tests chạy được', False, (r.stderr or r.stdout)[-800:])
        return
    for row in rows:
        check('browser: ' + row['name'], row['ok'], row.get('note', ''))


def main():
    test_syntax()
    test_widget_static()
    test_ai_bot_static()
    test_messaging_settings_static()
    test_campaign_builder_static()
    test_omnichannel_static()
    test_dashboard_static()
    test_messaging_e2e_expectation()
    if '--browser' in sys.argv:
        test_browser()
    print(f'\n{"OK" if not FAILS else "FAILED"} — {len(FAILS)} lỗi')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
