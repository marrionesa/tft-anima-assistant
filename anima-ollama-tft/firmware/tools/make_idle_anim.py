#!/usr/bin/env python3
"""Genera el salvapantallas de reposo de ANIMA para la TFT ST7735 (160x128).

Entrada : firmware/assets/anima_reposo_base.png  (imagen base limpia, 480x270)
Salida  : firmware/src/idle_anim.h               (8 frames RLE en PROGMEM)
          firmware/assets/preview_tft.gif        (vista previa ampliada x3)

La animación original (GIF de 8,4 MB) parpadea a nivel de píxel; en una
ESP8266 eso no cabe en flash ni en RAM. Aquí sintetizamos el mismo efecto
con 8 niveles de brillo de un único cuadro, comprimidos en RLE: el resultado
pesa ~20 KB y el bucle corre sin tocar la red.

Uso:  python3 firmware/tools/make_idle_anim.py
Requiere Pillow.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[3]   # tools/ → firmware/ → anima-ollama-tft/ → raíz
ASSETS = ROOT / "anima-ollama-tft" / "firmware" / "assets"
SRC = ASSETS / "anima_reposo_base.png"
OUT_H = ROOT / "anima-ollama-tft" / "firmware" / "src" / "idle_anim.h"
OUT_PREVIEW = ASSETS / "preview_tft.gif"

TFT_W, TFT_H = 160, 128
AMP = 0.38          # amplitud del pulso de neón (0.0-1.0)

# Paleta de marca (la misma del panel de la PWA)
TEAL = (53, 230, 206)
MINT = (154, 247, 233)
BG = (4, 15, 19)
HEADER = (12, 42, 47)


def load_base() -> Image.Image:
    """Recorta la base a la relación 5:4 del panel y escala a 160x128."""
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    target_ratio = TFT_W / TFT_H
    src_ratio = w / h
    if src_ratio > target_ratio:              # demasiado ancha: recortar lados
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        im = im.crop((x0, 0, x0 + new_w, h))
    else:                                     # demasiado alta: recortar arriba/abajo
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        im = im.crop((0, y0, w, y0 + new_h))
    return im.resize((TFT_W, TFT_H), Image.LANCZOS)


def compose(frame: Image.Image) -> Image.Image:
    """Añade la cabecera HUD y el badge LOCAL, como en el GIF original."""
    frame = frame.copy()
    d = ImageDraw.Draw(frame)

    # Barra superior con el rótulo ANIMA
    d.rectangle((0, 0, TFT_W - 1, 13), fill=(2, 10, 13))
    d.line((0, 13, TFT_W - 1, 13), fill=(23, 94, 92), width=1)
    d.rectangle((0, 0, TFT_W - 1, TFT_H - 1), outline=(16, 66, 64), width=1)

    font = ImageFont.load_default()
    d.text((6, 3), "ANIMA", font=font, fill=MINT)
    d.text((6, 3), "ANIMA", font=font, fill=MINT)   # doble pasada = más brillo

    # Badge LOCAL + icono wifi arriba a la derecha
    label = "LOCAL"
    lw = d.textlength(label, font=font)
    d.text((TFT_W - lw - 18, 3), label, font=font, fill=MINT)
    # wifi (3 arcos simplificados)
    cx, cy = TFT_W - 9, 9
    for r, alpha in ((5, 255), (3, 230), (1, 210)):
        d.arc((cx - r, cy - r, cx + r, cy + r), start=215, end=325,
              fill=(100, 240, 220) if alpha > 240 else (70, 200, 190), width=1)
    d.point((cx, cy + 1), fill=(150, 250, 235))
    return frame


def glow_variant(frame: Image.Image, factor: float) -> Image.Image:
    """Devuelve el cuadro con el neón a otro nivel de brillo.

    factor 1.0 = brillo base. Por debajo atenúa, por encima intensifica.
    El glow se aplica sobre todo a los píxeles claros (los trazos), no al fondo.
    """
    if abs(factor - 1.0) < 1e-4:
        return frame
    img = frame.convert("RGB")
    # brillo del píxel normalizado: 0 fondo, 1 trazo
    lum = img.convert("L")
    # gamma para concentrar el efecto en los trazos
    mask = lum.point(lambda v: int(255 * ((v / 255) ** 1.6)))
    if factor > 1.0:
        # intensificar: mezclar el trazo hacia blanco-menta
        overlay = Image.new("RGB", img.size, (210, 255, 246))
        return Image.composite(Image.blend(img, overlay, min(0.55, (factor - 1) * 1.4)),
                               img, mask)
    # atenuar: oscurecer hacia el fondo
    dark = Image.new("RGB", img.size, (0, 4, 6))
    return Image.composite(Image.blend(img, dark, min(0.72, (1 - factor) * 1.5)),
                           img, mask)


def to_rgb565(img: Image.Image) -> list[list[int]]:
    """Cuantización por zonas + RGB565.

    Tres zonas con fidelidad distinta (la clave para que el RLE muerda):
      · Franjas de texto (header y badge): cuantización fina — el texto antialiasado
        se destruye con pasos gruesos y es lo primero que lee el ojo.
      · Trazos del neón: pasos de 16 — el glow se degrada con suavidad.
      · Fondo (textura HUD del GIF): pasos de 48 — solo aporta textura.
    Sin dithering a propósito: a 1,8" el patrón se notaría más que el degradado que salva.
    """
    im = img.convert("RGB")
    im = im.filter(ImageFilter.MedianFilter(3))
    a = np.asarray(im).astype(np.int16)
    g = a[:, :, 1]
    r = a[:, :, 0]
    stroke = (g > 60) & (g > r + 20)

    # Zonas de texto: header completo y esquina superior derecha (badge+wifi).
    text_zone = np.zeros((TFT_H, TFT_W), dtype=bool)
    text_zone[0:15, :] = True
    text_zone[0:15, TFT_W - 66:] = True      # doble cobertura, harmless

    a2 = a.copy()
    # Fondo: grueso
    bg = ~stroke & ~text_zone
    a2[bg] = (a2[bg] // 48) * 48
    # Trazo: medio
    st = stroke & ~text_zone
    a2[st] = (a2[st] // 16) * 16
    # Texto: fino (pasos de 6)
    a2[text_zone] = (a2[text_zone] // 6) * 6
    im = Image.fromarray(a2.astype(np.uint8))

    px = im.load()
    rows: list[list[int]] = []
    for y in range(TFT_H):
        row: list[int] = []
        for x in range(TFT_W):
            r, g, b = px[x, y]
            row.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
        rows.append(row)
    return rows


def rle_encode(rows: list[list[int]]) -> tuple[bytes, int]:
    """RLE por filas: (run: uint8, color: uint16 LE)*. Devuelve (datos, n_runs)."""
    out = bytearray()
    runs = 0
    for row in rows:
        x = 0
        while x < TFT_W:
            color = row[x]
            n = 1
            while x + n < TFT_W and row[x + n] == color and n < 255:
                n += 1
            out.append(n)
            out += struct.pack("<H", color)
            runs += 1
            x += n
    return bytes(out), runs


# Curva de respiración: 4 niveles (sube y baja simétrico) ahorrando flash.
WAVE = [0.82, 1.0, 1.14, 1.0]
LEVELS = len(WAVE)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        raise SystemExit(
            f"Falta {SRC}. Genera la imagen base con el GIF original "
            "(promedio de todos los frames) y guárdala ahí."
        )

    base = compose(load_base())
    base.save(ASSETS / "base_160.png")

    # ── Generar los 8 niveles ─────────────────────────────────────────────
    frames_rows: list[list[list[int]]] = []
    total = 0
    runs_total = 0
    for level in range(LEVELS):
        factor = WAVE[level]
        img = glow_variant(base, factor)
        rows = to_rgb565(img)
        data, runs = rle_encode(rows)
        frames_rows.append(rows)
        total += len(data)
        runs_total += runs
        print(f"  nivel {level}: factor {factor:.2f}  RLE {len(data)/1024:.1f} KB ({runs} runs)")

    print(f"TOTAL RLE: {total/1024:.1f} KB en {LEVELS} cuadros ({runs_total} runs)")

    # ── Escribir el header C ──────────────────────────────────────────────
    lines: list[str] = []
    lines.append("#pragma once")
    lines.append("//")
    lines.append("// Salvapantallas de reposo de ANIMA · generado por tools/make_idle_anim.py")
    lines.append("// NO EDITAR A MANO: regenerar con  python3 firmware/tools/make_idle_anim.py")
    lines.append("//")
    lines.append(f"// {LEVELS} cuadros 160x128 RGB565 comprimidos en RLE (run uint8 + color uint16 LE).")
    lines.append(f"// Total: {total} bytes de datos + {LEVELS} índices.")
    lines.append("//")
    lines.append("#include <Arduino.h>")
    lines.append("")
    lines.append(f"#define IDLE_W {TFT_W}")
    lines.append(f"#define IDLE_H {TFT_H}")
    lines.append(f"#define IDLE_FRAMES {LEVELS}")
    lines.append("// ms por cuadro: ciclo completo ≈ (IDLE_FRAME_MS * IDLE_FRAMES) / 1000 s")
    lines.append("#define IDLE_FRAME_MS 170")
    lines.append("")
    for i, (rows, ) in enumerate([ (r,) for r in frames_rows ]):
        data, _runs = rle_encode(rows)
        hexbytes = ",".join(f"0x{b:02X}" for b in data)
        # Trocear por tokens completos (nunca a mitad de un 0xNN): un corte
        # ciego produce "0xE7,," y el compilador lo rechaza.
        limit = 98
        chunks: list[str] = []
        line = ""
        for token in hexbytes.split(","):
            piece = token if not line else "," + token
            if len(line) + len(piece) > limit:
                chunks.append(line)
                line = token
            else:
                line += piece
        if line:
            chunks.append(line)
        lines.append(f"static const uint8_t idleFrame{i}[] PROGMEM = {{")
        for c in chunks:
            lines.append(f"  {c},")
        lines.append("};")
        lines.append("")
    lines.append("static const uint8_t* const idleFrames[IDLE_FRAMES] PROGMEM = {")
    for i in range(LEVELS):
        lines.append(f"  idleFrame{i},")
    lines.append("};")
    lines.append(f"static const uint16_t idleFrameLen[IDLE_FRAMES] PROGMEM = {{")
    for i in range(LEVELS):
        _, r = rle_encode(frames_rows[i])
        data_len = len(rle_encode(frames_rows[i])[0])
        lines.append(f"  {data_len},")
    lines.append("};")
    lines.append("")
    OUT_H.write_text("\n".join(lines), encoding="utf-8")
    print(f"escrito {OUT_H.relative_to(ROOT)} ({OUT_H.stat().st_size/1024:.1f} KB)")

    # ── Vista previa ampliada ─────────────────────────────────────────────
    preview_frames = []
    for level in range(LEVELS):
        f = glow_variant(base, WAVE[level]).convert("RGB")
        preview_frames.append(f)
    preview_frames[0].save(
        OUT_PREVIEW, save_all=True, append_images=preview_frames[1:],
        duration=170, loop=0,
    )
    print(f"vista previa {OUT_PREVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
