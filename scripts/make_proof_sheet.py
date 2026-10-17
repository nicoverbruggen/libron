#!/usr/bin/env python3
"""Check combining accents and render proofs from the built fonts.

Run in fntbld-oci:
    python3 scripts/make_proof_sheet.py --check
    python3 scripts/make_proof_sheet.py --compare-dir out/before

Without --check, also render the individual precomposed letters. A comparison
adds shaped before/after specimens, including the text from discussion #23.
Input fonts are never modified.
"""
import argparse
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path
import unicodedata as ud

from fontTools.pens.boundsPen import BoundsPen
from PIL import Image, ImageDraw, ImageFont

from generate_specimens import Font, SVG, harfbuzz

ROOT = Path(__file__).resolve().parent.parent
STYLES = ("Regular", "Bold", "Italic", "BoldItalic")
REPORTER_TEXT = (
    "Dìdelis bal̃tas vil̃kas bė́go per tìltą prie ą́žuolo.",
    "Ū́kyje auga šim̃tas gėlių̃.",
    "i̇̀ i̇́ i̇̃ į̇́ į̇̃ ė́ ė̃ ą́ ą̃ ę́ ę̃ ų́ ų̃ ū́ ū̃ l̃ m̃ ñ r̃",
    "Į́ Į̃ Ė́ Ė̃ Ą́ Ą̃ Ę́ Ę̃ Ų́ Ų̃ Ū́ Ū̃ L̃ M̃ Ñ R̃",
)
EXTRA_SEQUENCES = (
    "ā́", "ǖ́", "ấ̃", "ộ́", "ớ", "ṇ̄", "Ń̃",
    "j̇́", "j̤́", "i̱̇́", "ị̇̃", "a̤̣", "ą̣", "ą̤̣",
    "x̧̣", "x̨̣", "á̵", "ớ̄", "Ự̃", "ǫ́",
    "x̃́", "x̤̣̱", "Ã́", "á̤̃", "á̤̣", "f̃", "k̃",
)


def clusters(text):
    """Keep a base and its following combining marks together."""
    cluster = ""
    for ch in text:
        if not ud.category(ch).startswith("M"):
            if cluster:
                yield cluster
            cluster = ch
        else:
            cluster += ch
    if cluster:
        yield cluster


