"""Side-by-side before/after sheets, one per representative workflow."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

R = sys.argv[1]
OUT = os.path.join(R, 'sheets')
os.makedirs(OUT, exist_ok=True)
SHEETS = [
    ('01-desk-phone', [('list', 390)], 'The desk at 390px: totals that add up, the reason a figure is missing, what a part-paid model has left'),
    ('02-desk-desktop', [('list', 1440)], 'The desk at 1440px'),
    ('03-ready-to-send', [('detail-send', 390), ('detail-send', 1440)], "A month ready to send: the next act in one sentence; a changed destination as a real warning"),
    ('04-overpaid', [('detail-overpaid', 390)], 'Overpaid: a warning that ends in its act'),
    ('05-blocked-and-approve', [('detail-blocked-real', 1440), ('detail-confirm', 390)], "Can't be approved yet (amber, not red), and the approval question naming its amount"),
    ('06-record', [('record-partial', 390)], 'Recording a part payment: what is left, why, and the date error under its field'),
    ('07-transfer', [('receipt', 390)], 'A transfer: titled for the transfer, dated when it was sent'),
    ('08-settle-and-correct', [('reconcile-chosen', 390), ('correction', 390)], 'Settling an overpayment and a correction: one head, one vocabulary, nothing preselected'),
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
