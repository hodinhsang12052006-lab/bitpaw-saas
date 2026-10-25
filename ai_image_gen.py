"""
(CŨ) Sinh ảnh AI — nay chỉ là lớp bọc mỏng quanh ai_media.py (docs/AI_SUITE_SPEC.md §2).

Bản trước gọi /v1/predictions với 1 version hash SDXL bị CỤT (63 ký tự thay vì 64) nên Replicate luôn trả 422, và trả
về link replicate.delivery hết hạn sau ~1 giờ. ai_media dùng "official models" (không cần version hash), chép kết quả về
GridFS và tính hạn mức theo gói. Không còn module nào import file này (ai_studio_bp gọi thẳng ai_media); giữ lại để
script/đoạn code cũ gọi generate_image() không vỡ.

Không dùng OpenAI/DALL-E (đã gỡ hẳn theo yêu cầu "không dùng OpenAI").
"""
import time

import ai_media


def generate_image(prompt, size='1024x1024', business_id=None, user_id=None, base_url=None, wait_seconds=60):
    """Tạo ảnh preset 'draft' cho 1 tiệm và chờ tối đa wait_seconds. Trả (url, 'replicate') — url là link công khai
    tương đối /m/... (hoặc tuyệt đối khi có base_url). Thiếu business_id -> báo lỗi rõ (hạn mức/kho lưu theo tiệm)."""
    if not business_id:
        raise RuntimeError("generate_image() cần business_id — dùng ai_media.create_job() cho luồng mới.")
    try:
        job = ai_media.create_job(business_id, user_id, 'image', 'draft', prompt, aspect=ai_media.aspect_from_size(size),
                                  base_url=base_url)
        deadline = time.time() + max(0, int(wait_seconds))
        while job.get('status') in ai_media.ACTIVE and time.time() < deadline:
            time.sleep(2)
            job = ai_media.refresh_job(job['id'])
    except ai_media.MediaError as e:
        raise RuntimeError(e.message) from e
    if job.get('status') != 'succeeded':
        raise RuntimeError((job.get('error') or {}).get('message') or "Replicate sinh ảnh quá lâu, vui lòng thử lại.")
    return ((base_url or '').rstrip('/') + job['public_url']), 'replicate'
