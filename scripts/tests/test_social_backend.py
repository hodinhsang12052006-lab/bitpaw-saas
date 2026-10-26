"""Kiểm thử OFFLINE bộ đăng bài AI Social Manager (social_accounts / social_publisher / social_planner / social_bp).

KHÔNG kết nối MongoDB (mongo_client bị thay bằng DB giả trong bộ nhớ TRƯỚC khi import — import mongo_client thật là mở
kết nối tới production), KHÔNG gọi mạng (requests.request bị thay bằng bộ định tuyến giả; Session.request bị chặn hẳn),
KHÔNG gọi DeepSeek/Meta/Google/TikTok thật.
    python scripts/tests/test_social_backend.py
"""
import copy
import json
import os
import re
import struct
import sys
import traceback
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------- môi trường thử (đặt TRƯỚC khi import module)
for k in ('VERCEL_ENV', 'SOCIAL_ALLOW_TICK', 'SOCIAL_APPROVED', 'SOCIAL_META_VIDEO_BASE', 'SOCIAL_GOOGLE_AUTH_URL',
          'SOCIAL_PUBLIC_BASE', 'REPLICATE_API_BASE', 'NURTURE_CHANNEL_ENC_KEY', 'MONGO_URI'):
    os.environ.pop(k, None)
TEST_ENV = {
    'SOCIAL_META_API_BASE': 'http://meta.mock', 'SOCIAL_GOOGLE_API_BASE': 'http://google.mock',
    'SOCIAL_GOOGLE_OAUTH_BASE': 'http://gauth.mock', 'SOCIAL_TIKTOK_API_BASE': 'http://tiktok.mock',
    'SOCIAL_GBP_API_BASE': 'http://gbp.mock',
}
os.environ.update(TEST_ENV)
os.environ.update({'SOCIAL_TEST_BUSINESS_IDS': 'biz1,biz2', 'FLASK_SECRET_KEY': 'offline-test-secret',
                   'GOOGLE_CLIENT_ID': 'gcid', 'GOOGLE_CLIENT_SECRET': 'gsec', 'TIKTOK_CLIENT_KEY': 'tkey',
                   'TIKTOK_CLIENT_SECRET': 'tsec', 'PUBLIC_BASE_URL': 'https://www.bitpawsoftware.com', 'CRON_SECRET': 'cron-s3cret'})

# ---------------------------------------------------------------- Mongo giả (đủ toán tử module dùng)
from pymongo import ReturnDocument  # noqa: E402  (chỉ hằng số, không kết nối)


def _naive(v):
    """Mô phỏng pymongo: lưu UTC, đọc ra datetime NAIVE."""
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, dict):
        return {k: _naive(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_naive(x) for x in v]
    return v


def _resolve(doc, path):
    cur = [doc]
    for part in path.split('.'):
        nxt = []
        for c in cur:
            if isinstance(c, dict):
                if part in c:
                    nxt.append(c[part])
            elif isinstance(c, list):
                if part.isdigit():
                    if int(part) < len(c):
                        nxt.append(c[int(part)])
                else:
                    nxt.extend(el[part] for el in c if isinstance(el, dict) and part in el)
        cur = nxt
    return cur


def _eq(values, x):
    x = _naive(x)
    if x is None:
        return not values or any(v is None for v in values)
    return any(v == x or (isinstance(v, list) and x in v) for v in values)


def _cmp(values, arg, fn):
    arg = _naive(arg)
    for v in values:
        if v is None or arg is None:
            continue
        try:
            if fn(v, arg):
                return True
        except TypeError:
            pass
    return False


def _cond(values, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith('$') for k in cond):
        for op, arg in cond.items():
            if op == '$in':
                ok = any(_eq(values, a) for a in arg)
            elif op == '$nin':
                ok = not any(_eq(values, a) for a in arg)
            elif op == '$ne':
                ok = not _eq(values, arg)
            elif op == '$lt':
                ok = _cmp(values, arg, lambda a, b: a < b)
            elif op == '$lte':
                ok = _cmp(values, arg, lambda a, b: a <= b)
            elif op == '$gt':
                ok = _cmp(values, arg, lambda a, b: a > b)
            elif op == '$gte':
                ok = _cmp(values, arg, lambda a, b: a >= b)
            elif op == '$exists':
                ok = bool(values) == bool(arg)
            elif op == '$elemMatch':
                ok = any(isinstance(v, list) and any(isinstance(el, dict) and _match(el, arg) for el in v) for v in values)
            elif op == '$regex':
                ok = any(isinstance(v, str) and re.search(arg, v) for v in values)
            else:
                raise NotImplementedError(op)
            if not ok:
                return False
        return True
    return _eq(values, cond)


def _match(doc, q):
    for k, c in (q or {}).items():
        if k == '$or':
            if not any(_match(doc, x) for x in c):
                return False
        elif k == '$and':
            if not all(_match(doc, x) for x in c):
                return False
        elif not _cond(_resolve(doc, k), c):
            return False
    return True


def _set_path(doc, path, value):
    parts = path.split('.')
    cur = doc
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _apply(doc, update, insert=False):
    for op, fields in update.items():
        for path, v in fields.items():
            if op == '$set' or (op == '$setOnInsert' and insert):
                _set_path(doc, path, _naive(copy.deepcopy(v)))
            elif op == '$inc':
                cur = _resolve(doc, path)
                _set_path(doc, path, (cur[0] if cur else 0) + v)
            elif op == '$setOnInsert':
                pass
            else:
                raise NotImplementedError(op)


def _project(doc, proj):
    d = copy.deepcopy(doc)
    if proj and any(v for k, v in proj.items() if k != '_id'):
        return {k: d[k] for k, v in proj.items() if v and k in d}
    return d


class Res:
    def __init__(self, matched=0, inserted_id=None):
        self.matched_count = self.modified_count = self.deleted_count = matched
        self.inserted_id = inserted_id


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.docs.sort(key=lambda x: (x.get(k) is None, x.get(k) if x.get(k) is not None else 0), reverse=(d == -1))
        return self

    def limit(self, n):
        self.docs = self.docs[:n] if n else self.docs
        return self

    def __iter__(self):
        return iter(self.docs)


class Coll:
    def __init__(self, name):
        self.name, self.docs = name, []

    def create_index(self, *a, **k):
        return 'ix'

    def insert_one(self, doc):
        self.docs.append(_naive(copy.deepcopy(doc)))
        return Res(1, len(self.docs))

    def find_one(self, q=None, proj=None):
        for d in self.docs:
            if _match(d, q or {}):
                return _project(d, proj)
        return None

    def find(self, q=None, proj=None):
        return Cursor([_project(d, proj) for d in self.docs if _match(d, q or {})])

    def count_documents(self, q):
        return sum(1 for d in self.docs if _match(d, q))

    def _first(self, q, sort=None):
        hits = [d for d in self.docs if _match(d, q)]
        for k, direction in reversed(sort or []):
            hits.sort(key=lambda x: (x.get(k) is None, x.get(k) if x.get(k) is not None else 0), reverse=(direction == -1))
        return hits[0] if hits else None

    def find_one_and_update(self, q, update, sort=None, projection=None, return_document=ReturnDocument.BEFORE, upsert=False):
        d = self._first(q, sort)
        if d is None:
            return None
        before = _project(d, projection)
        _apply(d, update)
        return _project(d, projection) if return_document == ReturnDocument.AFTER else before

    def update_one(self, q, update, upsert=False):
        d = self._first(q)
        if d is None:
            if upsert:
                new = {k: v for k, v in q.items() if not k.startswith('$') and not isinstance(v, dict)}
                _apply(new, update, insert=True)
                self.docs.append(_naive(new))
            return Res(0)
        _apply(d, update)
        return Res(1)

    def update_many(self, q, update):
        hits = [d for d in self.docs if _match(d, q)]
        for d in hits:
            _apply(d, update)
        return Res(len(hits))

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                del self.docs[i]
                return Res(1)
        return Res(0)

    def delete_many(self, q):
        n = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, q)]
        return Res(n - len(self.docs))


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._c.setdefault(name, Coll(name))

    def reset(self):
        self._c.clear()


DB = FakeDB()
_ids = {}


def _next_id(name):
    _ids[name] = _ids.get(name, 0) + 1
    return _ids[name]


sys.modules['mongo_client'] = types.SimpleNamespace(db=DB, next_mongo_id=_next_id)

# ---------------------------------------------------------------- module giả: media_store, messaging, AI, app
MEDIA = {}


class FakeGridOut:
    def __init__(self, data, content_type, kind, business_id, length=None):
        self._data, self.content_type, self.kind, self.business_id = data, content_type, kind, business_id
        self.length = len(data) if length is None else length   # length giả: thử ảnh "nặng" mà không cấp phát nhiều MB

    def read(self):
        return self._data


def _ms_get(file_id, business_id=None):
    g = MEDIA.get(str(file_id))
    if g is None or (business_id is not None and g.business_id != business_id):
        return None
    return g


sys.modules['media_store'] = types.SimpleNamespace(
    KINDS={'ai_image', 'ai_video', 'promo_video', 'social_upload'}, get=_ms_get, FULL_MAX=3_200_000,
    public_url=lambda fid, ext: f"/m/{fid}.tok.{ext}",
    absolute_public_url=lambda fid, ext, base: f"{base.rstrip('/')}/m/{fid}.tok.{ext}")
sys.modules['messaging'] = types.SimpleNamespace(get_settings=lambda bid: {'timezone': 'Australia/Sydney', 'language': 'en'})
AI = {'fn': None, 'calls': 0, 'payloads': []}


def _deepseek(system, user, temperature, max_tokens, business_id):
    AI['calls'] += 1
    if AI['fn'] is None:
        raise AssertionError('DeepSeek must not be called here')
    out = AI['fn'](system, user)
    return out[0] if isinstance(out, tuple) else out


def _ds_completion(payload, business_id=None, proxy_api_key=None, direct_api_key=None, timeout=45):
    """Giả ai_deepseek_client.deepseek_chat_completion (kế hoạch tuần gọi thẳng để đọc finish_reason).
    AI['fn'] trả text hoặc (text, finish_reason)."""
    AI['calls'] += 1
    AI['payloads'].append(payload)
    if AI['fn'] is None:
        raise AssertionError('DeepSeek must not be called here')
    msgs = payload['messages']
    out = AI['fn'](msgs[0]['content'], msgs[1]['content'])
    text, finish = out if isinstance(out, tuple) else (out, 'stop')
    return {'choices': [{'message': {'content': text}, 'finish_reason': finish}]}


sys.modules['ai_deepseek_client'] = types.SimpleNamespace(deepseek_chat_completion=_ds_completion)


sys.modules['ai_studio_bp'] = types.SimpleNamespace(_call_deepseek_text=_deepseek,
                                                    _business_facts=lambda bid: 'BUSINESS FACTS (real): Golden Nails\nServices: Gel $45.00')


class _Nurture:
    @staticmethod
    def booking_link(business_id, industry, base_url=None):
        return f"{(base_url or '').rstrip('/')}/booking/nail/qr/{business_id}" if industry in ('nail', 'nails') else None


sys.modules['ai_nurturing_engine'] = types.SimpleNamespace(AINurturingEngine=_Nurture)
sys.modules['currency_utils'] = types.SimpleNamespace(format_money=lambda a, c='USD': f"${float(a):,.2f}")

from functools import wraps  # noqa: E402
from flask import jsonify as _fj, session as _fs  # noqa: E402


def _login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'user_id' not in _fs:
            return _fj({'success': False}), 401
        return f(*a, **k)
    return w


def _role_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if _fs.get('role', 'staff') not in roles:
                return _fj({'success': False, 'message': 'forbidden'}), 403
            return f(*a, **k)
        return w
    return deco


sys.modules['app'] = types.SimpleNamespace(login_required=_login_required, role_required=_role_required,
                                           _tenant_currency=lambda bid: 'AUD')

# ---------------------------------------------------------------- HTTP giả
import requests  # noqa: E402


class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.content = json.dumps(body).encode() if body is not None else b''
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


class Call:
    def __init__(self, method, url, kw):
        self.method, self.url, self.kw = method, url, kw
        u = urlsplit(url)
        self.path = u.path
        self.query = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.query.update({k: str(v) for k, v in (kw.get('params') or {}).items()})
        self.data = kw.get('data')
        self.json = kw.get('json')
        self.files = kw.get('files') or {}
        self.headers = kw.get('headers') or {}


