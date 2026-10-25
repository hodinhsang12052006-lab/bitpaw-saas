# File: ad_assistant.py
# Đặt trong cùng thư mục với app.py
# Cung cấp các route: /ad-assistant, /ad-assistant/api/suggest, /ad-assistant/api/create-campaign, /ad-assistant/api/campaigns
# Lưu log gợi ý và quản lý chiến dịch quảng cáo qua MongoDB Atlas (đã gỡ Supabase — file này
# trước đây tự tạo 1 client Supabase RIÊNG, độc lập với supabase_client.py, kèm fallback
# hardcode URL/anon-key ngay trong source — cả 2 vấn đề đó đều biến mất khi chuyển sang dùng
# chung mongo_client.py với phần còn lại của app).

import os
import json
import math
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, jsonify, session
from mongo_client import db, next_mongo_id
import ad_platform_tokens
import facebook_ads_client
from ai_deepseek_client import deepseek_chat_completion
# An toàn vì app.py chỉ import ad_assistant SAU khi login_required/limiter/role_required (dòng ~174, ~534,
# ~1411) đã định nghĩa xong, giống hệt pattern blueprints/spa_bp.py đang dùng.
from app import login_required, limiter, role_required, TenantEngine

# Tạo Blueprint
ad_assistant_bp = Blueprint('ad_assistant', __name__, url_prefix='/ad-assistant')

# Số ngày chạy mặc định của "tổng ngân sách" trên form (biểu đồ ước tính cũng tính 7 ngày)
DEFAULT_DURATION_DAYS = 7
# Mục tiêu ODAX hợp lệ của Meta — không chuyển thẳng chuỗi tuỳ ý từ client sang Graph API
ALLOWED_OBJECTIVES = {'OUTCOME_TRAFFIC', 'OUTCOME_ENGAGEMENT', 'OUTCOME_LEADS', 'OUTCOME_SALES', 'OUTCOME_AWARENESS'}


def _shop_region(business_id):
    """{'country','currency'} THẬT của tiệm — nhắm quốc gia + tiền tệ ngân sách theo tiệm, không mặc định cứng."""
    try:
        region = TenantEngine.get_region_config(business_id) or {}
    except Exception:
        region = {}
    return {'country': str(region.get('country') or 'VN').strip().upper(),
            'currency': str(region.get('currency') or 'VND').strip().upper()}


