# File: ad_suggest_api.py
# Đặt trong cùng thư mục với app.py (hoặc import vào app.py)
# Endpoint: /api/ad-suggest (POST)
# Chức năng: Nhận thông tin sản phẩm, trả về gợi ý nội dung quảng cáo (tiêu đề, mô tả, từ khóa, đối tượng, ngân sách)

from flask import Blueprint, request, jsonify

# Nếu bạn muốn tích hợp với Supabase để log, hãy thêm import bên dưới
# from supabase import create_client, Client
# SUPABASE_URL = "..."
# SUPABASE_KEY = "..."
# supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Tạo Blueprint để dễ dàng gắn vào app chính
ad_suggest_bp = Blueprint('ad_suggest', __name__, url_prefix='/api')

# Hàm mô phỏng AI (bạn có thể thay bằng gọi OpenAI API thật)
def generate_suggestions(product_name, product_desc, target_audience, budget, platform):
    # Dữ liệu mẫu – có thể tùy chỉnh theo nhu cầu
    headlines = [
        f"✨ {product_name} – Chất lượng đỉnh cao, giá tốt nhất thị trường!",
        f"🔥 Hot! {product_name} đang được săn đón – Ưu đãi cực sốc hôm nay",
        f"🎯 Bạn đang tìm {product_name}? Đây chính là lựa chọn hoàn hảo",
        f"🚀 {product_name} – Trải nghiệm ngay để cảm nhận sự khác biệt",
        f"💎 Độc quyền: {product_name} chỉ có tại BitPaw, không đâu rẻ hơn"
    ]
    descriptions = [
        f"{product_desc} Đặt hàng ngay để nhận quà tặng hấp dẫn và miễn phí vận chuyển.",
        f"Sản phẩm {product_name} được hàng ngàn khách hàng tin dùng. Cam kết chính hãng, bảo hành dài hạn.",
        f"Chỉ còn vài giờ cuối để sở hữu {product_name} với mức giá ưu đãi. Nhanh tay lên bạn ơi!"
    ]
    keywords = [product_name, product_name.split()[0] if product_name else "sản phẩm", "giảm giá", "chất lượng", "uy tín"]
    
    if platform == "facebook":
        audience = f"Độ tuổi {target_audience.get('age_min', 18)}–{target_audience.get('age_max', 65)}, quan tâm đến {', '.join(target_audience.get('interests', ['sản phẩm tương tự']))}"
    elif platform == "google":
        audience = f"Từ khóa: {', '.join(keywords[:3])} – Người dùng đang chủ động tìm kiếm sản phẩm liên quan."
    else:
        audience = f"Người dùng TikTok quan tâm đến {', '.join(keywords[:2])}, tuổi {target_audience.get('age_min', 18)}–{target_audience.get('age_max', 65)}."
    
    budget_recommend = {
        "min": int(budget * 0.8),
        "max": int(budget * 1.2),
        "daily": int(budget / 30) if budget > 0 else 50000
    }
    
    return {
        "headlines": headlines,
        "descriptions": descriptions,
        "keywords": keywords,
        "audience_suggestion": audience,
        "budget_recommendation": budget_recommend
    }

@ad_suggest_bp.route('/ad-suggest', methods=['POST'])
def ad_suggest():
    """
    Nhận JSON:
    {
        "product_name": "Tên sản phẩm",
        "product_desc": "Mô tả ngắn",
        "target_audience": { "age_min": 18, "age_max": 35, "interests": ["thể thao", "công nghệ"] },
        "budget": 1000000,
        "platform": "facebook" | "google" | "tiktok"
    }
    Trả về JSON gợi ý chiến dịch
    """
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
    
    # (Tuỳ chọn) Ghi log vào Supabase
    # try:
    #     supabase.table('ad_suggestions_log').insert({
    #         'product_name': product_name,
    #         'platform': platform,
    #         'suggestions': suggestions,
    #         'created_at': datetime.now().isoformat()
    #     }).execute()
    # except:
    #     pass
    
    return jsonify({
        "success": True,
        "suggestions": suggestions
    })

# Nếu bạn không dùng Blueprint, có thể đăng ký trực tiếp:
# app.add_url_rule('/api/ad-suggest', view_func=ad_suggest, methods=['POST'])