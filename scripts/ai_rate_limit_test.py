"""Giới hạn tần suất riêng của route AI tốn tiền có thật sự chặn không (lỗi 25/10: gắn limiter mà bỏ hàm bọc -> mất cả giới
hạn riêng lẫn mặc định). KHÔNG ghi DB, KHÔNG gọi AI: gửi yêu cầu sai kind (400 trước khi tới Replicate) để chỉ đo limiter.
    python scripts/ai_rate_limit_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod  # noqa: E402
import plans  # noqa: E402

app = appmod.app
app.config['TESTING'] = True
appmod.csrf.protect = lambda: None
plans.business_plan = lambda _db, bid, ttl=60: 'empire'
db = appmod.db
EMAIL = 'demo.nails.au.006758@bitpawdemo.com'
user = db.users.find_one({'email': EMAIL}, {'_id': 0, 'id': 1, 'business_id': 1, 'session_ver': 1})
c = app.test_client()
with c.session_transaction() as s:
    s['user_id'] = user['id']; s['business_id'] = user.get('business_id') or user['id']; s['role'] = 'admin'
    s['business_mode'] = 'nail'; s['user_email'] = EMAIL; s['sv'] = int(user.get('session_ver') or 0)

codes = [c.post('/api/ai_studio/media/jobs', json={'kind': 'nope'}, environ_base={'REMOTE_ADDR': '10.9.8.7'}).status_code
         for _ in range(8)]
ok = codes[:6] == [400] * 6 and 429 in codes[6:]
print(('PASS' if ok else 'FAIL') + f" tạo ảnh/video AI: 6 lần/phút rồi chặn 429 — {codes}")
codes2 = [c.post('/api/social/review', json={}, environ_base={'REMOTE_ADDR': '10.9.8.6'}).status_code for _ in range(2)]
print(('PASS' if codes2[0] != 429 else 'FAIL') + f" route khác vẫn chạy bình thường — {codes2}")
sys.exit(0 if ok else 1)
