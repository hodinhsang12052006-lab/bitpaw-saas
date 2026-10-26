# -*- coding: utf-8 -*-
"""AI Nurturing Engine — Module 3 overhaul (Task 2 + Task 3 of the Marketing/Growth audit).

predict_churn_risk() is a rule-based RFM-style classifier (recency + the customer's spend rank
inside the shop's OWN spend distribution — currency agnostic; notes in the shop's language),
run for real against MongoDB order history by recompute_customer_segments().

generate_nurturing_copy() is a full rewrite: the old version was static, hardcoded
per-industry/goal/tone string templates — not actually AI at all despite the module's
name. It now makes a real DeepSeek call, grounded in the customer's ACTUAL purchase
history (passed in by the caller, sourced from AIContextEngine._load_purchase_history —
reused rather than re-queried), and degrades gracefully to a small set of honest, non
-industry-specific fallback lines if DeepSeek is unavailable — it never fabricates a
history the customer doesn't have.

get_sample_customers() has been removed — confirmed dead code (never called from
app.py), a leftover demo-data generator from before real MongoDB data was wired in.
"""

import os
import bisect
import json
import re
import datetime


class AINurturingEngine:
    @staticmethod
    def predict_churn_risk(last_purchase_days, total_spending, source_platform=None, spend_rank=None, lang='en'):
        """
        Rule-based RFM-style risk assessment (not a trained model).
        Spend tier = the customer's rank inside THIS shop's own spend distribution (spend_rank = share of the shop's paying
        customers who spent less, 0..1 — see spend_rank()), so it works the same in USD, AUD or VND. The old fixed VND tiers
        (1M/5M/10M) put every USD/AUD customer at 50. Without a rank (caller has no distribution) the base is a neutral 50.
        Notes are in the shop's language and never suggest a gift/voucher the owner has not offered.
        Returns: (nurturing_status, potential_score, ai_notes)
        """
        en = lang == 'en'
        r = spend_rank if isinstance(spend_rank, (int, float)) else None
        if r is not None and r >= 0.90:
            potential_score = 95
        elif r is not None and r >= 0.75:
            potential_score = 80
        elif r is not None and r >= 0.50:
            potential_score = 65
        else:
            potential_score = 50

        # Penalize for days since last purchase
        if last_purchase_days > 90:
            nurturing_status = "CHURN_RISK"
            potential_score = max(5, potential_score - 45)
            ai_notes = ("No purchase in over 3 months — high risk of not coming back. Worth a personal win-back message." if en else
                        "Hơn 3 tháng chưa phát sinh giao dịch — nguy cơ không quay lại cao. Nên gửi tin hỏi thăm riêng.")
        elif last_purchase_days > 45:
            nurturing_status = "HIBERNATING"
            potential_score = max(20, potential_score - 25)
            ai_notes = ("Has not been back for over 45 days. A friendly check-in or rebooking reminder fits." if en else
                        "Hơn 45 ngày chưa quay lại. Phù hợp gửi tin hỏi thăm hoặc nhắc đặt lịch.")
        elif last_purchase_days > 21:
            nurturing_status = "NEEDS_CARE"
            potential_score = max(40, potential_score - 10)
            ai_notes = ("Over 3 weeks since the last visit — close to the usual time to come back. A short check-in fits." if en else
                        "Hơn 3 tuần từ lần ghé gần nhất — sắp tới lúc thường quay lại. Phù hợp gửi tin thăm hỏi ngắn.")
        else:
            nurturing_status = "REGULAR"
            ai_notes = ("Active regular customer. Keep in touch without over-messaging." if en else
                        "Khách đang ghé đều. Giữ liên lạc vừa phải, không nhắn quá nhiều.")
        if r is not None and r >= 0.90:
            ai_notes += (" Among this shop's top 10% spenders." if en else " Thuộc nhóm 10% khách chi tiêu nhiều nhất của tiệm.")

        # Source platform modifiers (cosmetic — only appends a note, never changes the score/status)
        if source_platform in ('facebook', 'messenger', 'zalo', 'zalo_oa'):
            ai_notes += (" Usually reaches the shop through social messaging." if en else " Thường tương tác online qua tin nhắn mạng xã hội.")
        elif source_platform == 'pos':
            ai_notes += (" Usually buys in person at the counter." if en else " Thói quen mua trực tiếp tại quầy thanh toán.")

        return nurturing_status, potential_score, ai_notes

    @staticmethod
    def _format_purchase_history(purchase_history):
        """Chuyển list kết quả AIContextEngine._load_purchase_history() thành text tự
        nhiên cho prompt. Trả về None nếu khách chưa từng mua gì — KHÔNG bịa lịch sử."""
        if not purchase_history:
            return None
        lines = []
        for h in purchase_history[:5]:
            prod = (h.get('products') or {}) if isinstance(h, dict) else {}
            name = prod.get('name') or 'sản phẩm/dịch vụ'
            qty = h.get('quantity') or 1
            when = (h.get('created_at') or '')[:10]
            lines.append(f"- {name} x{qty}" + (f" ({when})" if when else ""))
        return "\n".join(lines) if lines else None

    @staticmethod
    def _fallback_copy(customer_name, lang='vi'):
        """Dự phòng an toàn khi DeepSeek không khả dụng — NGẮN, TRUNG TÍNH, không bịa
        chi tiết mua hàng cụ thể nào (khác với bản cũ vốn có sẵn chi tiết sản phẩm giả
        định theo ngành mà khách có thể chưa từng mua)."""
        if lang == 'en':
            name = customer_name or "there"
            return {
                "3days": f"Hi {name}, thanks for visiting us recently! If there's anything we can help with, just reply here.",
                "7days": f"Hi {name}, we'd love to see you again — book your next visit whenever suits you.",
                "14days": f"Hi {name}, it's been a little while! Reply to this message and we'll find you a time that works.",
            }
        name = customer_name or "bạn"
        return {
            "3days": f"Chào {name}! Cảm ơn {name} đã ghé ủng hộ gần đây. Có gì cần hỗ trợ thêm, nhắn em ngay nhé!",
            "7days": f"{name} ơi, lâu rồi chưa thấy ghé lại. Bên em vẫn luôn sẵn sàng phục vụ {name} bất cứ khi nào ạ.",
            "14days": f"{name} ơi, đã một thời gian rồi chưa gặp lại! Trả lời tin này, bên em xếp giờ phù hợp cho {name} nhé.",
        }

    @staticmethod
    def _goal_meaning(goal):
        return {
            'RECALL': "win this customer back — they have not returned in a while",
            'UPSELL': "encourage this already-engaged customer to buy more / try something new",
        }.get((goal or '').upper(), "re-engage this customer")

    @staticmethod
    def _call_deepseek(system_prompt, user_prompt, max_tokens=500, temperature=0.8, json_mode=False, business_id=None):
        """Điểm gọi LLM DUY NHẤT của module này — đi qua ai_gateway (Phase 1): 1 dòng sổ db.ai_usage token thật
        (tính năng 'nurture'), timeout + thử lại lỗi tạm thời, cổng gói 'crm_ai' lúc chạy (tiệm cũ chưa có gói = Empire).
        business_id=None -> gateway lấy tiệm trong phiên đăng nhập (route của chủ tiệm). Gói không có CRM + AI ->
        ai_gateway.AIPlanBlocked (các hàm generate_* bên dưới rơi về câu mẫu trung thực, không gọi AI)."""
        if not os.environ.get('DEEPSEEK_API_KEY'):
            raise RuntimeError("DEEPSEEK_API_KEY chưa được cấu hình.")
        import ai_gateway
        return ai_gateway.text('nurture', business_id, system_prompt, user_prompt, temperature=temperature,
                               max_tokens=max_tokens, json_mode=json_mode, require='crm_ai')

    @staticmethod
    def generate_nurturing_copy(business_name, industry, goal, tone, customer_name, purchase_history=None, lang='vi',
                                business_id=None):
        """
        Real LLM-generated (DeepSeek — Mã "Hợp nhất AI bằng DeepSeek" audit), personalized
        3/7/14-day nurturing message sequence — grounded in this customer's ACTUAL purchase
        history when available. Replaces the old static per-industry/goal/tone string templates.

        Returns: {"3days": str, "7days": str, "14days": str}
        """
        name = customer_name or ("there" if lang == 'en' else "bạn")
        history_snippet = AINurturingEngine._format_purchase_history(purchase_history)

        if not os.environ.get('DEEPSEEK_API_KEY'):
            return AINurturingEngine._fallback_copy(name, lang)

        history_block = (
            f"Their real recent purchase history:\n{history_snippet}"
            if history_snippet else
            "No purchase history on file yet for this customer — do NOT invent one; keep the message general and welcoming instead."
        )

        system_prompt = (
            "You write short customer-retention messages for local businesses. "
            "Reference the customer's ACTUAL past purchases naturally where relevant instead of "
            "generic language — but never invent a purchase that wasn't listed. Keep each message "
            "warm, human, and under 300 characters — not a corporate blast. "
            + ("Write in natural US/Australian English. " if lang == 'en' else "Write in natural, conversational Vietnamese. ")
            + "Return STRICT JSON only, exactly this shape: "
            '{"3days": "...", "7days": "...", "14days": "..."}'
        )
        user_prompt = (
            f"Business: {business_name or 'this business'}, a {industry or 'local'} business. "
            f"Customer name: {name}. Tone: {tone or 'friendly'}. Goal: {AINurturingEngine._goal_meaning(goal)}.\n\n"
            f"{history_block}\n\n"
            "Write THREE short messages meant to be sent 3 days, 7 days, and 14 days apart (only if "
            "the customer hasn't already responded/returned by then)."
        )

        try:
            raw = AINurturingEngine._call_deepseek(system_prompt, user_prompt, max_tokens=500, temperature=0.8, json_mode=True,
                                                   business_id=business_id)
            raw = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            if all(k in parsed and parsed[k] for k in ("3days", "7days", "14days")):
                return {"3days": parsed["3days"], "7days": parsed["7days"], "14days": parsed["14days"]}
            return AINurturingEngine._fallback_copy(name, lang)
        except Exception:
            return AINurturingEngine._fallback_copy(name, lang)

    @staticmethod
    def generate_single_nurture_message(business_name, industry, goal, tone, customer_name,
                                         purchase_history=None, trigger_reason=None, lang='vi', business_id=None):
        """1 tin nhắn DUY NHẤT (không phải chuỗi 3/7/14 ngày) — dùng bởi nurture_scheduler.py
        khi 1 rule tự động vừa khớp điều kiện (vd 'không ghé 30 ngày'), cần 1 tin gửi NGAY,
        không phải lên lịch trước 3 mốc thời gian."""
        name = customer_name or ("there" if lang == 'en' else "bạn")
        history_snippet = AINurturingEngine._format_purchase_history(purchase_history)

        if not os.environ.get('DEEPSEEK_API_KEY'):
            return AINurturingEngine._fallback_copy(name, lang)['7days']

        history_block = (
            f"Their real recent purchase history:\n{history_snippet}" if history_snippet else
            "No purchase history on file yet — do NOT invent one; keep the message general and welcoming."
        )
        system_prompt = (
            "You write short, warm, human customer-retention messages "
            + ("in natural US/Australian English " if lang == 'en' else "in Vietnamese ")
            + "for local businesses. Never invent purchase history. Output ONLY the message text itself, "
            "nothing else — no quotes, no labels, no explanation, under 300 characters."
        )
        user_prompt = (
            f"Business: {business_name or 'this business'}, a {industry or 'local'} business. "
            f"Customer: {name}. Tone: {tone or 'friendly'}.\n"
            f"Trigger reason this message is being sent now: {trigger_reason or AINurturingEngine._goal_meaning(goal)}.\n"
            f"Goal: {AINurturingEngine._goal_meaning(goal)}.\n\n{history_block}"
        )
        try:
            text = AINurturingEngine._call_deepseek(system_prompt, user_prompt, max_tokens=300, temperature=0.8,
                                                    business_id=business_id)
            return text.strip().strip('"')
        except Exception:
            return AINurturingEngine._fallback_copy(name, lang)['7days']

    @staticmethod
    def generate_sequence_template(business_name, industry, goal, tone, lang='en', business_id=None):
        """1 lần gọi AI cho CẢ chiến dịch: chuỗi 3 tin (3/7/14 ngày) có chỗ trống {first_name}, {last_service},
        {days_since_visit} — mỗi khách được điền DỮ LIỆU THẬT của chính họ. Chiến dịch 1.000 khách vẫn xong trong
        vài giây (trước đây gọi AI lần lượt từng khách trong 1 request — vượt thời gian chạy của máy chủ)."""
        en = lang == 'en'
        fallback = {
            "3days": ("Hi {first_name}, thanks again for choosing " + (business_name or "us") + "! How did your {last_service} turn out? Reply anytime.") if en else
                     ("Chào {first_name}, cảm ơn bạn đã chọn " + (business_name or "tiệm") + "! {last_service} của bạn thế nào? Cần gì cứ nhắn tiệm nhé."),
            "7days": "Hi {first_name}, ready for your next {last_service}? Book a time that suits you — we'd love to see you." if en else
                     "Chào {first_name}, bạn có muốn đặt lịch {last_service} lần tới không? Tiệm luôn sẵn sàng.",
            "14days": "Hi {first_name}, it's been {days_since_visit} days — reply to this message and we'll save you a spot." if en else
                      "Chào {first_name}, đã {days_since_visit} ngày rồi — trả lời tin này để tiệm giữ chỗ cho bạn nhé.",
        }
        if not os.environ.get('DEEPSEEK_API_KEY'):
            return fallback
        system_prompt = (
            "You write short, warm customer-retention text messages for a local business. "
            + ("Write in natural US/Australian English. " if en else "Write in natural Vietnamese. ")
            + "Use these placeholders exactly where they fit: {first_name}, {last_service}, {days_since_visit}. "
            "Each message under 190 characters (a booking link is added after it; long texts cost extra SMS segments), "
            "no prices or offers that were not given, no emoji spam (max 1). Only use {days_since_visit} to talk about time — "
            "never count time between messages. Don't claim things you can't know (a favourite seat, a saved spot, a new product). "
            'Return STRICT JSON only: {"3days": "...", "7days": "...", "14days": "..."}'
        )
        user_prompt = (f"Business: {business_name or 'this business'} ({industry or 'local'} business). Tone: {tone or 'friendly'}. "
                       f"Goal: {AINurturingEngine._goal_meaning(goal)}. Messages are sent 3, 7 and 14 days after the campaign starts, "
                       "only if the customer has not come back.")
        try:
            raw = AINurturingEngine._call_deepseek(system_prompt, user_prompt, max_tokens=600, temperature=0.8, json_mode=True,
                                                   business_id=business_id)
            raw = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            if all(isinstance(parsed.get(k), str) and parsed[k].strip() for k in ("3days", "7days", "14days")):
                return {k: parsed[k].strip() for k in ("3days", "7days", "14days")}
        except Exception:
            pass
        return fallback

    @staticmethod
    def fill_template(text, first_name, last_service, days_since_visit, lang='en', booking_link=None):
        en = lang == 'en'
        # số ngày luôn kèm đơn vị (AI hay viết "đã {days_since_visit} rồi" -> "đã 45 rồi")
        unit = 'days' if en else 'ngày'
        days_txt = f"{days_since_visit if days_since_visit else ('a few' if en else 'vài')} {unit}"
        out = re.sub(r'\{days_since_visit\}(?:\s*(?:ngày|days?)(?![A-Za-zÀ-ỹ]))?', lambda m: days_txt, text)
        out = (out.replace('{first_name}', first_name or ('there' if en else 'bạn'))
                  .replace('{last_service}', last_service or ('visit' if en else 'dịch vụ')))
        out = re.sub(r'\s{2,}', ' ', out).strip()
        # Link đặt lịch online thật của tiệm ở cuối tin (như tin "rebook" của Fresha/Square) — khách bấm là đặt được ngay
        if booking_link and booking_link not in out:
            out += (f" Book: {booking_link}" if en else f" Đặt lịch: {booking_link}")
        return out

    @staticmethod
    def booking_link(business_id, industry, base_url=None):
        """Trang đặt lịch công khai của tiệm (chỉ ngành có đặt lịch online: Nails, Spa)."""
        base = (base_url or os.environ.get('PUBLIC_BASE_URL') or 'https://www.bitpawsoftware.com').rstrip('/')
        if industry in ('nail', 'nails'):
            return f"{base}/booking/nail/qr/{business_id}"
        if industry == 'spa':
            return f"{base}/booking/qr/{business_id}"
        return None

    @staticmethod
    def real_recommendations(business_id, industry, lang='en', currency='USD'):
        """Đề xuất từ SỐ LIỆU THẬT của tiệm (khách lâu chưa quay lại, khách chi tiêu cao đang nguội, giờ trống tuần tới,
        dịch vụ có tỷ lệ quay lại thấp). Thay cho câu viết sẵn có số bịa ("Có 12 khách VIP...") giống hệt nhau mọi tiệm."""
        from mongo_client import db
        en = lang == 'en'
        now = datetime.datetime.now()
        recs = []
        # "chi tiêu cao" = top 25% chi tiêu của CHÍNH tiệm (trước: 5.000.000đ / 400 cố định theo tiền tệ — số tự đặt)
        vip_threshold = top_spend_threshold(business_id)
        churn = db.customers.count_documents({'business_id': business_id, 'nurturing_status': 'CHURN_RISK'})
        cold_vip = db.customers.count_documents({'business_id': business_id, 'total_spent': {'$gte': vip_threshold},
                                                 'last_purchase_at': {'$lt': (now - datetime.timedelta(days=30)).isoformat()}}) \
            if vip_threshold is not None else 0
        if cold_vip:
            recs.append({"type": "CHURN_ALERT", "text": (f"{cold_vip} high-spending customers have not been back in over 30 days. Send them a personal 'we miss you' message." if en else
                                                         f"{cold_vip} khách chi tiêu cao đã hơn 30 ngày chưa quay lại. Nên gửi tin hỏi thăm riêng cho nhóm này.")})
        if churn:
            recs.append({"type": "CHURN_ALERT", "text": (f"{churn} customers are at risk of not coming back. Start a 3-step win-back campaign for this group." if en else
                                                         f"{churn} khách có nguy cơ không quay lại. Nên chạy chuỗi 3 tin chăm sóc cho nhóm này.")})
        week = [(now + datetime.timedelta(days=i)).date().isoformat() for i in range(1, 8)]
        booked = {}
        for a in db.appointments.find({'business_id': business_id, 'status': {'$in': ['pending', 'confirmed']},
                                       'book_time': {'$gte': week[0], '$lt': (now + datetime.timedelta(days=8)).date().isoformat()}}, {'book_time': 1, '_id': 0}):
            d = str(a.get('book_time', ''))[:10]
            booked[d] = booked.get(d, 0) + 1
        if industry in ('nail', 'spa') and booked is not None:
            quiet = min(week, key=lambda d: booked.get(d, 0))
            qd = datetime.date.fromisoformat(quiet)
            recs.append({"type": "CAMPAIGN_SUGGESTION", "text": (f"Your quietest day next week is {qd.strftime('%A %b %d')} ({booked.get(quiet, 0)} bookings). Offer a time-limited slot that day to past customers." if en else
                                                                 f"Ngày vắng nhất tuần tới là {qd.strftime('%d/%m')} ({booked.get(quiet, 0)} lịch). Nên mời khách cũ đặt khung giờ ngày đó.")})
        # dịch vụ bán nhiều nhưng khách ít quay lại (90 ngày)
        since = (now - datetime.timedelta(days=90)).isoformat()
        rows = list(db.order_items.aggregate([
            {'$match': {'business_id': business_id, 'created_at': {'$gte': since}, 'product_id': {'$ne': None}, 'customer_phone': {'$nin': [None, '']}}},
            {'$group': {'_id': {'p': '$product_id', 'c': '$customer_phone'}, 'n': {'$sum': 1}}},
            {'$group': {'_id': '$_id.p', 'customers': {'$sum': 1}, 'repeat': {'$sum': {'$cond': [{'$gt': ['$n', 1]}, 1, 0]}}}},
            {'$match': {'customers': {'$gte': 5}}},
        ]))
        if rows:
            worst = min(rows, key=lambda r: r['repeat'] / r['customers'])
            prod = db.products.find_one({'id': worst['_id']}, {'name': 1, '_id': 0}) or {}
            rate = round(100 * worst['repeat'] / worst['customers'])
            if prod.get('name') and rate < 40:
                recs.append({"type": "REVENUE_OPTIMIZE", "text": (f"Only {rate}% of {worst['customers']} customers who had '{prod['name']}' came back for it in 90 days. Send an aftercare tip 3 days after this service." if en else
                                                                  f"Chỉ {rate}% trong {worst['customers']} khách làm '{prod['name']}' quay lại trong 90 ngày. Nên gửi tin hướng dẫn chăm sóc sau 3 ngày.")})
        if not recs:
            recs.append({"type": "CAMPAIGN_SUGGESTION", "text": ("Not enough history yet for data-based suggestions. Add customers and record sales in POS — suggestions appear automatically." if en else
                                                                 "Chưa đủ dữ liệu để đề xuất. Thêm khách hàng và ghi bán hàng qua POS — đề xuất sẽ tự xuất hiện.")})
        return recs


