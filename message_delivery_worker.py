"""
Gửi tin chăm sóc ĐÃ DUYỆT (db.campaign_messages) — giờ chỉ là LỚP MỎNG gọi messaging.pump() cho những tiệm còn tin chờ gửi.

Việc gửi thật nằm trong bộ gửi chung messaging.pump (chạy bởi cron Vercel /api/cron/messages + /api/cron/daily_tasks, và khi
chủ tiệm/nhân viên đang mở app): SMS (Twilio của tiệm), email, và Zalo/Messenger qua inbox_channels.send_text bằng kênh CHÍNH
tiệm đã nối ở Hộp thư chung (/inbox/channels), tới zalo_user_id / fb_psid của khách — chỉ trong khung trả lời của nền tảng
(Messenger 24 giờ, Zalo 48 giờ kể từ tin gần nhất của khách); ngoài khung thì SMS/email nếu khách có, không thì bỏ qua có ghi
lý do. Cùng khung giờ gửi của tiệm, danh sách từ chối nhận tin, chống gửi trùng, thử lại.

Trước đây file này tự gửi Zalo/Facebook và: (1) không được lên lịch ở đâu (vercel.json) nên không tin nào đi; (2) so kênh chữ
thường trong khi chiến dịch lưu 'ZALO'/'FACEBOOK'; (3) dùng token lưu riêng ở /api/ai/nurture/test-connection thay vì kênh
Hộp thư chung; (4) quét MỌI tin đã duyệt — cả SMS/EMAIL — rồi ghi đè 'failed'. Giờ file này KHÔNG ghi gì vào campaign_messages.

CÁCH CHẠY (tuỳ chọn — cron Vercel đã đủ):
    python message_delivery_worker.py            # 1 lượt rồi thoát
    python message_delivery_worker.py --loop      # lặp mỗi 60 giây (máy không có cron)
"""
import os
import sys
import time

# Ép stdout/stderr UTF-8 khi chạy standalone trên Windows — log tiếng Việt có dấu không làm chết process
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from mongo_client import db

POLL_INTERVAL_SECONDS = 60


def pending_business_ids():
    """Tiệm còn tin chăm sóc đã duyệt chưa xếp hàng gửi."""
    return sorted({b for b in db.campaign_messages.distinct('business_id', {'approval_status': 'APPROVED', 'queued': {'$ne': True}}) if b},
                  key=str)


def run_once(base_url=None, now_utc=None):
    """1 lượt: messaging.pump() cho từng tiệm còn tin chờ (tạo tin tới hạn + gửi). 1 tiệm lỗi không chặn tiệm khác."""
    import messaging
    total = {'businesses': 0, 'produced': 0, 'sent': 0, 'failed': 0, 'deferred': 0, 'skipped': 0, 'errors': []}
    base = base_url or os.environ.get('PUBLIC_BASE_URL', '')
    for bid in pending_business_ids():
        total['businesses'] += 1
        try:
            st = messaging.pump(bid, base_url=base, now_utc=now_utc)
            for k in ('produced', 'sent', 'failed', 'deferred', 'skipped'):
                total[k] += st.get(k, 0)
        except Exception as e:
            total['errors'].append(f"{bid}: {str(e)[:120]}")
            print(f"[message_delivery_worker] business_id={bid}: {e}")
    return total


if __name__ == '__main__':
    if '--loop' in sys.argv:
        while True:
            out = run_once()
            if out['businesses']:
                print(f"[message_delivery_worker] {out}")
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        print(run_once())
