"""Chuẩn bị icon 3D cho ngành Nails (ảnh tạo bằng Gemini / công cụ AI khác).

1. Bỏ ảnh gốc vào thư mục  3d/  ở thư mục gốc dự án, đặt TÊN FILE = tên icon (vd 3d/checkout.png, 3d/pedicure.jpg).
   Danh sách 35 tên icon: xem ICONS bên dưới hoặc static/icons/3d/README.md.
2. Chạy:  python scripts/prepare_3d_icons.py
   -> tách nền (nếu ảnh không trong suốt), cắt sát, căn giữa khung vuông, thu về 256x256,
      lưu static/icons/3d/<tên>.webp (nhẹ ~15-30 KB) — phần mềm tự dùng ảnh 3D thay icon cũ.
3. Khởi động lại server (local) hoặc deploy để thấy icon mới.

Thư mục 3d/ (ảnh gốc nặng) không đưa lên git / Vercel.
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, '3d')
OUT = os.path.join(ROOT, 'static', 'icons', '3d')
SIZE = 256          # hiển thị tối đa 46px x 3 (màn hình retina) ~ 140px -> 256 dư nét
PADDING = 0.06      # chừa 6% mép để bóng đổ không bị cắt

ICONS = ['checkout', 'hold', 'booking', 'checkedin', 'polish', 'history', 'discount', 'refund', 'quote', 'clear',
         'ticket', 'queue', 'all', 'acrylic', 'pedicure', 'package', 'design', 'addon', 'waxing', 'gel', 'spark',
         'dashboard', 'qr', 'customers', 'ai', 'staff', 'payroll', 'leave', 'chart', 'settings', 'exit',
         'cash', 'card', 'split', 'terminal']


def remove_flat_background(im):
    """Ảnh không có kênh trong suốt (Gemini thường trả nền trắng / xám trơn): xoá vùng nền nối với 4 góc."""
    if im.getextrema()[3][0] < 250:      # đã có vùng trong suốt -> giữ nguyên
        return im
    w, h = im.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if im.getpixel(corner)[3] != 0:
            ImageDraw.floodfill(im, corner, (0, 0, 0, 0), thresh=38)
    return im


def process(path, name):
    im = Image.open(path).convert('RGBA')
    im = remove_flat_background(im)
    alpha = im.getchannel('A').point(lambda a: 255 if a > 10 else 0)
    box = alpha.getbbox()
    if not box:
        raise ValueError('ảnh trống sau khi tách nền')
    im = im.crop(box)
    side = int(max(im.size) * (1 + 2 * PADDING))
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    canvas = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    out = os.path.join(OUT, f'{name}.webp')
    canvas.save(out, 'WEBP', quality=90, method=6)
    return os.path.getsize(out)


def main():
    os.makedirs(SRC, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    done, unknown = [], []
    for f in sorted(os.listdir(SRC)):
        name, ext = os.path.splitext(f)
        if ext.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            continue
        name = name.strip().lower()
        if name not in ICONS:
            unknown.append(f)
            continue
        try:
            size = process(os.path.join(SRC, f), name)
            done.append(name)
            print(f'OK   {f:28} -> static/icons/3d/{name}.webp ({size // 1024} KB)')
        except Exception as e:
            print(f'LỖI {f}: {e}')
    missing = [i for i in ICONS if i not in done and not os.path.exists(os.path.join(OUT, f'{i}.webp'))]
    print(f'\nĐã xử lý {len(done)} ảnh.')
    if unknown:
        print('Tên file không khớp icon nào (đổi tên đúng danh sách):', ', '.join(unknown))
    if missing:
        print(f'Còn thiếu {len(missing)} icon (đang dùng icon cũ):', ', '.join(missing))
    sys.exit(0)


if __name__ == '__main__':
    main()
