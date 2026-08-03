# File: ad_assistant.py
# Đặt trong cùng thư mục với app.py
# Cung cấp các route: /ad-assistant, /ad-assistant/api/suggest, /ad-assistant/api/create-campaign, /ad-assistant/api/campaigns
# Lưu log gợi ý và quản lý chiến dịch quảng cáo qua MongoDB Atlas (đã gỡ Supabase — file này
# trước đây tự tạo 1 client Supabase RIÊNG, độc lập với supabase_client.py, kèm fallback
# hardcode URL/anon-key ngay trong source — cả 2 vấn đề đó đều biến mất khi chuyển sang dùng
# chung mongo_client.py với phần còn lại của app).

import os
import json
import re
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
from mongo_client import db, next_mongo_id
import ad_platform_tokens
import facebook_ads_client
from ai_deepseek_client import deepseek_chat_completion
# An toàn vì app.py chỉ import ad_assistant SAU khi login_required/limiter (dòng ~174, ~534) đã
# định nghĩa xong, giống hệt pattern blueprints/spa_bp.py đang dùng.
from app import login_required, limiter

# Tạo Blueprint
ad_assistant_bp = Blueprint('ad_assistant', __name__, url_prefix='/ad-assistant')


def _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation):
    """Dự phòng khi DEEPSEEK_API_KEY chưa cấu hình hoặc DeepSeek lỗi — mẫu chung chung, gắn cờ
    fallback=True rõ ràng, KHÔNG giả danh là gợi ý AI cá nhân hoá thật."""
    headlines = [f"{product_name} – Chất lượng tốt, giá hợp lý", f"Đã có {product_name} tại đây"]
    descriptions = [(product_desc or f"Tìm hiểu thêm về {product_name}.").strip()]
    keywords = [k for k in [product_name] if k]

    if platform == "facebook":
        audience_suggestion = f"Độ tuổi {age_min}–{age_max}, quan tâm đến {', '.join(interests) if interests else 'sản phẩm tương tự'}"
    elif platform == "google":
        audience_suggestion = f"Từ khóa: {product_name}."
    else:
        audience_suggestion = f"Người dùng quan tâm {product_name}, tuổi {age_min}–{age_max}."

    return {
        "headlines": headlines, "descriptions": descriptions, "keywords": keywords,
        "audience_suggestion": audience_suggestion, "budget_recommendation": budget_recommendation,
        "fallback": True,
    }