def _parse_amount(value):
    """Số tiền hợp lệ (> 0, hữu hạn) hoặc None — ô trống/NaN/số âm KHÔNG BAO GIỜ bị thay bằng 1 con số mặc
    định (trước đây UI tự điền 1.000.000 khi để trống -> 1.000.000 USD/ngày với tài khoản đô)."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _pick(business_id, vi, en):
    # Ngôn ngữ thông báo theo tiệm (VND -> tiếng Việt, còn lại tiếng Anh) như phần gợi ý quảng cáo
    return vi if _shop_region(business_id)['currency'] == 'VND' else en


def _err(business_id, code, vi, en, status, **extra):
    """Lỗi có `code` để UI tự dịch + `error` theo ngôn ngữ tiệm (giữ khoá `error` cũ cho UI hiện tại)."""
    return jsonify({"success": False, "code": code, "error": _pick(business_id, vi, en), **extra}), status


def _clamp_age(value, default):
    # Meta chỉ nhận 13–65; giữ tối thiểu 18 cho quảng cáo của tiệm
    try:
        return max(18, min(65, int(value)))
    except (TypeError, ValueError):
        return default


def _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation, lang='vi'):
    """Dự phòng khi DEEPSEEK_API_KEY chưa cấu hình hoặc DeepSeek lỗi — mẫu chung chung, gắn cờ
    fallback=True rõ ràng, KHÔNG giả danh là gợi ý AI cá nhân hoá thật."""
    if lang == 'en':
        headlines = [f"{product_name}", f"Discover {product_name}"]  # trung tính: không tự nhận "chất lượng tốt, giá hợp lý"
        descriptions = [(product_desc or f"Find out more about {product_name}.").strip()]
        keywords = [k for k in [product_name] if k]
        if platform == "google":
            audience_suggestion = f"Keywords: {product_name}."
        else:
            audience_suggestion = f"Age {age_min}–{age_max}" + (f", interested in {', '.join(interests)}" if interests else "")
        return {
            "headlines": headlines, "descriptions": descriptions, "keywords": keywords,
            "audience_suggestion": audience_suggestion, "budget_recommendation": budget_recommendation,
            "fallback": True,
        }
    headlines = [f"{product_name}", f"Khám phá {product_name}"]  # trung tính: không tự nhận "chất lượng tốt, giá hợp lý"
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
def generate_suggestions(product_name, product_desc, target_audience, budget, platform, lang='vi'):
    """Trả về dict: headlines, descriptions, keywords, audience_suggestion, budget_recommendation.
    lang: 'vi' | 'en' — tiệm Mỹ/Úc cần quảng cáo tiếng Anh (trước đây luôn viết tiếng Việt)."""
    target_audience = target_audience if isinstance(target_audience, dict) else {}
    age_min = target_audience.get('age_min', 18)
    age_max = target_audience.get('age_max', 65)
    interests = target_audience.get('interests', [])
    # Không nhập ngân sách -> không bịa con số gợi ý (trước đây tự lấy 500.000 bất kể tiền tệ của tiệm)
    budget_recommendation = ({"min": int(budget * 0.8), "max": int(budget * 1.2), "daily": int(budget / DEFAULT_DURATION_DAYS)}
                             if budget and budget > 0 else None)

    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation, lang)

    system_prompt = (
        "You are a senior performance-marketing copywriter for Facebook/Google/TikTok ads. Write "
        "persuasive, concrete ad copy in " + ("natural US/Australian English" if lang == 'en' else "Vietnamese")
        + ", grounded in the exact product/service given — never invent details not provided (no prices, "
        "discounts, free shipping, reviews or customer counts unless given). Return STRICT JSON only, exactly this shape: "
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
        return _fallback_suggestions(product_name, product_desc, age_min, age_max, interests, platform, budget_recommendation, lang)

    if lang == 'en':
        audience_suggestion = (f"Keywords: {', '.join(keywords[:3])}" if platform == "google" else
                               f"Age {age_min}–{age_max}" + (f", interested in {', '.join(interests)}" if interests else ""))
    elif platform == "facebook":
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
@login_required  # trang gọi toàn API cần đăng nhập + hiện tên tiệm trong bản xem trước
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
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Missing JSON body"}), 400

    product_name = str(data.get('product_name') or '').strip()
    if not product_name:
        return jsonify({"error": "product_name is required"}), 400

    product_desc = data.get('product_desc', '')
    target_audience = data.get('target_audience', {})
    budget = _parse_amount(data.get('budget')) or 0
    platform = data.get('platform', 'facebook')
    business_id = session.get('business_id') or session['user_id']
    lang = 'vi' if _shop_region(business_id)['currency'] == 'VND' else 'en'

    suggestions = generate_suggestions(product_name, product_desc, target_audience, budget, platform, lang)

    # Ghi log vào collection ad_suggestions_log (nếu có)
    try:
        db.ad_suggestions_log.insert_one({
            'id': next_mongo_id('ad_suggestions_log'),
            'business_id': business_id,
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
# Chỉ chủ/quản lý (admin) được nối token có quyền TIÊU TIỀN quảng cáo thật; giới hạn tần suất chống dò token.
@ad_assistant_bp.route('/api/connect-facebook', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
@limiter.limit("10 per hour")
def connect_facebook():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    access_token = str(data.get('access_token') or '').strip()
    ad_account_id = facebook_ads_client.normalize_ad_account_id(data.get('ad_account_id'))
    page_id = str(data.get('page_id') or '').strip() or None
    business_id = session.get('business_id') or session['user_id']
    if not access_token or not ad_account_id:
        return _err(business_id, 'missing_fields', "access_token và ad_account_id là bắt buộc.",
                    "access_token and ad_account_id are required.", 400)

    # Kiểm tra token THẬT với Meta trước khi lưu (GET /me + đọc tài khoản quảng cáo): trước đây lưu mù,
    # token sai/hết hạn chỉ lộ ra lúc tạo chiến dịch.
    try:
        me = facebook_ads_client.verify_token(access_token)
        account = facebook_ads_client.get_ad_account(access_token, ad_account_id)
    except facebook_ads_client.FacebookTokenExpiredError:
        return _err(business_id, 'token_invalid', "Token Facebook không hợp lệ hoặc đã hết hạn — hãy tạo token mới rồi thử lại.",
                    "This Facebook token is invalid or expired — create a new token and try again.", 400)
    except RuntimeError as e:
        return _err(business_id, 'ad_account_unreachable',
                    "Meta từ chối token hoặc Ad Account ID (kiểm tra ID dạng act_… và quyền ads_management).",
                    "Meta rejected the token or Ad Account ID (check the act_… ID and the ads_management permission).",
                    400, detail=str(e)[:300])

    try:
        ad_platform_tokens.save_facebook_token(business_id, access_token, ad_account_id, page_id)
    except RuntimeError as e:
        return jsonify({"success": False, "code": "storage_not_configured", "error": str(e)}), 500

    return jsonify({
        "success": True, "message": _pick(business_id, "Đã kết nối Facebook Ads thành công.", "Facebook Ads connected."),
        "facebook_user": (me or {}).get('name'), "ad_account_id": ad_account_id,
        "account_name": (account or {}).get('name'), "account_currency": (account or {}).get('currency'),
    })


# ========== API: TRẠNG THÁI KẾT NỐI FACEBOOK (Mã "Go-Live Pentest" audit) ==========
# Cho phép UI tự hỏi "kết nối Facebook của tôi còn dùng được không" để hiện banner "Kết nối lại"
# khi ads_metrics_worker.py/create_campaign() đã phát hiện + đánh dấu token hết hạn, thay vì
# chủ tiệm chỉ biết khi tạo campaign thất bại (hoặc không bao giờ biết nếu chỉ xem báo cáo).
@ad_assistant_bp.route('/api/facebook-status', methods=['GET'])
@login_required
def facebook_status():
    business_id = session.get('business_id') or session['user_id']
    # UI chỉ hiện nút kết nối/tạo chiến dịch cho người có quyền (route vẫn tự chặn bằng role_required)
    can_manage = session.get('role') in ('admin', 'super_admin')
    token_info = ad_platform_tokens.get_facebook_token(business_id)
    if not token_info:
        return jsonify({"success": True, "connected": False, "can_manage": can_manage})
    return jsonify({
        "success": True,
        "connected": True,
        "can_manage": can_manage,
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
@role_required('admin', 'super_admin')  # tạo chiến dịch = cam kết tiêu tiền thật của tiệm -> chỉ chủ/quản lý
@limiter.limit("10 per hour")
def create_campaign():
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Missing JSON body"}), 400
    business_id = session.get('business_id') or session['user_id']
    region = _shop_region(business_id)

    platform = data.get('platform')
    campaign_name = str(data.get('name') or '').strip()[:200]
    objective = data.get('objective') or 'OUTCOME_TRAFFIC'
    message = data.get('message')
    link = str(data.get('link') or '').strip()
    image_url = data.get('image_url')  # tuỳ chọn: media_url lấy từ /api/ai_studio/generate_image
    product_name = data.get('product_name')
    product_desc = data.get('product_desc', '')
    target_audience = data.get('target_audience') if isinstance(data.get('target_audience'), dict) else {}

    if not platform or not campaign_name:
        return jsonify({"error": "platform and name are required"}), 400
    if platform != 'facebook':
        return _err(business_id, 'platform_not_supported', f"Nền tảng '{platform}' chưa được tích hợp thật — hiện chỉ hỗ trợ Facebook.",
                    f"Platform '{platform}' is not integrated yet — only Facebook is supported.", 400)
    if objective not in ALLOWED_OBJECTIVES:
        return _err(business_id, 'invalid_objective', "Mục tiêu chiến dịch không hợp lệ.", "Invalid campaign objective.", 400)
    if not re.match(r'^https?://\S+$', link, flags=re.IGNORECASE):
        return _err(business_id, 'link_required', "Cần link đích của quảng cáo (bắt đầu bằng http:// hoặc https://).",
                    "A destination link is required (starting with http:// or https://).", 400)

    # Ngân sách: form gửi TỔNG ngân sách cho `duration_days` ngày (mặc định 7 — khớp biểu đồ ước tính 7 ngày).
    # Trước đây số tổng này bị dùng thẳng làm ngân sách MỖI NGÀY (x7) và x100 kể cả với VND (thêm x100 nữa).
    total_budget = _parse_amount(data.get('budget'))
    if total_budget is None:
        return _err(business_id, 'budget_required', "Vui lòng nhập tổng ngân sách (lớn hơn 0).",
                    "Please enter a total budget greater than 0.", 400)
    try:
        days = int(data.get('duration_days') or DEFAULT_DURATION_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_DURATION_DAYS
    days = max(1, min(days, 90))
    # Tiền tệ của con số chủ tiệm gõ (mặc định = tiền của tiệm) — PHẢI trùng tiền tệ tài khoản quảng cáo,
    # không tự quy đổi tỷ giá (đổi sai = chi sai tiền thật).
    budget_currency = str(data.get('currency') or region['currency']).strip().upper()

    country = region['country']
    if not re.fullmatch(r'[A-Z]{2}', country):
        return _err(business_id, 'shop_country_missing', "Chưa xác định được quốc gia của tiệm để nhắm quảng cáo.",
                    "The shop's country is not set, so the ad cannot be targeted.", 400)

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
        return _err(business_id, 'not_connected', "Chưa kết nối Facebook Ads — hãy kết nối trước.",
                    "Facebook Ads is not connected yet — connect it first.", 400)
    if not token_info.get('page_id'):
        return _err(business_id, 'page_id_missing', "Thiếu Page ID — vui lòng kết nối lại Facebook Ads kèm Page ID.",
                    "Page ID is missing — reconnect Facebook Ads with your Page ID.", 400)
    if token_info.get('status') == 'expired':
        return _err(business_id, 'reconnect_required', "Kết nối Facebook Ads đã hết hạn. Vui lòng kết nối lại trước khi tạo chiến dịch.",
                    "Your Facebook Ads connection has expired. Reconnect before creating a campaign.", 401, reconnect_required=True)

    # Tiền tệ THẬT của tài khoản quảng cáo quyết định cách đổi sang đơn vị nhỏ nhất (USD x100, VND x1)
    try:
        account = facebook_ads_client.get_ad_account(token_info['access_token'], token_info['ad_account_id'])
    except facebook_ads_client.FacebookTokenExpiredError as e:
        ad_platform_tokens.mark_facebook_token_invalid(business_id, str(e))
        return _err(business_id, 'reconnect_required', "Kết nối Facebook Ads đã hết hạn hoặc bị thu hồi. Vui lòng kết nối lại Facebook Ads.",
                    "Your Facebook Ads connection expired or was revoked. Please reconnect Facebook Ads.", 401, reconnect_required=True)
    except RuntimeError as e:
        return jsonify({"success": False, "code": "meta_error", "error": str(e)[:500]}), 502
    account_currency = str((account or {}).get('currency') or '').strip().upper()
    if not account_currency:
        return _err(business_id, 'account_currency_unknown', "Không đọc được tiền tệ của tài khoản quảng cáo — chưa tạo gì cả.",
                    "Could not read the ad account's currency — nothing was created.", 502)
    if account_currency != budget_currency:
        return _err(business_id, 'currency_mismatch',
                    f"Tài khoản quảng cáo dùng {account_currency}, còn ngân sách đang nhập theo {budget_currency}. "
                    f"Hãy nhập lại ngân sách bằng {account_currency} — chưa tạo gì cả.",
                    f"Your ad account uses {account_currency} but the budget was entered in {budget_currency}. "
                    f"Re-enter the budget in {account_currency} — nothing was created.",
                    400, account_currency=account_currency, budget_currency=budget_currency)

    daily_amount = total_budget / days
    daily_budget_minor = facebook_ads_client.to_minor_units(daily_amount, account_currency)
    if daily_budget_minor < 1:
        return _err(business_id, 'budget_too_small', "Ngân sách quá nhỏ.", "The budget is too small.", 400)

    # Nhắm đúng quốc gia của tiệm (trước đây cứng nước Úc) + độ tuổi chủ tiệm chọn trên form
    age_min = _clamp_age(target_audience.get('age_min'), 18)
    age_max = _clamp_age(target_audience.get('age_max'), 65)
    if age_max < age_min:
        age_min, age_max = age_max, age_min
    targeting = {'geo_locations': {'countries': [country]}, 'age_min': age_min, 'age_max': age_max}
    # Ngày dừng: ngân sách/ngày x số ngày không vượt tổng đã nhập (không có end_time thì chạy mãi tới khi tắt tay)
    end_time = (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+0000')

    # Chưa gõ tay message -> tự sinh ad copy thật qua DeepSeek từ product_name/product_desc rồi
    # feed thẳng vào luồng tạo Ad Creative bên dưới (đúng yêu cầu "đầu ra DeepSeek tự động feed
    # vào luồng Facebook Graph API hiện tại"), thay vì bắt chủ tiệm tự viết nội dung quảng cáo.
    # (Sinh SAU khi đã kiểm tra kết nối/tiền tệ để không tốn lượt AI cho 1 yêu cầu chắc chắn bị từ chối.)
    generated_ad_copy = None
    if not message:
        if not product_name:
            return jsonify({"error": "Cần 'message' (tự viết) hoặc 'product_name' (để AI tự sinh nội dung quảng cáo)."}), 400
        generated_ad_copy = generate_suggestions(product_name, product_desc, target_audience, total_budget, platform,
                                                 'vi' if region['currency'] == 'VND' else 'en')
        headline = generated_ad_copy['headlines'][0]
        description = generated_ad_copy['descriptions'][0]
        message = f"{headline}\n\n{description}"

    try:
        result = facebook_ads_client.launch_campaign(
            token_info['access_token'], facebook_ads_client.normalize_ad_account_id(token_info['ad_account_id']), token_info['page_id'],
            campaign_name, objective, daily_budget_minor=daily_budget_minor,
            message=message, link=link, image_url=image_url, targeting=targeting, end_time=end_time,
        )
    except facebook_ads_client.FacebookTokenExpiredError as e:
        # Mã "Go-Live Pentest" audit — trước đây lỗi này chỉ trả về như 1 lỗi 502 chung chung,
        # chủ tiệm không biết cần làm gì. Giờ đánh dấu token hỏng + báo RÕ hành động cần làm.
        ad_platform_tokens.mark_facebook_token_invalid(business_id, str(e))
        return _err(business_id, 'reconnect_required', "Kết nối Facebook Ads đã hết hạn hoặc bị thu hồi. Vui lòng kết nối lại Facebook Ads.",
                    "Your Facebook Ads connection expired or was revoked. Please reconnect Facebook Ads.", 401, reconnect_required=True)
    except (RuntimeError, ValueError) as e:
        return jsonify({"success": False, "code": "meta_error", "error": str(e)[:500]}), 502

    campaign_id = result['campaign_id']
    budget_info = {
        'currency': account_currency, 'budget_total': total_budget, 'duration_days': days,
        'daily_budget': round(daily_amount, 2), 'daily_budget_minor': daily_budget_minor,
        'end_time': end_time, 'targeting': targeting,
    }

    # Lưu chiến dịch vào collection ad_campaigns
    try:
        campaign_doc = {
            'id': next_mongo_id('ad_campaigns'),
            'business_id': business_id,
            'platform': platform,
            'name': campaign_name,
            'objective': objective,
            'budget': total_budget,  # TỔNG ngân sách cho duration_days ngày (theo `currency`)
            **budget_info,
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

    response = {"success": True, "campaign_id": campaign_id, "message": message, "facebook_status": "PAUSED",
                **budget_info, **result}
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