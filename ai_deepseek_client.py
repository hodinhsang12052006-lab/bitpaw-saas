"""
Điểm gọi DeepSeek DUY NHẤT của toàn hệ thống.

- Chế độ Web/SaaS (Vercel): gọi thẳng api.deepseek.com bằng DEEPSEEK_API_KEY thật trong biến
  môi trường server — như trước giờ, không đổi.
- Chế độ Desktop App (BITPAW_DESKTOP_MODE=1, do desktop_app/launcher.py set sau khi verify
  license): KHÔNG được đóng gói DEEPSEEK_API_KEY thật vào file .exe (khách hàng giải nén đọc
  ngược ra được) — gọi qua AI Proxy trên Cloud (cloud_relay/api/ai-proxy.js), Proxy đó mới
  cầm giữ key thật, Desktop app chỉ cầm 1 proxy_api_key riêng theo từng license.
"""
import os

import requests

_IS_DESKTOP = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
_PROXY_URL = os.environ.get('BITPAW_AI_PROXY_URL', 'https://your-relay-project.vercel.app/api/ai-proxy')


def deepseek_chat_completion(payload, business_id=None, proxy_api_key=None, direct_api_key=None, timeout=45):
    """payload: dict đã dựng sẵn {model, messages, temperature, max_tokens, tools, tool_choice}."""
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
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {direct_api_key}"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Gọi trực tiếp DeepSeek thất bại: {e}") from e
