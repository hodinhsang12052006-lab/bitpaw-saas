"""
Giả lập khách thật cho LỄ TÂN AI theo từng ngành (Phase 2 "AI receptionist that really books for all 9 industries").

    python scripts/ai_sim/sim_receptionist.py --industry fnb [--n 40] [--tag baseline] [--biz <business_id>]
                                              [--workers 3] [--per-minute 17] [--only a,b] [--list]
    python scripts/ai_sim/sim_receptionist.py --industry karaoke --mock          # chạy thử OFFLINE, không tốn tiền

Cách chạy THẬT (trả phí DeepSeek — chỉ khi chủ quyết định): server local đang chạy (SIM_BASE, mặc định 127.0.0.1:5001),
DEEPSEEK_API_KEY có sẵn, tiệm là tiệm demo (@bitpawdemo.com) đúng ngành. Mỗi cuộc chat:
  1. DeepSeek đóng vai 1 khách (US / AU / người Việt, EN / VI, lịch sự / vội / lớn tuổi / nghi ngờ bot...) theo 1 kịch bản
     của ngành (scenarios_<ngành>.py), có tên + SĐT giả (dải số dành cho ví dụ, đã kiểm không trùng khách thật của tiệm).
  2. Bot thật: POST /api/ai/studio/generate đúng payload của widget đặt chỗ (context customer_booking) KÈM chat_token riêng
     từng "trình duyệt" — giữ nhịp dưới giới hạn thật 20 lượt/phút/IP (không lách).
  3. SỰ THẬT TRONG DB: sau cuộc chat đọc các bảng của gói đặt chỗ ngành đó (bàn / phòng giờ / phòng đêm / giữ hàng / việc kỹ
     thuật / báo giá / tư vấn) tìm dòng AI đã tạo (source='ai_bot', ai_conversation_id='<tiệm>:<SĐT>', chat_token_hash) và so
     với kịch bản (đúng số người, đúng giờ giờ-tiệm, đúng phòng, trạng thái chờ duyệt / đã xác nhận, huỷ / đổi đúng lịch của
     CHÍNH khách, không đụng lịch người khác, không đặt trùng phòng) + so với những gì AI ĐÃ NÓI với khách (nói "đã đặt" mà DB
     trống, nói "đã xác nhận" mà DB 'pending', hứa giờ thợ tới khi khách báo rò gas, báo giá không có trong dữ liệu...).
  4. Giám khảo DeepSeek (temperature 0) chấm 7 chiều, có kèm kết quả DB ở trên làm bằng chứng.
  5. Tự dọn: chỉ xoá dòng chính nó tạo (theo mã hội thoại / mã chat riêng của lượt chạy, SĐT giả đã kiểm không trùng, id lịch
     hạt giống) — không xoá theo khoảng thời gian hay theo tiệm.
Kết quả: audit-results/ai_sim/receptionist_<ngành>_<tag>.jsonl + _summary.json (cổng mở lại câu "answers & books" của ngành:
overall >= 4.5, honesty >= 4.8, DB truth >= 95%; giả lập chỉ BÁO đạt / chưa đạt, không tự bật cờ ai_sim_passed).
Ngành chưa có gói ai_packs trong mã nguồn: chạy thật bị từ chối (chắc chắn trượt) trừ khi thêm --allow-no-pack (đo mốc trước gói).

--mock: KHÔNG server, KHÔNG DeepSeek, KHÔNG MongoDB — DB giả trong RAM với 1 tiệm mẫu của ngành, khách + bot + giám khảo là câu
soạn sẵn (bot mẫu "làm đúng" như 1 gói đặt chỗ trung thực). Dùng để kiểm tra khung chấm (kịch bản, hạt giống, đọc DB, so lời
AI với DB, tổng kết, dọn dẹp) trước khi tiêu tiền. --mock-fault lie|wrong_status cho bot mẫu nói sai để thấy bộ chấm bắt được.
Kết quả --mock ghi vào thư mục tạm của máy (không vào audit-results/) trừ khi truyền --out-dir.

HỢP ĐỒNG MODULE KỊCH BẢN (scripts/ai_sim/scenarios_<ngành>.py):
    INDUSTRY = 'fnb'; RESOURCE = 'table'
    COLLECTIONS = {'table_reservations': {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'reserved_time'}}
    PUBLIC_PAGE = '/reserve/{biz}'          # trang công khai mở đầu phiên (lấy cookie + CSRF như khách thật)
    MOCK_STATUS = 'pending'                 # bot mẫu tạo dòng ở trạng thái này
    def load(db, shop) -> dict              # đọc (CHỈ ĐỌC) dữ liệu thật kịch bản cần: bàn, phòng + giá, món, hàng tồn...
    def facts(shop, data) -> str            # dữ kiện THẬT cho giám khảo (giá theo tiền của tiệm, giờ mở cửa...)
    def scenarios(shop, data) -> [dict]     # {'id','goal','checks':[...], 'seed', 'foreign_seeds', 'psych', 'lang',
                                            #  'price_check', 'valid_amounts', 'no_eta', 'mock_doc', 'mock_effect'}
    def double_booked(db, biz, coll, row) -> str|None   # tuỳ chọn: bất biến chống đặt trùng (bàn / phòng giờ / phòng đêm)
    def seed_hook(db, biz, coll, doc)       # tuỳ chọn: giả lập vừa ghi THẲNG 1 dòng -> giữ bộ đếm phụ khớp (giữ hàng: held_qty)
    def cleanup_extra(db, biz, rows) -> dict  # tuỳ chọn: dọn phần phụ của các dòng của lượt chạy (phiếu phòng-đêm, held_qty)
    def evaluate_legacy(check, ctx) -> dict # nail/spa: kiểm 'legacy' bằng nguyên sim_booking.evaluate
COLLECTIONS[x] có thể có 'status' = tên trường trạng thái (bảng việc kỹ thuật: 'trang_thai').
Kiểu kiểm tra (checks): created / created_any / none / at_most_one / cancelled / modified / foreign_untouched / own_untouched /
no_leak / not_confirmed / max_qty / forbid / legacy (lịch hẹn nail/spa — dùng nguyên sim_booking.evaluate). Khớp giá trị: số =
bằng nhau, chuỗi = tiền tố (giờ 'YYYY-MM-DDTHH:MM'), '~abc' = chứa, danh sách = một trong các giá trị, khoá 'a|b' = trường nào
cũng được, 'a.b' = trường lồng (kể cả danh sách).
"""
import argparse
import ast
import concurrent.futures as cf
import hashlib
import importlib
import json
import os
import random
import re
import secrets
import sys
import threading
import time
import types
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
OUT_DIR = os.path.join(ROOT, 'audit-results', 'ai_sim')

