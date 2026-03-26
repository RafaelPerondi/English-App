"""
Serviço de geração de imagens de feedback — Pillow.
Layout clean pastel Apple-vibe. Peach warm palette.
Vertical mobile 1080x1920+. Score X/100.
Sem tips/regras na imagem (vão como texto no WhatsApp).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import AUDIO_CACHE_DIR, FONTS_DIR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Cores — Peach warm + roxo vivo
# ─────────────────────────────────────────────

BG_TOP = (245, 225, 215)
BG_MID = (250, 236, 228)
BG_BOT = (252, 246, 242)
CARD_BG = (255, 255, 255)
CARD_SHADOW = (215, 213, 225)
TEXT_DARK = (28, 28, 35)
TEXT_MED = (80, 80, 95)
ACCENT_PURPLE = (100, 45, 210)
ACCENT_GREEN = (45, 155, 60)
HIGHLIGHT_GREEN = (210, 242, 200)
HIGHLIGHT_YELLOW = (255, 244, 195)
BADGE_BG = (232, 222, 255)
BADGE_TXT = (100, 45, 210)
WHITE = (255, 255, 255)
DIVIDER = (235, 233, 242)
HOME_BAR = (200, 198, 210)

W = 1080
PAD = 64
CARD_PAD = 52
CARD_R = 36
LINE_SP = 18
MIN_H = 1920
HL_PAD_X = 10
HL_PAD_Y = 6


# ─────────────────────────────────────────────
# Fontes
# ─────────────────────────────────────────────

def _f(size, bold=False):
    names = (
        ["arialbd.ttf", "segoeuib.ttf", "calibrib.ttf"]
        if bold
        else ["arial.ttf", "segoeui.ttf", "calibri.ttf"]
    )
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    for n in names:
        p = FONTS_DIR / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    try:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _wrap(text, font, mw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if font.getbbox(t)[2] <= mw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _lh(font):
    return font.getbbox("Ay")[3] - font.getbbox("Ay")[1] + LINE_SP


def _th(text, font, mw):
    return _lh(font) * len(_wrap(text, font, mw))


def _tw(text, font):
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def _text_h(font):
    bb = font.getbbox("Ay")
    return bb[3] - bb[1]


def _gradient_bg(img, ht, total):
    d = ImageDraw.Draw(img)
    for y in range(total):
        if y < ht:
            t = y / max(ht - 1, 1)
            r = int(BG_TOP[0] + (BG_MID[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_MID[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_MID[2] - BG_TOP[2]) * t)
        else:
            t = min((y - ht) / max(total - ht - 1, 1), 1.0)
            r = int(BG_MID[0] + (BG_BOT[0] - BG_MID[0]) * t)
            g = int(BG_MID[1] + (BG_BOT[1] - BG_MID[1]) * t)
            b = int(BG_MID[2] + (BG_BOT[2] - BG_MID[2]) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))


def _card_shadow(draw, x0, y0, x1, y1):
    for i in range(3, 0, -1):
        o = i * 3
        draw.rounded_rectangle(
            (x0 + o, y0 + o, x1 + o, y1 + o),
            radius=CARD_R, fill=CARD_SHADOW,
        )


def _draw_badge(draw, x, y, text, font, bg, fg):
    """Desenha badge pill. Retorna (largura, altura)."""
    tw = _tw(text, font)
    th = _text_h(font)
    pw, ph = tw + 44, th + 22
    draw.rounded_rectangle(
        (x, y, x + pw, y + ph),
        radius=ph // 2, fill=bg,
    )
    draw.text(
        (x + 22, y + (ph - th) // 2),
        text, font=font, fill=fg,
    )
    return pw, ph


def _draw_card_header(draw, card_x, row_y, title, title_font, badge_text, badge_font):
    """Desenha título + badge alinhados verticalmente. Retorna y após o divider."""
    title_th = _text_h(title_font)
    badge_tw = _tw(badge_text, badge_font)
    badge_th = _text_h(badge_font)
    badge_pw, badge_ph = badge_tw + 44, badge_th + 22

    row_h = max(title_th, badge_ph)
    title_y = row_y + (row_h - title_th) // 2
    badge_y = row_y + (row_h - badge_ph) // 2

    draw.text((card_x + CARD_PAD, title_y), title, font=title_font, fill=TEXT_DARK)

    badge_x = W - card_x - CARD_PAD - badge_pw
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_pw, badge_y + badge_ph),
        radius=badge_ph // 2, fill=BADGE_BG,
    )
    draw.text(
        (badge_x + 22, badge_y + (badge_ph - badge_th) // 2),
        badge_text, font=badge_font, fill=BADGE_TXT,
    )

    # Divider
    div_y = row_y + row_h + 16
    draw.line(
        [(card_x + CARD_PAD, div_y), (W - card_x - CARD_PAD, div_y)],
        fill=DIVIDER, width=2,
    )
    return div_y + 24


def _draw_highlighted_words(draw, cx, cy, words, highlight_set, font, font_bold,
                            hl_color, text_color, max_x, lh, sp, body_h):
    """Desenha palavras com highlights alinhados. Retorna cy final."""
    for word in words:
        wc = word.lower().strip(".,!?;:\"'")
        ww = _tw(word, font)

        if wc in highlight_set:
            hw = ww + HL_PAD_X * 2
            total = hw + 4
            if cx + total > max_x:
                cx = PAD + CARD_PAD
                cy += lh
            draw.rounded_rectangle(
                (cx - 2, cy - HL_PAD_Y, cx + hw + 2, cy + body_h + HL_PAD_Y),
                radius=10, fill=hl_color,
            )
            draw.text((cx + HL_PAD_X, cy), word, font=font_bold, fill=text_color)
            cx += hw + sp + 2
        else:
            if cx + ww > max_x:
                cx = PAD + CARD_PAD
                cy += lh
            draw.text((cx, cy), word, font=font, fill=TEXT_DARK)
            cx += ww + sp

    return cy


# ─────────────────────────────────────────────
# Geração principal
# ─────────────────────────────────────────────

def generate_feedback_image(correction_data: dict, filename: str) -> Path:

    f_tag = _f(26, True)
    f_title = _f(60, True)
    f_score = _f(90, True)
    f_section = _f(44, True)
    f_badge = _f(28, True)
    f_body = _f(36)
    f_body_b = _f(36, True)
    f_enc = _f(36, True)

    cw = W - PAD * 2
    ci = cw - CARD_PAD * 2

    HH = 360

    original = correction_data.get("original", "...")
    corrected = correction_data.get("corrected", "...")
    errors = correction_data.get("errors", [])[:5]
    encouragement = correction_data.get("encouragement", "")
    err_count = len(errors)

    # Score
    total_words = len(original.split()) if original else 10
    score = max(0, min(100, int(100 - (err_count / max(total_words, 1)) * 100)))

    # Mapas
    error_words = {
        e["wrong"].lower(): e.get("right", "")
        for e in errors if e.get("wrong")
    }
    right_set = {
        e["right"].lower().strip(".,"): True
        for e in errors if e.get("right")
    }

    sol_word = "soluções" if err_count != 1 else "solução"

    lh = _lh(f_body)
    sp = _tw(" ", f_body)
    body_h = _text_h(f_body)

    # ── Calcular altura ──
    c1_body = _th(original, f_body, ci - 20) + len(errors) * 18 + 30
    c1h = 80 + c1_body + CARD_PAD

    c2_body = _th(corrected, f_body, ci - 20) + len(errors) * 18 + 30
    c2h = 80 + c2_body + CARD_PAD

    content_h = HH + 30 + c1h + 36 + c2h + 44 + 80 + PAD + 50
    img_h = max(content_h, MIN_H)

    # ── Criar imagem ──
    img = Image.new("RGB", (W, img_h), BG_BOT)
    _gradient_bg(img, HH, img_h)
    draw = ImageDraw.Draw(img)

    y = PAD + 20

    # ── Tag "Feedback" ──
    tag = "Feedback"
    ttw = _tw(tag, f_tag)
    tw2, th2 = ttw + 52, 50
    draw.rounded_rectangle(
        (PAD, y, PAD + tw2, y + th2),
        radius=th2 // 2, fill=WHITE,
    )
    draw.ellipse((PAD + 16, y + 15, PAD + 31, y + 30), fill=ACCENT_PURPLE)
    draw.text((PAD + 40, y + 11), tag, font=f_tag, fill=TEXT_MED)
    y += th2 + 40

    # ── Score ──
    draw.text((PAD, y), "Score", font=f_title, fill=TEXT_DARK)
    y += 72
    score_text = str(score)
    draw.text((PAD, y), score_text, font=f_score, fill=ACCENT_PURPLE)
    sw = _tw(score_text, f_score)
    draw.text((PAD + sw + 8, y + 30), "/100", font=f_title, fill=TEXT_DARK)

    # ── Cards ──
    y = HH + 30

    # Card 1: Pronúncia
    _card_shadow(draw, PAD - 2, y, W - PAD + 2, y + c1h)
    draw.rounded_rectangle(
        (PAD - 2, y, W - PAD + 2, y + c1h),
        radius=CARD_R, fill=CARD_BG,
    )

    cy = _draw_card_header(
        draw, PAD, y + CARD_PAD,
        "Pronúncia", f_section,
        f"{err_count} {sol_word}", f_badge,
    )

    max_x = PAD + ci
    cx = PAD + CARD_PAD
    cy = _draw_highlighted_words(
        draw, cx, cy,
        original.split(), error_words,
        f_body, f_body_b,
        HIGHLIGHT_YELLOW, TEXT_DARK,
        max_x, lh, sp, body_h,
    )

    y += c1h + 36

    # Card 2: Como melhorar
    _card_shadow(draw, PAD - 2, y, W - PAD + 2, y + c2h)
    draw.rounded_rectangle(
        (PAD - 2, y, W - PAD + 2, y + c2h),
        radius=CARD_R, fill=CARD_BG,
    )

    cy = _draw_card_header(
        draw, PAD, y + CARD_PAD,
        "Como melhorar", f_section,
        "corrigido", f_badge,
    )

    cx = PAD + CARD_PAD
    cy = _draw_highlighted_words(
        draw, cx, cy,
        corrected.split(), right_set,
        f_body, f_body_b,
        HIGHLIGHT_GREEN, ACCENT_GREEN,
        max_x, lh, sp, body_h,
    )

    y += c2h + 44

    # ── Encorajamento ──
    if encouragement:
        draw.text((PAD, y), encouragement, font=f_enc, fill=ACCENT_PURPLE)

    # ── Home bar ──
    bar_w, bar_h = 180, 6
    bar_x = (W - bar_w) // 2
    bar_y = img_h - 36
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=bar_h // 2, fill=HOME_BAR,
    )

    # ── Salvar ──
    out = AUDIO_CACHE_DIR / f"{filename}.png"
    img.save(str(out), "PNG")
    logger.info("Feedback image: %s (%dx%d)", out, W, img_h)
    return out
