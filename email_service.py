import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mongo_client import load_env_file

load_env_file()

GMAIL_USERNAME = os.environ.get("GMAIL_USERNAME")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


class EmailService:
    """Gửi email qua Gmail SMTP. Yêu cầu Google App Password (không dùng mật khẩu tài khoản Gmail thường)."""

    @staticmethod
    def send_email(nguoi_nhan, tieu_de, noi_dung_html):
        if not GMAIL_USERNAME or not GMAIL_APP_PASSWORD:
            return False, "Chưa cấu hình GMAIL_USERNAME / GMAIL_APP_PASSWORD trong biến môi trường."

        if not nguoi_nhan:
            return False, "Thiếu địa chỉ người nhận."

        msg = MIMEMultipart('alternative')
        msg['Subject'] = tieu_de
        msg['From'] = GMAIL_USERNAME
        msg['To'] = nguoi_nhan
        msg.attach(MIMEText(noi_dung_html, 'html', 'utf-8'))

        try:
            with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(GMAIL_USERNAME, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USERNAME, [nguoi_nhan], msg.as_string())
            return True, "Đã gửi email thành công."
        except smtplib.SMTPAuthenticationError:
            return False, ("Xác thực Gmail thất bại. Kiểm tra lại GMAIL_USERNAME / GMAIL_APP_PASSWORD "
                            "(phải là App Password 16 ký tự, không phải mật khẩu Gmail thông thường).")
        except Exception as e:
            return False, f"Gửi email thất bại: {str(e)}"
