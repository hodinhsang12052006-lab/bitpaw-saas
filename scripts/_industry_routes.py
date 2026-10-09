"""In JSON cho scripts/industry_isolation_audit.mjs: với mỗi ngành, các TRANG (GET, không tham số) và API
(GET, không tham số) riêng của ngành đó theo industry_access.ENDPOINT_INDUSTRIES — để test thử mở chéo từ
8 ngành còn lại. Dòng JSON là dòng cuối stdout."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import industry_access as ia  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == 'bids':
    # business_id của từng tài khoản demo: python scripts/_industry_routes.py bids '{"nail": "email", ...}'
    from mongo_client import db
    out = {}
    for ind, email in json.loads(sys.argv[2]).items():
        u = db.users.find_one({'email': email}, {'id': 1, 'business_id': 1, '_id': 0}) or {}
        out[ind] = u.get('business_id') or u.get('id')
    print(json.dumps(out))
    sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == 'tables':
    # tiệm KHÔNG phải F&B mà vẫn có bàn ăn (dining_tables) -> {business_id: [ngành, số bàn]}
    from mongo_client import db
    out = {}
    for b in db.dining_tables.distinct('business_id'):
        d = db.system_settings.find_one({'key': f'business_mode_{b}'}, {'value': 1, '_id': 0}) or {}
        mode = (d.get('value') or '').lower()
        if mode != 'fnb':
            out[str(b)] = [mode, db.dining_tables.count_documents({'business_id': b})]
    print(json.dumps(out))
    sys.exit(0)

from app import app  # noqa: E402

pages, apis = {i: [] for i in ia.INDUSTRIES}, {i: [] for i in ia.INDUSTRIES}
for rule in app.url_map.iter_rules():
    allowed = ia.ENDPOINT_INDUSTRIES.get(rule.endpoint)
    if not allowed or rule.arguments or 'GET' not in rule.methods or rule.rule.startswith('/api/stream'):
        continue
    for ind in allowed:
        (apis if rule.rule.startswith('/api/') else pages)[ind].append(rule.rule)
# chấm công riêng từng ngành qua /chamcong/<slug>
for ind, slug in ia.CHAMCONG_SLUG.items():
    if f'/chamcong/{slug}' not in pages[ind]:
        pages[ind].append(f'/chamcong/{slug}')
print(json.dumps({'pages': pages, 'apis': apis, 'home': ia.INDUSTRY_HOME, 'pos': ia.INDUSTRY_POS}))
