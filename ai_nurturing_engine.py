# -*- coding: utf-8 -*-
"""AI Nurturing Engine — Module 3 overhaul (Task 2 + Task 3 of the Marketing/Growth audit).

predict_churn_risk() is kept as-is — it was already a reasonable rule-based RFM-style
classifier, it just had never been WIRED to any route (see app.py's
nurture_import_data / _recompute_customer_nurturing_segment, which now call it for
real against MongoDB order history instead of never calling it at all).

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
import json
import re
import datetime

from ai_deepseek_client import deepseek_chat_completion


class AINurturingEngine:
    @staticmethod
    def predict_churn_risk(last_purchase_days, total_spending, source_platform=None):
        """
        Rule-based RFM-style risk assessment for churn prediction.
        Returns: (nurturing_status, potential_score, ai_notes)
        """
        potential_score = 100

        # Adjust base score based on spending
        if total_spending > 10000000:
            potential_score = 95
        elif total_spending > 5000000:
            potential_score = 80
        elif total_spending > 1000000:
            potential_score = 65
        else:
            potential_score = 50

        # Penalize for days since last purchase
        if last_purchase_days > 90:
            nurturing_status = "CHURN_RISK"
            potential_score = max(5, potential_score - 45)
            ai_notes = "Khách hàng có nguy cơ rời bỏ cực cao. Đã hơn 3 tháng không phát sinh giao dịch. Cần tung kịch bản kéo khách khẩn cấp kèm quà tặng lớn."
        elif last_purchase_days > 45:
            nurturing_status = "HIBERNATING"
            potential_score = max(20, potential_score - 25)
            ai_notes = "Khách hàng đang ngủ đông. Đã lâu chưa thấy quay lại. Đề xuất gửi kịch bản upsell hoặc voucher chăm sóc định kỳ."
        elif last_purchase_days > 21:
            nurturing_status = "NEEDS_CARE"
            potential_score = max(40, potential_score - 10)
            ai_notes = "Khách hàng sắp chạm chu kỳ mua lại trung bình. Thích hợp gửi tin nhắn thăm hỏi, tặng ưu đãi nhẹ nhàng."
        else:
            nurturing_status = "REGULAR"
            ai_notes = "Khách hàng thân thiết, hoạt động tích cực. Giữ tần suất tương tác ổn định, gợi ý combo quà tặng sinh nhật hoặc tích điểm thành viên."

        # Source platform modifiers (cosmetic — only appends a note, never changes the score/status)
        if source_platform in ('facebook', 'zalo_oa'):
            ai_notes += " Thường tương tác online qua tin nhắn mạng xã hội."
        elif source_platform == 'pos':
            ai_notes += " Thói quen mua trực tiếp tại quầy thanh toán."

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
    def _fallback_copy(customer_name):
        """Dự phòng an toàn khi DeepSeek không khả dụng — NGẮN, TRUNG TÍNH, không bịa
        chi tiết mua hàng cụ thể nào (khác với bản cũ vốn có sẵn chi tiết sản phẩm giả
        định theo ngành mà khách có thể chưa từng mua)."""
        name = customer_name or "Sếp"
        return {
            "3days": f"Chào {name}! Cảm ơn {name} đã ghé ủng hộ gần đây. Có gì cần hỗ trợ thêm, nhắn em ngay nhé!",
            "7days": f"{name} ơi, lâu rồi chưa thấy ghé lại. Bên em vẫn luôn sẵn sàng phục vụ {name} bất cứ khi nào ạ.",
            "14days": f"Gửi {name} một ưu đãi nhỏ để {name} ghé lại trải nghiệm — nhắn em để nhận ưu đãi nhé!",
        }

    @staticmethod
    def _goal_meaning(goal):
        return {
            'RECALL': "win this customer back — they have not returned in a while",
            'UPSELL': "encourage this already-engaged customer to buy more / try something new",
        }.get((goal or '').upper(), "re-engage this customer")

    @staticmethod
    def _call_deepseek(system_prompt, user_prompt, max_tokens=500, temperature=0.8, json_mode=False):
        """Điểm gọi LLM DUY NHẤT của module này — đi qua ai_deepseek_client.py (Mã "Hợp nhất AI
        bằng DeepSeek" audit, thay thế Anthropic/Claude đã dùng trước đó). Không có nhánh
        Desktop-proxy ở đây vì AI Nurture chỉ chạy ở server/worker nền (nurture_scheduler.py),
        không có luồng Desktop App nào gọi tới."""
        api_key = os.environ.get('DEEPSEEK_API_KEY')
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY chưa được cấu hình.")
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        result = deepseek_chat_completion(payload, direct_api_key=api_key)
        return result['choices'][0]['message']['content']

    @staticmethod
    def generate_nurturing_copy(business_name, industry, goal, tone, customer_name, purchase_history=None):
        """
        Real LLM-generated (DeepSeek — Mã "Hợp nhất AI bằng DeepSeek" audit), personalized
        3/7/14-day nurturing message sequence — grounded in this customer's ACTUAL purchase
        history when available. Replaces the old static per-industry/goal/tone string templates.

        Returns: {"3days": str, "7days": str, "14days": str}
        """
        name = customer_name or "Sếp"
        history_snippet = AINurturingEngine._format_purchase_history(purchase_history)

        if not os.environ.get('DEEPSEEK_API_KEY'):
            return AINurturingEngine._fallback_copy(name)

        history_block = (
            f"Their real recent purchase history:\n{history_snippet}"
            if history_snippet else
            "No purchase history on file yet for this customer — do NOT invent one; keep the message general and welcoming instead."
        )

        system_prompt = (
            "You write short customer-retention messages for local Vietnamese businesses. "
            "Reference the customer's ACTUAL past purchases naturally where relevant instead of "
            "generic language — but never invent a purchase that wasn't listed. Keep each message "
            "warm, human, and under 300 characters — not a corporate blast. Write in Vietnamese, "
            "natural and conversational. Return STRICT JSON only, exactly this shape: "
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
            raw = AINurturingEngine._call_deepseek(system_prompt, user_prompt, max_tokens=500, temperature=0.8, json_mode=True)
            raw = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            if all(k in parsed and parsed[k] for k in ("3days", "7days", "14days")):
                return {"3days": parsed["3days"], "7days": parsed["7days"], "14days": parsed["14days"]}
            return AINurturingEngine._fallback_copy(name)
        except Exception:
            return AINurturingEngine._fallback_copy(name)

    @staticmethod
    def generate_single_nurture_message(business_name, industry, goal, tone, customer_name,
                                         purchase_history=None, trigger_reason=None):
        """1 tin nhắn DUY NHẤT (không phải chuỗi 3/7/14 ngày) — dùng bởi nurture_scheduler.py
        khi 1 rule tự động vừa khớp điều kiện (vd 'không ghé 30 ngày'), cần 1 tin gửi NGAY,
        không phải lên lịch trước 3 mốc thời gian."""
        name = customer_name or "Sếp"
        history_snippet = AINurturingEngine._format_purchase_history(purchase_history)

        if not os.environ.get('DEEPSEEK_API_KEY'):
            return AINurturingEngine._fallback_copy(name)['7days']

        history_block = (
            f"Their real recent purchase history:\n{history_snippet}" if history_snippet else
            "No purchase history on file yet — do NOT invent one; keep the message general and welcoming."
        )
        system_prompt = (
            "You write short, warm, human customer-retention messages in Vietnamese for local "
            "businesses. Never invent purchase history. Output ONLY the message text itself, "
            "nothing else — no quotes, no labels, no explanation, under 300 characters."
        )
        user_prompt = (
            f"Business: {business_name or 'this business'}, a {industry or 'local'} business. "
            f"Customer: {name}. Tone: {tone or 'friendly'}.\n"
            f"Trigger reason this message is being sent now: {trigger_reason or AINurturingEngine._goal_meaning(goal)}.\n"
            f"Goal: {AINurturingEngine._goal_meaning(goal)}.\n\n{history_block}"
        )
        try:
            text = AINurturingEngine._call_deepseek(system_prompt, user_prompt, max_tokens=300, temperature=0.8)
            return text.strip().strip('"')
        except Exception:
            return AINurturingEngine._fallback_copy(name)['7days']

    @staticmethod
    def get_industry_recommendations(industry):
        """
        Generates smart AI insights customized per industry.
        NOTE: still static per-industry text at this phase — not part of Module 3's
        Task 1-3 scope (database unification / churn logic / message personalization).
        Left unchanged intentionally; a natural next follow-up once this phase ships.
        """
        recs = {
            "nail": [
                {"type": "CHURN_ALERT", "text": "Có 12 khách hàng VIP của tiệm Nails chưa quay lại làm móng trong 30 ngày qua. Đề xuất chạy chiến dịch 'Sơn Gel Thu Sáng Tình Cảm' tặng voucher 25%."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Dự báo tuần này có 25 lịch hẹn làm móng trống ca sáng. Đề xuất gửi kịch bản 'Giờ vàng dưỡng móng' ưu đãi dọn da miễn phí khung giờ 9h-11h."},
                {"type": "REVENUE_OPTIMIZE", "text": "Khách hàng mua dịch vụ 'Đắp bột' thường có tỷ lệ quay lại thấp. Gợi ý gửi tin nhắn chăm sóc sau 3 ngày hướng dẫn cách bảo quản móng lâu hỏng."}
            ],
            "spa": [
                {"type": "CHURN_ALERT", "text": "Có 8 khách hàng đang dở dang liệu trình trị mụn 5 buổi chưa quay lại Spa quá 14 ngày. Đề xuất AI tự động gửi tin nhắn nhắc lịch."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Nhiệt độ ngoài trời tăng cao tuần này. Khách hàng quan tâm cao dịch vụ thải độc phục hồi da. Đề xuất chạy chiến dịch 'Thải độc detox mát rượi'."},
                {"type": "REVENUE_OPTIMIZE", "text": "Tỷ lệ mua thêm serum dưỡng sau liệu trình đạt thấp (12%). Đề xuất tích hợp combo tặng mẫu thử serum mini khi đặt liệu trình VIP."}
            ],
            "fnb": [
                {"type": "CHURN_ALERT", "text": "Có 45 khách hàng cũ hay đặt Cafe Muối/Trà Sữa chưa gọi món lại quá 10 ngày. Đề xuất gửi tin nhắn tặng code Freeship ly trà chiều."},
                {"type": "CAMPAIGN_SUGGESTION", "text": "Thứ 7 tuần này có giải đấu bóng đá lớn. Đề xuất chạy chiến dịch 'Đồng hành túc cầu' tặng đĩa mồi nhắm khoai tây chiên khi đặt Combo bia."},
                {"type": "REVENUE_OPTIMIZE", "text": "Khách đi nhóm 3-4 người thường gọi nước uống lẻ. Gợi ý cấu hình popup Menu QR giới thiệu thẳng Combo Gia Đình tiết kiệm 15%."}
            ]
        }

        return recs.get((industry or '').lower(), [
            {"type": "CHURN_ALERT", "text": "Có 18 khách hàng tiềm năng đã lâu chưa phát sinh tương tác. Đề xuất gửi tin nhắn thăm hỏi kèm mã ưu đãi tri ân thành viên."},
            {"type": "CAMPAIGN_SUGGESTION", "text": "Cuối tháng là thời điểm nhu cầu mua sắm và chi tiêu tăng cao. Đề xuất chạy chiến dịch 'Flash Sale tri ân khách cũ' kéo tương tác."},
            {"type": "REVENUE_OPTIMIZE", "text": "AI phát hiện 24% đơn hàng có thể upsell bằng cách đính kèm phụ kiện liên quan. Đề xuất tối ưu hóa gợi ý sản phẩm tự động."}
        ])


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
                    last_purchase_days, total_spent, source_platform='pos'
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
