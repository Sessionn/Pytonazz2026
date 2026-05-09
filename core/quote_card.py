"""
core/quote_card.py  —  Quote card noir 2K

Zero dipendenze extra: solo Pillow + httpx (stdlib Python).
Veloce, stabile, operativo.

Risoluzione: 2560 x 1080 px, 144 DPI
Dipendenze: Pillow, httpx
"""
from __future__ import annotations

import asyncio
import io
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise ImportError("pip install Pillow")

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

# ── Dimensioni ────────────────────────────────────────────────────────────
_W, _H = 2560, 1080
_PAD   = 110
_AV_W  = int(_W * 0.40)

# ── Palette B&W noir ───────────────────────────────────────────────────────
_BG     = (5,   5,   5)
_TEXT_Q = (240, 240, 240)
_TEXT_N = (190, 190, 190)
_QM_COL = (255, 255, 255)
_SEP_A  = (180, 180, 180)
_SEP_B  = (10,  10,  10)
_BORDER = (60,  60,  60)

# ── Font paths ─────────────────────────────────────────────────────────────
_SERIF_PATHS = [
    "C:/Windows/Fonts/georgia.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
]
_SERIF_B_PATHS = [
    "C:/Windows/Fonts/georgiab.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]
_SANS_B_PATHS = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


@lru_cache(maxsize=16)
def _font(path_tuple: tuple, size: int) -> ImageFont.FreeTypeFont:
    """Caricamento font cachato: il disco viene letto una sola volta per dimensione."""
    for p in path_tuple:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _get_fonts():
    return (
        _font(tuple(_SERIF_B_PATHS), 200),  # virgolette
        _font(tuple(_SERIF_PATHS),    72),  # corpo testo
        _font(tuple(_SANS_B_PATHS),   46),  # nome autore
    )


# ── Fetch avatar + cover-fit LANCZOS ───────────────────────────────────────
async def _fetch_avatar(url: str) -> Optional[Image.Image]:
    if not _HAS_HTTPX or not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return None
        src    = Image.open(io.BytesIO(r.content)).convert("RGB")
        sw, sh = src.size
        scale  = max(_AV_W / sw, _H / sh)
        nw, nh = int(sw * scale), int(sh * scale)
        src    = src.resize((nw, nh), Image.LANCZOS)
        left   = (nw - _AV_W) // 2
        top    = (nh - _H)    // 2
        return src.crop((left, top, left + _AV_W, top + _H))
    except Exception:
        return None


# ── Fade mask: bytearray 1D -> broadcast via bytes*H -> Image.frombuffer ──────
# Nessun loop Python su pixel: la replica delle righe è un'op C (bytes multiply).
@lru_cache(maxsize=4)
def _fade_mask(fade_start_pct: int = 28) -> Image.Image:
    start_x = (_AV_W * fade_start_pct) // 100
    fade_w  = _AV_W - start_x
    row = bytearray(_AV_W)                       # default 0
    for x in range(start_x, _AV_W):
        t      = (x - start_x) / fade_w
        row[x] = int((t ** 1.9) * 255)
    data = bytes(row) * _H                       # replica C-level
    return Image.frombuffer("L", (_AV_W, _H), data)


# ── Linea gradiente orizzontale ────────────────────────────────────────────
def _grad_line(draw: ImageDraw.ImageDraw,
               x0: int, y: int, x1: int, thick: int,
               c1: tuple, c2: tuple):
    span = x1 - x0
    for i in range(span):
        t = i / max(1, span - 1)
        r = int(c1[0] + (c2[0]-c1[0]) * t)
        g = int(c1[1] + (c2[1]-c1[1]) * t)
        b = int(c1[2] + (c2[2]-c1[2]) * t)
        draw.line([(x0+i, y), (x0+i, y+thick-1)], fill=(r, g, b))


# ── Word-wrap Unicode-safe ────────────────────────────────────────────────────
def _wrap(text: str, font: ImageFont.FreeTypeFont,
          draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    """Wrap per parola (latino/greco/cirillico/arabo) o per carattere (CJK)."""
    if " " not in text:
        # CJK e lingue senza spazi: wrap carattere per carattere
        lines, cur = [], ""
        for ch in text:
            test = cur + ch
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = ch
        if cur: lines.append(cur)
        return lines
    words, lines, cur = text.split(" "), [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    return lines


# ── Entry point ─────────────────────────────────────────────────────────────
async def build_quote_card(
    text: str,
    author: str = "",
    avatar_url: str = "",
    server_name: str = "",   # mantenuto per compatibilità, non usato
) -> bytes:
    loop = asyncio.get_running_loop()

    # Avatar scaricato in async + mask precalcolata (cachata dopo la prima volta)
    avatar, fade_mask = await asyncio.gather(
        _fetch_avatar(avatar_url),
        loop.run_in_executor(None, _fade_mask, 28),
    )

    def _render() -> bytes:
        f_qm, f_body, f_name = _get_fonts()    # dal cache, 0 I/O

        img = Image.new("RGB", (_W, _H), _BG)

        if avatar:
            img.paste(avatar, (0, 0))
            black_over = Image.new("RGB", (_W, _H), _BG)
            full_mask  = Image.new("L", (_W, _H), 255)
            full_mask.paste(fade_mask, (0, 0))
            img = Image.composite(black_over, img, full_mask)

        draw = ImageDraw.Draw(img)

        # Bordo card
        draw.rounded_rectangle([3, 3, _W-4, _H-4],
                                radius=28, outline=_BORDER, width=2)

        tx0 = int(_W * 0.44)
        tw  = _W - tx0 - _PAD

        # Virgoletta apertura
        draw.text((tx0, _PAD - 44), "\u201c", font=f_qm, fill=_QM_COL)

        # Corpo testo centrato verticalmente
        lh      = 100
        lines   = _wrap(text.strip(), f_body, draw, tw)
        block_h = len(lines) * lh
        t_top   = _PAD + 130
        t_bot   = _H - _PAD - 180
        ty      = t_top + max(0, (t_bot - t_top - block_h) // 2)
        for line in lines:
            draw.text((tx0, ty), line, font=f_body, fill=_TEXT_Q)
            ty += lh

        # Virgoletta chiusura
        qm_bb = draw.textbbox((0, 0), "\u201d", font=f_qm)
        draw.text((_W - _PAD - (qm_bb[2]-qm_bb[0]), ty - lh - 20),
                  "\u201d", font=f_qm, fill=_QM_COL)

        # Separatore
        sep_y = _H - _PAD - 140
        _grad_line(draw, tx0, sep_y, _W - _PAD, 2, _SEP_A, _SEP_B)

        # Nome autore
        if author:
            draw.text((tx0, sep_y + 24), f"\u2014 {author}",
                      font=f_name, fill=_TEXT_N)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, dpi=(144, 144))
        return buf.getvalue()

    return await loop.run_in_executor(None, _render)
