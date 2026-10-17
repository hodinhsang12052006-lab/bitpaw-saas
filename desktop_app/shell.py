"""BitPaw cho Windows — app theo NGÀNH (BitPaw-Nails.exe, BitPaw-Spa.exe, ...).

Thay bản Desktop cũ (desktop_app/launcher.py chạy cả server Flask trên máy khách): bản đó cần chuỗi kết
nối MongoDB nằm ngay trên máy khách + 1 server license chưa từng tồn tại, nên file tải về không bao giờ
chạy được. App này chỉ là cửa sổ riêng (WebView2) mở thẳng hệ thống cloud BitPaw, ĐÚNG NGÀNH:
  - Ngành lấy từ TÊN FILE (BitPaw-Nails.exe -> nail) hoặc tham số --industry=nail; cùng 1 bản build,
    trang /download/<ngành>/windows trả về đúng tên file cho từng ngành.
  - Không chứa mật khẩu/khoá nào: đăng nhập bằng tài khoản BitPaw như trên web, AI chạy trên cloud.
  - Giữ đăng nhập giữa các lần mở (hồ sơ WebView riêng mỗi ngành trong %APPDATA%/BitPaw/<ngành>).
  - Mất mạng lúc mở app: hiện trang báo mất kết nối, tự thử lại.

Build: build_env/Scripts/python.exe -m PyInstaller desktop_app/shell.spec --distpath dist --workpath build/shell
Đổi tên/nhân bản theo ngành: python scripts/make_desktop_releases.py
"""
import os
import re
import sys
import urllib.request

import webview

APP_VERSION = "2.0.0"
BASE_URL = os.environ.get('BITPAW_URL', 'https://www.bitpawsoftware.com').rstrip('/')

# slug trong tên file -> (mã ngành trong hệ thống, tên hiển thị)
INDUSTRIES = {
    'nails': ('nail', 'Nails & Salon'),
    'nail': ('nail', 'Nails & Salon'),
    'spa': ('spa', 'Spa & Beauty'),
    'fnb': ('fnb', 'Restaurant & Cafe'),
    'karaoke': ('karaoke', 'Karaoke & Bida'),
    'hotel': ('hotel', 'Hotel & Homestay'),
    'retail': ('retail', 'Retail'),
    'production': ('production', 'Production'),
    'technical': ('technical', 'Technical Services'),
    'office': ('office', 'Office & HR'),
}


def detect_industry(argv=None, exe_path=None):
    """--industry=<x> thắng; không có thì đọc tên file .exe (BitPaw-Nails.exe, BitPaw_Spa (1).exe...)."""
    for arg in (argv if argv is not None else sys.argv[1:]):
        if arg.startswith('--industry='):
            slug = arg.split('=', 1)[1].strip().lower()
            if slug in INDUSTRIES:
                return INDUSTRIES[slug]
    name = os.path.basename(exe_path or sys.executable).lower()
    m = re.search(r'bitpaw[\s_-]*([a-z]+)', name)
    if m and m.group(1) in INDUSTRIES:
        return INDUSTRIES[m.group(1)]
    return None


def start_url(industry_code):
    if industry_code:
        return f"{BASE_URL}/login?industry={industry_code}&src=desktop"
    return f"{BASE_URL}/login?src=desktop"


def is_online(timeout=6):
    try:
        urllib.request.urlopen(urllib.request.Request(BASE_URL + '/login', method='HEAD'), timeout=timeout)
        return True
    except Exception:
        return False


OFFLINE_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>BitPaw</title>
<style>body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#08061a;
color:#e5e7eb;font-family:Segoe UI,Arial,sans-serif;text-align:center}.c{max-width:460px;padding:32px}
h1{color:#22d3ee;font-size:22px}p{color:#9ca3af;line-height:1.6}button{margin-top:16px;padding:12px 28px;border:0;
border-radius:12px;background:#06b6d4;color:#00121a;font-weight:700;font-size:15px;cursor:pointer}</style></head>
<body><div class="c"><h1>Không có kết nối mạng · No internet</h1>
<p>BitPaw cần Internet để mở hệ thống của tiệm. Kiểm tra Wi-Fi rồi bấm thử lại — app tự thử lại mỗi 10 giây.</p>
<p>BitPaw needs the Internet to open your business system. Check your Wi-Fi — retrying every 10 seconds.</p>
<button onclick="go()">Thử lại · Retry</button></div>
<script>const U=%URL%;function go(){fetch(U,{mode:'no-cors',cache:'no-store'}).then(()=>{location.href=U}).catch(()=>{})}
setInterval(go,10000)</script></body></html>"""


def main():
    industry = detect_industry()
    code, label = industry if industry else (None, None)
    url = start_url(code)
    title = f"BitPaw {label}" if label else "BitPaw Software"

    webview.settings['ALLOW_DOWNLOADS'] = True                    # xuất báo cáo/CSV/PDF
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True

    if is_online():
        window = webview.create_window(title, url, width=1440, height=900, min_size=(1024, 700))
    else:
        import json
        window = webview.create_window(title, html=OFFLINE_HTML.replace('%URL%', json.dumps(url)),
                                       width=1440, height=900, min_size=(1024, 700))
    storage_dir = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'BitPaw', code or 'general')
    os.makedirs(storage_dir, exist_ok=True)
    webview.start(private_mode=False, storage_path=storage_dir)
    return window


if __name__ == '__main__':
    main()
