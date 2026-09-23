"""Small stdout-JSON helper for nail_business_cycle_e2e.mjs — queries MongoDB directly via the
app's own mongo_client.py (pymongo), so the E2E script can prove data really landed in the
database (not just trust the API's own success response) without adding a Node MongoDB driver
dependency to package.json for a single test script."""
import sys
import os
import json

# `python scripts/_e2e_db_helper.py` sets sys.path[0] to scripts/, not the repo root, so the
# top-level mongo_client.py module (repo root) isn't importable by default — add the repo root
# explicitly rather than relying on the caller's cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db


def sum_chamcong(business_id, ma_nv, ngay_cham):
    commission = 0.0
    tip_cash = 0.0
    tip_card = 0.0
    for d in db.chamcong.find({'business_id': business_id, 'ma_nv': ma_nv, 'ngay_cham': ngay_cham}):
        commission += d.get('tien_tua') or 0
        if d.get('tien_tips_cash') is not None or d.get('tien_tips_card') is not None:
            tip_cash += d.get('tien_tips_cash') or 0
            tip_card += d.get('tien_tips_card') or 0
        else:
            tip_cash += d.get('tien_tips') or 0
    return {'commission': round(commission, 2), 'tipCash': round(tip_cash, 2), 'tipCard': round(tip_card, 2)}


def get_order(order_id, business_id):
    doc = db.orders.find_one({'id': int(order_id), 'business_id': business_id}, {'_id': 0})
    return doc


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'sum_chamcong':
        result = sum_chamcong(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == 'get_order':
        result = get_order(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f'Unknown mode: {mode}')
    print(json.dumps(result))
