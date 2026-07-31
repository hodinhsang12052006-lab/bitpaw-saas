#!/usr/bin/env python3
"""
auto_build.py — pipeline build .exe Windows 1 lệnh duy nhất cho BitPaw OS Desktop.

Chạy:  python auto_build.py

Làm đúng 5 việc, TUẦN TỰ, dừng ngay + in lỗi rõ ràng nếu bước nào thất bại (không nuốt lỗi
bằng try/except-rồi-bỏ-qua ở bất kỳ bước nào):

  1. Lọc bỏ dòng 'sqlcipher3-binary' khỏi danh sách cài đặt cho MÔI TRƯỜNG BUILD (không sửa
     requirements.txt gốc trong git — gói này hay lỗi build từ source trên Windows do thiếu
     wheel sẵn cho nhiều bản Python mới).
  2. Tự sinh icon .ico tạm (desktop_app/temp_icon.ico) nếu chưa có icon thật, thuần bằng
     module `struct` — không cần cài Pillow.
  3. Tự sinh desktop_app/build.spec khớp đúng entry point hiện có của repo.
  4. Chạy PyInstaller build ra .exe.
  5. Copy .exe vào static/downloads/BitPawOS_Setup.exe.

LƯU Ý QUAN TRỌNG: vì bước 1 bỏ qua sqlcipher3-binary, bản .exe build ra từ script này sẽ
KHÔNG có tính năng mã hoá lịch hẹn cục bộ (book_appointment sẽ báo lỗi rõ ràng cho AI thay vì
đặt lịch thật — xem ai_function_tools.py/desktop_app/secure_db.py) cho tới khi bạn cài được
sqlcipher3-binary thật trên máy build và bỏ nó ra khỏi danh sách loại trừ bên dưới.
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

# Console mặc định của cmd.exe/PowerShell trên Windows thường dùng codepage cp1252/cp850,
# không phải UTF-8 — mọi print() chứa tiếng Việt có dấu (Đ, ọ, ệ...) sẽ crash ngay bằng
# UnicodeEncodeError giữa chừng build. Ép stdout/stderr sang UTF-8 trước khi làm bất cứ điều
# gì khác, để toàn bộ log tiếng Việt của script luôn in được, không phụ thuộc codepage máy.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(ROOT, 'requirements.txt')
ICON_PATH = os.path.join(ROOT, 'desktop_app', 'icon.ico')
TEMP_ICON_PATH = os.path.join(ROOT, 'desktop_app', 'temp_icon.ico')
BUILD_SPEC_PATH = os.path.join(ROOT, 'desktop_app', 'build.spec')
DIST_DIR = os.path.join(ROOT, 'dist')
BUILD_DIR = os.path.join(ROOT, 'build')
DOWNLOADS_DIR = os.path.join(ROOT, 'static', 'downloads')
FINAL_EXE_PATH = os.path.join(DOWNLOADS_DIR, 'BitPawOS_Setup.exe')

SQLCIPHER_LINE_PATTERN = re.compile(r'^\s*sqlcipher3-binary', re.IGNORECASE)


def step(title):
    print(f"\n{'=' * 70}\n[auto_build] {title}\n{'=' * 70}")


def fail(message):
    print(f"\n[auto_build] LỖI: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 1. Lọc requirements.txt cho môi trường build (không sửa file gốc trong repo)
# ---------------------------------------------------------------------------
def build_filtered_requirements():
    step("1/5 — Lọc sqlcipher3-binary khỏi danh sách cài đặt cho bản build")
    if not os.path.exists(REQUIREMENTS_PATH):
        fail(f"Không tìm thấy {REQUIREMENTS_PATH}")

    with open(REQUIREMENTS_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    kept_lines = [ln for ln in lines if not SQLCIPHER_LINE_PATTERN.match(ln)]
    removed = len(lines) - len(kept_lines)

    if removed:
        print(f"[auto_build] Đã loại {removed} dòng sqlcipher3-binary khỏi danh sách cài đặt "
              f"cho bản build này (KHÔNG đụng tới requirements.txt thật trong git).")
        print("[auto_build] CẢNH BÁO: bản .exe này sẽ KHÔNG có tính năng mã hoá lịch hẹn cục bộ "
              "(book_appointment sẽ báo lỗi rõ ràng cho AI thay vì đặt lịch thật) cho tới khi "
              "bạn cài được sqlcipher3-binary thật trên máy build.")
    else:
        print("[auto_build] Không thấy dòng sqlcipher3-binary nào trong requirements.txt — "
              "giữ nguyên danh sách.")

    tmp_fd, tmp_path = tempfile.mkstemp(prefix='requirements_build_', suffix='.txt')
    with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
        f.writelines(kept_lines)
    return tmp_path


def pip_install(requirements_path):
    cmd = [sys.executable, '-m', 'pip', 'install', '-r', requirements_path]
    print(f"[auto_build] Chạy: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        fail("pip install thất bại — xem log phía trên để biết gói nào lỗi.")


# ---------------------------------------------------------------------------
# 2. Icon tạm — thuần bằng struct, không phụ thuộc Pillow
# ---------------------------------------------------------------------------
def ensure_icon():
    step("2/5 — Kiểm tra icon .ico")
    if os.path.exists(ICON_PATH):
        print(f"[auto_build] Đã có icon thật: {ICON_PATH}")
        return ICON_PATH

    if os.path.exists(TEMP_ICON_PATH):
        print(f"[auto_build] Đã có icon tạm từ lần build trước: {TEMP_ICON_PATH}")
        return TEMP_ICON_PATH

    print(f"[auto_build] Chưa có {ICON_PATH} — tự sinh icon tạm 32x32 màu cyan thương hiệu "
          f"để PyInstaller không báo FileNotFoundError.")
    _write_placeholder_ico(TEMP_ICON_PATH)
    print(f"[auto_build] Đã tạo {TEMP_ICON_PATH}")
    return TEMP_ICON_PATH


def _write_placeholder_ico(path, size=32, bgr_color=(212, 182, 6)):
    """Sinh 1 file .ico hợp lệ (1 frame, 24bpp, không nén) hoàn toàn bằng struct.pack —
    không cần Pillow. size=32 để mỗi dòng ảnh (width*3 byte) đã là bội số của 4, khỏi phải
    xử lý padding từng dòng theo chuẩn BMP."""
    width = height = size
    xor_data = bytes(bgr_color) * width * height
    and_row = b'\x00' * ((width + 31) // 32 * 4)
    and_data = and_row * height

    bmp_header = struct.pack(
        '<IiiHHIIiiII',
        40,                                 # biSize
        width,                              # biWidth
        height * 2,                         # biHeight (x2: XOR + AND mask theo chuẩn ICO)
        1,                                  # biPlanes
        24,                                 # biBitCount
        0,                                  # biCompression
        len(xor_data) + len(and_data),      # biSizeImage
        0, 0,                               # biXPelsPerMeter, biYPelsPerMeter
        0, 0,                               # biClrUsed, biClrImportant
    )
    image_data = bmp_header + xor_data + and_data

    icon_dir = struct.pack('<HHH', 0, 1, 1)  # reserved, type=1(icon), count=1
    icon_entry = struct.pack(
        '<BBBBHHII',
        width if width < 256 else 0,
        height if height < 256 else 0,
        0, 0,                               # colorCount, reserved
        1,                                  # planes
        24,                                 # bitCount
        len(image_data),                    # bytesInRes
        6 + 16,                             # imageOffset: ICONDIR(6) + 1 ICONDIRENTRY(16)
    )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(icon_dir + icon_entry + image_data)


# ---------------------------------------------------------------------------
# 3. Sinh desktop_app/build.spec
# ---------------------------------------------------------------------------
def resolve_entry_point():
    launcher_rel = os.path.join('desktop_app', 'launcher.py')
    if os.path.exists(os.path.join(ROOT, launcher_rel)):
        return launcher_rel.replace(os.sep, '/')

    print(
        "[auto_build] CẢNH BÁO: không tìm thấy desktop_app/launcher.py — dùng tạm app.py làm "
        "entry point. Bản .exe này sẽ CHỈ chạy Flask dev server thô (app.run()), KHÔNG mở cửa "
        "sổ desktop nào (thiếu lớp webview/license/updater của launcher.py). Đây là bản build "
        "suy giảm — khôi phục desktop_app/launcher.py trước khi phát hành cho khách hàng.",
        file=sys.stderr,
    )
    return 'app.py'


def write_build_spec(entry_point, icon_path):
    step("3/5 — Sinh desktop_app/build.spec")
    icon_rel = os.path.relpath(icon_path, ROOT).replace(os.sep, '/')

    spec_source = f"""# File này được auto_build.py TỰ SINH mỗi lần chạy — sửa tay sẽ bị ghi đè ở lần chạy kế
