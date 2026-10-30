# -*- coding: utf-8 -*-
"""Test OFFLINE — trang Cài đặt đặt chỗ (/settings/booking) của ngành đặt chỗ + sidebar nhân viên + script seed demo.

  - Công tắc chung "tự xác nhận": bật/tắt 1 ngày ở Giờ mở cửa KHÔNG được âm thầm bật lại mặc định "tự xác nhận" của Nails
    (chạy đúng script của trang trong node với DOM giả, rồi gửi lại đúng các lệnh POST nó tạo qua route Flask thật);
  - quán karaoke / F&B từng bấm Lưu ở trang Cài đặt đặt lịch CŨ (luôn gửi auto_confirm=True mặc định của Nails) không bị
    "theo công tắc chung" biến thành AI tự xác nhận — chỉ lựa chọn chủ lưu ở trang Đặt chỗ mới được tính;
  - Đặt trước tối thiểu / tối đa: trang hiện ĐÚNG giá trị AI đang dùng (chưa đặt = 0 / 366), Lưu không âm thầm ghi 60 / 60;
  - lỗi giờ mở cửa theo ngôn ngữ của chủ (VI / EN, có tên ngày), giờ qua nửa đêm lưu được cho ngành đặt chỗ, Nails giữ luật cũ;
  - nhân viên bán lẻ / văn phòng thấy link Giữ hàng chờ lấy / Yêu cầu tư vấn (trang cho phép nhân viên);
  - scripts/seed_ai_demo_data.py: chỉ điền khoá còn trống, bản sao hoàn tác ghi ngay cả khi lỗi giữa chừng, hoàn tác chỉ gỡ
    đúng ô đã seed (ô chủ demo sửa sau đó được giữ).

Dùng lại DB giả + Flask + decorator thật của test_phase2_owner_settings.py. KHÔNG import app.py, KHÔNG mở MongoDB thật,
KHÔNG gọi mạng.

Chạy: python scripts/tests/test_phase2_settings_hours.py
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_phase2_owner_settings as S  # noqa: E402  (DB giả + stub mongo_client / app TRƯỚC mọi import của module thật)

ROOT, DB, BID, rc, booking_rules = S.ROOT, S.DB, S.BID, S.rc, S.booking_rules
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import seed_ai_demo_data as seed  # noqa: E402

MARK = 'reservations_general_saved_at'
WEEK = booking_rules.DAY_KEYS
ALL_DAYS = {d: ['18:00', '23:00'] for d in WEEK}


# DB giả của test_phase2_owner_settings chưa có $unset theo đường dẫn 'a.b' và replace_one — Mongo thật có cả 2.
def _apply(d, update, inserting=False, _orig=S.FakeCollection._apply):
    upd = dict(update)
    unset = upd.pop('$unset', None) or {}
    _orig(d, upd, inserting)
    for k in unset:
        parts, cur = k.split('.'), d
        for p in parts[:-1]:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)


def _replace_one(self, flt, doc, upsert=False):
    for i, d in enumerate(self.docs):
        if S._matches(d, flt):
            self.docs[i] = dict(S.copy.deepcopy(doc), _id=d['_id'])
            return S._Res(matched_count=1)
    if upsert:
        self.insert_one(S.copy.deepcopy(doc))
    return S._Res(matched_count=0)


S.FakeCollection._apply = staticmethod(_apply)
S.FakeCollection.replace_one = _replace_one


class Base(S.Base):
    industry = 'karaoke'

    def general(self, method='GET', body=None):
        r = self.client.get('/api/booking/settings') if method == 'GET' else self.client.post('/api/booking/settings', json=body)
        return r.status_code, r.get_json()


# ================================================================ công tắc chung + khách cũ (#23, #24)
LEGACY = {'business_id': BID, 'hours': S.HOURS, 'auto_confirm': True, 'slot_minutes': 15, 'min_lead_minutes': 60,
          'max_advance_days': 60, 'default_duration': 60, 'capacity': 0, 'durations': {},
          'info': {'address': '1 Main St', 'parking': '', 'payments': '', 'gift_cards': '', 'cancellation_policy': '', 'other': ''},
          'updated_at': '2026-09-01T10:00:00'}     # đúng thứ trang Cài đặt đặt lịch CŨ ghi khi chủ karaoke bấm Lưu 1 lần


class GeneralSwitch(Base):
    def test_old_page_defaults_do_not_opt_into_ai_auto_confirm(self):
        DB.booking_settings.insert_one(dict(LEGACY))
        k = rc.load_rules(BID, 'karaoke')
        self.assertIs(k['auto_confirm'], False)
        self.assertEqual(rc.karaoke_status_for(k), ('pending', 'shop_confirms'))
        self.assertEqual(rc.table_status_for(rc.load_rules(BID, 'table'), 'covers', 2), ('pending', 'shop_confirms'))
        code, j = self.get('karaoke')
        self.assertEqual((j['settings']['auto_confirm'], j['general_auto_confirm'], j['effective_auto_confirm']),
                         ('follow', None, False))
        code, g = self.general()
        self.assertEqual(code, 200)
        self.assertIs(g['rules']['auto_confirm'], False)            # công tắc chung hiện đúng "chờ duyệt"

    def test_choice_saved_on_the_reservation_page_is_followed(self):
        DB.booking_settings.insert_one(dict(LEGACY))
        code, g = self.general('POST', {'auto_confirm': True})
        self.assertEqual(code, 200, g)
        self.assertIs(g['rules']['auto_confirm'], True)
        self.assertTrue(self.stored().get(MARK))
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('confirmed', None))
        self.assertIs(self.get('karaoke')[1]['general_auto_confirm'], True)
        self.general('POST', {'auto_confirm': False})
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('pending', 'shop_confirms'))
        self.assertIs(self.get('karaoke')[1]['general_auto_confirm'], False)

    def test_save_without_the_switch_does_not_legitimise_the_old_default(self):
        DB.booking_settings.insert_one(dict(LEGACY))
        self.general('POST', {'info': {'parking': 'Street'}})
        self.assertIsNone(self.stored().get(MARK))
        self.assertIs(rc.load_rules(BID, 'karaoke')['auto_confirm'], False)

    def test_explicit_always_still_wins(self):
        DB.booking_settings.insert_one(dict(LEGACY))
        self.post('karaoke', {'auto_confirm': 'always'})
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('confirmed', None))

    def test_nail_switch_is_unchanged(self):
        self.login('nail')
        code, g = self.general()
        self.assertEqual((g['rules']['auto_confirm'], g['rules']['min_lead_minutes'], g['rules']['max_advance_days']), (True, 60, 60))
        code, g = self.general('POST', {'auto_confirm': False, 'min_lead_minutes': 30})
        self.assertEqual(code, 200)
        doc = self.stored()
        self.assertEqual((doc['auto_confirm'], doc['min_lead_minutes']), (False, 30))
        self.assertNotIn(MARK, doc)

    def test_hotel_hidden_general_switch_is_not_saved(self):
        self.login('hotel')
        code, g = self.general('POST', {'auto_confirm': True, 'info': {'parking': 'On site'}})
        self.assertEqual(code, 200, g)
        doc = self.stored()
        self.assertNotIn('auto_confirm', doc)
        self.assertNotIn(MARK, doc)
        self.assertEqual(doc['info']['parking'], 'On site')


# ================================================================ đặt trước tối thiểu / tối đa hiện đúng (#42)
class BookingWindow(Base):
    def test_unsaved_values_show_what_the_ai_uses(self):
        code, g = self.general()
        self.assertEqual((g['rules']['min_lead_minutes'], g['rules']['max_advance_days']), (None, None))
        code, j = self.get('karaoke')
        self.assertEqual((j['min_lead_minutes'], j['max_advance_days']), (0, 366))
        code, g = self.general('POST', {'hours': ALL_DAYS, 'auto_confirm': False, 'info': {'parking': 'Street'}})
        self.assertEqual(code, 200, g)
        doc = self.stored()
        self.assertNotIn('min_lead_minutes', doc)
        self.assertNotIn('max_advance_days', doc)
        r = rc.load_rules(BID, 'karaoke')
        self.assertEqual((r['min_lead_minutes'], r['max_advance_days']), (0, 366))
        self.general('POST', {'min_lead_minutes': 30, 'max_advance_days': 90, 'auto_confirm': False})
        self.assertEqual(self.general()[1]['rules']['min_lead_minutes'], 30)
        self.assertEqual((self.get('karaoke')[1]['min_lead_minutes'], self.get('karaoke')[1]['max_advance_days']), (30, 90))

    def test_table_payload_too(self):
        self.login('fnb')
        code, j = self.get('table')
        self.assertEqual((j['min_lead_minutes'], j['max_advance_days']), (0, 366))


# ================================================================ giờ qua nửa đêm + lỗi theo ngôn ngữ (#15, #29, #43)
class HoursErrors(Base):
    def post_hours(self, **days):
        return self.general('POST', {'hours': dict(ALL_DAYS, **days), 'auto_confirm': False})

    def test_reservation_venue_saves_hours_past_midnight(self):
        code, g = self.post_hours(fri=['18:00', '02:00'], sat=['18:00', '03:00'])
        self.assertEqual(code, 200, g)
        self.assertEqual((g['rules']['hours']['fri'], g['rules']['hours']['sat']), (['18:00', '02:00'], ['18:00', '03:00']))
        self.assertEqual(rc.hours_on(rc.load_rules(BID, 'karaoke'), S.date(2026, 10, 30)), (1080, 1560))
        self.login('fnb')
        self.assertEqual(self.post_hours(fri=['17:00', '01:00'])[0], 200)

    def test_errors_in_the_owner_language(self):
        code, j = self.post_hours(fri=['18:00', '09:00'])
        self.assertEqual((code, j['message']),
                         (400, 'Friday hours: when you close after midnight, the latest closing time is 08:00 the next morning.'))
        self.assertEqual(self.post_hours(mon=['18:00', '18:00'])[1]['message'],
                         'Monday hours: the opening and closing times are the same. Open all day: set 00:00 to 00:00.')
        self.assertEqual(self.post_hours(tue=['25:00', '02:00'])[1]['message'],
                         'Tuesday hours: times must be HH:MM, from 00:00 to 24:00.')
        self.assertEqual(self.general('POST', {'min_lead_minutes': 'soon'})[1]['message'], 'Minimum notice: must be a number.')
        self.login('karaoke', lang='vi')
        self.assertEqual(self.post_hours(fri=['18:00', '09:00'])[1]['message'],
                         'Giờ mở cửa Thứ 6: đóng sau nửa đêm thì giờ đóng muộn nhất là 08:00 sáng hôm sau.')
        self.assertEqual(self.general('POST', {'max_advance_days': 'x'})[1]['message'], 'Đặt trước tối đa: phải là một con số.')
        self.assertNotIn('hours', self.stored())                  # lỗi không ghi gì

    def test_nail_keeps_the_old_rule_with_a_clear_message(self):
        self.login('nail')
        code, j = self.post_hours(fri=['18:00', '02:00'])
        self.assertEqual((code, j['message']),
                         (400, 'Friday hours: the closing time must be after the opening time (00:00 means midnight).'))
        self.login('nail', lang='vi')
        self.assertEqual(self.post_hours(sun=['18:00', '02:00'])[1]['message'],
                         'Giờ mở cửa Chủ nhật: giờ đóng phải sau giờ mở (00:00 = nửa đêm).')
        self.assertNotIn('hours', self.stored())


# ================================================================ script thật của trang trong node, DOM giả (#23, #42)
NODE_HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const VOID = new Set(['input', 'br', 'img', 'meta', 'link', 'hr', 'source', 'wbr', 'col', 'area', 'base']);
const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
const dec = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENT[m]);
class El {
  constructor(tag, attrs, parent) {
    this.tag = tag; this.tagName = tag.toUpperCase(); this.attrs = attrs || {}; this.children = []; this.parentNode = parent || null;
    this._ls = {}; this._text = ''; this._value = undefined; this._checked = 'checked' in this.attrs;
    this.hidden = 'hidden' in this.attrs; this.disabled = 'disabled' in this.attrs; this.className = this.attrs.class || '';
  }
  get id() { return this.attrs.id || ''; }
  get type() { return (this.attrs.type || (this.tag === 'input' ? 'text' : '')).toLowerCase(); }
  get dataset() { const o = {}; for (const k in this.attrs) if (k.startsWith('data-')) o[k.slice(5)] = this.attrs[k]; return o; }
  get checked() { return this._checked; } set checked(v) { this._checked = !!v; }
  get options() { return this.querySelectorAll('option'); }
  get value() {
    if (this.tag === 'select') {
      if (this._value !== undefined) return this._value;
      const o = this.options, s = o.find((x) => 'selected' in x.attrs) || o[0];
      return s ? s.value : '';
    }
    if (this.tag === 'option') return 'value' in this.attrs ? this.attrs.value : this.textContent;
    if (this.tag === 'textarea') return this._value !== undefined ? this._value : this.textContent;
    return this._value !== undefined ? this._value : (this.attrs.value || '');
  }
  set value(v) {
    const s = v === null ? '' : String(v);
    if (this.tag === 'select') { this._value = this.options.some((o) => o.value === s) ? s : ''; return; }
    this._value = s;
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children = []; this._text = String(v); }
  set innerHTML(h) { this.children = []; this._text = ''; parseInto(this, String(h)); }
  get innerHTML() { return ''; }
  addEventListener(t, fn) { (this._ls[t] = this._ls[t] || []).push(fn); }
  fire(t) { const ev = { type: t, target: this, currentTarget: this, preventDefault() {} }; (this._ls[t] || []).forEach((fn) => fn(ev)); }
  matches(sel) { return match(this, sel); }
  closest(sel) { let e = this; while (e && e.tag !== '#doc') { if (match(e, sel)) return e; e = e.parentNode; } return null; }
  querySelectorAll(sel) { const out = []; const walk = (n) => n.children.forEach((c) => { if (match(c, sel)) out.push(c); walk(c); }); walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementById(id) { return this.querySelector('#' + id); }
}
function one(el, part) {
  const m = /^([a-z0-9]+)?(.*)$/i.exec(part);
  if (m[1] && el.tag !== m[1].toLowerCase()) return false;
  const re = /#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=("?)([^"\]]*)\4)?\]/g; let x;
  while ((x = re.exec(m[2]))) {
    if (x[1] && el.id !== x[1]) return false;
    if (x[2] && !String(el.className).split(/\s+/).includes(x[2])) return false;
    if (x[3]) { if (!(x[3] in el.attrs)) return false; if (x[5] !== undefined && String(el.attrs[x[3]]) !== x[5]) return false; }
  }
  return true;
}
function match(el, sel) {
  const parts = sel.trim().split(/\s+/);
  if (!one(el, parts[parts.length - 1])) return false;
  let i = parts.length - 2, e = el.parentNode;
  while (i >= 0 && e && e.tag !== '#doc') { if (one(e, parts[i])) i--; e = e.parentNode; }
  return i < 0;
}
function parseInto(root, html) {
  const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|([^<]+)/g;
  let m, cur = root;
  while ((m = re.exec(html))) {
    if (m[1]) { let e = cur; while (e !== root && e.tag !== m[1].toLowerCase()) e = e.parentNode; if (e !== root) cur = e.parentNode; }
    else if (m[2]) {
      const attrs = {}, ar = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g; let a;
      while ((a = ar.exec(m[3] || ''))) attrs[a[1].toLowerCase()] = dec(a[2] !== undefined ? a[2] : a[3] !== undefined ? a[3] : (a[4] || ''));
      const el = new El(m[2].toLowerCase(), attrs, cur); cur.children.push(el);
      if (!VOID.has(el.tag)) cur = el;
    } else if (m[4]) cur._text += dec(m[4]);
  }
}
const doc = new El('#doc'); parseInto(doc, IN.main);
const posts = [], errors = [], snaps = {};
const stub = (url, method) => IN.responses[method + ' ' + url];
const fetch = (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  if (method !== 'GET') posts.push({ url, method, body: JSON.parse(opts.body) });
  const r = stub(url, method) || (method !== 'GET' ? stub(url, 'GET') : null);
  if (IN.fail && IN.fail.includes(method + ' ' + url)) return Promise.resolve({ ok: false, status: 500, json: async () => ({ success: false, message: 'boom' }) });
  return Promise.resolve(r ? { ok: true, status: 200, json: async () => r } : { ok: false, status: 404, json: async () => ({ success: false, message: 'no stub ' + url }) });
};
const $ = (id) => doc.getElementById(id);
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
const row = (d) => doc.querySelector('#hours .day[data-d=' + d + ']');
const snap = (name) => {
  const o = doc.querySelector('#rv_auto_confirm option[value="follow"]');
  snaps[name] = { autoc: $('autoc').value, follow: o ? o.textContent : null, lead: $('lead').value, adv: $('adv').value,
                  saveDisabled: !!$('saveBtn').disabled, note: $('note').textContent, rvNow: $('rvNow') ? $('rvNow').textContent : null,
                  parking: $('i_parking') ? $('i_parking').value : null, warn: $('defaultWarn').hidden,
                  tueClose: row('tue') && row('tue').querySelectorAll('input[type=time]')[1] ? row('tue').querySelectorAll('input[type=time]')[1].value : null,
                  friTag: row('fri') && row('fri').querySelector('.nextday') ? row('fri').querySelector('.nextday').textContent : null };
};
const ctx = { document: doc, window: { confirm: () => true }, fetch, console, setTimeout, setImmediate, Date, JSON, Promise };
ctx.window.document = doc;
(async () => {
  try {
    vm.runInNewContext(IN.script, ctx);
    snap('initial');
    await settle(); snap('loaded');
    for (const s of IN.steps) {
      if (s.op === 'value') { const el = s.id ? $(s.id) : row(s.day).querySelectorAll('input[type=time]')[s.i]; el.value = s.value; el.fire('change'); el.fire('input'); }
      else if (s.op === 'toggle') { const cb = row(s.day).querySelector('input[type=checkbox]'); cb.checked = !cb.checked; cb.fire('change'); }
      else if (s.op === 'snap') snap(s.name);
      else if (s.op === 'save') { $('saveBtn').fire('click'); await settle(); }
    }
  } catch (e) { errors.push(String(e && e.stack || e)); }
  console.log(JSON.stringify({ snaps, posts, errors }));
})();
'''


@unittest.skipUnless(shutil.which('node'), 'node không có trên máy này')
class PageScript(Base):
    def run_page(self, industry, steps, lang='en', fail=()):
        """Hiện trang cho `industry` với dữ liệu GET thật (route Flask + DB giả), chạy script của trang trong node, rồi gửi lại
        đúng các lệnh POST trang tạo qua route thật."""
        self.login(industry, lang=lang)
        html = S.render('booking_settings.html', active_industry_code=industry, default_lang=lang)
        main = re.search(r'<main class="bs-main">[\s\S]*?</main>', html).group(0)
        script = re.findall(r'<script>([\s\S]*?)</script>', html)[-1]
        kind = bsr_kind(industry)
        responses = {'GET /api/booking/settings': self.client.get('/api/booking/settings').get_json()}
        if kind:
            responses['GET /api/booking/reservation_settings/' + kind] = self.get(kind)[1]
        tmp = tempfile.mkdtemp(prefix='p2_settings_')
        try:
            js, data = os.path.join(tmp, 'h.js'), os.path.join(tmp, 'in.json')
            with open(js, 'w', encoding='utf-8') as f:
                f.write(NODE_HARNESS)
            with open(data, 'w', encoding='utf-8') as f:
                json.dump({'main': main, 'script': script, 'responses': responses, 'steps': steps, 'fail': list(fail)}, f)
            r = subprocess.run(['node', js, data], capture_output=True, text=True, encoding='utf-8', timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out['errors'], [])
        for p in out['posts']:
            res = self.client.post(p['url'], json=p['body'])
            self.assertEqual(res.status_code, 200, (p, res.get_json()))
        return out

    STEPS = [{'op': 'value', 'id': 'i_parking', 'value': 'Street parking after 6pm'},
             {'op': 'value', 'day': 'tue', 'i': 1, 'value': '23:00'},
             {'op': 'value', 'day': 'fri', 'i': 0, 'value': '18:00'},
             {'op': 'value', 'day': 'fri', 'i': 1, 'value': '02:00'},
             {'op': 'snap', 'name': 'edited'},
             {'op': 'toggle', 'day': 'mon'},
             {'op': 'snap', 'name': 'toggled'},
             {'op': 'save'},
             {'op': 'snap', 'name': 'saved'}]

    def test_day_toggle_never_turns_on_auto_confirm(self):
        out = self.run_page('karaoke', self.STEPS)
        s = out['snaps']
        self.assertTrue(s['initial']['saveDisabled'])                       # chưa tải xong thì chưa cho Lưu
        self.assertFalse(s['loaded']['saveDisabled'])
        for name in ('loaded', 'edited', 'toggled', 'saved'):
            self.assertEqual(s[name]['autoc'], '0', name)                   # chưa từng chọn: chờ duyệt, mọi lúc
            self.assertEqual(s[name]['follow'], 'Follow general switch (now: approve)', name)
        self.assertEqual((s['toggled']['parking'], s['toggled']['tueClose']), ('Street parking after 6pm', '23:00'))
        self.assertEqual(s['edited']['friTag'], 'Closes 02:00 the next morning (after midnight)')
        body = out['posts'][0]['body']
        self.assertEqual(out['posts'][0]['url'], '/api/booking/settings')
        self.assertIs(body['auto_confirm'], False)
        self.assertNotIn('min_lead_minutes', body)                          # ô trống = chưa đặt: không gửi 60 mặc định
        self.assertNotIn('max_advance_days', body)
        self.assertEqual((body['hours']['mon'], body['hours']['tue'][1], body['hours']['fri']), (None, '23:00', ['18:00', '02:00']))
        self.assertEqual(body['info']['parking'], 'Street parking after 6pm')
        self.assertEqual(out['posts'][1]['body']['auto_confirm'], 'follow')
        k = rc.load_rules(BID, 'karaoke')
        self.assertEqual((k['auto_confirm'], k['min_lead_minutes'], k['max_advance_days']), (False, 0, 366))
        self.assertEqual(k['hours']['fri'], ['18:00', '02:00'])
        self.assertEqual(rc.karaoke_status_for(k), ('pending', 'shop_confirms'))
        self.assertIn('no minimum notice, up to 366 days ahead', s['loaded']['rvNow'])

    def test_owner_turns_auto_confirm_on_and_a_toggle_keeps_it(self):
        out = self.run_page('karaoke', [{'op': 'value', 'id': 'autoc', 'value': '1'}, {'op': 'toggle', 'day': 'sun'},
                                        {'op': 'snap', 'name': 'toggled'}, {'op': 'save'}])
        self.assertEqual((out['snaps']['toggled']['autoc'], out['snaps']['toggled']['follow']),
                         ('1', 'Follow general switch (now: instant)'))
        self.assertIs(out['posts'][0]['body']['auto_confirm'], True)
        self.assertEqual(rc.karaoke_status_for(rc.load_rules(BID, 'karaoke')), ('confirmed', None))

    def test_legacy_shop_sees_and_keeps_pending(self):
        DB.booking_settings.insert_one(dict(LEGACY))
        out = self.run_page('fnb', [{'op': 'save'}])
        self.assertEqual(out['snaps']['loaded']['autoc'], '0')
        self.assertEqual((out['snaps']['loaded']['lead'], out['snaps']['loaded']['adv']), ('60', '60'))   # đã lưu thật: hiện
        self.assertIs(out['posts'][0]['body']['auto_confirm'], False)
        self.assertFalse(rc.load_rules(BID, 'table')['auto_confirm'])

    def test_failed_reservation_load_does_not_send_the_nails_default(self):
        out = self.run_page('karaoke', [{'op': 'save'}], fail=('GET /api/booking/reservation_settings/karaoke',))
        self.assertEqual(out['snaps']['loaded']['autoc'], '0')
        self.assertIs(out['posts'][0]['body']['auto_confirm'], False)
        self.assertEqual(len(out['posts']), 1)

    def test_nail_page_still_sends_its_rules(self):
        out = self.run_page('nail', [{'op': 'toggle', 'day': 'mon'}, {'op': 'save'}])
        body = out['posts'][0]['body']
        self.assertEqual((body['auto_confirm'], body['min_lead_minutes'], body['max_advance_days']), (True, 60, 60))
        self.assertEqual(len(out['posts']), 1)
        self.assertIsNone(out['snaps']['loaded']['friTag'])                 # Nails: không có giờ qua nửa đêm


def bsr_kind(industry):
    return S.bsr.RESERVATION_KIND.get(industry)


class PageText(unittest.TestCase):
    def test_hours_hint_explains_past_midnight(self):
        k = S.render('booking_settings.html', active_industry_code='karaoke', default_lang='en')
        self.assertIn('Open past midnight: set a closing time earlier than the opening time', k)
        self.assertNotIn('cannot be entered yet', k)
        self.assertIn('Mở qua nửa đêm: chọn giờ đóng nhỏ hơn giờ mở',
                      S.render('booking_settings.html', active_industry_code='fnb', default_lang='vi'))
        self.assertNotIn('past midnight', S.render('booking_settings.html', active_industry_code='nail', default_lang='en')
                         .split('<script>')[0])


# ================================================================ sidebar nhân viên (#41)
class StaffSidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jinja2 import Environment, FileSystemLoader
        cls.env = Environment(loader=FileSystemLoader(os.path.join(ROOT, 'templates')))
        with open(os.path.join(ROOT, 'translations', 'en.json'), encoding='utf-8') as f:
            cls.menu = json.load(f)['menu']

    def render(self, role, industry, lang='en'):
        return self.env.get_template('components/app_sidebar.html').render(
            session={'role': role}, url_for=lambda e, **k: '/' + e, plan_lock=lambda f: '', menu_i18n=self.menu,
            menu_i18n_all={'en': self.menu, 'vi': self.menu}, default_lang=lang, active_industry_code=industry,
            active_industry_cfg={'modules': ['sales', 'attendance']}, request=types.SimpleNamespace(path='/retail/holds'),
            industry_pos_url='/pos', industry_chamcong_url='/chamcong', current_plan='pro')

    def test_staff_reach_the_request_pages_they_are_allowed_to_use(self):
        html = self.render('staff', 'retail')
        self.assertEqual(html.count('href="/retail/holds"'), 1)
        self.assertIn('Pickup holds', html)
        self.assertIn('Giữ hàng chờ lấy', self.render('staff', 'retail', 'vi'))
        self.assertEqual(self.render('staff', 'office').count('href="/requests/consultations"'), 1)
        self.assertNotIn('/requests/quotes', self.render('staff', 'production'))     # báo giá: chỉ chủ / quản lý
        self.assertNotIn('/retail/holds', self.render('staff', 'fnb'))
        self.assertEqual(self.render('admin', 'retail').count('href="/retail/holds"'), 1)


# ================================================================ scripts/seed_ai_demo_data.py (#39, #40)
DEMO = {'fnb': {'id': 'f1', 'name': 'Demo F&B', 'industry_code': 'fnb'},
        'technical': {'id': 't1', 'name': 'Demo Tech', 'industry_code': 'technical'}}
TECH_HOURS = {d: (['08:00', '18:00'] if d not in ('sat', 'sun') else None) for d in WEEK}


class Seed(unittest.TestCase):
    def setUp(self):
        DB.reset()
        booking_rules._CACHE.clear()
        self.tmp = tempfile.mkdtemp(prefix='p2_seed_')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_main(self, *args, demo=DEMO):
        with mock.patch.object(seed, 'ROOT', self.tmp), mock.patch.object(seed, 'demo_businesses', lambda db: dict(demo)), \
                mock.patch.object(sys, 'argv', ['seed_ai_demo_data.py', *args]), mock.patch('builtins.print'):
            seed.main()

    def backups(self):
        return glob.glob(os.path.join(self.tmp, 'audit-results', 'ai_sim', 'demo_seed_backup_*.json'))

    def test_plan_fills_only_missing_table_rules(self):
        DB.booking_settings.insert_one({'business_id': 'f1', 'table_reservations': {'auto_confirm': False, 'hold_minutes': 30}})
        bs, todo = seed.plan(DB, 'fnb', DEMO['fnb'])
        self.assertIn(('table_rules', {'max_covers_per_slot': 40}), todo)
        seed.apply(DB, 'fnb', DEMO['fnb'], bs, todo, {})
        tr = DB.booking_settings.find_one({'business_id': 'f1'})['table_reservations']
        self.assertEqual(tr, {'auto_confirm': False, 'hold_minutes': 30, 'max_covers_per_slot': 40})
        self.assertIs(rc.load_rules('f1', 'table')['auto_confirm'], False)
        DB.booking_settings.update_one({'business_id': 'f1'}, {'$set': {'table_reservations.auto_confirm': None}})   # "theo công tắc chung"
        self.assertNotIn('table_rules', [k for k, _v in seed.plan(DB, 'fnb', DEMO['fnb'])[1]])

    def test_backup_is_written_when_apply_fails_midway(self):
        DB.booking_settings.insert_one({'business_id': 't1', 'hours': TECH_HOURS, 'info': {'payments': 'Card'}})
        orig, n = DB.dichvu.insert_one, []

        def flaky(doc):
            n.append(1)
            if len(n) == 3:
                raise TimeoutError('Atlas timeout')
            return orig(doc)
        DB.dichvu.insert_one = flaky
        with self.assertRaises(TimeoutError):
            self.run_main('--apply')
        files = self.backups()
        self.assertEqual(len(files), 1)
        with open(files[0], encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(set(data), {'f1', 't1'})
        self.assertEqual(DB.dichvu.count_documents({'business_id': 't1'}), 2)
        stored = {d['id'] for d in DB.dichvu.find({'business_id': 't1'})}
        self.assertTrue(stored <= set(data['t1']['inserted']['dichvu']))
        with mock.patch('builtins.print'):
            seed.revert(DB, files[0])
        self.assertEqual(DB.dichvu.count_documents({}), 0)
        self.assertIsNone(DB.booking_settings.find_one({'business_id': 'f1'}))    # chưa có trước khi seed -> gỡ sạch
        self.assertEqual(DB.ai_knowledge.count_documents({'business_id': 'f1'}), 0)
        t1 = DB.booking_settings.find_one({'business_id': 't1'}, {'_id': 0})
        self.assertEqual((t1['hours'], t1['info']), (TECH_HOURS, {'payments': 'Card'}))

    def test_revert_only_undoes_seeded_fields(self):
        DB.booking_settings.insert_one({'business_id': 't1', 'hours': TECH_HOURS, 'info': {'payments': 'Card'}})
        self.run_main('--apply')
        files = self.backups()
        self.assertEqual(len(files), 1)
        # chủ demo sửa sau khi seed: ô không do seed ghi, và 1 ô seed đã ghi
        DB.booking_settings.update_one({'business_id': 't1'}, {'$set': {'hours.sat': ['09:00', '13:00'], 'info.parking': 'Street'}})
        DB.booking_settings.update_one({'business_id': 'f1'}, {'$set': {'hours.mon': ['12:00', '22:00']}})
        with mock.patch('builtins.print'):
            seed.revert(DB, files[0])
        t1 = DB.booking_settings.find_one({'business_id': 't1'}, {'_id': 0})
        self.assertEqual(t1['hours']['sat'], ['09:00', '13:00'])
        self.assertEqual(t1['info'], {'payments': 'Card', 'parking': 'Street'})
        self.assertEqual(DB.dichvu.count_documents({}), 0)
        f1 = DB.booking_settings.find_one({'business_id': 'f1'}, {'_id': 0})
        self.assertEqual(f1['hours']['mon'], ['12:00', '22:00'])                 # chủ đã sửa -> giữ
        self.assertNotIn('table_reservations', f1)
        self.assertEqual(f1.get('info') or {}, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
