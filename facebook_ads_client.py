"""
Facebook Marketing API — tạo Campaign/Ad Set/Ad Creative/Ad THẬT và kéo insight THẬT (Mã AI
Ads Part 2.2 + 2.3 audit). KHÔNG còn nhánh sinh "DEMO-xxx" giả cho platform chưa hỗ trợ — nếu
tenant chọn Google/TikTok (chưa tích hợp thật), route gọi vào đây phải trả lỗi rõ ràng thay vì
giả vờ tạo thành công.

Mọi hàm ở đây nhận access_token/ad_account_id đã giải mã từ ad_platform_tokens.get_facebook_token()
— không tự quản lý token, không cache token, giữ module này thuần "gọi API".
"""
import json
import os

import requests

GRAPH_API_VERSION = 'v21.0'
# Base URL đổi được qua env (FB_ADS_API_BASE) để test e2e bằng mock server local — không bao giờ phải gọi Meta thật khi test.
GRAPH_BASE = f"{os.environ.get('FB_ADS_API_BASE', 'https://graph.facebook.com').rstrip('/')}/{GRAPH_API_VERSION}"

# Meta tính ngân sách theo "đơn vị nhỏ nhất" của tiền tệ TÀI KHOẢN QUẢNG CÁO: USD/AUD... x100 (cent), còn
# VND/JPY/KRW... không có đơn vị lẻ -> x1 (offset=1). Trước đây luôn x100 -> tiệm VND nhập 100.000đ thành
# 10.000.000đ/ngày. Danh sách theo bảng "Currencies" của Marketing API (developers.facebook.com/docs/marketing-api/currencies).
ZERO_DECIMAL_CURRENCIES = frozenset({'CLP', 'COP', 'CRC', 'HUF', 'ISK', 'IDR', 'JPY', 'KRW', 'PYG', 'TWD', 'VND'})


def currency_offset(currency):
    return 1 if (currency or '').strip().upper() in ZERO_DECIMAL_CURRENCIES else 100


def to_minor_units(amount, currency):
    """Số tiền (đơn vị chính, vd 12.5 USD / 150000 VND) -> số nguyên đơn vị nhỏ nhất Meta yêu cầu."""
    return int(round(float(amount) * currency_offset(currency)))


def normalize_ad_account_id(ad_account_id):
    """Graph API cần dạng 'act_<số>' — chủ tiệm hay dán thiếu tiền tố 'act_'."""
    s = str(ad_account_id or '').strip()
    return f'act_{s}' if s.isdigit() else s

# Mã "Go-Live Pentest" audit — mã lỗi Facebook OAuth chuẩn cho "token hết hạn/không hợp lệ"
# (https://developers.facebook.com/docs/graph-api/guides/error-handling). Bắt riêng ra để caller
# (ads_metrics_worker.py, ad_assistant.py) có thể phân biệt "cần kết nối lại Facebook" với các
# lỗi tạm thời khác (timeout, rate limit, sai tham số...).
FB_TOKEN_ERROR_CODES = {190}
FB_TOKEN_ERROR_SUBCODES = {463, 467, 460}  # expired / password changed / session invalidated


class FacebookTokenExpiredError(RuntimeError):
    """Token Facebook (System User Access Token) đã hết hạn hoặc bị thu hồi — tenant cần vào
    lại /ad-assistant kết nối Facebook Ads Manager một lần nữa."""


def _raise_for_fb_response(path, resp):
    if resp.status_code == 200:
        return resp.json()
    body = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    fb_error = (body or {}).get('error') or {}
    if fb_error.get('code') in FB_TOKEN_ERROR_CODES or fb_error.get('error_subcode') in FB_TOKEN_ERROR_SUBCODES:
        raise FacebookTokenExpiredError(
            f"Token Facebook đã hết hạn hoặc bị thu hồi: {fb_error.get('message', resp.text)}"
        )
    raise RuntimeError(f"Facebook API từ chối {path} ({resp.status_code}): {resp.text}")


