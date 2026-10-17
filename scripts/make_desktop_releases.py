"""Nhân bản dist/BitPaw.exe (desktop_app/shell.spec) thành 1 file cho mỗi ngành + SHA256SUMS.txt, để upload
lên GitHub Releases. App tự đọc ngành từ tên file (desktop_app/shell.py::detect_industry), nên tên file PHẢI
khớp DESKTOP_RELEASE_FILES trong app.py.

    python scripts/make_desktop_releases.py      -> dist/releases/BitPaw-Nails.exe, BitPaw-Spa.exe, ...
"""
import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'dist', 'BitPaw.exe')
OUT = os.path.join(ROOT, 'dist', 'releases')
NAMES = ['Nails', 'Spa', 'FnB', 'Karaoke', 'Hotel', 'Retail', 'Production', 'Technical', 'Office']


def main():
    if not os.path.exists(SRC):
        raise SystemExit('Chưa có dist/BitPaw.exe — build trước bằng desktop_app/shell.spec')
    os.makedirs(OUT, exist_ok=True)
    digest = hashlib.sha256(open(SRC, 'rb').read()).hexdigest()
    lines = []
    for n in NAMES:
        name = f'BitPaw-{n}.exe'
        shutil.copyfile(SRC, os.path.join(OUT, name))
        lines.append(f'{digest}  {name}')
        print('OK', name)
    with open(os.path.join(OUT, 'SHA256SUMS.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'{len(NAMES)} file, {os.path.getsize(SRC) // (1024 * 1024)} MB mỗi file -> {OUT}')


if __name__ == '__main__':
    main()