# tiếp. Muốn đổi vĩnh viễn, sửa hàm write_build_spec() trong auto_build.py.
block_cipher = None

a = Analysis(
    [{entry_point!r}],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('translations', 'translations'),
        # KHÔNG đóng gói '.env' — tránh lộ API key dùng chung mọi tenant vào file .exe.
    ],
    hiddenimports=[
        'ai_context_engine', 'ai_sales_prompts', 'ai_memory_engine', 'ai_vector_rag',
        'ai_nurturing_engine', 'email_service', 'tenant_engine', 'currency_utils',
        'payment_us_engine', 'auth_service', 'i18n', 'blueprints.spa_bp',
        'ai_function_tools', 'ai_deepseek_client',
        'desktop_app.secure_db', 'desktop_app.license_manager',
        'desktop_app.updater', 'desktop_app.realtime_client',
        'pymongo', 'bson', 'gridfs',
        'montydb', 'montydb.storage', 'montydb.storage.sqlite', 'montydb.types',
        'sqlalchemy', 'sqlalchemy.dialects.sqlite',
        # sqlcipher3 CỐ Ý không có ở đây — auto_build.py loại gói này khỏi bước cài đặt (hay
        # lỗi build từ source trên Windows). desktop_app/secure_db.py tự báo lỗi rõ ràng lúc
        # chạy nếu thiếu, không làm sập cả app (xem ai_function_tools.py: book_appointment()).
        'keyring.backends.Windows', 'keyring.backends.fail',
        'socketio', 'engineio', 'engineio.async_drivers.threading',
        'webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr_loader', 'clr',
        'flask_limiter', 'flask_limiter.util',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BitPawOS',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon={icon_rel!r},
)
"""
    os.makedirs(os.path.dirname(BUILD_SPEC_PATH), exist_ok=True)
    with open(BUILD_SPEC_PATH, 'w', encoding='utf-8') as f:
        f.write(spec_source)
    print(f"[auto_build] Đã ghi {BUILD_SPEC_PATH} (entry point: {entry_point})")


# ---------------------------------------------------------------------------
# 4. Chạy PyInstaller
# ---------------------------------------------------------------------------
def run_pyinstaller():
    step("4/5 — Chạy PyInstaller")
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    spec_rel = os.path.relpath(BUILD_SPEC_PATH, ROOT).replace(os.sep, '/')
    cmd = [
        sys.executable, '-m', 'PyInstaller', spec_rel,
        '--distpath', 'dist', '--workpath', 'build', '--noconfirm',
    ]
    print(f"[auto_build] Chạy: {' '.join(cmd)}  (cwd={ROOT})")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        fail("PyInstaller build thất bại — xem log phía trên.")


# ---------------------------------------------------------------------------
# 5. Copy .exe vào static/downloads/
# ---------------------------------------------------------------------------
def copy_exe_to_downloads():
    step("5/5 — Copy .exe vào static/downloads/")
    built_exe = os.path.join(DIST_DIR, 'BitPawOS.exe')
    if not os.path.exists(built_exe):
        fail(f"Không tìm thấy file build ra tại {built_exe} — kiểm tra log PyInstaller phía trên.")

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    shutil.copy2(built_exe, FINAL_EXE_PATH)
    print(f"[auto_build] Đã copy -> {FINAL_EXE_PATH}")


def main():
    if sys.platform != 'win32':
        print(
            f"[auto_build] CẢNH BÁO: đang chạy trên '{sys.platform}', không phải Windows. "
            "PyInstaller không cross-compile — file build ra chỉ chạy được trên hệ điều hành "
            "hiện tại của bạn, KHÔNG phải .exe Windows dùng được cho khách hàng Windows.",
            file=sys.stderr,
        )

    filtered_requirements = build_filtered_requirements()
    try:
        pip_install(filtered_requirements)
    finally:
        os.remove(filtered_requirements)

    icon_path = ensure_icon()
    entry_point = resolve_entry_point()
    write_build_spec(entry_point, icon_path)
    run_pyinstaller()
    copy_exe_to_downloads()

    print(f"\n[auto_build] XONG. File cài đặt sẵn sàng tại:\n  {FINAL_EXE_PATH}")
    print(f"[auto_build] Chạy thử trước khi git push:\n  {os.path.join(DIST_DIR, 'BitPawOS.exe')}")


if __name__ == '__main__':
    main()
