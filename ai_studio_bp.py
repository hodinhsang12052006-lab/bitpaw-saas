"""
AI Studio — Blueprint RIÊNG, TÁCH HẲN khỏi AI Bot (Mã AI Studio Part 1.1 audit).

Trước bản vá này, templates/ai-studio.html gọi NHẦM vào `/api/ai/studio/generate`
(secure_ai_generate() trong app.py) — route đó thực chất là API của AI BOT bán hàng cho
KHÁCH của tenant, đã bị khoá cứng persona server-side (không đọc `systemPrompt` client gửi
lên nữa, vì bot chat với khách lạ không được để client tự đổi hành vi). AI Studio lại là công
cụ NỘI BỘ cho CHÍNH chủ tiệm (đã đăng nhập) tự soạn nội dung marketing — cho phép họ tự set
systemPrompt là hợp lý và an toàn (họ chỉ đang tự nói chuyện với AI cho work của họ, không có
rủi ro mạo danh/injection từ khách lạ như route bot). Vì 2 route có mô hình rủi ro khác nhau,
tách hẳn 2 endpoint là đúng, không phải gộp chung rồi thêm cờ điều kiện.

Routes:
    POST /api/ai_studio/generate_text   — viết lại kịch bản/copy marketing (giữ nguyên tính
                                           năng cũ của ai-studio.html, chỉ đổi sang endpoint
                                           riêng, không lẫn với AI Bot nữa)
    POST /api/ai_studio/generate_image  — sinh ảnh THẬT qua Replicate/Stable Diffusion (ai_image_gen.py —
                                           DeepSeek không có model sinh ảnh, không dùng OpenAI/DALL-E nữa)
    GET  /api/ai_studio/media_history   — lịch sử media đã sinh (đọc db.generated_media)

Toàn bộ route yêu cầu đăng nhập (@login_required) — đây là công cụ nội bộ của chủ tiệm, không
phải widget công khai cho khách vãng lai như AI Bot.
"""
import os
from datetime import datetime

from flask import Blueprint, request, jsonify, session
import requests

from mongo_client import db, next_mongo_id
from ai_deepseek_client import deepseek_chat_completion
from ai_image_gen import generate_image
# An toàn vì app.py chỉ import/đăng ký ai_studio_bp SAU khi login_required (dòng ~534) đã định
# nghĩa xong, giống hệt pattern blueprints/spa_bp.py đang dùng.
from app import login_required

ai_studio_bp = Blueprint('ai_studio', __name__, url_prefix='/api/ai_studio')


def _call_deepseek_text(system_prompt, user_prompt, temperature, max_tokens, business_id):
    """Gọi DeepSeek qua ai_deepseek_client (tự chuyển sang AI Proxy nếu đang chạy Desktop mode,
    y hệt cách secure_ai_generate() làm) — trả về text thuần, không phải object response thô."""
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    is_desktop_mode = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
    result = deepseek_chat_completion(
        payload,
        business_id=business_id,
        proxy_api_key=os.environ.get('BITPAW_AI_PROXY_KEY') if is_desktop_mode else None,
        direct_api_key=os.environ.get('DEEPSEEK_API_KEY') if not is_desktop_mode else None,
    )
    return result['choices'][0]['message']['content']


@ai_studio_bp.route('/generate_text', methods=['POST'])
@login_required
def generate_text():
    data = request.get_json() or {}
    system_prompt = (data.get('system_prompt') or data.get('systemPrompt') or '').strip()
    user_prompt = (data.get('user_prompt') or data.get('userPrompt') or '').strip()
    temperature = float(data.get('temperature', 0.7))
    max_tokens = int(data.get('max_tokens', 1500))

    if not system_prompt or not user_prompt:
        return jsonify({"success": False, "error": "Thiếu system_prompt hoặc user_prompt."}), 400

    business_id = session.get('business_id') or session.get('user_id')
    try:
        content = _call_deepseek_text(system_prompt, user_prompt, temperature, max_tokens, business_id)
        return jsonify({"success": True, "choices": [{"message": {"content": content}}]})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "AI Studio timeout, vui lòng thử lại."}), 504
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502


def _derive_image_prompt(nurture_script, brand_name, industry, business_id):
    """Biến 1 đoạn kịch bản/nội dung text (vd: message do AINurturingEngine.generate_nurturing_copy()
    sinh ra) thành 1 prompt sinh ảnh chi tiết — đúng yêu cầu 'sinh ảnh dựa trên prompt sinh ra từ
    kịch bản AI Nurture' (Mã AI Studio Part 1.2)."""
    system_prompt = (
        "You are an expert visual/creative director for social media ad graphics. Given a short "
        "marketing message, write ONE detailed, vivid English prompt (for an AI image generator) "
        "describing a promotional image that matches the message's tone and goal. Describe scene, "
        "subject, lighting, mood, composition. Do NOT include any text/words to render inside the "
        "image. Output ONLY the prompt, nothing else."
    )
    user_prompt = (
        f"Business: {brand_name or 'a local business'} ({industry or 'general'} industry).\n"
        f"Marketing message: \"{nurture_script}\""
    )
    return _call_deepseek_text(system_prompt, user_prompt, 0.8, 300, business_id)


@ai_studio_bp.route('/generate_image', methods=['POST'])
@login_required
def generate_image_route():
    data = request.get_json() or {}
    prompt = (data.get('prompt') or '').strip()
    nurture_script = (data.get('nurture_script') or '').strip()
    brand_name = data.get('brand_name')
    industry = data.get('industry')
    campaign_id = data.get('campaign_id')
    size = data.get('size') or '1024x1024'

    business_id = session.get('business_id') or session.get('user_id')
    if not business_id:
        return jsonify({"success": False, "error": "Chưa đăng nhập."}), 401

    if not prompt and not nurture_script:
        return jsonify({"success": False, "error": "Cần 'prompt' hoặc 'nurture_script'."}), 400

    try:
        # Prompt trực tiếp (chủ tiệm tự gõ) được ưu tiên; nếu không có, tự dựng prompt từ
        # kịch bản AI Nurture qua DeepSeek trước khi đưa vào model sinh ảnh.
        final_prompt = prompt or _derive_image_prompt(nurture_script, brand_name, industry, business_id)
        media_url, provider = generate_image(final_prompt, size=size)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502

    media_id = next_mongo_id('generated_media')
    doc = {
        'id': media_id,
        'business_id': business_id,
        'campaign_id': campaign_id,
        'prompt': final_prompt,
        'media_url': media_url,
        'provider': provider,
        'created_at': datetime.now().isoformat(),
    }
    db.generated_media.insert_one(doc)

    return jsonify({"success": True, "id": media_id, "media_url": media_url, "prompt": final_prompt})


@ai_studio_bp.route('/media_history', methods=['GET'])
@login_required
def media_history():
    business_id = session.get('business_id') or session.get('user_id')
    if not business_id:
        return jsonify({"success": False, "error": "Chưa đăng nhập."}), 401

    query = {'business_id': business_id}
    campaign_id = request.args.get('campaign_id')
    if campaign_id:
        query['campaign_id'] = campaign_id

    items = list(
        db.generated_media.find(query, {'_id': 0}).sort('id', -1).limit(100)
    )
    return jsonify({"success": True, "items": items})
