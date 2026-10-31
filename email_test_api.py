# File: email_test_api.py
# Endpoint nội bộ để test chức năng gửi email qua Gmail SMTP (xem email_service.py)
#
# Bảo mật (10/2026): trước đây route này KHÔNG cần đăng nhập và gửi HTML + người nhận do người gọi tự đặt, từ hộp Gmail
# thật của BitPaw (qua SPF/DKIM) -> bất kỳ ai cũng dùng làm trạm gửi thư lừa đảo / đốt hạn mức gửi. Giờ: chỉ Super Admin
# đang đăng nhập, nội dung CỐ ĐỊNH, chỉ gửi về ĐÚNG email của chính admin đó, tối đa 3 lần/giờ; lỗi SMTP không trả nguyên
# văn cho client (chỉ ghi log máy chủ).

from flask import Blueprint, jsonify, session
from email_service import EmailService
from app import _is_superadmin, limiter, login_required

email_test_bp = Blueprint('email_test', __name__, url_prefix='/api')

TEST_SUBJECT = 'Email thử nghiệm từ BitPaw · BitPaw SMTP test'
TEST_HTML = '<p>Đây là email thử nghiệm gửi qua Gmail SMTP.</p><p>This is a BitPaw SMTP test email.</p>'


@email_test_bp.route('/test-email', methods=['POST'])
@limiter.limit('3 per hour')
@login_required
def test_email():
    """Gửi 1 email thử (tiêu đề + nội dung cố định) tới email của Super Admin đang đăng nhập.
    Mọi trường người gọi gửi lên (nguoi_nhan, tieu_de, noi_dung_html) đều bị BỎ QUA."""
    if not _is_superadmin():
        return jsonify({"success": False, "message": "BitPaw admins only."}), 403
    nguoi_nhan = (session.get('user_email') or '').strip()
    if not nguoi_nhan:
        return jsonify({"success": False, "message": "No admin email on this session."}), 400

    success, message = EmailService.send_email(nguoi_nhan, TEST_SUBJECT, TEST_HTML)
    if not success:
        print(f"[test-email] send failed: {str(message)[:200]}")
        return jsonify({"success": False, "message": "Could not send the test email — check the server logs."}), 500
    return jsonify({"success": True, "message": f"Test email sent to {nguoi_nhan}."}), 200