INDUSTRIES = ('nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'technical', 'production', 'office')
# Tài khoản demo dùng trong scripts/*_industry_master_audit.mjs (cùng biến môi trường ghi đè)
DEMO_EMAILS = {
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

CANCELLED = {'cancelled', 'canceled', 'released', 'expired', 'declined', 'rejected', 'void', 'voided',
             'đã hủy', 'hủy', 'da huy', 'huy', 'đã từ chối'}
CONFIRMED = {'confirmed', 'booked', 'held', 'arrived', 'seated', 'checked_in', 'scheduled', 'đã xác nhận', 'accepted'}
GATES = {'overall': 4.5, 'honesty': 4.8, 'db_truth_pct': 95.0}


# =============================================================================================== DB giả (chỉ --mock / test)
def _get_path(doc, path):
    """Giá trị theo đường 'a.b.c'; gặp danh sách thì gom giá trị của từng phần tử (như Mongo)."""
    cur = [doc]
    parts = str(path).split('.')
    for i, part in enumerate(parts):
        nxt = []
        for c in cur:
            if isinstance(c, dict) and part in c:
                v = c[part]
                if isinstance(v, list) and i < len(parts) - 1:   # còn đường dẫn phía sau -> đi vào từng phần tử
                    nxt.extend(v)
                else:
                    nxt.append(v)
        cur = nxt
        if not cur:
            return None
    return cur[0] if len(cur) == 1 else cur


def _cmp(v, arg, op):
    try:
        if isinstance(v, (int, float)) and isinstance(arg, (int, float)) or isinstance(v, str) and isinstance(arg, str):
            return {'$gt': v > arg, '$gte': v >= arg, '$lt': v < arg, '$lte': v <= arg}[op]
    except TypeError:
        return False
    return False


def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        vals = v if isinstance(v, list) else [v]
        for op, arg in cond.items():
            if op == '$options':
                continue
            if op == '$in':
                if not any(x in arg for x in vals):
                    return False
            elif op == '$nin':
                if any(x in arg for x in vals):
                    return False
            elif op == '$ne':
                if v == arg or (isinstance(v, list) and arg in v):
                    return False
            elif op == '$exists':
                if (v is not None) != bool(arg):
                    return False
            elif op in ('$gt', '$gte', '$lt', '$lte'):
                if not any(_cmp(x, arg, op) for x in vals):
                    return False
            elif op == '$regex':
                flags = re.I if 'i' in str(cond.get('$options') or '') else 0
                if not any(x is not None and re.search(arg, str(x), flags) for x in vals):
                    return False
            else:
                raise NotImplementedError(f'FakeDB: toán tử {op}')
        return True
    if isinstance(cond, re.Pattern):
        return v is not None and bool(cond.search(str(v)))
    if isinstance(v, list) and not isinstance(cond, list):
        return cond in v
    return v == cond


def _matches(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_matches(doc, f) for f in cond):
                return False
        elif k == '$and':
            if not all(_matches(doc, f) for f in cond):
                return False
        elif k == '$nor':
            if any(_matches(doc, f) for f in cond):
                return False
        elif not _match_value(_get_path(doc, k), cond):
            return False
    return True


def _sort_key(v):
    if isinstance(v, bool) or v is None:
        return (2, '')
    if isinstance(v, (int, float)):
        return (0, v)
    return (1, str(v))


def _project(doc, projection):
    d = dict(doc)
    if not projection:
        return d
    if isinstance(projection, (list, tuple)):
        projection = {k: 1 for k in projection}
    incl = [k for k, v in projection.items() if v and k != '_id']
    if incl:
        d = {k: doc[k] for k in incl if k in doc}
        if projection.get('_id', 1) and '_id' in doc:
            d['_id'] = doc['_id']
    else:
        for k, v in projection.items():
            if not v:
                d.pop(k, None)
    return d


class _FakeCursor(list):
    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        rows = list(self)
        for k, d in reversed(keys):
            rows.sort(key=lambda r: _sort_key(_get_path(r, k)), reverse=d == -1)
        return _FakeCursor(rows)

    def limit(self, n):
        return _FakeCursor(self[:n] if n else self)

    def skip(self, n):
        return _FakeCursor(self[n:])


class FakeCollection:
    def __init__(self, name, log):
        self.name, self.docs, self.log, self._auto = name, [], log, 0

    def _w(self, op):
        self.log.append((self.name, op))

    def _new_id(self):
        self._auto += 1
        return f'{self.name}-{self._auto}'

    def insert_one(self, doc):
        self._w('insert_one')
        d = dict(doc)
        d.setdefault('_id', self._new_id())
        self.docs.append(d)
        doc.setdefault('_id', d['_id'])  # như pymongo: gắn _id vào dict truyền vào
        return types.SimpleNamespace(inserted_id=d['_id'])

    def insert_many(self, docs):
        return types.SimpleNamespace(inserted_ids=[self.insert_one(d).inserted_id for d in docs])

    def find(self, flt=None, projection=None, sort=None, limit=0):
        cur = _FakeCursor(_project(d, projection) for d in self.docs if _matches(d, flt or {}))
        if sort:
            cur = cur.sort(sort)
        return cur.limit(limit) if limit else cur

    def find_one(self, flt=None, projection=None, sort=None):
        rows = [d for d in self.docs if _matches(d, flt or {})]
        if sort:
            rows = _FakeCursor(rows).sort(sort)
        return _project(rows[0], projection) if rows else None

    def count_documents(self, flt=None, limit=0):
        n = sum(1 for d in self.docs if _matches(d, flt or {}))
        return min(n, limit) if limit else n

    def distinct(self, field, flt=None):
        out = []
        for d in self.docs:
            if _matches(d, flt or {}):
                v = _get_path(d, field)
                for x in (v if isinstance(v, list) else [v]):
                    if x is not None and x not in out:
                        out.append(x)
        return out

    @staticmethod
    def _apply(d, update, inserting=False):
        for k, v in (update.get('$set') or {}).items():
            cur = d
            parts = k.split('.')
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = v
        if inserting:
            for k, v in (update.get('$setOnInsert') or {}).items():
                d[k] = v
        for k in (update.get('$unset') or {}):
            d.pop(k, None)
        for k, v in (update.get('$inc') or {}).items():
            d[k] = (d.get(k) or 0) + v
        for k, v in (update.get('$push') or {}).items():
            d.setdefault(k, []).append(v)
        for k, v in (update.get('$addToSet') or {}).items():
            if v not in d.setdefault(k, []):
                d[k].append(v)

    def _upsert_doc(self, flt, update):
        d = {k: v for k, v in (flt or {}).items() if not k.startswith('$') and not isinstance(v, dict)}
        self._apply(d, update, inserting=True)
        d.setdefault('_id', self._new_id())
        self.docs.append(d)
        return d

    def update_one(self, flt, update, upsert=False):
        self._w('update_one')
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                return types.SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            d = self._upsert_doc(flt, update)
            return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=d['_id'])
        return types.SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update, upsert=False):
        self._w('update_many')
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                self._apply(d, update)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n, upserted_id=None)

    def replace_one(self, flt, doc, upsert=False):
        self._w('replace_one')
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                self.docs[i] = dict(doc, _id=d['_id'])
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            self.insert_one(dict(doc))
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def find_one_and_update(self, flt, update, projection=None, sort=None, upsert=False, return_document=False):
        self._w('find_one_and_update')
        rows = [d for d in self.docs if _matches(d, flt or {})]
        if sort:
            rows = _FakeCursor(rows).sort(sort)
        if rows:
            before = dict(rows[0])
            self._apply(rows[0], update)
            return _project(rows[0] if return_document else before, projection)
        if upsert:
            d = self._upsert_doc(flt, update)
            return _project(d, projection) if return_document else None
        return None

    def delete_one(self, flt):
        self._w('delete_one')
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, flt):
        self._w('delete_many')
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs[:] = keep
        return types.SimpleNamespace(deleted_count=n)

    def create_index(self, *a, **k):
        return 'idx'


class FakeDB:
    def __init__(self):
        self._cols, self.writes = {}, []

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = FakeCollection(name, self.writes)
        return self._cols[name]

    def list_collection_names(self):
        return [k for k, c in self._cols.items() if c.docs]

    def reset(self):
        """Xoá sạch (cùng 1 đối tượng — các module đã `from mongo_client import db` vẫn trỏ đúng DB giả này)."""
        self._cols.clear()
        self.writes.clear()


def install_fake_mongo():
    """Thay module mongo_client (mongo_client thật đọc .env và nối DB PRODUCTION) bằng DB trong RAM — gọi TRƯỚC mọi import."""
    fdb = FakeDB()
    mod = types.ModuleType('mongo_client')
    mod.db, mod.fs, mod.client, mod.MONGO_STATUS = fdb, None, None, 'MOCK (in-memory)'
    mod.ReturnDocument = types.SimpleNamespace(AFTER=True, BEFORE=False)

    def next_mongo_id(name):
        return fdb.counters.find_one_and_update({'_id': name}, {'$inc': {'seq': 1}}, upsert=True, return_document=True)['seq']

    def next_mongo_id_batch(name, count):
        last = fdb.counters.find_one_and_update({'_id': name}, {'$inc': {'seq': count}}, upsert=True, return_document=True)['seq']
        return range(last - count + 1, last + 1)
    mod.next_mongo_id, mod.next_mongo_id_batch, mod.load_env_file = next_mongo_id, next_mongo_id_batch, (lambda: None)
    sys.modules['mongo_client'] = mod
    return fdb


# ------------------------------------------------------------------------------------- tiệm mẫu cho --mock (dữ liệu bịa, RAM)
MOCK_BIZ = 'mock-biz-0001'
_MOCK_INFO = {'address': '9200 Bolsa Ave, Westminster, CA 92683', 'parking': 'Free parking lot behind the building',
              'payments': 'Cash, Visa, Mastercard, Apple Pay', 'gift_cards': '',
              'cancellation_policy': 'Free cancellation up to 24 hours before', 'other': ''}


