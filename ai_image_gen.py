"""
AI Studio — sinh ảnh THẬT (Mã "Hợp nhất AI bằng DeepSeek" audit). DeepSeek không có model sinh
ảnh — nhánh OpenAI/DALL-E trước đây đã bị GỠ BỎ HOÀN TOÀN (đúng yêu cầu "không dùng OpenAI").
Chỉ còn 1 lựa chọn thật: Replicate (Stable Diffusion), qua IMAGE_GEN_PROVIDER=replicate +
REPLICATE_API_TOKEN. Nếu tenant chưa cấu hình Replicate, generate_image() báo lỗi rõ ràng yêu
cầu tự upload ảnh — KHÔNG âm thầm gọi API nào khác, KHÔNG trả URL ảnh giả.

Biến môi trường cần cấu hình trong `.env`:
    IMAGE_GEN_PROVIDER=replicate          # bắt buộc phải là 'replicate' để tính năng sinh ảnh hoạt động
    REPLICATE_API_TOKEN=r8_...            # bắt buộc nếu muốn sinh ảnh AI thật
"""
import os
import time

import requests

REPLICATE_PREDICTIONS_URL = "https://api.replicate.com/v1/predictions"
# Version hash của model SDXL công khai trên Replicate — cố định version để 1 lần deploy không
# bị đổi hành vi ngầm khi Replicate cập nhật model mặc định.
REPLICATE_SDXL_VERSION = "39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08"


def _generate_image_replicate(prompt, size='1024x1024'):
    """Replicate là API BẤT ĐỒNG BỘ: tạo prediction xong phải poll GET liên tục tới khi
    status='succeeded'/'failed'."""
    api_token = os.environ.get('REPLICATE_API_TOKEN')
    if not api_token:
        raise RuntimeError("Server chưa cấu hình REPLICATE_API_TOKEN.")
    width, height = (size.split('x') + ['1024', '1024'])[:2]
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_token}"}

    try:
        create_resp = requests.post(
            REPLICATE_PREDICTIONS_URL, headers=headers, timeout=20,
            json={
                "version": REPLICATE_SDXL_VERSION,
                "input": {"prompt": prompt, "width": int(width), "height": int(height)},
            },
        )
        create_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Lỗi tạo prediction trên Replicate: {e}") from e

    prediction = create_resp.json()
    get_url = prediction['urls']['get']

    # Poll tối đa 60s (2s/lần) — SDXL thường xong trong 5-15s, 60s là ngưỡng an toàn trước khi
    # coi là timeout thay vì poll vô hạn.
    for _ in range(30):
        time.sleep(2)
        try:
            poll_resp = requests.get(get_url, headers=headers, timeout=15)
            poll_resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Lỗi khi poll kết quả Replicate: {e}") from e
        poll_data = poll_resp.json()
        status = poll_data.get('status')
        if status == 'succeeded':
            output = poll_data.get('output')
            url = output[0] if isinstance(output, list) and output else output
            if not url:
                raise RuntimeError("Replicate báo succeeded nhưng không có output ảnh nào.")
            return url
        if status == 'failed':
            raise RuntimeError(f"Replicate sinh ảnh thất bại: {poll_data.get('error')}")

    raise RuntimeError("Replicate sinh ảnh quá lâu (>60s), vui lòng thử lại.")


def generate_image(prompt, size='1024x1024'):
    """Dispatcher — nơi DUY NHẤT ai_studio_bp.py cần gọi. Chỉ hỗ trợ Replicate (DeepSeek không
    vẽ được ảnh). Nếu chưa cấu hình Replicate, ném RuntimeError với thông báo rõ ràng để route
    gọi hàm này trả lời tenant là hãy tự upload ảnh thay vì để lỗi mơ hồ hoặc âm thầm trả ảnh giả."""
    provider = os.environ.get('IMAGE_GEN_PROVIDER', '').strip().lower()
    if provider != 'replicate' or not os.environ.get('REPLICATE_API_TOKEN'):
        raise RuntimeError(
            "Tính năng AI sinh ảnh chưa được cấu hình (cần IMAGE_GEN_PROVIDER=replicate + "
            "REPLICATE_API_TOKEN). Vui lòng tự upload ảnh có sẵn thay vì dùng AI sinh ảnh lúc này."
        )
    return _generate_image_replicate(prompt, size), 'replicate'
