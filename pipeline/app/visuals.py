"""Slide rendering with Pillow: title cards, progressive bullets, highlighted code, end cards, thumbnails.
Everything is drawn from text, so it runs fast on CPU and every video looks specific to its topic."""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.styles import get_style_by_name

from . import config as C

BG_TOP, BG_BOT = (10, 14, 28), (18, 26, 52)
TEXT, MUTED = (238, 242, 250), (150, 162, 190)
ACCENT = {"linux": (245, 197, 24), "aws": (255, 153, 0), "azure": (47, 140, 255),
          "gcp": (52, 168, 83), "devops": (169, 112, 255)}
CODE_BG = (24, 26, 33)
DAY_BADGE = None          # e.g. "DAY 12 / 100" - set by the render stage for challenge videos
_STYLE = get_style_by_name("monokai")


@lru_cache(maxsize=64)
def font(kind, size):
    path = {"bold": C.FONT_BOLD, "sans": C.FONT_SANS, "mono": C.FONT_MONO}[kind]
    return ImageFont.truetype(path, size)


def accent(cat):
    return ACCENT.get(cat, (120, 200, 255))


@lru_cache(maxsize=8)
def _background(w, h, cat):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3)))
    # faint dot grid
    step = 48
    for y in range(step, h, step):
        for x in range(step, w, step):
            d.point((x, y), fill=(40, 50, 80))
    # soft accent glow, top-right
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(min(w, h) * 0.55)
    gd.ellipse([w - r, -r // 2, w + r // 2, r], fill=tuple(int(c * 0.35) for c in accent(cat)))
    glow = glow.filter(ImageFilter.GaussianBlur(r // 3))
    return Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.5)


def wrap(draw, text, fnt, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, kind, max_w, max_lines, start, minimum=28):
    size = start
    while size > minimum:
        f = font(kind, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
        size -= 4
    f = font(kind, minimum)
    return f, wrap(draw, text, f, max_w)[:max_lines]


class Canvas:
    def __init__(self, w, h, cat):
        self.w, self.h, self.cat = w, h, cat
        self.portrait = h > w
        self.m = int(w * (0.08 if self.portrait else 0.07))
        self.img = _background(w, h, cat).copy()
        self.d = ImageDraw.Draw(self.img)

    def chrome(self, counter=None):
        a = accent(self.cat)
        label = C.CATEGORY_LABEL.get(self.cat, self.cat.upper())
        f = font("bold", 40 if self.portrait else 30)
        bh = 66 if self.portrait else 54
        top = int(self.h * (0.06 if self.portrait else 0.065))
        tw = self.d.textlength(label, font=f)
        self.d.rounded_rectangle([self.m, top, self.m + tw + 48, top + bh], radius=bh // 2, fill=a)
        self.d.text((self.m + 24, top + (bh - f.size) // 2 - 2), label, font=f, fill=(15, 15, 20))
        if DAY_BADGE:
            x0 = self.m + tw + 48 + 16
            dw = self.d.textlength(DAY_BADGE, font=f)
            self.d.rounded_rectangle([x0, top, x0 + dw + 48, top + bh], radius=bh // 2, outline=a, width=3)
            self.d.text((x0 + 24, top + (bh - f.size) // 2 - 2), DAY_BADGE, font=f, fill=TEXT)
        if not self.portrait:
            fc = font("sans", 26)
            name = C.CHANNEL_NAME
            self.d.text((self.w - self.m - self.d.textlength(name, font=fc), top + 13), name, font=fc, fill=MUTED)
        if counter:
            fc = font("bold", 26)
            txt = f"{counter[0]:02d} / {counter[1]:02d}"
            y = self.h - int(self.h * 0.07)
            self.d.text((self.m, y), txt, font=fc, fill=MUTED)
            bx, bw = self.m + 130, self.w - 2 * self.m - 130
            self.d.rounded_rectangle([bx, y + 12, bx + bw, y + 18], radius=3, fill=(45, 55, 85))
            self.d.rounded_rectangle([bx, y + 12, bx + int(bw * counter[0] / counter[1]), y + 18], radius=3, fill=a)
        return top + bh

    def area(self, top):
        """Vertical band available for content (portrait keeps the lower part free for captions)."""
        bottom = int(self.h * (0.58 if self.portrait else 0.88))
        return top + int(self.h * 0.05), bottom

    def save(self, path):
        self.img.save(path, quality=92)
        return path


def title_card(path, w, h, cat, heading, kicker=None, counter=None):
    c = Canvas(w, h, cat)
    c.chrome(counter)
    a = accent(cat)
    maxw = w - 2 * c.m
    f, lines = fit(c.d, heading, "bold", maxw, 4 if c.portrait else 3, 104 if c.portrait else 96)
    lh = int(f.size * 1.18)
    block = lh * len(lines)
    y = int(h * (0.30 if c.portrait else 0.5)) - block // 2
    if kicker:
        fk = font("bold", 34)
        c.d.text((c.m, y - 70), kicker.upper(), font=fk, fill=a)
    for ln in lines:
        c.d.text((c.m, y), ln, font=f, fill=TEXT)
        y += lh
    c.d.rectangle([c.m, y + 24, c.m + 160, y + 34], fill=a)
    return c.save(path)


def bullets_card(path, w, h, cat, heading, bullets, shown, counter=None):
    c = Canvas(w, h, cat)
    a0, a1 = c.area(c.chrome(counter))
    a = accent(cat)
    maxw = w - 2 * c.m
    gap = int(h * 0.045)
    hs, bs = (84, 66) if c.portrait else (76, 58)
    while True:  # shrink until heading + all bullets fit the content band
        fh, hl = fit(c.d, heading, "bold", maxw, 3 if c.portrait else 2, hs)
        fb = font("sans", bs)
        blines = [wrap(c.d, b, fb, maxw - 70) for b in bullets]
        head_h = int(fh.size * 1.2) * len(hl)
        body_h = sum(int(fb.size * 1.25) * len(bl) + int(fb.size * 0.6) for bl in blines)
        if head_h + gap + body_h <= a1 - a0 or bs <= 36:
            break
        hs, bs = hs - 6, bs - 4
    y = a0 + max(0, (a1 - a0 - head_h - gap - body_h) // 2)
    c.d.rectangle([c.m, y - 28, c.m + 90, y - 20], fill=a)
    for ln in hl:
        c.d.text((c.m, y), ln, font=fh, fill=TEXT)
        y += int(fh.size * 1.2)
    y += gap
    for i, bl in enumerate(blines):
        on = i < shown
        if not on and not c.portrait:
            continue  # landscape: reveal one by one; portrait: show upcoming points dimmed
        r = 14
        cy = y + fb.size // 2 + 4
        c.d.ellipse([c.m, cy - r, c.m + 2 * r, cy + r], fill=a if on else (70, 80, 110))
        for ln in bl:
            c.d.text((c.m + 60, y), ln, font=fb, fill=TEXT if on else (80, 90, 120))
            y += int(fb.size * 1.25)
        y += int(fb.size * 0.6)
    return c.save(path)


def _token_color(tok):
    while tok is not None:
        st = _STYLE.style_for_token(tok)
        if st.get("color"):
            return "#" + st["color"]
        tok = tok.parent
    return "#f8f8f2"


def code_card(path, w, h, cat, heading, lang, code, counter=None):
    c = Canvas(w, h, cat)
    a0, a1 = c.area(c.chrome(counter))
    maxw = w - 2 * c.m
    fh, hl = fit(c.d, heading, "bold", maxw, 2 if c.portrait else 1, 72 if c.portrait else 64, minimum=30)
    lines = (code or "").rstrip("\n").split("\n")[:14]
    longest = max((len(l) for l in lines), default=10)
    head_h = int(fh.size * 1.25) * len(hl) + int(h * 0.03)
    avail = a1 - a0 - head_h - 110
    size = int(min(52 if c.portrait else 48, (maxw - 80) / max(longest, 16) / 0.6, avail / max(len(lines), 1) / 1.45))
    size = max(size, 18)
    fm = font("mono", size)
    lh = int(size * 1.45)
    bh = 76 + lh * len(lines) + 34
    y = a0 + max(0, (a1 - a0 - head_h - bh) // 2)
    for ln in hl:
        c.d.text((c.m, y), ln, font=fh, fill=TEXT)
        y += int(fh.size * 1.25)
    y += int(h * 0.03)
    c.d.rounded_rectangle([c.m, y, c.m + maxw, y + bh], radius=18, fill=CODE_BG, outline=(55, 60, 75), width=2)
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        c.d.ellipse([c.m + 26 + i * 34, y + 24, c.m + 46 + i * 34, y + 44], fill=col)
    fl = font("sans", 26)
    c.d.text((c.m + maxw - 30 - c.d.textlength(lang, font=fl), y + 20), lang, font=fl, fill=MUTED)
    try:
        lexer = get_lexer_by_name({"terraform": "hcl", "shell": "bash", "sh": "bash"}.get(lang.lower(), lang.lower()))
    except Exception:
        lexer = TextLexer()
    cx, cy = c.m + 40, y + 76
    x = cx
    for tok, val in lex("\n".join(lines), lexer):
        for k, part in enumerate(val.split("\n")):
            if k:
                cy += lh
                x = cx
            if part:
                c.d.text((x, cy), part, font=fm, fill=_token_color(tok))
                x += c.d.textlength(part, font=fm)
    return c.save(path)


def end_card(path, w, h, cat, line1, line2):
    c = Canvas(w, h, cat)
    c.chrome()
    a = accent(cat)
    maxw = w - 2 * c.m
    f1, l1 = fit(c.d, line1, "bold", maxw, 3, 92)
    y = int(h * (0.28 if c.portrait else 0.38))
    for ln in l1:
        c.d.text((c.m, y), ln, font=f1, fill=TEXT)
        y += int(f1.size * 1.2)
    f2 = font("bold", 48)
    y += 30
    tw = c.d.textlength(line2, font=f2)
    c.d.rounded_rectangle([c.m, y, c.m + tw + 60, y + 86], radius=43, fill=a)
    c.d.text((c.m + 30, y + 16), line2, font=f2, fill=(15, 15, 20))
    return c.save(path)


def lower_third_overlay(path, w, h, cat, heading, counter=None):
    """Transparent overlay for stock b-roll segments."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(w * 0.07)
    a = accent(cat)
    f, lines = fit(d, heading, "bold", w - 2 * m - 40, 2, 72)
    bh = int(f.size * 1.25) * len(lines) + 60
    y0 = h - bh - int(h * 0.12)
    d.rounded_rectangle([m, y0, w - m, y0 + bh], radius=20, fill=(10, 14, 28, 215))
    d.rectangle([m, y0, m + 12, y0 + bh], fill=a + (255,))
    y = y0 + 30
    for ln in lines:
        d.text((m + 40, y), ln, font=f, fill=TEXT + (255,))
        y += int(f.size * 1.25)
    img.save(path)
    return path


def thumbnail(path, cat, text, w=1280, h=720, day=None, total=None):
    c = Canvas(w, h, cat)
    a = accent(cat)
    c.m = 70
    label = C.CATEGORY_LABEL.get(cat, cat.upper())
    fb = font("bold", 44)
    tw = c.d.textlength(label, font=fb)
    c.d.rounded_rectangle([c.m, 60, c.m + tw + 56, 130], radius=35, fill=a)
    c.d.text((c.m + 28, 72), label, font=fb, fill=(15, 15, 20))
    words = (text or "").upper()
    f, lines = fit(c.d, words, "bold", int(w * 0.62), 3, 128, minimum=60)
    lh = int(f.size * 1.08)
    y = (h - lh * len(lines)) // 2 + 40
    for i, ln in enumerate(lines):
        c.d.text((c.m + 5, y + 5), ln, font=f, fill=(0, 0, 0))
        c.d.text((c.m, y), ln, font=f, fill=a if i == len(lines) - 1 else TEXT)
        y += lh
    if day:
        # big "DAY 12" block with a progress bar
        gx, gy, gw, gh = int(w * 0.69), 170, int(w * 0.26), 400
        c.d.rounded_rectangle([gx, gy, gx + gw, gy + gh], radius=28, fill=a)
        fd, fn = font("bold", 64), font("bold", 190 if day < 100 else 150)
        c.d.text((gx + (gw - c.d.textlength("DAY", font=fd)) // 2, gy + 30), "DAY", font=fd, fill=(15, 15, 20))
        num = str(day)
        c.d.text((gx + (gw - c.d.textlength(num, font=fn)) // 2, gy + 95), num, font=fn, fill=(15, 15, 20))
        px, pw = gx + 30, gw - 60
        c.d.rounded_rectangle([px, gy + gh - 60, px + pw, gy + gh - 40], radius=10, fill=(15, 15, 20))
        c.d.rounded_rectangle([px, gy + gh - 60, px + max(20, int(pw * day / total)), gy + gh - 40], radius=10, fill=TEXT)
        fs = font("bold", 30)
        lbl = f"OF {total}"
        c.d.text((gx + (gw - c.d.textlength(lbl, font=fs)) // 2, gy + gh + 18), lbl, font=fs, fill=TEXT)
        c.img.save(path, quality=92)
        return path
    # terminal glyph on the right
    gx, gy, gw, gh = int(w * 0.70), 190, int(w * 0.24), 340
    c.d.rounded_rectangle([gx, gy, gx + gw, gy + gh], radius=26, fill=CODE_BG, outline=a, width=6)
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        c.d.ellipse([gx + 24 + i * 36, gy + 22, gx + 46 + i * 36, gy + 44], fill=col)
    c.d.text((gx + 36, gy + 110), ">_", font=font("mono", 150), fill=a)
    c.img.save(path, quality=92)
    return path