class Router:
    def __init__(self):
        self.routes, self.calls = [], []

    def on(self, method, pattern, handler):
        self.routes.append((method, re.compile(pattern), handler))

    def reset(self):
        self.routes, self.calls = [], []

    def __call__(self, method, url, timeout=None, **kw):
        assert timeout is not None, 'every request needs a timeout'
        call = Call(method, url, kw)
        self.calls.append(call)
        for m, pat, h in reversed(self.routes):
            if m == method and pat.search(url.split('?')[0]):
                out = h(call) if callable(h) else h
                if isinstance(out, FakeResp):
                    return out
                if isinstance(out, tuple):
                    return FakeResp(*out)
                return FakeResp(200, out)
        raise AssertionError(f"unmocked {method} {url}")

    def find(self, method, part):
        return [c for c in self.calls if c.method == method and part in c.url]


HTTP = Router()
requests.request = HTTP


def _no_network(*a, **k):
    raise AssertionError('real network call attempted')


requests.sessions.Session.request = _no_network
requests.get = requests.post = requests.put = requests.delete = _no_network

# ---------------------------------------------------------------- module cần thử
import nurture_channel_tokens as vault  # noqa: E402
import social_accounts as sa  # noqa: E402
import social_publisher as sp  # noqa: E402
import social_planner as pl  # noqa: E402

assert sa.META_API == 'http://meta.mock' and sa.META_VIDEO_API == 'http://meta.mock', 'test mode must route Meta video to mock'
assert sa.GRAPH_V == 'v23.0'


# ---------------------------------------------------------------- tiện ích
def reset():
    DB.reset()
    HTTP.reset()
    MEDIA.clear()
    AI['fn'], AI['calls'], AI['payloads'] = None, 0, []
    os.environ.update(TEST_ENV)
    for k in ('VERCEL_ENV', 'SOCIAL_ALLOW_TICK'):
        os.environ.pop(k, None)
    DB.businesses.insert_one({'id': 'biz1', 'name': 'Golden Nails', 'industry_code': 'nail'})


def now0():
    # +1 giây: bài vừa tạo (scheduled_at = giờ thật, có micro giây) luôn "tới giờ" ở mốc thử
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)


def account(bid, platform, ext, token='tok', qa=True, **extra):
    doc = {'business_id': bid, 'platform': platform, 'status': 'connected', 'account_name': f"{platform} acct", 'external_id': ext,
           'token_enc': vault.encrypt_secret(token), 'refresh_token_enc': None, 'connected_via': 'token', 'qa_test': qa,
           'token_expires_at': None, 'connected_at': now0(), 'updated_at': now0(), 'last_error': None}
    doc.update(extra)
    DB.social_accounts.insert_one(doc)


def media(fid, ct, kind='social_upload', bid='biz1', data=None, length=None):
    MEDIA[fid] = FakeGridOut(data or (b'\xff\xd8\xff' + b'x' * 64 if ct.startswith('image') else b'\x00' * 256), ct, kind, bid,
                             length)


def mp4(seconds, pad=2048):
    """MP4 tối thiểu có hộp mvhd (version 0, size 108) để đọc thời lượng."""
    body = bytes([0, 0, 0, 0]) + struct.pack('>IIII', 0, 0, 1000, int(seconds * 1000)) + b'\x00' * 80
    mvhd = struct.pack('>I', 8 + len(body)) + b'mvhd' + body
    assert len(mvhd) == 108
    moov = struct.pack('>I', 8 + len(mvhd)) + b'moov' + mvhd
    return b'\x00\x00\x00\x18ftypisom' + b'\x00' * 12 + moov + b'\x00' * pad


def post(bid='biz1', **data):
    data.setdefault('status', 'scheduled')
    return sp.create_post(bid, 'u1', data)


def stored(pid):
    return DB.social_posts.find_one({'id': pid})


def target(pid, platform):
    return next(t for t in stored(pid)['targets'] if t['platform'] == platform)


RESULTS = []


def check(name, cond, note=''):
    RESULTS.append((name, bool(cond)))
    if not cond:
        raise AssertionError(f"{name} {note}")


# ---------------------------------------------------------------- các bài thử
def test_fb_photo_publish():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    media('img1', 'image/jpeg')

    def photos(c):
        check('fb photo multipart source', 'source' in c.files and c.files['source'][2] == 'image/jpeg')
        check('fb photo caption + hashtags', 'Gel special' in c.data['caption'] and '#nails' in c.data['caption'])
        check('fb photo token', c.data['access_token'] == 'fb-token')
        check('fb photo not scheduled', 'scheduled_publish_time' not in c.data)
        return {'id': 'PH1', 'post_id': 'PAGE1_99'}
    HTTP.on('POST', r'meta\.mock/v23\.0/PAGE1/photos$', photos)
    p = post(caption='Gel special this week', hashtags=['nails'], media_file_ids=['img1'], targets=[{'platform': 'facebook'}])
    check('created scheduled', p['status'] == 'scheduled' and p['media_type'] == 'image' and p['qa_test'] is True)
    st = sp.run_due('biz1', now=now0())
    check('fb photo stats', st['claimed'] == 1 and st['published'] == 1, st)
    t = target(p['id'], 'facebook')
    check('fb photo target published', t['status'] == 'published' and t['remote_id'] == 'PAGE1_99' and t['permalink'].endswith('PAGE1_99'))
    check('fb post published + lease released', stored(p['id'])['status'] == 'published' and stored(p['id'])['lease_owner'] is None)
    pub = sp.public_post(stored(p['id']))
    check('public post iso Z + media url', pub['scheduled_at'].endswith('Z') and pub['media'][0]['url'] == '/m/img1.tok.jpg')
    check('second run does nothing', sp.run_due('biz1', now=now0())['claimed'] == 0)


def test_fb_native_schedule():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    t0 = now0()
    when = t0 + timedelta(hours=2)

    def feed(c):
        check('native: published=false', c.data.get('published') == 'false')
        check('native: unix time', c.data.get('scheduled_publish_time') == str(int(when.timestamp())))
        check('native: link', c.data.get('link') == 'https://goldennails.example/book')
        return {'id': 'PAGE1_77'}
    HTTP.on('POST', r'/PAGE1/feed$', feed)
    p = post(caption='Weekend slots open', link='https://goldennails.example/book', targets=['facebook'],
             scheduled_at=when.isoformat().replace('+00:00', 'Z'))
    st = sp.run_due('biz1', now=t0)
    check('prepush claimed', st['claimed'] == 1 and st['processing'] == 1, st)
    t = target(p['id'], 'facebook')
    check('target scheduled_remote', t['status'] == 'scheduled_remote' and t['remote_id'] == 'PAGE1_77')
    check('post still scheduled', stored(p['id'])['status'] == 'scheduled')
    check('prepush once', sp.run_due('biz1', now=t0 + timedelta(minutes=5))['claimed'] == 0)
    # tới giờ: bài vào 'publishing', chưa kiểm tra (Meta cần 2 phút)
    sp.run_due('biz1', now=when)
    check('due -> publishing, no check yet', stored(p['id'])['status'] == 'publishing' and not HTTP.find('GET', 'PAGE1_77'))
    HTTP.on('GET', r'/v23\.0/PAGE1_77$', lambda c: {'is_published': True, 'permalink_url': 'https://www.facebook.com/goldennails/posts/77'})
    st = sp.run_due('biz1', now=when + timedelta(minutes=3))
    check('check fields', HTTP.find('GET', 'PAGE1_77')[0].query['fields'] == 'is_published,permalink_url')
    t = target(p['id'], 'facebook')
    check('native published', t['status'] == 'published' and t['permalink'].endswith('/posts/77') and stored(p['id'])['status'] == 'published')

    # ảnh hẹn giờ: tải ảnh tạm rồi /feed gắn ảnh
    HTTP.reset()
    media('img2', 'image/jpeg')
    HTTP.on('POST', r'/PAGE1/photos$', lambda c: ({'id': 'TMP1'} if c.data.get('temporary') == 'true' and c.data.get('published') == 'false'
                                                  else (400, {'error': {'message': 'bad', 'code': 100}})))
    HTTP.on('POST', r'/PAGE1/feed$', lambda c: {'id': 'PAGE1_88'} if json.loads(c.data['attached_media'])[0]['media_fbid'] == 'TMP1'
            and c.data.get('published') == 'false' else (400, {'error': {'message': 'bad', 'code': 100}}))
    p2 = post(caption='New gel colours', media_file_ids=['img2'], targets=['facebook'], scheduled_at=(t0 + timedelta(days=1)).isoformat())
    sp.run_due('biz1', now=t0)
    check('native photo scheduled_remote', target(p2['id'], 'facebook')['status'] == 'scheduled_remote'
          and target(p2['id'], 'facebook')['remote_id'] == 'PAGE1_88')
    # sửa bài đã đẩy lên Meta: gỡ lịch bên Meta trước, đích làm lại từ đầu
    HTTP.on('DELETE', r'/v23\.0/PAGE1_88$', {'success': True})
    sp.update_post('biz1', p2['id'], {'caption': 'New gel colours — updated'}, 'u1')
    check('edit unschedules remote', HTTP.find('DELETE', 'PAGE1_88') and target(p2['id'], 'facebook')['status'] == 'pending')


def test_ig_reels_two_runs():
    reset()
    account('biz1', 'instagram', 'IG1', 'ig-token')
    vid = mp4(9, pad=9000)
    media('vid1', 'video/mp4', kind='ai_video', data=vid)

    def create(c):
        check('reels media_type', c.data['media_type'] == 'REELS' and c.data['share_to_feed'] == 'true')
        # SOC-3: Reels tải byte thẳng lên Instagram (resumable) — không nhờ Instagram tải link /m/ (Vercel cắt file lớn)
        check('reels resumable, no video_url', c.data.get('upload_type') == 'resumable' and 'video_url' not in c.data)
        # link Meta trả về ở host khác host rupload đã cấu hình -> không dùng (token không đi tới host lạ)
        return {'id': 'C1', 'uri': 'https://rupload.facebook.com/ig-api-upload/v23.0/C1'}

    def rupload(c):
        check('rupload OAuth header + offset + size', c.headers.get('Authorization') == 'OAuth ig-token'
              and c.headers.get('offset') == '0' and c.headers.get('file_size') == str(len(vid)))
        check('rupload sends the whole file', c.data == vid)
        return {'success': True, 'message': 'Upload successful.'}
    HTTP.on('POST', r'/IG1/media$', create)
    HTTP.on('POST', r'meta\.mock/ig-api-upload/v23\.0/C1$', rupload)
    p = post(caption='Watch this', hashtags=['nailart'], media_file_ids=['vid1'], targets=['instagram'])
    t0 = now0()
    st = sp.run_due('biz1', now=t0)
    t = target(p['id'], 'instagram')
    check('reels uploaded once', len(HTTP.find('POST', 'ig-api-upload')) == 1)
    check('reels processing', st['processing'] == 1 and t['status'] == 'processing' and t['container_id'] == 'C1')
    check('post publishing', stored(p['id'])['status'] == 'publishing')
    check('not polled before next_attempt_at', sp.run_due('biz1', now=t0 + timedelta(seconds=10))['claimed'] == 0)
    HTTP.on('GET', r'/v23\.0/C1$', {'status_code': 'FINISHED', 'status': 'Finished: Media has been uploaded'})
    HTTP.on('GET', r'/IG1/content_publishing_limit$', {'data': [{'quota_usage': 3, 'config': {'quota_total': 50, 'quota_duration': 86400}}]})
    HTTP.on('POST', r'/IG1/media_publish$', lambda c: {'id': 'M1'} if c.data['creation_id'] == 'C1' else (400, {'error': {'code': 100}}))
    HTTP.on('GET', r'/v23\.0/M1$', {'permalink': 'https://www.instagram.com/reel/abc/'})
    st = sp.run_due('biz1', now=t0 + timedelta(minutes=1))
    t = target(p['id'], 'instagram')
    check('reels published on 2nd run', st['published'] == 1 and t['status'] == 'published' and t['remote_id'] == 'M1'
          and t['permalink'].endswith('/reel/abc/'))
    check('post published', stored(p['id'])['status'] == 'published')

    # hết lượt 24 giờ -> bỏ qua, nói rõ
    reset()
    account('biz1', 'instagram', 'IG1', 'ig-token')
    media('img9', 'image/jpeg')
    HTTP.on('POST', r'/IG1/media$', {'id': 'C9'})
    HTTP.on('GET', r'/IG1/content_publishing_limit$', {'data': [{'quota_usage': 50, 'config': {'quota_total': 50}}]})
    p = post(caption='Photo', media_file_ids=['img9'], targets=['instagram'])
    sp.run_due('biz1', now=now0())
    t = target(p['id'], 'instagram')
    check('ig daily limit skipped', t['status'] == 'skipped' and t['error']['code'] == 'ig_daily_limit' and not HTTP.find('POST', 'media_publish'))
    check('all skipped -> failed', stored(p['id'])['status'] == 'failed')


