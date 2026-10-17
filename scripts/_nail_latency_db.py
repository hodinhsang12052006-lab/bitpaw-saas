"""stdout-JSON helper cho scripts/nail_customer_experience_latency.mjs — đối soát DB thật và dọn sạch
dữ liệu test (dòng JSON luôn là dòng CUỐI của stdout).

    python scripts/_nail_latency_db.py bot <business_id> <phone>        # hội thoại khách đã lưu chưa
    python scripts/_nail_latency_db.py appt <business_id> <phone>       # lịch hẹn AI đặt cho khách
    python scripts/_nail_latency_db.py cleanup <business_id> <token> <phone> [<phone>...]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo_client import db  # noqa: E402


def bot(bid, phone):
    cid = f"{bid}:{phone}"
    docs = list(db.bot_messages.find({'customer_id': cid}, {'_id': 0, 'sender_type': 1, 'content': 1}))
    return {'customer': bool(db.bot_customers.find_one({'id': cid}, {'_id': 1})),
            'count': len(docs), 'senderTypes': [d.get('sender_type') for d in docs]}


def appt(bid, phone):
    docs = list(db.appointments.find({'business_id': bid, 'customer_phone': phone},
                                     {'_id': 0, 'id': 1, 'book_time': 1, 'service_name': 1, 'source': 1, 'status': 1}))
    return {'count': len(docs), 'appointments': docs}


def cleanup(bid, token, phones):
    cids = [f"{bid}:{p}" for p in phones]
    out = {
        'bot_messages': db.bot_messages.delete_many({'business_id': bid, 'customer_id': {'$in': cids}}).deleted_count,
        'bot_customers': db.bot_customers.delete_many({'business_id': bid, 'id': {'$in': cids}}).deleted_count,
        'chat_messages': db.chat_messages.delete_many(
            {'business_id': bid, 'content': {'$regex': re.escape(token)}}).deleted_count,
        'appointments': db.appointments.delete_many(
            {'business_id': bid, '$or': [{'customer_phone': {'$in': phones}}, {'phone': {'$in': phones}}]}).deleted_count,
    }
    return out


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'bot':
        res = bot(sys.argv[2], sys.argv[3])
    elif mode == 'appt':
        res = appt(sys.argv[2], sys.argv[3])
    elif mode == 'cleanup':
        res = cleanup(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        res = {'error': 'unknown mode'}
    print(json.dumps(res, ensure_ascii=False, default=str))
