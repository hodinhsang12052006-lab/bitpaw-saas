"""Chuyển 7 tiệm DEMO (F&B, Karaoke, Khách sạn, Bán lẻ, Sản xuất, Kỹ thuật, Văn phòng) sang khu vực Mỹ / USD (25/10/2026).

Vì sao: landing nhắm khách Mỹ/Úc; link "xem demo" (vd menu QR) và ảnh chụp phần mềm trên landing lấy từ các tiệm demo này,
mà chúng đang để giá VND ("Phở 65.000₫") — khách Mỹ nhìn vào thấy không phải sản phẩm cho mình.
Giá đổi theo mức THỰC TẾ ở Mỹ cho từng ngành (không theo tỉ giá): F&B/Karaoke/Khách sạn ÷4000 (Phở $16.25, phòng $162.50/đêm),
bán lẻ ÷8000 (Coca 6 lon $5.75), lương ÷1500 (30.000₫/giờ -> $20/giờ). Tên phòng/bàn/món/chức vụ sang tiếng Anh, SĐT khách -> số Mỹ
dải 555-01xx (dải dành cho ví dụ), toạ độ thợ/việc -> Garden Grove, CA (Little Saigon).

    python scripts/showcase_demo_usd.py                 # chạy thử: in ra sẽ đổi gì
    python scripts/showcase_demo_usd.py --apply BACKUP  # sao lưu toàn bộ dữ liệu 7 tiệm vào file BACKUP (json) rồi mới đổi
Chỉ đụng các tài khoản @bitpawdemo.com liệt kê dưới đây.
"""
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_client import db  # noqa: E402

TENANTS = {  # email -> (ngành, hệ số giá, đổi tên doanh nghiệp)
    'demo.fnb.343602@bitpawdemo.com': ('fnb', 4000, None),
    'demo.karaoke.071443@bitpawdemo.com': ('karaoke', 4000, 'Neon Nights Karaoke & Billiards'),
    'demo.hotel.071443@bitpawdemo.com': ('hotel', 4000, None),
    'demo.retail.596348@bitpawdemo.com': ('retail', 8000, None),
    'demo.production.393328@bitpawdemo.com': ('production', 4000, None),
    'demo.technical.393328@bitpawdemo.com': ('technical', 4000, None),
    'demo.office.784966@bitpawdemo.com': ('office', 4000, 'Vietstar Consulting LLC'),
}
WAGE_FACTOR = 1500
PRICE_FIELDS = {'products': ['price', 'cost_price'], 'hotel_rooms': ['price_per_night'], 'karaoke_rooms': ['price_per_hour']}
MONEY_FIELDS = {
    'orders': ['total_amount', 'metadata.subtotal', 'metadata.tax_amount', 'metadata.room_total', 'metadata.extra_charges[].amount',
               'metadata.extra_charges_total', 'metadata.parts[].unit_price', 'metadata.parts[].line_total', 'metadata.refunded_amount',
               'metadata.tip_amount', 'metadata.discount_amount'],
    'order_items': ['total_price', 'price'],
    'transactions': ['amount'],
    'payment_transactions': ['amount', 'tip_amount', 'split_cash_amount', 'split_card_amount'],
    'hotel_room_charges': ['amount'],
    'expenses': ['amount'],
    'customers': ['total_spent'],
}
WAGE_FIELDS = {'employees': ['luong_gio', 'luong_cb', 'phu_cap'], 'chamcong': ['tien_tua', 'tien_tips', 'phu_cap']}
PHONE_FIELDS = {'customers': ['phone'], 'orders': ['customer_phone'], 'order_items': ['customer_phone'],
                'table_reservations': ['customer_phone'], 'karaoke_room_reservations': ['customer_phone'], 'hotel_reservations': ['guest_phone']}
