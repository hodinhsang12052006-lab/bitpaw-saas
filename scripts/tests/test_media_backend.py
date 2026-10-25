"""
Test OFFLINE cho media_store.py + ai_media.py + ai_studio_bp.py (docs/AI_SUITE_SPEC.md §1–3).

    python scripts/tests/test_media_backend.py

KHÔNG kết nối MongoDB (local và production chung 1 DB), KHÔNG gọi Replicate/DeepSeek thật, KHÔNG import app.py:
mongo_client / app / ai_deepseek_client được thay bằng bản giả TRƯỚC khi import module thật; mọi lệnh requests.* bị
chặn (gọi nhầm ra mạng -> test hỏng ngay), Replicate giả trả lời qua mock.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from bson import ObjectId  # noqa: E402  (bson/gridfs/pymongo import không mở kết nối nào)
from gridfs.errors import NoFile  # noqa: E402


# ---------------------------------------------------------------- Mongo giả (đủ cho các module này)
def _norm(v):
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)   # như pymongo: lưu UTC, đọc ra naive
    return v


def _store(v):
    if isinstance(v, dict):
        return {k: _store(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_store(x) for x in v]
    return _norm(v)


def _copy(doc):
    return _store(doc)


def _match(doc, flt):
    for k, cond in (flt or {}).items():
        if k == '$or':
            if not any(_match(doc, c) for c in cond):
                return False
            continue
        if k == '$and':
            if not all(_match(doc, c) for c in cond):
                return False
            continue
        present, val = k in doc, _norm(doc.get(k))
        if isinstance(cond, dict) and cond and all(str(op).startswith('$') for op in cond):
            for op, arg in cond.items():
                if op == '$in':
                    if val not in [_norm(a) for a in arg]:
                        return False
                elif op == '$nin':
                    if val in [_norm(a) for a in arg]:
                        return False
                elif op == '$ne':
                    if val == _norm(arg):
                        return False
                elif op == '$exists':
                    if present != bool(arg):
                        return False
                elif op in ('$lt', '$lte', '$gt', '$gte'):
                    if val is None:
                        return False
                    a = _norm(arg)
                    ok = {'$lt': val < a, '$lte': val <= a, '$gt': val > a, '$gte': val >= a}[op]
                    if not ok:
                        return False
                else:
                    raise NotImplementedError(op)
        elif cond is None:
            if val is not None:
                return False
        elif val != _norm(cond):
            return False
    return True


def _apply(doc, upd, inserting=False):
    for op, fields in upd.items():
        for k, v in fields.items():
            if op == '$set':
                doc[k] = _store(v)
            elif op == '$unset':
                doc.pop(k, None)
            elif op == '$inc':
                doc[k] = (doc.get(k) or 0) + v
            elif op == '$setOnInsert':
                if inserting:
                    doc[k] = _store(v)
            else:
                raise NotImplementedError(op)


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        self.docs.sort(key=lambda d: (d.get(key) is None, d.get(key) if d.get(key) is not None else 0), reverse=direction < 0)
        return self

    def limit(self, n):
        if n:
            self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter([_copy(d) for d in self.docs])


class FakeCollection:
    def __init__(self, name):
        self.name, self.docs = name, []

    def insert_one(self, doc):
        doc.setdefault('_id', ObjectId())
        self.docs.append(_store(doc))
        return types.SimpleNamespace(inserted_id=doc['_id'])

    def find(self, flt=None, projection=None):
        return FakeCursor([d for d in self.docs if _match(d, flt)])

    def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if _match(d, flt):
                return _copy(d)
        return None

    def count_documents(self, flt):
        return sum(1 for d in self.docs if _match(d, flt))

    def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                _apply(d, upd)
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith('$') and not isinstance(v, dict)}
            _apply(new, upd, inserting=True)
            self.insert_one(new)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, flt, upd):
        n = 0
        for d in self.docs:
            if _match(d, flt):
                _apply(d, upd)
                n += 1
        return types.SimpleNamespace(matched_count=n, modified_count=n)

    def find_one_and_update(self, flt, upd, projection=None, return_document=False, upsert=False, **kw):
        for d in self.docs:
            if _match(d, flt):
                before = _copy(d)
                _apply(d, upd)
                return _copy(d) if return_document else before
        return None

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _match(d, flt):
                del self.docs[i]
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    def delete_many(self, flt):
        keep = [d for d in self.docs if not _match(d, flt)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return types.SimpleNamespace(deleted_count=n)

    def aggregate(self, pipeline):
        rows = [_copy(d) for d in self.docs]
        for stage in pipeline:
            if '$match' in stage:
                rows = [r for r in rows if _match(r, stage['$match'])]
            elif '$group' in stage:
                g = stage['$group']
                key = g['_id']
                groups = {}
                for r in rows:
                    gk = r.get(key[1:]) if isinstance(key, str) else None
                    acc = groups.setdefault(gk, {'_id': gk})
                    for f, spec in g.items():
                        if f == '_id':
                            continue
                        src = spec['$sum']
                        acc[f] = acc.get(f, 0) + (r.get(src[1:]) or 0 if isinstance(src, str) else src)
                rows = list(groups.values())
        return iter(rows)


class FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = FakeCollection(name)
        return self._cols[name]

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]


class FakeGridOut:
    def __init__(self, fdoc, data):
        self.__dict__['_file'] = fdoc
        self.__dict__['_data'] = data
        self.__dict__['_pos'] = 0

    def __getattr__(self, name):
        f = self.__dict__['_file']
        if name in f:
            return f[name]
        raise AttributeError(name)

    @property
    def _id(self):
        return self._file['_id']

    @property
    def length(self):
        return self._file['length']

    @property
    def content_type(self):
        return self._file.get('contentType')

    def seek(self, pos):
        self.__dict__['_pos'] = pos

    def read(self, n=-1):
        p = self._pos
        out = self._data[p:] if n is None or n < 0 else self._data[p:p + n]
        self.__dict__['_pos'] = p + len(out)
        return out


class FakeGridFS:
    def __init__(self, fdb):
        self.db, self.blobs = fdb, {}

    def put(self, data, **kw):
        oid = ObjectId()
        if 'content_type' in kw:
            kw['contentType'] = kw.pop('content_type')
        doc = {'_id': oid, 'length': len(data), 'chunkSize': 261120, 'uploadDate': datetime.now(timezone.utc)}
        doc.update(kw)
        self.db['media.files'].insert_one(doc)
        self.blobs[oid] = bytes(data)
        return oid

    def get(self, oid):
        doc = self.db['media.files'].find_one({'_id': oid})
        if not doc:
            raise NoFile(str(oid))
        return FakeGridOut(doc, self.blobs[oid])

    def delete(self, oid):
        self.db['media.files'].delete_one({'_id': oid})
        self.blobs.pop(oid, None)


# ---------------------------------------------------------------- stub TRƯỚC khi import module thật
FDB = FakeDB()
_ids = {}


def _next_id(name):
    _ids[name] = _ids.get(name, 0) + 1
    return _ids[name]


sys.modules['mongo_client'] = types.SimpleNamespace(db=FDB, next_mongo_id=_next_id)
sys.modules['app'] = types.SimpleNamespace(login_required=lambda f: f, _tenant_currency=lambda b: 'USD')
_DEEPSEEK = {'reply': 'a bright nail salon photo', 'calls': []}


def _fake_deepseek(payload, **kw):
    _DEEPSEEK['calls'].append(payload)
    return {'choices': [{'message': {'content': _DEEPSEEK['reply']}}]}


sys.modules['ai_deepseek_client'] = types.SimpleNamespace(deepseek_chat_completion=_fake_deepseek)

os.environ['FLASK_SECRET_KEY'] = 'unit-test-secret'
os.environ['REPLICATE_API_TOKEN'] = 'r8_unit_test'
os.environ['REPLICATE_API_BASE'] = 'http://127.0.0.1:9'   # bật test_mode() + base giả
os.environ['SOCIAL_TEST_BUSINESS_IDS'] = 'biz-test,biz-pro,biz-full'
os.environ.pop('REPLICATE_WEBHOOK_SECRET', None)
os.environ.pop('PUBLIC_BASE_URL', None)


def _no_network(*a, **kw):
    raise RuntimeError('network disabled in offline tests')


_NET_GUARD = mock.patch('requests.sessions.Session.request', _no_network)
_NET_GUARD.start()

import media_store  # noqa: E402
import ai_media  # noqa: E402
import plans  # noqa: E402
import ai_studio_bp  # noqa: E402
from flask import Flask  # noqa: E402

media_store._FS = FakeGridFS(FDB)
ai_studio_bp._business_facts = lambda bid: 'BUSINESS FACTS: Test Nails; Services: Gel $35'

JPEG = b'\xff\xd8\xff\xe0' + b'\x00\x10JFIF' + bytes(range(256)) * 4
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 200
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'\x00' * 100
MP4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2' + b'\x00' * 300
WEBM = b'\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\x82\x84webm' + b'\x00' * 100


class FakeResp:
    def __init__(self, status=200, json_data=None, content=b'', headers=None):
        self.status_code = status
        self._json = json_data
        self.content = content if json_data is None else json.dumps(json_data).encode()
        self.headers = headers or {}
        self.text = self.content.decode('latin-1')
        self.closed = False

    def json(self):
        if self._json is None:
            raise ValueError('no json')
        return self._json

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        self.closed = True


def _reset_db():
    FDB._cols.clear()
    media_store._FS = FakeGridFS(FDB)
    plans._PLAN_CACHE.clear()


def _flask_app():
    app = Flask(__name__)
    app.secret_key = 'unit-test-secret'
    app.register_blueprint(media_store.media_bp)
    app.register_blueprint(ai_studio_bp.ai_studio_bp)
    return app


def _login(client, bid='biz-test'):
    with client.session_transaction() as s:
        s['user_id'] = 'user-1'
        s['business_id'] = bid


# ---------------------------------------------------------------- tests
class SniffTests(unittest.TestCase):
    def test_magic_bytes(self):
        self.assertEqual(media_store.sniff(JPEG), 'image/jpeg')
        self.assertEqual(media_store.sniff(PNG), 'image/png')
        self.assertEqual(media_store.sniff(WEBP), 'image/webp')
        self.assertEqual(media_store.sniff(MP4), 'video/mp4')
        self.assertEqual(media_store.sniff(WEBM), 'video/webm')

    def test_mp4_by_compatible_brand_and_rejects(self):
        odd = b'\x00\x00\x00\x18ftypXYZ1\x00\x00\x00\x00mp42isom' + b'\x00' * 50
        self.assertEqual(media_store.sniff(odd), 'video/mp4')
        heic = b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic' + b'\x00' * 50
        self.assertIsNone(media_store.sniff(heic))
        mkv = b'\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x88matroska' + b'\x00' * 50
        self.assertIsNone(media_store.sniff(mkv))
        self.assertIsNone(media_store.sniff(b'<html><script>alert(1)</script></html>'))
        self.assertIsNone(media_store.sniff(b'\xff\xd8'))
        self.assertIsNone(media_store.sniff(b''))
        self.assertIsNone(media_store.sniff(b'GIF89a' + b'\x00' * 20))


class TokenTests(unittest.TestCase):
    def test_sign_verify(self):
        fid = str(ObjectId())
        tok = media_store.public_token(fid)
        fid2, sig = tok.split('.')
        self.assertEqual(fid2, fid)
        self.assertEqual(len(sig), 24)
        want = hmac.new(b'unit-test-secret', f'media|{fid}'.encode(), hashlib.sha256).hexdigest()[:24]
        self.assertEqual(sig, want)
        self.assertEqual(media_store.verify_token(tok), fid)
        self.assertEqual(media_store.public_url(fid, 'jpg'), f'/m/{tok}.jpg')
        self.assertEqual(media_store.absolute_public_url(fid, 'mp4', 'https://x.test/'), f'https://x.test/m/{tok}.mp4')

    def test_tampered(self):
        fid = str(ObjectId())
        tok = media_store.public_token(fid)
        bad = tok[:-1] + ('0' if tok[-1] != '0' else '1')
        self.assertIsNone(media_store.verify_token(bad))
        other = str(ObjectId())
        self.assertIsNone(media_store.verify_token(f"{other}.{tok.split('.')[1]}"))
        for t in ('', 'abc', tok + '.x', tok.upper(), None, fid):
            self.assertIsNone(media_store.verify_token(t))


class RangeTests(unittest.TestCase):
    S = media_store.SLICE

    def test_no_range(self):
        self.assertEqual(media_store.plan_range(None, 4_000_000), (200, 0, 3_999_999))
        self.assertEqual(media_store.plan_range(None, 4_400_000), (200, 0, 4_399_999))
        self.assertEqual(media_store.plan_range(None, 10_000_000), (206, 0, self.S - 1))
        self.assertEqual(media_store.plan_range('items=0-5', 100), (200, 0, 99))

    def test_slices(self):
        size = 10_000_000
        self.assertEqual(media_store.plan_range('bytes=0-', size), (206, 0, self.S - 1))          # đầu, mở -> cắt
        self.assertEqual(media_store.plan_range('bytes=0-99', size), (206, 0, 99))
        self.assertEqual(media_store.plan_range(f'bytes={self.S}-{2 * self.S - 1}', size), (206, self.S, 2 * self.S - 1))
        self.assertEqual(media_store.plan_range('bytes=1000-9999999', size), (206, 1000, 1000 + self.S - 1))  # giữa, cắt
        self.assertEqual(media_store.plan_range('bytes=7000000-', size), (206, 7_000_000, size - 1))       # lát cuối
        self.assertEqual(media_store.plan_range('bytes=9999999-20000000', size), (206, 9_999_999, 9_999_999))
        self.assertEqual(media_store.plan_range('bytes=0-99,200-299', size), (206, 0, 99))

    def test_suffix_and_invalid(self):
        self.assertEqual(media_store.plan_range('bytes=-500', 1000), (206, 500, 999))
        self.assertEqual(media_store.plan_range('bytes=-5000', 1000), (206, 0, 999))
        self.assertEqual(media_store.plan_range('bytes=-5000000', 10_000_000), (206, 5_000_000, 5_000_000 + self.S - 1))
        self.assertEqual(media_store.plan_range('bytes=20000000-', 10_000_000)[0], 416)
        self.assertEqual(media_store.plan_range('bytes=-0', 100)[0], 416)
        self.assertEqual(media_store.plan_range('bytes=50-10', 100), (200, 0, 99))   # sai cú pháp -> bỏ qua
        self.assertEqual(media_store.plan_range('bytes=abc', 100), (200, 0, 99))


class StoreAndPublicRouteTests(unittest.TestCase):
    def setUp(self):
        _reset_db()
        self.app = _flask_app()
        self.c = self.app.test_client()

    def test_save_and_serve(self):
        saved = media_store.save_bytes('biz-test', JPEG, 'ai_image', filename='x.png', meta={'source': 'replicate', 'job_id': 7})
        self.assertEqual(saved['content_type'], 'image/jpeg')   # theo magic bytes, không theo tên file
        self.assertTrue(saved['public_url'].endswith('.jpg'))
        f = FDB['media.files'].find_one({})
        self.assertEqual((f['business_id'], f['kind'], f['source'], f['job_id'], f['contentType']),
                         ('biz-test', 'ai_image', 'replicate', 7, 'image/jpeg'))
        self.assertTrue(f.get('qa_test'))
        r = self.c.get(saved['public_url'])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, JPEG)
        self.assertEqual(r.headers['Content-Type'], 'image/jpeg')
        self.assertEqual(r.headers['Cache-Control'], 'public, max-age=31536000, immutable')
        self.assertEqual(r.headers['X-Media-Cache'], '1')
        self.assertEqual(r.headers['Accept-Ranges'], 'bytes')
        r = self.c.get(saved['public_url'], headers={'Range': 'bytes=0-9'})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.data, JPEG[:10])
        self.assertEqual(r.headers['Content-Range'], f'bytes 0-9/{len(JPEG)}')
        r = self.c.get(saved['public_url'], headers={'Range': f'bytes={len(JPEG) + 5}-'})
        self.assertEqual(r.status_code, 416)
        self.assertEqual(r.headers['Content-Range'], f'bytes */{len(JPEG)}')
        r = self.c.get(saved['public_url'], headers={'If-None-Match': f'"{saved["file_id"]}"'})
        self.assertEqual(r.status_code, 304)
        self.assertEqual(self.c.get(saved['public_url'][:-4] + '.png').status_code, 404)   # đuôi sai
        self.assertEqual(self.c.get(saved['public_url'].replace('.jpg', 'x.jpg')).status_code, 404)
        self.assertEqual(self.c.head(saved['public_url']).status_code, 200)

    def test_private_kind_never_public(self):
        oid = media_store._FS.put(JPEG, content_type='image/jpeg', business_id='biz-test', kind='checkin')
        url = media_store.public_url(str(oid), 'jpg')
        self.assertEqual(self.c.get(url).status_code, 404)

    def test_big_video_without_range(self):
        saved = media_store.save_bytes('biz-test', MP4 + b'\x00' * 50, 'promo_video')
        with mock.patch.object(media_store, 'FULL_MAX', 100), mock.patch.object(media_store, 'SLICE', 64):
            r = self.c.get(saved['public_url'])
            self.assertEqual(r.status_code, 206)
            self.assertEqual(len(r.data), 64)
            self.assertEqual(r.headers['Content-Range'], f'bytes 0-63/{saved["size"]}')
            r = self.c.get(saved['public_url'], headers={'Range': 'bytes=64-'})
            self.assertEqual(r.headers['Content-Range'], f'bytes 64-127/{saved["size"]}')

    def test_save_rejects(self):
        with self.assertRaises(media_store.MediaError) as cm:
            media_store.save_bytes('biz-test', b'<html>' * 10, 'ai_image')
        self.assertEqual(cm.exception.code, 'unsupported_type')
        with self.assertRaises(media_store.MediaError) as cm:
            media_store.save_bytes('biz-test', JPEG, 'checkin')
        self.assertEqual(cm.exception.code, 'bad_kind')
        with mock.patch.object(media_store, 'MAX_IMAGE_BYTES', 100):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.save_bytes('biz-test', JPEG, 'ai_image')
            self.assertEqual(cm.exception.code, 'too_large')

    def test_get_delete_usage(self):
        a = media_store.save_bytes('biz-test', JPEG, 'ai_image')
        media_store.save_bytes('biz-other', PNG, 'social_upload')
        self.assertIsNone(media_store.get(a['file_id'], 'biz-other'))
        self.assertIsNotNone(media_store.get(a['file_id'], 'biz-test'))
        self.assertIsNone(media_store.get('nope'))
        self.assertEqual(media_store.usage_bytes('biz-test'), len(JPEG))
        self.assertFalse(media_store.delete(a['file_id'], 'biz-other'))
        self.assertTrue(media_store.delete(a['file_id'], 'biz-test'))
        self.assertEqual(media_store.usage_bytes('biz-test'), 0)


class UploadApiTests(unittest.TestCase):
    def setUp(self):
        _reset_db()
        self.app = _flask_app()
        self.c = self.app.test_client()
        self.p = mock.patch.object(media_store, 'SLICE', 128)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _init(self, data, kind='social_upload', ctype='video/mp4'):
        return self.c.post('/api/media/upload/init', json={'kind': kind, 'size': len(data), 'content_type': ctype})

    def test_requires_login(self):
        self.assertEqual(self._init(MP4).status_code, 401)

    def test_chunked_roundtrip_idempotent_finish(self):
        _login(self.c)
        data = MP4 + bytes(range(256))
        r = self._init(data, kind='promo_video')
        self.assertEqual(r.status_code, 200, r.json)
        up = r.json['upload_id']
        n = r.json['chunks']
        self.assertEqual(n, -(-len(data) // 128))
        for i in range(n):
            r = self.c.post(f'/api/media/upload/{up}/chunk?index={i}', data=data[i * 128:(i + 1) * 128])
            self.assertEqual(r.status_code, 200, r.json)
        # gửi lại khúc 0 (mạng chập chờn) không làm hỏng dữ liệu
        r = self.c.post(f'/api/media/upload/{up}/chunk?index=0', data=data[:128])
        self.assertEqual(r.json['received'], len(data))
        r = self.c.post(f'/api/media/upload/{up}/finish')
        self.assertEqual(r.status_code, 200, r.json)
        fid = r.json['file_id']
        self.assertEqual(r.json['content_type'], 'video/mp4')
        f = FDB['media.files'].find_one({'_id': ObjectId(fid)})
        self.assertEqual((f['kind'], f['source'], f['length']), ('promo_video', 'browser', len(data)))
        self.assertEqual(media_store._FS.blobs[ObjectId(fid)], data)
        self.assertEqual(FDB.media_upload_chunks.count_documents({'type': 'chunk'}), 0)
        r2 = self.c.post(f'/api/media/upload/{up}/finish')
        self.assertEqual(r2.json['file_id'], fid)     # finish lần 2 -> cùng file, không lưu thêm
        self.assertEqual(FDB['media.files'].count_documents({}), 1)

    def test_rejects(self):
        _login(self.c)
        self.assertEqual(self._init(MP4, kind='ai_image').json['code'], 'bad_kind')
        self.assertEqual(self._init(MP4, ctype='text/html').json['code'], 'unsupported_type')
        self.assertEqual(self._init(MP4, kind='promo_video', ctype='image/jpeg').json['code'], 'unsupported_type')
        r = self.c.post('/api/media/upload/init', json={'kind': 'social_upload', 'size': 'x', 'content_type': 'video/mp4'})
        self.assertEqual(r.json['code'], 'bad_size')
        r = self.c.post('/api/media/upload/init', json={'kind': 'social_upload', 'size': 9_000_000, 'content_type': 'image/png'})
        self.assertEqual(r.json['code'], 'too_large')
        # khai ảnh nhưng ruột là video -> từ chối lúc finish
        r = self._init(MP4, ctype='image/jpeg')
        up = r.json['upload_id']
        for i in range(r.json['chunks']):
            self.c.post(f'/api/media/upload/{up}/chunk?index={i}', data=MP4[i * 128:(i + 1) * 128])
        r = self.c.post(f'/api/media/upload/{up}/finish')
        self.assertEqual(r.json['code'], 'unsupported_type')
        # thiếu khúc
        r = self._init(MP4)
        up = r.json['upload_id']
        self.c.post(f'/api/media/upload/{up}/chunk?index=0', data=MP4[:128])
        self.assertEqual(self.c.post(f'/api/media/upload/{up}/finish').json['code'], 'missing_chunks')
        self.assertEqual(self.c.post(f'/api/media/upload/{up}/chunk?index=99', data=b'x').json['code'], 'bad_index')
        self.assertEqual(self.c.post(f'/api/media/upload/{up}/chunk?index=1', data=b'x' * 200).status_code, 413)
        # tiệm khác không chạm được phiên tải của tiệm này
        _login(self.c, 'biz-other')
        self.assertEqual(self.c.post(f'/api/media/upload/{up}/chunk?index=1', data=b'x').status_code, 404)


class WebhookSignatureTests(unittest.TestCase):
    KEY = b'0123456789abcdef0123456789abcdef'

    def setUp(self):
        os.environ['REPLICATE_WEBHOOK_SECRET'] = 'whsec_' + base64.b64encode(self.KEY).decode()

    def tearDown(self):
        os.environ.pop('REPLICATE_WEBHOOK_SECRET', None)

    def _sign(self, body, wid='msg_1', ts=None, key=None):
        ts = str(int(time.time()) if ts is None else ts)
        sig = base64.b64encode(hmac.new(key or self.KEY, f'{wid}.{ts}.'.encode() + body, hashlib.sha256).digest()).decode()
        return {'webhook-id': wid, 'webhook-timestamp': ts, 'webhook-signature': f'v1,{sig}'}

    def test_valid_and_tampered(self):
        body = b'{"id":"pred1","status":"succeeded"}'
        h = self._sign(body)
        self.assertTrue(ai_media.verify_webhook(body, h))
        self.assertTrue(ai_media.verify_webhook(body, {k.title(): v for k, v in h.items()}))   # header không phân biệt hoa thường
        self.assertFalse(ai_media.verify_webhook(body + b' ', h))
        multi = dict(h, **{'webhook-signature': 'v1,AAAA ' + h['webhook-signature'] + ' v2,BBBB'})
        self.assertTrue(ai_media.verify_webhook(body, multi))
        self.assertFalse(ai_media.verify_webhook(body, dict(h, **{'webhook-signature': h['webhook-signature'].replace('v1,', 'v2,')})))
        self.assertFalse(ai_media.verify_webhook(body, self._sign(body, key=b'x' * 32)))
        self.assertFalse(ai_media.verify_webhook(body, self._sign(body, ts=int(time.time()) - 301)))
        self.assertFalse(ai_media.verify_webhook(body, {'webhook-id': 'x'}))
        self.assertFalse(ai_media.verify_webhook(body, {}))

    def test_missing_secret_fails_closed(self):
        os.environ.pop('REPLICATE_WEBHOOK_SECRET', None)
        ai_media._WEBHOOK_SECRET['value'] = None
        body = b'{}'
        with mock.patch('requests.get', return_value=FakeResp(500, {'detail': 'x'})):
            self.assertFalse(ai_media.verify_webhook(body, self._sign(body)))
        # lấy secret từ API rồi cache
        with mock.patch('requests.get', return_value=FakeResp(200, {'key': 'whsec_' + base64.b64encode(self.KEY).decode()})) as g:
            self.assertTrue(ai_media.verify_webhook(body, self._sign(body)))
            self.assertTrue(g.call_args[0][0].endswith('/v1/webhooks/default/secret'))
        ai_media._WEBHOOK_SECRET['value'] = None


class FakeReplicate:
    """Replicate giả: ghi lại mọi request, trả lời theo kịch bản."""

    def __init__(self):
        self.posts, self.gets = [], []
        self.create = {'id': 'pred_abc123', 'status': 'starting'}
        self.create_status = 201
        self.pred = {'id': 'pred_abc123', 'status': 'processing'}
        self.files = {'http://127.0.0.1:9/out/a.jpg': JPEG, 'http://127.0.0.1:9/out/v.mp4': MP4}

    def post(self, url, headers=None, json=None, timeout=None, **kw):
        assert timeout, 'requests must have a timeout'
        self.posts.append({'url': url, 'headers': headers, 'json': json})
        return FakeResp(self.create_status, self.create)

    def get(self, url, headers=None, timeout=None, stream=False, allow_redirects=True, **kw):
        assert timeout, 'requests must have a timeout'
        self.gets.append(url)
        if '/v1/predictions/' in url:
            return FakeResp(200, self.pred)
        if url in self.files:
            return FakeResp(200, content=self.files[url], headers={'Content-Length': str(len(self.files[url]))})
        return FakeResp(404, content=b'nope')


class JobTests(unittest.TestCase):
    def setUp(self):
        _reset_db()
        self.r = FakeReplicate()
        self.patches = [mock.patch('requests.post', self.r.post), mock.patch('requests.get', self.r.get)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_image_lifecycle_and_duplicate_refresh(self):
        job = ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'gel nails', aspect='4:5', base_url='http://127.0.0.1:5001')
        self.assertEqual(job['status'], 'queued')
        call = self.r.posts[0]
        self.assertEqual(call['url'], 'http://127.0.0.1:9/v1/models/black-forest-labs/flux-schnell/predictions')
        self.assertEqual(call['headers']['Prefer'], 'wait=5')
        self.assertEqual(call['json']['input'], {'prompt': 'gel nails', 'aspect_ratio': '4:5', 'output_format': 'jpg', 'num_outputs': 1})
        self.assertNotIn('webhook', call['json'])   # test mode / không HTTPS -> không webhook
        self.assertTrue(job['qa_test'])
        q = ai_media.quota_status('biz-test')
        self.assertEqual((q['images']['used'], q['images']['pending'], q['images']['limit']), (0, 1, 300))

        job = ai_media.refresh_job(job['id'])
        self.assertEqual(job['status'], 'running')

        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': ['http://127.0.0.1:9/out/a.jpg']}
        job = ai_media.refresh_job(job['id'])
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(job['content_type'], 'image/jpeg')
        self.assertTrue(job['public_url'].startswith('/m/') and job['public_url'].endswith('.jpg'))
        self.assertNotIn('storing_until', job)
        # refresh trùng (webhook + giao diện) -> không tải/lưu/ghi sổ lần 2
        again = ai_media.refresh_job(job['id'])
        self.assertEqual(again['file_id'], job['file_id'])
        self.assertEqual(self.r.gets.count('http://127.0.0.1:9/out/a.jpg'), 1)
        self.assertEqual(FDB['media.files'].count_documents({'job_id': job['id']}), 1)
        self.assertEqual(FDB.ai_usage.count_documents({'job_id': job['id']}), 1)
        ai_media._record_usage(again)
        self.assertEqual(FDB.ai_usage.count_documents({'job_id': job['id']}), 1)
        row = FDB.ai_usage.find_one({'job_id': job['id']})
        self.assertEqual((row['kind'], row['units'], row['cost_usd']), ('image', 1, 0.003))
        legacy = FDB.generated_media.find_one({'job_id': job['id']})
        self.assertEqual(legacy['media_url'], 'http://127.0.0.1:5001' + job['public_url'])
        q = ai_media.quota_status('biz-test')
        self.assertEqual((q['images']['used'], q['images']['pending']), (1, 0))
        pub = ai_media.public_job(job)
        self.assertTrue(pub['created_at'].endswith('Z'))
        self.assertNotIn('public_base', pub)

    def test_concurrent_claim_and_crash_reuse(self):
        job = ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': 'http://127.0.0.1:9/out/a.jpg'}
        # tiến trình khác đang lưu (lease còn hạn) -> không tải
        FDB.ai_media_jobs.update_one({'id': job['id']}, {'$set': {'storing_until': datetime.now(timezone.utc) + timedelta(seconds=60)}})
        self.assertIn(ai_media.refresh_job(job['id'])['status'], ('queued', 'running'))
        self.assertEqual(self.r.gets.count('http://127.0.0.1:9/out/a.jpg'), 0)
        # tiến trình đó chết sau khi đã lưu file -> lease hết hạn, lần sau dùng lại file cũ
        media_store.save_bytes('biz-test', JPEG, 'ai_image', meta={'source': 'replicate', 'job_id': job['id']})
        FDB.ai_media_jobs.update_one({'id': job['id']}, {'$set': {'storing_until': datetime.now(timezone.utc) - timedelta(seconds=1)}})
        done = ai_media.refresh_job(job['id'])
        self.assertEqual(done['status'], 'succeeded')
        self.assertEqual(self.r.gets.count('http://127.0.0.1:9/out/a.jpg'), 0)
        self.assertEqual(FDB['media.files'].count_documents({'job_id': job['id']}), 1)

    def test_succeeded_on_create_and_failed(self):
        self.r.create = {'id': 'pred_fast1', 'status': 'succeeded', 'output': ['http://127.0.0.1:9/out/a.jpg']}
        job = ai_media.create_job('biz-test', 'u1', 'image', 'hd', 'x', aspect='1:1')
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(self.r.posts[0]['json']['input']['output_format'], 'jpg')
        self.r.create = {'id': 'pred_bad1', 'status': 'failed', 'error': 'NSFW content detected'}
        job = ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['error']['code'], 'generation_failed')
        self.assertIn('NSFW', job['error']['message'])
        self.assertEqual(FDB.ai_usage.count_documents({'job_id': job['id']}), 0)

    def test_provider_error_marks_failed(self):
        self.r.create_status, self.r.create = 422, {'detail': 'invalid aspect_ratio', 'status': 422}
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.assertEqual(cm.exception.code, 'provider_rejected')
        j = FDB.ai_media_jobs.find_one({})
        self.assertEqual(j['status'], 'failed')

    def test_output_host_not_allowed(self):
        job = ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': 'https://evil.example/a.jpg'}
        job = ai_media.refresh_job(job['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['error']['code'], 'store_failed')
        self.assertNotIn('https://evil.example/a.jpg', self.r.gets)

    def test_video_and_animate_photo(self):
        job = ai_media.create_job('biz-test', 'u1', 'video', 'standard', 'spa room', aspect='9:16', duration=8)
        call = self.r.posts[-1]
        self.assertTrue(call['url'].endswith('/v1/models/bytedance/seedance-1-pro-fast/predictions'))
        self.assertEqual(call['headers']['Cancel-After'], '15m')
        self.assertNotIn('Prefer', call['headers'])
        self.assertEqual(call['json']['input'], {'prompt': 'spa room', 'duration': 8, 'resolution': '720p', 'aspect_ratio': '9:16'})
        self.assertAlmostEqual(job['cost_estimate_usd'], 0.2)
        # ảnh sản phẩm của tiệm (nhỏ) -> data: URI, model i2v
        oid = media_store._FS.put(JPEG, content_type='image/png', business_id='biz-test', kind='product_image')
        job2 = ai_media.create_job('biz-test', 'u1', 'video', 'draft', 'animate', image_file_id=str(oid))
        call = self.r.posts[-1]
        self.assertTrue(call['url'].endswith('/wan-video/wan-2.2-i2v-fast/predictions'))
        self.assertTrue(call['json']['input']['image'].startswith('data:image/jpeg;base64,'))   # sniff, không tin contentType
        self.assertNotIn('aspect_ratio', call['json']['input'])
        self.assertEqual(job2['model'], 'wan-video/wan-2.2-i2v-fast')
        # ảnh của tiệm khác / ảnh riêng tư -> từ chối
        other = media_store._FS.put(JPEG, content_type='image/jpeg', business_id='biz-other', kind='product_image')
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-test', 'u1', 'video', 'draft', 'x', image_file_id=str(other))
        self.assertEqual(cm.exception.code, 'image_not_found')
        priv = media_store._FS.put(JPEG, content_type='image/jpeg', business_id='biz-test', kind='checkin')
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-test', 'u1', 'video', 'draft', 'x', image_file_id=str(priv))
        self.assertEqual(cm.exception.code, 'image_not_allowed')
        # video xong -> lưu ai_video, ghi sổ theo giây
        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': 'http://127.0.0.1:9/out/v.mp4'}
        done = ai_media.refresh_job(job['id'])
        self.assertEqual((done['status'], done['content_type']), ('succeeded', 'video/mp4'))
        self.assertEqual(FDB.ai_usage.find_one({'job_id': job['id']})['units'], 8)

    def test_validation(self):
        cases = [(('image', 'nope', 'x'), {}, 'bad_preset'), (('image', 'draft', 'x'), {'aspect': '7:3'}, 'bad_aspect'),
                 (('video', 'premium', 'x'), {'duration': 5}, 'bad_duration'), (('image', 'draft', '  '), {}, 'prompt_required'),
                 (('image', 'draft', 'x' * 2001), {}, 'prompt_too_long'),
                 (('image', 'draft', 'x'), {'image_file_id': str(ObjectId())}, 'image_not_supported')]
        for args, kw, code in cases:
            with self.assertRaises(ai_media.MediaError) as cm:
                ai_media.create_job('biz-test', 'u1', *args, **kw)
            self.assertEqual(cm.exception.code, code, (args, kw))
        self.assertEqual(self.r.posts, [])

    def test_quota_exceeded(self):
        FDB.ai_usage.insert_one({'business_id': 'biz-full', 'kind': 'image', 'units': 300, 'cost_usd': 0.9, 'job_id': 999,
                                 'created_at': datetime.now(timezone.utc)})
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-full', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.assertEqual(cm.exception.code, 'quota_exceeded')
        self.assertEqual(cm.exception.detail['images']['used'], 300)
        # tháng trước không tính
        FDB.ai_usage.update_one({'job_id': 999}, {'$set': {'created_at': datetime.now(timezone.utc) - timedelta(days=40)}})
        ai_media.create_job('biz-full', 'u1', 'image', 'draft', 'x', aspect='1:1')
        # gói Pro: hạn mức 0
        FDB.businesses.insert_one({'id': 'biz-pro', 'plan': 'pro'})
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-pro', 'u1', 'video', 'draft', 'x')
        self.assertEqual(cm.exception.code, 'quota_exceeded')
        # video đang chạy giữ chỗ hạn mức giây
        FDB.ai_usage.insert_one({'business_id': 'biz-test', 'kind': 'video', 'units': 291, 'job_id': 1000,
                                 'created_at': datetime.now(timezone.utc)})
        ai_media.create_job('biz-test', 'u1', 'video', 'draft', 'x')            # 291 + 5 = 296 ≤ 300
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('biz-test', 'u1', 'video', 'draft', 'x')        # 291 + 5 đang chạy + 5 = 301 > 300
        self.assertEqual(cm.exception.code, 'quota_exceeded')

    def test_test_mode_business_filter_and_missing_token(self):
        with self.assertRaises(ai_media.MediaError) as cm:
            ai_media.create_job('real-shop', 'u1', 'image', 'draft', 'x', aspect='1:1')
        self.assertEqual(cm.exception.code, 'test_mode_business')
        with mock.patch.dict(os.environ, {'REPLICATE_API_TOKEN': ''}):
            with self.assertRaises(ai_media.MediaError) as cm:
                ai_media.create_job('biz-test', 'u1', 'image', 'draft', 'x', aspect='1:1')
            self.assertEqual(cm.exception.code, 'not_configured')

    def test_webhook_only_on_https_outside_test_mode(self):
        with mock.patch.object(ai_media, 'test_mode', lambda: False), mock.patch.object(media_store, 'test_mode', lambda: False):
            job = ai_media.create_job('real-shop', 'u1', 'image', 'draft', 'x', aspect='1:1', base_url='https://shop.example')
        body = self.r.posts[-1]['json']
        self.assertEqual(body['webhook'], f"https://shop.example/api/ai_studio/replicate_webhook?job={job['id']}")
        self.assertEqual(body['webhook_events_filter'], ['completed'])


class FetchToStoreTests(unittest.TestCase):
    def setUp(self):
        _reset_db()

    def test_allowlist(self):
        hosts = ('replicate.delivery', 'replicate.com')
        for url, code in (('https://evilreplicate.delivery/a.jpg', 'bad_host'), ('https://replicate.delivery.evil.io/a.jpg', 'bad_host'),
                          ('http://replicate.delivery/a.jpg', 'bad_url'), ('ftp://replicate.delivery/a.jpg', 'bad_url'),
                          ('https://user:pw@replicate.delivery/a.jpg', 'bad_url'), ('https://169.254.169.254/latest', 'bad_host')):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.fetch_to_store('biz-test', url, 'ai_image', hosts, 1000)
            self.assertEqual(cm.exception.code, code, url)
        with mock.patch('requests.get', return_value=FakeResp(200, content=JPEG)) as g:
            out = media_store.fetch_to_store('biz-test', 'https://pbxt.replicate.delivery/x/out-0.jpg', 'ai_image', hosts, 10_000)
            self.assertEqual(out['content_type'], 'image/jpeg')
            self.assertFalse(g.call_args.kwargs['allow_redirects'])
            self.assertTrue(g.call_args.kwargs['timeout'])

    def test_local_http_only_in_test_mode(self):
        with mock.patch('requests.get', return_value=FakeResp(200, content=JPEG)):
            media_store.fetch_to_store('biz-test', 'http://127.0.0.1:9/a.jpg', 'ai_image', ai_media.output_hosts(), 10_000)
            with mock.patch.dict(os.environ, {'REPLICATE_API_BASE': ''}):
                self.assertNotIn('127.0.0.1', ai_media.output_hosts())
                with self.assertRaises(media_store.MediaError) as cm:
                    media_store.fetch_to_store('biz-test', 'http://127.0.0.1:9/a.jpg', 'ai_image', ('127.0.0.1',), 10_000)
                self.assertEqual(cm.exception.code, 'bad_url')

    def test_redirect_rechecked(self):
        seq = iter([FakeResp(302, content=b'', headers={'Location': 'https://cdn.replicate.delivery/b.jpg'}),
                    FakeResp(200, content=JPEG)])
        with mock.patch('requests.get', side_effect=lambda *a, **k: next(seq)):
            out = media_store.fetch_to_store('biz-test', 'https://replicate.delivery/a', 'ai_image', ('replicate.delivery',), 10_000)
            self.assertEqual(out['content_type'], 'image/jpeg')
        with mock.patch('requests.get', return_value=FakeResp(302, content=b'', headers={'Location': 'http://10.0.0.1/x'})):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.fetch_to_store('biz-test', 'https://replicate.delivery/a', 'ai_image', ('replicate.delivery',), 10_000)
            self.assertIn(cm.exception.code, ('bad_url', 'bad_host'))

    def test_size_cap(self):
        big = JPEG * 10
        with mock.patch('requests.get', return_value=FakeResp(200, content=big, headers={'Content-Length': str(len(big))})):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.fetch_to_store('biz-test', 'https://replicate.delivery/a', 'ai_image', ('replicate.delivery',), 1000)
            self.assertEqual(cm.exception.code, 'too_large')
        # Content-Length nói dối / không có -> vẫn chặn khi đọc
        with mock.patch('requests.get', return_value=FakeResp(200, content=big, headers={'Content-Length': '10'})):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.fetch_to_store('biz-test', 'https://replicate.delivery/a', 'ai_image', ('replicate.delivery',), 1000)
            self.assertEqual(cm.exception.code, 'too_large')
        with mock.patch('requests.get', return_value=FakeResp(500, content=b'x')):
            with self.assertRaises(media_store.MediaError) as cm:
                media_store.fetch_to_store('biz-test', 'https://replicate.delivery/a', 'ai_image', ('replicate.delivery',), 1000)
            self.assertEqual(cm.exception.code, 'fetch_failed')
        self.assertEqual(FDB['media.files'].count_documents({}), 0)


class StudioRouteTests(unittest.TestCase):
    def setUp(self):
        _reset_db()
        _DEEPSEEK['calls'].clear()
        self.app = _flask_app()
        self.c = self.app.test_client()
        _login(self.c)
        self.r = FakeReplicate()
        self.patches = [mock.patch('requests.post', self.r.post), mock.patch('requests.get', self.r.get)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_generate_text_clamps_and_logs(self):
        _DEEPSEEK['reply'] = 'copy'
        r = self.c.post('/api/ai_studio/generate_text', json={'system_prompt': 's', 'user_prompt': 'u', 'temperature': 5, 'max_tokens': 99999})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((_DEEPSEEK['calls'][-1]['temperature'], _DEEPSEEK['calls'][-1]['max_tokens']), (1.2, 2000))
        self.assertIn('BUSINESS FACTS', _DEEPSEEK['calls'][-1]['messages'][0]['content'])
        row = FDB.ai_usage.find_one({'kind': 'text'})
        self.assertEqual((row['units'], row['cost_usd'], row['business_id']), (2000, 0.0, 'biz-test'))
        self.c.post('/api/ai_studio/generate_text', json={'system_prompt': 's', 'user_prompt': 'u', 'temperature': -3, 'max_tokens': 0})
        self.assertEqual((_DEEPSEEK['calls'][-1]['temperature'], _DEEPSEEK['calls'][-1]['max_tokens']), (0.0, 1))
        for bad in ({'temperature': 'abc'}, {'max_tokens': 'lots'}, {'temperature': 'nan'}, {'max_tokens': [1]}):
            r = self.c.post('/api/ai_studio/generate_text', json=dict({'system_prompt': 's', 'user_prompt': 'u'}, **bad))
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json['code'], 'bad_number')

    def test_job_routes_list_delete(self):
        r = self.c.post('/api/ai_studio/media/jobs', json={'kind': 'image', 'preset': 'draft', 'prompt': 'nails', 'aspect': '1:1'})
        self.assertEqual(r.status_code, 200, r.json)
        jid = r.json['job']['id']
        self.assertEqual(r.json['quota']['images']['pending'], 1)
        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': ['http://127.0.0.1:9/out/a.jpg']}
        # vừa cập nhật (< 4 giây) -> chưa hỏi Replicate
        r = self.c.get(f'/api/ai_studio/media/jobs/{jid}')
        self.assertEqual(r.json['job']['status'], 'queued')
        FDB.ai_media_jobs.update_one({'id': jid}, {'$set': {'updated_at': datetime.now(timezone.utc) - timedelta(seconds=5)}})
        r = self.c.get(f'/api/ai_studio/media/jobs/{jid}')
        self.assertEqual(r.json['job']['status'], 'succeeded')
        fid = r.json['job']['file_id']
        self.assertEqual(r.json['job']['url'], f'/api/storage/file/{fid}')
        # thư viện = job xong + file tải lên
        up = media_store.save_bytes('biz-test', MP4, 'promo_video', meta={'source': 'browser'})
        items = self.c.get('/api/ai_studio/media').json['items']
        self.assertEqual({i['source'] for i in items}, {'replicate', 'browser'})
        self.assertEqual(len(self.c.get('/api/ai_studio/media?kind=image').json['items']), 1)
        self.assertEqual(self.c.get('/api/ai_studio/media?kind=promo_video').json['items'][0]['file_id'], up['file_id'])
        self.assertEqual(self.c.get('/api/ai_studio/media?kind=bogus').status_code, 400)
        self.assertEqual(len(self.c.get('/api/ai_studio/media_history').json['items']), 2)
        # tiệm khác không thấy/không xoá được
        _login(self.c, 'biz-other')
        self.assertEqual(self.c.get(f'/api/ai_studio/media/jobs/{jid}').status_code, 404)
        self.assertEqual(self.c.delete(f'/api/ai_studio/media/{fid}').status_code, 404)
        self.assertEqual(self.c.get('/api/ai_studio/media').json['items'], [])
        _login(self.c)
        self.assertEqual(self.c.delete(f'/api/ai_studio/media/{fid}').status_code, 200)
        self.assertTrue(FDB.ai_media_jobs.find_one({'id': jid})['deleted'])
        self.assertEqual(FDB.generated_media.count_documents({'file_id': fid}), 0)
        self.assertEqual(len(self.c.get('/api/ai_studio/media?kind=image').json['items']), 0)
        q = self.c.get('/api/ai_studio/quota').json
        self.assertEqual((q['plan'], q['images']['used'], q['quota']['images']['limit']), ('empire', 1, 300))
        self.assertEqual([p['preset'] for p in q['presets']['video']], ['draft', 'standard', 'premium'])

    def test_from_text_and_errors(self):
        _DEEPSEEK['reply'] = '"A cozy pedicure chair, warm light"'
        r = self.c.post('/api/ai_studio/media/jobs', json={'kind': 'image', 'preset': 'draft', 'from_text': 'Mùa thu giảm giá', 'aspect': '1:1', 'lang': 'vi'})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json['job']['prompt'], 'A cozy pedicure chair, warm light')
        self.assertEqual(r.json['job']['source_text'], 'Mùa thu giảm giá')
        self.assertIn('Do NOT include any text', _DEEPSEEK['calls'][-1]['messages'][0]['content'])
        r = self.c.post('/api/ai_studio/media/jobs', json={'kind': 'gif', 'prompt': 'x'})
        self.assertEqual((r.status_code, r.json['code']), (400, 'bad_kind'))
        FDB.businesses.insert_one({'id': 'biz-pro', 'plan': 'pro'})
        _login(self.c, 'biz-pro')
        n = len(_DEEPSEEK['calls'])
        r = self.c.post('/api/ai_studio/media/jobs', json={'kind': 'image', 'from_text': 'x', 'aspect': '1:1'})
        self.assertEqual((r.status_code, r.json['code']), (402, 'quota_exceeded'))
        self.assertEqual(len(_DEEPSEEK['calls']), n)   # hết hạn mức -> không tốn lượt DeepSeek

    def test_legacy_generate_image(self):
        self.r.create = {'id': 'pred_fast2', 'status': 'succeeded', 'output': ['http://127.0.0.1:9/out/a.jpg']}
        r = self.c.post('/api/ai_studio/generate_image', json={'prompt': 'nails', 'size': '1024x1792'})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(self.r.posts[-1]['json']['input']['aspect_ratio'], '9:16')
        self.assertTrue(r.json['media_url'].startswith('http://localhost/m/'))
        self.assertEqual(r.json['status'], 'succeeded')
        self.assertEqual(self.c.post('/api/ai_studio/generate_image', json={}).status_code, 400)

    def test_webhook_route(self):
        key = b'k' * 32
        r = self.c.post('/api/ai_studio/media/jobs', json={'kind': 'video', 'preset': 'draft', 'prompt': 'x'})
        jid = r.json['job']['id']
        self.r.pred = {'id': 'pred_abc123', 'status': 'succeeded', 'output': 'http://127.0.0.1:9/out/v.mp4'}
        body = json.dumps({'id': 'pred_abc123', 'status': 'succeeded'}).encode()
        ts = str(int(time.time()))
        sig = base64.b64encode(hmac.new(key, f'msg_9.{ts}.'.encode() + body, hashlib.sha256).digest()).decode()
        headers = {'webhook-id': 'msg_9', 'webhook-timestamp': ts, 'webhook-signature': f'v1,{sig}', 'Content-Type': 'application/json'}
        with mock.patch.dict(os.environ, {'REPLICATE_WEBHOOK_SECRET': 'whsec_' + base64.b64encode(key).decode()}):
            bad = dict(headers, **{'webhook-signature': 'v1,AAAA'})
            self.assertEqual(self.c.post(f'/api/ai_studio/replicate_webhook?job={jid}', data=body, headers=bad).status_code, 401)
            self.assertEqual(FDB.ai_media_jobs.find_one({'id': jid})['status'], 'queued')
            r = self.c.post(f'/api/ai_studio/replicate_webhook?job={jid}', data=body, headers=headers)
            self.assertEqual((r.status_code, r.json['status']), (200, 'succeeded'))
            other = json.dumps({'id': 'pred_other', 'status': 'succeeded'}).encode()
            sig2 = base64.b64encode(hmac.new(key, f'msg_9.{ts}.'.encode() + other, hashlib.sha256).digest()).decode()
            r = self.c.post(f'/api/ai_studio/replicate_webhook?job={jid}', data=other, headers=dict(headers, **{'webhook-signature': f'v1,{sig2}'}))
            self.assertTrue(r.json.get('ignored'))
        self.assertEqual(FDB.ai_usage.count_documents({'job_id': jid}), 1)

    def test_scene_plan(self):
        _DEEPSEEK['reply'] = json.dumps({'title': 'Fall nails', 'caption': 'Book now #nails', 'scenes': [
            {'start': 0, 'end': 2, 'on_screen_text': 'Fall is here', 'voiceover': 'v', 'visual': 'text', 'photo_hint': ''},
            {'start': 2, 'end': 9, 'on_screen_text': 'Gel $35', 'voiceover': 'v', 'visual': 'photo', 'photo_hint': 'gel close-up'},
            {'start': 9, 'end': 12, 'on_screen_text': 'Book online', 'voiceover': 'v', 'visual': 'video', 'photo_hint': ''}]})
        r = self.c.post('/api/ai_studio/scene_plan', json={'topic': 'fall promo', 'seconds': 15, 'lang': 'en'})
        self.assertEqual(r.status_code, 200, r.json)
        sc = r.json['scenes']
        self.assertEqual(sc[0]['start'], 0)
        self.assertEqual(sc[-1]['end'], 15)
        for a, b in zip(sc, sc[1:]):
            self.assertEqual(a['end'], b['start'])
        self.assertEqual(sc[2]['visual'], 'photo')   # 'video' không hợp lệ -> photo
        self.assertEqual(_DEEPSEEK['calls'][-1]['response_format'], {'type': 'json_object'})
        self.assertIn('BUSINESS FACTS', _DEEPSEEK['calls'][-1]['messages'][1]['content'])
        self.assertEqual(self.c.post('/api/ai_studio/scene_plan', json={'topic': 'x', 'seconds': 'abc'}).status_code, 400)
        self.assertEqual(self.c.post('/api/ai_studio/scene_plan', json={'topic': 'x', 'seconds': 99}).json['seconds'], 30)
        self.assertEqual(self.c.post('/api/ai_studio/scene_plan', json={'seconds': 10}).status_code, 400)
        _DEEPSEEK['reply'] = 'not json'
        self.assertEqual(self.c.post('/api/ai_studio/scene_plan', json={'topic': 'x'}).json['code'], 'ai_bad_output')


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        _NET_GUARD.stop()
