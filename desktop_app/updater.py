"""
Auto-Updater. Không cần thư viện nặng (PyUpdater/esky...) cho 1 app Windows đóng gói bằng
PyInstaller onefile + trình cài đặt Inno Setup — requests + subprocess là đủ:
    1. Hỏi server bản mới nhất.
    2. Nếu có bản mới -> tải file installer .exe về thư mục temp.
    3. Chạy installer ở chế độ im lặng (Inno Setup: /VERYSILENT) rồi tự thoát app hiện tại
       để installer được phép ghi đè file .exe đang chạy dở.
"""
import os
import sys
import subprocess
import tempfile

import requests

CURRENT_VERSION = "1.0.0"  # bump tay mỗi lần build bản mới, hoặc đọc từ 1 file VERSION riêng
VERSION_CHECK_URL = os.environ.get('BITPAW_VERSION_URL', 'https://license.bitpawsoftware.com/api/v1/latest-version')


def check_for_update():
    try:
        resp = requests.get(VERSION_CHECK_URL, timeout=5)
        info = resp.json()
    except requests.RequestException:
        return  # không có mạng -> bỏ qua, chạy tiếp bản hiện tại, không chặn khởi động

    latest_version = info.get("version")
    installer_url = info.get("installer_url")
    if not latest_version or not installer_url or latest_version == CURRENT_VERSION:
        return

    print(f"[Updater] Có bản mới {latest_version} (đang chạy {CURRENT_VERSION}). Đang tải về...")
    installer_path = os.path.join(tempfile.gettempdir(), f"BitPawOS_Setup_{latest_version}.exe")

    try:
        with requests.get(installer_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(installer_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except requests.RequestException as e:
        print(f"[Updater] Tải bản mới thất bại ({e}) — chạy tiếp bản hiện tại.")
        return

    subprocess.Popen([installer_path, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
    sys.exit(0)  # installer sẽ tự khởi động lại app sau khi cài xong (cấu hình trong Inno Setup script)
