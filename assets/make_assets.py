# RockSteady Fix – (c) 2026 @jiri.fpv.zone – https://www.instagram.com/jiri.fpv.zone/
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generates icon.ico / icon.png / splash.png / ig.png (run from this folder)."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

LIME = (198, 255, 0)
CYAN = (0, 229, 255)
BG0, BG1 = (16, 21, 28), (5, 7, 10)
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, c0, c1, diagonal=True):
    w, h = size
    g = Image.new('RGB', size)
    px = g.load()
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h) if diagonal else y / h
            px[x, y] = lerp(c0, c1, t)
    return g


def neon(layer_mask, c0, c1, glow=18, size=(S, S)):
    """colour a white-on-black mask with a lime->cyan gradient plus soft glow"""
    col = gradient((64, 64), c0, c1).resize(size, Image.BILINEAR)
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    g = layer_mask.filter(ImageFilter.GaussianBlur(glow))
    out.paste(col, (0, 0), g.point(lambda v: int(v * 0.85)))
    out.paste(col, (0, 0), layer_mask)
    return out


def icon():
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    bg = gradient((S, S), BG0, BG1, diagonal=False).convert('RGBA')
    m = Image.new('L', (S, S), 0); ImageDraw.Draw(m).rounded_rectangle([24, 24, S - 24, S - 24], 220, fill=255)
    im.paste(bg, (0, 0), m)
    # thin neon rim
    rim = Image.new('L', (S, S), 0); ImageDraw.Draw(rim).rounded_rectangle([30, 30, S - 30, S - 30], 214, outline=255, width=10)
    im.alpha_composite(neon(rim, LIME, CYAN, glow=6))

    # quad, top view: X frame + 4 prop rings + body
    q = Image.new('L', (S, S), 0); d = ImageDraw.Draw(q)
    c = S / 2; r = 255  # motor distance from centre (diagonal)
    motors = [(c + sx * r / math.sqrt(2), c + sy * r / math.sqrt(2)) for sx in (-1, 1) for sy in (-1, 1)]
    for mx, my in motors:
        d.line([(c, c), (mx, my)], fill=255, width=46)
    for mx, my in motors:
        d.ellipse([mx - 150, my - 150, mx + 150, my + 150], outline=255, width=30)   # prop ring
        d.ellipse([mx - 38, my - 38, mx + 38, my + 38], fill=255)                     # motor
    d.rounded_rectangle([c - 95, c - 140, c + 95, c + 140], 50, fill=255)             # body
    # cut-out so the horizon reads clearly over the body
    cut = Image.new('L', (S, S), 0); ImageDraw.Draw(cut).rectangle([0, c - 40, S, c + 40], fill=255)
    q = ImageChops.subtract(q, cut)
    quad = neon(q, (78, 90, 108), (52, 62, 78), glow=1)   # dark steel quad
    im.alpha_composite(quad)

    # horizon: jittery on the left, rock steady on the right
    h = Image.new('L', (S, S), 0); d = ImageDraw.Draw(h)
    y = c
    zig = [(110, y), (190, y - 70), (260, y + 75), (330, y - 50), (395, y + 30), (450, y)]
    d.line(zig + [(S - 140, y)], fill=255, width=40, joint='curve')
    d.ellipse([S - 175, y - 34, S - 107, y + 34], fill=255)
    d.ellipse([90, y - 20, 130, y + 20], fill=255)
    im.alpha_composite(neon(h, LIME, CYAN, glow=22))
    return im


def ig_glyph(sz=128):
    g = gradient((sz, sz), (254, 218, 117), (150, 47, 191)).convert('RGBA')
    g2 = gradient((sz, sz), (250, 126, 30), (79, 91, 213)).convert('RGBA')
    g = Image.blend(g, g2, 0.5)
    m = Image.new('L', (sz, sz), 0); d = ImageDraw.Draw(m)
    w = sz // 11
    d.rounded_rectangle([w, w, sz - w, sz - w], sz // 4, outline=255, width=w)
    d.ellipse([sz * .3, sz * .3, sz * .7, sz * .7], outline=255, width=w)
    d.ellipse([sz * .68, sz * .2, sz * .78, sz * .3], fill=255)
    out = Image.new('RGBA', (sz, sz), (0, 0, 0, 0)); out.paste(g, (0, 0), m)
    return out


def osd_corners(d, box, col, l=26, w=3):
    x0, y0, x1, y1 = box
    for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(x, y), (x + dx * l, y)], fill=col, width=w); d.line([(x, y), (x, y + dy * l)], fill=col, width=w)


def splash(ic):
    W, H = 640, 340
    sp = gradient((W, H), (14, 18, 24), (6, 8, 11), diagonal=False).convert('RGBA')
    d = ImageDraw.Draw(sp)
    # faint grid like goggles OSD
    grid = Image.new('RGBA', (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(grid)
    for x in range(0, W, 32): gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 10))
    for y in range(0, H, 32): gd.line([(0, y), (W, y)], fill=(255, 255, 255, 10))
    sp.alpha_composite(grid); d = ImageDraw.Draw(sp)
    osd_corners(d, (16, 16, W - 17, H - 17), LIME + (255,))
    i = ic.resize((170, 170), Image.LANCZOS); sp.alpha_composite(i, (36, 72))
    fb = ImageFont.truetype('bahnschrift.ttf', 50); fb.set_variation_by_name('Bold')
    fs = ImageFont.truetype('bahnschrift.ttf', 18); fs.set_variation_by_name('SemiBold')
    fm = ImageFont.truetype('consolab.ttf', 15)
    d.text((232, 96), 'ROCKSTEADY', font=fb, fill=(236, 242, 248))
    d.text((232, 146), 'FIX', font=fb, fill=LIME)
    d.text((234, 208), 'GYROGATE KILLER · DJI O4 PRO', font=fs, fill=CYAN)
    d.text((234, 238), 'by @jiri.fpv.zone', font=fs, fill=(150, 160, 175))
    d.ellipse([34, 34, 46, 46], fill=(255, 60, 60))
    d.text((54, 31), 'REC', font=fm, fill=(236, 242, 248))
    d.text((W - 150, 31), 'LOADING…', font=fm, fill=LIME)
    return sp.convert('RGB')


if __name__ == '__main__':
    ic = icon()
    ic.save('icon.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    ic.resize((256, 256), Image.LANCZOS).save('icon.png')
    ig_glyph().save('ig.png')
    splash(ic).save('splash.png')
    # preview sheet of icon sizes
    sheet = Image.new('RGBA', (560, 280), (40, 44, 52, 255)); x = 10
    for s in (256, 128, 64, 48, 32, 16):
        sheet.alpha_composite(ic.resize((s, s), Image.LANCZOS), (x, 10)); x += s + 12
    sheet.save('_icon_sizes_preview.png')
    print('ok')
