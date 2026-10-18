"""So 2 bộ ảnh chụp màn hình (trước/sau 1 thay đổi CSS) theo từng điểm ảnh, xếp hạng trang khác nhiều nhất.

    python scripts/compare_screenshots.py <thư mục trước> <thư mục sau> [ngưỡng %]
Ảnh khác kích thước -> báo riêng (vd trang mobile hết bị nới 678px). Khác > ngưỡng -> in ra + lưu ảnh ghép
trước|sau vào <thư mục sau>/_diff/ để soi bằng mắt.
"""
import os
import sys

import numpy as np
from PIL import Image

before, after = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
rows = []
for root, _dirs, files in os.walk(after):
    if '_diff' in root:
        continue
    for f in files:
        if not f.endswith('.png'):
            continue
        rel = os.path.relpath(os.path.join(root, f), after)
        pb = os.path.join(before, rel)
        if not os.path.exists(pb):
            rows.append((rel, 'mới', None))
            continue
        a, b = Image.open(pb).convert('RGB'), Image.open(os.path.join(root, f)).convert('RGB')
        if a.size != b.size:
            rows.append((rel, f'kích thước {a.size} -> {b.size}', None))
            h, w = min(a.height, b.height), min(a.width, b.width)
            a, b = a.crop((0, 0, w, h)), b.crop((0, 0, w, h))
        da, db = np.asarray(a, dtype=np.int16), np.asarray(b, dtype=np.int16)
        pct = float((np.abs(da - db).max(axis=2) > 40).mean() * 100)
        rows.append((rel, f'{pct:.2f}%', pct))
        if pct > thr:
            out = os.path.join(after, '_diff')
            os.makedirs(out, exist_ok=True)
            w = a.width + b.width + 10
            canvas = Image.new('RGB', (w, max(a.height, b.height)), (255, 0, 0))
            canvas.paste(a, (0, 0))
            canvas.paste(b, (a.width + 10, 0))
            canvas.thumbnail((1800, 1800))
            canvas.save(os.path.join(out, rel.replace(os.sep, '__')))
for rel, note, pct in sorted(rows, key=lambda r: -(r[2] or 0)):
    if pct is None or pct > thr:
        print(f'{note:>28}  {rel}')
print(f"{len(rows)} ảnh so sánh, {sum(1 for r in rows if r[2] is not None and r[2] > thr)} ảnh khác > {thr}%")
