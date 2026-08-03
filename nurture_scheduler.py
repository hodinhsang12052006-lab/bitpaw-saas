"""
Cronjob CHẠY NGẦM MỖI NGÀY 1 LẦN (Mã Nurture Part 2 audit) — trước đây AI Nurture hoàn toàn thủ
công (chủ tiệm phải tự bấm "Generate Campaign" mỗi lần muốn chăm sóc khách). Worker này quét
db.customers đối chiếu với db.nurture_schedule_rules (cấu hình riêng từng tenant, tạo qua
app.py:/api/ai/nurture/rules — vd "khách không ghé 30 ngày"). Khách nào khớp điều kiện: gọi
Claude (qua AINurturingEngine.generate_single_nurture_message, xem ai_nurturing_engine.py) sinh
1 tin nhắn, rồi đẩy vào db.campaign_messages — APPROVED (gửi thẳng, message_delivery_worker.py
sẽ gửi) nếu rule.auto_send=True, hoặc PENDING (vào hàng chờ duyệt tay, y hệt UI đã có) nếu False.

CÁCH CHẠY:
    python nurture_scheduler.py            # quét 1 lần rồi thoát — dùng với cron thật:
                                            #   0 8 * * * cd /path/to/project && python nurture_scheduler.py
    python nurture_scheduler.py --loop      # tự lặp lại mỗi 24h — tiện cho môi trường không có cron
"""
import sys
import time
from datetime import datetime

from mongo_client import db
from ai_context_engine import AIContextEngine
from ai_nurturing_engine import AINurturingEngine, recompute_customer_segments

LOOP_SLEEP_SECONDS = 24 * 3600


def _customer_matches_rule(customer, rule):
    """Điều kiện DUY NHẤT hiện hỗ trợ: 'đã bao nhiêu ngày kể từ lần mua/ghé gần nhất'
    (last_purchase_at, do recompute_customer_segments() tính lại mỗi lần chạy worker)."""
    last_purchase_at = customer.get('last_purchase_at')
    if not last_purchase_at:
        return False  # chưa từng mua gì -> không áp dụng rule "bao lâu chưa ghé"
    try:
        days_since = (datetime.now() - datetime.fromisoformat(last_purchase_at)).days
    except (TypeError, ValueError):
        return False
    return days_since >= int(rule.get('condition_days', 30))


def _already_triggered_recently(business_id, rule_id, customer_id, cooldown_days):
    """Chặn spam: rule 'không ghé 30 ngày' vẫn ĐÚNG mỗi ngày sau khi đã khớp lần đầu — không có
    cooldown thì worker sẽ nhắn lại đúng khách đó MỖI NGÀY vô thời hạn."""
    trigger = db.nurture_rule_triggers.find_one({
        'business_id': business_id, 'rule_id': rule_id, 'customer_id': customer_id,
    })
    if not trigger:
        return False
    try:
        last_triggered = datetime.fromisoformat(trigger['last_triggered_at'])
    except (KeyError, ValueError):
        return False
    return (datetime.now() - last_triggered).days < cooldown_days


def _mark_triggered(business_id, rule_id, customer_id):
    db.nurture_rule_triggers.update_one(
        {'business_id': business_id, 'rule_id': rule_id, 'customer_id': customer_id},
        {'$set': {'last_triggered_at': datetime.now().isoformat()}},
        upsert=True,
    )


def _process_rule(rule):
    business_id = rule['business_id']
    rule_id = rule['id']
    biz = db.businesses.find_one({'id': business_id}, {'name': 1, '_id': 0})
    business_name = (biz or {}).get('name') or 'BitPaw'
    industry = rule.get('industry') or 'retail'
    cooldown_days = int(rule.get('cooldown_days', 14))

    customers = list(db.customers.find({'business_id': business_id}, {'_id': 0}))
    triggered_count = 0

    for cust in customers:
        if not _customer_matches_rule(cust, rule):
            continue
        cust_id = cust.get('id')
        if _already_triggered_recently(business_id, rule_id, cust_id, cooldown_days):
            continue

        cust_phone = cust.get('phone')
        purchase_history = (
            AIContextEngine._load_purchase_history(business_id, cust_phone) if cust_phone else []
        )

        try:
            message_body = AINurturingEngine.generate_single_nurture_message(
                business_name, industry, rule.get('goal', 'RECALL'), rule.get('tone', 'friendly'),
                cust.get('name'), purchase_history, trigger_reason=rule.get('name'),
            )
        except Exception as e:
            print(f"[nurture_scheduler] Lỗi sinh nội dung Claude cho customer_id={cust_id}: {e}")
            continue

        approval_status = 'APPROVED' if rule.get('auto_send') else 'PENDING'
        db.campaign_messages.insert_one({
            'id': f"auto-{rule_id}-{cust_id}-{int(datetime.now().timestamp())}",
            'business_id': business_id,
            'campaign_id': f"auto-rule-{rule_id}",
            'customer_id': cust_id,
            'step_delay': 0,
            'message_body': message_body,
            'channel': rule.get('channel', 'zalo_oa'),
            'approval_status': approval_status,
            'source': 'auto_rule',
            'rule_id': rule_id,
            'created_at': datetime.now().isoformat(),
        })
        _mark_triggered(business_id, rule_id, cust_id)
        triggered_count += 1

    if triggered_count:
        print(f"[nurture_scheduler] business_id={business_id} rule='{rule.get('name')}': {triggered_count} khách được đẩy kịch bản.")


def run_once():
    print(f"[nurture_scheduler] Bắt đầu quét lúc {datetime.now().isoformat()}")
    active_rules = list(db.nurture_schedule_rules.find({'is_active': True}, {'_id': 0}))
    if not active_rules:
        print("[nurture_scheduler] Không có rule nào đang active.")
        return

    # business_id nào có rule active thì tính lại segment (last_purchase_at/nurturing_status)
    # trước — tránh tính lại cho toàn bộ tenant kể cả những tenant không dùng tính năng này.
    businesses_with_rules = {r['business_id'] for r in active_rules}
    for business_id in businesses_with_rules:
        try:
            recompute_customer_segments(business_id)
        except Exception as e:
            print(f"[nurture_scheduler] Lỗi recompute_customer_segments business_id={business_id}: {e}")

    for rule in active_rules:
        try:
            _process_rule(rule)
        except Exception as e:
            print(f"[nurture_scheduler] Lỗi xử lý rule {rule.get('id')} (business_id={rule.get('business_id')}): {e}")


if __name__ == '__main__':
    if '--loop' in sys.argv:
        while True:
            run_once()
            time.sleep(LOOP_SLEEP_SECONDS)
    else:
        run_once()
