"""Điền dữ liệu mà AI lễ tân cần cho 9 TIỆM DEMO (demo.*@bitpawdemo.com) — giờ mở cửa, sức chứa bàn / phòng, giờ nhận / trả
phòng, bảng giá dịch vụ kỹ thuật, sản phẩm xưởng, dịch vụ văn phòng, chính sách, vài câu hỏi đáp cho trang Kiến thức AI.

Chỉ điền chỗ CÒN TRỐNG (không ghi đè thứ chủ demo đã nhập), chỉ đụng đúng các tiệm demo mà scripts/ai_demo_readiness.py dùng.
Mặc định chạy thử (in ra sẽ làm gì). --apply mới ghi, và lưu bản sao để hoàn tác:
    python scripts/seed_ai_demo_data.py                 # xem trước
    python scripts/seed_ai_demo_data.py --apply         # ghi + audit-results/ai_sim/demo_seed_backup_<giờ>.json
    python scripts/seed_ai_demo_data.py --revert <file> # trả lại đúng như trước khi ghi
Không đặt địa chỉ / SĐT tiệm (đó là nội dung của chủ demo) — báo cáo sẵn sàng vẫn nhắc.
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

WEEK = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def _days(spec):
    """{'mon-fri': ('08:00','18:00'), 'sat': (...), 'sun': None} -> {'mon': [...], ...}"""
    out = {d: None for d in WEEK}
    for key, val in spec.items():
        a, _, b = key.partition('-')
        i, j = WEEK.index(a), WEEK.index(b or a)
        for d in WEEK[i:j + 1]:
            out[d] = list(val) if val else None
    return out


HOURS = {
    'spa': _days({'mon-sat': ('09:00', '20:00'), 'sun': ('10:00', '18:00')}),
    'fnb': _days({'mon-thu': ('11:00', '22:00'), 'fri-sat': ('11:00', '23:00'), 'sun': ('11:00', '21:00')}),
    'karaoke': _days({'mon-sun': ('16:00', '24:00')}),
    'hotel': _days({'mon-sun': ('00:00', '24:00')}),          # quầy lễ tân 24/7
    'retail': _days({'mon-sun': ('07:00', '23:00')}),
    'technical': _days({'mon-fri': ('08:00', '18:00'), 'sat': ('08:00', '14:00')}),
    'production': _days({'mon-fri': ('08:00', '17:00'), 'sat': ('08:00', '12:00')}),
    'office': _days({'mon-fri': ('09:00', '17:30')}),
}

INFO = {
    'spa': {'payments': 'Visa, Mastercard, Amex, Apple Pay / Google Pay and cash.',
            'cancellation_policy': 'Please give at least 24 hours notice to change or cancel a treatment.'},
    'fnb': {'payments': 'Visa, Mastercard, Amex, Apple Pay / Google Pay and cash.',
            'cancellation_policy': 'Tables are held 15 minutes past the booking time. Parties of 10 or more, please call us.'},
    'karaoke': {'payments': 'Visa, Mastercard, Apple Pay / Google Pay and cash.',
                'cancellation_policy': 'Rooms are held 15 minutes past the start time, then released.'},
    'hotel': {'payments': 'Visa, Mastercard, Amex. A card is required at check-in for incidentals.',
              'cancellation_policy': 'Free cancellation up to 48 hours before check-in.'},
    'retail': {'payments': 'Visa, Mastercard, Apple Pay / Google Pay, EBT and cash.'},
    'technical': {'payments': 'Card or cash on completion. Quotes are confirmed by the technician on site.'},
    'production': {'payments': 'Bank transfer. Bulk orders: 30% deposit, balance before shipping.'},
    'office': {'payments': 'Card or bank transfer.',
               'cancellation_policy': 'Please give 24 hours notice to move or cancel a consultation.'},
}

KNOWLEDGE = {
    'spa': [('faq', 'parking', 'Is there parking?', 'Free parking for spa guests in the lot behind the building.'),
            ('faq', 'kids', 'Do you treat children?', 'Guests under 16 need a parent or guardian present for treatments.')],
    'fnb': [('faq', 'allergies', 'Can you cater for allergies?',
             'Tell us about any allergy when you book or order — the kitchen will advise which dishes are safe. '
             'We cannot guarantee a completely nut-free kitchen.'),
            ('faq', 'kids', 'Do you have high chairs?', 'Yes, we have high chairs — mention it when you book.')],
    'karaoke': [('faq', 'groups', 'Can I bring a birthday cake?', 'Yes, you can bring your own cake for a birthday in your room.'),
                ('faq', 'kids', 'Are kids allowed?', 'Kids are welcome with an adult until 9 pm.')],
    'hotel': [('faq', 'parking', 'Is parking available?', 'Free on-site parking for hotel guests.'),
              ('faq', 'pets', 'Are pets allowed?', 'Sorry, we can only accept registered service animals.')],
    'retail': [('faq', 'delivery', 'Can I pick up an order later?',
                'Yes — ask us to hold items for pickup; the hold lasts until closing time the next business day.')],
    'technical': [('faq', 'other', 'Do you charge a call-out fee?',
                   'The diagnostic visit fee is on our price list; it is waived if you go ahead with the repair.')],
    'production': [('faq', 'other', 'What is your minimum order?', 'Our minimum order is 100 pieces per design.'),
                   ('faq', 'delivery', 'How long does production take?',
                    'Usually 2–3 weeks after the sample is approved, depending on quantity.')],
    'office': [('faq', 'other', 'Do you offer online consultations?', 'Yes — in person at our office or by video call.')],
}

FNB_TABLE_RULES = {'max_covers_per_slot': 40, 'auto_confirm': True, 'hold_minutes': 15}   # chủ duyệt 2026-10-30
KARAOKE_RULES = {'hold_minutes': 15}                     # tự xác nhận: theo công tắc chung của tiệm (chưa bật = chờ duyệt)
KARAOKE_SIZES = {'VIP Room 1': 12, 'VIP Room 2': 12, 'Pool Table 1': 4, 'Pool Table 2': 4}
HOTEL_SETTINGS = {'checkin_time': '14:00', 'checkout_time': '11:00', 'free_cancel_hours': 48, 'min_nights': 1,
                  'auto_confirm': False}                 # chờ duyệt: khách sạn có thể bán cả trên Booking.com
TECH_SERVICES = [('Diagnostic visit (any appliance)', 89), ('AC not cooling — check & recharge', 150),
                 ('Washer / dryer repair (labor, first hour)', 95), ('Electrical outlet / switch repair', 85),
                 ('Water heater service', 120)]
PRODUCTION_PRODUCTS = [('Custom printed cotton T-shirt', 'Apparel', 6.5), ('Embroidered polo shirt', 'Apparel', 11.0),
                       ('Work uniform set (shirt + pants)', 'Uniforms', 24.0), ('Fleece hoodie with logo', 'Apparel', 16.0)]
OFFICE_SERVICES = [('Initial consultation (60 min)', 'Consulting', 150.0), ('Business registration package', 'Company setup', 450.0),
                   ('Monthly bookkeeping (small business)', 'Accounting', 300.0), ('Annual tax filing (small business)', 'Tax', 600.0)]


def demo_businesses(db):
    import ai_demo_readiness as R
    out = {}
    for ind, (env, default) in R.demo_accounts().items():
        email = os.environ.get(env) or default
        u = db.users.find_one({'email': email}, {'_id': 0, 'business_id': 1})
        if not u or not u.get('business_id'):
            print(f'!! {ind}: không thấy tài khoản demo {email}')
            continue
        b = db.businesses.find_one({'id': u['business_id']}, {'_id': 0, 'id': 1, 'name': 1, 'industry_code': 1})
        code = {'nails': 'nail'}.get(str((b or {}).get('industry_code') or '').lower(), str((b or {}).get('industry_code') or '').lower())
        if not b or code != ind or not email.endswith('@bitpawdemo.com'):
            print(f'!! {ind}: {email} không phải tiệm demo đúng ngành — bỏ qua')
            continue
        out[ind] = b
    return out


def plan(db, ind, b):
    """Danh sách việc cần làm cho 1 tiệm (chỉ chỗ còn trống)."""
    bid = b['id']
    bs = db.booking_settings.find_one({'business_id': bid}, {'_id': 0}) or {}
    todo = []
    if ind in HOURS and not isinstance(bs.get('hours'), dict):
        todo.append(('hours', HOURS[ind]))
    info = bs.get('info') if isinstance(bs.get('info'), dict) else {}
    miss = {k: v for k, v in INFO.get(ind, {}).items() if not info.get(k)}
    if miss:
        todo.append(('info', miss))
    if ind == 'fnb':
        cur = bs.get('table_reservations') if isinstance(bs.get('table_reservations'), dict) else {}
        if not cur.get('max_covers_per_slot'):
            todo.append(('table_rules', FNB_TABLE_RULES))
    if ind == 'karaoke':
        cur = bs.get('karaoke_reservations') if isinstance(bs.get('karaoke_reservations'), dict) else {}
        if not cur.get('hold_minutes'):
            todo.append(('karaoke_rules', KARAOKE_RULES))
        rooms = [r for r in db.karaoke_rooms.find({'business_id': bid}, {'_id': 0, 'id': 1, 'name': 1, 'max_guests': 1, 'capacity': 1})
                 if r.get('name') in KARAOKE_SIZES and not (r.get('max_guests') or r.get('capacity'))]
        if rooms:
            todo.append(('karaoke_sizes', [(r['id'], r['name'], KARAOKE_SIZES[r['name']]) for r in rooms]))
    if ind == 'hotel' and not isinstance(bs.get('hotel'), dict):
        todo.append(('hotel_settings', HOTEL_SETTINGS))
    if ind == 'technical' and not db.dichvu.count_documents({'business_id': bid}):
        todo.append(('tech_services', TECH_SERVICES))
    if ind == 'production' and not db.products.count_documents({'business_id': bid, 'is_active': {'$in': [1, True]}}):
        todo.append(('products', PRODUCTION_PRODUCTS))
    if ind == 'office' and not db.products.count_documents({'business_id': bid, 'is_active': {'$in': [1, True]}}):
        todo.append(('products', OFFICE_SERVICES))
    if ind in KNOWLEDGE and not db.ai_knowledge.count_documents({'business_id': bid}):
        todo.append(('knowledge', KNOWLEDGE[ind]))
    return bs, todo


def apply(db, ind, b, bs, todo, backup):
    import ai_knowledge
    import reservations_core
    import reservations_hotel
    from mongo_client import next_mongo_id
    bid = b['id']
    rec = backup.setdefault(bid, {'industry': ind, 'booking_settings_before': bs or None, 'inserted': {}, 'karaoke_sizes': []})
    now = datetime.now().isoformat()
    for kind, val in todo:
        if kind == 'hours':
            db.booking_settings.update_one({'business_id': bid}, {'$set': {'hours': val, 'updated_at': now}}, upsert=True)
        elif kind == 'info':
            db.booking_settings.update_one({'business_id': bid}, {'$set': {**{f'info.{k}': v for k, v in val.items()},
                                                                         'updated_at': now}}, upsert=True)
        elif kind == 'table_rules':
            reservations_core.save_reservation_settings(bid, 'table', val)
        elif kind == 'karaoke_rules':
            reservations_core.save_reservation_settings(bid, 'karaoke', val)
        elif kind == 'karaoke_sizes':
            for rid, _name, size in val:
                db.karaoke_rooms.update_one({'id': rid, 'business_id': bid}, {'$set': {'max_guests': size}})
                rec['karaoke_sizes'].append(rid)
        elif kind == 'hotel_settings':
            reservations_hotel.save_hotel_settings(bid, val)
        elif kind == 'tech_services':
            ids = []
            for name, price in val:
                sid = next_mongo_id('dichvu')
                db.dichvu.insert_one({'id': sid, 'business_id': bid, 'ten_dich_vu': name, 'gia_dich_vu': price, 'tien_tua': 0})
                ids.append(sid)
            rec['inserted']['dichvu'] = ids
        elif kind == 'products':
            ids = []
            for name, cat, price in val:
                pid = next_mongo_id('products')
                db.products.insert_one({'id': pid, 'name': name, 'category': cat, 'channel_type': 'retail', 'stock': 0,
                                        'price': float(price), 'image': None, 'barcode': None, 'is_active': 1, 'business_id': bid})
                ids.append(pid)
            rec['inserted']['products'] = ids
        elif kind == 'knowledge':
            ids = []
            for k, topic, q, a in val:
                ids.append(ai_knowledge.create(bid, {'kind': k, 'topic': topic, 'question': q, 'answer': a},
                                               user='seed_ai_demo_data')['id'])
            rec['inserted']['ai_knowledge'] = ids


def revert(db, path):
    data = json.load(open(path, encoding='utf-8'))
    for bid, rec in data.items():
        before = rec.get('booking_settings_before')
        if before:
            db.booking_settings.replace_one({'business_id': bid}, before, upsert=True)
        else:
            db.booking_settings.delete_one({'business_id': bid})
        for rid in rec.get('karaoke_sizes') or []:
            db.karaoke_rooms.update_one({'id': rid, 'business_id': bid}, {'$unset': {'max_guests': ''}})
        ins = rec.get('inserted') or {}
        if ins.get('dichvu'):
            db.dichvu.delete_many({'business_id': bid, 'id': {'$in': ins['dichvu']}})
        if ins.get('products'):
            db.products.delete_many({'business_id': bid, 'id': {'$in': ins['products']}})
        if ins.get('ai_knowledge'):
            db.ai_knowledge.delete_many({'business_id': bid, 'id': {'$in': ins['ai_knowledge']}})
        print('reverted', rec.get('industry'), bid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--revert')
    ap.add_argument('--industry', default='')
    a = ap.parse_args()
    from mongo_client import db
    if a.revert:
        revert(db, a.revert)
        return
    only = {x.strip() for x in a.industry.split(',') if x.strip()}
    backup = {}
    for ind, b in demo_businesses(db).items():
        if only and ind not in only:
            continue
        bs, todo = plan(db, ind, b)
        print(f"== {ind:<10} {b['name']}  ({b['id']})")
        for kind, val in todo:
            n = len(val) if isinstance(val, (list, dict)) else 1
            print(f'   {"GHI" if a.apply else "sẽ ghi"} {kind} ({n})')
        if not todo:
            print('   đủ rồi — không đụng')
        if a.apply and todo:
            apply(db, ind, b, bs, todo, backup)
    if a.apply and backup:
        out = os.path.join(ROOT, 'audit-results', 'ai_sim', f"demo_seed_backup_{datetime.now():%Y%m%d_%H%M%S}.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(backup, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
        print('bản sao để hoàn tác:', out)


if __name__ == '__main__':
    main()