def test_youtube_resumable():
    reset()
    account('biz1', 'youtube', 'UC1', 'ya29.tok', connected_via='oauth', token_expires_at=now0() + timedelta(hours=1))
    data = mp4(8)
    media('vid2', 'video/mp4', kind='ai_video', data=data)

    def init(c):
        check('yt resumable params', c.query.get('uploadType') == 'resumable' and c.query.get('part') == 'snippet,status')
        check('yt bearer', c.headers['Authorization'] == 'Bearer ya29.tok')
        check('yt upload length', c.headers['X-Upload-Content-Length'] == str(len(data)) and c.headers['X-Upload-Content-Type'] == 'video/mp4')
        s = c.json['status']
        check('yt status fields', s['privacyStatus'] == 'public' and s['selfDeclaredMadeForKids'] is False and s['containsSyntheticMedia'] is True)
        check('yt title', c.json['snippet']['title'] == 'Gel in 8 seconds' and c.json['snippet']['categoryId'] == '22')
        return FakeResp(200, {}, {'Location': 'http://google.mock/upload/session/abc'})

    def put(c):
        check('yt PUT bytes', c.data == data and c.headers['Content-Type'] == 'video/mp4')
        return {'id': 'VID9', 'status': {'privacyStatus': 'private', 'uploadStatus': 'uploaded'}}
    HTTP.on('POST', r'google\.mock/upload/youtube/v3/videos$', init)
    HTTP.on('PUT', r'google\.mock/upload/session/abc$', put)
    p = post(caption='Gel in 8 seconds\nBook now', title='', media_file_ids=['vid2'], targets=['youtube'])
    st = sp.run_due('biz1', now=now0())
    t = target(p['id'], 'youtube')
    check('yt published', st['published'] == 1 and t['status'] == 'published' and t['remote_id'] == 'VID9'
          and t['permalink'] == 'https://youtu.be/VID9' and t['visibility'] == 'private')


def test_tiktok_init_put_status():
    reset()
    account('biz1', 'tiktok', 'OPEN1', 'act.tok', connected_via='oauth', token_expires_at=now0() + timedelta(hours=10))
    data = mp4(10)
    media('vid3', 'video/mp4', kind='promo_video', data=data)
    opts = {'privacy_level': 'SELF_ONLY', 'disable_comment': False, 'disable_duet': True, 'disable_stitch': True,
            'brand_content_toggle': False, 'brand_organic_toggle': False}
    try:
        post(caption='x', media_file_ids=['vid3'], targets=[{'platform': 'tiktok', 'options': {'privacy_level': 'SELF_ONLY'}}])
        check('tiktok options required', False)
    except sa.SocialError as e:
        check('tiktok options required', e.code == 'tiktok_options_required')
    HTTP.on('POST', r'/v2/post/publish/creator_info/query/$', {'data': {'privacy_level_options': ['PUBLIC_TO_EVERYONE', 'SELF_ONLY'],
                                                                         'max_video_post_duration_sec': 60, 'creator_username': 'goldennails',
                                                                         'comment_disabled': False}, 'error': {'code': 'ok'}})

    def init(c):
        pi, si = c.json['post_info'], c.json['source_info']
        check('tt post_info', pi['privacy_level'] == 'SELF_ONLY' and pi['disable_duet'] is True and pi['is_aigc'] is False
              and pi['brand_content_toggle'] is False)
        check('tt single chunk', si == {'source': 'FILE_UPLOAD', 'video_size': len(data), 'chunk_size': len(data), 'total_chunk_count': 1})
        return {'data': {'publish_id': 'v_pub_1', 'upload_url': 'http://tiktok-upload.mock/upload/1'}, 'error': {'code': 'ok'}}
    HTTP.on('POST', r'/v2/post/publish/video/init/$', init)

    def put(c):
        n = len(data)
        check('tt content-range', c.headers['Content-Range'] == f'bytes 0-{n - 1}/{n}' and c.headers['Content-Type'] == 'video/mp4')
        return FakeResp(201, {})
    HTTP.on('PUT', r'tiktok-upload\.mock/upload/1$', put)
    info = sp.tiktok_creator_info('biz1')
    check('tt creator info for compose UI', info['creator_username'] == 'goldennails' and 'SELF_ONLY' in info['privacy_level_options'])
    p = post(caption='Chrome nails', media_file_ids=['vid3'], targets=[{'platform': 'tiktok', 'options': opts}])
    t0 = now0()
    sp.run_due('biz1', now=t0)
    t = target(p['id'], 'tiktok')
    check('tt processing', t['status'] == 'processing' and t['container_id'] == 'v_pub_1')
    HTTP.on('POST', r'/v2/post/publish/status/fetch/$', lambda c: {'data': {'status': 'PUBLISH_COMPLETE', 'publicaly_available_post_id': [7300]},
                                                                   'error': {'code': 'ok'}} if c.json['publish_id'] == 'v_pub_1' else {})
    sp.run_due('biz1', now=t0 + timedelta(minutes=1))
    t = target(p['id'], 'tiktok')
    check('tt published', t['status'] == 'published' and t['remote_id'] == '7300'
          and t['permalink'] == 'https://www.tiktok.com/@goldennails/video/7300')
    # video quá dài so với giới hạn của tài khoản
    media('vid4', 'video/mp4', kind='promo_video', data=mp4(90))
    p2 = post(caption='Long', media_file_ids=['vid4'], targets=[{'platform': 'tiktok', 'options': opts}])
    sp.run_due('biz1', now=t0 + timedelta(minutes=2))
    check('tt too long', target(p2['id'], 'tiktok')['error']['code'] == 'tiktok_too_long')
    check('mp4 duration parser', abs(sp._mp4_duration(mp4(12.5)) - 12.5) < 1e-6 and sp._mp4_duration(b'random mvhd bytes') is None)


def test_gbp_local_post():
    reset()
    account('biz1', 'google_business', 'accounts/1/locations/2', 'ya29.gbp', connected_via='oauth',
            token_expires_at=now0() + timedelta(hours=1))
    media('img3', 'image/jpeg', kind='ai_image')

    def lp(c):
        b = c.json
        check('gbp summary no hashtags', '#' not in b['summary'] and 'Fresh gel colours' in b['summary'])
        check('gbp CTA BOOK', b['callToAction'] == {'actionType': 'BOOK', 'url': 'https://www.bitpawsoftware.com/booking/nail/qr/biz1'})
        check('gbp photo url', b['media'] == [{'mediaFormat': 'PHOTO', 'sourceUrl': 'https://www.bitpawsoftware.com/m/img3.tok.jpg'}])
        check('gbp topic + lang', b['topicType'] == 'STANDARD' and b['languageCode'] == 'en')
        return {'name': 'accounts/1/locations/2/localPosts/LP1', 'state': 'LIVE', 'searchUrl': 'https://local.google.com/place?lp=1'}
    HTTP.on('POST', r'gbp\.mock/v4/accounts/1/locations/2/localPosts$', lp)
    p = post(caption='Fresh gel colours #nails #gel', media_file_ids=['img3'], targets=['google_business'])
    sp.run_due('biz1', now=now0())
    t = target(p['id'], 'google_business')
    check('gbp published', t['status'] == 'published' and t['remote_id'].endswith('LP1') and t['permalink'].startswith('https://local.google'))
    media('vid5', 'video/mp4')
    p2 = post(caption='Video', media_file_ids=['vid5'], targets=['google_business'])
    check('gbp video warning up front', p2['warnings'][0]['code'] == 'gbp_no_video')
    sp.run_due('biz1', now=now0())
    check('gbp video skipped', target(p2['id'], 'google_business')['error']['code'] == 'gbp_no_video')


def test_transient_retry_then_success():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    n = {'i': 0}

    def feed(c):
        n['i'] += 1
        return (500, {'error': {'message': 'An unexpected error has occurred.', 'code': 2, 'is_transient': True}}) if n['i'] == 1 else {'id': 'PAGE1_5'}
    HTTP.on('POST', r'/PAGE1/feed$', feed)
    p = post(caption='Hello', targets=['facebook'])
    t0 = now0()
    st = sp.run_due('biz1', now=t0)
    t = target(p['id'], 'facebook')
    check('transient -> retrying', st['retrying'] == 1 and t['status'] == 'pending' and t['attempts'] == 1
          and sa.as_utc(t['next_attempt_at']) == t0 + timedelta(minutes=2) and t['error']['code'] == 'provider_busy')
    check('post stays publishing', stored(p['id'])['status'] == 'publishing')
    check('backoff respected', sp.run_due('biz1', now=t0 + timedelta(minutes=1))['claimed'] == 0)
    st = sp.run_due('biz1', now=t0 + timedelta(minutes=3))
    check('retry succeeded', st['published'] == 1 and target(p['id'], 'facebook')['status'] == 'published'
          and stored(p['id'])['status'] == 'published')
    # Meta rate limit (code 4, HTTP 400) cũng là lỗi tạm; 5 lần liên tiếp -> failed
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    HTTP.on('POST', r'/PAGE1/feed$', (400, {'error': {'message': 'Application request limit reached', 'code': 4}}))
    p = post(caption='Hello', targets=['facebook'])
    t = t0
    for _ in range(5):
        sp.run_due('biz1', now=t)
        t += timedelta(hours=1)
    tg = target(p['id'], 'facebook')
    check('max attempts -> failed', tg['status'] == 'failed' and tg['attempts'] == 5 and stored(p['id'])['status'] == 'failed')


def test_token_190_needs_reconnect():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'old-token')
    HTTP.on('POST', r'/PAGE1/feed$', (400, {'error': {'message': 'Error validating access token', 'type': 'OAuthException', 'code': 190}}))
    p = post(caption='Hi', targets=['facebook'])
    sp.run_due('biz1', now=now0())
    t = target(p['id'], 'facebook')
    acc = DB.social_accounts.find_one({'business_id': 'biz1', 'platform': 'facebook'})
    check('190 target failed', t['status'] == 'failed' and t['error']['code'] == 'token_invalid')
    check('190 account needs_reconnect', acc['status'] == 'needs_reconnect' and acc['last_error']['code'] == 'token_invalid')
    check('190 post failed', stored(p['id'])['status'] == 'failed')
    check('public status shows reconnect', sa.public_status('biz1')['facebook']['status'] == 'needs_reconnect')
    try:
        post(caption='again', targets=['facebook'])
        check('schedule refused while reconnect needed', False)
    except sa.SocialError as e:
        check('schedule refused while reconnect needed', e.code == 'not_connected')


def test_lease_blocks_second_worker():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    p = post(caption='Lease', targets=['facebook'])
    t0 = now0()
    scope = sp._scope('biz1', None)
    a = sp._claim(scope, t0, 'worker-A', 'due')
    check('A claims', a is not None and a['id'] == p['id'])
    check('B blocked while leased', sp._claim(scope, t0 + timedelta(minutes=1), 'worker-B', 'due') is None)
    b = sp._claim(scope, t0 + timedelta(minutes=6), 'worker-B', 'due')
    check('B claims after lease expiry', b is not None and stored(p['id'])['lease_owner'] == 'worker-B')
    check('A cannot write after losing lease', not sp._save_target(p['id'], 0, {'status': 'published'}, 'worker-A', t0))

    # máy B chạy run_due ĐÚNG LÚC máy A đang gọi Meta -> B không nhận được bài
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb-token')
    seen = {}

    def feed(c):
        seen['b'] = sp.run_due('biz1', now=t0, worker='worker-B')
        return {'id': 'PAGE1_1'}
    HTTP.on('POST', r'/PAGE1/feed$', feed)
    p = post(caption='Concurrent', targets=['facebook'])
    st = sp.run_due('biz1', now=t0, worker='worker-A')
    check('concurrent worker claimed nothing', seen['b']['claimed'] == 0 and st['published'] == 1)
    check('posted exactly once', len(HTTP.find('POST', '/PAGE1/feed')) == 1)


