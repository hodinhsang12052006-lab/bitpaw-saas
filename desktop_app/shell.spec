# App Windows theo ngành (desktop_app/shell.py) — chỉ là cửa sổ WebView2 mở hệ thống cloud, KHÔNG đóng gói
# templates/app.py/.env. Build (chạy từ thư mục gốc dự án):
#   build_env/Scripts/python.exe -m PyInstaller desktop_app/shell.spec --distpath dist --workpath build/shell --noconfirm
# rồi: python scripts/make_desktop_releases.py  (nhân bản thành BitPaw-Nails.exe, BitPaw-Spa.exe, ...)
a = Analysis(
    ['shell.py'],
    pathex=['..'],
    hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr_loader', 'clr'],
    excludes=['tkinter', 'numpy', 'pandas', 'PIL', 'matplotlib', 'pymongo', 'flask'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='BitPaw',
    console=False,
    icon='bitpaw.ico',
    upx=False,
)