def recompute_customer_segments(business_id):
    """Tính lại last_purchase_at/nurturing_status/potential_score/ai_notes cho MỌI khách của 1
    tenant, dựa trên đơn hàng gần nhất THẬT trong db.orders (Mã Nurture Part 2 audit). Hàm
    module-level (không phải staticmethod của AINurturingEngine) vì thao tác trên nhiều khách
    + đọc/ghi Mongo trực tiếp, khác các hàm tính toán thuần của class ở trên.

    DÙNG CHUNG bởi route thủ công app.py:/api/ai/nurture/import-data VÀ nurture_scheduler.py
    (cron tự động) — để 2 nơi không tính "khách bao lâu chưa mua" ra 2 công thức khác nhau,
    tránh cron tự động và nút bấm thủ công cho ra 2 kết quả lệch nhau."""
    from mongo_client import db  # import lazy: tránh vòng import khi module này được app.py import ở module-level

    customers = list(db.customers.find(
        {'business_id': business_id}, {'id': 1, 'phone': 1, 'total_spent': 1, '_id': 0}
    ))
    now = datetime.datetime.now()
    recomputed = 0
    # hạng chi tiêu theo phân bố chi tiêu của CHÍNH tiệm (không phụ thuộc tiền tệ); ghi chú theo ngôn ngữ của tiệm
    spends = _sorted_spends(customers)
    try:
        import messaging
        lang = messaging.get_settings(business_id)['language']
    except Exception:
        lang = 'en'

    for cust in customers:
        phone = cust.get('phone')
        total_spent = cust.get('total_spent') or 0
        if not phone:
            continue

        # customer_phone nằm trong order_doc['metadata'] (schema chuẩn hoá Giai đoạn 3 audit),
        # không còn top-level.
        last_order = db.orders.find_one(
            {'business_id': business_id, 'metadata.customer_phone': phone},
            {'created_at': 1, '_id': 0}, sort=[('created_at', -1)]
        )

        update_fields = {'source_platform': 'pos'}
        if last_order and last_order.get('created_at'):
            try:
                last_purchase_days = (now - datetime.datetime.fromisoformat(last_order['created_at'])).days
            except Exception:
                last_purchase_days = None
            if last_purchase_days is not None:
                status, score, notes = AINurturingEngine.predict_churn_risk(
                    last_purchase_days, total_spent, source_platform='pos',
                    spend_rank=spend_rank(spends, total_spent), lang=lang
                )
                update_fields.update({
                    'nurturing_status': status, 'potential_score': score, 'ai_notes': notes,
                    'last_purchase_at': last_order['created_at'],
                })
        else:
            update_fields.update({'nurturing_status': 'NEW', 'potential_score': 50, 'ai_notes': None})

        db.customers.update_one({'id': cust['id'], 'business_id': business_id}, {'$set': update_fields})
        recomputed += 1

    return recomputed


