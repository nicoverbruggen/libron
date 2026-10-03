#!/usr/bin/env python3
"""Generate README SVGs from built TTFs, using HarfBuzz for OpenType shaping.

Run in fntbld-oci after building: python3 scripts/generate_specimens.py
The SVGs contain outlines, so image viewers do not need Libron installed.
"""

import argparse
import ctypes as ct
from ctypes.util import find_library
from contextlib import ExitStack
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
STYLES = ("Regular", "Italic", "Bold", "BoldItalic")
PAPER = "#faf9f7"
INK = "#252525"
ACCENT = "#b34d71"


class GlyphInfo(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ("codepoint", "mask", "cluster", "var1", "var2")]


class GlyphPosition(ct.Structure):
    _fields_ = [(name, ct.c_int32) for name in
                ("x_advance", "y_advance", "x_offset", "y_offset", "var")]


class Feature(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in ("tag", "value", "start", "end")]


def harfbuzz():
    library = find_library("harfbuzz")
    if not library:
        raise RuntimeError("HarfBuzz is required. Run this script in fntbld-oci.")
    hb = ct.CDLL(library)
    pointer = ct.c_void_p
    signatures = {
        "blob_create_from_file_or_fail": (pointer, [ct.c_char_p]),
        "face_create": (pointer, [pointer, ct.c_uint]),
        "font_create": (pointer, [pointer]),
        "ot_font_set_funcs": (None, [pointer]),
        "font_set_scale": (None, [pointer, ct.c_int, ct.c_int]),
        "buffer_create": (pointer, []),
        "buffer_add_utf8": (None, [pointer, ct.c_char_p, ct.c_int, ct.c_uint, ct.c_int]),
        "buffer_guess_segment_properties": (None, [pointer]),
        "language_from_string": (pointer, [ct.c_char_p, ct.c_int]),
        "buffer_set_language": (None, [pointer, pointer]),
        "feature_from_string": (ct.c_int, [ct.c_char_p, ct.c_int, ct.POINTER(Feature)]),
        "shape": (None, [pointer, pointer, ct.POINTER(Feature), ct.c_uint]),
        "buffer_get_glyph_infos": (ct.POINTER(GlyphInfo), [pointer, ct.POINTER(ct.c_uint)]),
        "buffer_get_glyph_positions": (ct.POINTER(GlyphPosition), [pointer, ct.POINTER(ct.c_uint)]),
    }
    for resource in ("blob", "face", "font", "buffer"):
        signatures[f"{resource}_destroy"] = (None, [pointer])
    for name, (result, arguments) in signatures.items():
        function = getattr(hb, f"hb_{name}")
        function.restype = result
        function.argtypes = arguments
    return hb


class Font:
    def __init__(self, path, hb, resources):
        self.tt = resources.enter_context(TTFont(path))
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.upm = self.tt["head"].unitsPerEm
        self.hb = hb
        blob = hb.hb_blob_create_from_file_or_fail(str(path).encode())
        if not blob:
            raise RuntimeError(f"Cannot load font: {path}")
        resources.callback(hb.hb_blob_destroy, blob)
        face = hb.hb_face_create(blob, 0)
        resources.callback(hb.hb_face_destroy, face)
        self.font = hb.hb_font_create(face)
        resources.callback(hb.hb_font_destroy, self.font)
        hb.hb_ot_font_set_funcs(self.font)
        hb.hb_font_set_scale(self.font, self.upm, self.upm)

    def shape(self, text, features=(), language="en"):
        hb = self.hb
        buffer = hb.hb_buffer_create()
        try:
            encoded = text.encode("utf-8")
            hb.hb_buffer_add_utf8(buffer, encoded, len(encoded), 0, len(encoded))
            hb.hb_buffer_set_language(buffer, hb.hb_language_from_string(language.encode(), -1))
            hb.hb_buffer_guess_segment_properties(buffer)
            settings = (Feature * len(features))()
            for i, setting in enumerate(features):
                if not hb.hb_feature_from_string(setting.encode(), -1, ct.byref(settings[i])):
                    raise ValueError(f"Invalid OpenType feature: {setting}")
            hb.hb_shape(self.font, buffer, settings, len(settings))
            count = ct.c_uint()
            infos = hb.hb_buffer_get_glyph_infos(buffer, ct.byref(count))
            positions = hb.hb_buffer_get_glyph_positions(buffer, ct.byref(count))
            glyphs = []
            for i in range(count.value):
                if infos[i].codepoint == 0:
                    raise ValueError(f"Missing glyph in {text!r}")
                p = positions[i]
                glyphs.append((infos[i].codepoint, p.x_advance, p.y_advance, p.x_offset, p.y_offset))
            return glyphs
        finally:
            hb.hb_buffer_destroy(buffer)

    def width(self, text, size, **options):
        return sum(g[1] for g in self.shape(text, **options)) * size / self.upm