NAMES = {
    'products': {
        'Phở Bò Tái': 'Rare Beef Phở', 'Cơm Tấm Sườn Bì Chả': 'Broken Rice Combo (Cơm Tấm)', 'Gỏi Cuốn Tôm Thịt (4 cuốn)': 'Fresh Spring Rolls (4)',
        'Lẩu Thái Hải Sản (Nồi lớn)': 'Thai Seafood Hot Pot (large)', 'Bia Sài Gòn (lon)': 'Saigon Beer (can)',
        'Rượu Vang Đỏ Đà Lạt (chai)': 'Dalat Red Wine (bottle)', 'Trà Đá / Trà Đường': 'Iced Tea', 'Nước Ép Cam Tươi': 'Fresh Orange Juice',
        'Cà Phê Sữa Đá': 'Vietnamese Iced Coffee', 'Bia Tiger (lon)': 'Tiger Beer (can)', 'Nước ngọt Pepsi': 'Pepsi',
        'Trái cây thập cẩm': 'Fruit Platter', 'Snack khô mực': 'Dried Squid Snack', 'Combo bia 1 thùng': 'Beer Bucket (24 cans)',
        'Phí Giờ Karaoke': 'Karaoke Room (per hour)', 'Coca-Cola 330ml (lốc 6)': 'Coca-Cola 12oz (6-pack)',
        'Mì tôm Hảo Hảo (thùng 30)': 'Hao Hao Instant Noodles (case of 30)', 'Bánh quy Oreo': 'Oreo Cookies',
        'Sữa tươi Vinamilk 1L': 'Vinamilk Fresh Milk 1L', 'Nước rửa chén Sunlight 750ml': 'Sunlight Dish Soap 25oz',
        'Giấy vệ sinh Bless You (lốc 10)': 'Toilet Paper (10 rolls)', 'Cà phê hoà tan G7 (hộp 20)': 'G7 Instant Coffee (20 sticks)',
        'Kem đánh răng P/S': 'P/S Toothpaste'},
    'karaoke_rooms': {'Phòng VIP 1': 'VIP Room 1', 'Phòng VIP 2': 'VIP Room 2', 'Phòng Đôi (2-4 người)': 'Couple Room (2–4)',
                      'Phòng Gia Đình (6-8 người)': 'Family Room (6–8)', 'Phòng Đại Sảnh (10-15 người)': 'Party Hall (10–15)',
                      'Bàn Bida 1': 'Pool Table 1', 'Bàn Bida 2': 'Pool Table 2'},
    'raw_materials': {'Vải Cotton': 'Cotton Fabric'},
    'expenses': {'Tiền điện tháng': 'Monthly electricity', 'Nhập hàng đồ uống': 'Drinks restock', 'Tiền thuê mặt bằng': 'Store rent',
                 'Sửa máy lạnh': 'A/C repair', 'Nhập hàng bánh kẹo': 'Snacks restock'},
}
TITLES = {'Chủ quán': 'Owner', 'Phục vụ': 'Server', 'Quản lý': 'Manager', 'Thu ngân': 'Cashier', 'Đầu bếp chính': 'Head Chef',
          'Nhân viên kỹ thuật âm thanh': 'Sound Technician', 'Nhân viên phục vụ': 'Server', 'Bảo vệ': 'Security',
          'Lễ tân': 'Front Desk', 'Nhân viên buồng phòng': 'Housekeeping', 'Quản lý khách sạn': 'Hotel Manager',
          'Chủ cửa hàng': 'Store Owner', 'Nhân viên bán hàng': 'Sales Associate', 'Nhân viên kho': 'Stock Clerk',
          'Công nhân cắt': 'Cutter', 'Công nhân may': 'Sewing Operator', 'Công nhân đóng gói': 'Packer', 'Kiểm hàng (QC)': 'QC Inspector',
          'Quản đốc xưởng': 'Floor Supervisor', 'Tổ trưởng tổ may': 'Sewing Team Lead', 'Kỹ thuật viên bảo trì': 'Maintenance Tech',
          'Kỹ thuật viên mạng/IT': 'IT / Network Tech', 'Kỹ thuật viên điện lạnh': 'HVAC Tech', 'Kỹ thuật viên điện nước': 'Plumbing & Electrical Tech',
          'Trưởng nhóm kỹ thuật': 'Lead Technician', 'Chuyên viên Marketing': 'Marketing Specialist', 'Giám đốc': 'Director',
          'Kế toán trưởng': 'Chief Accountant', 'Nhân viên Hành chính': 'Office Administrator', 'Nhân viên Kinh doanh': 'Sales Executive',
          'Trưởng phòng Nhân sự': 'HR Manager'}
US_ANCHOR = (33.7743, -117.9378)   # Garden Grove, CA (Little Saigon)
COLLECTIONS = sorted(set(PRICE_FIELDS) | set(MONEY_FIELDS) | set(WAGE_FIELDS) | set(PHONE_FIELDS) |
                     {'dining_tables', 'kitchen_orders', 'raw_materials', 'tasks', 'businesses', 'employees'})


def get_paths(doc, path):
    """[(container, key)] cho 'a.b' / 'a[].b'."""
    parts = path.split('.')
    nodes = [doc]
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        arr = p.endswith('[]')
        key = p[:-2] if arr else p
        nxt = []
        for n in nodes:
            if not isinstance(n, dict) or key not in n:
                continue
            if last and not arr:
                nxt.append((n, key))
            elif arr and isinstance(n[key], list):
                nxt.extend(x for x in n[key] if isinstance(x, dict))
            elif isinstance(n[key], dict):
                nxt.append(n[key])
        nodes = nxt
    return nodes


def q(v, step):
    return round(round(v / step) * step, 2)


