"""Tạo / dọn 1 tài khoản chủ tiệm tạm cho scripts/store_compliance_e2e.mjs (luồng Xoá tài khoản).

Cách chạy (từ thư mục gốc dự án, server local đang chạy):
    python scripts/store_test_account.py create <file.json>
    ACC=<file.json> OUT=<thư mục ảnh> node scripts/store_compliance_e2e.mjs
    python scripts/store_test_account.py cleanup <file.json>
Mật khẩu sinh ngẫu nhiên, chỉ ghi vào <file.json> (đặt ngoài repo)."""
import json
import secrets
import sys
import uuid
from datetime import datetime

import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from mongo_client import db  # noqa: E402

out = sys.argv[2]
if sys.argv[1] == 'create':
    uid = str(uuid.uuid4())
    email = f'qa.delete.{uid[:8]}@bitpaw.test'
    pw = secrets.token_urlsafe(12)
    db.users.insert_one({'id': uid, 'email': email, 'password_hash': generate_password_hash(pw), 'business_id': uid,
                         'role': 'admin', 'created_at': datetime.now().isoformat()})
    db.businesses.insert_one({'id': uid, 'name': 'QA Delete Test Salon', 'owner_name': 'QA', 'industry_code': 'nail',
                              'created_at': datetime.now().isoformat()})
    db.system_settings.update_one({'key': f'business_mode_{uid}'},
                                  {'$set': {'key': f'business_mode_{uid}', 'value': 'nail'}}, upsert=True)
    json.dump({'id': uid, 'email': email, 'password': pw}, open(out, 'w'))
    print('created', email)
else:
    acc = json.load(open(out))
    u = db.users.find_one({'id': acc['id']}, {'_id': 0, 'email': 1, 'is_deleted': 1})
    b = db.businesses.find_one({'id': acc['id']}, {'_id': 0, 'is_deleted': 1})
    print('state before cleanup: user', u, '| business', b)
    print('deleted', db.users.delete_many({'id': acc['id']}).deleted_count,
          db.businesses.delete_many({'id': acc['id']}).deleted_count,
          db.system_settings.delete_many({'key': f"business_mode_{acc['id']}"}).deleted_count)
