# File: ad_assistant.py
# Đặt trong cùng thư mục với app.py
# Cung cấp các route: /ad-assistant, /ad-assistant/api/suggest, /ad-assistant/api/create-campaign, /ad-assistant/api/campaigns
# Tích hợp Supabase để lưu log gợi ý và quản lý chiến dịch quảng cáo

import os
import uuid
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client

# ========== CẤU HÌNH SUPABASE ==========
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://iojtglaxgdwsxxalhubx.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlvanRnbGF4Z2R3c3h4YWxodWJ4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc1NjgzNTIsImV4cCI6MjA5MzE0NDM1Mn0.KA7wdsZsK3oA6ybi5Gl_KnkzAKZM-ESI3Eyzx-mipwM')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Tạo Blueprint
ad_assistant_bp = Blueprint('ad_assistant', __name__, url_prefix='/ad-assistant')

# ========== HÀM GỢI Ý NỘI DUNG (AI MÔ PHỎNG) ==========
def generate_suggestions(product_name, product_desc, target_audience, budget, platform):
    """
    Trả về dictionary các gợi ý: headlines, descriptions, keywords, audience_suggestion, budget_recommendation
    """
    # Tiêu đề gợi ý
    headlines = [
        f"✨ {product_name} – Chất lượng đỉnh cao, giá tốt nhất!",
        f"🔥 Hot! {product_name} đang được săn đón – Ưu đãi cực sốc",
        f"🎯 Bạn đang tìm {product_name}? Đây chính là lựa chọn hoàn hảo",
        f"🚀 {product_name} – Trải nghiệm ngay để cảm nhận sự khác biệt",
        f"💎 Độc quyền: {product_name} chỉ có tại BitPaw"
    ]
    # Mô tả gợi ý
    descriptions = [
        f"{product_desc} Đặt hàng ngay để nhận quà tặng hấp dẫn và miễn phí vận chuyển.",
        f"Sản phẩm {product_name} được hàng ngàn khách hàng tin dùng. Cam kết chính hãng.",
        f"Chỉ còn vài giờ cuối để sở hữu {product_name} với mức giá ưu đãi."
    ]
    # Từ khóa
    keywords = [product_name] + (product_name.split()[:2] if product_name else []) + ["giảm giá", "chất lượng", "uy tín"]
    keywords = list(dict.fromkeys(keywords))  # loại trùng
    
    # Gợi ý đối tượng theo nền tảng
    age_min = target_audience.get('age_min', 18)
    age_max = target_audience.get('age_max', 65)
    interests = target_audience.get('interests', [])
    if platform == "facebook":
        audience_suggestion = f"Độ tuổi {age_min}–{age_max}, quan tâm đến {', '.join(interests) if interests else 'sản phẩm tương tự'}"
    elif platform == "google":
        audience_suggestion = f"Từ khóa: {', '.join(keywords[:3])} – Người dùng đang chủ động tìm kiếm sản phẩm liên quan."
    else:
        audience_suggestion = f"Người dùng TikTok quan tâm đến {', '.join(keywords[:2])}, tuổi {age_min}–{age_max}."
    
    # Ngân sách đề xuất
    if budget <= 0:
        budget = 500000
    budget_recommendation = {
        "min": int(budget * 0.8),
        "max": int(budget * 1.2),
        "daily": int(budget / 30)
    }
    
    return {
        "headlines": headlines,
        "descriptions": descriptions,
        "keywords": keywords,
        "audience_suggestion": audience_suggestion,
        "budget_recommendation": budget_recommendation
    }

# ========== HÀM TẠO CAMPAIGN TRÊN FACEBOOK (SANDBOX) ==========
def create_facebook_campaign(access_token, ad_account_id, name, objective, budget, status="PAUSED"):
    """
    Gọi Facebook Marketing API để tạo campaign (sandbox).
    objective: 'OUTCOME_TRAFFIC', 'OUTCOME_ENGAGEMENT', 'OUTCOME_LEADS', 'OUTCOME_SALES'
    """
    url = f"https://graph.facebook.com/v18.0/{ad_account_id}/campaigns"
    params = {
        "name": name,
        "objective": objective,
        "status": status,
        "special_ad_categories": [],
        "access_token": access_token
    }
    if budget:
        params["daily_budget"] = int(budget * 100)  # USD -> cent (nếu budget là USD)
    response = requests.post(url, params=params)
    if response.status_code == 200:
        return response.json().get("id")
    else:
        raise Exception(f"Facebook API error: {response.text}")

# ========== ROUTE: GIAO DIỆN CHÍNH ==========
@ad_assistant_bp.route('/')
def index():
    return render_template('ad_assistant.html')

# ========== API: GỢI Ý CHIẾN DỊCH ==========
@ad_assistant_bp.route('/api/suggest', methods=['POST'])
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
    
    # Ghi log vào bảng ad_suggestions_log (nếu có)
    try:
        supabase.table('ad_suggestions_log').insert({
            'product_name': product_name,
            'platform': platform,
            'suggestions': suggestions,
            'created_at': datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print("Loi ghi log:", e)
    
    return jsonify({"success": True, "suggestions": suggestions})

# ========== API: TẠO CHIẾN DỊCH (HIỆN TẠI HỖ TRỢ FACEBOOK) ==========
@ad_assistant_bp.route('/api/create-campaign', methods=['POST'])
def create_campaign():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    
    platform = data.get('platform')
    campaign_name = data.get('name')
    objective = data.get('objective', 'OUTCOME_TRAFFIC')
    budget = float(data.get('budget', 0))
    
    if not platform or not campaign_name:
        return jsonify({"error": "platform and name are required"}), 400
    
    user_id = session.get('user_id')  # Lấy từ session nếu đã đăng nhập
    
    try:
        if platform == 'facebook':
            access_token = data.get('access_token')
            ad_account_id = data.get('ad_account_id')
            if not access_token or not ad_account_id:
                return jsonify({"error": "access_token and ad_account_id required for Facebook"}), 400
            campaign_id = create_facebook_campaign(access_token, ad_account_id, campaign_name, objective, budget)
        else:
            # Google, TikTok – tạm thời tạo ID giả lập
            campaign_id = f"DEMO-{uuid.uuid4().hex[:8]}"
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    # Lưu chiến dịch vào bảng ad_campaigns
    try:
        supabase.table('ad_campaigns').insert({
            'user_id': user_id,
            'platform': platform,
            'name': campaign_name,
            'objective': objective,
            'budget': budget,
            'campaign_id': campaign_id,
            'status': 'created',
            'created_at': datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print("Loi luu chien dich:", e)
    
    return jsonify({"success": True, "campaign_id": campaign_id})

# ========== API: DANH SÁCH CHIẾN DỊCH CỦA NGƯỜI DÙNG ==========
@ad_assistant_bp.route('/api/campaigns', methods=['GET'])
def list_campaigns():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])
    try:
        res = supabase.table('ad_campaigns').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
        return jsonify(res.data)
    except Exception as e:
        print("Loi lay danh sach:", e)
        return jsonify([])