def main():
    apply = '--apply' in sys.argv
    backup_path = sys.argv[sys.argv.index('--apply') + 1] if apply else None
    plan = defaultdict(int)
    backup = {}
    phone_map = {}
    for email, (ind, factor, new_name) in TENANTS.items():
        u = db.users.find_one({'email': email}, {'_id': 0, 'id': 1})
        if not u:
            print('missing', email)
            continue
        bid = u['id']
        biz = db.businesses.find_one({'id': bid}, {'_id': 0})
        if (biz or {}).get('currency') == 'USD':
            print(ind, 'already USD — skip')
            continue
        backup[bid] = {c: list(db[c].find({'id': bid} if c == 'businesses' else {'business_id': bid}, {'_id': 0})) for c in COLLECTIONS}
        ops = []   # (collection, filter, $set)
        ops.append(('businesses', {'id': bid}, {'country': 'US', 'currency': 'USD', **({'name': new_name} if new_name else {})}))
        # khác: dọn vật tư rác của bài test cũ
        junk = db.raw_materials.count_documents({'business_id': bid, 'name': {'$regex': '^QA Audit'}})
        if junk:
            plan['raw_materials QA Audit junk deleted'] += junk
        coords = [(e.get('toa_do_lat'), e.get('toa_do_lng')) for e in backup[bid]['employees'] if e.get('toa_do_lat')]
        coords += [(t.get('lat'), t.get('lng')) for t in backup[bid]['tasks'] if t.get('lat')]
        base = (sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)) if coords else None
        for coll in COLLECTIONS:
            if coll == 'businesses':
                continue
            for d in backup[bid][coll]:
                sets = {}
                work = json.loads(json.dumps(d, default=str))
                for path in PRICE_FIELDS.get(coll, []):
                    for cont, k in get_paths(work, path):
                        if isinstance(cont[k], (int, float)) and cont[k]:
                            cont[k] = q(cont[k] / factor, 0.25)
                for path in MONEY_FIELDS.get(coll, []):
                    for cont, k in get_paths(work, path):
                        if isinstance(cont[k], (int, float)) and cont[k]:
                            cont[k] = round(cont[k] / factor, 2)
                for path in WAGE_FIELDS.get(coll, []):
                    for cont, k in get_paths(work, path):
                        if isinstance(cont[k], (int, float)) and cont[k]:
                            cont[k] = q(cont[k] / WAGE_FACTOR, 0.25) if k == 'luong_gio' else round(cont[k] / WAGE_FACTOR, 2)
                for path in PHONE_FIELDS.get(coll, []):
                    for cont, k in get_paths(work, path):
                        ph = cont[k]
                        if isinstance(ph, str) and re.fullmatch(r'0\d{8,10}', ph.strip()):
                            if ph not in phone_map:
                                phone_map[ph] = f'(714) 555-01{len(phone_map) % 100:02d}'
                            cont[k] = phone_map[ph]
                if coll == 'payment_transactions' and work.get('currency') == 'VND':
                    work['currency'] = 'USD'
                for f, tbl in (('name', NAMES.get(coll, {})), ('description', NAMES.get(coll, {}))):
                    if work.get(f) in tbl:
                        work[f] = tbl[work[f]]
                if coll == 'employees' and work.get('chuc_vu') in TITLES:
                    work['chuc_vu'] = TITLES[work['chuc_vu']]
                if coll in ('dining_tables', 'kitchen_orders'):
                    for f in ('name', 'table_name'):
                        if isinstance(work.get(f), str) and work[f].startswith('Bàn '):
                            work[f] = 'Table ' + work[f][4:]
                if base and coll == 'employees' and work.get('toa_do_lat'):
                    work['toa_do_lat'] = round(US_ANCHOR[0] + (work['toa_do_lat'] - base[0]), 6)
                    work['toa_do_lng'] = round(US_ANCHOR[1] + (work['toa_do_lng'] - base[1]), 6)
                if base and coll == 'tasks' and work.get('lat'):
                    work['lat'] = round(US_ANCHOR[0] + (work['lat'] - base[0]), 6)
                    work['lng'] = round(US_ANCHOR[1] + (work['lng'] - base[1]), 6)
                for k in work:
                    if work[k] != json.loads(json.dumps(d.get(k), default=str)):
                        sets[k] = work[k]
                if sets:
                    plan[f'{ind}.{coll}'] += 1
                    ident = {'id': d['id']} if 'id' in d else {k: d[k] for k in ('business_id', 'ma_nv', 'ngay_cham') if k in d}
                    ops.append((coll, {**ident, 'business_id': bid}, sets))
        if apply:
            with open(backup_path, 'w', encoding='utf-8') as fh:   # sao lưu TRƯỚC khi ghi
                json.dump(backup, fh, ensure_ascii=False, default=str)
            for coll, flt, sets in ops:
                db[coll].update_one(flt, {'$set': sets})
            db.raw_materials.delete_many({'business_id': bid, 'name': {'$regex': '^QA Audit'}})
        sample = [o for o in ops if o[0] == 'products'][:2]
        print(ind, 'ops', len(ops), 'sample', [(s[2].get('name'), s[2].get('price')) for s in sample])
    if apply:
        with open(backup_path, 'w', encoding='utf-8') as fh:
            json.dump(backup, fh, ensure_ascii=False, default=str)
        print('backup ->', backup_path)
    for k, v in sorted(plan.items()):
        print(f'  {k}: {v}')
    print('APPLIED' if apply else 'DRY RUN')


if __name__ == '__main__':
    main()
