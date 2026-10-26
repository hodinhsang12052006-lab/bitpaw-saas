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

Routes (docs/AI_SUITE_SPEC.md §3):
    POST /api/ai_studio/generate_text        — viết copy/kịch bản (DeepSeek)
    GET|POST /api/ai_studio/brand            — Brand DNA của tiệm
    POST /api/ai_studio/media/jobs           — tạo job ảnh/video AI THẬT (Replicate, ai_media.py)
    GET  /api/ai_studio/media/jobs/<id>      — trạng thái job (tự hỏi Replicate khi job còn chạy)
    GET  /api/ai_studio/media                — thư viện: ảnh/video AI đã xong + video quảng cáo/file đã tải lên
    DELETE /api/ai_studio/media/<file_id>    — xoá file của tiệm
    GET  /api/ai_studio/quota                — hạn mức tháng theo gói + bảng preset/giá ước tính
    POST /api/ai_studio/replicate_webhook    — CÔNG KHAI (Replicate gọi về; kiểm chữ ký, integrator miễn CSRF)
    POST /api/ai_studio/scene_plan           — kịch bản cảnh cho video quảng cáo render trên trình duyệt
    POST /api/ai_studio/generate_image       — (cũ) = tạo job ảnh preset 'draft'
    GET  /api/ai_studio/media_history        — (cũ) = /media

