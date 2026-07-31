"""
CSDL cục bộ MÃ HOÁ bằng SQLCipher — dùng cho các bảng dữ liệu MỚI của Desktop App (lịch hẹn
AI Bot tự đặt, license cache...). Đây KHÔNG phải kho dữ liệu chính (đơn hàng/khách hàng/nhân
viên...) — kho đó vẫn ở local_db.py (MontyDB), MontyDB không expose 1 connection factory để
cắm SQLCipher vào, nên mã hoá lại toàn bộ kho đó là 1 dự án riêng, lớn hơn (đổi engine lưu trữ
hoàn toàn), không lẫn vào đây. secure_db.py là điểm bắt đầu: mọi bảng MỚI (bắt đầu từ
`appointments`) đi qua đường mã hoá ngay từ đầu.

Yêu cầu cài đặt: pip install sqlcipher3-binary keyring
LƯU Ý (Windows): sqlcipher3-binary không phải lúc nào cũng có sẵn wheel dựng sẵn cho mọi phiên
bản Python mới nhất — nếu `pip install` báo lỗi build từ source, cần cài Visual C++ Build Tools
+ OpenSSL dev headers, hoặc dùng phiên bản Python thấp hơn 1 bậc có wheel sẵn.
"""
import os
import secrets

import keyring
import sqlcipher3
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

APP_DATA_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'BitPawOS')
os.makedirs(APP_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(APP_DATA_DIR, 'secure_local.db')

_KEYRING_SERVICE = "BitPawOS"
_KEYRING_USERNAME = "secure_db_master_key"


def _get_or_create_master_key():
    """Khoá mã hoá KHÔNG được lưu cùng thư mục với file .db (nếu vậy chẳng khác nào khoá cửa
    nhưng để chìa ngay dưới thảm) — lưu vào Windows Credential Manager (hoặc macOS Keychain /
    Linux Secret Service qua cùng thư viện `keyring`), tách biệt hoàn toàn khỏi file .exe/.db
    mà khách hàng có trong tay."""
    try:
        existing_key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if existing_key:
            return existing_key
        new_key = secrets.token_hex(32)  # 256-bit
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, new_key)
        return new_key
    except Exception as e:
        # KHÔNG bao giờ fallback về 1 khoá cứng/mặc định nếu keyring lỗi — thà app không khởi
        # động được còn hơn âm thầm mã hoá bằng 1 khoá công khai ai cũng đoán ra.
        raise RuntimeError(
            f"Không thể lấy/tạo Master Key mã hoá từ hệ điều hành (keyring backend lỗi): {e}. "
            "Không thể khởi tạo an toàn CSDL mã hoá nếu thiếu khoá này."
        ) from e


_MASTER_KEY = _get_or_create_master_key()

engine = create_engine(f"sqlite:///{DB_PATH}", module=sqlcipher3.dbapi2, future=True)


@event.listens_for(engine, "connect")
def _set_sqlcipher_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute(f"PRAGMA key = \"x'{_MASTER_KEY}'\"")
        cursor.execute("PRAGMA cipher_page_size = 4096")
        cursor.execute("PRAGMA kdf_iter = 256000")
        cursor.execute("PRAGMA journal_mode = WAL")
        # SQLCipher KHÔNG báo lỗi ngay nếu key sai ở lệnh PRAGMA key — nó chỉ âm thầm trả về
        # dữ liệu rác ở query thật đầu tiên. Buộc giải mã thật ngay bây giờ để fail nhanh và
        # rõ ràng, thay vì phát hiện muộn (và mơ hồ) ở tận nơi gọi book_appointment().
        cursor.execute("SELECT count(*) FROM sqlite_master")
    except Exception as e:
        cursor.close()
        raise RuntimeError(
            f"Không thể mở CSDL mã hoá (sai Master Key hoặc file .db bị hỏng/không phải SQLCipher): {e}"
        ) from e
    finally:
        cursor.close()


def init_schema():
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    appointment_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_appointments_lookup "
                "ON appointments (business_id, appointment_time)"
            ))
    except SQLAlchemyError as e:
        raise RuntimeError(f"Không thể khởi tạo schema CSDL mã hoá cục bộ: {e}") from e


init_schema()
