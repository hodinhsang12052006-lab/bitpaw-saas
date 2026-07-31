"""
Thay thế cho mongo_client.py khi chạy ở chế độ Desktop (offline, local-first).
Dùng MontyDB — API tương thích pymongo (find_one/insert_one/update_one/$inc/$set/
aggregate/ObjectId...) nhưng lưu dữ liệu bằng SQLite ngay trên ổ cứng máy khách,
không cần server Mongo nào cả.

CÁCH DÙNG: trong app.py, đổi đúng 1 dòng import:
    from mongo_client import db, fs, client as mongo_client_instance, MONGO_STATUS, next_mongo_id, next_mongo_id_batch
thành:
    from local_db import db, fs, client as mongo_client_instance, MONGO_STATUS, next_mongo_id, next_mongo_id_batch

QUAN TRỌNG: MontyDB không phủ 100% aggregation pipeline/operator của MongoDB thật
(vd một số $lookup/$facet nâng cao, transactions, change streams đều không có).
Trước khi coi đây là xong, chạy lại đúng bộ test đã có sẵn trong repo
(test_mongo.py, e2e_core_test.py, test_pos_nails_e2e.py...) nhằm vào local_db.py
này để biết chắc các query thật của bạn có tương thích hay không, thay vì đoán.
"""
import os
from pymongo import ReturnDocument  # chỉ là 1 enum hằng số, không cần kết nối thật -> vẫn import được dù không có Mongo

from mongo_client import load_env_file
load_env_file()

from montydb import MontyClient, set_storage

# Lưu ở %APPDATA%\BitPawOS (Windows) / ~/.BitPawOS (khác) — KHÔNG lưu trong thư mục cài đặt,
# vì thư mục đó có thể là ổ đĩa read-only hoặc bị ghi đè mỗi lần auto-update cài bản mới.
_APPDATA_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'BitPawOS')
_DB_DIR = os.path.join(_APPDATA_DIR, 'local_db')
_BACKUP_DIR = os.path.join(_APPDATA_DIR, 'backups')
os.makedirs(_DB_DIR, exist_ok=True)
os.makedirs(_BACKUP_DIR, exist_ok=True)

set_storage(_DB_DIR, storage='sqlite')  # <- đây là phần "SQLite lưu trực tiếp trên ổ cứng khách"
client = MontyClient(_DB_DIR)
db = client.get_database('bitpaw_db')
MONGO_STATUS = "CONNECTED (local SQLite via MontyDB)"


class _LocalFileBackup:
    """MontyDB không có GridFS. Thay vì lưu file backup thành chunks trong DB (lý do GridFS
    tồn tại là để chia sẻ file lớn qua nhiều node Mongo — vô nghĩa khi chỉ có 1 máy cục bộ),
    ghi thẳng ra thư mục backups/ trên ổ đĩa. Giữ đúng tên method .put()/.get_last_version()
    app.py đang gọi qua biến `fs` để không phải sửa code gọi backup ở nơi khác."""

    def put(self, data, filename=None, **kwargs):
        filename = filename or f"backup_{int(os.times().elapsed * 1000)}.bin"
        path = os.path.join(_BACKUP_DIR, filename)
        with open(path, 'wb') as f:
            f.write(data if isinstance(data, (bytes, bytearray)) else data.read())
        return filename

    def get_last_version(self, filename):
        path = os.path.join(_BACKUP_DIR, filename)
        return open(path, 'rb')


fs = _LocalFileBackup()


def next_mongo_id(collection_name):
    counter = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter['seq']


def next_mongo_id_batch(collection_name, count):
    counter = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': count}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    last_id = counter['seq']
    return range(last_id - count + 1, last_id + 1)