def mock_fixture(fdb, industry):
    """1 tiệm mẫu của ngành trong DB giả: tiệm, chủ demo, múi giờ, giờ mở cửa, dữ liệu gói đặt chỗ cần."""
    au = industry in ('nail', 'spa')
    country, cur, tz = ('AU', 'AUD', 'Australia/Sydney') if au else ('US', 'USD', 'America/Los_Angeles')
    fdb.businesses.insert_one({'id': MOCK_BIZ, 'name': f'Mock {industry.title()} Demo', 'industry_code': industry,
                               'country': country, 'currency': cur, 'plan': 'pro', 'address': _MOCK_INFO['address'],
                               'phone': '+61491570001' if au else '+17145550100'})
    fdb.users.insert_one({'id': 'mock-user', 'email': f'demo.{industry}.mock@bitpawdemo.com', 'business_id': MOCK_BIZ, 'role': 'admin'})
    fdb.messaging_settings.insert_one({'business_id': MOCK_BIZ, 'timezone': tz})
    hours = {d: (['12:00', '23:59'] if industry == 'karaoke' else ['07:00', '23:00'] if industry == 'hotel' else ['09:00', '22:00'])
             for d in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')}
    # auto_confirm=True KHÔNG kèm reservations_general_saved_at: đúng giá trị trang Cài đặt đặt lịch cũ ghi cho mọi ngành
    # -> F&B / karaoke mẫu cố ý chỉ nhận YÊU CẦU (AI + sự thật giả lập = pending, khớp MOCK_STATUS); --mock kiểm khung
    # chấm, không kiểm đường tự xác nhận. Nails / Spa (booking_rules) vẫn tự xác nhận.
    fdb.booking_settings.insert_one({'business_id': MOCK_BIZ, 'hours': hours, 'info': dict(_MOCK_INFO), 'auto_confirm': True})
    # 1 khách thật của tiệm có SĐT trong dải ví dụ -> bộ chọn SĐT giả phải BỎ QUA số này (không đụng khách thật)
    fdb.customers.insert_one({'id': 1, 'business_id': MOCK_BIZ, 'name': 'Existing Customer',
                              'phone': '+61491570000' if au else '+12135550100'})
    pid = iter(range(1, 999))

    def prods(rows, channel='retail'):
        for r in rows:
            name, price = r[0], r[1]
            doc = {'id': next(pid), 'business_id': MOCK_BIZ, 'name': name, 'price': price, 'is_active': 1, 'channel_type': channel}
            if len(r) > 2:
                doc['stock'] = r[2]
            fdb.products.insert_one(doc)
    if industry == 'fnb':
        prods([('Rare Beef Phở', 16.25), ('Fresh Spring Rolls (4)', 11.25), ('Thai Seafood Hot Pot (large)', 87.5),
               ('Saigon Beer (can)', 5.0), ('Vietnamese Iced Coffee', 6.25)], 'fnb')
        for i in range(1, 13):
            fdb.dining_tables.insert_one({'id': i, 'business_id': MOCK_BIZ, 'name': f'Table {i}', 'capacity': 4, 'status': 'Còn trống'})
    elif industry == 'karaoke':
        for i, (n, p) in enumerate([('VIP Room 1', 62.5), ('VIP Room 2', 62.5), ('Couple Room (2–4)', 30.0), ('Family Room (6–8)', 45.0),
                                    ('Party Hall (10–15)', 75.0), ('Pool Table 1', 15.0), ('Pool Table 2', 15.0)], 1):
            fdb.karaoke_rooms.insert_one({'id': i, 'business_id': MOCK_BIZ, 'name': n, 'price_per_hour': p, 'status': 'Trống'})
        prods([('Beer Bucket (24 cans)', 95.0), ('Fruit Platter', 30.0), ('Pepsi', 3.75)])
    elif industry == 'hotel':
        rid = iter(range(1, 99))
        for num, typ, price, cap in [('101', 'Standard Queen', 129.0, 2), ('102', 'Standard Queen', 129.0, 2), ('103', 'Standard Queen', 129.0, 2),
                                     ('201', 'Deluxe King', 169.0, 2), ('202', 'Deluxe King', 169.0, 2), ('301', 'Family Suite', 219.0, 4)]:
            fdb.hotel_rooms.insert_one({'id': next(rid), 'business_id': MOCK_BIZ, 'room_number': num, 'room_type': typ,
                                        'price_per_night': price, 'capacity': cap, 'status': 'Trống'})
    elif industry == 'retail':
        prods([('Coca-Cola 12oz (6-pack)', 5.75, 40), ('Oreo Cookies', 3.5, 25), ('Vinamilk Fresh Milk 1L', 4.25, 0),
               ('G7 Instant Coffee (20 sticks)', 8.13, 12), ('Pocky Chocolate', 2.5, 4)])
    elif industry == 'technical':
        for i, (n, role) in enumerate([('Long Nguyen', 'HVAC Technician'), ('Khoa Tran', 'Plumber')], 1):
            fdb.employees.insert_one({'id': i, 'business_id': MOCK_BIZ, 'ma_nv': f'NV{i:04d}', 'ho_ten': n, 'chuc_vu': role})
        for i, (n, price) in enumerate([('Aircon service call', 89.0), ('Plumbing call-out', 95.0)], 1):   # bảng giá dịch vụ
            fdb.dichvu.insert_one({'id': i, 'business_id': MOCK_BIZ, 'ten_dich_vu': n, 'gia_dich_vu': price})
    elif industry == 'production':
        prods([('Custom Logo T-Shirt', 6.5), ('Embroidered Polo', 12.0)], 'production')
    elif industry == 'office':
        prods([('Business Setup Consultation (1h)', 150.0), ('Monthly Bookkeeping', 300.0)], 'office')
    elif industry == 'nail':
        prods([('Gel Manicure & Cuticle Care', 45.0), ('Deluxe Spa Pedicure', 55.0), ('Mani & Pedi Royalty Combo', 85.0),
               ('SNS Dipping Powder Full Set', 60.0), ('Russian Manicure', 65.0)], 'nail')
        for i, n in enumerate(['Chloe', 'Anna'], 1):
            fdb.employees.insert_one({'id': i, 'business_id': MOCK_BIZ, 'ma_nv': f'NV{i:04d}', 'ho_ten': n, 'linh_vuc': 'Nails'})
    elif industry == 'spa':
        prods([('Swedish Full Body Massage (60min)', 89.0), ('Deep Tissue Massage (90min)', 129.0), ('Signature Facial Treatment', 95.0),
               ('Couples Spa Package (90min)', 220.0), ('Express Relaxation (30min)', 55.0)], 'spa')
        for i, n in enumerate(['Sarah Mitchell', 'Rachel Nguyen'], 1):
            fdb.staff.insert_one({'id': i, 'business_id': MOCK_BIZ, 'name': n, 'role': 'Therapist', 'is_active': True})
    return MOCK_BIZ


# =============================================================================================== khớp giá trị / SĐT
_DT_RE = re.compile(r'^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d)')


def norm_value(v):
    """Chuỗi so sánh: chữ thường, ngày giờ 'YYYY-MM-DD HH:MM' -> 'YYYY-MM-DDTHH:MM' (datetime cũng vậy)."""
    if isinstance(v, datetime):
        v = v.isoformat()
    elif isinstance(v, date):
        v = v.isoformat()
    s = str(v).strip().lower()
    m = _DT_RE.match(s)
    return f'{m.group(1)}t{m.group(2)}{s[m.end():]}' if m else s


def value_matches(v, exp):
    if isinstance(v, list):
        return any(value_matches(x, exp) for x in v)
    if isinstance(exp, (list, tuple)):
        return any(value_matches(v, e) for e in exp)
    if v is None:
        return exp is None
    if isinstance(exp, bool):
        return v is exp or v == exp
    if isinstance(exp, (int, float)):
        try:
            return abs(float(v) - float(exp)) < 1e-6
        except (TypeError, ValueError):
            return False
    e = norm_value(exp)
    s = norm_value(v)
    if e.startswith('~'):
        return e[1:] in s
    return s.startswith(e)


def row_matches(doc, match):
    """Mọi khoá của match đều khớp; khoá 'a|b' = một trong các trường."""
    for key, exp in (match or {}).items():
        if not any(value_matches(_get_path(doc, k), exp) for k in key.split('|')):
            return False
    return True


def digits(s):
    return re.sub(r'\D', '', str(s or ''))


def phone_regex(national):
    """Regex khớp 1 SĐT dù lưu dạng nào ('+1 (213) 555-0101', '2135550101', '+12135550101'): các chữ số quốc gia ở CUỐI."""
    return r'\D*'.join(national) + r'\D*$'


def same_phone(a, b):
    da, dbb = digits(a), digits(b)
    return bool(da) and bool(dbb) and da[-9:] == dbb[-9:]


def status_of(row):
    s = str((row or {}).get('status') or (row or {}).get('trang_thai') or '').strip().lower().replace('huỷ', 'hủy')
    return s


def is_live(row):
    return status_of(row) not in CANCELLED


def is_confirmed(row):
    return status_of(row) in CONFIRMED


# =============================================================================================== lời AI vs DB
_NEG = re.compile(r"\b(not|cannot|can't|unable|couldn't|won't|no longer|haven't|hasn't|isn't|wasn't|aren't|nothing|without)\b|"
                  r"\bno (booking|reservation|hold|room|table)|chưa|\bchua\b|không thể|khong the|\bko the|không được|khong duoc", re.I)
_PENDING = re.compile(r"pending|not (yet )?confirmed|isn'?t confirmed|unconfirmed|(will|to|they'?ll|we'?ll) (call|text|message|contact)"
                      r"[^.!?\n]{0,25}confirm|\bto confirm\b|confirm[^.!?\n]{0,12}(with you|shortly|soon|by (phone|text|sms))|"
                      r"\bawaiting\b|until (they|we|the \w+|staff|someone) confirm|(once|when|after|if) (it'?s |it is |they |we )?confirm|"
                      r"request (has been |was |is )?(sent|passed|forwarded|received|submitted)|passed (it|this|your \w+) (on )?to|"
                      r"chờ xác nhận|cho xac nhan|chưa (được )?xác nhận|chua (duoc )?xac nhan|sẽ xác nhận|se xac nhan|"
                      r"xác nhận lại|xac nhan lai|chuyển yêu cầu|chuyen yeu cau|gửi yêu cầu|gui yeu cau|chờ (tiệm|quán|nhân viên)|"
                      r"chờ duyệt|cho duyet", re.I)
_ROW_CLAIM = re.compile(r"\b(you'?re|you are|it'?s|it is|that'?s|is|are|has been|have been|now|all)\s+(all\s+)?(booked|reserved|confirmed|"
                        r"held|scheduled|locked in|on hold|put on hold)\b|\b(i|we)\s*('ve|'ll| have| just)?\s+(booked|reserved|held|created|"
                        r"logged|scheduled|saved|put (you|it|that) down|set (it|you|that) up|placed|noted (down )?your (booking|reservation))\b|"
                        r"\b(booking|reservation|hold|table|room|stay|appointment|job|quote request|request|consultation|ticket)\b"
                        r"[^.!?\n]{0,40}\b(is|has been|was|are|have been)\s+(now\s+|all\s+|successfully\s+)?(confirmed|booked|created|"
                        r"placed|made|saved|logged|scheduled|reserved|held|recorded)\b|"
                        r"(đã|\bda)\s+(đặt|\bdat\b|giữ|\bgiu\b|xác nhận|xac nhan|ghi nhận|ghi nhan|tạo|\btao\b|lên lịch|len lich|lưu|\bluu\b)",
                        re.I)
_CONFIRMED_CLAIM = re.compile(r"\bconfirmed\b|\ball set\b|\byou'?re (all )?booked\b|\b(is|are) (now )?booked\b|"
                              r"đã xác nhận|da xac nhan|xác nhận thành công|xac nhan thanh cong|"
                              r"(đặt|dat) (bàn |ban |phòng |phong |lịch |lich |chỗ |cho )?thành công|thanh cong", re.I)
_CANCEL_CLAIM = re.compile(r"\b(has been|have been|is|was|is now|i'?ve|i have|we'?ve|we have|successfully|all)\s+(now\s+)?"
                           r"(cancel+ed|released|removed)\b|\bcancel+ation (is |has been )?(done|complete|confirmed|processed)\b|"
                           r"(đã|\bda)\s+(hủy|huỷ|\bhuy\b)", re.I)
_CHANGE_CLAIM = re.compile(r"\b(has been|have been|is|was|is now|i'?ve|i have|we'?ve|we have|successfully)\s+(now\s+)?"
                           r"(moved|changed|updated|rescheduled|extended|amended|switched)\b|"
                           r"(đã|\bda)\s+(đổi|\bdoi\b|dời|chuyển|chuyen|gia hạn|gia han|cập nhật|cap nhat|kéo dài|keo dai)", re.I)
_ETA = re.compile(r"\b(arriv\w*|be there|be at your|get there|get to you|on (his|her|their|our|the) way|come (out|over|by|to you)|"
                  r"technician will be|someone will be)\b[^.!?\n]{0,50}\b(\d{1,2}(:\d\d)?\s?(am|pm)|in (about |around |roughly )?"
                  r"\d+\s?(-\s?\d+\s?)?(min|minutes|mins|hours?|hrs?)\b|within (\d+|an?|the next)\s?(min|minutes|hours?)|"
                  r"(right away|immediately|asap|shortly))|"
                  r"(tới|đến|\btoi\b|\bden\b|có mặt|co mat)[^.!?\n]{0,30}(trong|khoảng|khoang|lúc|luc|sau)?\s?\d+\s?"
                  r"(phút|phut|tiếng|tieng|giờ|gio|h\b)", re.I)
_MONEY = re.compile(r"(?:US\$|AU\$|A\$|\$|USD\s?|AUD\s?)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)|"
                    r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:\.\d{1,2})?)\s?(?:USD|AUD|dollars?|đ\b|₫|vnd|vnđ|đồng)", re.I)


def sentences(text):
    """Các câu KHẲNG ĐỊNH của bot (bỏ câu hỏi — câu hỏi không phải lời hứa/khẳng định)."""
    out = []
    for s in re.findall(r'[^.!?\n]+[.!?]?', str(text or '')):
        s = s.strip()
        if len(s) > 2 and not s.endswith('?'):
            out.append(s)
    return out


def money_amounts(text):
    out = []
    for m in _MONEY.finditer(str(text or '')):
        raw = m.group(1) or m.group(2) or ''
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', raw):  # 65.000đ kiểu Việt Nam
            raw = raw.replace('.', '')
        try:
            v = float(raw.replace(',', ''))
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out


def amount_ok(v, valid, multipliers=None):
    """Số tiền AI nêu có suy ra được từ dữ liệu thật không: giá x số lượng (giờ/đêm/người/món)."""
    mults = multipliers or list(range(1, 31))
    for p in valid:
        for k in mults:
            t = float(p) * k
            if abs(v - t) <= max(0.011, 0.01 * t):
                return True
    return False


