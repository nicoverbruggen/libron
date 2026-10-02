"""Check built fonts with HarfBuzz. Run after build.py in fntbld-oci.

    python3 -m unittest discover -s tests
"""

import ctypes
import ctypes.util
from pathlib import Path
import unicodedata
import unittest

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parents[1]
STYLES = ("Regular", "Bold", "Italic", "BoldItalic")
PUNCTUATION = {0x0374: 0x02B9, 0x037E: 0x003B, 0x0387: 0x00B7}


class GlyphInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint) for name in ("codepoint", "mask", "cluster", "var1", "var2")]


class GlyphPosition(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("x_advance", "y_advance", "x_offset", "y_offset", "var")]


class Shaper:
    """Use the container's HarfBuzz library without another Python dependency."""

    def __init__(self, path):
        library = ctypes.util.find_library("harfbuzz")
        if library is None:
            raise RuntimeError("HarfBuzz is required; run these tests in fntbld-oci")
        self.lib = ctypes.CDLL(library)
        pointer, integer, unsigned = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint
        functions = {
            "hb_blob_create": (pointer, [ctypes.c_char_p, unsigned, integer, pointer, pointer]),
            "hb_face_create": (pointer, [pointer, unsigned]),
            "hb_font_create": (pointer, [pointer]),
            "hb_ot_font_set_funcs": (None, [pointer]),
            "hb_font_set_scale": (None, [pointer, integer, integer]),
            "hb_buffer_create": (pointer, []),
            "hb_buffer_add_utf8": (None, [pointer, ctypes.c_char_p, integer, unsigned, integer]),
            "hb_buffer_guess_segment_properties": (None, [pointer]),
            "hb_language_from_string": (pointer, [ctypes.c_char_p, integer]),
            "hb_buffer_set_language": (None, [pointer, pointer]),
            "hb_shape": (None, [pointer, pointer, pointer, unsigned]),
            "hb_buffer_get_glyph_infos": (ctypes.POINTER(GlyphInfo), [pointer, ctypes.POINTER(unsigned)]),
            "hb_buffer_get_glyph_positions": (ctypes.POINTER(GlyphPosition), [pointer, ctypes.POINTER(unsigned)]),
        }
        for name in ("blob", "face", "font", "buffer"):
            functions[f"hb_{name}_destroy"] = (None, [pointer])
        for name, (result, arguments) in functions.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, arguments
        with TTFont(path) as font:
            self.order = font.getGlyphOrder()
            self.cmap = font.getBestCmap()
            upem = font["head"].unitsPerEm
        data = path.read_bytes()
        self.blob = self.lib.hb_blob_create(data, len(data), 0, None, None)
        self.face = self.lib.hb_face_create(self.blob, 0)
        self.font = self.lib.hb_font_create(self.face)
        self.lib.hb_ot_font_set_funcs(self.font)
        self.lib.hb_font_set_scale(self.font, upem, upem)

    def close(self):
        self.lib.hb_font_destroy(self.font)
        self.lib.hb_face_destroy(self.face)
        self.lib.hb_blob_destroy(self.blob)

    def shape(self, text, language="en"):
        buffer = self.lib.hb_buffer_create()
        try:
            encoded = text.encode("utf-8")
            self.lib.hb_buffer_add_utf8(buffer, encoded, len(encoded), 0, len(encoded))
            self.lib.hb_buffer_guess_segment_properties(buffer)
            self.lib.hb_buffer_set_language(buffer, self.lib.hb_language_from_string(language.encode(), -1))
            self.lib.hb_shape(self.font, buffer, None, 0)
            count = ctypes.c_uint()
            infos = self.lib.hb_buffer_get_glyph_infos(buffer, ctypes.byref(count))
            positions = self.lib.hb_buffer_get_glyph_positions(buffer, ctypes.byref(count))
            return [
                (self.order[infos[index].codepoint], positions[index].x_advance,
                 positions[index].y_advance, positions[index].x_offset, positions[index].y_offset)
                for index in range(count.value)
            ]
        finally:
            self.lib.hb_buffer_destroy(buffer)


class ScriptCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fonts = {}
        for style in STYLES:
            path = ROOT / "out" / "ttf" / f"Libron-{style}.ttf"
            if not path.is_file():
                raise RuntimeError("Build Libron before running script coverage tests")
            cls.fonts[style] = Shaper(path)
        cls.addClassCleanup(lambda: [font.close() for font in cls.fonts.values()])

    def test_greek_and_cyrillic_survive_each_output_format(self):
        required = set(map(ord, "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψωάέήίόύώϊϋΐΰАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюяҐґЄєІіЇїЂђЉљЊњЋћЏџЃѓЅѕЌќЈј"))
        for style in STYLES:
            for directory, filename in (("ttf", f"Libron-{style}.ttf"), ("kf", f"KF_Libron-{style}.ttf"), ("web", f"Libron-{style}.woff2")):
                with self.subTest(style=style, format=directory), TTFont(ROOT / "out" / directory / filename) as font:
                    cmap = font.getBestCmap()
                    self.assertFalse(required - set(cmap))
                    for greek, equivalent in PUNCTUATION.items():
                        self.assertEqual(cmap[greek], cmap[equivalent])
                    self.assertEqual((font["OS/2"].sTypoAscender, font["OS/2"].sTypoDescender, font["OS/2"].sTypoLineGap), (1600, -400, 0))

    def test_canonical_spellings_shape_identically(self):
        for style, font in self.fonts.items():
            for codepoint in sorted(font.cmap):
                if not 0x0370 <= codepoint <= 0x052F:
                    continue
                character = chr(codepoint)
                decomposed = unicodedata.normalize("NFD", character)
                if character == decomposed:
                    continue
                language = "el" if codepoint < 0x0400 else "ru"
                with self.subTest(style=style, character=f"U+{codepoint:04X}"):
                    self.assertEqual(font.shape(character, language), font.shape(decomposed, language))

    def test_localized_cyrillic_forms(self):
        for style, font in self.fonts.items():
            with self.subTest(style=style):
                russian = font.shape("бгдпт", "ru")
                bulgarian = font.shape("бгдпт", "bg")
                serbian = font.shape("бгдпт", "sr")
                macedonian = font.shape("бгдпт", "mk")
                self.assertNotEqual(russian, bulgarian)
                self.assertNotEqual(russian, serbian)
                self.assertEqual(serbian, macedonian)
                self.assertTrue(any(".srb" in glyph[0] for glyph in serbian))

    def test_combining_marks_attach_and_do_not_advance(self):
        for style, font in self.fonts.items():
            for text, language in (("а\u0301", "ru"), ("α\u0308\u0301", "el")):
                with self.subTest(style=style, text=text):
                    shaped = font.shape(text, language)
                    self.assertGreater(len(shaped), 1)
                    self.assertFalse(any(glyph[0] == ".notdef" for glyph in shaped))
                    for mark in shaped[1:]:
                        self.assertEqual(mark[1], 0)
                        self.assertNotEqual(mark[3:], (0, 0))


if __name__ == "__main__":
    unittest.main()