def _sorted_spends(customers):
    """Chi tiêu (> 0) của các khách, tăng dần — phân bố chi tiêu của chính tiệm."""
    out = []
    for c in customers:
        try:
            v = float(c.get('total_spent') or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.append(v)
    return sorted(out)


def spend_rank(sorted_spends, value):
    """Tỷ lệ khách (có chi tiêu) của tiệm chi ÍT HƠN khách này, 0..1. Không chi tiêu / chưa có dữ liệu -> 0."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0 or not sorted_spends:
        return 0.0
    return bisect.bisect_left(sorted_spends, v) / len(sorted_spends)


def top_spend_threshold(business_id, top_fraction=0.25):
    """Mức chi tiêu tối thiểu để vào nhóm top `top_fraction` khách chi nhiều nhất của tiệm (tiền tệ nào cũng đúng).
    None nếu tiệm chưa có khách nào có chi tiêu."""
    from mongo_client import db
    spends = _sorted_spends(db.customers.find({'business_id': business_id, 'total_spent': {'$gt': 0}}, {'total_spent': 1, '_id': 0}))
    if not spends:
        return None
    idx = min(len(spends) - 1, max(0, int(len(spends) * (1 - top_fraction))))
    return spends[idx]


def customer_fill_values(business_id, customer):
    """(first_name, last_service, days_since_visit) THẬT của 1 khách — để điền vào mẫu tin của chiến dịch."""
    from ai_context_engine import AIContextEngine
    first = (customer.get('name') or '').strip().split(' ')[0]
    last_service = ''
    phone = customer.get('phone')
    if phone:
        for h in AIContextEngine._load_purchase_history(business_id, phone, limit=5):
            name = ((h.get('products') or {}) if isinstance(h, dict) else {}).get('name')
            if name:
                last_service = name
                break
    days = None
    lp = customer.get('last_purchase_at')
    if lp:
        try:
            days = max(0, (datetime.datetime.now() - datetime.datetime.fromisoformat(str(lp)[:19])).days)
        except ValueError:
            days = None
    return first, last_service, days
