"""
Background Worker RIÊNG (Mã Nurture Part 3 audit) — đọc các tin nhắn ĐÃ DUYỆT
(db.campaign_messages, approval_status='APPROVED', chưa có sent_at) và gửi THẬT qua Zalo OA /
Facebook Messenger Send API, dùng access token riêng của TỪNG TENANT
(nurture_channel_tokens.py). Gửi API thành công MỚI ghi sent_at + delivery_status='success' —
khác hẳn app.py:/api/ai/nurture/approve-message TRƯỚC ĐÂY (set sent_at giả ngay lúc bấm duyệt,
chưa hề gọi API nào).

CÁCH CHẠY:
    python message_delivery_worker.py            # quét 1 lần rồi thoát — dùng với cron dày hơn:
                                                   #   */5 * * * * cd /path && python message_delivery_worker.py
    python message_delivery_worker.py --loop      # tự lặp mỗi 60s (môi trường không có cron)
"""
import sys
import time
from datetime import datetime

import requests

from mongo_client import db
import nurture_channel_tokens

MAX_DELIVERY_ATTEMPTS = 5
POLL_INTERVAL_SECONDS = 60
BATCH_LIMIT = 200


def _send_zalo(access_token, zalo_user_id, message_text):
    resp = requests.post(
        'https://openapi.zalo.me/v3.0/oa/message/cs',
        headers={'access_token': access_token, 'Content-Type': 'application/json'},
        json={'recipient': {'user_id': zalo_user_id}, 'message': {'text': message_text}},
        timeout=10,
    )
    payload = resp.json()
    if payload.get('error') not in (0, None):
        raise RuntimeError(f"Zalo từ chối gửi: {payload.get('message')}")
    return payload


def _send_facebook(access_token, fb_psid, message_text):
    # LƯU Ý CHÍNH SÁCH META: gửi tin nhắn "marketing/nurture" cho khách NGOÀI cửa sổ 24h kể từ
    # tin nhắn gần nhất của họ về Facebook chịu ràng buộc Messenger Platform Policy (không phải
    # giới hạn kỹ thuật của code này) — messaging_type='UPDATE' chỉ hợp lệ cho non-promotional
    # follow-up. Với nurture mang tính khuyến mãi thật sự, tenant cần cân nhắc Sponsored Message
    # hoặc chỉ gửi cho khách còn trong cửa sổ 24h; đây là giới hạn của nền tảng Meta, không phải
    # điều code có thể lách qua.
    resp = requests.post(
        'https://graph.facebook.com/v21.0/me/messages',
        params={'access_token': access_token},
        json={
            'recipient': {'id': fb_psid},
            'message': {'text': message_text},
            'messaging_type': 'UPDATE',
        },
        timeout=10,
    )
    payload = resp.json()
    if 'error' in payload:
        raise RuntimeError(f"Facebook từ chối gửi: {payload['error'].get('message')}")
    return payload


def _mark_sent(msg_id):
    db.campaign_messages.update_one(
        {'id': msg_id},
        {'$set': {'sent_at': datetime.now().isoformat(), 'delivery_status': 'success'}},
    )


def _mark_failed(msg_id, error, attempts):
    status = 'failed_permanent' if attempts >= MAX_DELIVERY_ATTEMPTS else 'failed'
    db.campaign_messages.update_one(
        {'id': msg_id},
        {'$set': {'delivery_status': status, 'delivery_error': str(error), 'delivery_attempts': attempts}},
    )


def _deliver_one(msg):
    business_id = msg['business_id']
    attempts = int(msg.get('delivery_attempts', 0)) + 1

    customer = db.customers.find_one({'id': msg['customer_id'], 'business_id': business_id}, {'_id': 0})
    if not customer:
        _mark_failed(msg['id'], "Không tìm thấy khách hàng (đã bị xoá?)", MAX_DELIVERY_ATTEMPTS)
        return

    channel = msg.get('channel') or 'zalo_oa'
    try:
        if channel in ('zalo', 'zalo_oa'):
            token_info = nurture_channel_tokens.get_channel_token(business_id, 'zalo_oa')
            if not token_info:
                raise RuntimeError("Tenant chưa kết nối Zalo OA (chưa có token đã xác thực qua /api/ai/nurture/test-connection).")
            zalo_user_id = customer.get('zalo_user_id')
            if not zalo_user_id:
                raise RuntimeError("Khách hàng chưa có zalo_user_id (chưa từng nhắn tin qua OA này).")
            _send_zalo(token_info['access_token'], zalo_user_id, msg['message_body'])
        elif channel in ('facebook', 'messenger'):
            token_info = nurture_channel_tokens.get_channel_token(business_id, 'facebook')
            if not token_info:
                raise RuntimeError("Tenant chưa kết nối Facebook Messenger (chưa có token đã xác thực).")
            fb_psid = customer.get('fb_psid')
            if not fb_psid:
                raise RuntimeError("Khách hàng chưa có fb_psid (chưa từng nhắn tin qua Messenger).")
            _send_facebook(token_info['access_token'], fb_psid, msg['message_body'])
        else:
            raise RuntimeError(f"Kênh '{channel}' chưa được hỗ trợ gửi thật.")
    except Exception as e:
        _mark_failed(msg['id'], e, attempts)
        print(f"[message_delivery_worker] Gửi thất bại message_id={msg['id']} (lần {attempts}): {e}")
        return

    _mark_sent(msg['id'])
    print(f"[message_delivery_worker] Gửi thành công message_id={msg['id']} qua {channel}.")


def run_once():
    """1 lượt quét — 1 tin nhắn lỗi không được chặn các tin còn lại trong cùng lượt."""
    pending = list(db.campaign_messages.find({
        'approval_status': 'APPROVED',
        'sent_at': {'$exists': False},
        'delivery_status': {'$nin': ['failed_permanent']},
    }, {'_id': 0}).limit(BATCH_LIMIT))

    for msg in pending:
        try:
            _deliver_one(msg)
        except Exception as e:
            print(f"[message_delivery_worker] Lỗi không mong đợi xử lý message_id={msg.get('id')}: {e}")
    return len(pending)


if __name__ == '__main__':
    if '--loop' in sys.argv:
        while True:
            n = run_once()
            if n:
                print(f"[message_delivery_worker] Đã xử lý {n} tin nhắn.")
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        run_once()
