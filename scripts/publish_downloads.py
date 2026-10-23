"""Đưa file cài đặt mới lên website (thay GitHub Releases): chép bản build vào static/downloads/ + ghi downloads_manifest.json.

    python scripts/publish_downloads.py
      - dist/BitPaw.exe                                               -> static/downloads/BitPaw-Windows.exe
      - mobile_app/build/app/outputs/flutter-apk/app-release.apk      -> static/downloads/BitPaw.apk
    rồi:  git add -f static/downloads/BitPaw-Windows.exe static/downloads/BitPaw.apk downloads_manifest.json

Vì sao cần downloads_manifest.json: trên Vercel 2 file này do CDN phục vụ thẳng (vercel.json) và bị LOẠI khỏi gói Flask
(excludeFiles) -> Flask không thể kiểm tra "file có tồn tại" bằng ổ đĩa (lần đầu làm vậy: web thật luôn báo "đang cập nhật").
Flask đọc file kê khai nhỏ này thay thế (app.py::_published_downloads).
"""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'static', 'downloads')
SOURCES = {
    'windows': (os.path.join(ROOT, 'dist', 'BitPaw.exe'), 'BitPaw-Windows.exe'),
    'android': (os.path.join(ROOT, 'mobile_app', 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk'), 'BitPaw.apk'),
}

os.makedirs(OUT, exist_ok=True)
manifest = {}
for kind, (src, name) in SOURCES.items():
    dst = os.path.join(OUT, name)
    if os.path.exists(src):
        shutil.copyfile(src, dst)
    if not os.path.exists(dst):
        print(f'BỎ QUA {kind}: chưa có bản build ({src})')
        continue
    data = open(dst, 'rb').read()
    manifest[kind] = {'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'published': datetime.now().strftime('%Y-%m-%d')}
    print(f'OK {kind}: {name} · {len(data) / 1048576:.1f} MB · sha256 {manifest[kind]["sha256"][:16]}…')
json.dump(manifest, open(os.path.join(ROOT, 'downloads_manifest.json'), 'w', encoding='utf-8'), indent=1)
print('Đã ghi downloads_manifest.json')
