"""Side-by-side before/after sheets, one per workflow.
Usage: python compose.py <root with before/ and after/>  (needs Pillow). Edit SHEETS."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

R = sys.argv[1]
OUT = os.path.join(R, 'sheets')
os.makedirs(OUT, exist_ok=True)
SHEETS = [
    # (sheet name, [(shot, width), ...], caption) - one sheet per workflow.
    # Payments' list, for an example: docs/design-refinement/payments/tools/compose.py
    ('01-list-phone', [('list', 390)], 'The list at 390px'),
    ('02-list-desktop', [('list', 1440)], 'The list at 1440px'),
]
try:
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 22)
    small = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 18)
except OSError:
    font = small = ImageFont.load_default()

def scaled(path, width):
    im = Image.open(path).convert('RGB')
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)))
    return im

for name, shots, caption in SHEETS:
    cols = []
    for shot, w in shots:
        target = 390 if w == 390 else 900
        b = scaled(os.path.join(R, 'before', f'{shot}-{w}.png'), target)
        a = scaled(os.path.join(R, 'after', f'{shot}-{w}.png'), target)
        cols.append((f'{shot} · {w}px', b, a))
    gap, head = 24, 90
    width = sum(b.width + a.width + gap * 2 for _, b, a in cols) + gap
    height = head + max(max(b.height, a.height) for _, b, a in cols) + 40 + gap
    sheet = Image.new('RGB', (width, height), (245, 245, 243))
    d = ImageDraw.Draw(sheet)
    import textwrap
    d.text((gap, 10), textwrap.fill(caption, max(30, width // 12)), fill=(20, 20, 20), font=small)
    x = gap
    for label, b, a in cols:
        for tag, im in (('Before', b), ('After', a)):
            d.text((x, head - 8), f'{tag} — {label}', fill=(90, 90, 90), font=small)
            sheet.paste(im, (x, head + 20))
            x += im.width + gap
        x += gap
    sheet.save(os.path.join(OUT, name + '.png'), optimize=True)
    print(name, sheet.size)
