"""
AI Core gateway (Phase 1, 26/10/2026) — 1 cổng cho các lệnh gọi AI chữ (DeepSeek) của BitPaw:

  chat(feature, business_id, payload)   gọi ai_deepseek_client.deepseek_chat_completion với timeout + thử lại 1 lần cho lỗi
                                        tạm thời (mạng/429/5xx, KHÔNG thử lại khi đã hết thời gian), rồi ghi 1 dòng db.ai_usage
                                        từ trường `usage` THẬT DeepSeek trả về:
                                        {business_id, feature, kind 'text', model, prompt_tokens, completion_tokens,
                                         cache_hit_tokens, units, cost_usd, usage_missing, created_at}
  text(feature, business_id, system, user, ...)   = chat() rồi trả chữ.
  allowed(business_id, feature)         cổng gói LÚC CHẠY: plans.FEATURE_MIN_PLAN + tiệm cũ chưa có gói = Empire
                                        (plans.business_plan, cache 60 giây) -> hạ gói thì AI trả phí dừng trong <= 60 giây.
  begin()/end(), scope(), tag_request() gắn tính năng + tiệm cho lệnh DeepSeek gọi THẲNG ai_deepseek_client ở chỗ khác
                                        (vd vòng Function Calling _call_deepseek_with_tools trong app.py): client báo về
                                        on_client_completion() sau mỗi lệnh thành công -> vẫn ghi đúng sổ, không ghi 2 lần.
  usage_summary(business_id, month)     tổng số lệnh / token / chi phí THẬT theo tính năng trong 1 tháng (giờ của tiệm).

Không gọi API trả phí nào ngoài chính lệnh DeepSeek được yêu cầu; ghi sổ là best-effort (lỗi DB không làm hỏng câu trả lời).
"""
import contextlib
import contextvars
import importlib
import os
import re
import sys
import time
from datetime import datetime, timezone

import plans

# ---- Bảng giá DeepSeek (USD / 1 triệu token) ------------------------------------------------------------------------
# Giá niêm yết api-docs.deepseek.com/quick_start/pricing — deepseek-chat & deepseek-reasoner (V3.2) từ 29/09/2025:
# input trúng cache 0.028, input không trúng cache 0.28, output 0.42. CHỦ BITPAW XÁC NHẬN lại với trang giá / hoá đơn
# DeepSeek hiện tại trước khi dùng cost_usd để tính tiền khách; đổi giá chỉ cần sửa đúng bảng này.
DEEPSEEK_PRICES_USD_PER_M = {
    'deepseek-chat': {'input_cache_hit': 0.028, 'input_cache_miss': 0.28, 'output': 0.42},
    'deepseek-reasoner': {'input_cache_hit': 0.028, 'input_cache_miss': 0.28, 'output': 0.42},
}
DEFAULT_MODEL = 'deepseek-chat'
CACHE_TTL = 60   # giây — gói của tiệm đọc lại tối đa mỗi 60 giây (plans.business_plan)

