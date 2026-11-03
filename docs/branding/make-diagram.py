#!/usr/bin/env python3
"""Regenera docs/branding/arquitectura.png con la paleta oficial de ANIMA.

Uso:  python3 docs/branding/make-diagram.py
Requiere Pillow (ya presente en el sistema).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "branding" / "arquitectura.png"

# ── Paleta oficial (extraída de static/index.html y del wallpaper) ─────────
BG = "#00151c"
PANEL = "#052027"
PANEL_HI = "#072a31"
BORDER = "#123f45"
TEAL = "#35e6ce"
MINT = "#9af7e9"
TEXT = "#e8fffb"
MUTED = "#7fa8a4"
DIM = "#557d7a"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


W, H = 1600, 880
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

F_TITLE = font(FONT_BOLD, 46)
F_SUB = font(FONT_REG, 21)
F_LABEL = font(FONT_MONO_B, 17)
F_BOX = font(FONT_BOLD, 25)
F_CHIP = font(FONT_MONO_B, 17)
F_BODY = font(FONT_REG, 18)
F_MONO = font(FONT_MONO, 17)
F_MONO_B = font(FONT_MONO_B, 17)
F_NOTE = font(FONT_REG, 17)

overflow: list[str] = []


def text(xy, s, f, fill, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)
    return xy[0] + d.textlength(s, font=f)


def check(label, x_end, limit):
    if x_end > limit:
        overflow.append(f"{label}: {x_end:.0f} > {limit}")


def box(x0, y0, x1, y1, hi=False):
    d.rounded_rectangle(
        (x0, y0, x1, y1), radius=16,
        fill=PANEL_HI if hi else PANEL, outline=BORDER, width=2,
    )


def chip(x, y, label, color=TEAL):
    """Etiqueta de puerto con fondo tenue."""
    pad_x, pad_y = 10, 5
    f = F_CHIP
    tw = d.textlength(label, font=f)
    th = f.size
    d.rounded_rectangle(
        (x, y, x + tw + pad_x * 2, y + th + pad_y * 2),
        radius=7, fill="#0a3b3d", outline="#1a5a58", width=1,
    )
    d.text((x + pad_x, y + pad_y - 1), label, font=f, fill=color)
    return x + tw + pad_x * 2


def arrow_h(x0, x1, y, dashed=False, color=TEAL):
    """Flecha horizontal con punta a la derecha."""
    head = 11
    end = x1 - head
    if dashed:
        x = x0
        while x < end:
            d.line((x, y, min(x + 9, end), y), fill=color, width=2)
            x += 16
    else:
        d.line((x0, y, end, y), fill=color, width=2)
    d.polygon([(x1, y), (end, y - 7), (end, y + 7)], fill=color)


# ── Encabezado ────────────────────────────────────────────────────────────
xe = text((72, 52), "ANIMA", F_TITLE, TEAL)
xe = text((xe + 14, 52), "· arquitectura local", F_TITLE, "#2f6f6d")
text((74, 116), "Sin nube, sin claves de API: el modelo, la voz y el firmware viven en tu red.",
     F_SUB, MUTED)
d.line((72, 168, W - 72, 168), fill=BORDER, width=2)

# ── Etiquetas de columna ──────────────────────────────────────────────────
text((80, 200), "CLIENTES", F_LABEL, DIM)
text((520, 200), "NÚCLEO", F_LABEL, DIM)
text((1020, 200), "SERVICIOS LOCALES", F_LABEL, DIM)

# ── Columna 1: clientes ───────────────────────────────────────────────────
CA0, CA1 = 80, 430
box(CA0, 250, CA1, 410)
xe = text((CA0 + 22, 272), "PWA", F_BOX, TEXT)
text((CA0 + 22 + d.textlength("PWA", font=F_BOX) + 12, 278), "móvil · escritorio", F_BODY, MUTED)
text((CA0 + 22, 312), "Chat + micrófono + voz", F_BODY, "#bfe6e0")
text((CA0 + 22, 340), "Historial local (100 msgs)", F_MONO, MUTED)
text((CA0 + 22, 366), "Instalable · offline shell", F_MONO, MUTED)

box(CA0, 480, CA1, 640)
text((CA0 + 22, 502), "NodeMCU ESP8266", F_BOX, TEXT)
text((CA0 + 22, 542), "TFT ST7735 1.8\" · 160×128", F_BODY, "#bfe6e0")
text((CA0 + 22, 570), "Renderiza estado y respuesta", F_MONO, MUTED)
text((CA0 + 22, 596), "vía JSON por WebSocket", F_MONO, MUTED)

# ── Columna 2: Chat API ───────────────────────────────────────────────────
CB0, CB1 = 520, 930
box(CB0, 250, CB1, 750, hi=True)
text((CB0 + 24, 274), "Chat API", F_BOX, MINT)
chip(CB0 + 24 + d.textlength("Chat API", font=F_BOX) + 14, 278, ":8000")
text((CB0 + 24, 316), "FastAPI + Uvicorn · sin estado", F_BODY, MUTED)
d.line((CB0 + 24, 352, CB1 - 24, 352), fill=BORDER, width=1)

rows = [
    ("POST", "/api/chat", "→ Ollama"),
    ("POST", "/api/voice/transcribe", "→ ASR"),
    ("POST", "/api/voice/speak", "→ TTS"),
    ("GET", "/health", "estado"),
    ("WS", "/ws", "push TFT"),
]
y = 376
for method, path, note in rows:
    mc = TEAL if method in ("POST", "WS") else MUTED
    text((CB0 + 24, y), method, F_MONO_B, mc)
    text((CB0 + 88, y), path, F_MONO, TEXT)
    text((CB1 - 24, y), note, F_MONO, DIM, anchor="ra")
    y += 40

d.line((CB0 + 24, 586, CB1 - 24, 586), fill=BORDER, width=1)
text((CB0 + 24, 606), "Un solo modelo ⇒ peticiones", F_MONO, MUTED)
text((CB0 + 24, 630), "serializadas con un lock.", F_MONO, MUTED)
text((CB0 + 24, 672), "Broadcast a la TFT:", F_MONO, "#bfe6e0")
# Las etiquetas JSON tienen anchos distintos: la descripción se alinea
# al ancho de la más larga para que no se solapen.
desc_x = CB0 + 34 + max(
    d.textlength(f'"{k}"', font=F_MONO) for k, _ in [("status", 0), ("response", 0)]
) + 18
for i, (kind, desc) in enumerate([("status", "thinking / connected"), ("response", "texto renderizado")]):
    yy = 700 + i * 24
    text((CB0 + 34, yy), f'"{kind}"', F_MONO, TEAL)
    text((desc_x, yy), desc, F_MONO, MUTED)

# ── Columna 3: servicios ──────────────────────────────────────────────────
CC0, CC1 = 1020, 1528
box(CC0, 250, CC1, 450)
text((CC0 + 24, 274), "Voice API", F_BOX, MINT)
chip(CC0 + 24 + d.textlength("Voice API", font=F_BOX) + 14, 278, ":8001")
text((CC0 + 24, 316), "FastAPI · solo loopback", F_BODY, MUTED)
d.line((CC0 + 24, 352, CC1 - 24, 352), fill=BORDER, width=1)
text((CC0 + 24, 374), "faster-whisper", F_MONO_B, TEAL)
text((CC0 + 190, 374), "ASR · es · small", F_MONO, MUTED)
text((CC0 + 24, 406), "Piper", F_MONO_B, TEAL)
text((CC0 + 190, 406), "TTS · es_ES-sharvard", F_MONO, MUTED)

box(CC0, 540, CC1, 740)
text((CC0 + 24, 564), "Ollama", F_BOX, MINT)
chip(CC0 + 24 + d.textlength("Ollama", font=F_BOX) + 14, 568, ":11434")
text((CC0 + 24, 606), "Runtime LLM · solo loopback", F_BODY, MUTED)
d.line((CC0 + 24, 642, CC1 - 24, 642), fill=BORDER, width=1)
text((CC0 + 24, 662), "qwen2.5-coder:14b", F_MONO_B, TEAL)
text((CC0 + 24, 694), "Modelo y timeout en server/.env", F_MONO, MUTED)

# ── Conexiones ────────────────────────────────────────────────────────────
arrow_h(CA1 + 6, CB0 - 6, 330)
text(((CA1 + CB0) // 2, 306), "HTTP", F_MONO, TEAL, anchor="ma")

arrow_h(CA1 + 6, CB0 - 6, 560, dashed=True)
text(((CA1 + CB0) // 2, 536), "WS", F_MONO, TEAL, anchor="ma")

arrow_h(CB1 + 6, CC0 - 6, 350)
text(((CB1 + CC0) // 2, 326), "HTTP", F_MONO, TEAL, anchor="ma")

arrow_h(CB1 + 6, CC0 - 6, 640)
text(((CB1 + CC0) // 2, 616), "HTTP", F_MONO, TEAL, anchor="ma")

# ── Pie ───────────────────────────────────────────────────────────────────
d.line((72, 786, W - 72, 786), fill=BORDER, width=2)
text((72, 806), "11434 y 8001 escuchan solo en 127.0.0.1.", F_NOTE, MUTED)
text((72, 832), "El móvil habla únicamente con el puerto 8000.", F_NOTE, MUTED)
text((W - 72, 806), "Todas las piezas: software libre y local", F_NOTE, DIM, anchor="ra")
text((W - 72, 832), "ANIMA · asistente personal local", F_NOTE, DIM, anchor="ra")

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, optimize=True)
print(f"ok → {OUT.relative_to(ROOT)}  {img.size[0]}x{img.size[1]}")
if overflow:
    print("DESBORDES DETECTADOS:")
    for item in overflow:
        print("  -", item)
else:
    print("sin desbordes de texto")