def _fb_post(path, access_token, timeout=20, **params):
    try:
        resp = requests.post(f'{GRAPH_BASE}/{path}', params={**params, 'access_token': access_token}, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Facebook API timeout khi gọi {path}.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Lỗi kết nối Facebook API ({path}): {e}") from e
    return _raise_for_fb_response(path, resp)


def _fb_get(path, access_token, timeout=20, **params):
    try:
        resp = requests.get(f'{GRAPH_BASE}/{path}', params={**params, 'access_token': access_token}, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Facebook API timeout khi gọi {path}.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Lỗi kết nối Facebook API ({path}): {e}") from e
    return _raise_for_fb_response(path, resp)


def verify_token(access_token):
    """GET /me — xác nhận token còn sống TRƯỚC khi lưu (trước đây lưu mù, chủ tiệm chỉ biết token sai lúc tạo
    chiến dịch). Token hỏng -> FacebookTokenExpiredError; lỗi khác -> RuntimeError."""
    return _fb_get('me', access_token, fields='id,name')


def get_ad_account(access_token, ad_account_id):
    """Tiền tệ + trạng thái THẬT của tài khoản quảng cáo — ngân sách phải đổi theo đúng tiền tệ này."""
    return _fb_get(normalize_ad_account_id(ad_account_id), access_token, fields='id,name,currency,account_status')


def create_campaign(access_token, ad_account_id, name, objective, status='PAUSED'):
    """objective vd: 'OUTCOME_TRAFFIC', 'OUTCOME_ENGAGEMENT', 'OUTCOME_LEADS', 'OUTCOME_SALES'.
    status mặc định PAUSED — KHÔNG tự động chạy tiêu tiền thật ngay khi vừa tạo, chủ tiệm phải
    tự bấm 'kích hoạt' (đổi status='ACTIVE') sau khi xem lại trên Ads Manager, an toàn hơn cho
    tài khoản mới kết nối."""
    return _fb_post(
        f'{ad_account_id}/campaigns', access_token,
        name=name, objective=objective, status=status, special_ad_categories='[]',
    )['id']


def create_ad_set(access_token, ad_account_id, campaign_id, name, daily_budget_minor, targeting,
                   billing_event='IMPRESSIONS', optimization_goal='REACH', status='PAUSED', end_time=None):
    """daily_budget_minor: đơn vị NHỎ NHẤT của tiền tệ tài khoản quảng cáo (xem to_minor_units — USD x100,
    VND x1). targeting BẮT BUỘC có quốc gia: trước đây mặc định cứng nước Úc (AU) nên tiệm Việt/Mỹ chạy quảng
    cáo cho người Úc. end_time (ISO 8601): ngày dừng — ngân sách/ngày x số ngày không vượt tổng chủ tiệm nhập."""
    if not targeting or not (targeting.get('geo_locations') or {}).get('countries'):
        raise ValueError("targeting phải có geo_locations.countries (quốc gia của tiệm).")
    params = dict(
        name=name, campaign_id=campaign_id, daily_budget=int(daily_budget_minor),
        billing_event=billing_event, optimization_goal=optimization_goal,
        targeting=json.dumps(targeting), status=status,
    )
    if end_time:
        params['end_time'] = end_time
    return _fb_post(f'{ad_account_id}/adsets', access_token, **params)['id']


def upload_ad_image(access_token, ad_account_id, image_url):
    """Tải ảnh từ media_url (vd: ảnh do ai_image_gen.generate_image() sinh ra, lưu ở
    db.generated_media) rồi upload lên thư viện ảnh quảng cáo của Facebook, trả về `image_hash`
    để dùng trong create_ad_creative(). Facebook KHÔNG cho dùng thẳng 1 URL ảnh bên ngoài làm
    creative — bắt buộc phải upload vào tài khoản quảng cáo trước."""
    try:
        img_resp = requests.get(image_url, timeout=20)
        img_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Không tải được ảnh từ media_url để upload lên Facebook: {e}") from e

    try:
        resp = requests.post(
            f'{GRAPH_BASE}/{ad_account_id}/adimages',
            params={'access_token': access_token},
            files={'file': ('ad_image.jpg', img_resp.content)},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Lỗi kết nối Facebook API khi upload ảnh quảng cáo: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"Facebook API từ chối upload ảnh quảng cáo ({resp.status_code}): {resp.text}")

    images = resp.json().get('images', {})
    first_image = next(iter(images.values()), None)
    if not first_image or not first_image.get('hash'):
        raise RuntimeError("Facebook không trả về image_hash sau khi upload ảnh quảng cáo.")
    return first_image['hash']


def create_ad_creative(access_token, ad_account_id, page_id, name, message, link, image_hash=None):
    link_data = {'message': message, 'link': link}
    if image_hash:
        link_data['image_hash'] = image_hash
    object_story_spec = {'page_id': page_id, 'link_data': link_data}
    return _fb_post(
        f'{ad_account_id}/adcreatives', access_token,
        name=name, object_story_spec=json.dumps(object_story_spec),
    )['id']


def create_ad(access_token, ad_account_id, name, ad_set_id, creative_id, status='PAUSED'):
    return _fb_post(
        f'{ad_account_id}/ads', access_token,
        name=name, adset_id=ad_set_id, creative=json.dumps({'creative_id': creative_id}), status=status,
    )['id']


def launch_campaign(access_token, ad_account_id, page_id, name, objective, daily_budget_minor,
                     message, link, image_url=None, targeting=None, end_time=None):
    """Orchestrator: tạo đủ bộ Campaign -> Ad Set -> (upload ảnh nếu có) -> Ad Creative -> Ad,
    ĐÚNG yêu cầu 'tạo Ad Campaign, Ad Set, Ad Creative' — tất cả ở status=PAUSED, chủ tiệm tự
    bật chạy thật sau khi xem lại. Nếu 1 bước giữa chừng lỗi, ném RuntimeError kèm thông tin đã
    tạo được tới đâu (route gọi hàm này chịu trách nhiệm quyết định có dọn rác trên Facebook hay
    không — Facebook không có "transaction" xuyên nhiều object như MongoDB)."""
    # Kiểm tra targeting TRƯỚC khi tạo campaign — tránh để lại campaign rác trên Facebook khi ad set chắc chắn lỗi
    if not targeting or not (targeting.get('geo_locations') or {}).get('countries'):
        raise ValueError("targeting phải có geo_locations.countries (quốc gia của tiệm).")
    campaign_id = create_campaign(access_token, ad_account_id, name, objective)
    ad_set_id = create_ad_set(access_token, ad_account_id, campaign_id, f"{name} - Ad Set", daily_budget_minor,
                              targeting, end_time=end_time)

    image_hash = None
    if image_url:
        image_hash = upload_ad_image(access_token, ad_account_id, image_url)

    creative_id = create_ad_creative(access_token, ad_account_id, page_id, f"{name} - Creative", message, link, image_hash)
    ad_id = create_ad(access_token, ad_account_id, f"{name} - Ad", ad_set_id, creative_id)

    return {
        'campaign_id': campaign_id, 'ad_set_id': ad_set_id,
        'creative_id': creative_id, 'ad_id': ad_id,
    }


def fetch_campaign_insights(access_token, campaign_id, date_preset='yesterday'):
    """Kéo insight THẬT (Mã AI Ads Part 2.3) — dùng bởi ads_metrics_worker.py chạy định kỳ.
    date_preset chuẩn Facebook: 'today', 'yesterday', 'last_7d', 'last_30d'..."""
    data = _fb_get(
        f'{campaign_id}/insights', access_token,
        fields='impressions,clicks,spend,ctr,cpc,reach', date_preset=date_preset,
    )
    rows = data.get('data') or []
    if not rows:
        # Campaign chưa có traffic nào trong khoảng date_preset (bình thường với campaign mới
        # tạo/đang PAUSED) — trả về 0 thay vì lỗi, để worker vẫn ghi được 1 dòng metric = 0.
        return {'impressions': 0, 'clicks': 0, 'spend': 0, 'ctr': 0, 'cpc': 0, 'reach': 0}
    return rows[0]