# ========== HÀM GỢI Ý NỘI DUNG — SINH AD COPY THẬT QUA DEEPSEEK ==========
# Mã "Hợp nhất AI bằng DeepSeek" audit — trước đây là chuỗi template cố định giả danh AI
# ("AI MÔ PHỎNG"), không hề gọi model nào. Giờ gọi thật DeepSeek qua ai_deepseek_client.py
# (client OpenAI-SDK trỏ base_url về DeepSeek) để sinh tiêu đề/mô tả/từ khoá thật theo đúng
# sản phẩm/dịch vụ chủ tiệm nhập vào.
def generate_suggestions(product_name, product_desc, target_audience, budget, platform):
    """Trả về dict: headlines, descriptions, keywords, audience_suggestion, budget_recommendation."""
    age_min = target_audience.get('age_min', 18)
    age_max = target_audience.get('age_max', 65)
    interests = target_audience.get('interests', [])
    budget = budget if budget and budget > 0 else 500000
    budget_recommendation = {"min": int(budget * 0.8), "max": int(budget * 1.2), "daily": int(budget / 30)}

    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation)

    system_prompt = (
        "You are a senior performance-marketing copywriter for Facebook/Google/TikTok ads. Write "
        "persuasive, concrete ad copy in Vietnamese, grounded in the exact product/service given — "
        "never invent details not provided. Return STRICT JSON only, exactly this shape: "
        '{"headlines": ["...", "...", "...", "...", "..."], "descriptions": ["...", "...", "..."], '
        '"keywords": ["...", "...", "...", "...", "..."]} — 5 headlines, 3 descriptions, 5-8 keywords.'
    )
    user_prompt = (
        f"Product/service: {product_name}. Description: {product_desc or 'N/A'}. Platform: {platform}. "
        f"Target audience: age {age_min}-{age_max}"
        + (f", interested in {', '.join(interests)}" if interests else "") + "."
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": 0.8, "max_tokens": 600,
        "response_format": {"type": "json_object"},
    }

    try:
        result = deepseek_chat_completion(payload, direct_api_key=api_key)
        raw = result['choices'][0]['message']['content'].strip()
        raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        headlines = parsed.get('headlines') or []
        descriptions = parsed.get('descriptions') or []
        keywords = parsed.get('keywords') or []
        if not headlines or not descriptions:
            raise ValueError("DeepSeek trả về thiếu headlines/descriptions.")
    except Exception as e:
        print(f"[ad_assistant] Lỗi sinh ad copy qua DeepSeek, dùng fallback: {e}")
        return _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation)

    if platform == "facebook":
        audience_suggestion = f"Độ tuổi {age_min}–{age_max}, quan tâm đến {', '.join(interests) if interests else 'sản phẩm tương tự'}"
    elif platform == "google":
        audience_suggestion = f"Từ khóa: {', '.join(keywords[:3])} – Người dùng đang chủ động tìm kiếm sản phẩm liên quan."
    else:
        audience_suggestion = f"Người dùng TikTok quan tâm đến {', '.join(keywords[:2])}, tuổi {age_min}–{age_max}."

    return {
        "headlines": headlines, "descriptions": descriptions, "keywords": keywords,
        "audience_suggestion": audience_suggestion, "budget_recommendation": budget_recommendation,
    }

# ========== ROUTE: GIAO DIỆN CHÍNH ==========
@ad_assistant_bp.route('/')
def index():
    return render_template('ad_assistant.html')

# ========== API: GỢI Ý CHIẾN DỊCH ==========
# Mã "Go-Live Pentest" audit (Critical) — route này TRƯỚC ĐÂY không có @login_required VÀ
# không rate-limit, lúc còn là template hardcode thì vô hại; nhưng từ khi generate_suggestions()
# gọi THẬT DeepSeek (tốn tiền/request), bất kỳ ai (kể cả không đăng nhập) cũng có thể spam route
# này để đốt quota DeepSeek của chủ hệ thống — cùng lớp lỗ hổng với Mã 3.5 đã vá cho AI Bot.
@ad_assistant_bp.route('/api/suggest', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def suggest():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    
    product_name = data.get('product_name', '').strip()
    if not product_name:
        return jsonify({"error": "product_name is required"}), 400
    
    product_desc = data.get('product_desc', '')
    target_audience = data.get('target_audience', {})
    budget = float(data.get('budget', 0))
    platform = data.get('platform', 'facebook')
    
    suggestions = generate_suggestions(product_name, product_desc, target_audience, budget, platform)
    
    # Ghi log vào collection ad_suggestions_log (nếu có)
    try:
        db.ad_suggestions_log.insert_one({
            'id': next_mongo_id('ad_suggestions_log'),
            'product_name': product_name,
            'platform': platform,
            'suggestions': suggestions,
            'created_at': datetime.now().isoformat()
        })
    except Exception as e:
        print("Loi ghi log:", e)
    
    return jsonify({"success": True, "suggestions": suggestions})

# ========== API: KẾT NỐI FACEBOOK ADS (Mã AI Ads Part 2.1 audit) ==========
# Chủ tiệm dán System User Access Token + Ad Account ID + Page ID 1 LẦN DUY NHẤT ở đây.
# Token được mã hoá (Fernet) và lưu theo business_id — mọi lần tạo campaign SAU ĐÓ tự dùng lại
# token này, không bắt gõ tay mỗi lần như route create-campaign cũ.
@ad_assistant_bp.route('/api/connect-facebook', methods=['POST'])
@login_required
def connect_facebook():
    data = request.get_json() or {}
    access_token = (data.get('access_token') or '').strip()
    ad_account_id = (data.get('ad_account_id') or '').strip()
    page_id = (data.get('page_id') or '').strip() or None
    if not access_token or not ad_account_id:
        return jsonify({"success": False, "error": "access_token và ad_account_id là bắt buộc."}), 400

    business_id = session.get('business_id') or session['user_id']
    try:
        ad_platform_tokens.save_facebook_token(business_id, access_token, ad_account_id, page_id)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "message": "Đã kết nối Facebook Ads thành công."})


