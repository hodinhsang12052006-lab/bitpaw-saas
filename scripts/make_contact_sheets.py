"""Ghép ảnh chụp màn hình thành các tấm lưới có ghi tên trang, để soi bằng mắt nhanh mà không sót trang nào.

    python scripts/make_contact_sheets.py <thư mục ảnh> <thư mục ra>
Ảnh desktop (1440_*.png) -> lưới 3x3; ảnh mobile (390_*.png) -> lưới 6x2.
"""
import os
import sys

from PIL import Image, ImageDraw

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)


def sheet(files, cols, rows, tile, prefix):
    per = cols * rows
    for n in range(0, len(files), per):
        batch = files[n:n + per]
        tw, th = tile
        canvas = Image.new('RGB', (cols * tw, rows * (th + 22)), (30, 30, 30))
        d = ImageDraw.Draw(canvas)
        for i, f in enumerate(batch):
            im = Image.open(os.path.join(src, f)).convert('RGB')
            im = im.resize((tw, max(1, int(im.height * tw / im.width))))  # giữ tỉ lệ theo chiều ngang ô
            im = im.crop((0, 0, tw, min(th, im.height)))
            x, y = (i % cols) * tw, (i // cols) * (th + 22)
            canvas.paste(im, (x, y + 22))
            d.rectangle((x, y, x + tw, y + 21), fill=(0, 0, 0))
            d.text((x + 6, y + 5), f, fill=(255, 255, 0))
        name = f"{prefix}_{n // per + 1:02d}.png"
        canvas.save(os.path.join(out, name))
        print(name, len(batch))


files = sorted(f for f in os.listdir(src) if f.endswith('.png'))
sheet([f for f in files if f.startswith('1440_')], 3, 2, (480, 560), 'desk')
sheet([f for f in files if f.startswith('390_')], 6, 1, (240, 900), 'mob')
