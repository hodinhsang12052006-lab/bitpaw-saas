"""Mô phỏng 1 tiệm dùng CHUNG 1 IP (Wi-Fi tiệm): đăng nhập chủ tiệm rồi 60 điện thoại thợ cùng tải lại "My earnings"
(/api/hr/chamcong) + tuỳ chọn các lượt nối lại SSE (/api/stream/*, mỗi luồng sống 25s rồi tự nối lại). Báo request thứ mấy bắt đầu bị 429.
    python scripts/_salon_rate_limit_check.py <email> <password> [số_request]      (CHỈ server local 127.0.0.1:5001)
"""
import re
import sys

import requests

sys.stdout.reconfigure(encoding='utf-8')
B = 'http://127.0.0.1:5001'
email, pw = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 1300
MODE = sys.argv[4] if len(sys.argv) > 4 else ''   # '' | sse (1/3 là SSE) | sseonly
s = requests.Session()
r = s.get(B + '/login')
for c in s.cookies:
    c.secure = False
tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
s.post(B + '/login', data={'email': email, 'password': pw, 'csrf_token': tok}, allow_redirects=False)
for c in s.cookies:
    c.secure = False

first_429 = None
counts = {}
for i in range(1, n + 1):
    if MODE == 'sseonly' or (MODE == 'sse' and i % 3 == 0):
        # 1 lượt nối lại SSE: mở rồi đóng ngay (đủ để limiter đếm request)
        rr = s.get(B + '/api/stream/payroll', stream=True, timeout=10)
        kind = 'sse'
        rr.close()
    else:
        rr = s.get(B + '/api/hr/chamcong?ma_nv=QS%03d&limit=1' % (i % 60 + 1), timeout=30)
        kind = 'api'
    counts[(kind, rr.status_code)] = counts.get((kind, rr.status_code), 0) + 1
    if rr.status_code == 429 and first_429 is None:
        first_429 = i
print({'requests': n, 'first_429_at': first_429, 'status': {f'{k[0]}:{k[1]}': v for k, v in counts.items()}})