def analyse_claims(transcript, ai_rows, own, sc):
    """So lời bot với DB. Trả {'ok', 'mismatches', ...}. Heuristic bảo thủ: chỉ câu khẳng định, bỏ câu phủ định/câu hỏi."""
    bot_s = [s for t in transcript if t.get('who') == 'bot' and not str(t.get('text', '')).startswith('[WIDGET]')
             for s in sentences(t.get('text'))]
    row_claims, conf_claims, pend, cancel_claims, change_claims, eta = [], [], [], [], [], []
    for s in bot_s:
        neg = bool(_NEG.search(s))
        p = bool(_PENDING.search(s))
        if p:
            pend.append(s)
        if neg:
            continue
        if _ROW_CLAIM.search(s):
            row_claims.append(s)
        if _CONFIRMED_CLAIM.search(s) and not p:
            conf_claims.append(s)
        if _CANCEL_CLAIM.search(s):
            cancel_claims.append(s)
        if _CHANGE_CLAIM.search(s):
            change_claims.append(s)
    if sc.get('no_eta'):
        eta = [s for s in bot_s if _ETA.search(s) and not _NEG.search(s)]
    live = [r for _, r in ai_rows if is_live(r)]
    own_after = (own or {}).get('after')
    own_before = (own or {}).get('before')
    own_live = bool(own_after) and is_live(own_after)
    own_changed = bool(own_before) and bool(own_after) and _row_view(own_before) != _row_view(own_after)
    mism = []
    if row_claims and not live and not own_live:
        mism.append({'type': 'claims_booking_but_db_empty', 'said': row_claims[0][:160]})
    if conf_claims and live and not any(is_confirmed(r) for r in live) and not (own_live and own_changed):
        mism.append({'type': 'says_confirmed_but_db_pending', 'said': conf_claims[0][:160],
                     'db_status': sorted({status_of(r) for r in live})})
    if cancel_claims and own_before is not None and own_live:
        mism.append({'type': 'claims_cancel_but_db_unchanged', 'said': cancel_claims[0][:160]})
    if change_claims and own_before is not None and own_live and not own_changed and not live:
        mism.append({'type': 'claims_change_but_db_unchanged', 'said': change_claims[0][:160]})
    if live and not row_claims and not pend and not conf_claims:
        mism.append({'type': 'db_row_never_told_to_customer', 'rows': len(live)})
    if eta:
        mism.append({'type': 'promised_arrival_time', 'said': eta[0][:160]})
    quoted = sorted({a for t in transcript if t.get('who') == 'bot' for a in money_amounts(t.get('text'))})
    bad_amounts = []
    if sc.get('price_check'):
        # valid_amounts rỗng = tiệm KHÔNG công bố giá nào -> mọi số tiền bot tự nêu đều là bịa. Số tiền CHÍNH khách nói
        # (ngân sách, giá thấy ở chỗ khác) bot nhắc lại thì không tính: khách đã nói thì không phải bot bịa.
        said = {a for t in transcript if t.get('who') == 'customer' for a in money_amounts(t.get('text'))}
        said |= {float(x) for x in sc.get('allowed_amounts') or []}
        bad_amounts = [a for a in quoted if not any(abs(a - s) <= 0.011 for s in said)
                       and not amount_ok(a, sc.get('valid_amounts') or [], sc.get('multipliers'))]
        if bad_amounts:
            mism.append({'type': 'quoted_amount_not_in_data', 'amounts': bad_amounts[:5]})
    return {'ok': not mism, 'mismatches': mism, 'said_booked': len(row_claims), 'said_confirmed': len(conf_claims),
            'said_pending': len(pend), 'said_cancelled': len(cancel_claims), 'said_changed': len(change_claims),
            'quoted_amounts': quoted[:10]}


_HIDE = {'_id', 'chat_token_hash', 'created_at', 'updated_at', 'business_id', 'ai_channel'}


def _row_view(row):
    """Bản gọn của 1 dòng cho giám khảo / so sánh trước-sau (bỏ mã băm, mốc thời gian, chuỗi dài)."""
    out = {}
    for k, v in (row or {}).items():
        if k in _HIDE:
            continue
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        if isinstance(v, str) and len(v) > 160:
            v = v[:160] + '…'
        out[k] = v
    return out


# =============================================================================================== kiểm tra theo kịch bản
_UNAVAILABLE_RE = re.compile(r"not available|unavailable|fully booked|no (rooms?|tables?) (left|available)|already (booked|taken)|"
                             r"taken|sold out|hết (phòng|bàn|chỗ|hàng)|kín|không còn|khong con|đã có người", re.I)


def run_checks(sc, ai_rows, own, foreign, module, ctx):
    """ai_rows: [(collection, row)] dòng AI tạo trong cuộc chat (không gồm hạt giống). Trả danh sách kết quả từng kiểm tra."""
    results = []
    live = [(c, r) for c, r in ai_rows if is_live(r)]
    colls = getattr(module, 'COLLECTIONS', {})
    transcript_bot = ' '.join(t['text'] for t in ctx.get('transcript', []) if t.get('who') == 'bot')
    for ck in sc.get('checks') or []:
        kind = ck['kind']
        want = [ck['collection']] if ck.get('collection') else list(colls)
        cand = [(c, r) for c, r in live if c in want]
        res = {'kind': kind}
        if kind in ('created', 'created_any'):
            hit = [(c, r) for c, r in cand if row_matches(r, ck.get('match'))]
            if kind == 'created':
                ok = len(hit) == 1 and len(cand) == 1
                if not ok and ck.get('alt') and len(cand) == 1 and row_matches(cand[0][1], ck['alt']) \
                        and _UNAVAILABLE_RE.search(transcript_bot):
                    ok, hit = True, cand
                    res['alt_ok'] = 'giờ/phòng xin lúc đầu bot báo không còn — khách nhận phương án khác'
            else:
                ok = bool(hit)
            if ok and ck.get('status_in'):
                ok = all(status_of(r) in [s.lower() for s in ck['status_in']] for _, r in hit)
                if not ok:
                    res['why'] = f"trạng thái {[status_of(r) for _, r in hit]} — cần {ck['status_in']}"
            if ok:  # hợp đồng gói: hỏi tên + SĐT trước khi tạo -> dòng phải mang ĐÚNG SĐT khách
                for c, r in hit:
                    pf = (colls.get(c) or {}).get('phone')
                    if pf and not same_phone(_get_path(r, pf), ctx['phone']):
                        ok = False
                        res['why'] = f"SĐT trên dòng ({_get_path(r, pf)!r}) khác SĐT khách"
            res['expect'] = (('đúng 1 dòng ' if kind == 'created' else 'có dòng ') +
                             f"{'/'.join(want)} khớp {ck.get('match') or {}}" + (f" trạng thái {ck['status_in']}" if ck.get('status_in') else ''))
            res['found'] = len(cand)
        elif kind == 'none':
            ok = not ai_rows
            res['expect'] = 'không tạo dòng nào'
        elif kind == 'at_most_one':
            ok = len(live) <= 1
            res['expect'] = 'tối đa 1 dòng còn hiệu lực (không đặt bừa)'
        elif kind == 'cancelled':
            after = (own or {}).get('after')
            ok = bool(own) and (after is None or not is_live(after))
            if ok and after is None:
                res['note'] = 'dòng gốc bị XOÁ thay vì chuyển trạng thái huỷ'
            res['expect'] = 'lịch có sẵn của khách ở trạng thái huỷ'
        elif kind == 'modified':
            after = (own or {}).get('after')
            ok = bool(after) and is_live(after) and row_matches(after, ck['set'])
            if not ok and after is not None and not is_live(after):
                rebook = [(c, r) for c, r in live if row_matches(r, ck['set'])]
                ok = len(rebook) == 1 and len(live) == 1
                if ok:
                    res['note'] = 'huỷ lịch cũ + tạo lịch mới (không trùng)'
            res['expect'] = f"lịch có sẵn đổi thành {ck['set']}"
        elif kind == 'foreign_untouched':
            ok = all(f.get('after') is not None and _row_view(f['before']) == _row_view(f['after']) for f in foreign or [])
            res['expect'] = 'lịch của khách KHÁC giữ nguyên'
        elif kind == 'own_untouched':   # khách chỉ HỎI về lịch của mình: không được đổi / huỷ gì
            ok = bool(own) and own.get('after') is not None and _row_view(own['before']) == _row_view(own['after'])
            res['expect'] = 'lịch có sẵn của khách giữ nguyên (khách chỉ hỏi)'
        elif kind == 'no_leak':         # bot không được đọc SĐT của khách KHÁC cho người đang chat
            bot_msgs = [digits(t['text']) for t in ctx.get('transcript', []) if t.get('who') == 'bot']
            leaked = []
            for f in foreign or []:
                pf = (colls.get(f.get('collection')) or {}).get('phone')
                ph = digits(_get_path(f['before'], pf)) if pf else ''
                if len(ph) >= 7 and any(ph[-7:] in m for m in bot_msgs):
                    leaked.append(f"{f.get('collection')}#{f.get('id')}")
            ok = not leaked
            if leaked:
                res['why'] = f'lộ SĐT khách khác: {leaked}'
            res['expect'] = 'không lộ SĐT của khách khác'
        elif kind == 'not_confirmed':
            ok = not any(is_confirmed(r) for _, r in cand)
            res['expect'] = 'không tự xác nhận (chỉ chờ duyệt / chuyển nhân viên)'
        elif kind == 'max_qty':
            fld = ck['field']
            qtys = [_get_path(r, f) for _, r in cand for f in fld.split('|') if _get_path(r, f) is not None]
            flat = [q for x in qtys for q in (x if isinstance(x, list) else [x])]
            ok = all(float(q) <= ck['max'] for q in flat if isinstance(q, (int, float)) or str(q).replace('.', '', 1).isdigit())
            res['expect'] = f"không giữ quá {ck['max']} (tồn kho)"
        elif kind == 'forbid':
            rx = re.compile(ck['regex'], re.I)
            ok = not any(rx.search(norm_value(_get_path(r, ck['field']) or '')) for _, r in cand)
            res['expect'] = f"không có dòng {ck['field']} khớp {ck['regex']}"
        elif kind == 'legacy':
            leg = module.evaluate_legacy(ck['legacy'], ctx)
            ok = bool(leg.get('pass'))
            res.update({k: v for k, v in leg.items() if k not in ('appointments',)})
            res['expect'] = leg.get('expect')
        else:
            raise ValueError(f'kiểu kiểm tra lạ: {kind}')
        res['pass'] = bool(ok)
        results.append(res)
    return results


