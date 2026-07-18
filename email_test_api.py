# File: email_test_api.py
# Endpoint nội bộ để test chức năng gửi email qua Gmail SMTP (xem email_service.py)

from flask import Blueprint, request, jsonify
from email_service import EmailService

email_test_bp = Blueprint('email_test', __name__, url_prefix='/api')


@email_test_bp.route('/test-email', methods=['POST'])
def test_email():
    """
    Nhận JSON:
    {
        "nguoi_nhan": "abc@gmail.com",
        "tieu_de": "Chủ đề email (tuỳ chọn)",
        "noi_dung_html": "<b>Nội dung HTML</b> (tuỳ chọn)"
    }
    """
    data = request.get_json() or {}

    nguoi_nhan = (data.get('nguoi_nhan') or '').strip()
    if not nguoi_nhan:
        return jsonify({"error": "nguoi_nhan is required"}), 400

    tieu_de = data.get('tieu_de', 'Email thử nghiệm từ BitPaw')
    noi_dung_html = data.get('noi_dung_html', '<p>Đây là email thử nghiệm gửi qua Gmail SMTP.</p>')

    success, message = EmailService.send_email(nguoi_nhan, tieu_de, noi_dung_html)
    return jsonify({"success": success, "message": message}), (200 if success else 500)
