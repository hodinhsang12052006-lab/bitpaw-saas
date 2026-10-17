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

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, '3d')
OUT = os.path.join(ROOT, 'static', 'icons', '3d')
SIZE = 256          # hiển thị tối đa 46px x 3 (màn hình retina) ~ 140px -> 256 dư nét
PADDING = 0.06      # chừa 6% mép để bóng đổ không bị cắt
# Icon có phần TRẮNG/XÁM NHẠT thật của vật thể (cán dù, cột trắng của biểu đồ, mặt tối của ngôi sao nhỏ): độ xám
# trùng với bóng đổ nên KHÔNG đổi "xám nối nền" thành bóng — chỉ xoá nền. Tạo lại ảnh khác thì xem lại danh sách này.
KEEP_LIGHT_GRAYS = {'leave', 'chart', 'spark'}

ICONS = ['checkout', 'hold', 'booking', 'checkedin', 'polish', 'history', 'discount', 'refund', 'quote', 'clear',
         'ticket', 'queue', 'all', 'acrylic', 'pedicure', 'package', 'design', 'addon', 'waxing', 'gel', 'spark',
         'dashboard', 'qr', 'customers', 'ai', 'staff', 'payroll', 'leave', 'chart', 'settings', 'exit',
         'cash', 'card', 'split', 'terminal']


def _close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def erase_corner_watermark(im):
    """Gemini đóng dấu mờ hình ngôi sao ở góc dưới phải. Nếu góc đó toàn là nền (vật thể không chạm tới),
    tô lại bằng màu nền để bước tách nền xoá sạch, không bị cắt lệch vì dấu mờ."""
    w, h = im.size
    box = int(min(w, h) * 0.12)
    bg = im.getpixel((w - 2, h - 2))
    region = im.crop((w - box, h - box, w, h))
    if all(_close(p, bg, 40) for p in region.get_flattened_data() if hasattr(region, 'get_flattened_data')) if hasattr(region, 'get_flattened_data') else all(_close(p, bg, 40) for p in region.getdata()):
        im.paste(bg, (w - box, h - box, w, h))
    return im


def remove_flat_background(im, convert_shadows=True):
    """Ảnh không có kênh trong suốt (Gemini trả nền trắng/xám trơn, có thể tối dần ở góc):
      - NỀN: điểm gần màu nền (hoặc xám sáng hơn nền) nối ra mép ảnh -> trong suốt
      - BÓNG ĐỔ: điểm xám, tối hơn nền, nối liền vùng nền -> bóng đen trong suốt mềm (trước đây thành mảng trắng
        bẩn khi đặt lên giao diện tối)
      - VẬT THỂ: phần còn lại, viền làm mềm 1px (không viền trắng). Phần trắng của vật thể (cán dù...) sáng hơn
        nền nên không bị coi là bóng."""
    if im.getextrema()[3][0] < 250:      # đã có vùng trong suốt -> giữ nguyên
        return im
    im = erase_corner_watermark(im)
    rgb = np.asarray(im)[..., :3].astype(np.float32)
    edge = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3), rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    bg = np.median(edge, axis=0)
    lum, bg_l = rgb.mean(axis=2), float(bg.mean())
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    near = (np.abs(rgb - bg).max(axis=2) <= 34) | ((sat < 14) & (lum >= bg_l - 4))

    def touching_edges(mask):
        lab, _ = ndimage.label(mask)
        ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        return np.isin(lab, list(ids))

    bgmask = touching_edges(near)
    shadow_cand = (sat < 22) & (lum < bg_l - 2) & (lum > bg_l - 120) & ~bgmask
    lab, _ = ndimage.label(shadow_cand | bgmask)
    shadow = np.isin(lab, list(set(np.unique(lab[bgmask])) - {0})) & shadow_cand
    if not convert_shadows:
        shadow = np.zeros_like(shadow)
    obj = ~(bgmask | shadow)
    obj = ndimage.binary_opening(obj, iterations=1)          # bỏ đốm lẻ
    obj_a = ndimage.gaussian_filter(ndimage.binary_erosion(obj, iterations=1).astype(np.float32), 1.0)
    sh_a = ndimage.gaussian_filter(np.clip((bg_l - lum) / bg_l * 2.4, 0, 0.5) * shadow, 1.5)
    alpha = np.maximum(obj_a, sh_a)
    out_rgb = np.where(obj[..., None], rgb, 0)              # bóng + viền ngoài: màu đen
    return Image.fromarray(np.dstack([out_rgb, alpha * 255]).clip(0, 255).astype(np.uint8), 'RGBA')


def process(path, name):
    im = Image.open(path).convert('RGBA')
    im = remove_flat_background(im, convert_shadows=name not in KEEP_LIGHT_GRAYS)
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
