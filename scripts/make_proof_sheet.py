#!/usr/bin/env python3
"""Render a full proof sheet (one PNG per weight) of every accented/composite
letter in the built TTFs, in a labeled grid, so positioning can be eyeballed.

Run with the container's system python3 (has PIL + fontTools):
    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        python3 /work/scripts/make_proof_sheet.py
"""
import os, unicodedata
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

TTF = "/work/out/ttf"
OUT = "/work/proofs"
WEIGHTS = ["Regular", "Bold", "Italic", "BoldItalic"]

COLS = 14
CELL_W, CELL_H = 96, 116
GLYPH_PX = 64
PAD_TOP = 70


def accented_codepoints(ttf_path):
    cmap = TTFont(ttf_path).getBestCmap()
    out = []
    for cp in sorted(cmap):
        ch = chr(cp)
        if not unicodedata.category(ch).startswith("L"):
            continue
        nfd = unicodedata.normalize("NFD", ch)
        if nfd != ch and len(nfd) >= 2:
            out.append(cp)
    return out


def render(weight):
    path = os.path.join(TTF, "Libron IV-%s.ttf" % weight)
    cps = accented_codepoints(path)
    glyph_font = ImageFont.truetype(path, GLYPH_PX)
    title_font = ImageFont.truetype(path, 34)
    label_font = ImageFont.load_default()

    rows = (len(cps) + COLS - 1) // COLS
    W = COLS * CELL_W + 40
    H = PAD_TOP + rows * CELL_H + 30
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), "Libron IV %s  -  %d accented glyphs" % (weight, len(cps)),
           font=title_font, fill="black")

    for i, cp in enumerate(cps):
        r, c = divmod(i, COLS)
        x = 20 + c * CELL_W
        y = PAD_TOP + r * CELL_H
        d.rectangle([x, y, x + CELL_W - 4, y + CELL_H - 4], outline="#e8e8e8")
        # baseline guide
        base_y = y + 86
        d.line([(x + 6, base_y), (x + CELL_W - 10, base_y)], fill="#f0e0e0")
        ch = chr(cp)
        bb = d.textbbox((0, 0), ch, font=glyph_font)
        gx = x + (CELL_W - 4 - (bb[2] - bb[0])) / 2 - bb[0]
        d.text((gx, base_y - GLYPH_PX), ch, font=glyph_font, fill="black")
        d.text((x + 5, y + CELL_H - 16), "U+%04X" % cp, font=label_font, fill="#aaa")

    os.makedirs(OUT, exist_ok=True)
    out_path = os.path.join(OUT, "sheet_%s.png" % weight)
    img.save(out_path)
    print("wrote %s  (%d glyphs, %d rows)" % (out_path, len(cps), rows))


for w in WEIGHTS:
    render(w)
