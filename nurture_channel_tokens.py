"""
Lưu access token Zalo OA / Facebook Messenger THEO TỪNG TENANT (Mã Nurture Part 3 audit) —
message_delivery_worker.py cần biết dùng token nào để gửi hộ đúng doanh nghiệp nào. Khác với
_queue_loyalty_notification() (app.py, tính năng loyalty riêng) đang dùng 1 access token DÙNG
CHUNG toàn hệ thống qua biến môi trường global ZALO_OA_ACCESS_TOKEN/FB_PAGE_ACCESS_TOKEN — cách
đó chỉ đúng khi cả SaaS chỉ phục vụ 1 doanh nghiệp, sai ngay khi có tenant thứ 2 (tin nhắn nurture
của tiệm A sẽ gửi nhầm bằng OA của tiệm B).

access_token luôn được MÃ HOÁ (Fernet) trước khi ghi Mongo — cùng pattern app.py đã dùng cho
ECOMMERCE_ENC_KEY/AD_TOKEN_ENC_KEY, fail-closed nếu thiếu key mã hoá.
"""
import os
from datetime import datetime

import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet

from mongo_client import db

_ENC_KEY = os.environ.get('NURTURE_CHANNEL_ENC_KEY')
_keys = []
try:
    if _ENC_KEY:
        _keys.append(Fernet(_ENC_KEY.encode()))
except Exception as e:
    print(f"[!] NURTURE_CHANNEL_ENC_KEY không hợp lệ (phải là 1 Fernet key base64 32 byte): {e}")
# Chưa cấu hình khoá riêng: dẫn xuất khoá từ FLASK_SECRET_KEY (bí mật bắt buộc của app) để vẫn lưu được token
# MÃ HOÁ (kết nối SMS Twilio/Zalo/Messenger). MultiFernet: mã hoá bằng khoá đầu tiên, giải mã thử mọi khoá —
# thêm NURTURE_CHANNEL_ENC_KEY sau này thì token cũ vẫn đọc được.
_app_secret = os.environ.get('FLASK_SECRET_KEY')
if _app_secret:
    _keys.append(Fernet(base64.urlsafe_b64encode(hashlib.sha256(b'bitpaw-channel-tokens|' + _app_secret.encode()).digest())))
_fernet = MultiFernet(_keys) if _keys else None


def save_channel_token(business_id, platform, access_token, extra=None):
    """platform: 'zalo_oa' | 'facebook'. `extra`: dict phụ (vd oa_id/oa_name hoặc page_id/page_name)
    lấy từ chính response xác thực thật của provider (xem app.py:nurture_test_connection)."""
    if _fernet is None:
        raise RuntimeError("Server chưa cấu hình NURTURE_CHANNEL_ENC_KEY — không thể lưu token an toàn.")
    now_iso = datetime.now().isoformat()
    doc = {
        'business_id': business_id,
        'platform': platform,
        'access_token_enc': _fernet.encrypt(access_token.encode()).decode(),
        'updated_at': now_iso,
    }
    doc.update(extra or {})
    db.nurture_channel_tokens.update_one(
        {'business_id': business_id, 'platform': platform},
        {'$set': doc, '$setOnInsert': {'created_at': now_iso}},
        upsert=True,
    )


def get_channel_token(business_id, platform):
    """Trả về dict đã GIẢI MÃ (access_token + mọi field phụ đã lưu), hoặc None nếu tenant chưa
    kết nối kênh này (hoặc server thiếu NURTURE_CHANNEL_ENC_KEY)."""
    if _fernet is None:
        return None
    doc = db.nurture_channel_tokens.find_one({'business_id': business_id, 'platform': platform})
    if not doc:
        # Chưa nối riêng cho chiến dịch -> dùng chính kênh đã nối ở Hộp thư chung (cùng Zalo OA / Fanpage)
        inbox_ch = {'zalo_oa': 'zalo', 'facebook': 'messenger'}.get(platform)
        if inbox_ch:
            import inbox_channels
            conn = inbox_channels.get_connection(business_id, inbox_ch)
            token = (inbox_channels._zalo_token(conn) if inbox_ch == 'zalo' else decrypt_secret(conn.get('access_token_enc'))) if conn else None
            if token:
                return {'business_id': business_id, 'platform': platform, 'access_token': token,
                        'account_name': conn.get('account_name'), 'external_id': conn.get('external_id'), 'source': 'inbox'}
        return None
    try:
        access_token = _fernet.decrypt(doc['access_token_enc'].encode()).decode()
    except Exception:
        return None
    result = {k: v for k, v in doc.items() if k not in ('_id', 'access_token_enc')}
    result['access_token'] = access_token
    return result


def encrypt_secret(value):
    """Mã hoá 1 bí mật bất kỳ (token/app secret của kênh Hộp thư chung — inbox_channels.py) bằng CÙNG khoá Fernet."""
    if _fernet is None:
        raise RuntimeError("Server chưa cấu hình khoá mã hoá — không thể lưu bí mật an toàn.")
    return _fernet.encrypt(str(value).encode()).decode()


def decrypt_secret(token):
    if _fernet is None or not token:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except Exception:
        return None
