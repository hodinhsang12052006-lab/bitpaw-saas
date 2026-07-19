import os
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError
from gridfs import GridFS

# Custom environment loader (giữ nguyên từ supabase_client.py cũ) — email_service.py và các
# file khác vẫn import load_env_file từ đây, không đổi tên/đổi hành vi để không phá chúng.
def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        print("[*] Reading environment parameters from local '.env' file...")
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k_clean = k.strip()
                        v_clean = v.strip().strip('"').strip("'")
                        os.environ[k_clean] = v_clean
        except Exception as e:
            print(f"[!] Warning: Failed parsing '.env' file: {str(e)}")

load_env_file()

MONGO_URI = os.environ.get('MONGO_URI')

db = None
fs = None
MONGO_STATUS = "NOT CONFIGURED"

if MONGO_URI:
    try:
        # serverSelectionTimeoutMS=5000: bắt buộc cho môi trường Serverless (Vercel) — nếu không
        # set, driver mặc định chờ 30s mới báo lỗi kết nối, dễ làm function bị timeout/treo.
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client.get_database('bitpaw_db')
        # Probe kết nối thật (không chỉ khởi tạo object) — ping xong mới coi là CONNECTED,
        # để không đánh lừa phần còn lại của hệ thống khi Atlas thật sự không tới được.
        client.admin.command('ping')
        MONGO_STATUS = "CONNECTED"
        # GridFS thay thế Supabase Storage cho tính năng backup/restore (collection 'backups'
        # -> backups.files / backups.chunks, giữ đúng tên bucket cũ BACKUP_BUCKET='backups').
        fs = GridFS(db, collection='backups')
        print(f"[*] MongoDB client connected. (Database: bitpaw_db)")
    except PyMongoError as e:
        MONGO_STATUS = "DISCONNECTED"
        db = None
        print(f"[!] Critical: MongoDB connection failed -> {str(e)}")
else:
    print("[!] Warning: MONGO_URI không có trong biến môi trường.")
    MONGO_STATUS = "NOT CONFIGURED"


def next_mongo_id(collection_name):
    """Sinh id nguyên tự tăng (giống SERIAL/BIGINT IDENTITY của Postgres) cho 1 collection —
    MongoDB không có auto-increment sẵn, nên dùng collection 'counters' để đếm atomic. Giữ id
    dạng int (không dùng ObjectId của Mongo) để không phải đổi route Flask (vd: <int:id>) hay
    JS ở frontend đang mong đợi id là số. Dùng chung cho mọi module (app.py, ad_assistant.py...),
    không định nghĩa lặp lại ở từng file."""
    counter = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return counter['seq']


def next_mongo_id_batch(collection_name, count):
    """Sinh 1 dải `count` id nguyên liên tiếp trong ĐÚNG 1 lần gọi DB — dùng khi cần tạo hàng
    loạt bản ghi cùng lúc (vd: seed 200 bàn mặc định), tránh gọi next_mongo_id() lặp lại
    `count` lần (mỗi lần là 1 round-trip riêng tới collection counters)."""
    counter = db.counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': count}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    last_id = counter['seq']
    first_id = last_id - count + 1
    return range(first_id, last_id + 1)
