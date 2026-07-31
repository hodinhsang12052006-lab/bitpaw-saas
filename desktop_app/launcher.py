"""
Entry point khi build .exe. Không đụng vào app.py — chỉ import app object của nó,
chạy Flask bằng werkzeug ở 1 thread nền, rồi mở 1 cửa sổ webview trỏ vào localhost.
Đóng cửa sổ webview -> tắt luôn server Flask nền theo.
"""
import os
import sys
import threading
import time

import webview
from werkzeug.serving import make_server


def resource_path(relative_path):
    """PyInstaller --onefile giải nén toàn bộ vào thư mục tạm sys._MEIPASS lúc chạy.
    Nếu không trỏ đúng vào đó, mọi đường dẫn tương đối (templates/, static/, .env cũ) sẽ
    trỏ nhầm vào thư mục chứa file .exe thay vì nội dung đã đóng gói bên trong."""
    base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    return os.path.join(base_path, relative_path)


# app.py nằm ở thư mục gốc project, desktop_app/ là thư mục con -> phải thêm gốc vào sys.path
sys.path.insert(0, resource_path('.'))

from license_manager import verify_license_or_exit  # noqa: E402
from updater import check_for_update  # noqa: E402


class ServerThread(threading.Thread):
    def __init__(self, flask_app, port=5001):
        super().__init__(daemon=True)
        self.srv = make_server('127.0.0.1', port, flask_app, threaded=True)

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()


def main():
    license_data = verify_license_or_exit()   # thoát ngay nếu license không hợp lệ/hết hạn và không có cache offline hợp lệ
    check_for_update()          # nếu có bản mới: tự tải + tự chạy installer + sys.exit(0), không return về đây

    # Báo cho app.py biết đang chạy Desktop mode -> KHÔNG gọi thẳng DeepSeek bằng key thật
    # (file .exe không chứa key thật), mà gọi qua AI Proxy bằng proxy_api_key cấp riêng theo
    # license này (xem ai_deepseek_client.py + cloud_relay/api/ai-proxy.js).
    os.environ['BITPAW_DESKTOP_MODE'] = '1'
    proxy_key = (license_data or {}).get('config', {}).get('proxy_api_key')
    if not proxy_key:
        print(
            "[Launcher] CẢNH BÁO: license server không trả về config.proxy_api_key — "
            "tính năng AI Bot sẽ không gọi được DeepSeek qua Proxy cho tới khi license "
            "server được cấu hình cấp trường này."
        )
    else:
        os.environ['BITPAW_AI_PROXY_KEY'] = proxy_key

    from app import app  # import trễ, sau khi license/update xong, tránh khởi tạo app 2 lần

    server = ServerThread(app, port=5001)
    server.start()
    time.sleep(0.8)  # đợi Flask bind port xong trước khi mở cửa sổ webview

    webview.create_window(
        'BitPaw OS',
        'http://127.0.0.1:5001',
        width=1440,
        height=900,
        min_size=(1024, 700),
    )
    webview.start()   # block tới khi người dùng đóng cửa sổ
    server.shutdown()


if __name__ == '__main__':
    main()