# Tính năng ghi sổ -> (tính năng của gói trong plans.FEATURE_MIN_PLAN hoặc None = không khoá, nhãn vi, nhãn en)
USAGE_FEATURES = {
    'booking_chat': ('ai_inbox', 'Trợ lý chat trên trang đặt lịch', 'Booking-page chat assistant'),
    'inbox_reply': ('ai_inbox', 'AI trả lời tin nhắn (Messenger, Instagram, WhatsApp, Zalo, Viber)',
                    'AI message replies (Messenger, Instagram, WhatsApp, Zalo, Viber)'),
    'sms_reply': ('ai_inbox', 'AI trả lời SMS', 'AI SMS replies'),
    'studio_text': ('ai_studio', 'AI Studio: viết nội dung', 'AI Studio: writing'),
    'studio_image_prompt': ('ai_studio', 'AI Studio: viết mô tả ảnh/video', 'AI Studio: image/video prompts'),
    'studio_scene_plan': ('ai_studio', 'AI Studio: kịch bản video quảng cáo', 'AI Studio: promo video script'),
    'social_caption': ('marketing_pro', 'Mạng xã hội: chú thích bài đăng', 'Social: post captions'),
    'social_plan': ('marketing_pro', 'Mạng xã hội: kế hoạch đăng bài tuần', 'Social: weekly post plan'),
    'social_review': ('marketing_pro', 'Mạng xã hội: nhận xét hiệu quả', 'Social: performance review'),
    'copilot': ('ai_copilot', 'AI Copilot', 'AI Copilot'),
    'ad_assistant': ('marketing_pro', 'Trợ lý quảng cáo: viết mẫu quảng cáo', 'Ad Assistant: ad copy'),
    'sales_bot': (None, 'Bot tư vấn BitPaw', 'BitPaw sales assistant'),
    'other': (None, 'AI khác', 'Other AI'),
}
MEDIA_LABELS = {'image': ('Ảnh AI', 'AI images', 'images'), 'video': ('Video AI', 'AI video', 'seconds')}
# Lệnh DeepSeek không được gắn tính năng nhưng chạy trong 1 route đã biết (theo request.endpoint)
_ENDPOINT_FEATURES = {
    'api_ai_copilot': 'copilot', 'ad_assistant.suggest': 'ad_assistant',
    'ai_studio.media_create_job': 'studio_image_prompt', 'ai_studio.generate_image_route': 'studio_image_prompt',
}
# Ghi vào bot_customers.handoff_reason khi gói không có AI trả lời (hộp thư /ai_bot hiện cho chủ tiệm)
PLAN_PAUSED_REASON = 'AI paused: plan — AI replies are included in Pro. Please reply to this customer.'

_SCOPE = contextvars.ContextVar('bitpaw_ai_gateway_scope', default=None)
_IN_CHAT = contextvars.ContextVar('bitpaw_ai_gateway_in_chat', default=False)
_VI_RE = re.compile(r'[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]'
                    r'|\b(khong|duoc|bao nhieu|nhieu|em oi|anh oi|chi oi|minh|cho em|cua|nhe|nha|vay|gium|giup|tiem|quan)\b', re.I)