def test_test_mode_filter_and_tick_guard():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb1')
    account('biz2', 'facebook', 'PAGE2', 'fb2-real', qa=False)
    account('biz3', 'facebook', 'PAGE3', 'fb3')
    HTTP.on('POST', r'/PAGE\d/feed$', lambda c: {'id': c.path.split('/')[2] + '_1'})
    p1 = post('biz1', caption='qa post', targets=['facebook'])
    p3 = post('biz3', caption='qa post other shop', targets=['facebook'], status='draft')
    # bài THẬT (tạo trên production) của biz2 và biz3 — không bao giờ được chạy từ máy thử
    now = now0()
    for bid, pid in (('biz2', 900), ('biz3', 901)):
        DB.social_posts.insert_one({'id': pid, 'business_id': bid, 'status': 'scheduled', 'scheduled_at': now - timedelta(minutes=1),
                                    'caption': 'real', 'captions': {}, 'hashtags': [], 'media': [], 'media_type': 'text',
                                    'targets': [sp._fresh_target('facebook', {})], 'qa_test': False, 'lease_until': None})
    DB.social_posts.update_one({'id': p3['id']}, {'$set': {'status': 'scheduled', 'scheduled_at': now - timedelta(minutes=1)}})
    st = sp.run_due(None, now=now)
    check('tick refused off production', st.get('blocked') == 'not_production' and st['claimed'] == 0)
    check('sync refused off production', sp.sync_metrics(None) == 0)
    check('pump for non-test shop refused', sp.run_due('biz3', now=now).get('blocked') == 'test_mode_business')
    os.environ['SOCIAL_ALLOW_TICK'] = '1'
    st = sp.run_due(None, now=now)
    check('tick in test mode: only qa posts of test shops', st['claimed'] == 1 and stored(p1['id'])['status'] == 'published')
    check('real post untouched', stored(900)['status'] == 'scheduled' and stored(901)['status'] == 'scheduled')
    check('other shop qa post untouched', stored(p3['id'])['status'] == 'scheduled')
    check('only PAGE1 called', [c.path for c in HTTP.calls] == ['/v23.0/PAGE1/feed'])
    # production: không còn biến máy giả + VERCEL_ENV=production -> chỉ bài thật, bỏ qua bài qa_test và tài khoản qa
    for k in TEST_ENV:
        os.environ.pop(k)
    os.environ.pop('SOCIAL_ALLOW_TICK')
    os.environ['VERCEL_ENV'] = 'production'
    try:
        check('test_mode off', not sa.test_mode())
        HTTP.calls.clear()
        st = sp.run_due(None, now=now)
        check('production claims real posts only', st['claimed'] == 2 and stored(p3['id'])['status'] == 'scheduled', st)
        check('real biz2 published with real account', stored(900)['status'] == 'published')
        t901 = stored(901)['targets'][0]
        check('qa account never used in production', t901['status'] == 'failed' and t901['error']['code'] == 'not_connected')
        check('production: qa post hidden from lists', [p['id'] for p in sp.list_posts('biz1')] == [])
    finally:
        os.environ.pop('VERCEL_ENV', None)
        os.environ.update(TEST_ENV)


def _metric_post(pid, when, rate, platform='facebook'):
    DB.social_posts.insert_one({'id': pid, 'business_id': 'biz1', 'status': 'published', 'scheduled_at': when, 'qa_test': True,
                                'caption': f'post {pid}', 'media_type': 'image',
                                'targets': [{'platform': platform, 'status': 'published', 'remote_id': f'R{pid}', 'published_at': when}]})
    DB.social_post_metrics.insert_one({'business_id': 'biz1', 'post_id': pid, 'platform': platform, 'remote_id': f'R{pid}',
                                       'fetched_at': when, 'metrics': {'reach': 1000, 'likes': int(rate * 1000), 'comments': 0}})


def test_best_times_learned_vs_default():
    reset()
    from zoneinfo import ZoneInfo
    syd = ZoneInfo('Australia/Sydney')
    base = datetime(2026, 9, 7, 20, 0, tzinfo=syd)   # thứ Hai 20:00 giờ Sydney
    d = pl.best_times('biz1', 'facebook')
    check('default with no data', d['source'] == 'default' and d['sample_size'] == 0 and d['slots'][0] == {'weekday': 3, 'hour': 12, 'score': 1.0})
    for i in range(5):
        _metric_post(100 + i, (base + timedelta(weeks=i)).astimezone(timezone.utc), 0.40)
    for i in range(4):
        _metric_post(200 + i, (base.replace(hour=12) + timedelta(days=3, weeks=i)).astimezone(timezone.utc), 0.05)
    d = pl.best_times('biz1', 'facebook')
    check('9 posts -> still default', d['source'] == 'default' and d['sample_size'] == 9 and 'switches' in d['note'])
    _metric_post(204, (base.replace(hour=12) + timedelta(days=3, weeks=5)).astimezone(timezone.utc), 0.05)
    d = pl.best_times('biz1', 'facebook')
    check('10 posts -> learned', d['source'] == 'learned' and d['sample_size'] == 10)
    check('strong real slot wins over prior', d['slots'][0]['weekday'] == 0 and d['slots'][0]['hour'] == 20, d['slots'])
    check('weak real slot drops', all(not (s['weekday'] == 3 and s['hour'] == 12) for s in d['slots']), d['slots'])
    check('other platform still default', pl.best_times('biz1', 'instagram')['source'] == 'default')
    nxt = pl.next_slot('biz1', 'facebook', datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc))
    loc = nxt.astimezone(syd)
    check('next_slot in shop time', loc.weekday() == 0 and loc.hour == 20 and nxt.tzinfo is not None, loc)


def test_sync_metrics_real_fields_only():
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    account('biz1', 'instagram', 'IG1', 'ig')
    t0 = now0()
    DB.social_posts.insert_one({'id': 50, 'business_id': 'biz1', 'status': 'published', 'scheduled_at': t0 - timedelta(hours=5),
                                'qa_test': True, 'caption': 'c', 'media_type': 'image',
                                'targets': [{'platform': 'facebook', 'status': 'published', 'remote_id': 'PAGE1_50', 'remote_kind': 'post',
                                             'published_at': t0 - timedelta(hours=5)},
                                            {'platform': 'instagram', 'status': 'published', 'remote_id': 'M50',
                                             'published_at': t0 - timedelta(hours=5)}]})
    HTTP.on('GET', r'/PAGE1_50/insights$', {'data': [{'name': 'post_media_view', 'values': [{'value': 321}]}]})
    HTTP.on('GET', r'/v23\.0/PAGE1_50$', {'likes': {'summary': {'total_count': 12}}, 'comments': {'summary': {'total_count': 3}}})
    HTTP.on('GET', r'/M50/insights$', (400, {'error': {'message': 'not supported', 'code': 100}}))
    HTTP.on('GET', r'/v23\.0/M50$', {'like_count': 7, 'comments_count': 1})
    n = sp.sync_metrics('biz1', now=t0)
    fb = DB.social_post_metrics.find_one({'post_id': 50, 'platform': 'facebook'})['metrics']
    ig = DB.social_post_metrics.find_one({'post_id': 50, 'platform': 'instagram'})['metrics']
    check('metrics rows', n == 2)
    check('fb only returned fields', fb == {'views': 321, 'likes': 12, 'comments': 3}, fb)
    check('ig fallback fields', ig == {'likes': 7, 'comments': 1}, ig)
    check('next fetch scheduled', sa.as_utc(stored(50)['targets'][0]['metrics_next_at']) == t0 + timedelta(hours=3))
    check('not refetched early', sp.sync_metrics('biz1', now=t0 + timedelta(hours=1)) == 0)
    ins = sp.insights('biz1', 30, now=t0)
    check('insights totals', ins['totals']['facebook']['metrics']['views'] == 321 and ins['totals']['instagram']['posts_with_metrics'] == 1
          and 'reach' not in ins['totals']['facebook']['metrics'])


def test_connect_from_inbox_and_oauth():
    reset()
    import inbox_channels
    DB.inbox_channels.insert_one({'business_id': 'biz1', 'channel': 'messenger', 'status': 'connected', 'external_id': 'PAGE1',
                                  'access_token_enc': vault.encrypt_secret('PAGE-TOKEN'), 'account_name': 'Golden Page'})
    check('inbox stub ok', inbox_channels.get_connection('biz1', 'messenger') is not None)
    HTTP.on('GET', r'/v23\.0/me$', lambda c: {'id': 'PAGE1', 'name': 'Golden Nails', 'category': 'Nail Salon'}
            if c.query.get('access_token') == 'PAGE-TOKEN' else (400, {'error': {'code': 190, 'message': 'bad'}}))
    row = sa.connect_from_inbox('biz1', 'facebook')
    acc = DB.social_accounts.find_one({'platform': 'facebook'})
    check('inbox connect', row['connected'] and row['connected_via'] == 'inbox' and row['account_name'] == 'Golden Nails'
          and vault.decrypt_secret(acc['token_enc']) == 'PAGE-TOKEN' and acc['qa_test'] is True)
    check('no token in public status', 'token_enc' not in json.dumps(sa.public_status('biz1'), default=str))
    try:
        sa.connect_from_inbox('biz1', 'instagram')
        check('ig inbox missing', False)
    except sa.SocialError as e:
        check('ig inbox missing', e.code == 'inbox_not_connected')
    HTTP.on('GET', r'/v23\.0/me$', (400, {'error': {'code': 100, 'message': 'Tried accessing nonexisting field (category) on node type (User)'}}))
    try:
        sa.connect_token('biz1', 'facebook', {'access_token': 'USER-TOKEN'})
        check('user token refused', False)
    except sa.SocialError as e:
        check('user token refused', e.code == 'need_page_token')

    # Google OAuth (YouTube)
    url = sa.oauth_start_url('biz1', 'youtube', 'http://127.0.0.1:5003/social/oauth/youtube/callback', 'st8')
    q = parse_qs(urlsplit(url).query)
    check('google start url', url.startswith('http://gauth.mock/o/oauth2/v2/auth?') and q['access_type'] == ['offline']
          and q['prompt'] == ['consent'] and 'youtube.upload' in q['scope'][0] and q['state'] == ['st8'])
    both = sa.GOOGLE_SCOPES['youtube']
    HTTP.on('POST', r'gauth\.mock/token$', lambda c: {'access_token': 'ya29.A', 'refresh_token': 'rt-1', 'expires_in': 3599, 'scope': both}
            if c.data['grant_type'] == 'authorization_code' else {'access_token': 'ya29.B', 'expires_in': 3599})
    HTTP.on('GET', r'google\.mock/youtube/v3/channels$', {'items': [{'id': 'UC1', 'snippet': {'title': 'Golden TV'}}]})
    row = sa.oauth_finish('biz1', 'youtube', 'code-1', 'http://127.0.0.1:5003/social/oauth/youtube/callback')
    check('youtube connected', row['connected'] and row['external_id'] == 'UC1' and row['connected_via'] == 'oauth')
    acc = sa.get_account('biz1', 'youtube')
    check('fresh token used', sa.access_token(acc) == 'ya29.A')
    DB.social_accounts.update_one({'platform': 'youtube'}, {'$set': {'token_expires_at': now0() - timedelta(minutes=1)}})
    check('expired token refreshed', sa.access_token(sa.get_account('biz1', 'youtube')) == 'ya29.B'
          and HTTP.find('POST', 'gauth.mock/token')[-1].data['refresh_token'] == 'rt-1')
    DB.social_accounts.update_one({'platform': 'youtube'}, {'$set': {'token_expires_at': now0() - timedelta(minutes=1)}})
    HTTP.on('POST', r'gauth\.mock/token$', (400, {'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'}))
    try:
        sa.access_token(sa.get_account('biz1', 'youtube'))
        check('invalid_grant -> reconnect', False)
    except sa.SocialError as e:
        check('invalid_grant -> reconnect', e.reconnect and e.code == 'token_invalid')
    # TikTok chưa có khoá app -> nói thẳng
    key = os.environ.pop('TIKTOK_CLIENT_KEY')
    try:
        try:
            sa.oauth_start_url('biz1', 'tiktok', 'http://x/cb', 's')
            check('tiktok app_not_configured', False)
        except sa.SocialError as e:
            check('tiktok app_not_configured', e.code == 'app_not_configured')
        st = sa.public_status('biz1')['tiktok']
        check('status shows app not configured', st['can_oauth'] is False and st['requirement_codes'][0] == 'app_not_configured')
    finally:
        os.environ['TIKTOK_CLIENT_KEY'] = key
    os.environ['SOCIAL_APPROVED'] = 'tiktok_audit'
    try:
        check('approved requirement hidden', 'tiktok_audit' not in sa.public_status('biz1')['tiktok']['requirement_codes'])
    finally:
        os.environ.pop('SOCIAL_APPROVED')