class SVG:
    def __init__(self, fonts, width, height, title):
        self.fonts = fonts
        self.width = width
        self.height = height
        self.title = title
        self.definitions = {}
        self.elements = []
        self.rect(0, 0, width, height, PAPER)

    def rect(self, x, y, width, height, fill):
        self.elements.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}"/>')

    def text(self, text, x, y, size, style="Regular", fill=INK, **options):
        font = self.fonts[style]
        scale = size / font.upm
        self.elements.append(f'<g fill="{fill}" aria-label={quoteattr(text)}><title>{escape(text)}</title>')
        for gid, advance, vertical, dx, dy in font.shape(text, **options):
            name = font.order[gid]
            key = (style, gid)
            if key not in self.definitions:
                pen = SVGPathPen(font.glyphs)
                font.glyphs[name].draw(pen)
                bounds = BoundsPen(font.glyphs)
                font.glyphs[name].draw(bounds)
                self.definitions[key] = (f"g{len(self.definitions)}", pen.getCommands(), bounds.bounds)
            identifier, path, bounds = self.definitions[key]
            gx, gy = x + dx * scale, y - dy * scale
            if bounds:
                left, bottom, right, top = bounds
                if gx + left * scale < 0 or gx + right * scale > self.width or gy - top * scale < 0 or gy - bottom * scale > self.height:
                    raise ValueError(f"Text outside SVG canvas: {text!r}")
            if path:
                self.elements.append(f'<use xlink:href="#{identifier}" transform="translate({gx:.3f} {gy:.3f}) scale({scale:.6f} {-scale:.6f})"/>')
            x += advance * scale
            y -= vertical * scale
        self.elements.append("</g>")
        return x

    def book_paragraph(self, runs, x, y, width, leading, indent=0, bottom=None):
        """Set mixed-size text with a first-line indent and justified lines.

        Each run is (text, size, OpenType features). Runs can join without a
        space, as the enlarged initial joins the opening small capitals.
        """
        import re

        font = self.fonts["Regular"]
        words = []
        for text, run_size, features in runs:
            for token in re.findall(r"\S+\s*", text):
                word = token.rstrip()
                space = font.width(" ", run_size) if token != word else 0
                words.append((word, run_size, features, font.width(word, run_size, features=features), space))

        def draw_line(line, baseline, inset, final):
            used = sum(word[3] + word[4] for word in line) - line[-1][4]
            spaces = sum(bool(word[4]) for word in line[:-1])
            extra = (width - inset - used) / spaces if spaces and not final else 0
            cursor = x + inset
            for i, (word, run_size, features, advance, space) in enumerate(line):
                self.text(word, cursor, baseline, run_size, features=features)
                cursor += advance
                if i < len(line) - 1:
                    cursor += space + (extra if space else 0)

        # Keep adjacent runs together when there is no space between them.
        # This prevents a comma or full stop wrapping away from a small cap.
        groups = []
        for word in words:
            if groups and not groups[-1][-1][4]:
                groups[-1].append(word)
            else:
                groups.append([word])

        line = []
        inset = indent
        for group in groups:
            candidate = line + group
            used = sum(item[3] + item[4] for item in candidate) - group[-1][4]
            if used > width - inset:
                group_width = sum(item[3] + item[4] for item in group) - group[-1][4]
                if not line or group_width > width:
                    raise ValueError(f"Word too wide: {group[0][0]!r}")
                if bottom is not None and y > bottom:
                    return y
                draw_line(line, y, inset, False)
                y += leading
                inset = 0
                line = group
            else:
                line = candidate
        if line:
            if bottom is not None and y > bottom:
                return y
            draw_line(line, y, inset, True)
            y += leading
        return y

    def save(self, path):
        definitions = "\n".join(f'<path id="{identifier}" d={quoteattr(commands)}/>' for identifier, commands, _ in self.definitions.values() if commands)
        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated by scripts/generate_specimens.py. Edit the script, then rebuild. -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" role="img" aria-labelledby="title">
