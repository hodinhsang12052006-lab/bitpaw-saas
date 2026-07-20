# Script test kết nối MongoDB ĐỘC LẬP — chỉ đọc MONGO_URI từ .env và ping thẳng, không đụng gì
# tới app.py/mongo_client.py để tránh output/side-effect khác chen vào làm rối kết quả.
#
# Chạy:  python test_mongo.py

import os
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')  # tránh UnicodeEncodeError khi in tiếng Việt trên console Windows

from pymongo import MongoClient
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError


def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        print(f"[!] Không tìm thấy file .env tại: {env_path}")
        sys.exit(1)
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


def mask_uri(uri):
    """Che password khi in ra terminal/log — không in credential thật dù chỉ để debug."""
    try:
        scheme, rest = uri.split('://', 1)
        creds, host_part = rest.split('@', 1)
        user = creds.split(':', 1)[0]
        return f"{scheme}://{user}:****@{host_part}"
    except ValueError:
        return uri


load_env_file()
MONGO_URI = os.environ.get('MONGO_URI')

if not MONGO_URI:
    print("[!] Không tìm thấy MONGO_URI trong .env")
    sys.exit(1)

print(f"Đang thử kết nối tới: {mask_uri(MONGO_URI)}\n")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    client.admin.command('ping')
    db = client.get_database('bitpaw_db')
    print("Kết nối ngon lành!")
    print(f"   Database: {db.name}")
    print(f"   Collections hiện có: {db.list_collection_names()}")

except ConfigurationError as e:
    print("LỖI CẤU HÌNH URI (thường do DNS SRV lookup thất bại):")
    print(f"   {type(e).__name__}: {e}")
    print("\nGợi ý:")
    print("   - Vào Atlas -> Connect -> Drivers, copy LẠI đúng nguyên connection string.")
    print("   - Thử đổi DNS máy bạn sang 8.8.8.8 (Google DNS) rồi chạy lại.")
    print("   - Nếu mạng của bạn chặn SRV record, lấy connection string dạng mongodb://")
    print("     (không phải +srv, liệt kê thẳng host:port) từ Atlas làm phương án dự phòng.")
    sys.exit(1)

except OperationFailure as e:
    print("LỖI XÁC THỰC (mạng/DNS OK, nhưng Atlas từ chối username/password):")
    print(f"   {type(e).__name__}: {e.details}")
    print("\nGợi ý:")
    print("   - Vào Atlas -> Database Access -> Edit user 'bitpaw_admin' -> Reset Password,")
    print("     generate password MỚI (bấm nút Autogenerate) để loại trừ gõ nhầm/thiếu ký tự.")
    print("   - Kiểm tra user có role đọc/ghi trên đúng database 'bitpaw_db' không.")
    sys.exit(1)

except ServerSelectionTimeoutError as e:
    print("LỖI TIMEOUT (thường do IP chưa được whitelist trên Atlas):")
    print(f"   {type(e).__name__}: {e}")
    print("\nGợi ý:")
    print("   - Vào Atlas -> Network Access -> Add IP Address -> thêm IP hiện tại của bạn")
    print("     (hoặc tạm thời 0.0.0.0/0 để test nhanh, KHÔNG dùng cho production).")
    sys.exit(1)

except Exception as e:
    print(f"LỖI KHÁC (chưa từng gặp, gửi nguyên dòng này cho tôi để xem tiếp): {type(e).__name__}: {e}")
    sys.exit(1)
