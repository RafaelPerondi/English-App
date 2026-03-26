"""
Serviço de geração de imagens de feedback — Pillow.
Layout clean pastel Apple-vibe. Peach warm palette.
Vertical mobile 1080x1920+. Score X/100.
Highlights robustos que funcionam com textos longos.
Sem tips/regras na imagem.
"""

from __future__ import annotations

import logging
import re
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

# Encouragement em português (fallback se vier em inglês)
_PT_ENCOURAGEMENTS = {
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

def _clean(word: str) -> str:
    """Remove toda pontuação de uma palavra pra comparação."""
    return re.sub(r"[^a-zA-Z0-9']", "", word).lower()


def _build_highlight_set(errors: list, key: str) -> set:
    """
    Constrói set de palavras limpas a partir dos erros.
    key = 'wrong' para o card de pronúncia, 'right' para o card de correção.
    Inclui cada palavra individual de frases multi-palavra.
    """
    result = set()
    for e in errors:
        val = e.get(key, "")
        if not val:
            continue
        # Adiciona a frase inteira (limpa) e cada palavra individual
        result.add(_clean(val))
        for w in val.split():
            cleaned = _clean(w)
            if cleaned and len(cleaned) > 1:  # ignora palavras de 1 letra como pontuação
                result.add(cleaned)
    return result


def _to_portuguese(encouragement: str) -> str:
    """Converte encouragement para português se estiver em inglês."""
    if not encouragement:
        return "Continue praticando!"
    lower = encouragement.lower()
    # Se já contém caracteres portugueses, provavelmente já está em PT
    if any(c in lower for c in "ãõçéáíóú"):
        return encouragement
    # Tenta match parcial
    for eng, pt in _PT_ENCOURAGEMENTS.items():
        if eng in lower:
            return pt
    # Fallback genérico
    return "Ótimo esforço! Continue praticando!"


def _tw(text, font):
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def _text_h(font):
    bb = font.getbbox("Ay")
    return bb[3] - bb[1]


def _lh(font):
    return _text_h(font) + LINE_SP


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


def _draw_card_header(draw, card_x, row_y, title, title_font, badge_text, badge_font):
    """Desenha título + badge alinhados. Retorna y após o divider."""
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

    div_y = row_y + row_h + 16
    draw.line(
        [(card_x + CARD_PAD, div_y), (W - card_x - CARD_PAD, div_y)],
        fill=DIVIDER, width=2,
    )
    return div_y + 24


def _render_text_with_highlights(draw, start_x, start_y, text, highlight_set,
                                  font, font_bold, hl_color, hl_text_color,
                                  max_x, lh, sp, body_h):
    """
    Renderiza texto palavra por palavra com highlights.
    Usa _clean() para comparação robusta.
    Retorna y final (abaixo da última linha).
    """
    words = text.split()
    cx, cy = start_x, start_y

    for word in words:
        cleaned = _clean(word)
        ww = _tw(word, font)
        is_highlighted = cleaned in highlight_set and len(cleaned) > 0

        if is_highlighted:
            # Largura com padding
            hw = ww + HL_PAD_X * 2 + 4
            # Quebra de linha se não cabe
            if cx + hw > max_x:
                cx = start_x
                cy += lh
            # Retângulo highlight
            draw.rounded_rectangle(
                (cx, cy - HL_PAD_Y, cx + hw, cy + body_h + HL_PAD_Y),
                radius=10, fill=hl_color,
            )
            # Texto centralizado no highlight
            draw.text((cx + HL_PAD_X + 2, cy), word, font=font_bold, fill=hl_text_color)
            cx += hw + sp
        else:
            # Quebra de linha se não cabe
            if cx + ww > max_x:
                cx = start_x
                cy += lh
            draw.text((cx, cy), word, font=font, fill=TEXT_DARK)
            cx += ww + sp

    # Retorna y abaixo da última linha
    return cy + lh


def _measure_text_with_highlights(text, highlight_set, font, font_bold,
                                   start_x, max_x, lh, sp):
    """Mede a altura que o texto com highlights vai ocupar (sem desenhar)."""
    words = text.split()
    cx, cy = start_x, 0

    for word in words:
        cleaned = _clean(word)
        ww = _tw(word, font)
        is_highlighted = cleaned in highlight_set and len(cleaned) > 0

        if is_highlighted:
            hw = ww + HL_PAD_X * 2 + 4
            if cx + hw > max_x:
                cx = start_x
                cy += lh
            cx += hw + sp
        else:
            if cx + ww > max_x:
                cx = start_x
                cy += lh
            cx += ww + sp

    return cy + lh


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
    text_start_x = PAD + CARD_PAD
    text_max_x = PAD + ci

    HH = 360

    original = correction_data.get("original", "...")
    corrected = correction_data.get("corrected", "...")
    errors = correction_data.get("errors", [])[:5]
    encouragement = _to_portuguese(correction_data.get("encouragement", ""))
    err_count = len(errors)

    # Score
    total_words = len(original.split()) if original else 10
    score = max(0, min(100, int(100 - (err_count / max(total_words, 1)) * 100)))

    # Highlight sets (comparação robusta)
    wrong_set = _build_highlight_set(errors, "wrong")
    right_set = _build_highlight_set(errors, "right")

    sol_word = "soluções" if err_count != 1 else "solução"

    lh = _lh(f_body)
    sp = _tw(" ", f_body)
    body_h = _text_h(f_body)

    # ── Medir alturas reais dos textos ──
    card_header_h = 80  # título + badge + divider + padding
    card_bottom_pad = CARD_PAD

    text1_h = _measure_text_with_highlights(
        original, wrong_set, f_body, f_body_b, text_start_x, text_max_x, lh, sp,
    )
    c1h = card_header_h + text1_h + card_bottom_pad

    text2_h = _measure_text_with_highlights(
        corrected, right_set, f_body, f_body_b, text_start_x, text_max_x, lh, sp,
    )
    c2h = card_header_h + text2_h + card_bottom_pad

    # Altura total
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

    # ── Card 1: Pronúncia ──
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

    _render_text_with_highlights(
        draw, text_start_x, cy,
        original, wrong_set,
        f_body, f_body_b,
        HIGHLIGHT_YELLOW, TEXT_DARK,
        text_max_x, lh, sp, body_h,
    )

    y += c1h + 36

    # ── Card 2: Como melhorar ──
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

    _render_text_with_highlights(
        draw, text_start_x, cy,
        corrected, right_set,
        f_body, f_body_b,
        HIGHLIGHT_GREEN, ACCENT_GREEN,
        text_max_x, lh, sp, body_h,
    )

    y += c2h + 44

    # ── Encorajamento (português, limitado pra não passar da imagem) ──
    if encouragement:
        # Limita a 50 caracteres
        if len(encouragement) > 50:
            encouragement = encouragement[:47] + "..."
        # Usa wrap pra garantir que não passa da largura
        enc_max_w = cw - 20
        enc_lines = []
        cur = ""
        for word in encouragement.split():
            test = f"{cur} {word}".strip()
            if _tw(test, f_enc) <= enc_max_w:
                cur = test
            else:
                if cur:
                    enc_lines.append(cur)
                cur = word
        if cur:
            enc_lines.append(cur)
        for line in enc_lines:
            draw.text((PAD, y), line, font=f_enc, fill=ACCENT_PURPLE)
            y += _lh(f_enc)

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