<title id="title">{escape(self.title)}</title>
<defs>{definitions}</defs>
{chr(10).join(self.elements)}
</svg>
'''
        path.write_text(content, encoding="utf-8")
        print(f"  Generated {path}")


def specimen(fonts, family, version):
    svg = SVG(fonts, 800, 1040, f"{family} {version}: roman and italic specimen")
    version_text = f"v{version}"
    svg.text(version_text, 782 - fonts["Regular"].width(version_text, 29), 39, 29, fill="#b3b3b3")
    svg.text(family, 48, 174, 126, fill=ACCENT)
    svg.rect(55, 189, 395, 2.6, ACCENT)
    svg.text("A serif for reading", 53, 236, 45.5, fill=ACCENT)
    svg.text("Aa Gg Qq", 52, 426, 85.5, fill="black")
    svg.text("Aa Gg Qq", 52, 544, 85.5, "Italic", fill="black")
    svg.text("a", 534, 560, 365, fill="black")
    svg.rect(0, 692, 800, 348, ACCENT)
    svg.text("abcdefghijklm", 73, 800, 68, fill="white")
    svg.text("nopqrstuvwxyz", 73, 888, 68, fill="white")
    digits = "1234567890"
    svg.text(digits, 718 - fonts["Regular"].width(digits, 68), 980, 68, fill="white")
    return svg


def sample(fonts, family, version):
    # Public-domain prologue from Trevelyan's Type Tester. Keep the source text
    # and its small-cap spans intact; regeneration does not need network access.
    # https://github.com/nicoverbruggen/type-tester-epub/blob/main/src/OEBPS/prologue.xhtml
    # At 300 pixels per inch, this diagonal is approximately seven inches.
    svg = SVG(fonts, 1264, 1680, f"Trevelyan's Type Tester in {family} {version}, simulated 7-inch e-reader page")
    svg.rect(0, 0, 1264, 1680, "#fafafa")
    margin = 104
    text_width = svg.width - 2 * margin
    bottom = 1536

    def centred(text, y, size, style="Regular", **options):
        width = fonts[style].width(text, size, **options)
        svg.text(text, (svg.width - width) / 2, y, size, style, **options)

    centred("Prologue", 150, 30, features=("smcp=1", "c2sc=1"))
    centred("The Firm", 228, 56, "Bold")
    svg.rect(590, 278, 84, 1, INK)
    size = 36
    sc = ("smcp=1",)
    all_sc = ("smcp=1", "c2sc=1")
    y = svg.book_paragraph([
        ("T", size * 2.2, ()), ("revelyan & Co. ", size, sc),
        ("designed typefaces and, through its small-press division, published books set in them, an arrangement Mr. Trevelyan considered so obviously correct that he rarely bothered to defend it, in much the same way that he did not defend the usefulness of windows, decent tea, or the avoidance of badly spaced capitals.", size, ()),
    ], margin, 366, text_width, 50, bottom=bottom)
    paragraphs = [
        [("The firm occupied a building whose chief architectural distinction was that no one looking at it from the street would have guessed, correctly or otherwise, what went on inside, which suited Mr. Trevelyan perfectly well.", size, ())],
        [("Within were proofs pinned to walls, drawers full of rejected alphabets, invoices of uncertain legibility, and three machines named ", size, ()),
         ("AVATAR", size, all_sc), (", ", size, ()), ("TITAN", size, all_sc), (", and ", size, ()), ("YETI", size, all_sc),
         (". Mr. Trevelyan had chosen those names on a whim, with the remarkable optimism of someone who had never spent much time thinking about the implications of assigning the names of frightening creatures to large and temperamental machines.", size, ())],
        [("Mr. Trevelyan held, with unembarrassed seriousness, that type was not decoration but voice, and that a voice badly set was a kind of discourtesy.", size, ())],
        [("Manuscripts and books passed through the place with differing degrees of promise. Some merely required sympathy, better spacing, and a firm refusal to let the lowercase l resemble the numeral 1 in any context involving money.", size, ())],
        [("A very few required something more difficult. When such things arrived, they generally found their way to Tanya, whose desk stood at the point where design, typesetting, and reading had, over the years, agreed to meet and remain.", size, ())],
    ]
    for runs in paragraphs:
        if y > bottom:
            break
        y = svg.book_paragraph(runs, margin, y, text_width, 50, indent=size * 1.3, bottom=bottom)
    centred("1", 1612, 30)
    return svg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=ROOT / "out" / "ttf")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--family", default="Libron")
    args = parser.parse_args()
    hb = harfbuzz()
    with ExitStack() as resources:
        fonts = {style: Font(args.font_dir / f"{args.family}-{style}.ttf", hb, resources) for style in STYLES}
        # Read the built font's version, not VERSION, so standalone regeneration
        # cannot label old fonts with a newer version number.
        version = fonts["Regular"].tt["name"].getDebugName(5).split(";")[0].removeprefix("Version ")
        specimen_svg = specimen(fonts, args.family, version)
        sample_svg = sample(fonts, args.family, version)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        specimen_svg.save(args.output_dir / "specimen.svg")
        sample_svg.save(args.output_dir / "sample.svg")


if __name__ == "__main__":
    main()
