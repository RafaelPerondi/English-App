"""
Serviço de geração de imagens de feedback — Pillow.
Layout vertical FULL HD mobile (1080×1920+).
Preenche a tela toda do celular ao abrir.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import AUDIO_CACHE_DIR, FONTS_DIR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Cores
# ─────────────────────────────────────────────

BG = (9, 9, 11)
HEADER_L = (88, 28, 135)
HEADER_R = (168, 85, 247)
PURPLE = (167, 139, 250)
GREEN = (74, 222, 128)
GREEN_TXT = (209, 250, 229)
RED = (239, 68, 68)
YELLOW = (250, 204, 21)
WHITE = (255, 255, 255)
BODY = (175, 175, 185)
MUTED = (70, 70, 80)
RULE_C = (100, 100, 115)
CARD_BG = (18, 18, 22)
CARD_BORDER = (38, 38, 48)
PILL_RED_BG = (55, 16, 16)
PILL_GREEN_BG = (12, 42, 22)
ENC_BG = (32, 30, 12)
ENC_BORDER = (65, 60, 18)

W = 1080
PAD = 56
CARD_PAD = 44
CARD_R = 30
BORDER_W = 7
LINE_SP = 12
MIN_H = 1920  # Altura mínima = tela mobile completa


# ─────────────────────────────────────────────
# Fontes
# ─────────────────────────────────────────────

def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
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
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _wrap(text: str, font, mw: int) -> list[str]:
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


def _lh(font) -> int:
    return font.getbbox("Ay")[3] - font.getbbox("Ay")[1] + LINE_SP


def _th(text, font, mw) -> int:
    return _lh(font) * len(_wrap(text, font, mw))


def _dt(draw, pos, text, font, fill, mw) -> int:
    x, y = pos
    h = _lh(font)
    for ln in _wrap(text, font, mw):
        draw.text((x, y), ln, font=font, fill=fill)
        y += h
    return y


def _stars(draw, w, h):
    rng = random.Random(42)
    for _ in range(80):
        sx = rng.randint(10, w - 10)
        sy = rng.randint(10, h - 10)
        sz = rng.choice([1, 2, 2, 3])
        draw.ellipse((sx, sy, sx + sz, sy + sz), fill=(255, 255, 255, 50))


def _gradient(img, h):
    """Gradiente roxo rápido (linha por linha, não pixel por pixel)."""
    w = img.width
    for y in range(h):
        yr = y / max(h - 1, 1)
        # Cria uma linha de gradiente horizontal
        line = Image.new("RGB", (w, 1))
        px = line.load()
        for x in range(w):
            t = (x / max(w - 1, 1)) * 0.7 + yr * 0.3
            r = int(HEADER_L[0] + (HEADER_R[0] - HEADER_L[0]) * t)
            g = int(HEADER_L[1] + (HEADER_R[1] - HEADER_L[1]) * t)
            b = int(HEADER_L[2] + (HEADER_R[2] - HEADER_L[2]) * t)
            px[x, 0] = (r, g, b)
        img.paste(line, (0, y))


def _card(draw, x0, y0, x1, y1, accent=None):
    draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_R, fill=CARD_BG, outline=CARD_BORDER)
    if accent:
        draw.rounded_rectangle(
            (x0 + 3, y0 + 14, x0 + 3 + BORDER_W, y1 - 14),
            radius=3, fill=accent,
        )


def _pill(draw, x, y, text, font, color, bg, strike=False) -> int:
    tw = font.getbbox(text)[2]
    th = font.getbbox(text)[3] - font.getbbox(text)[1]
    pw, ph = tw + 52, th + 24
    draw.rounded_rectangle((x, y, x + pw, y + ph), radius=ph // 2, fill=bg)
    tx, ty = x + 26, y + (ph - th) // 2
    draw.text((tx, ty), text, font=font, fill=color)
    if strike:
        mid = ty + th // 2 + 1
        draw.line((tx - 3, mid, tx + tw + 3, mid), fill=color, width=3)
    return x + pw


# ─────────────────────────────────────────────
# Geração
# ─────────────────────────────────────────────

def generate_feedback_image(correction_data: dict, filename: str) -> Path:

    # Fontes HD
    f_title = _f(44, True)
    f_sub = _f(24)
    f_label = _f(24, True)
    f_body = _f(32)
    f_body_b = _f(32, True)
    f_pill = _f(30)
    f_pill_b = _f(30, True)
    f_rule = _f(24)
    f_sec = _f(22, True)
    f_enc = _f(30, True)

    cw = W - PAD * 2
    ci = cw - CARD_PAD * 2 - BORDER_W

    HH = 160  # header height

    original = correction_data.get("original", "...")
    corrected = correction_data.get("corrected", "...")
    errors = correction_data.get("errors", [])[:5]
    encouragement = correction_data.get("encouragement", "")

    # ── Calcular altura do conteúdo ──
    content_y = HH + 48

    # Card original
    content_y += 50
    content_y += CARD_PAD * 2 + _th(original, f_body, ci)
    content_y += 32

    # Card corrigido
    content_y += 50
    content_y += CARD_PAD * 2 + _th(corrected, f_body_b, ci)
    content_y += 44

    # Correções
    if errors:
        content_y += 56
        for e in errors:
            content_y += 110 + (40 if e.get("rule") else 0) + 20
        content_y += 16

    # Encorajamento
    if encouragement:
        content_y += 32 + _th(encouragement, f_enc, cw - 96) + 64

    content_y += PAD

    # Garantir altura mínima pra preencher tela mobile
    img_h = max(content_y, MIN_H)

    # Se a altura mínima é maior que o conteúdo, calcular offset pra
    # distribuir espaço: header no topo, conteúdo um pouco mais baixo
    extra_space = img_h - content_y
    top_offset = min(extra_space // 3, 120)  # empurra conteúdo pra baixo suavemente

    # ── Criar imagem ──
    img = Image.new("RGB", (W, img_h), BG)
    draw = ImageDraw.Draw(img)

    # Estrelas
    _stars(draw, W, img_h)

    # Header gradiente
    _gradient(img, HH)
    draw = ImageDraw.Draw(img)

    # ── Header: decoração + título ──
    # Barra decorativa vertical à esquerda do título
    bar_x = PAD
    bar_y = (HH - 70) // 2
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + 8, bar_y + 70),
        radius=4, fill=WHITE,
    )

    # Título "Feedback"
    draw.text((bar_x + 28, HH // 2 - 24), "Feedback", font=f_title, fill=WHITE)

    # Linha fina decorativa abaixo do título
    line_y = HH // 2 + 28
    draw.line((bar_x + 28, line_y, bar_x + 240, line_y), fill=(255, 255, 255, 120), width=2)

    # Subtítulo
    draw.text((bar_x + 28, line_y + 8), "English Teacher", font=f_sub, fill=(255, 255, 255, 180))

    # Decoração: três pontos no canto direito
    dx = W - PAD - 60
    dy = HH // 2 - 20
    for i, c in enumerate([(168, 85, 247), (124, 58, 237), (88, 28, 135)]):
        draw.ellipse((dx + i * 22, dy + i * 14, dx + 12 + i * 22, dy + 12 + i * 14), fill=c)

    y = HH + 48 + top_offset

    # ── Card: O que você disse ──
    draw.ellipse((PAD + 10, y + 8, PAD + 22, y + 20), fill=PURPLE)
    draw.text((PAD + 32, y - 2), "O QUE VOCÊ DISSE", font=f_label, fill=PURPLE)
    y += 50

    oh = _th(original, f_body, ci)
    ch = oh + CARD_PAD * 2
    _card(draw, PAD, y, W - PAD, y + ch, PURPLE)
    _dt(draw, (PAD + BORDER_W + CARD_PAD, y + CARD_PAD), original, f_body, BODY, ci)
    y += ch + 32

    # ── Card: Versão corrigida ──
    draw.ellipse((PAD + 10, y + 8, PAD + 22, y + 20), fill=GREEN)
    draw.text((PAD + 32, y - 2), "VERSÃO CORRIGIDA", font=f_label, fill=GREEN)
    y += 50

    ch2 = _th(corrected, f_body_b, ci) + CARD_PAD * 2
    _card(draw, PAD, y, W - PAD, y + ch2, GREEN)
    _dt(draw, (PAD + BORDER_W + CARD_PAD, y + CARD_PAD), corrected, f_body_b, GREEN_TXT, ci)
    y += ch2 + 44

    # ── Correções ──
    if errors:
        draw.text((PAD, y), "CORREÇÕES", font=f_sec, fill=MUTED)
        y += 56

        for error in errors:
            wrong = error.get("wrong", "")
            right = error.get("right", "")
            rule = error.get("rule", "")

            ech = 100 + (40 if rule else 0)
            _card(draw, PAD, y, W - PAD, y + ech)

            # Pills
            py = y + 28
            px = PAD + 32
            px = _pill(draw, px, py, wrong, f_pill, RED, PILL_RED_BG, strike=True)

            # Seta
            px += 24
            ay = py + 16
            draw.line((px, ay, px + 32, ay), fill=GREEN, width=3)
            draw.polygon([(px + 32, ay - 7), (px + 42, ay), (px + 32, ay + 7)], fill=GREEN)
            px += 54

            _pill(draw, px, py, right, f_pill_b, GREEN, PILL_GREEN_BG)

            if rule:
                draw.text((PAD + 32, y + 82), rule, font=f_rule, fill=RULE_C)

            y += ech + 20

    # ── Encorajamento ──
    if encouragement:
        y += 16
        eh = _th(encouragement, f_enc, cw - 96) + 64
        draw.rounded_rectangle(
            (PAD, y, W - PAD, y + eh),
            radius=CARD_R, fill=ENC_BG, outline=ENC_BORDER,
        )
        _dt(draw, (PAD + 48, y + 32), encouragement, f_enc, YELLOW, cw - 96)

    # ── Rodapé discreto no final da imagem ──
    footer_y = img_h - 50
    draw.text(
        (W // 2, footer_y),
        "English Teacher Bot",
        font=_f(20), fill=(50, 50, 60), anchor="mm",
    )

    # ── Salvar ──
    out = AUDIO_CACHE_DIR / f"{filename}.png"
    img.save(str(out), "PNG")
    logger.info("Feedback image: %s (%dx%d)", out, W, img_h)
    return out