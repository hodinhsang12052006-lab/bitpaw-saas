"""
Facebook Marketing API — tạo Campaign/Ad Set/Ad Creative/Ad THẬT và kéo insight THẬT (Mã AI
Ads Part 2.2 + 2.3 audit). KHÔNG còn nhánh sinh "DEMO-xxx" giả cho platform chưa hỗ trợ — nếu
tenant chọn Google/TikTok (chưa tích hợp thật), route gọi vào đây phải trả lỗi rõ ràng thay vì
giả vờ tạo thành công.

Mọi hàm ở đây nhận access_token/ad_account_id đã giải mã từ ad_platform_tokens.get_facebook_token()
— không tự quản lý token, không cache token, giữ module này thuần "gọi API".
"""
import json

import requests

GRAPH_API_VERSION = 'v21.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

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


def create_campaign(access_token, ad_account_id, name, objective, status='PAUSED'):
    """objective vd: 'OUTCOME_TRAFFIC', 'OUTCOME_ENGAGEMENT', 'OUTCOME_LEADS', 'OUTCOME_SALES'.
    status mặc định PAUSED — KHÔNG tự động chạy tiêu tiền thật ngay khi vừa tạo, chủ tiệm phải
    tự bấm 'kích hoạt' (đổi status='ACTIVE') sau khi xem lại trên Ads Manager, an toàn hơn cho
    tài khoản mới kết nối."""
    return _fb_post(
        f'{ad_account_id}/campaigns', access_token,
        name=name, objective=objective, status=status, special_ad_categories='[]',
    )['id']


def create_ad_set(access_token, ad_account_id, campaign_id, name, daily_budget_cents,
                   billing_event='IMPRESSIONS', optimization_goal='REACH', targeting=None, status='PAUSED'):
    """daily_budget_cents: đơn vị NHỎ NHẤT của tiền tệ tài khoản quảng cáo (vd AUD -> cents),
    KHÔNG phải đơn vị chính — Facebook API luôn yêu cầu số nguyên ở đơn vị nhỏ nhất này."""
    targeting = targeting or {'geo_locations': {'countries': ['AU']}, 'age_min': 18, 'age_max': 65}
    return _fb_post(
        f'{ad_account_id}/adsets', access_token,
        name=name, campaign_id=campaign_id, daily_budget=int(daily_budget_cents),
        billing_event=billing_event, optimization_goal=optimization_goal,
        targeting=json.dumps(targeting), status=status,
    )['id']


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


def launch_campaign(access_token, ad_account_id, page_id, name, objective, daily_budget_cents,
                     message, link, image_url=None):
    """Orchestrator: tạo đủ bộ Campaign -> Ad Set -> (upload ảnh nếu có) -> Ad Creative -> Ad,
    ĐÚNG yêu cầu 'tạo Ad Campaign, Ad Set, Ad Creative' — tất cả ở status=PAUSED, chủ tiệm tự
    bật chạy thật sau khi xem lại. Nếu 1 bước giữa chừng lỗi, ném RuntimeError kèm thông tin đã
    tạo được tới đâu (route gọi hàm này chịu trách nhiệm quyết định có dọn rác trên Facebook hay
    không — Facebook không có "transaction" xuyên nhiều object như MongoDB)."""
    campaign_id = create_campaign(access_token, ad_account_id, name, objective)
    ad_set_id = create_ad_set(access_token, ad_account_id, campaign_id, f"{name} - Ad Set", daily_budget_cents)

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