def test_ai_captions_plan_review():
    reset()
    many = ' '.join(f'#tag{i}' for i in range(12))
    AI['fn'] = lambda s, u: json.dumps({'instagram': 'New season gel ✨ ' + many, 'tiktok': 'x' * 300,
                                        'google_business': 'Book your gel today #nails #gel', 'youtube_title': '<Gel> in 8s',
                                        'youtube': 'desc'})
    caps = pl.captions('biz1', 'Gel special this week', ['instagram', 'tiktok', 'google_business', 'youtube'], 'en')
    check('ig ≤ 8 hashtags', len(re.findall(r'#\w+', caps['instagram'])) == 8)
    check('hashtag trim keeps longer tags intact', pl._fit('instagram', ' '.join(['#nails'] * 8) + ' #nail #nailsalon') == ' '.join(['#nails'] * 8))
    check('tiktok ≤ 150', len(caps['tiktok']) == 150)
    check('gbp no hashtags', '#' not in caps['google_business'])
    check('yt title cleaned', caps['youtube_title'] == 'Gel in 8s')
    # kế hoạch tuần từ dữ liệu thật
    account('biz1', 'facebook', 'PAGE1')
    account('biz1', 'instagram', 'IG1')
    MEDIA['aaaaaaaaaaaaaaaaaaaaaaaa'] = FakeGridOut(b'\xff\xd8\xff' + b'1' * 50, 'image/jpeg', 'product_image', 'biz1')
    DB.products.insert_one({'id': 1, 'business_id': 'biz1', 'name': 'Gel manicure', 'price': 45, 'is_active': 1,
                            'image': '/api/public/storage/file/aaaaaaaaaaaaaaaaaaaaaaaa'})
    DB.products.insert_one({'id': 2, 'business_id': 'biz1', 'name': 'Pedicure', 'price': 55, 'is_active': 1, 'image': ''})
    DB.promotions.insert_one({'id': 7, 'business_id': 'biz1', 'name': 'Spring 10', 'code': 'SPRING10', 'discount_type': 'percentage',
                              'discount_value': '10', 'status': 'active', 'end_date': '2099-01-01', 'usage_limit': 100, 'used_count': 3})
    seen = {}

    def planner_ai(s, u):
        seen['user'] = seen.get('user', '') + u   # các lô chạy song song: gom prompt của mọi lô
        items = json.loads(u.split('ITEMS:\n', 1)[1])
        return json.dumps({'posts': [{'idx': it['idx'], 'caption': f"Post {it['idx']} about {it['type']}",
                                      'instagram': f"IG {it['idx']} #nails", 'hashtags': ['nails', 'gel'],
                                      'image_prompt': 'a calm nail salon table'} for it in items]})
    AI['fn'] = planner_ai
    plan, posts = pl.weekly_plan('biz1', 'u1', '2026-11-02', ['facebook', 'instagram', 'tiktok'], 4, 'en')
    check('plan facts from real data', 'SPRING10' in seen['user'] and '10% off' in seen['user'] and 'Gel manicure' in seen['user']
          and '$45.00' in seen['user'])
    check('plan size + approval', len(posts) == 4 and all(p['status'] == 'pending_approval' and p['created_by'] == 'ai' for p in posts))
    check('tiktok left out of AI plan', plan['skipped_platforms'] == ['tiktok'] and all(
        all(t['platform'] != 'tiktok' for t in p['targets']) for p in posts))
    photo = [p for p in posts if p['media']]
    check('real product photo used', len(photo) == 1 and photo[0]['media'][0]['kind'] == 'product_image'
          and {t['platform'] for t in photo[0]['targets']} == {'facebook', 'instagram'} and photo[0]['image_prompt'] is None)
    check('no-photo posts: facebook only + image idea', all({t['platform'] for t in p['targets']} == {'facebook'} and p['image_prompt']
                                                         for p in posts if not p['media']))
    times = [sa.as_utc(stored(p['id'])['scheduled_at']) for p in posts]
    check('distinct future slots', len(set(times)) == 4 and all(t > now0() for t in times))
    check('plan stored', DB.social_plans.find_one({'id': plan['id']})['post_ids'] == [p['id'] for p in posts])
    # duyệt -> lên lịch; nhận xét hiệu quả chưa đủ dữ liệu thì KHÔNG gọi AI
    ok = sp.approve('biz1', posts[0]['id'], 'owner')
    check('approve -> scheduled', ok['status'] == 'scheduled' and ok['approved_by'] == 'owner')
    AI['fn'], AI['calls'] = None, 0
    rv = pl.performance_review('biz1', 'vi')
    check('review not enough data, no AI', rv['enough_data'] is False and AI['calls'] == 0 and 'Chưa đủ dữ liệu' in rv['text'])


def test_skip_rules_partial_and_stale():
    reset()
    account('biz1', 'facebook', 'PAGE1')
    account('biz1', 'instagram', 'IG1')
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_3'})
    p = post(caption='Text only', targets=['facebook', 'instagram'])
    check('ig text warning', [w['code'] for w in p['warnings']] == ['ig_needs_media'])
    sp.run_due('biz1', now=now0())
    check('partial when one skipped', stored(p['id'])['status'] == 'partial' and target(p['id'], 'instagram')['status'] == 'skipped')
    media('png1', 'image/png')
    p2 = post(caption='PNG', media_file_ids=['png1'], targets=['instagram'], status='draft')
    check('png warning', p2['warnings'][0]['code'] == 'ig_needs_jpeg')
    MEDIA['priv'] = FakeGridOut(b'x', 'image/jpeg', 'avatar', 'biz1')
    try:
        post(caption='x', media_file_ids=['priv'], targets=['facebook'])
        check('private media refused', False)
    except sa.SocialError as e:
        check('private media refused', e.code == 'media_not_shareable')
    try:
        post(caption='x', media_file_ids=['png1', 'png1x'], targets=['facebook'])
        check('one media only', False)
    except sa.SocialError as e:
        check('one media only', e.code == 'single_media_only')
    # trễ > 24 giờ (cron hỏng) -> không đăng nữa, báo rõ
    t0 = now0()
    old = post(caption='Old', targets=['facebook'], status='draft')
    DB.social_posts.update_one({'id': old['id']}, {'$set': {'status': 'scheduled', 'scheduled_at': t0 - timedelta(hours=30)}})
    HTTP.calls.clear()
    sp.run_due('biz1', now=t0)
    check('stale -> missed_time', target(old['id'], 'facebook')['error']['code'] == 'missed_time' and not HTTP.calls)
    # đăng lại ngay (publish_now) sau lỗi -> chạy lại đích lỗi
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_4'})
    got, stats = sp.publish_now('biz1', old['id'], 'u1')
    check('publish_now retries failed target', got['status'] == 'published' and stats['published'] == 1)
    try:
        sp.update_post('biz1', old['id'], {'caption': 'edit'}, 'u1')
        check('published not editable', False)
    except sa.SocialError as e:
        check('published not editable', e.code == 'not_editable')
    try:
        post(caption='x', targets=['facebook'], scheduled_at='2026-11-02T09:00:00')
        check('naive time refused', False)
    except sa.SocialError as e:
        check('naive time refused', e.code == 'bad_time')


def test_routes():
    reset()
    import flask
    import social_bp
    app = flask.Flask('t')
    app.secret_key = 'x'
    app.register_blueprint(social_bp.social_bp)
    c = app.test_client()
    check('cron no auth 401', c.post('/api/cron/social_tick').status_code == 401)
    check('cron wrong secret 401', c.get('/api/cron/social_tick', headers={'Authorization': 'Bearer nope'}).status_code == 401)
    check('cron non-ascii header safe', c.get('/api/cron/social_tick', headers={'Authorization': 'Bearer ñ'}).status_code == 401)
    r = c.get('/api/cron/social_tick', headers={'Authorization': 'Bearer cron-s3cret'})
    check('cron off production skipped', r.status_code == 200 and r.get_json()['skipped'] == 'not_production')
    os.environ['SOCIAL_ALLOW_TICK'] = '1'
    try:
        r = c.post('/api/cron/social_tick', headers={'Authorization': 'Bearer cron-s3cret'})
        check('cron runs when allowed', r.status_code == 200 and r.get_json()['claimed'] == 0 and r.get_json()['test_mode'] is True)
    finally:
        os.environ.pop('SOCIAL_ALLOW_TICK')
    check('api needs login', c.get('/api/social/accounts').status_code == 401)
    account('biz1', 'facebook', 'PAGE1')
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_r'})
    with c.session_transaction() as s:
        s['user_id'], s['business_id'], s['role'] = 'staff1', 'biz1', 'staff'
    r = c.post('/api/social/posts', json={'caption': 'Staff idea', 'targets': [{'platform': 'facebook'}], 'status': 'scheduled'})
    j = r.get_json()
    check('staff schedule -> pending_approval', r.status_code == 200 and j['post']['status'] == 'pending_approval', j)
    pid = j['post']['id']
    check('staff cannot approve', c.post(f'/api/social/posts/{pid}/approve').status_code == 403)
    check('staff cannot connect accounts', c.post('/api/social/accounts/facebook', json={'action': 'disconnect'}).status_code == 403)
    with c.session_transaction() as s:
        s['user_id'], s['role'] = 'owner1', 'admin'
    r = c.post(f'/api/social/posts/{pid}/approve')
    check('admin approves', r.status_code == 200 and r.get_json()['post']['status'] == 'scheduled')
    r = c.get('/api/social/posts?status=scheduled')
    check('list posts', r.status_code == 200 and [p['id'] for p in r.get_json()['data']] == [pid])
    r = c.get('/api/social/posts?from=2026-01-01T00:00:00')
    check('naive from rejected', r.status_code == 400 and r.get_json()['code'] == 'bad_time')
    r = c.post('/api/social/posts', json={'caption': 'x', 'targets': ['myspace']})
    check('bad platform code', r.status_code == 400 and r.get_json()['code'] == 'bad_platform')
    check('unknown account platform 404', c.post('/api/social/accounts/myspace', json={'action': 'disconnect'}).status_code == 404)
    r = c.get('/api/social/accounts')
    check('accounts api', r.status_code == 200 and r.get_json()['data']['facebook']['connected'] is True)
    r = c.get('/api/social/best_times?platform=instagram')
    check('best_times api', r.status_code == 200 and r.get_json()['source'] == 'default')
    r = c.get('/social/oauth/tiktok/start')
    check('oauth start redirects to provider', r.status_code == 302 and r.headers['Location'].startswith('http://tiktok.mock/v2/auth/authorize/'))
    r = c.get('/social/oauth/tiktok/callback?code=abc&state=WRONG')
    check('oauth state mismatch', r.status_code == 302 and 'error=oauth_state' in r.headers['Location'])
    r = c.get('/social/oauth/tiktok/callback?code=abc&state=x')
    check('oauth state single-use', 'error=oauth_state' in r.headers['Location'])
    r = c.post('/api/social/pump')
    check('pump ok', r.status_code == 200 and r.get_json()['success'])
    check('pump throttled', c.post('/api/social/pump').get_json().get('skipped') is True)


# ================================================================ hồi quy các lỗi review (2026-10-25)
def _iso(dt):
    return dt.isoformat().replace('+00:00', 'Z')


def _expect(name, fn, code, platform=None):
    try:
        fn()
        check(name, False, f'expected {code}')
    except sa.SocialError as e:
        check(name, e.code == code and (platform is None or e.platform == platform), f'{e.code}/{e.platform}: {e}')


def _app():
    import flask
    import social_bp
    app = flask.Flask('t')
    app.secret_key = 'x'
    app.register_blueprint(social_bp.social_bp)
    return app.test_client()


def _login(c, uid, role):
    with c.session_transaction() as s:
        s['user_id'], s['business_id'], s['role'] = uid, 'biz1', role


