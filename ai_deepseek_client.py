"""
Điểm gọi DeepSeek DUY NHẤT của toàn hệ thống (Mã "Hợp nhất AI bằng DeepSeek" audit — TOÀN BỘ
tác vụ xử lý ngôn ngữ trong BitPaw OS đều đi qua đúng 1 hàm này, không còn Anthropic/OpenAI
thật nào cho text nữa). Nhánh gọi trực tiếp dùng SDK `openai` trỏ base_url về DeepSeek — DeepSeek
API tương thích 100% format OpenAI, nên dùng SDK chính hãng thay vì tự ghép JSON bằng `requests`
cho gọn và ít lỗi format hơn, nhưng KHÔNG hề gọi tới OpenAI thật (base_url luôn là DeepSeek).

- Chế độ Web/SaaS (Vercel): gọi thẳng api.deepseek.com bằng DEEPSEEK_API_KEY thật trong biến
  môi trường server — như trước giờ, không đổi.
- Chế độ Desktop App (BITPAW_DESKTOP_MODE=1, do desktop_app/launcher.py set sau khi verify
  license): KHÔNG được đóng gói DEEPSEEK_API_KEY thật vào file .exe (khách hàng giải nén đọc
  ngược ra được) — gọi qua AI Proxy trên Cloud (cloud_relay/api/ai-proxy.js) bằng `requests` (đây
  là API nội bộ tự viết, không phải endpoint OpenAI-compatible nên không dùng SDK ở nhánh này),
  Proxy đó mới cầm giữ key DeepSeek thật, Desktop app chỉ cầm 1 proxy_api_key riêng theo license.
"""
import os

import requests
from openai import OpenAI

_IS_DESKTOP = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
_PROXY_URL = os.environ.get('BITPAW_AI_PROXY_URL', 'https://your-relay-project.vercel.app/api/ai-proxy')
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

_client_cache = {}


def _get_deepseek_client(api_key):
    """Tái sử dụng 1 client OpenAI-SDK/tiến trình cho mỗi api_key (SDK tự quản lý connection
    pooling bên trong), thay vì tạo mới mỗi request."""
    client = _client_cache.get(api_key)
    if client is None:
        client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        _client_cache[api_key] = client
    return client


def deepseek_chat_completion(payload, business_id=None, proxy_api_key=None, direct_api_key=None, timeout=45):
    """payload: dict đã dựng sẵn {model, messages, temperature, max_tokens, tools, tool_choice, ...}.
    Trả về dict (không phải object SDK) để giữ nguyên cách các caller hiện có truy cập kết quả
    theo kiểu dict: result['choices'][0]['message']['content']."""
    if _IS_DESKTOP:
        if not business_id or not proxy_api_key:
            raise RuntimeError(
                "Thiếu business_id/proxy_api_key khi gọi AI Proxy ở chế độ Desktop — "
                "không thể xác thực với Cloud Proxy (kiểm tra lại license_manager.py đã set "
                "BITPAW_AI_PROXY_KEY sau khi verify license thành công chưa)."
            )
        try:
            resp = requests.post(
                _PROXY_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {proxy_api_key}"},
                json={**payload, "business_id": business_id},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Gọi AI Proxy thất bại: {e}") from e

    if not direct_api_key:
        raise RuntimeError("Thiếu DEEPSEEK_API_KEY khi gọi trực tiếp DeepSeek ở chế độ Web/SaaS.")

    try:
        client = _get_deepseek_client(direct_api_key)
        completion = client.chat.completions.create(timeout=timeout, **payload)
        return completion.model_dump()
    except Exception as e:
        raise RuntimeError(f"Gọi trực tiếp DeepSeek thất bại: {e}") from e