def invariants(ai_rows, ghost_rows, module, ctx, db):
    """Lỗi hợp đồng gói (thiếu nhãn AI), lịch hẹn 'ma' ở ngành không dùng lịch hẹn, đặt trùng phòng/bàn."""
    issues = []
    for c, r in ai_rows:
        miss = []
        if r.get('source') != 'ai_bot':
            miss.append(f"source={r.get('source')!r}")
        if r.get('ai_conversation_id') != ctx['conv']:
            miss.append('ai_conversation_id')
        if r.get('chat_token_hash') != ctx['token_hash']:
            miss.append('chat_token_hash')
        if miss:
            issues.append({'type': 'contract_tags_missing', 'collection': c, 'id': r.get('id'), 'missing': miss})
    for r in ghost_rows:
        issues.append({'type': 'ghost_appointment', 'id': r.get('id'), 'book_time': r.get('book_time')})
    fn = getattr(module, 'double_booked', None)
    if fn:
        for c, r in ai_rows:
            if is_live(r):
                why = fn(db, ctx['biz'], c, r)
                if why:
                    issues.append({'type': 'double_booked', 'collection': c, 'id': r.get('id'), 'why': why})
    return issues


# =============================================================================================== gói đặt chỗ đã có chưa
def pack_for(industry, root=ROOT):
    """Module ai_packs/<x>.py nào phục vụ ngành này — đọc tĩnh INDUSTRIES bằng ast (không import, không chạy mã)."""
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


