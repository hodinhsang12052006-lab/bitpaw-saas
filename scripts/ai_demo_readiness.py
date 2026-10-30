"""
Báo cáo CHỈ ĐỌC — tiệm DEMO của từng ngành đã có đủ dữ liệu cho lễ tân AI + gói đặt chỗ của ngành đó chưa, TRƯỚC khi chạy
giả lập trả phí (scripts/ai_sim/sim_receptionist.py) hay bật lại câu "AI trả lời & đặt chỗ" cho ngành.

    python scripts/ai_demo_readiness.py                       # cả 9 ngành, tiệm demo trong scripts/*_industry_master_audit.mjs
    python scripts/ai_demo_readiness.py --industry fnb,hotel  # vài ngành
    python scripts/ai_demo_readiness.py --industry hotel --biz <business_id>
    python scripts/ai_demo_readiness.py --json out.json       # thêm bản JSON

Tiệm demo = đúng tài khoản demo.*@bitpawdemo.com mà các bài kiểm tra tổng ngành (scripts/<ngành>_industry_master_audit.mjs)
dùng, cùng biến môi trường ghi đè (FNB_DEMO_EMAIL...). Mỗi mục: OK / MISSING (gói KHÔNG làm thật được nếu thiếu) / WARN (nên
có — thiếu thì AI phải nói "chưa có thông tin" hoặc chỉ nhận yêu cầu chờ duyệt) / INFO.

AN TOÀN: chỉ đọc. Mọi truy cập MongoDB đi qua ReadOnlyDB — chỉ find / find_one / count_documents / distinct; lệnh ghi nào cũng
ném lỗi ngay (kể cả do thư viện khác gọi). Không gọi server, không gọi AI.
"""
import argparse
import ast
import glob
import json
import os
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_DIR = os.path.join(ROOT, 'scripts', 'ai_sim')
for _p in (ROOT, SIM_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

INDUSTRIES = ('nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'technical', 'production', 'office')
FALLBACK_EMAILS = {   # = scripts/*_industry_master_audit.mjs (đọc lại file .mjs lúc chạy; bảng này chỉ là dự phòng)
    'nail': ('NAIL_DEMO_EMAIL', 'demo.nails.au.006758@bitpawdemo.com'),
    'spa': ('SPA_DEMO_EMAIL', 'demo.spa.596348@bitpawdemo.com'),
    'fnb': ('FNB_DEMO_EMAIL', 'demo.fnb.343602@bitpawdemo.com'),
    'karaoke': ('KARAOKE_DEMO_EMAIL', 'demo.karaoke.071443@bitpawdemo.com'),
    'hotel': ('HOTEL_DEMO_EMAIL', 'demo.hotel.071443@bitpawdemo.com'),
    'retail': ('RETAIL_DEMO_EMAIL', 'demo.retail.596348@bitpawdemo.com'),
    'technical': ('TECHNICAL_DEMO_EMAIL', 'demo.technical.393328@bitpawdemo.com'),
    'production': ('PRODUCTION_DEMO_EMAIL', 'demo.production.393328@bitpawdemo.com'),
    'office': ('OFFICE_DEMO_EMAIL', 'demo.office.784966@bitpawdemo.com'),
}
COUNTRY_TZ = {'AU': 'Australia/Sydney', 'US': 'America/New_York', 'VN': 'Asia/Ho_Chi_Minh', 'CA': 'America/Toronto',
              'NZ': 'Pacific/Auckland', 'GB': 'Europe/London'}
PACK_RESOURCE = {'nail': 'appointment', 'spa': 'appointment', 'fnb': 'table', 'karaoke': 'room_hour', 'hotel': 'room_night',
                 'retail': 'stock_hold', 'technical': 'job', 'production': 'quote', 'office': 'consult'}
OK, MISSING, WARN, INFO = 'OK', 'MISSING', 'WARN', 'INFO'


# ---------------------------------------------------------------- chỉ đọc
class ReadOnlyError(RuntimeError):
    pass


class ReadOnlyCollection:
    READS = frozenset({'find', 'find_one', 'count_documents', 'distinct'})

    def __init__(self, coll, name):
        self._coll, self._name = coll, name

    def __getattr__(self, attr):
        if attr in self.READS:
            return getattr(self._coll, attr)
        raise ReadOnlyError(f'ai_demo_readiness chỉ đọc: {self._name}.{attr} bị chặn')


class ReadOnlyDB:
    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        return ReadOnlyCollection(self._db[name], name)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]


# ---------------------------------------------------------------- tài khoản demo
_MJS_RE = re.compile(r"process\.env\.([A-Z]+_DEMO_EMAIL)\s*\|\|\s*'([^']+@bitpawdemo\.com)'")


def demo_accounts(root=ROOT):
    """{ngành: (biến môi trường, email mặc định)} đọc từ scripts/<ngành>_industry_master_audit.mjs (nguồn chuẩn)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, 'scripts', '*_industry_master_audit.mjs'))):
        ind = os.path.basename(path).split('_industry_master_audit')[0]
        try:
            with open(path, encoding='utf-8') as f:
                m = _MJS_RE.search(f.read())
        except OSError:
            m = None
        if m and ind in INDUSTRIES:
            out[ind] = (m.group(1), m.group(2))
    for ind, v in FALLBACK_EMAILS.items():
        out.setdefault(ind, v)
    return out


def pack_module(industry, root=ROOT):
    """ai_packs/<x>.py nào phục vụ ngành (đọc tĩnh INDUSTRIES bằng ast — không import, không chạy mã)."""
    d = os.path.join(root, 'ai_packs')
    if not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.py') or fn.startswith('_'):
            continue
        try:
            with open(os.path.join(d, fn), encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'INDUSTRIES' for t in node.targets):
                try:
                    inds = ast.literal_eval(node.value)
                except ValueError:
                    continue
                if industry in (inds if isinstance(inds, (list, tuple, set)) else [inds]):
                    return fn[:-3]
    return None


# ---------------------------------------------------------------- tiện ích
def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x and abs(x) != float('inf') else 0.0


_PEOPLE = r'(?:người|nguoi|pax|people|persons?|guests?|ppl|khách|khach)'
_SIZE_RE = re.compile(r'\(\s*\d{1,3}\s*(?:-|–|—|~|to|đến)\s*\d{1,3}\s*' + _PEOPLE + r'?\s*\)|\d{1,3}\s*' + _PEOPLE + r'(?!\w)|'
                      r'(?:max|tối đa|up to)\s*\d{1,3}', re.I)
_BILLIARDS = re.compile(r'bida|bi-a|billiard|pool|snooker|carom', re.I)


class Report:
    def __init__(self, industry, email):
        self.industry, self.email = industry, email
        self.business_id, self.business_name = None, None
        self.items = []

    def add(self, level, key, detail, fix=None):
        self.items.append({'level': level, 'key': key, 'detail': detail, **({'fix': fix} if fix else {})})

    def need(self, ok, key, detail, fix, required=True):
        self.add(OK if ok else (MISSING if required else WARN), key, detail, None if ok else fix)

    @property
    def missing(self):
        return [i for i in self.items if i['level'] == MISSING]

    def as_dict(self):
        return {'industry': self.industry, 'email': self.email, 'business_id': self.business_id,
                'business': self.business_name, 'ready': not self.missing, 'missing': len(self.missing),
                'warnings': sum(1 for i in self.items if i['level'] == WARN), 'items': self.items}


def _active_products(db, biz, channel=None):
    flt = {'business_id': biz, 'is_active': {'$in': [1, True]}}
    if channel:
        flt['channel_type'] = channel
    return list(db.products.find(flt, {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'held_qty': 1, 'allergens': 1,
                                       'channel_type': 1}).limit(2000))


# ---------------------------------------------------------------- kiểm tra chung
def check_common(db, r, biz, industry, today, env=None):
    env = os.environ if env is None else env
    b = db.businesses.find_one({'id': biz}, {'_id': 0}) or {}
    if not b:
        r.add(MISSING, 'business', f'không có db.businesses id={biz}')
        return None
    r.business_name = b.get('name')
    code = {'nails': 'nail'}.get(str(b.get('industry_code') or '').lower(), str(b.get('industry_code') or '').lower())
    r.need(code == industry, 'industry_code', f"industry_code={b.get('industry_code')!r}", f"đặt industry_code='{industry}'")
    try:
        import plans
        plan = plans.business_plan(db, biz, ttl=0)
        r.need(plans.allows(plan, 'ai_inbox'), 'plan_ai_inbox', f'gói {plan!r} ' + ('có' if plans.allows(plan, 'ai_inbox') else
                                                                                 'KHÔNG có') + " trợ lý AI ('ai_inbox', Pro)",
               'nâng gói tiệm demo lên Pro trở lên — không thì chat chỉ trả câu không-AI')
    except Exception as e:  # plans.py luôn có trong repo; lỗi bất ngờ thì báo, không dừng báo cáo
        r.add(WARN, 'plan_ai_inbox', f'không đọc được gói: {e}')
    bs = db.booking_settings.find_one({'business_id': biz}, {'_id': 0}) or {}
    hours = bs.get('hours') if isinstance(bs.get('hours'), dict) else None
    open_days = [k for k, v in (hours or {}).items() if v]
    r.need(bool(hours), 'opening_hours', f"giờ mở cửa: {len(open_days)} ngày mở" if hours else 'chưa công bố giờ mở cửa',
           'lưu giờ mở cửa ở Cài đặt đặt lịch — không có thì gói không tự xác nhận được, AI không được nói giờ mở cửa',
           required=industry not in ('production', 'office'))
    info = bs.get('info') if isinstance(bs.get('info'), dict) else {}
    addr = b.get('address') or info.get('address')
    r.need(bool(addr), 'address', f'địa chỉ: {addr}' if addr else 'chưa có địa chỉ',
           'nhập địa chỉ tiệm (AI trả lời "ở đâu", khách sạn / kỹ thuật cần)', required=False)
    phone = b.get('phone') or b.get('hotline') or (db.messaging_settings.find_one({'business_id': biz}, {'_id': 0, 'twilio_from': 1})
                                                   or {}).get('twilio_from')
    r.need(bool(phone), 'shop_phone', f'SĐT tiệm: {phone}' if phone else 'chưa có SĐT tiệm',
           'nhập SĐT tiệm (AI hướng khách gọi khi cần người thật)', required=False)
    tz = (db.messaging_settings.find_one({'business_id': biz}, {'_id': 0, 'timezone': 1}) or {}).get('timezone')
    tz_src = 'Nhắn tin' if tz else ('theo quốc gia' if COUNTRY_TZ.get(str(b.get('country') or '').upper()) else None)
    tz = tz or COUNTRY_TZ.get(str(b.get('country') or '').upper())
    r.need(bool(tz), 'timezone', f'múi giờ {tz} ({tz_src})' if tz else 'không có múi giờ / quốc gia',
           'đặt múi giờ ở trang Nhắn tin — giờ đặt chỗ phải là giờ tiệm')
    cur = str(b.get('currency') or '').upper()
    r.need(cur in ('USD', 'AUD', 'CAD', 'NZD', 'GBP'), 'currency',
           f'tiền tệ {cur or "(trống)"}', 'demo bán cho khách Mỹ/Úc phải là đô (từ 2026-10-25 mọi demo đều USD/AUD)', required=False)
    pol = [k for k in ('cancellation_policy', 'parking', 'payments') if info.get(k)]
    r.need(bool(pol), 'policies', f"chính sách đã công bố: {', '.join(pol)}" if pol else 'chưa có chính sách huỷ / gửi xe / thanh toán',
           'điền "Thông tin tiệm" (huỷ lịch, gửi xe, thanh toán) — AI chỉ được nói điều chủ đã ghi', required=False)
    try:
        kb = db.ai_knowledge.count_documents({'business_id': biz, 'active': {'$ne': False}})
    except Exception:
        kb = 0
    r.need(kb > 0, 'knowledge_base', f'{kb} mục hỏi đáp của chủ (db.ai_knowledge)',
           'thêm vài câu hỏi đáp thường gặp ở trang Kiến thức AI', required=False)
    pack = pack_module(industry) or ('builtin (ai_function_tools)' if industry in ('nail', 'spa') else None)
    r.need(bool(pack), 'booking_pack', f'gói đặt chỗ: {pack}' if pack else f"chưa có gói ai_packs cho '{industry}' trong mã nguồn",
           f"gộp nhánh gói đặt chỗ {PACK_RESOURCE[industry]} (Phase 2)")
    flag = (env.get('BITPAW_AI_SIM_PASSED') or '')
    passed = industry in {x.strip().lower() for x in flag.split(',') if x.strip()}
    if not passed:
        try:
            val = (db.system_settings.find_one({'key': 'ai_sim_passed'}, {'_id': 0, 'value': 1}) or {}).get('value')
        except Exception:
            val = None
        if isinstance(val, (list, tuple, set)):
            passed = industry in {str(x).lower() for x in val}
        elif isinstance(val, dict):
            v = val.get(industry)
            passed = v is True or (isinstance(v, dict) and v.get('passed') is True)
    r.add(INFO, 'claim_answers_and_books', 'đã qua giả lập — được nói "AI trả lời & đặt chỗ"' if passed else
          'chưa đánh dấu qua giả lập — giữ câu "AI trả lời & chuyển yêu cầu" (chủ quyết định sau khi xem kết quả sim)')
    return {'business': b, 'settings': bs, 'hours': hours}


# ---------------------------------------------------------------- theo ngành
def _appointments(db, r, biz, industry, today):
    prods = [p for p in _active_products(db, biz) if _num(p.get('price')) > 0]
    r.need(bool(prods), 'services', f'{len(prods)} dịch vụ đang bán có giá', 'thêm dịch vụ + giá')
    if industry == 'nail':
        team = db.employees.count_documents({'business_id': biz, 'linh_vuc': 'Nails'})
        r.need(team > 0, 'technicians', f'{team} thợ Nails (employees.linh_vuc=Nails)', 'thêm thợ ở trang Nhân viên')
    else:
        team = db.staff.count_documents({'business_id': biz, 'is_active': {'$ne': False}})
        r.need(team > 0, 'therapists', f'{team} kỹ thuật viên (db.staff)', 'thêm kỹ thuật viên')
    shifts = db.roster_shifts.count_documents({'business_id': biz, 'status': 'published', 'date': {
        '$gte': today.isoformat(), '$lte': (today + timedelta(days=14)).isoformat()}})
    r.need(shifts > 0, 'roster_next_14_days', f'{shifts} ca đã công bố trong 14 ngày tới',
           'công bố Lịch ca tuần — không có thì sức chứa = số thợ (có thể đặt cho thợ nghỉ)', required=False)


def _auto_confirm_item(r, key, settings, sub_key, what):
    """Tự xác nhận THẬT của AI đặt chỗ (= reservations_core.load_rules qua scenarios_common.auto_confirm_of, cùng luật với
    giả lập): khối riêng > công tắc chung chỉ khi chủ đã lưu ở trang Cài đặt đặt chỗ > chờ duyệt."""
    from scenarios_common import GENERAL_SAVED_MARK, auto_confirm_of
    auto = auto_confirm_of(settings, sub_key)
    sub = settings.get(sub_key) if isinstance(settings.get(sub_key), dict) else {}
    if isinstance(sub.get('auto_confirm'), bool):
        why = 'lựa chọn riêng ở mục Đặt chỗ'
    elif 'auto_confirm' in settings and settings.get(GENERAL_SAVED_MARK):
        why = 'theo công tắc chung chủ đã lưu'
    elif settings.get('auto_confirm'):
        why = 'công tắc chung chưa lưu ở trang Cài đặt đặt chỗ — auto_confirm=True của trang cũ (mặc định Nails) không tính'
    else:
        why = 'chưa bật'
    r.add(INFO, key, f"tự xác nhận {what}: {auto} ({why}; False = chờ quán duyệt)")


def _fnb(db, r, biz, ctx, today):
    tables = list(db.dining_tables.find({'business_id': biz}, {'_id': 0, 'id': 1, 'seats': 1, 'capacity': 1}))
    seated = [t for t in tables if _num(t.get('seats') or t.get('capacity')) > 0]
    r.need(bool(tables), 'dining_tables', f'{len(tables)} bàn', 'thêm bàn ở Sơ đồ bàn')
    rs = ctx['settings'].get('table_reservations') if isinstance(ctx['settings'].get('table_reservations'), dict) else {}
    covers = _num(rs.get('max_covers_per_slot'))
    cap = ([f'{int(covers)} khách / khung giờ'] if covers else []) + ([f'{len(seated)}/{len(tables)} bàn có số ghế'] if seated else [])
    r.need(bool(covers or seated), 'table_capacity',
           ('sức chứa: ' + '; '.join(cap)) if cap else 'chưa nhập sức chứa (số khách / khung giờ hoặc số ghế từng bàn)',
           'nhập sức chứa — không có thì AI chỉ ghi YÊU CẦU chờ duyệt, không bao giờ nói "còn bàn"', required=False)
    _auto_confirm_item(r, 'table_auto_confirm', ctx['settings'], 'table_reservations', 'đặt bàn')
    menu = _active_products(db, biz)
    r.need(bool(menu), 'menu', f'{len(menu)} món đang bán', 'thêm thực đơn + giá', required=False)
    al = sum(1 for p in menu if p.get('allergens'))
    r.need(al > 0, 'allergens', f'{al}/{len(menu)} món có ghi dị ứng',
           'ghi thành phần gây dị ứng cho món — không có thì AI phải nói "để em hỏi bếp"', required=False)


def _karaoke(db, r, biz, ctx, today):
    rooms = list(db.karaoke_rooms.find({'business_id': biz}, {'_id': 0}))
    priced = [x for x in rooms if _num(x.get('price_per_hour')) > 0]
    sized = [x for x in rooms if _num(x.get('max_guests') or x.get('capacity') or x.get('size')) > 0 or _SIZE_RE.search(str(x.get('name') or ''))]
    pool = [x for x in rooms if _BILLIARDS.search(f"{x.get('name')} {x.get('room_type') or ''}")]
    r.need(bool(rooms), 'karaoke_rooms', f'{len(rooms)} phòng / bàn ({len(pool)} bàn bi-a)', 'thêm phòng ở trang Phòng hát')
    r.need(bool(rooms) and len(priced) == len(rooms), 'room_rates', f'{len(priced)}/{len(rooms)} phòng có giá giờ',
           'nhập giá giờ cho mọi phòng (AI báo giá = giá giờ x số giờ)')
    r.need(bool(rooms) and len(sized) == len(rooms), 'room_sizes', f'{len(sized)}/{len(rooms)} phòng biết sức chứa',
           'ghi sức chứa (vd "Phòng Gia Đình (6-8 người)") — phòng không rõ sức chứa chỉ nhận yêu cầu chờ duyệt', required=False)
    rs = ctx['settings'].get('karaoke_reservations') if isinstance(ctx['settings'].get('karaoke_reservations'), dict) else {}
    r.need(bool(rs.get('hold_minutes')), 'release_policy', f"giữ phòng khi tới trễ: {rs.get('hold_minutes') or 'chưa công bố'}",
           'công bố số phút giữ phòng khi khách tới trễ', required=False)
    _auto_confirm_item(r, 'karaoke_auto_confirm', ctx['settings'], 'karaoke_reservations', 'đặt phòng hát')
    menu = _active_products(db, biz)
    r.add(INFO, 'drinks_menu', f'{len(menu)} món đồ uống / đồ ăn (đặt trước = ghi chú cho nhân viên)')


def _hotel(db, r, biz, ctx, today):
    rooms = list(db.hotel_rooms.find({'business_id': biz}, {'_id': 0, 'room_type': 1, 'price_per_night': 1, 'capacity': 1}))
    types = sorted({str(x.get('room_type') or '').strip() or 'Standard' for x in rooms})
    priced = [x for x in rooms if _num(x.get('price_per_night')) > 0]
    cap = [x for x in rooms if _num(x.get('capacity')) > 0]
    r.need(bool(rooms), 'hotel_rooms', f"{len(rooms)} phòng, {len(types)} loại: {', '.join(types[:6])}",
           'thêm phòng (số phòng, loại, giá đêm, sức chứa) ở trang Phòng khách sạn')
    r.need(bool(rooms) and len(priced) == len(rooms), 'room_rates', f'{len(priced)}/{len(rooms)} phòng có giá đêm',
           'nhập giá đêm cho mọi phòng (loại phòng thiếu giá không bao giờ tự xác nhận)')
    r.need(bool(rooms) and len(cap) == len(rooms), 'room_capacity', f'{len(cap)}/{len(rooms)} phòng có sức chứa',
           'nhập sức chứa từng phòng (phòng gia đình)', required=False)
    hs = ctx['settings'].get('hotel') if isinstance(ctx['settings'].get('hotel'), dict) else {}
    r.need(bool(hs.get('checkin_time') and hs.get('checkout_time')), 'checkin_checkout_times',
           f"nhận phòng {hs.get('checkin_time') or '?'} / trả phòng {hs.get('checkout_time') or '?'}",
           'công bố giờ nhận / trả phòng', required=False)
    r.need(hs.get('free_cancel_hours') is not None, 'cancellation_policy',
           f"huỷ miễn phí trước {hs.get('free_cancel_hours')} giờ" if hs.get('free_cancel_hours') is not None else 'chưa công bố hạn huỷ miễn phí',
           'công bố hạn huỷ miễn phí (AI nói chính sách trước khi xác nhận)', required=False)
    r.add(INFO, 'hotel_auto_confirm', f"tự xác nhận đặt phòng: {bool(hs.get('auto_confirm'))}")


def _retail(db, r, biz, ctx, today):
    prods = _active_products(db, biz, 'retail')
    stocked = [p for p in prods if _num(p.get('stock')) - _num(p.get('held_qty')) > 0]
    r.need(bool(prods), 'retail_products', f'{len(prods)} sản phẩm bán lẻ đang bán', 'thêm sản phẩm (kênh bán lẻ)')
    r.need(bool(stocked), 'stock', f'{len(stocked)}/{len(prods)} sản phẩm còn hàng (stock - held_qty > 0)',
           'nhập tồn kho — hết sạch thì không giữ hàng được')
    r.add(INFO, 'out_of_stock', f'{len(prods) - len(stocked)} sản phẩm hết hàng')
    holds = db.retail_holds.count_documents({'business_id': biz, 'status': {'$in': ['pending', 'ready']}})
    r.add(INFO, 'active_holds', f'{holds} hold đang giữ')


def _technical(db, r, biz, ctx, today):
    techs = db.employees.count_documents({'business_id': biz})
    r.need(techs > 0, 'technicians', f'{techs} nhân viên kỹ thuật', 'thêm thợ ở trang Nhân viên')
    svcs = list(db.dichvu.find({'business_id': biz}, {'_id': 0, 'gia_dich_vu': 1}))
    priced = [s for s in svcs if _num(s.get('gia_dich_vu')) > 0]
    r.need(bool(priced), 'service_price_list', f'{len(priced)}/{len(svcs)} dịch vụ có giá (db.dichvu)',
           'thêm bảng giá dịch vụ — không có thì AI không được báo giá', required=False)
    jobs = db.tasks.count_documents({'business_id': biz})
    r.add(INFO, 'job_board', f'{jobs} việc trên bảng điều phối (db.tasks)')


def _production(db, r, biz, ctx, today):
    prods = _active_products(db, biz)
    r.need(bool(prods), 'products', f'{len(prods)} sản phẩm xưởng làm', 'thêm danh mục sản phẩm (AI hỏi đúng sản phẩm khi nhận báo giá)')
    r.add(INFO, 'quote_requests', f"{db.quote_requests.count_documents({'business_id': biz})} yêu cầu báo giá đã có")


def _office(db, r, biz, ctx, today):
    svcs = _active_products(db, biz)
    r.need(bool(svcs), 'services', f'{len(svcs)} dịch vụ / phí tư vấn', 'thêm dịch vụ + phí (AI không được tự báo phí)',
           required=False)
    n = db.consult_requests.count_documents({'business_id': biz}) + db.consultation_requests.count_documents({'business_id': biz})
    r.add(INFO, 'consult_requests', f'{n} yêu cầu tư vấn đã có')


SPECIFIC = {'fnb': _fnb, 'karaoke': _karaoke, 'hotel': _hotel, 'retail': _retail, 'technical': _technical,
            'production': _production, 'office': _office}


def check_industry(db, industry, email=None, biz=None, today=None, env=None):
    today = today or date.today()
    r = Report(industry, email)
    if not biz:
        u = db.users.find_one({'email': email}, {'_id': 0, 'business_id': 1}) if email else None
        biz = (u or {}).get('business_id')
    if not biz:
        r.add(MISSING, 'demo_account', f'không tìm thấy tài khoản demo {email}', 'chạy setup_demo_other_industries.py cho ngành này')
        return r
    r.business_id = biz
    ctx = check_common(db, r, biz, industry, today, env=env)
    if ctx is None:
        return r
    if industry in ('nail', 'spa'):
        _appointments(db, r, biz, industry, today)
    else:
        SPECIFIC[industry](db, r, biz, ctx, today)
    return r


def run_report(db, industries=INDUSTRIES, accounts=None, biz=None, today=None, env=None):
    accounts = accounts or demo_accounts()
    env = os.environ if env is None else env
    out = []
    for ind in industries:
        var, default = accounts[ind]
        email = env.get(var) or default
        out.append(check_industry(db, ind, email=email, biz=biz, today=today, env=env))
    return out


def render(reports):
    lines = []
    for r in reports:
        head = f"== {r.industry.upper():<10} {r.email or ''}  biz={r.business_id or '-'}  {r.business_name or ''}"
        lines.append(head)
        for i in r.items:
            lines.append(f"   [{i['level']:<7}] {i['key']:<24} {i['detail']}" + (f"  -> {i['fix']}" if i.get('fix') else ''))
        lines.append(f"   => {'SẴN SÀNG cho giả lập' if not r.missing else f'CHƯA sẵn sàng ({len(r.missing)} mục thiếu)'}")
    ready = [r.industry for r in reports if not r.missing]
    lines.append(f"\nSẵn sàng: {', '.join(ready) or 'không ngành nào'} | chưa: "
                 f"{', '.join(r.industry for r in reports if r.missing) or 'không'}")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Báo cáo CHỈ ĐỌC: dữ liệu tiệm demo cho gói đặt chỗ AI từng ngành.')
    ap.add_argument('--industry', default=','.join(INDUSTRIES), help='danh sách ngành, phân cách dấu phẩy')
    ap.add_argument('--biz', default=None, help='business_id (chỉ khi --industry là 1 ngành)')
    ap.add_argument('--json', default=None, help='ghi thêm kết quả JSON vào file này')
    a = ap.parse_args(argv)
    inds = [x.strip() for x in a.industry.split(',') if x.strip()]
    bad = [x for x in inds if x not in INDUSTRIES]
    if bad:
        raise SystemExit(f'Ngành không hợp lệ: {bad}')
    if a.biz and len(inds) != 1:
        raise SystemExit('--biz chỉ dùng với đúng 1 ngành')
    from mongo_client import db as real_db   # đọc .env, nối MongoDB — chỉ dùng qua ReadOnlyDB
    reports = run_report(ReadOnlyDB(real_db), inds, biz=a.biz)
    print(render(reports))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump([r.as_dict() for r in reports], f, ensure_ascii=False, indent=2)
    return reports


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    main()
