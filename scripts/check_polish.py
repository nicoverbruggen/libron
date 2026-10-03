#!/usr/bin/env python3
"""Check Polish localization with HarfBuzz after building the fonts.

Run in fntbld-oci: python3 scripts/check_polish.py
Requires fontTools, skia-pathops, and HarfBuzz, all in the build image.
"""
import ctypes as ct
import ctypes.util
from io import BytesIO
from pathlib import Path
import unicodedata

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
import pathops


class GlyphInfo(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in
                ("codepoint", "mask", "cluster", "var1", "var2")]


class GlyphPosition(ct.Structure):
    _fields_ = [(n, ct.c_int32) for n in
                ("x_advance", "y_advance", "x_offset", "y_offset", "var")]


class Feature(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ("tag", "value", "start", "end")]


class Shaper:
    def __init__(self, font):
        library = ctypes.util.find_library("harfbuzz")
        if library is None:
            raise RuntimeError("HarfBuzz is required; run this check in fntbld-oci")
        self.hb = ct.CDLL(library)
        self.names = font.getGlyphOrder()
        ptr, uint, integer = ct.c_void_p, ct.c_uint, ct.c_int
        signatures = {
            "blob_create": (ptr, [ct.c_char_p, uint, integer, ptr, ptr]),
            "face_create": (ptr, [ptr, uint]),
            "font_create": (ptr, [ptr]),
            "ot_font_set_funcs": (None, [ptr]),
            "buffer_create": (ptr, []),
            "buffer_add_utf8": (None, [ptr, ct.c_char_p, integer, uint, integer]),
            "language_from_string": (ptr, [ct.c_char_p, integer]),
            "buffer_set_language": (None, [ptr, ptr]),
            "buffer_guess_segment_properties": (None, [ptr]),
            "shape": (None, [ptr, ptr, ct.POINTER(Feature), uint]),
            "buffer_get_length": (uint, [ptr]),
            "buffer_get_glyph_infos": (ct.POINTER(GlyphInfo), [ptr, ct.POINTER(uint)]),
            "buffer_get_glyph_positions": (ct.POINTER(GlyphPosition), [ptr, ct.POINTER(uint)]),
        }
        for kind in ("blob", "face", "font", "buffer"):
            signatures[kind + "_destroy"] = (None, [ptr])
        for name, (result, args) in signatures.items():
            fn = getattr(self.hb, "hb_" + name)
            fn.restype, fn.argtypes = result, args
        # HarfBuzz expects SFNT data, including when checking WOFF2 output.
        data = BytesIO()
        flavor = font.flavor
        font.flavor = None
        font.save(data)
        font.flavor = flavor
        raw = data.getvalue()
        self.blob = self.hb.hb_blob_create(raw, len(raw), 0, None, None)
        self.face = self.hb.hb_face_create(self.blob, 0)
        self.font = self.hb.hb_font_create(self.face)
        self.hb.hb_ot_font_set_funcs(self.font)

    def close(self):
        self.hb.hb_font_destroy(self.font)
        self.hb.hb_face_destroy(self.face)
        self.hb.hb_blob_destroy(self.blob)

    def shape(self, text, language="en", **features):
        hb = self.hb
        buffer = hb.hb_buffer_create()
        try:
            raw = text.encode("utf-8")
            hb.hb_buffer_add_utf8(buffer, raw, len(raw), 0, len(raw))
            lang = language.encode("ascii")
            hb.hb_buffer_set_language(buffer, hb.hb_language_from_string(lang, len(lang)))
            hb.hb_buffer_guess_segment_properties(buffer)
            settings = (Feature * len(features))(*[
                Feature(int.from_bytes(tag.encode("ascii"), "big"), value, 0, 0xFFFFFFFF)
                for tag, value in features.items()
            ])
            hb.hb_shape(self.font, buffer, settings, len(settings))
            count = hb.hb_buffer_get_length(buffer)
            info = hb.hb_buffer_get_glyph_infos(buffer, None)
            pos = hb.hb_buffer_get_glyph_positions(buffer, None)
            return [(self.names[info[i].codepoint], pos[i].x_advance, pos[i].y_advance,
                     pos[i].x_offset, pos[i].y_offset) for i in range(count)]
        finally:
            hb.hb_buffer_destroy(buffer)


def check(path):
    font = TTFont(path)
    shaper = Shaper(font)
    shape = shaper.shape
    text = "ćńóśźĆŃÓŚŹ"
    normal = shape(text)
    localized = shape(text, "pl")
    try:
        assert [g[0] for g in localized] == [g[0] + ".loclPLK" for g in normal]
        assert shape(text, "pl", locl=0) == normal
        for language in ("und", "cs", "fr", "ro"):
            assert shape(text, language) == normal, language
        assert shape(text, "pl-PL") == localized
        assert shape(unicodedata.normalize("NFD", text), "pl") == localized
        for feature, sample in (("smcp", text[:5]), ("c2sc", text[5:])):
            default = shape(sample, **{feature: 1})
            polish = shape(sample, "pl", **{feature: 1})
            assert all(g[0].endswith(".sc") for g in default)
            assert [g[0] for g in polish] == [g[0] + ".loclPLK" for g in default]
            assert [g[1:] for g in polish] == [g[1:] for g in default]
            assert shape(sample, "pl", locl=0, **{feature: 1}) == default
        # A noncomposing sequence exercises the localized mark and its anchors.
        for sample in ("q\u0301", "q\u0301\u0308", "c\u034f\u0301"):
            normal_mark = shape(sample)
            polish_mark = shape(sample, "pl")
            assert "acutecomb.loclPLK" in [g[0] for g in polish_mark]
            assert [g[1:] for g in polish_mark] == [g[1:] for g in normal_mark]
        for features in ({}, {"liga": 0}, {"tnum": 1}, {"pnum": 1}, {"smcp": 1}):
            assert shape("office AV To 0123456789", "pl", **features) == shape(
                "office AV To 0123456789", **features), features
        # Both sides of explicit and class kerning must survive substitution.
        neighbours = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,:;!?" + text
        for feature in ({}, {"smcp": 1}, {"c2sc": 1}):
            for accent in text:
                for neighbour in neighbours:
                    for pair in (accent + neighbour, neighbour + accent):
                        a = shape(pair, "pl", **feature)
                        b = shape(pair, "pl", locl=0, **feature)
                        assert [g[1:] for g in a] == [g[1:] for g in b], (pair, feature)
        glyphs = font.getGlyphSet()
        pen = DecomposingRecordingPen(glyphs)
        glyphs["eogonek"].draw(pen)
        outline = pathops.Path()
        pen.replay(outline.getPen())
        outline.simplify()
        assert len(list(outline.contours)) == 2, "detached ogonek or lost counter"
    finally:
        shaper.close()
        font.close()
    print(f"PASS {path}: Polish forms, fallback, normalization, features, kerning, attachment")


def main():
    root = Path(__file__).resolve().parents[1] / "out"
    for directory, prefix, extension in (("ttf", "", "ttf"), ("kf", "KF_", "ttf"),
                                         ("web", "", "woff2")):
        for style in ("Regular", "Bold", "Italic", "BoldItalic"):
            check(root / directory / f"{prefix}Libron-{style}.{extension}")


if __name__ == "__main__":
    main()
