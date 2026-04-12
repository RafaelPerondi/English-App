"""
Feedback image generator — Pillow.

Layout: iOS-inspired vertical mobile (1080×1920+). Score ring with
glassmorphism cards, Peach Warm palette. Cards: "O que você disse" +
"Versão corrigida" + "Detalhes".

Design goals:
- Retina-quality ring via 6× SSAA + LANCZOS downsample.
- Pixel-perfect text centering via Pillow anchors.
- Zero horizontal overflow — long words/phrases truncated with ellipsis.
- Optically centered highlight pills (based on cap-height, not nominal metrics).
- Defensive against malformed input data.
"""

from __future__ import annotations

import logging
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

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

@lru_cache(maxsize=32)
def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load and cache a font at the given size and weight.

    Caching: font loading walks the filesystem and parses TTF each call.
    With ~11 calls per image generation, caching is ~10× faster overall.
    """
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
        logger.warning("No TTF font found; falling back to Pillow default.")
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
    """Composite a glass card onto `img`.

    Performance: we composite on a small tile (card bbox + shadow margin)
    rather than allocating full-image RGBA layers. For a 1080×2000 image
    with 3 cards, this is ~50× less RAM churn than the naive full-image
    approach.
    """
    SHADOW_MARGIN = 16  # enough for 3-layer shadow offsets (max offset = 9+2)
    tile_x0 = max(0, x0 - SHADOW_MARGIN)
    tile_y0 = max(0, y0 - SHADOW_MARGIN)
    tile_x1 = min(img.size[0], x1 + SHADOW_MARGIN)
    tile_y1 = min(img.size[1], y1 + SHADOW_MARGIN)
    tile_w = tile_x1 - tile_x0
    tile_h = tile_y1 - tile_y0

    # Extract the tile region from the source image as RGBA base
    tile = img.crop((tile_x0, tile_y0, tile_x1, tile_y1)).convert("RGBA")

    # Coordinates relative to the tile
    rx0, ry0 = x0 - tile_x0, y0 - tile_y0
    rx1, ry1 = x1 - tile_x0, y1 - tile_y0

    # Soft shadow — 3 layers
    shadow = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i in range(3, 0, -1):
        o = i * 3
        a = 18 + (3 - i) * 8
        sd.rounded_rectangle(
            (rx0 + o, ry0 + o + 2, rx1 + o, ry1 + o + 2),
            radius=CARD_R, fill=(*CARD_SHADOW_CLR, a),
        )
    tile = Image.alpha_composite(tile, shadow)

    # Glass card body
    card = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    alpha_int = int(CARD_ALPHA * 255)
    cd.rounded_rectangle(
        (rx0, ry0, rx1, ry1),
        radius=CARD_R, fill=(255, 255, 255, alpha_int),
    )
    # Subtle border in the same layer — avoids one extra composite
    cd.rounded_rectangle(
        (rx0, ry0, rx1, ry1),
        radius=CARD_R, fill=None, outline=(*CARD_BORDER_CLR, 60), width=1,
    )
    tile = Image.alpha_composite(tile, card)

    # Paste result back
    img.paste(tile.convert("RGB"), (tile_x0, tile_y0))
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
    Ring profissional — qualidade retina, pontas flush (corte reto limpo).

    Técnica:
    1) SSAA 6× num canvas RGBA transparente → AA via alpha composite.
    2) Trilha 360° + arco de progresso com draw.arc() nativo.
    3) Pontas terminam alinhadas com a borda do traço (sem saliências).
    4) Downsample LANCZOS.
    5) Número central via anchor="mm" (Pillow middle-middle) — centralização
       pixel-perfect usando métricas internas da fonte.
    """
    SCALE = 6

    bg_at_center = _bg_color_at(cy, bg_mid, bg_total)
    ring_bg_color = _blend(RING_FG, bg_at_center, RING_BG_ALPHA)

    pad = 2
    size = (radius + thick) * 2 * SCALE + pad * 2 * SCALE
    ring_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring_img)

    rcx = rcy = size // 2
    r_hi = radius * SCALE
    t_hi = thick * SCALE
    bbox = (rcx - r_hi, rcy - r_hi, rcx + r_hi, rcy + r_hi)

    # 1) Trilha 360°
    rd.arc(bbox, start=0, end=360, fill=(*ring_bg_color, 255), width=t_hi)

    # 2) Arco de progresso — pontas flush (corte reto, sem bolinhas)
    prog = max(0, min(360, int(score / 100 * 360)))
    if prog > 0:
        rd.arc(bbox, start=-90, end=-90 + prog,
               fill=(*RING_FG, 255), width=t_hi)

    # 3) Downsample LANCZOS
    target_size = size // SCALE
    ring_img = ring_img.resize((target_size, target_size),
                               Image.Resampling.LANCZOS)

    paste_x = cx - target_size // 2
    paste_y = cy - target_size // 2
    img.paste(ring_img, (paste_x, paste_y), ring_img)

    # 4) Número central — anchor="mm" = centralização pixel-perfect
    # (middle horizontal, middle vertical baseado nas métricas da fonte)
    draw = ImageDraw.Draw(img)
    draw.text((cx, cy), str(score),
              font=font_big, fill=ACCENT_PURPLE, anchor="mm")

    return draw


