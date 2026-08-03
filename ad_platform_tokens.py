"""
Lưu System User Access Token dài hạn của Facebook Marketing API cho từng tenant (Mã AI Ads
Part 2.1 audit) — chủ tiệm dán token 1 LẦN DUY NHẤT lúc kết nối "Ads Manager", backend tự dùng
lại cho mọi lần tạo campaign/kéo insight sau đó, không bắt gõ access_token vào mỗi request như
ad_assistant.py bản cũ (rủi ro: token dài hạn bị lộ qua log request, và cực kỳ bất tiện).

access_token luôn được MÃ HOÁ (Fernet) trước khi ghi xuống Mongo — token Facebook System User
tồn tại lâu dài và có quyền chi tiêu tiền quảng cáo thật, lộ plaintext trong 1 bản dump DB là
rủi ro tài chính trực tiếp cho tenant. Theo đúng pattern app.py đã dùng cho ECOMMERCE_ENC_KEY
(ecommerce_sync.html) — fail-closed nếu chưa cấu hình key mã hoá, KHÔNG BAO GIỜ rơi về lưu
plaintext.
"""
import os
from datetime import datetime

from cryptography.fernet import Fernet

from mongo_client import db

_AD_TOKEN_ENC_KEY = os.environ.get('AD_TOKEN_ENC_KEY')
try:
    _fernet = Fernet(_AD_TOKEN_ENC_KEY.encode()) if _AD_TOKEN_ENC_KEY else None
except Exception as e:
    print(f"[!] AD_TOKEN_ENC_KEY không hợp lệ (phải là 1 Fernet key base64 32 byte): {e}")
    _fernet = None


def save_facebook_token(business_id, access_token, ad_account_id, page_id=None):
    """Ghi/ghi đè token Facebook của 1 tenant (upsert theo business_id). Fail-closed: nếu
    server chưa cấu hình AD_TOKEN_ENC_KEY, ném RuntimeError thay vì âm thầm lưu plaintext.

    Luôn reset status='active' + xoá invalid_reason — đây là điểm reconnect DUY NHẤT sau khi
    token cũ bị đánh dấu hết hạn (xem mark_facebook_token_invalid), nên phải dọn sạch cờ cũ."""
    if _fernet is None:
        raise RuntimeError("Server chưa cấu hình AD_TOKEN_ENC_KEY — không thể lưu token Facebook an toàn.")
    now_iso = datetime.now().isoformat()
    db.ad_platform_tokens.update_one(
        {'business_id': business_id, 'platform': 'facebook'},
        {
            '$set': {
                'business_id': business_id,
                'platform': 'facebook',
                'access_token_enc': _fernet.encrypt(access_token.encode()).decode(),
                'ad_account_id': ad_account_id,
                'page_id': page_id,
                'status': 'active',
                'invalid_reason': None,
                'updated_at': now_iso,
            },
            '$setOnInsert': {'created_at': now_iso},
        },
        upsert=True,
    )


def mark_facebook_token_invalid(business_id, reason):
    """Mã "Go-Live Pentest" audit — gọi khi Facebook Graph API trả lỗi OAuth (token hết hạn/bị
    thu hồi, xem facebook_ads_client.FacebookTokenExpiredError). Đánh dấu status='expired' để:
    (1) ads_metrics_worker.py ngưng lặp lại việc gọi API cho tenant này mỗi 15 phút vô ích,
    (2) UI đọc được qua get_facebook_token()['status'] để hiện banner 'Kết nối lại Facebook'."""
    db.ad_platform_tokens.update_one(
        {'business_id': business_id, 'platform': 'facebook'},
        {'$set': {'status': 'expired', 'invalid_reason': str(reason), 'invalid_at': datetime.now().isoformat()}},
    )


def get_facebook_token(business_id):
    """Trả về {access_token, ad_account_id, page_id, status, invalid_reason} đã GIẢI MÃ, hoặc
    None nếu tenant chưa kết nối Facebook Ads (hoặc server thiếu AD_TOKEN_ENC_KEY). KHÔNG log
    access_token ra bất kỳ đâu. `status` là 'active' hoặc 'expired' — caller (route/worker) tự
    quyết định có dùng access_token khi status='expired' hay không (Facebook có thể vẫn từ chối
    ngay, nhưng KHÔNG chặn cứng ở đây để tránh false-positive nếu tenant đã tự làm mới token)."""
    if _fernet is None:
        return None
    doc = db.ad_platform_tokens.find_one({'business_id': business_id, 'platform': 'facebook'})
    if not doc:
        return None
    try:
        access_token = _fernet.decrypt(doc['access_token_enc'].encode()).decode()
    except Exception:
        return None  # token hỏng/mã hoá bằng key cũ đã xoay vòng -> coi như chưa kết nối
    return {
        'access_token': access_token,
        'ad_account_id': doc.get('ad_account_id'),
        'page_id': doc.get('page_id'),
        'status': doc.get('status', 'active'),
        'invalid_reason': doc.get('invalid_reason'),
    }


def has_facebook_token(business_id):
    return db.ad_platform_tokens.count_documents({'business_id': business_id, 'platform': 'facebook'}) > 0