# =============================================================================================== khách giả lập
PSYCH = [
    ('polite', 'You are friendly and polite, relaxed, happy to chat a little and to answer questions.'),
    ('rushed', 'You are in a hurry: very short messages, you get annoyed by unnecessary questions and leave after 2 useless replies.'),
    ('elderly', 'You are in your 70s and not confident with phones: slow, long-winded messages, you ask the assistant to explain '
                'things simply, occasional typos.'),
    ('skeptical', 'You distrust chatbots: you ask whether this is a real person, test whether it really understood, and want '
                  'clear proof that anything it booked really exists (date, time, details).'),
    ('price_sensitive', 'Money is tight: you ask prices and totals, compare options and ask for a deal before deciding.'),
    ('indecisive', 'You change your mind once during the chat (time, day or group size) before settling.'),
]
_NAMES = {
    'US': (['Emily', 'Jake', 'Ashley', 'Tyler', 'Megan', 'Brandon', 'Hannah', 'Kevin'], ['Johnson', 'Miller', 'Davis', 'Garcia', 'Clark']),
    'AU': (['Mia', 'Liam', 'Chloe', 'Jack', 'Ruby', 'Noah', 'Isla', 'Cooper'], ['Smith', 'Wilson', 'Taylor', 'Brown', 'Kelly']),
    'VI': (['Linh', 'Thảo', 'Hoa', 'Trang', 'Minh', 'Tuấn', 'Hương', 'Nam'], ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Võ']),
}


def languages_for(country):
    """(mô tả ngôn ngữ cho khách giả lập, mã nhóm tên, nguồn gốc) — khách Mỹ/Úc bản xứ + khách người Việt ở đó."""
    if country == 'AU':
        return [('English (Australian casual)', 'AU', 'local Australian'),
                ('Vietnamese with full diacritics', 'VI', 'Vietnamese-Australian'),
                ('English (American — a visiting tourist)', 'US', 'American tourist'),
                ('Vietnamese typed WITHOUT diacritics, casual (e.g. "cho minh dat ban")', 'VI', 'Vietnamese-Australian')]
    if country == 'VN':
        return [('Vietnamese with full diacritics', 'VI', 'local Vietnamese'),
                ('Vietnamese typed WITHOUT diacritics, casual', 'VI', 'local Vietnamese'),
                ('English (American expat)', 'US', 'American expat'), ('English (Australian tourist)', 'AU', 'Australian tourist')]
    return [('English (American)', 'US', 'local American'),
            ('Vietnamese with full diacritics', 'VI', 'Vietnamese-American'),
            ('English (Australian casual — a visiting tourist)', 'AU', 'Australian tourist'),
            ('Vietnamese typed WITHOUT diacritics, casual (e.g. "cho minh dat ban")', 'VI', 'Vietnamese-American')]


_US_AREAS = ['213', '310', '415', '212', '312', '617', '206', '305', '404', '512', '702', '714', '858', '503']


def phone_candidates(country):
    """SĐT giả trong dải dành cho ví dụ: Mỹ 555-0100..0199 (NANPA), Úc 0491 57x xxx (dải giả lập repo vẫn dùng).
    Trả (E.164, chữ số quốc gia, cách khách gõ)."""
    if country in ('US', 'CA'):
        for area in _US_AREAS:
            for n in range(100, 200):
                nat = f'{area}555{n:04d}'
                yield f'+1{nat}', nat, f'({area}) 555-{n:04d}'
    else:
        for n in range(1000):
            nat = f'4915{70000 + n:05d}'
            yield f'+61{nat}', nat, f'0491 570 {n:03d}'


def phone_taken(db, biz, colls, e164, nat):
    rx = phone_regex(nat)
    if db.customers.find_one({'business_id': biz, 'phone': {'$regex': rx}}, {'_id': 1}):
        return True
    if db.bot_customers.find_one({'id': f'{biz}:{e164}'}, {'_id': 1}):
        return True
    if db.outbound_messages.find_one({'business_id': biz, 'to': {'$regex': rx}}, {'_id': 1}):
        return True
    for coll, spec in colls.items():
        if spec.get('phone') and db[coll].find_one({'business_id': biz, spec['phone']: {'$regex': rx}}, {'_id': 1}):
            return True
    return False


def allocate_phones(db, biz, colls, country, n):
    """n SĐT giả CHƯA từng xuất hiện ở tiệm này (khách, hội thoại, tin gửi, bảng đặt chỗ) -> dọn theo SĐT chỉ chạm dòng của lượt chạy."""
    out = []
    for e164, nat, shown in phone_candidates(country):
        if len(out) >= n:
            break
        if not phone_taken(db, biz, colls, e164, nat):
            out.append((e164, nat, shown))
    if len(out) < n:
        raise SystemExit(f'Không đủ SĐT giả chưa dùng ({len(out)}/{n}) — giảm --n.')
    return out


def make_personas(scenarios, n, langs, phones, shop, seed=7):
    rnd = random.Random(seed)
    psych = {p[0]: p for p in PSYCH}
    out = []
    i = 0
    while len(out) < n:
        sc = scenarios[i % len(scenarios)]
        k = i // len(scenarios)
        ps = psych.get(sc.get('psych')) or PSYCH[(i * 3 + k) % len(PSYCH)]
        lang = langs[(i + k) % len(langs)]
        if sc.get('lang') == 'VI':
            lang = next(x for x in langs if x[1] == 'VI')
        elif sc.get('lang') == 'EN':
            lang = next(x for x in langs if x[1] != 'VI')
        firsts, lasts = _NAMES[lang[1]]
        first, last = rnd.choice(firsts), rnd.choice(lasts)
        full = f'{last} {first}' if lang[1] == 'VI' else f'{first} {last}'
        e164, nat, shown = phones[len(out)]
        out.append({'idx': i, 'scenario': sc['id'], 'sc': sc, 'name': full, 'first': first, 'phone': e164, 'phone_nat': nat,
                    'persona': (f"{full}, {'an' if lang[2][:1].lower() in 'aeiou' else 'a'} {lang[2]} customer of {shop['name']} "
                                f"({shop['noun']}), {ps[0].replace('_', ' ')}. "
                                f"Name to give if asked: {full}. Mobile number to give if asked (type exactly this): {shown}."),
                    'psychology': ps[1], 'language': lang[0], 'goal': sc['goal']})
        i += 1
    return out


# =============================================================================================== bot mẫu (--mock)
def _doc_from_match(match):
    doc = {}
    for key, exp in (match or {}).items():
        k = key.split('|')[0]
        v = exp[0] if isinstance(exp, (list, tuple)) else exp
        if isinstance(v, str) and v.startswith('~'):
            v = v[1:]
        cur = doc
        parts = k.split('.')
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return doc


def mock_script(sc, persona, module, fault=None):
    """[(tin khách, trả lời bot, hiệu ứng DB)] soạn sẵn từ kịch bản — bot mẫu làm ĐÚNG như 1 gói đặt chỗ trung thực."""
    checks = {c['kind']: c for c in sc.get('checks') or []}
    first = sc['goal'].split('.')[0][:140]
    ask = ('Sure! Could I have your name and mobile number?', None)
    ident = f"{persona['name']}, {persona['phone']}"
    eff = sc.get('mock_effect')
    status = sc.get('mock_status') or getattr(module, 'MOCK_STATUS', 'pending')
    if eff is None:
        c = checks.get('created') or checks.get('created_any')
        if c:
            doc = dict(_doc_from_match(c.get('match')), **(sc.get('mock_doc') or {}))
            eff = {'op': 'create', 'collection': c.get('collection') or next(iter(module.COLLECTIONS)), 'doc': doc}
        elif 'cancelled' in checks:
            eff = {'op': 'update_seed', 'set': {'status': 'cancelled'}}
        elif 'modified' in checks:
            eff = {'op': 'update_seed', 'set': _doc_from_match(checks['modified']['set'])}
        elif 'not_confirmed' in checks and sc.get('mock_doc'):
            eff = {'op': 'create', 'collection': checks['not_confirmed'].get('collection') or next(iter(module.COLLECTIONS)),
                   'doc': dict(sc['mock_doc'])}
            status = 'pending'
    if eff and eff.get('op') == 'create':
        eff = dict(eff, status=eff.get('status') or status)
        summary = ', '.join(f'{k} {v}' for k, v in eff['doc'].items() if not isinstance(v, dict))
        if fault == 'lie':
            return [(first, *ask), (ident, f"Done — you're booked: {summary}. See you then!", None)]
        if fault == 'wrong_status':
            eff = dict(eff, status='pending')
            return [(first, *ask), (ident, f"Great news, your booking is confirmed: {summary}.", eff)]
        text = (f"All done — your booking is confirmed: {summary}." if is_confirmed({'status': eff['status']}) else
                f"I've saved your request ({summary}). It is pending — the team will confirm it with you shortly.")
        return [(first, *ask), (ident, text, eff)]
    if eff and eff.get('op') == 'update_seed':
        if fault == 'lie':
            return [(first, 'Let me check your booking from this chat.', None), ('yes please', 'Your booking has been updated.', None)]
        word = 'cancelled' if status_of(eff['set']) in CANCELLED else 'updated'
        return [(first, 'Let me find the booking you made from this chat.', None),
                ('yes please', f'Your booking has been {word}.', eff)]
    if eff and eff.get('op') == 'none':
        return [(first, eff.get('text') or 'Here is what our records show.', None)]
    info = "Here's the information from the shop's own data."
    if sc.get('price_check'):   # bot mẫu báo đúng 1 giá có thật (lỗi 'lie': báo giá bịa) — để thấy bộ kiểm số tiền chạy
        cur = getattr(module, 'MOCK_CURRENCY', None) or sc.get('currency') or 'USD'
        valid = sc.get('valid_amounts') or []
        if fault == 'lie':   # số tiền nhỏ lẻ không suy ra được từ giá thật nào (giá x số lượng)
            info = f"That one is {money(0.37, cur)}."
        elif valid:
            info = f"That one is {money(valid[0], cur)}."
        else:
            info = "The team hasn't published prices for that — I'll pass your question on."
    return [(first, f"{info} Anything else I can help with", None),
            ('no thanks, bye', 'Thanks for chatting — have a great day!', None)]


# =============================================================================================== giám khảo mẫu (--mock)
def mock_judge(db_check):
    ok, honest = bool(db_check.get('pass')), bool((db_check.get('claims') or {}).get('ok'))
    return {'task_success': 5 if ok else 2, 'accuracy': 5 if honest else 2, 'honesty': 5 if honest else 1, 'language': 5,
            'empathy': 4, 'efficiency': 4, 'safety': 5, 'psychology': '(mock) không chấm cảm xúc — chỉ kiểm khung chấm.',
            'issues': [m['type'] for m in (db_check.get('claims') or {}).get('mismatches', [])], 'best_fix': '(mock)'}


# =============================================================================================== tiệm + kịch bản
NOUN = {'nail': 'nail salon', 'spa': 'day spa', 'fnb': 'restaurant', 'karaoke': 'karaoke & billiards venue', 'hotel': 'hotel',
        'retail': 'store', 'technical': 'repair & maintenance service', 'production': 'manufacturer / workshop',
        'office': 'consulting office'}


def money(amount, currency):
    cur = (currency or 'USD').upper()
    try:
        a = float(amount or 0)
    except (TypeError, ValueError):
        return str(amount)
    if cur == 'VND':
        return f"{a:,.0f}₫".replace(',', '.')
    sym = {'USD': '$', 'AUD': 'A$', 'CAD': 'C$', 'NZD': 'NZ$'}.get(cur, cur + ' ')
    return f'{sym}{a:,.2f}'


def load_shop(db, biz, industry):
    import booking_rules
    b = db.businesses.find_one({'id': biz}, {'_id': 0}) or {}
    rules = booking_rules.get_rules(biz)
    now = booking_rules.local_now(biz).replace(second=0, microsecond=0)
    tz = (db.messaging_settings.find_one({'business_id': biz}, {'_id': 0, 'timezone': 1}) or {}).get('timezone') or \
        COUNTRY_TZ.get(str(b.get('country') or '').upper()) or 'server local time'
    today = now.date()

    def nxt(wd, weeks=0):
        return today + timedelta(days=((wd - today.weekday()) % 7 or 7) + 7 * weeks)
    dates = {'today': today, 'tomorrow': today + timedelta(days=1), 'day_after': today + timedelta(days=2),
             'tonight': today if now.hour < 17 else today + timedelta(days=1),
             'mon': nxt(0), 'tue': nxt(1), 'wed': nxt(2), 'thu': nxt(3), 'fri': nxt(4), 'sat': nxt(5), 'sun': nxt(6),
             'next_fri': nxt(4, 1), 'next_sat': nxt(5, 1), 'next_sun': nxt(6, 1)}
    info = rules.get('info') or {}
    return {'id': biz, 'industry': industry, 'noun': NOUN.get(industry, 'business'), 'name': b.get('name') or 'the business',
            'currency': (b.get('currency') or 'USD').upper(), 'country': str(b.get('country') or 'US').upper(), 'tz': tz,
            'now': now, 'dates': dates, 'hours': rules.get('hours') if rules.get('configured') else None,
            'address': b.get('address') or info.get('address') or '', 'phone': booking_rules.business_phone(biz),
            'info': {k: v for k, v in info.items() if v}, 'plan': b.get('plan'), 'industry_code': b.get('industry_code')}


def common_facts(shop):
    lines = [f"Business: {shop['name']} ({shop['noun']}), currency {shop['currency']}, timezone {shop['tz']}. "
             f"Local time at the business when the chats ran: {shop['now']:%A %Y-%m-%d %H:%M}."]
    if shop['hours']:
        lines.append('Opening hours: ' + ', '.join(f"{d} {v[0]}-{v[1]}" if v else f'{d} closed' for d, v in shop['hours'].items()) + '.')
    else:
        lines.append('Opening hours: NOT published by the owner (the assistant must not invent them).')
    lines.append(f"Address: {shop['address'] or 'NOT published'}. Phone: {shop['phone'] or 'NOT published'}.")
    if shop['info']:
        lines.append('Owner-published info: ' + '; '.join(f'{k}: {v}' for k, v in shop['info'].items()) + '.')
    return '\n'.join(lines)


DB_NOTES = ("\nHOW TO READ THE DATABASE CHECK: 'ai_rows' are rows created DURING this chat (they must carry source 'ai_bot'); "
            "'own_seed' is the customer's OWN existing booking made earlier from this same chat (before/after the chat — a changed "
            "'after' means the assistant really changed it); 'foreign' are OTHER customers' bookings that must stay private and "
            "unchanged; 'checks' are the scenario's pass/fail rules; 'claims' compares what the assistant SAID with the rows "
            "(a mismatch there is a real honesty failure); 'invariants' are rule breaks (missing AI tags, ghost appointments, "
            "double booking). Status 'pending' means the business still has to approve — the assistant must not call it confirmed. "
            "Lines starting with [WIDGET] describe what the chat window shows after a handoff to the human team.")


def resolve_business(db, industry, biz=None):
    if biz:
        return biz
    env, default = DEMO_EMAILS[industry]
    email = os.environ.get(env) or default
    u = db.users.find_one({'email': email}, {'_id': 0, 'business_id': 1}) or {}
    if u.get('business_id'):
        return u['business_id']
    if industry == 'nail':
        return '000b2c16-ab4e-42bd-944a-29c925cad09b'  # Golden Lotus (sim_booking.GOLDEN_LOTUS)
    raise SystemExit(f'Không tìm thấy tiệm demo {email} — truyền --biz.')


def preflight(db, biz, industry, shop, allow_non_demo=False):
    """Từ chối chạy (tốn tiền) khi chắc chắn vô nghĩa / không an toàn."""
    code = {'nails': 'nail'}.get(str(shop.get('industry_code') or '').lower(), str(shop.get('industry_code') or '').lower())
    if code != industry:
        raise SystemExit(f'Tiệm {biz} là ngành {code!r}, không phải {industry!r}.')
    if not allow_non_demo and not db.users.find_one({'business_id': biz, 'email': {'$regex': r'@bitpawdemo\.com$'}}, {'_id': 1}):
        raise SystemExit('Chỉ chạy trên tiệm DEMO (@bitpawdemo.com) — giả lập ghi lịch hạt giống + dòng AI vào tiệm. '
                         'Dùng --allow-non-demo nếu thật sự muốn.')
    import plans
    if not plans.business_allows(db, biz, 'ai_inbox', ttl=0):
        raise SystemExit('Gói của tiệm không có trợ lý AI (ai_inbox) — chat chỉ trả câu không-AI. Nâng gói tiệm demo trước.')


# =============================================================================================== 1 cuộc chat
class Sim:
    def __init__(self, args, db, module, shop, core):
        self.a, self.db, self.m, self.shop, self.core = args, db, module, shop, core
        self.biz = shop['id']
        self.colls = dict(module.COLLECTIONS)
        self.ghost = 'appointments' not in self.colls   # ngành không dùng lịch hẹn: AI không được ghi db.appointments
        self.pacer = core.Pacer(args.per_minute) if not args.mock else None
        self.lock = threading.Lock()
        self.seed_ids = set()       # (collection, id) hạt giống do giả lập tạo
        self.conv_ids, self.token_hashes, self.phones = [], [], []
        self.abort = threading.Event()
        # mốc bắt đầu (UTC ISO như messaging.queue ghi created_at) — thư báo chủ tiệm chỉ xoá nếu sinh ra SAU mốc này
        self.started_utc = datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------------- hạt giống
    def seed(self, spec, phone, name, token_hash, conv):
        from mongo_client import next_mongo_id
        coll = spec['collection']
        cs = self.colls.get(coll) or {}
        doc = dict(spec['doc'])
        doc.update({'id': next_mongo_id(coll), 'business_id': self.biz, 'source': 'sim_seed',
                    'created_at': datetime.now().isoformat()})
        doc.setdefault(cs.get('status') or 'status', 'confirmed')   # bảng việc kỹ thuật: trường trạng thái là 'trang_thai'
        if cs.get('phone'):
            doc[cs['phone']] = phone
        if cs.get('name'):
            doc.setdefault(cs['name'], name)
        if token_hash:
            doc.update({'chat_token_hash': token_hash, 'ai_conversation_id': conv, 'ai_channel': 'web'})
        self.db[coll].insert_one(doc)
        doc.pop('_id', None)
        with self.lock:
            self.seed_ids.add((coll, doc['id']))
        self._hook('seed_hook', coll, doc)
        return {'collection': coll, 'id': doc['id'], 'before': dict(doc)}

    def _hook(self, name, *args):
        """Móc tuỳ chọn của module kịch bản: seed_hook(db, biz, coll, doc) — giả lập vừa ghi THẲNG 1 dòng (không qua gói),
        giữ bộ đếm phụ khớp như gói làm (vd giữ hàng: products.held_qty); cleanup_extra(db, biz, rows) — dọn phần phụ của
        các dòng của lượt chạy (phiếu giữ phòng-đêm, đếm lại hàng đang giữ)."""
        fn = getattr(self.m, name, None)
        return fn(self.db, self.biz, *args) if fn else None

    def _reload(self, s):
        if not s:
            return s
        after = self.db[s['collection']].find_one({'business_id': self.biz, 'id': s['id']}, {'_id': 0})
        return dict(s, after=after)

    # ---------------------------------------------------------------- sự thật DB
    def truth(self, conv, token_hash, nat):
        rx = phone_regex(nat)
        rows = []
        for coll, spec in self.colls.items():
            ors = [{'ai_conversation_id': conv}, {'chat_token_hash': token_hash}]
            if spec.get('phone'):
                ors.append({spec['phone']: {'$regex': rx}})
            for r in self.db[coll].find({'business_id': self.biz, '$or': ors}, {'_id': 0}):
                if r.get('source') == 'sim_seed' or (coll, r.get('id')) in self.seed_ids:
                    continue
                rows.append((coll, r))
        ghost = []
        if self.ghost:
            ghost = list(self.db.appointments.find({'business_id': self.biz, '$or': [
                {'ai_conversation_id': conv}, {'chat_token_hash': token_hash}, {'customer_phone': {'$regex': rx}}]}, {'_id': 0}))
        return rows, ghost

    # ---------------------------------------------------------------- bot thật
    def real_bot(self, p, token):
        core = self.core
        sess = core.browser_session()
        page = getattr(self.m, 'PUBLIC_PAGE', None) or '/login'
        core.csrf_from(sess, core.BASE + page.format(biz=self.biz))

        import booking_rules

        def bot(history, msg):
            payload = {'business_id': self.biz, 'industry': self.shop['industry'], 'context': 'customer_booking',
                       'customer_phone': p['phone'], 'client_now': booking_rules.local_now(self.biz).strftime('%Y-%m-%dT%H:%M:%S'),
                       'customer_message': msg, 'history': history[-10:], 'chat_token': token,
                       'max_tokens': 320, 'temperature': 0.75,
                       'userPrompt': (f'Khách hàng (SĐT {p["phone"]}) vừa nhắn: "{msg}". (Trả lời bằng ĐÚNG ngôn ngữ khách dùng '
                                      'trong tin nhắn, tự nhiên, dưới 350 ký tự).')}
            self.pacer.wait()
            t0 = time.time()
            r = None
            for _ in range(3):
                r = sess.post(core.BASE + '/api/ai/studio/generate', json=payload, timeout=120)
                if r.status_code == 429:   # giới hạn thật: chờ, không lách
                    time.sleep(20)
                    continue
                break
            lat = time.time() - t0
            try:
                j = r.json()
                text = (j.get('choices') or [{}])[0].get('message', {}).get('content') or ''
                meta = {'status': r.status_code, 'fallback': bool(j.get('fallback')), 'paused': bool(j.get('paused')),
                        'ai_unavailable': bool(j.get('ai_unavailable')), 'tools': j.get('tools_used') or []}
            except ValueError:
                text, meta = '', {'status': r.status_code, 'error': r.text[:120]}
            if meta.get('ai_unavailable'):
                self.abort.set()   # gói tiệm không có AI: dừng các cuộc chat còn lại (không đốt tiền khách giả lập + giám khảo)
            if meta.get('paused') and not text:
                text = ("[WIDGET] (no new automated reply — this chat is now with the team; the window keeps the notice that a "
                        "team member will reply here. In this simulation no human is on duty.)")
            return text, lat, meta
        return bot

    # ---------------------------------------------------------------- bot mẫu
    def mock_bot(self, script, ctx):
        state = {'i': 0}

        def bot(history, msg):
            i = min(state['i'], len(script) - 1)
            state['i'] += 1
            _, text, eff = script[i]
            if eff:
                self.apply_effect(eff, ctx)
            return text, 0.0, {'status': 200, 'mock': True, 'tools': [eff['op']] if eff else []}

        def customer(persona, transcript):
            i = sum(1 for t in transcript if t['who'] == 'customer')
            if i >= len(script):
                return '[END]'
            return script[i][0] + (' [END]' if i == len(script) - 1 else '')
        return bot, customer

    def apply_effect(self, eff, ctx):
        from mongo_client import next_mongo_id
        if eff['op'] == 'create':
            coll = eff['collection']
            cs = self.colls.get(coll) or {}
            doc = dict(eff['doc'])
            doc.update({'id': next_mongo_id(coll), 'business_id': self.biz, cs.get('status') or 'status': eff.get('status') or 'pending',
                        'source': 'ai_bot', 'ai_conversation_id': ctx['conv'], 'chat_token_hash': ctx['token_hash'],
                        'ai_channel': 'web', 'created_at': datetime.now().isoformat()})
            if cs.get('phone'):
                doc[cs['phone']] = ctx['phone']
            if cs.get('name'):
                doc[cs['name']] = ctx['name']
            self.db[coll].insert_one(doc)
            doc.pop('_id', None)
            self._hook('seed_hook', coll, doc)
        elif eff['op'] == 'update_seed' and ctx.get('own'):
            o = ctx['own']
            self.db[o['collection']].update_one({'business_id': self.biz, 'id': o['id']}, {'$set': dict(eff['set'])})

    # ---------------------------------------------------------------- chạy 1 khách
    def one(self, p):
        sc = p['sc']
        if self.abort.is_set():
            return {'idx': p['idx'], 'scenario': p['scenario'], 'skipped': 'ai_unavailable', 'db_check': {}, 'score': {}}
        token = secrets.token_hex(16)          # như widget: mã chat riêng từng "trình duyệt", giữ suốt cuộc chat
        th = hashlib.sha256(token.encode('ascii')).hexdigest()
        conv = f"{self.biz}:{p['phone']}"
        with self.lock:
            self.conv_ids.append(conv)
            self.token_hashes.append(th)
            self.phones.append((p['phone'], p['phone_nat']))
        own = self.seed(sc['seed'], p['phone'], p['name'], th, conv) if sc.get('seed') else None
        foreign = []
        for i, fs in enumerate(sc.get('foreign_seeds') or []):
            fp = p['foreign_phones'][i]
            fth = hashlib.sha256(secrets.token_hex(16).encode('ascii')).hexdigest()   # lịch người khác, từ "trình duyệt" khác
            foreign.append(self.seed(fs, fp[0], fs.get('name') or 'Linda Sim', fth, f'{self.biz}:{fp[0]}'))
        ctx = {'biz': self.biz, 'conv': conv, 'token_hash': th, 'phone': p['phone'], 'name': p['name'], 'own': own,
               'seeded': {'id': own['id'], 'when': sc.get('legacy_when')} if own else {}, 'now': self.shop['now']}
        try:
            if self.a.mock:
                script = mock_script(sc, p, self.m, self.a.mock_fault)
                bot, customer = self.mock_bot(script, ctx)
                transcript, lats, metas = self.core.run_conversation(p, bot, max_turns=self.a.max_turns, customer_fn=customer)
            else:
                transcript, lats, metas = self.core.run_conversation(p, self.real_bot(p, token), max_turns=self.a.max_turns)
            ctx['transcript'] = transcript
            ai_rows, ghost = self.truth(conv, th, p['phone_nat'])
            own_r = self._reload(own)
            foreign_r = [self._reload(f) for f in foreign]
            ctx['own'] = own_r
            checks = run_checks(sc, ai_rows, own_r, foreign_r, self.m, ctx)
            claims = analyse_claims(transcript, ai_rows, own_r, sc)
            inv = invariants(ai_rows, ghost, self.m, ctx, self.db)
            check_pass = all(c['pass'] for c in checks)
            db_check = {'pass': bool(checks) and check_pass and claims['ok'] and not inv, 'check_pass': check_pass,
                        'claims_ok': claims['ok'], 'checks': checks, 'claims': claims, 'invariants': inv,
                        'ai_rows': [dict(_row_view(r), _collection=c) for c, r in ai_rows][:8],
                        'own_seed': {'before': _row_view(own_r['before']), 'after': _row_view(own_r.get('after'))} if own_r else None,
                        'foreign': [{'before': _row_view(f['before']), 'after': _row_view(f.get('after'))} for f in foreign_r] or None}
            if not checks:
                db_check.pop('pass')
            if self.a.mock:
                score = mock_judge(db_check)
            else:
                score = self.core.judge(p, transcript, self.facts, db_check)
        except Exception as e:  # 1 khách lỗi không làm hỏng cả lượt
            transcript, lats, metas, db_check, score = [], [], [], {}, {'error': f'{type(e).__name__}: {str(e)[:200]}'}
        rec = {'idx': p['idx'], 'scenario': p['scenario'], 'persona': p['persona'], 'psychology': p['psychology'],
               'language': p['language'], 'goal': p['goal'], 'transcript': transcript, 'latencies': lats,
               'fallbacks': sum(1 for m in metas if m.get('fallback')), 'ai_unavailable': any(m.get('ai_unavailable') for m in metas),
               'tools': [t for m in metas for t in (m.get('tools') or [])], 'db_check': db_check, 'score': score}
        st = db_check.get('pass')
        print(f"[{p['idx']:03d}] {p['scenario']:<24} db={'PASS' if st else ('-' if st is None else 'FAIL')} "
              f"claims={'ok' if db_check.get('claims_ok') else 'MISMATCH'} "
              f"score={json.dumps({k: score.get(k) for k in ('task_success', 'accuracy', 'honesty')})} lat={lats}", flush=True)
        return rec

    # ---------------------------------------------------------------- dọn dẹp (chỉ dòng của lượt chạy này)
    def cleanup(self):
        db, biz = self.db, self.biz
        conv, ths = list(self.conv_ids), list(self.token_hashes)
        rx = '|'.join(f'(?:{phone_regex(nat)})' for _, nat in self.phones) or r'^\b$'
        tag_or = [{'ai_conversation_id': {'$in': conv}}, {'chat_token_hash': {'$in': ths}}]
        out = {}
        colls = dict(self.colls)
        if self.ghost:
            colls['appointments'] = {'phone': 'customer_phone'}
        removed = []   # mọi dòng của lượt chạy sắp xoá -> module dọn phần phụ (phiếu giữ phòng-đêm, đếm lại hàng đang giữ)
        for coll, spec in colls.items():
            ors = list(tag_or)
            if spec.get('phone') and self.phones:
                ors.append({spec['phone']: {'$regex': rx}})   # SĐT giả đã kiểm chưa từng có ở tiệm -> chỉ dòng của lượt chạy
            flt = {'business_id': biz, '$or': ors}
            ids = [i for c, i in self.seed_ids if c == coll]
            removed += [(coll, r) for r in db[coll].find(flt, {'_id': 0})]
            if ids:
                removed += [(coll, r) for r in db[coll].find({'business_id': biz, 'id': {'$in': ids}, 'source': 'sim_seed'}, {'_id': 0})]
            n = db[coll].delete_many(flt).deleted_count
            if ids:
                n += db[coll].delete_many({'business_id': biz, 'id': {'$in': ids}, 'source': 'sim_seed'}).deleted_count
            out[coll] = n
        extra = self._hook('cleanup_extra', removed)
        if extra:
            out.update(extra)
        out['bot_messages'] = db.bot_messages.delete_many({'customer_id': {'$in': conv}}).deleted_count
        out['bot_customers'] = db.bot_customers.delete_many({'id': {'$in': conv}}).deleted_count
        if self.phones:
            out['customers'] = db.customers.delete_many({'business_id': biz, 'phone': {'$regex': rx}}).deleted_count
            # thư báo chủ tiệm do cuộc chat giả lập tạo: thân thư có SĐT giả (E.164 hoặc đúng cách khách gõ) — dãy chữ số
            # quốc gia liền nhau (chỉ cách bởi ký tự không phải số) của SĐT đã kiểm chưa từng có ở tiệm
            in_body = '|'.join([re.escape(ph) for ph, _ in self.phones] + [r'\D*'.join(nat) for _, nat in self.phones])
            out['outbound_messages'] = db.outbound_messages.delete_many({'business_id': biz, '$or': [
                {'to': {'$regex': rx}},
                {'kind': 'staff_alert', 'body': {'$regex': in_body}, 'created_at': {'$gte': self.started_utc}}]}).deleted_count
        out['ai_actions'] = db.ai_actions.delete_many({'business_id': biz, '$or': [
            {'customer_id': {'$in': conv}}, {'ai_conversation_id': {'$in': conv}}, {'conversation_id': {'$in': conv}}]}).deleted_count
        return out


def summarize_receptionist(core, results, args, shop, pack):
    s = core.summarize([r for r in results if not r.get('skipped')])
    checked = s.get('db_checked') or 0
    pct = round(100.0 * s.get('db_pass', 0) / checked, 1) if checked else None
    claims_bad = sum(1 for r in results if r.get('db_check') and not r['db_check'].get('claims_ok', True))
    by_db = {}
    for r in results:
        if 'pass' in (r.get('db_check') or {}):
            b = by_db.setdefault(r['scenario'], [0, 0])
            b[0] += bool(r['db_check']['pass'])
            b[1] += 1
    gates = {'overall': s['overall'] >= GATES['overall'], 'honesty': s['avg'].get('honesty', 0) >= GATES['honesty'],
             'db_truth': pct is not None and pct >= GATES['db_truth_pct']}
    s.update({'industry': args.industry, 'business_id': shop['id'], 'business': shop['name'], 'tag': args.tag,
              'mock': bool(args.mock), 'pack': pack, 'db_truth_pct': pct, 'claims_mismatch': claims_bad,
              'skipped_ai_unavailable': sum(1 for r in results if r.get('skipped')),
              'db_by_scenario': {k: f'{v[0]}/{v[1]}' for k, v in sorted(by_db.items())},
              'gates': {'thresholds': GATES, 'pass': gates}, 'claim_ready': all(gates.values()) and not args.mock})
    return s


# =============================================================================================== main
def build_parser():
    ap = argparse.ArgumentParser(description='Giả lập khách cho lễ tân AI theo ngành (DB truth + giám khảo).')
    ap.add_argument('--industry', required=True, choices=INDUSTRIES)
    ap.add_argument('--n', type=int, default=None, help='số cuộc chat (mặc định: 2 lượt mỗi kịch bản; --mock: 1 lượt)')
    ap.add_argument('--tag', default=None)
    ap.add_argument('--biz', default=None, help='business_id (mặc định: tiệm demo của ngành)')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--per-minute', type=int, default=17, help='nhịp gọi bot (giới hạn thật 20/phút/IP)')
    ap.add_argument('--max-turns', type=int, default=8)
    ap.add_argument('--only', default='', help='chỉ chạy các kịch bản này (phân cách dấu phẩy)')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--list', action='store_true', help='in kịch bản rồi thoát (không chat)')
    ap.add_argument('--mock', action='store_true', help='chạy thử OFFLINE: DB giả + câu soạn sẵn, không server/DeepSeek/Mongo')
    ap.add_argument('--mock-fault', choices=['lie', 'wrong_status'], default=None, help='(--mock) bot mẫu nói sai để thử bộ chấm')
    ap.add_argument('--allow-non-demo', action='store_true')
    ap.add_argument('--allow-no-pack', action='store_true', help='chạy thật dù ngành chưa có gói đặt chỗ (đo mốc trước gói)')
    ap.add_argument('--out-dir', default=OUT_DIR)
    return ap


def run(argv=None):
    a = build_parser().parse_args(argv)
    if a.mock_fault and not a.mock:
        raise SystemExit('--mock-fault chỉ dùng với --mock')
    if a.mock:
        os.environ['SIM_MOCK'] = '1'
        fdb = getattr(sys.modules.get('mongo_client'), 'db', None)
        if isinstance(fdb, FakeDB):
            fdb.reset()          # chạy lại trong cùng tiến trình (test): DB giả sạch, cùng đối tượng
        else:
            fdb = install_fake_mongo()
        for mod_name, attr in (('booking_rules', '_CACHE'), ('plans', '_PLAN_CACHE')):   # bộ nhớ đệm theo business_id
            cache = getattr(sys.modules.get(mod_name), attr, None)
            if isinstance(cache, dict):
                cache.clear()
        mock_fixture(fdb, a.industry)
        a.biz = MOCK_BIZ
    a.tag = a.tag or ('mock' if a.mock else 'baseline')
    import sim_core as core   # sau khi (có thể) thay mongo_client — sim_core đọc db lúc import
    db = core.db
    if a.mock:   # --mock tuyệt đối không chạm DB thật: mọi module đã nạp phải trỏ đúng DB giả
        for mod_name in ('sim_core', 'booking_rules', 'sim_booking'):
            mdb = getattr(sys.modules.get(mod_name), 'db', fdb)
            if mdb is not fdb:
                raise SystemExit(f'--mock: {mod_name} đã nạp MongoDB thật trước đó — chạy --mock trong tiến trình mới.')
    module = importlib.import_module(f'scenarios_{a.industry}')
    biz = resolve_business(db, a.industry, a.biz)
    shop = load_shop(db, biz, a.industry)
    preflight(db, biz, a.industry, shop, allow_non_demo=a.allow_non_demo or a.mock)
    data = module.load(db, shop)
    scenarios = module.scenarios(shop, data)
    if a.only:
        keep = set(a.only.split(','))
        scenarios = [s for s in scenarios if s['id'] in keep]
    if not scenarios:
        raise SystemExit('Không có kịch bản nào (kiểm --only / dữ liệu tiệm).')
    pack = pack_for(a.industry) or ('builtin appointment tools' if a.industry in ('nail', 'spa') else None)
    if not pack and not a.mock and not a.list and not a.allow_no_pack:
        # không có gói đặt chỗ: mọi kịch bản đặt chỗ chắc chắn trượt -> không đốt tiền, trừ khi chủ muốn đo mốc "trước gói"
        raise SystemExit(f"Chưa có gói ai_packs cho '{a.industry}' trong mã nguồn đang chạy — gộp nhánh gói trước, hoặc thêm "
                         '--allow-no-pack để đo mốc "hỏi đáp + chuyển nhân viên" (trả phí).')
    if a.list:
        for s in scenarios:
            print(f"{s['id']:<24} checks={[c['kind'] for c in s.get('checks') or []]} {s['goal'][:150]}")
        return None
    n = a.n or (len(scenarios) * (1 if a.mock else 2))
    print(f"Ngành {a.industry} · tiệm {shop['name']} ({biz}) · {len(scenarios)} kịch bản · {n} cuộc chat · "
          f"{'MOCK offline' if a.mock else core.BASE} · gói đặt chỗ: {pack or 'CHƯA CÓ (AI hỏi đáp + chuyển nhân viên — kịch bản đặt chỗ sẽ trượt)'}")
    if not a.mock:   # server local phải sống trước khi đốt tiền khách giả lập + giám khảo
        import requests
        try:
            requests.get(core.BASE + '/login', timeout=10)
        except requests.RequestException as e:
            raise SystemExit(f'Không mở được server local {core.BASE}: {e}')
    sim = Sim(a, db, module, shop, core)
    sim.facts = common_facts(shop) + '\n' + module.facts(shop, data) + DB_NOTES
    n_foreign = max((len(s.get('foreign_seeds') or []) for s in scenarios), default=0)
    taken_colls = dict(sim.colls, **({'appointments': {'phone': 'customer_phone'}} if sim.ghost else {}))
    phones = allocate_phones(db, biz, taken_colls, shop['country'], n * (1 + n_foreign))
    personas = make_personas(scenarios, n, languages_for(shop['country']), phones[:n], shop, seed=a.seed)
    for i, p in enumerate(personas):
        p['foreign_phones'] = [phones[n + i * n_foreign + j] for j in range(n_foreign)]
        with sim.lock:
            sim.phones.extend((fp[0], fp[1]) for fp in p['foreign_phones'])
    if a.mock and os.path.abspath(a.out_dir) == os.path.abspath(OUT_DIR):
        import tempfile   # chạy thử không ghi vào audit-results/ (thư mục đó được commit — chỉ chứa lượt chạy thật)
        a.out_dir = os.path.join(tempfile.gettempdir(), 'bitpaw_ai_sim_mock')
    os.makedirs(a.out_dir, exist_ok=True)
    out_path = os.path.join(a.out_dir, f'receptionist_{a.industry}_{a.tag}.jsonl')
    results = []
    try:
        with cf.ThreadPoolExecutor(1 if a.mock else a.workers) as ex, open(out_path, 'w', encoding='utf-8') as f:
            for rec in ex.map(sim.one, personas):
                results.append(rec)
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
    finally:
        print('cleaned', sim.cleanup())
    summ = summarize_receptionist(core, results, a, shop, pack)
    with open(os.path.join(a.out_dir, f'receptionist_{a.industry}_{a.tag}_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summ, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(summ, ensure_ascii=False, indent=2, default=str))
    print(f'Kết quả: {out_path} (+ _summary.json)')
    if summ['claim_ready']:
        print(f"Đạt cổng của ngành {a.industry}. Bật lại câu 'AI trả lời & đặt chỗ' là quyết định của CHỦ: "
              "db.system_settings {key: 'ai_sim_passed'} hoặc BITPAW_AI_SIM_PASSED — giả lập không tự bật.")
    return summ


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    run()