def test_sec2_staff_cannot_keep_or_set_schedule():
    """SEC-2: nhân viên gửi status null / '' / không phải chuỗi không được giữ bài 'scheduled' đã duyệt để đăng nội dung mới."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_x'})
    c = _app()
    when = _iso(now0() + timedelta(hours=3))
    _login(c, 'owner1', 'admin')
    j = c.post('/api/social/posts', json={'caption': 'Owner text', 'targets': [{'platform': 'facebook'}], 'status': 'scheduled',
                                          'scheduled_at': when}).get_json()
    pid = j['post']['id']
    check('owner scheduled', j['post']['status'] == 'scheduled' and j['post']['approved_by'] == 'owner1')
    _login(c, 'staff1', 'staff')
    for bad in (None, ''):
        DB.social_posts.update_one({'id': pid}, {'$set': {'status': 'scheduled', 'approved_by': 'owner1'}})
        r = c.put(f'/api/social/posts/{pid}', json={'caption': f'Staff text {bad!r}', 'status': bad})
        doc = stored(pid)
        check(f'staff status={bad!r} -> pending_approval', r.status_code == 200 and doc['status'] == 'pending_approval'
              and doc['approved_by'] is None, (r.get_json(), doc['status'], doc['approved_by']))
    r = c.put(f'/api/social/posts/{pid}', json={'caption': 'x', 'status': ['scheduled']})
    check('staff non-string status -> 400 bad_status', r.status_code == 400 and r.get_json()['code'] == 'bad_status')
    r = c.put(f'/api/social/posts/{pid}', json={'caption': 'x', 'status': 'scheduled'})
    check('staff asks scheduled -> pending_approval', stored(pid)['status'] == 'pending_approval')
    check('nothing published without approval', sp.run_due('biz1', now=now0() + timedelta(hours=4))['claimed'] == 0
          and not HTTP.find('POST', '/PAGE1/feed'))
    # chặn cả ở tầng engine (gọi thẳng update_post / create_post với is_admin=False)
    DB.social_posts.update_one({'id': pid}, {'$set': {'status': 'scheduled'}})
    out = sp.update_post('biz1', pid, {'caption': 'direct', 'status': None}, 'staff1', is_admin=False)
    check('engine: staff edit of scheduled -> pending', out['status'] == 'pending_approval')
    p2 = sp.create_post('biz1', 'staff1', {'caption': 'c', 'targets': ['facebook'], 'status': 'scheduled'}, is_admin=False)
    check('engine: staff create scheduled -> pending', p2['status'] == 'pending_approval' and p2['approved_by'] is None)


def _gbp_oauth_routes(locations):
    HTTP.on('POST', r'gauth\.mock/token$', {'access_token': 'ya29.G', 'refresh_token': 'rt-g', 'expires_in': 3599,
                                            'scope': sa.GOOGLE_SCOPES['google_business']})
    HTTP.on('GET', r'gbp\.mock/v1/accounts$', {'accounts': [{'name': 'accounts/1'}]})
    HTTP.on('GET', r'gbp\.mock/v1/accounts/1/locations$', {'locations': locations})


def test_sec3_gbp_multi_location_needs_choice():
    """SEC-3: nhiều địa điểm Google -> 'needs_location' (không tự lấy cái đầu), không đăng được tới khi chủ tiệm chọn."""
    reset()
    _gbp_oauth_routes([{'name': 'locations/2', 'title': 'Shop A'}, {'name': 'locations/3', 'title': 'Shop B'}])
    row = sa.oauth_finish('biz1', 'google_business', 'code-1', 'http://x/cb')
    check('needs_location, not connected', row['status'] == 'needs_location' and row['connected'] is False
          and row['needs_location'] is True and row['external_id'] == '' and len(row['location_choices']) == 2, row)
    check('is_connected refuses', not sa.is_connected('biz1', 'google_business'))
    _expect('schedule refused until a location is picked', lambda: post(caption='x', targets=['google_business']),
            'needs_location', 'google_business')
    _expect('unknown location refused', lambda: sa.connect_token('biz1', 'google_business', {'location': 'accounts/9/locations/9'}),
            'bad_location')
    c = _app()
    _login(c, 'owner1', 'admin')
    r = c.post('/api/social/accounts/google_business', json={'action': 'connect_token', 'fields': {'location': 'accounts/1/locations/3'}})
    row = r.get_json()['data']
    check('picked Shop B -> connected', r.status_code == 200 and row['connected'] and row['external_id'] == 'accounts/1/locations/3'
          and row['account_name'] == 'Shop B' and row['needs_location'] is False, row)
    HTTP.on('POST', r'gbp\.mock/v4/accounts/1/locations/3/localPosts$', {'name': 'accounts/1/locations/3/localPosts/L1', 'state': 'LIVE'})
    p = post(caption='Shop B news', targets=['google_business'])
    sp.run_due('biz1', now=now0())
    check('posted to the chosen location only', target(p['id'], 'google_business')['status'] == 'published'
          and not HTTP.find('POST', 'locations/2/localPosts'))
    row = sa.oauth_finish('biz1', 'google_business', 'code-2', 'http://x/cb')
    check('re-login keeps the chosen location', row['connected'] and row['external_id'] == 'accounts/1/locations/3')
    # 1 địa điểm -> nối luôn (như trước)
    reset()
    _gbp_oauth_routes([{'name': 'locations/5', 'title': 'Only shop'}])
    row = sa.oauth_finish('biz1', 'google_business', 'code-3', 'http://x/cb')
    check('single location connects directly', row['connected'] and row['external_id'] == 'accounts/1/locations/5')
    # tài khoản nối bằng bản cũ (tự lấy địa điểm đầu trong nhiều địa điểm, chưa ai xác nhận) -> coi như chưa chọn
    reset()
    choices = [{'id': 'accounts/1/locations/2', 'name': 'Shop A'}, {'id': 'accounts/1/locations/3', 'name': 'Shop B'}]
    account('biz1', 'google_business', 'accounts/1/locations/2', 'ya29', connected_via='oauth',
            token_expires_at=now0() + timedelta(hours=1), location_choices=choices)
    st = sa.public_status('biz1')['google_business']
    check('legacy auto-pick shown as needs_location', st['status'] == 'needs_location' and st['connected'] is False and st['needs_location'])
    _expect('legacy auto-pick cannot post', lambda: post(caption='x', targets=['google_business']), 'needs_location')
    _gbp_oauth_routes([{'name': 'locations/2', 'title': 'Shop A'}, {'name': 'locations/3', 'title': 'Shop B'}])
    row = sa.oauth_finish('biz1', 'google_business', 'code-4', 'http://x/cb')
    check('re-login does not keep an unconfirmed pick', row['status'] == 'needs_location')
    row = sa.connect_token('biz1', 'google_business', {'location': 'accounts/1/locations/2'})
    check('owner confirms Shop A -> connected', row['connected'] and row['external_id'] == 'accounts/1/locations/2')


def _yt_routes(vid_id='VIDP'):
    seen = []

    def init(c):
        seen.append(c.json['status'])
        return FakeResp(200, {}, {'Location': 'http://google.mock/upload/session/p'})
    HTTP.on('POST', r'google\.mock/upload/youtube/v3/videos$', init)
    HTTP.on('PUT', r'google\.mock/upload/session/p$', {'id': vid_id, 'status': {'privacyStatus': 'private'}})
    return seen


def test_soc1_prepush_only_inside_own_window():
    """SOC-1 / F1: bài nhận vì khung của YouTube không được đăng NGAY lên Facebook (và ngược lại)."""
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    account('biz1', 'youtube', 'UC1', 'ya29', connected_via='oauth', token_expires_at=now0() + timedelta(hours=2))
    media('vidP', 'video/mp4', kind='ai_video', data=mp4(8))
    HTTP.on('POST', r'/PAGE1/videos$', lambda c: {'id': 'VD1'})
    yt = _yt_routes()
    t0 = now0()
    far = post(caption='Far', title='Far', media_file_ids=['vidP'], targets=['facebook', 'youtube'],
               scheduled_at=_iso(t0 + timedelta(days=40)))
    sp.run_due('biz1', now=t0)
    check('40 days: YouTube pre-pushed natively', target(far['id'], 'youtube')['status'] == 'scheduled_remote'
          and yt and yt[0]['privacyStatus'] == 'private' and 'publishAt' in yt[0])
    check('40 days: Facebook NOT posted early', target(far['id'], 'facebook')['status'] == 'pending'
          and not HTTP.find('POST', '/PAGE1/videos') and stored(far['id'])['status'] == 'scheduled')
    HTTP.calls.clear()
    near = post(caption='Near', title='Near', media_file_ids=['vidP'], targets=['facebook', 'youtube'],
                scheduled_at=_iso(t0 + timedelta(minutes=13)))
    sp.run_due('biz1', now=t0)
    fbcall = HTTP.find('POST', '/PAGE1/videos')
    check('13 min: Facebook pre-pushed with published=false', target(near['id'], 'facebook')['status'] == 'scheduled_remote'
          and len(fbcall) == 1 and fbcall[0].data.get('published') == 'false')
    check('13 min: YouTube NOT uploaded early', target(near['id'], 'youtube')['status'] == 'pending'
          and not HTTP.find('POST', 'upload/youtube'))
    # tới giờ: YouTube tải lên bình thường (công khai, không publishAt)
    yt.clear()
    sp.run_due('biz1', now=t0 + timedelta(minutes=13, seconds=5))
    check('due: YouTube uploaded at its time', target(near['id'], 'youtube')['status'] == 'published'
          and yt and yt[0]['privacyStatus'] == 'public' and 'publishAt' not in yt[0])


def test_soc12_youtube_unlisted_never_native_and_no_starvation():
    """SOC-12: chủ tiệm chọn 'unlisted' -> không dùng publishAt (sẽ thành công khai); bài đó không chặn đẩy trước bài khác."""
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    account('biz1', 'youtube', 'UC1', 'ya29', connected_via='oauth', token_expires_at=now0() + timedelta(days=3))
    media('vidU', 'video/mp4', kind='promo_video', data=mp4(6))
    yt = _yt_routes('VIDU')
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_9'})
    t0 = now0()
    u = post(caption='Unlisted', title='Unlisted', media_file_ids=['vidU'], scheduled_at=_iso(t0 + timedelta(days=1)),
             targets=[{'platform': 'youtube', 'options': {'privacy_status': 'unlisted'}}])
    f = post(caption='FB later', targets=['facebook'], scheduled_at=_iso(t0 + timedelta(days=2)))
    sp.run_due('biz1', now=t0)
    check('unlisted video not pre-pushed', target(u['id'], 'youtube')['status'] == 'pending' and not yt)
    check('other post still pre-pushed (no starvation)', target(f['id'], 'facebook')['status'] == 'scheduled_remote')
    sp.run_due('biz1', now=t0 + timedelta(days=1, seconds=5))
    check('due: uploaded as unlisted without publishAt', target(u['id'], 'youtube')['status'] == 'published'
          and yt[0]['privacyStatus'] == 'unlisted' and 'publishAt' not in yt[0], yt)


def _fb_prepushed(caption='Sched', hours=2, pid='PAGE1_5'):
    HTTP.on('POST', r'/PAGE1/feed$', {'id': pid})
    p = post(caption=caption, targets=['facebook'], scheduled_at=_iso(now0() + timedelta(hours=hours)))
    sp.run_due('biz1', now=now0())
    check('fixture pre-pushed', target(p['id'], 'facebook')['status'] == 'scheduled_remote')
    return p


def test_soc2_cancel_delete_keep_remote_id_on_failure():
    """SOC-2: gỡ lịch trên Meta lỗi -> KHÔNG báo đã huỷ, giữ remote_id; force mới huỷ (vẫn giữ remote_id + cảnh báo)."""
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    p = _fb_prepushed()
    HTTP.on('DELETE', r'/v23\.0/PAGE1_5$', (500, {'error': {'message': 'boom', 'code': 2, 'is_transient': True}}))
    _expect('cancel refused when Meta delete fails', lambda: sp.cancel('biz1', p['id']), 'remote_cancel_failed', 'facebook')
    t = target(p['id'], 'facebook')
    check('still scheduled with remote id kept', stored(p['id'])['status'] == 'scheduled' and t['status'] == 'scheduled_remote'
          and t['remote_id'] == 'PAGE1_5' and stored(p['id'])['lease_owner'] is None)
    _expect('delete refused too', lambda: sp.delete('biz1', p['id']), 'remote_cancel_failed')
    check('doc still there', stored(p['id']) is not None)
    HTTP.on('DELETE', r'/v23\.0/PAGE1_5$', (400, {'error': {'message': 'Session has expired', 'code': 190}}))
    _expect('token error -> refused', lambda: sp.cancel('biz1', p['id']), 'remote_cancel_failed')
    check('account marked needs_reconnect', DB.social_accounts.find_one({'platform': 'facebook'})['status'] == 'needs_reconnect')
    c = _app()
    _login(c, 'owner1', 'admin')
    r = c.post(f"/api/social/posts/{p['id']}/cancel", json={})
    check('route: 409 remote_cancel_failed', r.status_code == 409 and r.get_json()['code'] == 'remote_cancel_failed')
    r = c.post(f"/api/social/posts/{p['id']}/cancel", json={'force': True})
    j = r.get_json()
    t = target(p['id'], 'facebook')
    check('force: canceled, remote id kept, warning returned', r.status_code == 200 and j['post']['status'] == 'canceled'
          and t['status'] == 'scheduled_remote' and t['remote_id'] == 'PAGE1_5'
          and [w['code'] for w in j['warnings']] == ['remote_cancel_failed'], j)
    # gỡ được -> huỷ bình thường, đích làm lại từ đầu
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    p = _fb_prepushed(pid='PAGE1_6')
    HTTP.on('DELETE', r'/v23\.0/PAGE1_6$', {'success': True})
    out = sp.cancel('biz1', p['id'])
    check('cancel ok -> remote removed', out['status'] == 'canceled' and target(p['id'], 'facebook')['remote_id'] is None
          and out['warnings'] == [])


def test_soc4_no_delete_before_validation_or_after_live():
    """SOC-4: sửa bị từ chối (giờ đã qua) thì KHÔNG xoá bài hẹn trên Meta; bài đã tới giờ (đã lên) không bị xoá khi sửa /
    đăng ngay / huỷ; gỡ được 1 nền tảng rồi nền tảng sau lỗi thì phần đã gỡ vẫn được ghi lại."""
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    p = _fb_prepushed()
    HTTP.on('DELETE', r'/v23\.0/PAGE1_5$', {'success': True})
    _expect('edit with past time refused', lambda: sp.update_post('biz1', p['id'], {'scheduled_at': _iso(now0() - timedelta(hours=1))}, 'u1'),
            'time_in_past')
    check('no DELETE before validation passed', not HTTP.find('DELETE', 'PAGE1_5')
          and target(p['id'], 'facebook')['status'] == 'scheduled_remote')
    # Meta đã đăng lúc tới giờ, BitPaw chưa kịp kiểm tra
    DB.social_posts.update_one({'id': p['id']}, {'$set': {'scheduled_at': now0() - timedelta(minutes=2)}})
    _expect('edit of live post refused', lambda: sp.update_post('biz1', p['id'], {'caption': 'new'}, 'u1'), 'already_live', 'facebook')
    _expect('publish_now of live post refused', lambda: sp.publish_now('biz1', p['id'], 'u1'), 'already_live')
    _expect('cancel of live post refused', lambda: sp.cancel('biz1', p['id']), 'already_live')
    check('live post never deleted', not HTTP.find('DELETE', 'PAGE1_5') and not HTTP.find('POST', '/PAGE1/feed')[1:])
    w = sp.delete('biz1', p['id'])
    check('BitPaw-only delete leaves it on Facebook', stored(p['id']) is None and [x['code'] for x in w] == ['already_live']
          and not HTTP.find('DELETE', 'PAGE1_5'))
    # gỡ Facebook xong, YouTube lỗi -> Facebook đã gỡ được ghi lại, YouTube giữ remote_id
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    account('biz1', 'youtube', 'UC1', 'ya29', connected_via='oauth', token_expires_at=now0() + timedelta(hours=5))
    media('vidQ', 'video/mp4', kind='ai_video', data=mp4(5))
    HTTP.on('POST', r'/PAGE1/videos$', {'id': 'VD9'})
    _yt_routes('VIDQ')
    q = post(caption='Both', title='Both', media_file_ids=['vidQ'], targets=['facebook', 'youtube'],
             scheduled_at=_iso(now0() + timedelta(hours=2)))
    sp.run_due('biz1', now=now0())
    check('both pre-pushed', target(q['id'], 'facebook')['status'] == 'scheduled_remote' and target(q['id'], 'youtube')['status'] == 'scheduled_remote')
    HTTP.on('DELETE', r'/v23\.0/VD9$', {'success': True})
    HTTP.on('DELETE', r'google\.mock/youtube/v3/videos$', (503, {'error': {'message': 'backend', 'errors': [{'reason': 'backendError'}]}}))
    _expect('edit stops when YouTube cannot be unscheduled', lambda: sp.update_post('biz1', q['id'], {'caption': 'edit'}, 'u1'),
            'remote_cancel_failed', 'youtube')
    check('facebook removal persisted, youtube kept', target(q['id'], 'facebook')['status'] == 'pending'
          and target(q['id'], 'facebook')['remote_id'] is None and target(q['id'], 'youtube')['remote_id'] == 'VIDQ'
          and stored(q['id'])['caption'] == 'Both' and stored(q['id'])['lease_owner'] is None)


def test_soc10_stale_read_cannot_overwrite_prepush():
    """SOC-10: đọc bài -> bộ đăng đẩy lên Meta xen giữa -> huỷ/sửa dựa trên bản cũ bị từ chối ('busy'), lịch Meta không mất."""
    reset()
    account('biz1', 'facebook', 'PAGE1', 'fb')
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_7'})
    p = post(caption='Race', targets=['facebook'], scheduled_at=_iso(now0() + timedelta(hours=2)))
    stale = sp.get_post('biz1', p['id'])
    sp.run_due('biz1', now=now0())   # đẩy trước lên Meta SAU khi màn hình đã đọc bài
    orig, calls = sp._get, {'n': 0}

    def stale_get(bid, pid):
        calls['n'] += 1
        return copy.deepcopy(stale) if calls['n'] == 1 else orig(bid, pid)
    sp._get = stale_get
    try:
        _expect('cancel on stale copy -> busy', lambda: sp.cancel('biz1', p['id']), 'busy')
    finally:
        sp._get = orig
    t = target(p['id'], 'facebook')
    check('Meta schedule kept', stored(p['id'])['status'] == 'scheduled' and t['status'] == 'scheduled_remote'
          and t['remote_id'] == 'PAGE1_7' and stored(p['id'])['lease_owner'] is None)
    # đang khoá để sửa -> bộ đăng không nhận bài; trả khoá -> nhận lại được
    p2 = post(caption='Locked', targets=['facebook'], scheduled_at=_iso(now0() + timedelta(hours=2)))
    scope = sp._scope('biz1', None)
    me = sp._lock(sp.get_post('biz1', p2['id']), sa.utcnow())
    check('runner cannot claim while edit lock held', sp._claim(scope, now0(), 'w', 'prepush') is None)
    sp._unlock(stored(p2['id']), me)
    got = sp._claim(scope, now0(), 'w', 'prepush')
    check('claimable again after unlock', got is not None and got['id'] == p2['id'])


def test_soc3_big_photos_refused_for_url_fetch():
    """SOC-3: ảnh lớn hơn media_store.FULL_MAX bị từ chối khi lên lịch cho Instagram / Google (tải qua link = ảnh cụt)."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    account('biz1', 'instagram', 'IG1')
    account('biz1', 'google_business', 'accounts/1/locations/2', 'ya29', connected_via='oauth',
            token_expires_at=now0() + timedelta(hours=1))
    media('big', 'image/jpeg', length=3_500_000)
    for p in ('instagram', 'google_business'):
        _expect(f'{p}: big photo refused at schedule', lambda p=p: post(caption='x', media_file_ids=['big'], targets=['facebook', p]),
                'media_too_large', p)
    d = post(caption='x', media_file_ids=['big'], targets=['facebook', 'instagram'], status='draft')
    w = {x['platform']: x for x in d['warnings']}
    check('draft shows blocking warning', w['instagram']['code'] == 'media_too_large' and w['instagram']['blocking'] is True
          and 'MB' in w['instagram']['message'])
    check('nothing sent anywhere', not [c for c in HTTP.calls if c.method == 'POST'])
    ok = post(caption='fine', media_file_ids=['big'], targets=['facebook'])
    check('facebook alone still fine (uploads bytes)', ok['status'] == 'scheduled')
    # bài cũ (lên lịch trước bản sửa) -> adapter vẫn chặn, không gửi ảnh cụt
    DB.social_posts.update_one({'id': ok['id']}, {'$set': {'targets': [sp._fresh_target('instagram', {})]}})
    sp.run_due('biz1', now=now0())
    check('adapter fails honestly, no IG call', target(ok['id'], 'instagram')['error']['code'] == 'media_too_large'
          and not HTTP.find('POST', '/IG1/media'))
    media('small', 'image/jpeg', length=3_000_000)
    check('photo under the limit accepted', post(caption='s', media_file_ids=['small'], targets=['instagram'])['status'] == 'scheduled')


