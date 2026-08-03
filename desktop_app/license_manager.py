"""
Kiểm tra License Key khi khởi động app, gọi lên server trung tâm của bạn.
Có cơ chế cache + grace period để app vẫn chạy được vài ngày khi khách mất mạng tạm thời,
thay vì chặn cứng ngay khi không gọi được API (trải nghiệm tệ cho 1 app cài local).
"""
import os
import sys
import json
import hmac
import hashlib
import uuid
from datetime import datetime, timedelta

import requests

APP_DATA = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'BitPawOS')
os.makedirs(APP_DATA, exist_ok=True)

LICENSE_KEY_PATH = os.path.join(APP_DATA, 'license.key')
LICENSE_CACHE_PATH = os.path.join(APP_DATA, 'license_cache.json')

# Đổi thành domain server license trung tâm thật của bạn (khác với domain web app SaaS cũ)
LICENSE_SERVER_URL = os.environ.get('BITPAW_LICENSE_SERVER', 'https://license.bitpawsoftware.com/api/v1/verify')
OFFLINE_GRACE_DAYS = 3

# --- Chống sửa tay license_cache.json (Mã 4.2 audit) ---
# SECRET nhúng sẵn trong build — KHÔNG chống được reverse-engineer chuyên nghiệp (ai dịch
# ngược được .exe/.pyc thì đọc được hằng số này), NHƯNG chặn đứng kiểu crack phổ biến nhất
# với 1 app POS nail salon: khách tự mở license_cache.json bằng Notepad, sửa tay "cached_at"
# thành giờ hiện tại để app tưởng vừa xác thực xong, chạy mãi ở "chế độ ân hạn". Có HMAC ký
# thì sửa 1 ký tự trong file là chữ ký sai ngay, cache bị coi là rác. Nên đổi hằng số này
# thành giá trị ngẫu nhiên riêng của bạn trước khi build, đừng dùng nguyên văn placeholder.
_CACHE_HMAC_SECRET = os.environ.get(
    'BITPAW_LICENSE_CACHE_SECRET',
    'DOI-CHUOI-NAY-THANH-RANDOM-SECRET-RIENG-CUA_BAN-TRUOC-KHI-BUILD',
).encode('utf-8')


def _sign_payload(payload_json_str):
    """Ký payload (đã json.dumps) bằng HMAC-SHA256 -> hex digest."""
    return hmac.new(_CACHE_HMAC_SECRET, payload_json_str.encode('utf-8'), hashlib.sha256).hexdigest()


def _machine_fingerprint():
    """Vân tay máy đơn giản (dựa trên MAC) — đủ để 1 License Key không bị dùng tràn lan trên
    nhiều máy khác nhau. Không cố chống crack chuyên nghiệp (driver-level HWID, TPM...) vì
    không tương xứng với rủi ro/lợi ích của 1 app POS nail salon."""
    node = uuid.getnode()
    return hashlib.sha256(str(node).encode()).hexdigest()[:32]


def _read_license_key():
    if not os.path.exists(LICENSE_KEY_PATH):
        return None
    with open(LICENSE_KEY_PATH, 'r', encoding='utf-8') as f:
        key = f.read().strip()
    return key or None


def _prompt_and_save_license_key():
    print("=" * 60)
    print("Chưa tìm thấy License Key trên máy này.")
    key = input("Vui lòng nhập License Key được cấp: ").strip()
    with open(LICENSE_KEY_PATH, 'w', encoding='utf-8') as f:
        f.write(key)
    return key


def save_license_cache(data):
    """Ghi cache license đã ký HMAC. File trên đĩa có dạng {"payload": {...}, "signature": "..."}.
    payload được json.dumps với sort_keys=True để đảm bảo lúc ký và lúc verify lại luôn ra
    cùng 1 chuỗi byte (nếu không sort_keys, thứ tự key có thể đổi giữa các lần json.dump/load
    và làm chữ ký không khớp dù nội dung không đổi)."""
    payload = {**data, "cached_at": datetime.utcnow().isoformat()}
    payload_str = json.dumps(payload, sort_keys=True)
    signature = _sign_payload(payload_str)
    with open(LICENSE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump({"payload": payload, "signature": signature}, f)


def load_license_cache():
    """Đọc + verify chữ ký HMAC của cache. Nếu file bị sửa tay (dù chỉ 1 ký tự) hoặc thiếu
    chữ ký hợp lệ, xoá file cache và coi như không có cache (trả về None)."""
    if not os.path.exists(LICENSE_CACHE_PATH):
        return None
    try:
        with open(LICENSE_CACHE_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        payload = raw["payload"]
        signature = raw["signature"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        _invalidate_cache()
        return None

    expected_signature = _sign_payload(json.dumps(payload, sort_keys=True))
    if not hmac.compare_digest(expected_signature, signature):
        print("[License] Cache bị sửa hoặc chữ ký HMAC không hợp lệ — huỷ cache, coi như invalid.")
        _invalidate_cache()
        return None

    return payload


def _invalidate_cache():
    try:
        os.remove(LICENSE_CACHE_PATH)
    except OSError:
        pass


def _within_grace_period(cached):
    try:
        cached_at = datetime.fromisoformat(cached["cached_at"])
    except (KeyError, ValueError):
        return False
    if datetime.utcnow() - cached_at >= timedelta(days=OFFLINE_GRACE_DAYS):
        return False

    # Chữ ký HMAC chỉ chống sửa file, không tự động chống license đã hết hạn thật sự:
    # nếu server đã trả "expires_at" trong lần xác thực online gần nhất, phải tự so lại
    # với ngày hôm nay — nếu không, 1 license hết hạn 1 lần rồi thì cache hợp lệ (đã ký đàng
    # hoàng) vẫn có thể bị "refresh cached_at" bằng cách gọi save_license_cache lặp lại và
    # chạy mãi mãi trong "ân hạn" dù license đã hết hạn từ lâu.
    expires_at = cached.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                print("[License] Cache hợp lệ về chữ ký nhưng license đã hết hạn (expires_at đã qua).")
                return False
        except ValueError:
            pass

    return True


def verify_license_or_exit():
    """Gọi về server trung tâm để xác minh License Key + hạn sử dụng. Thoát app (sys.exit)
    nếu license không hợp lệ/hết hạn, hoặc mất mạng và đã hết thời gian ân hạn offline.

    Payload response mong đợi từ server (tuỳ bạn định nghĩa):
        { "valid": true, "plan": "pro", "expires_at": "2027-01-01", "config": {...} }
    -> "config" là chỗ để trả các secret/API key riêng theo từng khách (xem ghi chú bảo mật
    trong build.spec) thay vì bundle 1 bộ .env dùng chung cho mọi bản cài.
    """
    key = _read_license_key() or _prompt_and_save_license_key()
    fingerprint = _machine_fingerprint()

    try:
        resp = requests.post(
            LICENSE_SERVER_URL,
            json={"license_key": key, "machine_id": fingerprint},
            timeout=6,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("valid"):
            save_license_cache(data)
            return data

        print(f"[License] Từ chối: {data.get('message', 'License không hợp lệ hoặc đã hết hạn.')}")
        sys.exit(1)

    except requests.RequestException:
        cached = load_license_cache()
        if cached and _within_grace_period(cached):
            print("[License] Không có mạng — chạy tạm bằng license đã cache (còn trong thời gian ân hạn).")
            return cached
        print("[License] Không thể xác minh License (mất mạng và đã hết thời gian ân hạn offline). Thoát.")
        sys.exit(1)