# ========== API: TRẠNG THÁI KẾT NỐI FACEBOOK (Mã "Go-Live Pentest" audit) ==========
# Cho phép UI tự hỏi "kết nối Facebook của tôi còn dùng được không" để hiện banner "Kết nối lại"
# khi ads_metrics_worker.py/create_campaign() đã phát hiện + đánh dấu token hết hạn, thay vì
# chủ tiệm chỉ biết khi tạo campaign thất bại (hoặc không bao giờ biết nếu chỉ xem báo cáo).
@ad_assistant_bp.route('/api/facebook-status', methods=['GET'])
@login_required
def facebook_status():
    business_id = session.get('business_id') or session['user_id']
    token_info = ad_platform_tokens.get_facebook_token(business_id)
    if not token_info:
        return jsonify({"success": True, "connected": False})
    return jsonify({
        "success": True,
        "connected": True,
        "status": token_info.get('status', 'active'),
        "invalid_reason": token_info.get('invalid_reason'),
        "ad_account_id": token_info.get('ad_account_id'),
        "page_id": token_info.get('page_id'),
    })


# ========== API: TẠO CHIẾN DỊCH THẬT TRÊN FACEBOOK (Mã AI Ads Part 2.2 audit) ==========
# CHỈ hỗ trợ Facebook thật qua Graph API — KHÔNG còn nhánh sinh "DEMO-xxx" giả cho Google/TikTok
# (chưa tích hợp thật thì báo lỗi rõ ràng, không giả vờ tạo thành công).
@ad_assistant_bp.route('/api/create-campaign', methods=['POST'])
@login_required
def create_campaign():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    platform = data.get('platform')
    campaign_name = data.get('name')
    objective = data.get('objective', 'OUTCOME_TRAFFIC')
    budget = float(data.get('budget', 0))
    message = data.get('message')
    link = data.get('link')
    image_url = data.get('image_url')  # tuỳ chọn: media_url lấy từ /api/ai_studio/generate_image
    product_name = data.get('product_name')
    product_desc = data.get('product_desc', '')

    if not platform or not campaign_name:
        return jsonify({"error": "platform and name are required"}), 400
    if platform != 'facebook':
        return jsonify({"error": f"Platform '{platform}' chưa được tích hợp thật — hiện chỉ hỗ trợ Facebook."}), 400
    if not link:
        return jsonify({"error": "link (URL đích của quảng cáo) là bắt buộc."}), 400

    # Chưa gõ tay message -> tự sinh ad copy thật qua DeepSeek từ product_name/product_desc rồi
    # feed thẳng vào luồng tạo Ad Creative bên dưới (đúng yêu cầu "đầu ra DeepSeek tự động feed
    # vào luồng Facebook Graph API hiện tại"), thay vì bắt chủ tiệm tự viết nội dung quảng cáo.
    generated_ad_copy = None
    if not message:
        if not product_name:
            return jsonify({"error": "Cần 'message' (tự viết) hoặc 'product_name' (để AI tự sinh nội dung quảng cáo)."}), 400
        generated_ad_copy = generate_suggestions(product_name, product_desc, data.get('target_audience') or {}, budget, platform)
        headline = generated_ad_copy['headlines'][0]
        description = generated_ad_copy['descriptions'][0]
        message = f"{headline}\n\n{description}"

    business_id = session.get('business_id') or session['user_id']

    # Mã "Go-Live Pentest" audit (High/SSRF) — image_url trước đây được fetch THẲNG server-side
    # (facebook_ads_client.upload_ad_image() gọi requests.get(image_url)) mà không kiểm tra gì.
    # 1 tenant đã đăng nhập có thể truyền image_url=http://169.254.169.254/... (cloud metadata),
    # http://localhost:xxxx/... hoặc bất kỳ URL nội bộ nào, khiến server tự thay mặt attacker gọi
    # tới đó (SSRF) rồi upload phản hồi lên làm ảnh quảng cáo. Chỉ chấp nhận image_url nếu nó THẬT
    # SỰ là 1 media do CHÍNH tenant này sinh ra qua /api/ai_studio/generate_image (đã lưu trong
    # db.generated_media), không tin bất kỳ URL nào client tự gõ vào.
    if image_url:
        owns_media = db.generated_media.count_documents({'business_id': business_id, 'media_url': image_url}) > 0
        if not owns_media:
            return jsonify({"error": "image_url không hợp lệ — chỉ được dùng ảnh do chính bạn sinh qua AI Studio."}), 400

    token_info = ad_platform_tokens.get_facebook_token(business_id)
    if not token_info:
        return jsonify({"error": "Chưa kết nối Facebook Ads — gọi /api/connect-facebook trước."}), 400
    if not token_info.get('page_id'):
        return jsonify({"error": "Thiếu page_id — vui lòng kết nối lại Facebook Ads kèm Page ID."}), 400
    if token_info.get('status') == 'expired':
        return jsonify({
            "error": "Kết nối Facebook Ads đã hết hạn. Vui lòng kết nối lại trước khi tạo chiến dịch.",
            "reconnect_required": True,
        }), 401

    try:
        result = facebook_ads_client.launch_campaign(
            token_info['access_token'], token_info['ad_account_id'], token_info['page_id'],
            campaign_name, objective, daily_budget_cents=int(budget * 100),
            message=message, link=link, image_url=image_url,
        )
    except facebook_ads_client.FacebookTokenExpiredError as e:
        # Mã "Go-Live Pentest" audit — trước đây lỗi này chỉ trả về như 1 lỗi 502 chung chung,
        # chủ tiệm không biết cần làm gì. Giờ đánh dấu token hỏng + báo RÕ hành động cần làm.
        ad_platform_tokens.mark_facebook_token_invalid(business_id, str(e))
        return jsonify({
            "error": "Kết nối Facebook Ads đã hết hạn hoặc bị thu hồi. Vui lòng kết nối lại Facebook Ads.",
            "reconnect_required": True,
        }), 401
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    campaign_id = result['campaign_id']

    # Lưu chiến dịch vào collection ad_campaigns
    try:
        campaign_doc = {
            'id': next_mongo_id('ad_campaigns'),
            'business_id': business_id,
            'platform': platform,
            'name': campaign_name,
            'objective': objective,
            'budget': budget,
            'message': message,
            'campaign_id': campaign_id,
            'ad_set_id': result['ad_set_id'],
            'creative_id': result['creative_id'],
            'ad_id': result['ad_id'],
            'status': 'created',  # Facebook status thật là PAUSED, chờ chủ tiệm tự bật chạy
            'created_at': datetime.now().isoformat()
        }
        if generated_ad_copy:
            campaign_doc['generated_ad_copy'] = generated_ad_copy
        db.ad_campaigns.insert_one(campaign_doc)
    except Exception as e:
        print("Loi luu chien dich:", e)

    response = {"success": True, "campaign_id": campaign_id, "message": message, **result}
    if generated_ad_copy:
        response['generated_ad_copy'] = generated_ad_copy
    return jsonify(response)


# ========== API: DANH SÁCH CHIẾN DỊCH CỦA TENANT ==========
@ad_assistant_bp.route('/api/campaigns', methods=['GET'])
@login_required
def list_campaigns():
    business_id = session.get('business_id') or session['user_id']
    try:
        campaigns = list(db.ad_campaigns.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
        return jsonify(campaigns)
    except Exception as e:
        print("Loi lay danh sach:", e)
        return jsonify([])