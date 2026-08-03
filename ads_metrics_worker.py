"""
Background Worker RIÊNG (Mã AI Ads Part 2.3 audit) — không chạy chung process với Flask. Định
kỳ kéo insight THẬT (impressions, clicks, spend, ctr, cpc, reach) từ Facebook Graph API cho mọi
campaign platform='facebook' đang có trong db.ad_campaigns, ghi vào db.ad_campaign_metrics.

CÁCH CHẠY:
    python ads_metrics_worker.py

Production: chạy dưới supervisor/systemd/pm2 (hoặc cron mỗi 15 phút gọi sync_all_once() 1 lần
thay vì vòng lặp vô hạn) — đây là 1 script chạy vô hạn (while True), không phải request-response.
"""
import time
from datetime import datetime

import ad_platform_tokens
import facebook_ads_client
from facebook_ads_client import FacebookTokenExpiredError
from mongo_client import db

POLL_INTERVAL_SECONDS = 900  # 15 phút/lần — Facebook insight bản thân cũng không real-time hơn vài phút
DATE_PRESET = 'yesterday'    # đổi thành 'today' nếu chấp nhận số liệu trong-ngày có thể chưa đầy đủ


def _sync_one_campaign(campaign_doc):
    business_id = campaign_doc['business_id']
    campaign_id = campaign_doc['campaign_id']

    token_info = ad_platform_tokens.get_facebook_token(business_id)
    if not token_info:
        print(f"[ads_metrics_worker] Bỏ qua campaign {campaign_id}: tenant {business_id} không còn token Facebook.")
        return
    if token_info.get('status') == 'expired':
        # Đã biết token này hết hạn từ lượt trước — không gọi Facebook lại vô ích mỗi 15 phút,
        # chờ tenant tự kết nối lại (save_facebook_token() sẽ tự reset status='active').
        print(f"[ads_metrics_worker] Bỏ qua campaign {campaign_id}: token Facebook của tenant {business_id} đã hết hạn, chờ kết nối lại.")
        return

    try:
        insights = facebook_ads_client.fetch_campaign_insights(
            token_info['access_token'], campaign_id, date_preset=DATE_PRESET,
        )
    except FacebookTokenExpiredError as e:
        # Mã "Go-Live Pentest" audit — phát hiện lần đầu token hết hạn: đánh dấu lại để (1) ngưng
        # retry vô ích các lượt sau, (2) UI đọc được để báo "kết nối lại Facebook" cho chủ tiệm.
        ad_platform_tokens.mark_facebook_token_invalid(business_id, str(e))
        print(f"[ads_metrics_worker] Token Facebook hết hạn (business_id={business_id}), đã đánh dấu status='expired': {e}")
        return
    today = datetime.now().strftime('%Y-%m-%d')

    # upsert theo (campaign_id, date): chạy worker nhiều lần/ngày chỉ ghi ĐÈ đúng 1 dòng của
    # ngày đó, không tạo thêm bản ghi trùng mỗi lần chạy (Idempotent theo ngày).
    db.ad_campaign_metrics.update_one(
        {'campaign_id': campaign_id, 'date': today},
        {'$set': {
            'business_id': business_id,
            'campaign_id': campaign_id,
            'date': today,
            'impressions': int(float(insights.get('impressions', 0))),
            'clicks': int(float(insights.get('clicks', 0))),
            'spend': float(insights.get('spend', 0)),
            'ctr': float(insights.get('ctr', 0)),
            'cpc': float(insights.get('cpc', 0)),
            'reach': int(float(insights.get('reach', 0))),
            'synced_at': datetime.now().isoformat(),
        }},
        upsert=True,
    )
    print(f"[ads_metrics_worker] Đồng bộ xong campaign {campaign_id}: "
          f"impressions={insights.get('impressions')} clicks={insights.get('clicks')} spend={insights.get('spend')}")


def sync_all_once():
    """1 lượt quét — 1 campaign lỗi (vd token hết hạn) không được chặn các campaign còn lại."""
    campaigns = list(db.ad_campaigns.find({'platform': 'facebook'}, {'_id': 0}))
    synced = 0
    for c in campaigns:
        try:
            _sync_one_campaign(c)
            synced += 1
        except Exception as e:
            print(f"[ads_metrics_worker] Lỗi đồng bộ campaign {c.get('campaign_id')}: {e}")
    return synced


def run():
    print(f"[ads_metrics_worker] Bắt đầu, chu kỳ {POLL_INTERVAL_SECONDS}s.")
    while True:
        try:
            n = sync_all_once()
            print(f"[ads_metrics_worker] Đã đồng bộ {n} campaign.")
        except Exception as e:
            print(f"[ads_metrics_worker] Lỗi vòng lặp chính (không crash worker): {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == '__main__':
    run()