def test_soc8_facebook_photo_limits():
    """SOC-8: WebP / > 4 MB bị báo trước + bỏ qua (không 'rejected' lúc đăng); PNG > 1 MB chỉ là lưu ý."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    HTTP.on('POST', r'/PAGE1/photos$', {'id': 'PH', 'post_id': 'PAGE1_p'})
    media('webp', 'image/webp')
    p = post(caption='w', media_file_ids=['webp'], targets=['facebook'])
    check('webp warned', [(x['code'], x['skip']) for x in p['warnings']] == [('fb_photo_format', True)])
    media('huge', 'image/jpeg', length=5_000_000)
    p2 = post(caption='h', media_file_ids=['huge'], targets=['facebook'])
    check('>4MB warned', p2['warnings'][0]['code'] == 'fb_photo_too_large')
    media('png', 'image/png', length=1_500_000)
    p3 = post(caption='p', media_file_ids=['png'], targets=['facebook'])
    check('big PNG is only a note', [(x['code'], x['skip'], x['blocking']) for x in p3['warnings']] == [('fb_png_large', False, False)])
    sp.run_due('biz1', now=now0())
    check('webp + huge skipped without calling Facebook', target(p['id'], 'facebook')['status'] == 'skipped'
          and target(p2['id'], 'facebook')['status'] == 'skipped' and len(HTTP.find('POST', '/PAGE1/photos')) == 1)
    check('big PNG still posted', target(p3['id'], 'facebook')['status'] == 'published')


def test_f6_ambiguous_create_never_reposted():
    """F6: mất phản hồi SAU khi gửi lệnh tạo bài -> 'publish_uncertain' (không tự gửi lại); 'sending' còn sót -> không gửi lại."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    seen = {}

    def feed_timeout(c):
        seen['status_during_call'] = target(c_pid['id'], 'facebook')['status']
        raise requests.exceptions.ReadTimeout('read timed out')
    HTTP.on('POST', r'/PAGE1/feed$', feed_timeout)
    c_pid = {}
    p = post(caption='Maybe', targets=['facebook'])
    c_pid['id'] = p['id']
    t0 = now0()
    sp.run_due('biz1', now=t0)
    t = target(p['id'], 'facebook')
    check("'sending' written before the create call", seen.get('status_during_call') == 'sending')
    check('read timeout -> failed publish_uncertain', t['status'] == 'failed' and t['error']['code'] == 'publish_uncertain')
    sp.run_due('biz1', now=t0 + timedelta(hours=1))
    check('never re-posted automatically', len(HTTP.find('POST', '/PAGE1/feed')) == 1)
    # chủ tiệm kiểm tra rồi bấm Đăng ngay -> gửi lại có chủ đích
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_ok'})
    got, _ = sp.publish_now('biz1', p['id'], 'u1')
    check('owner can resend on purpose', got['status'] == 'published')
    # lỗi CHƯA kết nối được (connect timeout) vẫn là lỗi tạm -> thử lại
    reset()
    account('biz1', 'facebook', 'PAGE1')

    def connect_fail(c):
        raise requests.exceptions.ConnectTimeout('connect timed out')
    HTTP.on('POST', r'/PAGE1/feed$', connect_fail)
    p = post(caption='Retry', targets=['facebook'])
    sp.run_due('biz1', now=now0())
    t = target(p['id'], 'facebook')
    check('connect timeout -> transient retry', t['status'] == 'pending' and t['attempts'] == 1 and t['error']['code'] == 'unreachable')
    # máy chết giữa lệnh tạo bài: đích còn 'sending', hết hạn thuê -> máy sau KHÔNG gửi lại
    reset()
    account('biz1', 'facebook', 'PAGE1')
    p = post(caption='Crashed', targets=['facebook'])
    DB.social_posts.update_one({'id': p['id']}, {'$set': {'status': 'publishing', 'targets.0.status': 'sending',
                                                         'lease_owner': 'dead', 'lease_until': now0() - timedelta(minutes=1)}})
    HTTP.calls.clear()
    sp.run_due('biz1', now=now0())
    t = target(p['id'], 'facebook')
    check('stale sending -> publish_uncertain, no call', t['status'] == 'failed' and t['error']['code'] == 'publish_uncertain'
          and not HTTP.calls and stored(p['id'])['status'] == 'failed')
    # đẩy trước lên Meta bị chết giữa chừng (bài vẫn 'scheduled'): Đăng ngay lần 1 = cảnh báo + ghi nhận, lần 2 = gửi có chủ đích
    reset()
    account('biz1', 'facebook', 'PAGE1')
    p = post(caption='Prepush crashed', targets=['facebook'], scheduled_at=_iso(now0() + timedelta(days=2)))
    DB.social_posts.update_one({'id': p['id']}, {'$set': {'targets.0.status': 'sending'}})
    _expect('first publish_now warns instead of re-sending', lambda: sp.publish_now('biz1', p['id'], 'u1'), 'publish_uncertain', 'facebook')
    check('target recorded as uncertain, nothing sent', target(p['id'], 'facebook')['status'] == 'failed'
          and not HTTP.calls and stored(p['id'])['lease_owner'] is None)
    HTTP.on('POST', r'/PAGE1/feed$', {'id': 'PAGE1_again'})
    got, _ = sp.publish_now('biz1', p['id'], 'u1')
    check('second press sends on purpose', got['status'] == 'published' and len(HTTP.find('POST', '/PAGE1/feed')) == 1)


