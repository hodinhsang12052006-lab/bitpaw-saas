"""Sinh TOÀN BỘ icon/logo chữ B từ 1 ảnh gốc (B cam phát sáng trên nền tối) cho BitPaw + PawNail.

    python scripts/make_brand_icons.py <ảnh_gốc> [thư_mục_PawNail]

Ảnh gốc 1024x1024: ô chữ B nằm giữa (tâm ~516,527, cạnh ~624px); góc phải dưới có dấu ✦ của trình tạo ảnh —
cắt đúng ô nên dấu đó tự bị loại. Ra 2 bản: "dark" (vuông, nền tối — iOS/apple-touch/maskable/og tự bo góc) và
"rounded" (bo góc trong suốt — favicon, icon PWA thường, icon .exe, launcher Android).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SRC = sys.argv[1]
PAWNAIL = sys.argv[2] if len(sys.argv) > 2 else None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG = (11, 15, 23)  # đúng màu nền ảnh gốc (~#0e121a) hơi tối hơn cho viền maskable

src = Image.open(SRC).convert('RGB')
CX, CY, HALF = 516, 527, 312
dark = src.crop((CX - HALF, CY - HALF, CX + HALF, CY + HALF)).resize((1024, 1024), Image.LANCZOS)

mask = Image.new('L', (4096, 4096), 0)
m = int(4096 * 0.035)
ImageDraw.Draw(mask).rounded_rectangle((m, m, 4096 - m, 4096 - m), radius=int(4096 * 0.2), fill=255)
mask = mask.resize((1024, 1024), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1))
rounded = dark.convert('RGBA')
rounded.putalpha(mask)


def sized(img, n):
    return img.resize((n, n), Image.LANCZOS)


def maskable(n):
    """Android cắt icon maskable theo hình tròn/giọt nước — giữ ô chữ B trong vùng an toàn 80%."""
    canvas = Image.new('RGB', (n, n), BG)
    inner = int(n * 0.80)
    canvas.paste(sized(rounded, inner), ((n - inner) // 2, (n - inner) // 2), sized(rounded, inner))
    return canvas


def save(img, path, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, **kw)
    print('  +', os.path.relpath(path, ROOT) if path.startswith(ROOT) else path, img.size)


ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# ---------------- BitPaw (Flask) ----------------
st = os.path.join(ROOT, 'static')
save(dark, os.path.join(st, 'logo_b.jpg'), quality=92)                       # 22 template + /favicon.ico dùng tên này
save(rounded, os.path.join(st, 'brand', 'bitpaw-b-1024.png'))
save(dark, os.path.join(st, 'brand', 'bitpaw-b-dark-1024.png'))
save(sized(rounded, 64), os.path.join(st, 'favicon.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])  # tab chỉ cần <=64px; cỡ lớn dùng PNG
for n in (32, 192, 512):
    save(sized(rounded, n), os.path.join(st, 'brand', f'icon-{n}.png'))
save(sized(dark, 180), os.path.join(st, 'brand', 'apple-touch-icon.png'))  # iOS: ảnh đặc, iOS tự bo góc
for n in (192, 512):
    save(maskable(n), os.path.join(st, 'brand', f'icon-maskable-{n}.png'))
# app Windows (.exe)
save(sized(rounded, 256), os.path.join(ROOT, 'desktop_app', 'bitpaw.ico'), sizes=ICO_SIZES)
# app Android/iOS (mobile_app Flutter)
res = os.path.join(ROOT, 'mobile_app', 'android', 'app', 'src', 'main', 'res')
for folder, n in (('mipmap-mdpi', 48), ('mipmap-hdpi', 72), ('mipmap-xhdpi', 96), ('mipmap-xxhdpi', 144), ('mipmap-xxxhdpi', 192)):
    save(sized(rounded, n), os.path.join(res, folder, 'ic_launcher.png'))
ios = os.path.join(ROOT, 'mobile_app', 'ios', 'Runner', 'Assets.xcassets', 'AppIcon.appiconset')
for f in os.listdir(ios):
    if f.startswith('Icon-App-') and f.endswith('.png'):
        base, scale = f[len('Icon-App-'):-4].split('@')
        n = round(float(base.split('x')[0]) * int(scale[:-1]))
        save(sized(dark, n), os.path.join(ios, f))                              # iOS cấm alpha trong app icon

# ---------------- PawNail (Next.js) ----------------
if PAWNAIL:
    pub, app = os.path.join(PAWNAIL, 'public'), os.path.join(PAWNAIL, 'app')
    save(dark, os.path.join(pub, 'logo_b.jpg'), quality=92)
    save(dark, os.path.join(app, 'icon.jpg'), quality=92)                     # favicon tab "PawNail Jobs"
    save(sized(dark, 180), os.path.join(app, 'apple-icon.png'))
    save(sized(rounded, 48), os.path.join(app, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    for n in (48, 72, 96, 128, 192, 256, 512):
        save(sized(rounded, n), os.path.join(pub, 'icons', f'icon-{n}.webp'), quality=90)
    for n in (192, 512):
        save(maskable(n), os.path.join(pub, 'icons', f'icon-maskable-{n}.webp'), quality=90)
print('xong')