class AIUnavailable(RuntimeError):
    """AI không chạy được cho yêu cầu này (RuntimeError: các chỗ đang bắt lỗi DeepSeek vẫn bắt được)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AIPlanBlocked(AIUnavailable):
    """Gói của tiệm không có tính năng AI này."""


def _db(load=True):
    mod = sys.modules.get('mongo_client')
    if mod is None and load:
        try:
            import mongo_client as mod
        except Exception:
            return None
    return getattr(mod, 'db', None)


def _client():
    # Tra lúc gọi (không giữ tham chiếu lúc import) để test thay được ai_deepseek_client trong sys.modules
    return importlib.import_module('ai_deepseek_client')


# ---- Cổng gói lúc chạy --------------------------------------------------------------------------------------------
def plan_feature(feature):
    """Tính năng của gói (khoá trong plans.FEATURE_MIN_PLAN) ứng với 1 tính năng ghi sổ, hoặc None (không khoá)."""
    if feature in plans.FEATURE_MIN_PLAN:
        return feature
    return (USAGE_FEATURES.get(feature) or (None,))[0]


def allowed(business_id, feature):
    """True nếu gói HIỆN TẠI của tiệm có tính năng (cache CACHE_TTL giây). Tiệm cũ chưa có trường plan = Empire.
    Không đọc được DB -> True (không cắt tính năng của tiệm đang trả tiền vì lỗi tạm)."""
    need = plan_feature(feature)
    if not need:
        return True
    db = _db()
    if db is None:
        return True
    return plans.business_allows(db, business_id, need, ttl=CACHE_TTL)


def _shop(business_id):
    db = _db()
    if db is None or not business_id:
        return {}
    try:
        return db.businesses.find_one({'id': business_id}, {'_id': 0, 'name': 1, 'country': 1, 'currency': 1}) or {}
    except Exception:
        return {}


def unavailable_reply(business_id, message=None):
    """Trả lời KHÔNG dùng AI cho chat trang đặt lịch khi gói của tiệm chưa có trợ lý AI (Essential / vừa hạ gói).
    Giữ đúng khuôn {"choices": [...]} để widget cũ vẫn hiện được câu này; widget mới đọc ai_unavailable + contact."""
    biz = _shop(business_id)
    name = (biz.get('name') or '').strip()
    if '@' in name:   # tài khoản cũ lấy email làm tên tiệm
        name = ''
    phone = ''
    try:
        import booking_rules
        phone = booking_rules.business_phone(business_id) or ''
    except Exception:
        phone = ''
    msg = message.strip() if isinstance(message, str) else ''
    if msg:
        vi = bool(_VI_RE.search(msg))
    else:
        vi = (biz.get('country') or '').upper() == 'VN' or (biz.get('currency') or '').upper() == 'VND'
    if vi:
        text = (f"{name or 'Tiệm'} chưa bật trợ lý chat trực tuyến. Bạn vẫn đặt lịch được bằng form trên trang này"
                + (f", hoặc gọi / nhắn tin cho tiệm: {phone}." if phone else ", hoặc liên hệ trực tiếp với tiệm."))
    else:
        text = (f"Online chat isn't available for {name or 'this business'}. You can still book with the form on this page"
                + (f", or call / text {phone}." if phone else ", or contact the business directly."))
    return {'ai_unavailable': True, 'reason': 'plan', 'lang': 'vi' if vi else 'en',
            'choices': [{'message': {'role': 'assistant', 'content': text}}],
            'contact': {'name': name or None, 'phone': phone or None}}


# ---- Phạm vi ghi sổ (tính năng + tiệm) ----------------------------------------------------------------------------
class _Scope:
    __slots__ = ('feature', 'business_id', 'calls', 'prompt_tokens', 'completion_tokens', 'cost_usd')

    def __init__(self, feature, business_id):
        self.feature, self.business_id = feature, business_id
        self.calls = self.prompt_tokens = self.completion_tokens = 0
        self.cost_usd = 0.0

    def add(self, row):
        self.calls += 1
        self.prompt_tokens += row['prompt_tokens']
        self.completion_tokens += row['completion_tokens']
        self.cost_usd += row['cost_usd']


def begin(feature, business_id=None):
    """Mọi lệnh DeepSeek sau đó (cùng luồng) ghi sổ theo tính năng + tiệm này cho tới end(token)."""
    return _SCOPE.set(_Scope(feature, business_id))


def end(token):
    try:
        _SCOPE.reset(token)
    except Exception:
        _SCOPE.set(None)


@contextlib.contextmanager
def scope(feature, business_id=None):
    tok = begin(feature, business_id)
    try:
        yield _SCOPE.get()
    finally:
        end(tok)


def tag_request(feature, business_id=None):
    """Như begin() nhưng cho hết request Flask hiện tại (flask.g tự hết hạn cuối request, không cần end)."""
    try:
        from flask import g, has_request_context
        if has_request_context():
            g._bitpaw_ai_scope = _Scope(feature, business_id)
            return g._bitpaw_ai_scope
    except Exception:
        pass
    return None


def _current():
    s = _SCOPE.get()
    if s is not None:
        return s
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, '_bitpaw_ai_scope', None)
    except Exception:
        pass
    return None


def run_totals():
    """Tổng của phạm vi hiện tại (để _log_ai_run ghi kèm chi phí vào db.ai_runs); không có phạm vi -> {}."""
    s = _current()
    if s is None or not s.calls:
        return {}
    return {'ai_calls': s.calls, 'prompt_tokens': s.prompt_tokens, 'completion_tokens': s.completion_tokens,
            'cost_usd': round(s.cost_usd, 8)}


def _request_info():
    """(tính năng theo route, endpoint, business_id trong phiên) của request Flask hiện tại, nếu có."""
    try:
        from flask import has_request_context, request, session
        if has_request_context():
            ep = request.endpoint or ''
            return _ENDPOINT_FEATURES.get(ep, 'other'), ep or None, session.get('business_id') or session.get('user_id')
    except Exception:
        pass
    return 'other', None, None


# ---- Ghi sổ -----------------------------------------------------------------------------------------------------
def _int(v):
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def cost_usd(model, prompt_tokens, completion_tokens, cache_hit_tokens=0):
    p = DEEPSEEK_PRICES_USD_PER_M.get('deepseek-reasoner' if str(model or '').startswith('deepseek-reasoner') else DEFAULT_MODEL)
    hit = min(_int(cache_hit_tokens), _int(prompt_tokens))
    miss = _int(prompt_tokens) - hit
    return round((hit * p['input_cache_hit'] + miss * p['input_cache_miss'] + _int(completion_tokens) * p['output']) / 1e6, 8)


def usage_row(feature, business_id, result, payload=None):
    usage = (result or {}).get('usage') if isinstance(result, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    pt, ct = _int(usage.get('prompt_tokens')), _int(usage.get('completion_tokens'))
    hit = usage.get('prompt_cache_hit_tokens')   # DeepSeek; định dạng OpenAI mới: prompt_tokens_details.cached_tokens
    if hit is None:
        details = usage.get('prompt_tokens_details')
        hit = details.get('cached_tokens') if isinstance(details, dict) else 0
    hit = min(_int(hit), pt)
    model = (result or {}).get('model') if isinstance(result, dict) else None
    model = str(model or (payload or {}).get('model') or DEFAULT_MODEL)[:60]
    return {'business_id': business_id, 'feature': feature if feature in USAGE_FEATURES else 'other', 'kind': 'text',
            'model': model, 'prompt_tokens': pt, 'completion_tokens': ct, 'cache_hit_tokens': hit, 'units': pt + ct,
            'cost_usd': cost_usd(model, pt, ct, hit),
            # 1 = phản hồi không có trường usage (vd proxy cắt mất) -> token/chi phí dòng này chưa đủ, tổng tháng báo rõ
            'usage_missing': 0 if usage else 1,
            'job_id': None, 'created_at': datetime.now(timezone.utc)}


def record(feature, business_id, result, payload=None, endpoint=None, load_db=True):
    """Ghi 1 dòng db.ai_usage cho 1 lệnh DeepSeek thành công + cộng vào phạm vi hiện tại. Không bao giờ ném lỗi."""
    try:
        row = usage_row(feature, business_id, result, payload)
    except Exception as e:
        print(f'[ai_gateway] usage row: {e}')
        return None
    if endpoint:
        row['endpoint'] = str(endpoint)[:80]
    s = _current()
    if s is not None:
        s.add(row)
    db = _db(load=load_db)
    if db is not None:
        try:
            db.ai_usage.insert_one(dict(row))
        except Exception as e:
            print(f'[ai_gateway] usage log: {e}')
    return row


def on_client_completion(result, payload=None, business_id=None):
    """ai_deepseek_client gọi sau MỖI lệnh DeepSeek thành công. Lệnh của chat() đã tự ghi -> bỏ qua; lệnh gọi thẳng client
    ghi theo phạm vi đang mở (begin/scope/tag_request), không có thì theo route + business_id truyền vào client."""
    if _IN_CHAT.get():
        return None
    s = _current()
    feature, endpoint, session_bid = _request_info()
    if s is not None:
        feature, bid = s.feature, s.business_id
    else:
        bid = business_id or session_bid
    # Chỉ ghi khi tiến trình ĐÃ có kết nối DB (app/test) — script lẻ dùng client không tự mở kết nối DB nào
    return record(feature, bid, result, payload, endpoint=endpoint, load_db=False)


# ---- Gọi DeepSeek ---------------------------------------------------------------------------------------------------
def _transient(exc):
    """Lỗi đáng thử lại: mất kết nối, 429, 5xx. Hết thời gian chờ thì KHÔNG (thử lại = gấp đôi thời gian chờ của khách)."""
    for e in (exc, getattr(exc, '__cause__', None)):
        if e is None:
            continue
        name = type(e).__name__
        if 'Timeout' in name:
            return False
        status = getattr(e, 'status_code', None)
        if status is None:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
        if isinstance(status, int) and (status == 429 or status >= 500):
            return True
        if name in ('APIConnectionError', 'ConnectionError', 'RemoteDisconnected', 'ChunkedEncodingError'):
            return True
    return False


def chat(feature, business_id, payload, timeout=45, retries=1, require=None):
    """1 lệnh DeepSeek qua gateway -> dict kết quả như deepseek_chat_completion (result['choices'][0]['message']...).
    require='ai_inbox'... -> kiểm gói trước (AIPlanBlocked). Lỗi cuối cùng được ném lại NGUYÊN loại (caller bắt như cũ)."""
    if require and not allowed(business_id, require):
        raise AIPlanBlocked('plan', f"The shop's plan does not include {plan_feature(require)}.")
    desktop = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
    kwargs = {'business_id': business_id,
              'proxy_api_key': os.environ.get('BITPAW_AI_PROXY_KEY') if desktop else None,
              'direct_api_key': None if desktop else os.environ.get('DEEPSEEK_API_KEY'),
              'timeout': timeout}
    client = _client()
    no_sdk_retry = getattr(client, 'sdk_retries', None)   # thử lại do gateway quyết, không chồng thêm 2 lần của SDK
    t0 = time.monotonic()
    attempt = 0
    while True:
        tok = _IN_CHAT.set(True)
        try:
            with (no_sdk_retry(0) if no_sdk_retry else contextlib.nullcontext()):
                result = client.deepseek_chat_completion(payload, **kwargs)
            break
        except Exception as e:
            if attempt >= retries or not _transient(e) or time.monotonic() - t0 > timeout / 2.0:
                raise
            attempt += 1
            time.sleep(min(0.5 * attempt, 2.0))
        finally:
            _IN_CHAT.reset(tok)
    s = _current()
    bid = business_id if business_id is not None else (s.business_id if s is not None else None)
    record(feature, bid, result, payload)
    return result


def text(feature, business_id, system_prompt, user_prompt, temperature=0.7, max_tokens=1000, json_mode=False, **kw):
    payload = {'model': DEFAULT_MODEL,
               'messages': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
               'temperature': temperature, 'max_tokens': max_tokens}
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    result = chat(feature, business_id, payload, **kw)
    return result['choices'][0]['message']['content']


# ---- Tổng chi phí theo tháng (owner) ------------------------------------------------------------------------------
_MONTH_RE = re.compile(r'^(\d{4})-(\d{2})$')


def shop_tz(business_id):
    from zoneinfo import ZoneInfo
    try:
        import messaging
        return ZoneInfo(messaging.get_settings(business_id)['timezone'])
    except Exception:
        return timezone.utc


def month_window(business_id, month=None, now=None):
    """('YYYY-MM', múi giờ, đầu tháng UTC, đầu tháng sau UTC) theo giờ của tiệm. month sai dạng -> ValueError."""
    tz = shop_tz(business_id)
    if month:
        m = _MONTH_RE.match(str(month).strip())
        if not m or not (2020 <= int(m.group(1)) <= 2100 and 1 <= int(m.group(2)) <= 12):
            raise ValueError('month must look like 2026-10')
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        local = (now or datetime.now(timezone.utc)).astimezone(tz)
        y, mo = local.year, local.month
    start = datetime(y, mo, 1, tzinfo=tz)
    nxt = datetime(y + (mo == 12), 1 if mo == 12 else mo + 1, 1, tzinfo=tz)
    return f'{y:04d}-{mo:02d}', tz, start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def usage_summary(business_id, month=None):
    """Số lệnh, token, chi phí THẬT theo tính năng trong 1 tháng (giờ của tiệm). Chi phí tính bằng USD vì DeepSeek/Replicate
    tính tiền bằng USD (không tự đổi sang tiền của tiệm để khỏi bịa tỷ giá)."""
    label, tz, start, end = month_window(business_id, month)
    db = _db()
    groups = []
    if db is not None and business_id:
        groups = list(db.ai_usage.aggregate([
            {'$match': {'business_id': business_id, 'created_at': {'$gte': start, '$lt': end}, 'qa_test': {'$ne': True}}},
            {'$group': {'_id': {'kind': '$kind', 'feature': '$feature'}, 'calls': {'$sum': 1},
                        'prompt_tokens': {'$sum': '$prompt_tokens'}, 'completion_tokens': {'$sum': '$completion_tokens'},
                        'units': {'$sum': '$units'}, 'cost_usd': {'$sum': '$cost_usd'},
                        'usage_missing': {'$sum': '$usage_missing'}}},
        ]))
    text_rows, media_rows, untracked = [], [], 0
    for g in groups:
        key = g.get('_id') or {}
        kind, feature = key.get('kind'), key.get('feature')
        if kind == 'text':
            # Dòng của bộ ghi cũ (ai_media.log_text_usage: chỉ ghi max_tokens xin, chi phí 0) — không phải số token thật,
            # không cộng vào tổng (lệnh đó đã có dòng thật của gateway nếu chạy sau Phase 1)
            if not feature:
                untracked += int(g.get('calls') or 0)
                continue
            lab = USAGE_FEATURES.get(feature) or USAGE_FEATURES['other']
            text_rows.append({'feature': feature, 'label_vi': lab[1], 'label_en': lab[2], 'calls': int(g.get('calls') or 0),
                              'prompt_tokens': int(g.get('prompt_tokens') or 0),
                              'completion_tokens': int(g.get('completion_tokens') or 0),
                              'cost_usd': round(float(g.get('cost_usd') or 0), 6),
                              'calls_without_usage': int(g.get('usage_missing') or 0)})
        elif kind in MEDIA_LABELS:
            lab = MEDIA_LABELS[kind]
            media_rows.append({'kind': kind, 'label_vi': lab[0], 'label_en': lab[1], 'jobs': int(g.get('calls') or 0),
                               'units': int(g.get('units') or 0), 'unit': lab[2], 'cost_usd': round(float(g.get('cost_usd') or 0), 6),
                               'cost_is_estimate': True})
    text_rows.sort(key=lambda r: (-r['cost_usd'], -r['calls'], r['feature']))
    media_rows.sort(key=lambda r: r['kind'])
    totals = {'calls': sum(r['calls'] for r in text_rows), 'prompt_tokens': sum(r['prompt_tokens'] for r in text_rows),
              'completion_tokens': sum(r['completion_tokens'] for r in text_rows),
              'text_cost_usd': round(sum(r['cost_usd'] for r in text_rows), 6),
              'media_cost_usd': round(sum(r['cost_usd'] for r in media_rows), 6)}
    totals['cost_usd'] = round(totals['text_cost_usd'] + totals['media_cost_usd'], 6)
    plan = plans.business_plan(db, business_id, ttl=CACHE_TTL) if db is not None else plans.DEFAULT_PLAN_FOR_EXISTING
    return {'month': label, 'timezone': getattr(tz, 'key', 'UTC'), 'from': start.isoformat(), 'to': end.isoformat(),
            'currency': 'USD', 'plan': plan, 'ai_replies_enabled': plans.allows(plan, 'ai_inbox'),
            'text': text_rows, 'media': media_rows, 'totals': totals, 'untracked_text_calls': untracked,
            'note_vi': ('Chi phí chữ = số token THẬT DeepSeek trả về x bảng giá niêm yết DeepSeek (USD). Ảnh/video = chi phí '
                        'ước tính theo bảng giá của từng mẫu. Dòng của bộ ghi cũ (untracked_text_calls) không có số token thật nên không cộng vào tổng.'),
            'note_en': ('Text cost = the REAL token counts DeepSeek returned x DeepSeek list prices (USD). Images/video = estimated '
                        'cost from each preset\'s price. Rows from the old text logger (untracked_text_calls) have no real token counts and are not in the totals.')}