Mọi route trừ webhook yêu cầu đăng nhập — đây là công cụ nội bộ của chủ tiệm/nhân viên có quyền AI Studio.
"""
import json
import math
import os
import re
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session
import requests

from mongo_client import db
import ai_gateway
import ai_media
import media_store
from media_store import MediaError
# An toàn vì app.py chỉ import/đăng ký ai_studio_bp SAU khi login_required (dòng ~534) đã định
# nghĩa xong, giống hệt pattern blueprints/spa_bp.py đang dùng.
from app import login_required

ai_studio_bp = Blueprint('ai_studio', __name__, url_prefix='/api/ai_studio')

MAX_TEMPERATURE = 1.2
MAX_TOKENS = 2000


def _call_deepseek_text(system_prompt, user_prompt, temperature, max_tokens, business_id, feature='studio_text'):
    """Gọi DeepSeek qua ai_gateway (tự chuyển sang AI Proxy nếu đang chạy Desktop mode, timeout + thử lại lỗi tạm thời)
    — trả về text thuần. Gateway ghi db.ai_usage theo token THẬT DeepSeek trả về (trước đây ghi max_tokens xin, chi phí 0)."""
    return ai_gateway.text(feature, business_id, system_prompt, user_prompt, temperature, max_tokens)


def _bid():
    return session.get('business_id') or session.get('user_id')


def _media_err(e):
    return jsonify(e.as_dict()), getattr(e, 'status', 400) or 400


def _public_base():
    # Chạy thử với máy giả: dùng đúng host local (đừng lấy PUBLIC_BASE_URL production trong .env)
    if media_store.test_mode():
        return request.host_url.rstrip('/')
    return (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')


@ai_studio_bp.route('/generate_text', methods=['POST'])
@login_required
def generate_text():
    data = request.get_json(silent=True) or {}
    system_prompt = (data.get('system_prompt') or data.get('systemPrompt') or '').strip()
    user_prompt = (data.get('user_prompt') or data.get('userPrompt') or '').strip()
    # Số do client gửi: sai kiểu -> 400 (trước đây float('abc') ném lỗi 500); ngoài khoảng -> kẹp lại
    # (DeepSeek nhận temperature 0–2 nhưng > 1.2 ra chữ lộn xộn; max_tokens lớn = tốn tiền vô ích)
    try:
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 1500))
        if not math.isfinite(temperature):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return jsonify({"success": False, "code": "bad_number",
                        "error": "temperature/max_tokens không hợp lệ.", "message": "Invalid temperature or max_tokens."}), 400
    temperature = min(max(temperature, 0.0), MAX_TEMPERATURE)
    max_tokens = min(max(max_tokens, 1), MAX_TOKENS)

    if not system_prompt or not user_prompt:
        return jsonify({"success": False, "error": "Thiếu system_prompt hoặc user_prompt."}), 400

    business_id = _bid()
    try:
        facts = _business_facts(business_id)
        if facts:
            system_prompt += "\n\n" + facts
        content = _call_deepseek_text(system_prompt, user_prompt, temperature, max_tokens, business_id)
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "AI Studio timeout, vui lòng thử lại."}), 504
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    return jsonify({"success": True, "choices": [{"message": {"content": content}}]})


def _business_facts(business_id):
    """Dữ kiện THẬT của tiệm cho bài đăng/kịch bản (tên, dịch vụ + giá đúng tiền tệ, link đặt lịch, thông tin tiệm) —
    như Shopify Magic viết từ dữ liệu sản phẩm thật. Trước đây AI Studio không biết gì về tiệm nên chỉ ghi [price]."""
    try:
        from currency_utils import format_money
        from app import _tenant_currency
        from ai_nurturing_engine import AINurturingEngine
        import booking_rules
        biz = db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'industry_code': 1}) or {}
        cur = _tenant_currency(business_id)
        svcs = list(db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}, 'price': {'$gt': 0}},
                                     {'_id': 0, 'name': 1, 'price': 1}).sort('price', -1).limit(30))
        lines = [f"BUSINESS FACTS (real — use them instead of placeholders; never invent other prices, offers or reviews): {biz.get('name') or ''}"]
        if svcs:
            lines.append('Services: ' + '; '.join(f"{s['name']} {format_money(s['price'], cur)}" for s in svcs))
        link = AINurturingEngine.booking_link(business_id, biz.get('industry_code'), os.environ.get('PUBLIC_BASE_URL'))
        if link:
            lines.append(f"Online booking link: {link}")
        info = (booking_rules.get_rules(business_id).get('info') or {})
        extra = [f"{booking_rules.INFO_LABELS[k]}: {v}" for k, v in info.items() if v]
        if extra:
            lines.append('; '.join(extra))
        return '\n'.join(lines)
    except Exception as e:
        print(f"[ai_studio] facts: {e}")
        return ''


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
    return _call_deepseek_text(system_prompt, user_prompt, 0.8, 300, business_id, feature='studio_image_prompt')


# ---------------------------------------------------------------- ảnh/video AI (job)
@ai_studio_bp.route('/media/jobs', methods=['POST'])
@login_required
def media_create_job():
    business_id = _bid()
    data = request.get_json(silent=True) or {}
    kind = data.get('kind') if isinstance(data.get('kind'), str) else ''
    preset = data.get('preset') if isinstance(data.get('preset'), str) and data.get('preset') else 'draft'
    prompt = (data.get('prompt') or '').strip() if isinstance(data.get('prompt'), str) else ''
    from_text = (data.get('from_text') or '').strip() if isinstance(data.get('from_text'), str) else ''
    lang = data.get('lang') if data.get('lang') in ('vi', 'en') else 'en'
    try:
        if kind not in ai_media.MODELS:
            raise MediaError('bad_kind', "kind must be 'image' or 'video'.")
        if preset not in ai_media.MODELS[kind]:
            raise MediaError('bad_preset', f'Unknown preset: {kind}/{preset}')
        if not prompt and from_text:
            # Hết hạn mức/chưa cấu hình thì báo ngay, khỏi tốn 1 lượt DeepSeek viết prompt
            ai_media.precheck(business_id, kind)
            prompt = ai_media.prompt_from_text(business_id, from_text, kind, lang, preset=preset)
        job = ai_media.create_job(business_id, session.get('user_id'), kind, preset, prompt,
                                  aspect=data.get('aspect') if isinstance(data.get('aspect'), str) else None,
                                  duration=data.get('duration'),
                                  image_file_id=data.get('image_file_id') or None, base_url=_public_base(),
                                  source_text=from_text or None)
    except MediaError as e:
        return _media_err(e)
    return jsonify({"success": True, "job": ai_media.public_job(job), "quota": ai_media.quota_status(business_id)})


@ai_studio_bp.route('/media/jobs/<int:job_id>', methods=['GET'])
@login_required
def media_job(job_id):
    business_id = _bid()
    job = db.ai_media_jobs.find_one({'id': job_id, 'business_id': business_id}, {'_id': 0})
    if not job:
        return _media_err(MediaError('not_found', 'Job not found.', status=404))
    updated = media_store._aware(job.get('updated_at'))
    # Giao diện hỏi 2 giây/lần; chỉ thật sự gọi Replicate khi lần cập nhật trước đã cũ hơn 4 giây
    if job.get('status') in ai_media.ACTIVE and (not updated or media_store._now() - updated > timedelta(seconds=4)):
        try:
            job = ai_media.refresh_job(job_id) or job
        except MediaError:
            pass
    return jsonify({"success": True, "job": ai_media.public_job(job)})


_FILE_KINDS = {'promo_video': ('promo_video',), 'social_upload': ('social_upload',)}


def _media_items(business_id, kind, limit):
    items = []
    if kind in ('', 'image', 'video'):
        q = {'business_id': business_id, 'status': 'succeeded', 'deleted': {'$ne': True}}
        if kind:
            q['kind'] = kind
        for j in db.ai_media_jobs.find(q, {'_id': 0}).sort('id', -1).limit(limit):
            # url/public_url/play_url/download_url: play/tải qua link /m/ có Range (video > 4,5 MB, iPhone cần Range)
            links = media_store.file_links(j['file_id'], j.get('content_type')) if j.get('file_id') else \
                {'url': None, 'public_url': None, 'play_url': None, 'download_url': None}
            items.append({
                'id': j['id'], 'kind': j.get('kind'), 'preset': j.get('preset'), 'prompt': j.get('prompt'),
                'status': j.get('status'), 'file_id': j.get('file_id'), **links,
                'content_type': j.get('content_type'), 'created_at': media_store.iso(j.get('created_at')),
                'cost_estimate_usd': j.get('cost_estimate_usd'), 'source': 'replicate', 'aspect': j.get('aspect'),
                'duration': j.get('duration'), 'model': j.get('model'), 'size': j.get('size'), 'is_ai_generated': True,
            })
    file_kinds = _FILE_KINDS.get(kind, media_store.UPLOAD_KINDS)
    family = kind if kind in ('image', 'video') else None
    for f in media_store.list_files(business_id, file_kinds, limit):
        if family and not (f.get('content_type') or '').startswith(family + '/'):
            continue
        items.append({
            'id': f['file_id'], 'kind': f['kind'], 'preset': None, 'prompt': None, 'status': 'succeeded',
            'file_id': f['file_id'], 'public_url': f['public_url'], 'url': f['url'], 'play_url': f['play_url'],
            'download_url': f['download_url'], 'content_type': f['content_type'],
            'created_at': f['created_at'], 'cost_estimate_usd': 0, 'source': f['source'], 'size': f.get('size'),
            'is_ai_generated': False,
        })
    items.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    return items[:limit]


@ai_studio_bp.route('/media', methods=['GET'])
@login_required
def media_list():
    business_id = _bid()
    kind = (request.args.get('kind') or '').strip()
    if kind and kind not in ('image', 'video', 'promo_video', 'social_upload'):
        return _media_err(MediaError('bad_kind', 'Unknown media kind.'))
    try:
        limit = max(1, min(int(request.args.get('limit') or 40), 100))
    except ValueError:
        limit = 40
    try:
        ai_media.sweep_stale(business_id, limit=1)   # job mồ côi thôi giữ chỗ hạn mức (tối đa 1 lần hỏi Replicate)
        items = _media_items(business_id, kind, limit)
        quota = ai_media.quota_status(business_id)
    except MediaError as e:
        return _media_err(e)
    return jsonify({"success": True, "items": items, "quota": quota, "limits": media_store.public_limits()})


@ai_studio_bp.route('/media/<file_id>', methods=['DELETE'])
@login_required
def media_delete(file_id):
    business_id = _bid()
    if not re.fullmatch(r'[0-9a-f]{24}', file_id or ''):
        return _media_err(MediaError('not_found', 'File not found.', status=404))
    grid = media_store.get(file_id, business_id)
    # Chỉ xoá media của AI Studio/Đăng bài — ảnh sản phẩm/chấm công… có màn quản lý riêng
    if grid is None or getattr(grid, 'kind', None) not in media_store.KINDS:
        return _media_err(MediaError('not_found', 'File not found.', status=404))
    media_store.delete(file_id, business_id)
    now = media_store._now()
    db.ai_media_jobs.update_many({'business_id': business_id, 'file_id': file_id},
                                 {'$set': {'deleted': True, 'deleted_at': now, 'updated_at': now}})
    try:
        db.generated_media.delete_many({'business_id': business_id, 'file_id': file_id})
    except Exception as e:
        print(f'[ai_studio] delete legacy row: {e}')
    return jsonify({"success": True, "file_id": file_id})


@ai_studio_bp.route('/quota', methods=['GET'])
@login_required
def media_quota():
    # 'presets' (kèm giá ước tính USD) luôn trả về — giao diện tự quyết ai được thấy giá
    ai_media.sweep_stale(_bid(), limit=1)
    q = ai_media.quota_status(_bid())
    return jsonify({"success": True, **q, "quota": q, "presets": ai_media.presets_public(),
                    "configured": bool((os.environ.get('REPLICATE_API_TOKEN') or '').strip()),
                    "limits": media_store.public_limits()})


@ai_studio_bp.route('/replicate_webhook', methods=['POST'])
def replicate_webhook():
    """CÔNG KHAI — Replicate gọi khi prediction xong. Không tin nội dung body: chỉ dùng làm tín hiệu rồi tự hỏi lại
    Replicate (refresh_job); chữ ký sai/thiếu -> 401."""
    raw = request.get_data(cache=True)
    if not ai_media.verify_webhook(raw, request.headers):
        return jsonify({"success": False, "code": "bad_signature"}), 401
    try:
        job_id = int(request.args.get('job', ''))
    except ValueError:
        return jsonify({"success": False, "code": "bad_job"}), 400
    job = db.ai_media_jobs.find_one({'id': job_id}, {'_id': 0, 'prediction_id': 1, 'status': 1})
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    pid = body.get('id')
    if job and not job.get('prediction_id') and job.get('status') in ai_media.ACTIVE:
        # create_job chết sau khi Replicate nhận lệnh nhưng trước khi lưu prediction_id (URL webhook mang đúng id job
        # do create_job đặt, chữ ký đã kiểm) -> nhận prediction này, không để kết quả đã trả tiền rơi mất
        adopted = ai_media.adopt_prediction(job_id, pid, body.get('model'))
        if adopted:
            job = adopted
    # Job lạ / chưa lưu prediction_id / id không khớp -> 200 để Replicate thôi gửi lại; giao diện tự hỏi lại sau
    if not job or not job.get('prediction_id') or pid != job['prediction_id']:
        return jsonify({"success": True, "ignored": True})
    try:
        job = ai_media.refresh_job(job_id)
    except MediaError as e:
        return jsonify(e.as_dict()), 503   # Replicate sẽ gửi lại webhook
    status = (job or {}).get('status')
    if status in ai_media.ACTIVE:
        # Sự kiện 'completed' mà job chưa xong: bên khác đang giữ quyền lưu / tải kết quả lỗi tạm / hỏi Replicate lỗi
        # mạng -> 503 để Replicate gửi lại sau (trả 200 thì job có thể kẹt 'running' mãi)
        return jsonify({"success": False, "code": "retry_later", "status": status}), 503
    return jsonify({"success": True, "status": status})


# ---------------------------------------------------------------- kịch bản video quảng cáo (render trên trình duyệt)
_VISUALS = ('photo', 'ai_image', 'text')


def _normalize_plan(raw, seconds):
    """Ép kịch bản DeepSeek về khung chuẩn: cảnh nối liền 0 -> seconds, tối đa 8 cảnh, chữ ngắn vừa màn hình dọc."""
    scenes_in = raw.get('scenes') if isinstance(raw, dict) else None
    if not isinstance(scenes_in, list):
        return None
    scenes_in = [s for s in scenes_in if isinstance(s, dict)][:8]
    max_n = max(1, int(seconds // 1.5))
    scenes_in = scenes_in[:max_n]
    if not scenes_in:
        return None
    weights = []
    for s in scenes_in:
        try:
            d = float(s.get('end')) - float(s.get('start'))
        except (TypeError, ValueError):
            d = 0
        weights.append(d if d > 0 and math.isfinite(d) else 0)
    if not all(weights):
        weights = [1.0] * len(scenes_in)   # mốc giờ AI đưa sai -> chia đều
    # Cảnh quá ngắn (làm tròn thành 0 giây) -> nâng lên tối thiểu, không có cảnh "chớp mắt"
    floor = sum(weights) / (3 * len(weights))
    weights = [max(w, floor) for w in weights]
    total = sum(weights)
    out, t = [], 0.0
    for i, s in enumerate(scenes_in):
        end = float(seconds) if i == len(scenes_in) - 1 else round(t + seconds * weights[i] / total, 1)
        visual = s.get('visual') if s.get('visual') in _VISUALS else 'photo'
        out.append({
            'start': round(t, 1), 'end': round(end, 1),
            'on_screen_text': str(s.get('on_screen_text') or '').strip()[:80],
            'voiceover': str(s.get('voiceover') or '').strip()[:240],
            'visual': visual, 'photo_hint': str(s.get('photo_hint') or '').strip()[:120],
        })
        t = end
    return out


@ai_studio_bp.route('/scene_plan', methods=['POST'])
@login_required
def scene_plan():
    business_id = _bid()
    data = request.get_json(silent=True) or {}
    topic = data.get('script') or data.get('topic') or ''
    topic = topic.strip()[:3000] if isinstance(topic, str) else ''
    lang = data.get('lang') if data.get('lang') in ('vi', 'en') else 'en'
    try:
        seconds = int(float(data.get('seconds', 15)))
    except (TypeError, ValueError, OverflowError):
        return jsonify({"success": False, "code": "bad_number", "message": "seconds must be a number."}), 400
    seconds = min(max(seconds, 10), 30)
    if not topic:
        return jsonify({"success": False, "code": "topic_required", "message": "Write a topic or script first."}), 400
    language = 'Vietnamese' if lang == 'vi' else 'English'
    system = (
        "You are a short-form video editor for a local business. Plan a vertical 9:16 promo video of EXACTLY "
        f"{seconds} seconds built from the shop's own photos with bold on-screen text. Use ONLY the business facts "
        "given; never invent prices, discounts, reviews, awards, statistics or opening hours. "
        "Return JSON: {\"title\": str, \"caption\": str, \"scenes\": [{\"start\": number, \"end\": number, "
        "\"on_screen_text\": str (max 7 words), \"voiceover\": str (one short sentence), \"visual\": "
        "\"photo\"|\"ai_image\"|\"text\", \"photo_hint\": str (which real shop photo fits, e.g. 'gel manicure close-up')}]}. "
        "3 to 7 scenes, contiguous from 0 to the total length; first scene is a hook, last scene is a call to action "
        "(book online if a booking link is given). Prefer visual 'photo'; use 'text' for the hook/CTA; 'ai_image' only "
        f"when no real photo could fit. Write title, caption, on_screen_text and voiceover in {language}. "
        "Caption: 1–3 sentences plus up to 5 relevant hashtags."
    )
    ctx = '\n'.join(x for x in (_business_facts(business_id), ai_media.brand_context(business_id)) if x)
    user = (ctx + '\n\n' if ctx else '') + f'Video topic / script: "{topic}"'
    try:
        text = _call_deepseek_text_json(system, user, business_id)
        raw = json.loads(re.sub(r'^```(?:json)?|```$', '', (text or '').strip(), flags=re.M).strip())
    except (RuntimeError, requests.exceptions.RequestException):
        return jsonify({"success": False, "code": "ai_unavailable", "message": "The AI writer is busy — try again."}), 502
    except ValueError:
        return jsonify({"success": False, "code": "ai_bad_output", "message": "The AI answer was not usable — try again."}), 502
    scenes = _normalize_plan(raw, seconds)
    if not scenes:
        return jsonify({"success": False, "code": "ai_bad_output", "message": "The AI answer was not usable — try again."}), 502
    return jsonify({"success": True, "seconds": seconds, "title": str(raw.get('title') or '').strip()[:90],
                    "caption": str(raw.get('caption') or '').strip()[:2200], "scenes": scenes})


def _call_deepseek_text_json(system_prompt, user_prompt, business_id):
    return ai_gateway.text('studio_scene_plan', business_id, system_prompt, user_prompt, 0.7, 1200, json_mode=True)


# ---------------------------------------------------------------- route cũ (giữ tương thích)
@ai_studio_bp.route('/generate_image', methods=['POST'])
@login_required
def generate_image_route():
    """(Cũ) = tạo job ảnh preset 'draft'. Ảnh nhanh thường xong ngay trong request nên vẫn trả media_url như trước."""
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt').strip() if isinstance(data.get('prompt'), str) else ''
    nurture_script = data.get('nurture_script').strip() if isinstance(data.get('nurture_script'), str) else ''
    business_id = _bid()
    if not business_id:
        return jsonify({"success": False, "error": "Chưa đăng nhập."}), 401
    if not prompt and not nurture_script:
        return jsonify({"success": False, "error": "Cần 'prompt' hoặc 'nurture_script'."}), 400
    try:
        if not prompt:
            ai_media.precheck(business_id, 'image')
            try:
                prompt = _derive_image_prompt(nurture_script, data.get('brand_name'), data.get('industry'), business_id)
            except (RuntimeError, requests.exceptions.RequestException):
                raise MediaError('ai_unavailable', 'The AI writer is busy — try again or type the prompt yourself.', status=502)
        job = ai_media.create_job(business_id, session.get('user_id'), 'image', 'draft', prompt,
                                  aspect=ai_media.aspect_from_size(data.get('size') or '1024x1024'), base_url=_public_base(),
                                  source_text=nurture_script or None)
    except MediaError as e:
        payload = e.as_dict()
        payload['error'] = payload['message']   # giao diện cũ đọc 'error'
        return jsonify(payload), e.status
    pub = ai_media.public_job(job)
    media_url = (job.get('public_base') or '') + job['public_url'] if job.get('public_url') else None
    if job.get('status') == 'failed':
        return jsonify({"success": False, "error": (job.get('error') or {}).get('message') or 'Generation failed',
                        "code": (job.get('error') or {}).get('code'), "job": pub}), 502
    return jsonify({"success": True, "id": job['id'], "job": pub, "status": job.get('status'),
                    "media_url": media_url, "prompt": job.get('prompt'), "quota": ai_media.quota_status(business_id)})


@ai_studio_bp.route('/media_history', methods=['GET'])
@login_required
def media_history():
    return media_list()


# Brand DNA của tiệm (tên, điểm khác biệt, khách mục tiêu, từ cấm) — lưu ở server để AI Studio dùng trên mọi máy.
# Trước đây chỉ nằm trong localStorage của 1 trình duyệt nhưng giao diện lại báo "đã lưu vào bộ nhớ DeepSeek".
_BRAND_FIELDS = (('name', 120), ('usp', 400), ('audience', 300), ('blacklist', 400))


@ai_studio_bp.route('/brand', methods=['GET', 'POST'])
@login_required
def brand_profile():
    business_id = session.get('business_id') or session.get('user_id')
    if not business_id:
        return jsonify({"success": False, "error": "Chưa đăng nhập."}), 401
    if request.method == 'GET':
        doc = db.ai_brand_profiles.find_one({'business_id': business_id}, {'_id': 0, 'business_id': 0}) or {}
        return jsonify({"success": True, "brand": doc})
    data = request.get_json() or {}
    doc = {}
    for key, max_len in _BRAND_FIELDS:
        v = data.get(key)
        doc[key] = v.strip()[:max_len] if isinstance(v, str) else ''
    doc['updated_at'] = datetime.now().isoformat()
    db.ai_brand_profiles.update_one({'business_id': business_id}, {'$set': doc}, upsert=True)
    return jsonify({"success": True, "brand": doc})