def check_font(font):
    cmap = font.tt.getBestCmap()
    above = {name for cp, name in cmap.items() if ud.combining(chr(cp)) == 230}
    below = {name for cp, name in cmap.items() if ud.combining(chr(cp)) == 220}
    # case and locl can select unencoded mark variants before positioning.
    above |= {name for name in font.order if name.split(".")[0] in above}
    below |= {name for name in font.order if name.split(".")[0] in below}

    @lru_cache(maxsize=None)
    def bounds(name):
        pen = BoundsPen(font.glyphs)
        font.glyphs[name].draw(pen)
        return pen.bounds

    checked = 0

    def check(text, language="lt", features=()):
        nonlocal checked
        shaped = font.shape(text, language=language, features=features)
        for form in ("NFC", "NFD"):
            normalized = font.shape(ud.normalize(form, text), language=language, features=features)
            if shaped != normalized:
                raise AssertionError(f"{text!r}: {form} changes shaping ({language}, {features})")
        x = 0
        top = bottom = left = right = None
        for gid, advance, _, dx, dy in shaped:
            name = font.order[gid]
            bb = bounds(name)
            if bb is None:
                x += advance
                continue
            l, b, r, t = bb
            l, r, b, t = l + x + dx, r + x + dx, b + dy, t + dy
            if name in above or name in below:
                if advance:
                    raise AssertionError(f"{text!r}: mark {name} advances by {advance}")
                if top is None:
                    raise AssertionError(f"{text!r}: mark without a base")
                # Measure ink clearance, not just the existence of a GPOS table.
                gap = b - top if name in above else bottom - t
                if gap < 20:
                    raise AssertionError(f"{text!r}: {name} clearance is {gap:.1f} units ({language}, {features})")
                # Allow the italic slant to carry high stacks to the right.
                if r < left - font.upm / 4 or l > right + font.upm / 4:
                    raise AssertionError(f"{text!r}: {name} is beside the base ({language}, {features})")
            top = t if top is None else max(top, t)
            bottom = b if bottom is None else min(bottom, b)
            left = l if left is None else min(left, l)
            right = r if right is None else max(right, r)
            x += advance
        checked += 1

    for language in ("lt", "en", "pl"):
        for line in REPORTER_TEXT:
            font.shape(line, language=language)
            for cluster in clusters(line):
                if cluster[0].isalpha():
                    check(cluster, language)
        for text in EXTRA_SEQUENCES:
            check(text, language)

    # Appending a second mark exercises mkmk even if HarfBuzz composes the first.
    letters = [chr(cp) for cp in cmap if ud.category(chr(cp)).startswith("L")
               and "LATIN" in ud.name(chr(cp), "")]
    marks = [chr(cp) for cp in cmap if ud.combining(chr(cp)) in (220, 230)]
    for letter in letters:
        for mark in marks:
            check(letter + mark)
        check(letter + "\u0303\u0301")
        check(letter + "\u0324\u0323")
    for first in marks:
        for second in marks:
            check("x" + first + second)

    for features in (("smcp=1", "c2sc=1"), ("case=1",)):
        for line in REPORTER_TEXT[2:]:
            for text in line.split():
                check(text, features=features)
        for text in EXTRA_SEQUENCES:
            check(text, features=features)

    # Below-marks must not hide an above-mark from contextual dot removal.
    for text, expected in (("i̇́", "dotlessi"), ("j̇́", "j.dotless"),
                           ("į̇̃", "iogonek.dotless"), ("ị̇̃", "uni1ECB.dotless"),
                           ("i̱̇́", "dotlessi"), ("j̤́", "j.dotless")):
        shaped = font.shape(text, language="lt")
        name = font.order[shaped[0][0]]
        if name != expected:
            raise AssertionError(f"{text!r}: expected {expected}, got {name}")
        if shaped[0][1] != font.shape(text[0], language="lt")[0][1]:
            raise AssertionError(f"{text!r}: removing the dot changes the advance")
    for text in ("i", "j", "į", "ị", "i̱", "j̤"):
        if font.shape(text) != font.shape(text, features=("ccmp=0",)):
            raise AssertionError(f"{text!r}: lost its dot without an above-mark")

    # A language-specific ccmp registration must not hide the default features.
    ordinary = "office affine fluff AVATAR To Wa fi fl ffi ffl 0123456789 H2O (abc) 1/2"
    tags = {record.FeatureTag for record in font.tt["GSUB"].table.FeatureList.FeatureRecord}
    for features in [()] + [(f"{tag}=1",) for tag in sorted(tags)]:
        if font.shape(ordinary, language="lt", features=features) != font.shape(ordinary, language="en", features=features):
            raise AssertionError(f"Lithuanian changes ordinary text shaping ({features})")
        checked += 1

    def base_anchors(mark):
        anchors = {}
        for lookup in font.tt["GPOS"].table.LookupList.Lookup:
            if lookup.LookupType != 4:
                continue
            for table in lookup.SubTable:
                if mark not in table.MarkCoverage.glyphs:
                    continue
                index = table.MarkCoverage.glyphs.index(mark)
                mark_class = table.MarkArray.MarkRecord[index].Class
                for name, record in zip(table.BaseCoverage.glyphs, table.BaseArray.BaseRecord):
                    anchor = record.BaseAnchor[mark_class]
                    if anchor is not None:
                        anchors[name] = (anchor.XCoordinate, anchor.YCoordinate)
        return anchors

    # A middle dot must not pull an additional above-mark away from the l stem.
    top = base_anchors(cmap[0x0303])
    if top.get(cmap[0x0140]) != top[cmap[ord("l")]]:
        raise AssertionError("ŀ: above-mark anchor differs from l")
    checked += 1

    # Adding only above-marks must not move a small capital's below-marks.
    bottom = base_anchors(cmap[0x0324])
    pairs = set()
    for letter in letters:
        decomposed = ud.normalize("NFD", letter)
        if len(decomposed) < 2 or not all(ud.combining(ch) == 230 for ch in decomposed[1:]):
            continue
        forms = [font.shape(ch, features=("smcp=1", "c2sc=1"))
                 for ch in (decomposed[0], letter)]
        if any(len(form) != 1 for form in forms):
            continue
        base, accented = (font.order[form[0][0]] for form in forms)
        if base.endswith(".sc") and accented.endswith(".sc"):
            pairs.add((base, accented))
    for base, accented in sorted(pairs):
        if base not in bottom or bottom.get(accented) != bottom[base]:
            raise AssertionError(f"{accented}: below-mark anchor differs from {base}")
        checked += 1
    return checked