def _dot_aligned(draw, x: int, y_text: int, font, color,
                 diameter: int = 14, gap: int = 12) -> int:
    """
    Dot centralizado verticalmente com a cap-height do texto.

    Usa getbbox("H") pra medir apenas a altura da maiúscula (sem descender),
    dando um alinhamento ótico mais preciso do que "Hx".
    """
    bb = font.getbbox("H")
    glyph_mid_y = y_text + (bb[1] + bb[3]) // 2
    r = diameter // 2
    draw.ellipse(
        (x, glyph_mid_y - r, x + diameter, glyph_mid_y + r),
        fill=color,
    )
    return x + diameter + gap


# ─────────────────────────────────────────────
# Text with highlights
# ─────────────────────────────────────────────

def _render_hl(draw, sx, sy, text, hl_set, f, fb, hlc, hltc, mx, lh, sp, bh):
    """
    Renderiza texto com highlights "pill" centralizados opticamente.

    Garantias:
    - Pills centradas verticalmente na cap-height (sem vão inferior).
    - Palavras maiores que a largura disponível são truncadas com "…"
      (evita vazamento pra fora do card).
    """
    bb_cap = fb.getbbox("Hg")
    cap_top, cap_bot = bb_cap[1], bb_cap[3]
    visual_h = cap_bot - cap_top
    max_word_w = mx - sx  # largura útil numa linha vazia

    words = text.split()
    cx, cy = sx, sy
    for w in words:
        cl = _clean(w)
        is_hl = cl in hl_set and len(cl) > 0
        font_w = fb if is_hl else f

        # Se palavra sozinha não cabe nem numa linha inteira, trunca
        reserved = HL_PAD_X * 2 + 4 if is_hl else 0
        if _tw(w, font_w) + reserved > max_word_w:
            w = _truncate(w, font_w, max_word_w - reserved)

        ww = _tw(w, font_w)

        if is_hl:
            hw = ww + HL_PAD_X * 2 + 4
            if cx + hw > mx:
                cx = sx; cy += lh
            visual_mid = cy + (cap_top + cap_bot) / 2
            pill_half = visual_h / 2 + HL_PAD_Y
            draw.rounded_rectangle(
                (cx, int(visual_mid - pill_half),
                 cx + hw, int(visual_mid + pill_half)),
                radius=12, fill=hlc,
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
    """Measure wrapped height for highlighted text.

    IMPORTANT: highlighted words use bold font (`fb`), which is wider than
    regular (`f`). Using `f` for measurement underestimates width and causes
    card under-sizing — resulting in text overflow at render time. This
    function mirrors `_render_hl`'s font selection exactly.
    """
    words = text.split()
    cx, cy = sx, 0
    for w in words:
        cl = _clean(w)
        is_hl = cl in hl_set and len(cl) > 0
        font_w = fb if is_hl else f
        ww = _tw(w, font_w)
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


def _truncate(text: str, font, max_w: int, ellipsis: str = "…") -> str:
    """Trunca texto com reticências se exceder max_w pixels."""
    if _tw(text, font) <= max_w:
        return text
    ew = _tw(ellipsis, font)
    # Busca binária seria ideal; linear é ok para textos curtos
    for i in range(len(text) - 1, 0, -1):
        t = text[:i].rstrip()
        if _tw(t, font) + ew <= max_w:
            return t + ellipsis
    return ellipsis


def _draw_det(draw, x, y, errors, fl, fd, fdb, mx=None):
    """Desenha card de detalhes. mx = margem direita; trunca textos se excederem."""
    if not errors:
        return y

    tx_txt = _dot_aligned(draw, x, y, fl, DOT_PURPLE)
    draw.text((tx_txt, y), "Detalhes", font=fl, fill=TEXT_DARK)
    y += _th(fl) + 24

    nr = 18  # raio da bolinha

    for i, e in enumerate(errors):
        wrong = e.get("wrong", "")
        right = e.get("right", "")

        # Bolinha numerada
        draw.ellipse((x, y, x + nr * 2, y + nr * 2), fill=ERROR_NUM_BG)
        nt = str(i + 1)
        # anchor="mm" pro número da bolinha — centralização pixel-perfect
        draw.text((x + nr, y + nr), nt, font=fdb,
                  fill=ACCENT_RED, anchor="mm")

        # Layout horizontal: [bolinha] [wrong tachado] [→] [right]
        # Truncar wrong e right se não couber
        tx = x + nr * 2 + 18
        arrow_w = 28 + 16 + 16  # seta + gaps

        if mx is not None:
            # Calcular espaço disponível dividido entre wrong e right
            total_available = mx - tx - arrow_w
            if total_available < 100:
                # muito apertado: não mostra wrong, só o right
                wrong = ""
                max_right = max(total_available + len(wrong) * 10, 60)
                right = _truncate(right, fdb, max_right)
            else:
                # divide proporcionalmente
                half = total_available // 2
                wrong = _truncate(wrong, fd, half)
                right = _truncate(right, fdb, total_available - _tw(wrong, fd))

        ww = _tw(wrong, fd)
        ty = y + (nr * 2 - _th(fd)) // 2

        if wrong:
            draw.text((tx, ty), wrong, font=fd, fill=TEXT_MUTED)
            sy = ty + _th(fd) // 2
            draw.line([(tx, sy), (tx + ww, sy)], fill=TEXT_MUTED, width=2)

        # Seta
        ax = tx + ww + (18 if wrong else 0)
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

# ─────────────────────────────────────────────
# Input normalization & score calculation
# ─────────────────────────────────────────────

def _normalize_input(data: Any) -> dict:
    """Normalize and validate correction data.

    Returns a dict with safe, predictable types. Never raises on malformed
    input — substitutes placeholders and logs warnings. Important because
    upstream OpenAI responses can occasionally be malformed.
    """
    if not isinstance(data, dict):
        logger.warning("correction_data is not a dict (%s); using empty.",
                       type(data).__name__)
        data = {}

    def _s(v: Any, default: str = "") -> str:
        if v is None:
            return default
        s = v if isinstance(v, str) else str(v)
        return s[:1000]  # hard cap against pathological inputs

    raw_errors = data.get("errors", [])
    if not isinstance(raw_errors, list):
        raw_errors = []
    errors: list[dict] = []
    for e in raw_errors[:5]:
        if not isinstance(e, dict):
            continue
        w = _s(e.get("wrong")).strip()
        r = _s(e.get("right")).strip()
        if w or r:
            errors.append({"wrong": w, "right": r})

    return {
        "original": _s(data.get("original"), "—"),
        "corrected": _s(data.get("corrected"), "—"),
        "encouragement": _s(data.get("encouragement")),
        "errors": errors,
    }


def _compute_score(original: str, errors: list) -> int:
    """Compute score as percentage of non-erroneous words.

    Counts words inside each error (e.g., "I eat" contributes 2 wrong words)
    giving a more accurate severity measure than raw error count.
    """
    if not original.strip():
        return 100 if not errors else 50
    total = max(len(original.split()), 1)
    wrong = sum(max(len(e.get("wrong", "").split()), 1) for e in errors)
    ratio = min(wrong / total, 1.0)
    return max(0, min(100, int(round(100 * (1 - ratio)))))


# ─────────────────────────────────────────────
# Main entry point
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

    t_start = time.perf_counter()

    # Validate and normalize input — never trust upstream data
    norm = _normalize_input(correction_data)
    original = norm["original"]
    corrected = norm["corrected"]
    errors = norm["errors"]
    enc = _to_pt(norm["encouragement"])
    n_err = len(errors)

    score = _compute_score(original, errors)

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
    tx_txt = _dot_aligned(draw, tsx, cy, f_sec, DOT_RED)
    draw.text((tx_txt, cy), "O que você disse", font=f_sec, fill=TEXT_DARK)
    cy += sec_hdr
    _render_hl(draw, tsx, cy, original, ws, f_body, f_body_b,
               HIGHLIGHT_YELLOW, TEXT_DARK, tmx, lh, sp, bh)
    y += c1h + gap

    # ── Card 2: Versão corrigida ──
    draw = _glass(img, cx0, y, cx1, y + c2h)
    cy = y + CARD_PAD
    tx_txt = _dot_aligned(draw, tsx, cy, f_sec, DOT_GREEN)
    draw.text((tx_txt, cy), "Versão corrigida", font=f_sec, fill=TEXT_DARK)
    cy += sec_hdr
    _render_hl(draw, tsx, cy, corrected, rs, f_body, f_body_b,
               HIGHLIGHT_GREEN, ACCENT_GREEN, tmx, lh, sp, bh)
    y += c2h + gap

    # ── Card 3: Detalhes ──
    if errors:
        draw = _glass(img, cx0, y, cx1, y + c3h)
        _draw_det(draw, tsx, y + CARD_PAD, errors, f_sec, f_det, f_det_b, mx=tmx)
        y += c3h + 32
    else:
        y += 12

    # ── Encorajamento ──
    if enc:
        # Trunca por largura em pixels (mais preciso que contar chars)
        max_enc_w = W - PAD * 2
        enc = _truncate(enc, f_enc, max_enc_w)
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

    # Save with robust error handling
    # PNG options: optimize=False keeps save time low; compress_level=6 is
    # a good balance between filesize and speed (default is 6 but we're
    # explicit for clarity).
    try:
        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = AUDIO_CACHE_DIR / f"{filename}.png"
        img.save(str(out), "PNG", compress_level=6)
    except (OSError, IOError) as e:
        logger.error("Failed to save feedback image to %s: %s",
                     AUDIO_CACHE_DIR, e)
        raise

    elapsed_ms = (time.perf_counter() - t_start) * 1000
    logger.info("Feedback image generated: %s (%dx%d, score=%d, errors=%d, %.0fms)",
                out.name, W, img_h, score, n_err, elapsed_ms)
    return out
