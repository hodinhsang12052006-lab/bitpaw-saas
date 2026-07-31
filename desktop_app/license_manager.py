"""
Kiểm tra License Key khi khởi động app, gọi lên server trung tâm của bạn.
Có cơ chế cache + grace period để app vẫn chạy được vài ngày khi khách mất mạng tạm thời,
thay vì chặn cứng ngay khi không gọi được API (trải nghiệm tệ cho 1 app cài local).
"""
import os
import sys
import json
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


def _cache_success(data):
    payload = {**data, "cached_at": datetime.utcnow().isoformat()}
    with open(LICENSE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f)


def _load_cache():
    if not os.path.exists(LICENSE_CACHE_PATH):
        return None
    try:
        with open(LICENSE_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _within_grace_period(cached):
    try:
        cached_at = datetime.fromisoformat(cached["cached_at"])
    except (KeyError, ValueError):
        return False
    return datetime.utcnow() - cached_at < timedelta(days=OFFLINE_GRACE_DAYS)


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
            _cache_success(data)
            return data

        print(f"[License] Từ chối: {data.get('message', 'License không hợp lệ hoặc đã hết hạn.')}")
        sys.exit(1)

    except requests.RequestException:
        cached = _load_cache()
        if cached and _within_grace_period(cached):
            print("[License] Không có mạng — chạy tạm bằng license đã cache (còn trong thời gian ân hạn).")
            return cached
        print("[License] Không thể xác minh License (mất mạng và đã hết thời gian ân hạn offline). Thoát.")
        sys.exit(1)