def render_grid(font, path, output):
    cps = [cp for cp in sorted(font.tt.getBestCmap())
           if ud.category(chr(cp)).startswith("L")
           and ud.normalize("NFD", chr(cp)) != chr(cp)]
    cols, cell_w, cell_h = 14, 96, 116
    image = Image.new("RGB", (cols * cell_w + 40, ((len(cps) + cols - 1) // cols) * cell_h + 100), "white")
    draw = ImageDraw.Draw(image)
    face = ImageFont.truetype(str(path), 64)
    title = ImageFont.truetype(str(path), 28)
    label = ImageFont.load_default()
    draw.text((20, 20), f"{path.stem}: {len(cps)} accented letters", font=title, fill="black")
    for i, cp in enumerate(cps):
        x, y = 20 + i % cols * cell_w, 70 + i // cols * cell_h
        draw.rectangle((x, y, x + cell_w - 4, y + cell_h - 4), outline="#e8e8e8")
        bb = draw.textbbox((0, 0), chr(cp), font=face)
        gx = x + (cell_w - 4 - bb[2] + bb[0]) / 2 - bb[0]
        draw.text((gx, y + 22), chr(cp), font=face, fill="black")
        draw.text((x + 5, y + cell_h - 16), f"U+{cp:04X}", font=label, fill="#666")
    image.save(output)


def render_comparison(before, after, style, output):
    svg = SVG({"Before": before, "After": after}, 1600, 1000, f"Libron {style}: combining accents before and after")
    svg.text(f"Libron {style}", 50, 52, 32, "After")
    rows = (
        (REPORTER_TEXT[0], 27), (REPORTER_TEXT[1], 30),
        ("i̇̀  i̇́  i̇̃  į̇́  į̇̃  ė́  ė̃", 48),
        ("ą́  ą̃  ę́  ę̃  ų́  ų̃  ū́  ū̃", 48),
        ("Į́  Į̃  Ė́  Ė̃  Ą́  Ą̃  Ę́  Ę̃", 44),
        ("Ų́  Ų̃  Ū́  Ū̃  L̃  M̃  Ñ  R̃", 44),
        ("l̃  m̃  ñ  r̃  j̇́  j̤́  ị̇̃", 48),
        ("ā́  ǖ́  ấ̃  ộ́  ớ  ṇ̄  Ń̃", 48),
        ("x̃́  x̤̣̱  Ã́  á̤̣  ą̣  ą̤̣", 48),
    )
    for name, x in (("Before", 50), ("After", 830)):
        svg.text(name, x, 108, 28, "After", fill="#666")
        for i, (text, size) in enumerate(rows):
            svg.text(text, x, 190 + i * 88, size, name, language="lt")
    svg.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=ROOT / "out" / "ttf")
    parser.add_argument("--family", default="Libron")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "proofs")
    parser.add_argument("--compare-dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate fonts without modifying them or writing proofs")
    parser.add_argument("--fonts", nargs="+", type=Path, help="Explicit font files to check")
    args = parser.parse_args()
    if args.fonts and not args.check:
        parser.error("--fonts requires --check")
    hb = harfbuzz()
    if args.check:
        paths = args.fonts or [args.font_dir / f"{args.family}-{style}.ttf" for style in STYLES]
        for path in paths:
            with ExitStack() as resources:
                font = Font(path, hb, resources)
                count = check_font(font)
                print(f"{path.name}: {count} combining-accent checks passed")
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for style in STYLES:
        with ExitStack() as resources:
            filename = f"{args.family}-{style}.ttf"
            path = args.font_dir / filename
            font = Font(path, hb, resources)
            render_grid(font, path, args.output_dir / f"sheet_{style}.png")
            if args.compare_dir:
                before = Font(args.compare_dir / filename, hb, resources)
                render_comparison(before, font, style, args.output_dir / f"combining_{style}.svg")


if __name__ == "__main__":
    main()
