"""
Serviço de geração de imagens de feedback — Pillow.
Layout iOS moderno: score ring lateral, glassmorphism cards, Peach Warm.
Vertical mobile 1080×1920+. Ring com gap real proporcional ao score.
Cards: "O que você disse" + "Versão corrigida" + "Detalhes".
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import AUDIO_CACHE_DIR, FONTS_DIR

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Paleta — Peach Warm suave + roxo
# ─────────────────────────────────────────────

BG_TOP = (248, 232, 222)       # peach suave (mais claro que antes)
BG_MID = (251, 240, 233)
BG_BOT = (253, 249, 246)

CARD_ALPHA = 0.84               # 84% opacidade glass

TEXT_DARK = (36, 36, 42)
TEXT_MED = (90, 90, 105)
TEXT_LIGHT = (145, 145, 155)
TEXT_MUTED = (178, 178, 185)

ACCENT_PURPLE = (100, 45, 210)
ACCENT_PURPLE_SOFT = (70, 55, 145)
ACCENT_GREEN = (32, 120, 48)
ACCENT_RED = (220, 80, 55)

HIGHLIGHT_GREEN = (215, 245, 208)
HIGHLIGHT_YELLOW = (255, 243, 200)

# Ring: trilha = roxo 12% sobre peach, arco = roxo sólido
RING_FG = (100, 45, 210)
RING_BG_ALPHA = 0.22

DOT_RED = (220, 80, 55)
DOT_GREEN = (50, 165, 65)
DOT_PURPLE = (100, 45, 210)

ERROR_NUM_BG = (253, 238, 236)
ARROW_CLR = (100, 45, 210)

WHITE = (255, 255, 255)
HOME_BAR = (208, 205, 215)

CARD_SHADOW_CLR = (195, 190, 210)
CARD_BORDER_CLR = (225, 222, 232)

W = 1080
PAD = 60
CARD_PAD = 48
CARD_R = 40
LINE_SP = 24
MIN_H = 1920
HL_PAD_X = 14
HL_PAD_Y = 10

# ─────────────────────────────────────────────
# Encouragement PT
# ─────────────────────────────────────────────

_PT_ENC = {
    "great effort": "Ótimo esforço! Continue assim!",
    "keep practicing": "Continue praticando!",
    "good job": "Bom trabalho!",
    "well done": "Muito bem!",
    "nice try": "Boa tentativa!",
    "keep going": "Continue assim!",
    "keep it up": "Continue assim!",
    "you're doing great": "Você está indo muito bem!",
    "excellent": "Excelente!",
    "perfect": "Perfeito! Sem erros!",
}


def _score_label(s: int) -> str:
    if s >= 90: return "Excelente!"
    if s >= 75: return "Muito bom!"
    if s >= 60: return "Bom trabalho!"
    if s >= 40: return "Continue praticando!"
    return "Não desista!"


def _to_pt(enc: str) -> str:
    if not enc:
        return "Continue praticando!"
    lo = enc.lower()
    if any(c in lo for c in "ãõçéáíóú"):
        return enc
    for eng, pt in _PT_ENC.items():
        if eng in lo:
            return pt
    return "Ótimo esforço! Continue praticando!"


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
        path = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ─────────────────────────────────────────────
# Helpers de texto
# ─────────────────────────────────────────────

def _clean(w: str) -> str:
    return re.sub(r"[^a-zA-Z0-9']", "", w).lower()


def _hl_set(errors: list, key: str) -> set:
    r = set()
    for e in errors:
        v = e.get(key, "")
        if not v:
            continue
        r.add(_clean(v))
        for w in v.split():
            c = _clean(w)
            if c and len(c) > 1:
                r.add(c)
    return r


def _tw(text: str, font) -> int:
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def _th(font) -> int:
    bb = font.getbbox("Ay")
    return bb[3] - bb[1]


def _lh(font) -> int:
    return _th(font) + LINE_SP


def _blend(fg: tuple, bg: tuple, alpha: float) -> tuple:
    """Blend manual: fg sobre bg com alpha [0..1]. Retorna RGB tuple."""
    return tuple(int(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


# ─────────────────────────────────────────────
# Background Peach Warm
# ─────────────────────────────────────────────

def _gradient(img: Image.Image, mid: int, total: int) -> None:
    d = ImageDraw.Draw(img)
    for row in range(total):
        if row < mid:
            t = row / max(mid - 1, 1)
            top, bot = BG_TOP, BG_MID
        else:
            t = min((row - mid) / max(total - mid - 1, 1), 1.0)
            top, bot = BG_MID, BG_BOT
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        d.line([(0, row), (W, row)], fill=c)


def _bg_color_at(y: int, mid: int, total: int) -> tuple:
    """Retorna a cor do background na linha y (para blend do ring)."""
    if y < mid:
        t = y / max(mid - 1, 1)
        top, bot = BG_TOP, BG_MID
    else:
        t = min((y - mid) / max(total - mid - 1, 1), 1.0)
        top, bot = BG_MID, BG_BOT
    return tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))


# ─────────────────────────────────────────────
# Glass card (RGBA composite)
# ─────────────────────────────────────────────

def _glass(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> ImageDraw.ImageDraw:
    base = img.convert("RGBA")

    # Sombra suave (3 camadas)
    for i in range(3, 0, -1):
        o = i * 3
        a = 18 + (3 - i) * 8
        ly = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(ly).rounded_rectangle(
            (x0 + o, y0 + o + 2, x1 + o, y1 + o + 2),
            radius=CARD_R, fill=(*CARD_SHADOW_CLR, a),
        )
        base = Image.alpha_composite(base, ly)

    # Card branco semi-transparente
    alpha_int = int(CARD_ALPHA * 255)
    ly = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(ly)
    ld.rounded_rectangle(
        (x0, y0, x1, y1), radius=CARD_R, fill=(255, 255, 255, alpha_int),
    )
    base = Image.alpha_composite(base, ly)

    # Borda sutil
    ly2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ly2).rounded_rectangle(
        (x0, y0, x1, y1), radius=CARD_R,
        fill=None, outline=(*CARD_BORDER_CLR, 60), width=1,
    )
    base = Image.alpha_composite(base, ly2)

    result = base.convert("RGB")
    img.paste(result, (0, 0))
    return ImageDraw.Draw(img)


# ─────────────────────────────────────────────
# Score ring com gap real
# ─────────────────────────────────────────────

def _ring(
    img: Image.Image, cx: int, cy: int,
    radius: int, thick: int, score: int,
    font_big, bg_mid: int, bg_total: int,
) -> ImageDraw.ImageDraw:
    """
    Ring com gap real: trilha de fundo em cor blendada (roxo suave),
    arco de progresso em roxo sólido. A diferença é visível porque
    usamos blend manual em vez de alpha (que Pillow ignora em RGB).
    """
    draw = ImageDraw.Draw(img)
    h = thick // 2

    # Cor da trilha: roxo blendado sobre a cor de fundo no centro do ring
    bg_at_center = _bg_color_at(cy, bg_mid, bg_total)
    ring_bg_color = _blend(RING_FG, bg_at_center, RING_BG_ALPHA)

    # 1) Trilha de fundo completa (360°) — cor suave
    for deg in range(360):
        a = math.radians(deg - 90)
        x = cx + radius * math.cos(a)
        y = cy + radius * math.sin(a)
        draw.ellipse((x - h, y - h, x + h, y + h), fill=ring_bg_color)

    # 2) Arco de progresso — cor sólida, proporcional ao score
    prog = max(0, int(score / 100 * 360))
    if prog > 0:
        for deg in range(prog):
            a = math.radians(deg - 90)
            x = cx + radius * math.cos(a)
            y = cy + radius * math.sin(a)
            draw.ellipse((x - h, y - h, x + h, y + h), fill=RING_FG)

    # 3) Número central
    txt = str(score)
    tw = _tw(txt, font_big)
    th = _th(font_big)
    draw.text((cx - tw // 2, cy - th // 2 - 2), txt, font=font_big, fill=ACCENT_PURPLE)

    return draw


# ─────────────────────────────────────────────
# Text with highlights
# ─────────────────────────────────────────────

def _render_hl(draw, sx, sy, text, hl_set, f, fb, hlc, hltc, mx, lh, sp, bh):
    words = text.split()
    cx, cy = sx, sy
    for w in words:
        cl = _clean(w)
        ww = _tw(w, f)
        is_hl = cl in hl_set and len(cl) > 0
        if is_hl:
            hw = ww + HL_PAD_X * 2 + 4
            if cx + hw > mx:
                cx = sx; cy += lh
            draw.rounded_rectangle(
                (cx, cy - HL_PAD_Y, cx + hw, cy + bh + HL_PAD_Y),
                radius=10, fill=hlc,
            )
            draw.text((cx + HL_PAD_X + 2, cy), w, font=fb, fill=hltc)
            cx += hw + sp
        else:
            if cx + ww > mx:
                cx = sx; cy += lh
            draw.text((cx, cy), w, font=f, fill=TEXT_DARK)
            cx += ww + sp
    return cy + lh


def _measure_hl(text, hl_set, f, fb, sx, mx, lh, sp):
    words = text.split()
    cx, cy = sx, 0
    for w in words:
        cl = _clean(w)
        ww = _tw(w, f)
        is_hl = cl in hl_set and len(cl) > 0
        if is_hl:
            hw = ww + HL_PAD_X * 2 + 4
            if cx + hw > mx:
                cx = sx; cy += lh
            cx += hw + sp
        else:
            if cx + ww > mx:
                cx = sx; cy += lh
            cx += ww + sp
    return cy + lh


# ─────────────────────────────────────────────
# Card de detalhes
# ─────────────────────────────────────────────

_DET_ROW = 40
_DET_GAP = 16


def _meas_det(errors, fl, fd):
    if not errors:
        return 0
    return _th(fl) + 24 + len(errors) * (_DET_ROW + _DET_GAP) - _DET_GAP


def _draw_det(draw, x, y, errors, fl, fd, fdb):
    if not errors:
        return y

    draw.ellipse((x, y + 8, x + 14, y + 22), fill=DOT_PURPLE)
    draw.text((x + 26, y), "Detalhes", font=fl, fill=TEXT_DARK)
    y += _th(fl) + 24

    nr = 18  # raio da bolinha

    for i, e in enumerate(errors):
        wrong = e.get("wrong", "")
        right = e.get("right", "")

        # Bolinha numerada
        draw.ellipse((x, y, x + nr * 2, y + nr * 2), fill=ERROR_NUM_BG)
        nt = str(i + 1)
        ntw = _tw(nt, fdb)
        nth = _th(fdb)
        draw.text(
            (x + nr - ntw // 2, y + nr - nth // 2),
            nt, font=fdb, fill=ACCENT_RED,
        )

        # Texto errado + tachado
        tx = x + nr * 2 + 18
        ty = y + (nr * 2 - _th(fd)) // 2
        draw.text((tx, ty), wrong, font=fd, fill=TEXT_MUTED)
        ww = _tw(wrong, fd)
        sy = ty + _th(fd) // 2
        draw.line([(tx, sy), (tx + ww, sy)], fill=TEXT_MUTED, width=2)

        # Seta
        ax = tx + ww + 18
        ay = ty + _th(fd) // 2
        al = 28
        draw.line([(ax, ay), (ax + al, ay)], fill=ARROW_CLR, width=3)
        draw.polygon(
            [(ax + al, ay), (ax + al - 9, ay - 6), (ax + al - 9, ay + 6)],
            fill=ARROW_CLR,
        )

        # Correção
        draw.text((ax + al + 16, ty), right, font=fdb, fill=ACCENT_GREEN)
        y += nr * 2 + _DET_GAP

    return y


# ─────────────────────────────────────────────
# Geração principal
# ─────────────────────────────────────────────

def generate_feedback_image(correction_data: dict, filename: str) -> Path:

    # Fontes (ligeiramente maiores para legibilidade)
    f_tag    = _f(28, True)
    f_score  = _f(68, True)      # número no ring
    f_inf_t  = _f(28, True)      # "Score geral"
    f_inf_d  = _f(28, True)      # "Muito bom!"
    f_inf_s  = _f(24)            # "3 correções encontradas"
    f_sec    = _f(32, True)      # headers dos cards
    f_body   = _f(38)            # corpo do texto
    f_body_b = _f(38, True)
    f_det    = _f(30)            # detalhes
    f_det_b  = _f(30, True)
    f_enc    = _f(34, True)      # encorajamento

    # Dados
    original  = correction_data.get("original", "...")
    corrected = correction_data.get("corrected", "...")
    errors    = correction_data.get("errors", [])[:5]
    enc       = _to_pt(correction_data.get("encouragement", ""))
    n_err     = len(errors)

    total_w = len(original.split()) if original else 10
    score = max(0, min(100, int(100 - (n_err / max(total_w, 1)) * 100)))

    ws = _hl_set(errors, "wrong")
    rs = _hl_set(errors, "right")

    # Layout
    cx0 = PAD
    cx1 = W - PAD
    tsx = cx0 + CARD_PAD
    tmx = cx1 - CARD_PAD

    lh = _lh(f_body)
    sp = _tw(" ", f_body) + 4
    bh = _th(f_body)

    sec_hdr = _th(f_sec) + 20

    # Medir cards
    t1h = _measure_hl(original, ws, f_body, f_body_b, tsx, tmx, lh, sp)
    c1h = CARD_PAD + sec_hdr + t1h + CARD_PAD

    t2h = _measure_hl(corrected, rs, f_body, f_body_b, tsx, tmx, lh, sp)
    c2h = CARD_PAD + sec_hdr + t2h + CARD_PAD

    c3h = 0
    if errors:
        di = _meas_det(errors, f_sec, f_det)
        c3h = CARD_PAD + di + CARD_PAD

    # Score area
    ring_r = 108
    score_area = 80 + ring_r * 2 + 40

    gap = 24

    total_h = (
        PAD + 24
        + score_area
        + c1h + gap
        + c2h + gap
        + (c3h + gap if errors else 0)
        + _lh(f_enc) + 24
        + 60
    )
    img_h = max(total_h, MIN_H)

    bg_mid = score_area + PAD

    # Criar imagem
    img = Image.new("RGB", (W, img_h), BG_BOT)
    _gradient(img, bg_mid, img_h)
    draw = ImageDraw.Draw(img)

    y = PAD + 24

    # ── Tag "Feedback" centralizada ──
    tag = "Feedback"
    ttw = _tw(tag, f_tag)
    tp = ttw + 56
    tph = 52
    tx = (W - tp) // 2
    draw.rounded_rectangle(
        (tx, y, tx + tp, y + tph),
        radius=tph // 2, fill=WHITE,
    )
    draw.ellipse((tx + 16, y + 16, tx + 32, y + 32), fill=ACCENT_PURPLE)
    draw.text((tx + 42, y + 12), tag, font=f_tag, fill=ACCENT_PURPLE_SOFT)
    y += tph + 36

    # ── Score ring (mais centralizado à esquerda) ──
    ring_thick = 18
    rcx = PAD + 40 + ring_r  # mais à esquerda e centralizado
    rcy = y + ring_r + 8

    draw = _ring(img, rcx, rcy, ring_r, ring_thick, score, f_score, bg_mid, img_h)

    # Info ao lado do ring
    ix = rcx + ring_r + 52
    iy = rcy - 44

    draw.text((ix, iy), "Score geral", font=f_inf_t, fill=TEXT_MED)
    iy += _th(f_inf_t) + 8

    draw.text((ix, iy), _score_label(score), font=f_inf_d, fill=ACCENT_PURPLE)
    iy += _th(f_inf_d) + 10

    if n_err == 0:
        sub = "Nenhum erro encontrado"
    elif n_err == 1:
        sub = "1 correção encontrada"
    else:
        sub = f"{n_err} correções encontradas"
    draw.text((ix, iy), sub, font=f_inf_s, fill=TEXT_LIGHT)

    y = rcy + ring_r + 48

    # ── Card 1: O que você disse ──
    draw = _glass(img, cx0, y, cx1, y + c1h)
    cy = y + CARD_PAD
    draw.ellipse((tsx, cy + 8, tsx + 14, cy + 22), fill=DOT_RED)
    draw.text((tsx + 26, cy), "O que você disse", font=f_sec, fill=TEXT_DARK)
    cy += sec_hdr
    _render_hl(draw, tsx, cy, original, ws, f_body, f_body_b,
               HIGHLIGHT_YELLOW, TEXT_DARK, tmx, lh, sp, bh)
    y += c1h + gap

    # ── Card 2: Versão corrigida ──
    draw = _glass(img, cx0, y, cx1, y + c2h)
    cy = y + CARD_PAD
    draw.ellipse((tsx, cy + 8, tsx + 14, cy + 22), fill=DOT_GREEN)
    draw.text((tsx + 26, cy), "Versão corrigida", font=f_sec, fill=TEXT_DARK)
    cy += sec_hdr
    _render_hl(draw, tsx, cy, corrected, rs, f_body, f_body_b,
               HIGHLIGHT_GREEN, ACCENT_GREEN, tmx, lh, sp, bh)
    y += c2h + gap

    # ── Card 3: Detalhes ──
    if errors:
        draw = _glass(img, cx0, y, cx1, y + c3h)
        _draw_det(draw, tsx, y + CARD_PAD, errors, f_sec, f_det, f_det_b)
        y += c3h + 32
    else:
        y += 12

    # ── Encorajamento ──
    if enc:
        if len(enc) > 55:
            enc = enc[:52] + "..."
        ew = _tw(enc, f_enc)
        draw.text(((W - ew) // 2, y), enc, font=f_enc, fill=ACCENT_PURPLE)

    # ── Home bar ──
    bw, bh2 = 180, 6
    bx = (W - bw) // 2
    by = img_h - 40
    draw.rounded_rectangle(
        (bx, by, bx + bw, by + bh2),
        radius=bh2 // 2, fill=HOME_BAR,
    )

    # Salvar
    out = AUDIO_CACHE_DIR / f"{filename}.png"
    img.save(str(out), "PNG")
    logger.info("Feedback image: %s (%dx%d)", out, W, img_h)
    return out
