# -*- coding: utf-8 -*-
"""READ-ONLY report — "ghost bookings": db.appointments rows the customer AI created for businesses whose industry has
NO real appointment pack (anything other than nail / spa: fnb, karaoke, hotel, retail, technical, production, office).

Why: until Phase 0 the inbox/SMS/booking-chat AI gave every industry the nail booking tools, so restaurants, karaoke bars,
hotels and shops could get db.appointments rows (and a "confirmed" message to the customer) that their own reservation
screens (/reservations, /karaoke/reservations, /hotel/reservations) never show.

How AI bookings are marked: ai_function_tools.book_appointment -> booking_engine.book_appointment(source='ai_bot');
since Phase 0 also ai_conversation_id / ai_channel. AI cancellations: cancelled_by='customer_ai_chat'.

THIS SCRIPT NEVER WRITES. Every collection is wrapped in a read-only proxy (find / find_one / count_documents only).
It reads the database configured in .env through mongo_client (that is PRODUCTION) — run it only when the owner asks.
It prints counts per business (no customer names or phone numbers). Cleanup needs the owner's explicit approval and a
separate, reviewed script.

Run:  python scripts/report_ai_ghost_bookings.py            (table)
      python scripts/report_ai_ghost_bookings.py --json     (machine-readable)
      python scripts/report_ai_ghost_bookings.py --since 2026-09-01
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BOOKING_PACK_INDUSTRIES = ('nail', 'spa')  # same list as ai_function_tools.BOOKING_PACK_INDUSTRIES
AI_CREATED = {'$or': [{'source': 'ai_bot'}, {'ai_conversation_id': {'$exists': True}}]}
_READ_METHODS = ('find', 'find_one', 'count_documents')


class ReadOnlyCollection:
    """Only read methods pass through; anything else raises before touching the database."""

    def __init__(self, coll):
        self._coll = coll

    def __getattr__(self, name):
        if name not in _READ_METHODS:
            raise PermissionError(f"report_ai_ghost_bookings is read-only: '{name}' is not allowed")
        return getattr(self._coll, name)


class ReadOnlyDB:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return ReadOnlyCollection(getattr(self._db, name))

    def __getitem__(self, name):
        return ReadOnlyCollection(self._db[name])


def _industry_of(db, business_ids):
    """{business_id: (name, industry)} — db.businesses.industry_code, fallback system_settings business_mode_<id>."""
    out = {}
    for b in db.businesses.find({'id': {'$in': list(business_ids)}}, {'_id': 0, 'id': 1, 'name': 1, 'industry_code': 1}):
        code = str(b.get('industry_code') or '').strip().lower()
        out[b.get('id')] = (b.get('name') or '', {'nails': 'nail'}.get(code, code))
    for bid in business_ids:
        name, code = out.get(bid, ('', ''))
        if not code:
            mode = db.system_settings.find_one({'key': f'business_mode_{bid}'}, {'_id': 0, 'value': 1}) or {}
            code = str(mode.get('value') or '').strip().lower()
            code = {'nails': 'nail'}.get(code, code)
        out[bid] = (name, code or 'unknown')
    return out


def collect(db, since=None, now=None):
    """Rows for businesses outside nail/spa that have AI-created appointments, biggest first. `db` is wrapped read-only."""
    db = db if isinstance(db, ReadOnlyDB) else ReadOnlyDB(db)
    now_s = (now or datetime.now()).strftime('%Y-%m-%dT%H:%M')
    query = dict(AI_CREATED)
    if since:
        query = {'$and': [AI_CREATED, {'created_at': {'$gte': since}}]}
    per_biz = {}
    for a in db.appointments.find(query, {'_id': 0, 'business_id': 1, 'status': 1, 'book_time': 1, 'created_at': 1,
                                          'ai_channel': 1}):
        bid = a.get('business_id')
        r = per_biz.setdefault(bid, {'business_id': bid, 'ai_created': 0, 'status': Counter(), 'channels': Counter(),
                                     'upcoming_active': 0, 'first_created': None, 'last_created': None})
        r['ai_created'] += 1
        st = a.get('status') or 'unknown'
        r['status'][st] += 1
        r['channels'][a.get('ai_channel') or 'not recorded'] += 1
        if str(a.get('book_time') or '') >= now_s and st not in ('cancelled', 'canceled'):
            r['upcoming_active'] += 1
        c = str(a.get('created_at') or '')
        if c:
            r['first_created'] = min(r['first_created'] or c, c)
            r['last_created'] = max(r['last_created'] or c, c)
    if not per_biz:
        return []
    info = _industry_of(db, per_biz.keys())
    rows = []
    for bid, r in per_biz.items():
        name, industry = info.get(bid, ('', 'unknown'))
        if industry in BOOKING_PACK_INDUSTRIES:
            continue
        r.update(business_name=name, industry=industry, status=dict(r['status']), channels=dict(r['channels']),
                 ai_cancelled=db.appointments.count_documents({'business_id': bid, 'cancelled_by': 'customer_ai_chat'}))
        rows.append(r)
    rows.sort(key=lambda x: (-x['ai_created'], str(x['business_id'])))
    return rows


def render(rows):
    if not rows:
        return "No AI-created appointments found for businesses outside nail/spa. Nothing to review."
    lines = ["AI-created appointments for businesses WITHOUT an appointment pack (read-only report — nothing was changed)", ""]
    hdr = f"{'business_id':<28} {'industry':<11} {'AI created':>10} {'upcoming':>9} {'AI cancelled':>12}  status / channels / first..last created"
    lines += [hdr, '-' * len(hdr)]
    for r in rows:
        st = ', '.join(f"{k}={v}" for k, v in sorted(r['status'].items()))
        ch = ', '.join(f"{k}={v}" for k, v in sorted(r['channels'].items()))
        lines.append(f"{str(r['business_id'])[:28]:<28} {r['industry']:<11} {r['ai_created']:>10} {r['upcoming_active']:>9} "
                     f"{r['ai_cancelled']:>12}  {st} | {ch} | {(r['first_created'] or '')[:10]}..{(r['last_created'] or '')[:10]}")
        if r.get('business_name'):
            lines.append(f"{'':<28} name: {r['business_name']}")
    lines += ["", f"Businesses: {len(rows)} · AI-created appointments: {sum(r['ai_created'] for r in rows)} · "
                  f"still upcoming and not cancelled: {sum(r['upcoming_active'] for r in rows)}",
              "These customers may believe they have a booking the business never saw. Contact/cleanup needs the owner's approval."]
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', action='store_true', help='print JSON instead of a table')
    ap.add_argument('--since', help='only appointments created on/after this ISO date (YYYY-MM-DD)')
    args = ap.parse_args(argv)
    try:  # tên tiệm tiếng Việt trên console Windows (cp1252) không được làm sập báo cáo
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    from mongo_client import db, MONGO_STATUS  # noqa: E402 — imported here so tests can call collect() with a fake db
    if db is None or MONGO_STATUS != 'CONNECTED':
        print(f"MongoDB not connected ({MONGO_STATUS}) — nothing read.")
        return 2
    rows = collect(db, since=args.since)
    print(json.dumps(rows, ensure_ascii=False, indent=1, default=str) if args.json else render(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