def test_soc6_instagram_photo_not_posted_twice():
    """SOC-6: media_publish mất phản hồi -> giữ container, lần sau hỏi trạng thái (PUBLISHED) thay vì đăng ảnh lần 2."""
    reset()
    account('biz1', 'instagram', 'IG1', 'ig')
    media('jp', 'image/jpeg')
    HTTP.on('POST', r'/IG1/media$', {'id': 'C7'})
    HTTP.on('GET', r'/IG1/content_publishing_limit$', {'data': [{'quota_usage': 1, 'config': {'quota_total': 50}}]})
    seen = {}

    def publish_timeout(c):
        t = target(pid['id'], 'instagram')
        seen['saved'] = (t['status'], t['container_id'])
        raise requests.exceptions.ReadTimeout('read timed out')
    HTTP.on('POST', r'/IG1/media_publish$', publish_timeout)
    pid = {}
    p = post(caption='Photo', media_file_ids=['jp'], targets=['instagram'])
    pid['id'] = p['id']
    t0 = now0()
    sp.run_due('biz1', now=t0)
    t = target(p['id'], 'instagram')
    check('container saved before media_publish', seen.get('saved') == ('processing', 'C7'))
    check('kept as processing with the same container', t['status'] == 'processing' and t['container_id'] == 'C7' and t['attempts'] == 1)
    HTTP.on('GET', r'/v23\.0/C7$', {'status_code': 'PUBLISHED'})
    sp.run_due('biz1', now=t0 + timedelta(minutes=3))
    check('detected as already published', target(p['id'], 'instagram')['status'] == 'published')
    check('one container, one media_publish', len(HTTP.find('POST', '/IG1/media')) - len(HTTP.find('POST', 'media_publish')) == 1
          and len(HTTP.find('POST', 'media_publish')) == 1)


def test_soc7_tiktok_post_id_after_moderation():
    """SOC-7: TikTok xong nhưng chưa có id (đang kiểm duyệt) -> hỏi lại sau, rồi lấy link + số liệu thật."""
    reset()
    account('biz1', 'tiktok', 'OPEN1', 'act', connected_via='oauth', token_expires_at=now0() + timedelta(days=3))
    media('tv', 'video/mp4', kind='promo_video', data=mp4(10))
    HTTP.on('POST', r'/v2/post/publish/creator_info/query/$', {'data': {'privacy_level_options': ['PUBLIC_TO_EVERYONE', 'SELF_ONLY'],
                                                                         'max_video_post_duration_sec': 60, 'creator_username': 'gn'},
                                                                'error': {'code': 'ok'}})
    HTTP.on('POST', r'/v2/post/publish/video/init/$', {'data': {'publish_id': 'pub9', 'upload_url': 'http://tiktok-upload.mock/u/9'},
                                                       'error': {'code': 'ok'}})
    HTTP.on('PUT', r'tiktok-upload\.mock/u/9$', FakeResp(201, {}))
    status = {'ids': []}
    HTTP.on('POST', r'/v2/post/publish/status/fetch/$', lambda c: {'data': {'status': 'PUBLISH_COMPLETE',
                                                                             'publicaly_available_post_id': status['ids']},
                                                                    'error': {'code': 'ok'}})
    HTTP.on('POST', r'/v2/video/query/$', {'data': {'videos': [{'id': '7311', 'view_count': 90, 'like_count': 9}]}, 'error': {'code': 'ok'}})
    opts = {'privacy_level': 'PUBLIC_TO_EVERYONE', 'disable_comment': False, 'disable_duet': False, 'disable_stitch': False,
            'brand_content_toggle': False, 'brand_organic_toggle': False}
    p = post(caption='Public clip', media_file_ids=['tv'], targets=[{'platform': 'tiktok', 'options': opts}])
    t0 = now0()
    sp.run_due('biz1', now=t0)
    sp.run_due('biz1', now=t0 + timedelta(minutes=1))
    t = target(p['id'], 'tiktok')
    check('published, waiting for post id', t['status'] == 'published' and not t.get('remote_id') and t.get('needs_post_id') is True)
    check('still in moderation -> ask again later', sp.sync_metrics('biz1', now=t0 + timedelta(minutes=5)) == 0
          and target(p['id'], 'tiktok').get('needs_post_id') is True)
    status['ids'] = [7311]
    n = sp.sync_metrics('biz1', now=t0 + timedelta(hours=1))
    t = target(p['id'], 'tiktok')
    check('id + link + real metrics after moderation', n == 1 and t['remote_id'] == '7311' and t['needs_post_id'] is False
          and t['permalink'] == 'https://www.tiktok.com/@gn/video/7311'
          and DB.social_post_metrics.find_one({'post_id': p['id']})['metrics'] == {'views': 90, 'likes': 9})


def test_soc9_google_revoke_only_when_last_google_platform():
    """SOC-9: ngắt YouTube khi Google Business còn nối -> KHÔNG thu hồi quyền Google (sẽ làm hỏng bên kia)."""
    reset()
    for p, ext in (('youtube', 'UC1'), ('google_business', 'accounts/1/locations/2')):
        account('biz1', p, ext, f'tok-{p}', connected_via='oauth', token_expires_at=now0() + timedelta(hours=1))
    HTTP.on('POST', r'gauth\.mock/revoke$', {})
    sa.disconnect('biz1', 'youtube')
    check('no revoke while GBP connected', not HTTP.find('POST', '/revoke')
          and sa.public_status('biz1')['youtube']['status'] == 'disconnected' and sa.is_connected('biz1', 'google_business'))
    sa.disconnect('biz1', 'google_business')
    check('last Google platform revokes', len(HTTP.find('POST', '/revoke')) == 1)


def test_soc13_14_caption_limits_not_silently_cut():
    """SOC-13/14: Facebook nhận tới 63.206 ký tự (không cắt ở 5000); mô tả YouTube tính theo BYTE; quá giới hạn thì báo rõ."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    account('biz1', 'instagram', 'IG1')
    account('biz1', 'youtube', 'UC1', 'ya29', connected_via='oauth', token_expires_at=now0() + timedelta(hours=1))
    long_fb = 'A' * 6000
    sent = {}
    HTTP.on('POST', r'/PAGE1/feed$', lambda c: sent.update(msg=c.data['message']) or {'id': 'PAGE1_L'})
    p = post(caption=long_fb, targets=['facebook'])
    sp.run_due('biz1', now=now0())
    check('6000-char Facebook post sent whole', len(stored(p['id'])['caption']) == 6000 and sent.get('msg') == long_fb)
    _expect('IG own caption over 2200 refused', lambda: post(caption='x', captions={'instagram': 'b' * 2300}, targets=['facebook'],
                                                             status='draft'), 'caption_too_long', 'instagram')
    media('j', 'image/jpeg')
    _expect('base text too long for IG refused at schedule', lambda: post(caption='c' * 3000, media_file_ids=['j'],
                                                                          targets=['facebook', 'instagram']), 'caption_too_long', 'instagram')
    media('v', 'video/mp4', kind='ai_video', data=mp4(5))
    vi = 'Chăm sóc móng đẹp ' * 220   # ~4000 ký tự nhưng > 5000 byte UTF-8
    check('fixture: under 5000 chars, over 5000 bytes', len(vi) < 5000 and len(vi.encode('utf-8')) > 5000)
    _expect('YouTube description counted in bytes', lambda: post(caption=vi, title='T', media_file_ids=['v'], targets=['youtube']),
            'caption_too_long', 'youtube')
    cut = sp.caption_for({'caption': 'ệ' * 2000}, 'youtube')
    check('byte cut never breaks a letter', len(cut.encode('utf-8')) <= 5000 and set(cut) == {'ệ'})


def test_soc15_best_times_ignore_other_world():
    """SOC-15: số liệu của bài khác "thế giới" (thật vs chạy thử) không bao giờ thành giờ tốt nhất đã học."""
    reset()
    base = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    for i in range(12):
        _metric_post(300 + i, base + timedelta(weeks=i), 0.5)
        DB.social_posts.update_one({'id': 300 + i}, {'$set': {'qa_test': False}})   # bài THẬT, máy đang ở chế độ thử
    d = pl.best_times('biz1', 'facebook')
    check('real-world numbers not mixed into test mode', d['source'] == 'default' and d['sample_size'] == 0, d)


def test_f5_weekly_plan_batches_keep_partial_results():
    """F5: kế hoạch tuần chia lô (JSON mode, token theo số bài); lô bị cắt / lỗi không làm mất các bài đã viết."""
    reset()
    account('biz1', 'facebook', 'PAGE1')
    for i in range(1, 8):
        DB.products.insert_one({'id': i, 'business_id': 'biz1', 'name': f'Service {i}', 'price': 10 + i, 'is_active': 1, 'image': ''})

    def ai(s, u):
        idxs = [it['idx'] for it in json.loads(u.split('ITEMS:\n', 1)[1])]
        if 6 in idxs:
            raise RuntimeError('DeepSeek down for this batch')
        if 3 in idxs:   # bị cắt giữa bài thứ 3 (hết max_tokens)
            return ('{"posts": [{"idx": 3, "caption": "P3", "hashtags": ["a"]}, {"idx": 4, "caption": "P4"}, '
                    '{"idx": 5, "capt', 'length')
        return json.dumps({'posts': [{'idx': i, 'caption': f'P{i}'} for i in idxs]})
    AI['fn'] = ai
    plan, posts = pl.weekly_plan('biz1', 'u1', None, ['facebook'], 7, 'en')
    sizes = sorted(len(json.loads(p['messages'][1]['content'].split('ITEMS:\n', 1)[1])) for p in AI['payloads'])
    check('3 batches of <=3 items', sizes == [1, 3, 3], sizes)
    check('json mode + token budget per batch', all(p.get('response_format') == {'type': 'json_object'} and
                                                    p['max_tokens'] == 300 + 700 * len(json.loads(p['messages'][1]['content'].split('ITEMS:\n', 1)[1]))
                                                    for p in AI['payloads']))
    check('complete posts kept (incl. truncated batch)', sorted(p['caption'] for p in posts) == ['P0', 'P1', 'P2', 'P3', 'P4'])
    check('plan says what is missing', plan['unwritten'] == 2 and '5 of 7' in plan['note'] and '5/7' in plan['note_vi'])
    AI['fn'] = lambda s, u: (_ for _ in ()).throw(RuntimeError('down'))
    _expect('all batches down -> ai_unavailable (honest reason)', lambda: pl.weekly_plan('biz1', 'u1', None, ['facebook'], 4, 'en'),
            'ai_unavailable')


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]

if __name__ == '__main__':
    failed = 0
    for fn in TESTS:
        start = len(RESULTS)
        try:
            fn()
            bad = [n for n, ok in RESULTS[start:] if not ok]   # check() hỏng bên trong máy giả HTTP cũng tính là lỗi
            if bad:
                raise AssertionError(f"failed checks: {bad}")
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} tests passed, {sum(ok for _, ok in RESULTS)} checks ok")
    sys.exit(1 if failed else 0)
