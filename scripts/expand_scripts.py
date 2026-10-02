"""Fit Source Serif's Greek and Cyrillic to Libron, then merge their layout data.

The donor files are unmodified Source Serif 4 variable fonts from Sourcerer
commit a87decbe8c5ae349def828b4a0b314c1f2d5d227. Their OFL notice is in LICENSE.
Run through build.py inside the fntbld-oci container.
"""

import copy
import hashlib
import os
import unicodedata
from pathlib import Path

from fontTools import subset
from fontTools.merge import Merger
from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.varLib.instancer import instantiateVariableFont


SOURCE_HASHES = {
    "Roman": "14d360ee1b76655da9276628b229e11671bc1f5d1083636144db6677d452cf55",
    "Italic": "6a059a64838978d54e8fab71ed86b0d82e948c0e12b2664d0c15166326dcff82",
}
DONOR_STYLES = {
    "Regular": ("Roman", 450),
    "Italic": ("Italic", 450),
    "Bold": ("Roman", 650),
    "BoldItalic": ("Italic", 675),
}
SCRIPT_TAGS = {"grek", "cyrl"}
CANONICAL_PUNCTUATION = {0x0374: 0x02B9, 0x037E: 0x003B, 0x0387: 0x00B7}


def _bounds(font, name):
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[name].draw(pen)
    return pen.bounds


def _subtables(font, tag):
    if tag not in font:
        return
    for lookup in font[tag].table.LookupList.Lookup:
        for subtable in lookup.SubTable:
            yield getattr(subtable, "ExtSubTable", subtable)


def _vertical_scales(font, capital_scale, lowercase_scale):
    """Unencoded localized forms inherit the scale of their encoded source."""
    scales = {}
    for codepoint, name in font.getBestCmap().items():
        category = unicodedata.category(chr(codepoint))
        scales[name] = (
            lowercase_scale if category == "Ll" or category.startswith("M")
            else capital_scale
        )
    # Some alternate chains refer to other unencoded alternates.
    changed = True
    while changed:
        changed = False
        for subtable in _subtables(font, "GSUB"):
            mappings = getattr(subtable, "mapping", {})
            mappings = {**mappings, **getattr(subtable, "alternates", {})}
            for source, targets in mappings.items():
                if source not in scales:
                    continue
                if isinstance(targets, str):
                    targets = [targets]
                for target in targets:
                    if target not in scales:
                        scales[target] = scales[source]
                        changed = True
            for source, ligatures in getattr(subtable, "ligatures", {}).items():
                if source not in scales:
                    continue
                for ligature in ligatures:
                    if ligature.LigGlyph not in scales:
                        scales[ligature.LigGlyph] = scales[source]
                        changed = True
    return {name: scales.get(name, capital_scale) for name in font.getGlyphOrder()}


def _scale_anchor(anchor, name, horizontal_scale, vertical_scales):
    if anchor is None:
        return None
    anchor = copy.deepcopy(anchor)
    anchor.XCoordinate = otRound(anchor.XCoordinate * horizontal_scale)
    anchor.YCoordinate = otRound(anchor.YCoordinate * vertical_scales[name])
    # Outlines are decomposed, so an old contour-point index cannot be retained.
    if anchor.Format == 2:
        anchor.Format = 1
        del anchor.AnchorPoint
    return anchor


def _scale_value(value, horizontal_scale, vertical_scale):
    if value is None:
        return None
    value = copy.deepcopy(value)
    for field in ("XPlacement", "XAdvance"):
        if hasattr(value, field):
            setattr(value, field, otRound(getattr(value, field) * horizontal_scale))
    for field in ("YPlacement", "YAdvance"):
        if hasattr(value, field):
            setattr(value, field, otRound(getattr(value, field) * vertical_scale))
    return value


def _scale_positioning(font, horizontal_scale, vertical_scales):
    """Fit attachment anchors per glyph and pair adjustments horizontally."""
    for subtable in _subtables(font, "GPOS"):
        kind = subtable.__class__.__name__
        if kind == "MarkBasePos":
            for name, record in zip(subtable.MarkCoverage.glyphs, subtable.MarkArray.MarkRecord):
                record.MarkAnchor = _scale_anchor(record.MarkAnchor, name, horizontal_scale, vertical_scales)
            for name, record in zip(subtable.BaseCoverage.glyphs, subtable.BaseArray.BaseRecord):
                record.BaseAnchor = [
                    _scale_anchor(anchor, name, horizontal_scale, vertical_scales)
                    for anchor in record.BaseAnchor
                ]
        elif kind == "MarkMarkPos":
            for name, record in zip(subtable.Mark1Coverage.glyphs, subtable.Mark1Array.MarkRecord):
                record.MarkAnchor = _scale_anchor(record.MarkAnchor, name, horizontal_scale, vertical_scales)
            for name, record in zip(subtable.Mark2Coverage.glyphs, subtable.Mark2Array.Mark2Record):
                record.Mark2Anchor = [
                    _scale_anchor(anchor, name, horizontal_scale, vertical_scales)
                    for anchor in record.Mark2Anchor
                ]
        elif kind == "SinglePos":
            names = subtable.Coverage.glyphs
            if subtable.Format == 1:
                scales = {vertical_scales[name] for name in names}
                if len(scales) != 1 and any(getattr(subtable.Value, field, 0) for field in ("YPlacement", "YAdvance")):
                    # A shared adjustment needs separate records when its glyphs
                    # have different vertical scales.
                    value = subtable.Value
                    subtable.Format = 2
                    subtable.Value = [_scale_value(value, horizontal_scale, vertical_scales[name]) for name in names]
                    subtable.ValueCount = len(names)
                else:
                    subtable.Value = _scale_value(subtable.Value, horizontal_scale, vertical_scales[names[0]])
            else:
                subtable.Value = [
                    _scale_value(value, horizontal_scale, vertical_scales[name])
                    for name, value in zip(names, subtable.Value)
                ]
        elif kind == "PairPos":
            if subtable.Format == 1:
                pairs = (
                    (name, record.SecondGlyph, record)
                    for name, pairset in zip(subtable.Coverage.glyphs, subtable.PairSet)
                    for record in pairset.PairValueRecord
                )
            else:
                pairs = (
                    (None, None, record)
                    for class1 in subtable.Class1Record
                    for record in class1.Class2Record
                )
            for first, second, record in pairs:
                for field, name in (("Value1", first), ("Value2", second)):
                    value = getattr(record, field, None)
                    if name is None and value is not None and any(getattr(value, axis, 0) for axis in ("YPlacement", "YAdvance")):
                        raise ValueError("Donor class kerning has an unsupported vertical adjustment")
                    setattr(record, field, _scale_value(value, horizontal_scale, vertical_scales.get(name, 1.0)))
        elif kind not in {"ContextPos", "ChainContextPos"}:
            raise ValueError(f"Unsupported donor positioning table: {kind}")


def _fit_outlines(font, horizontal_scale, vertical_scales):
    glyphs = font.getGlyphSet()
    recordings = {}
    # Freeze every component before modifying a base that it may reference.
    for name in font.getGlyphOrder():
        pen = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(pen)
        recordings[name] = pen
    for name, recording in recordings.items():
        pen = TTGlyphPen(None)
        recording.replay(TransformPen(pen, (horizontal_scale, 0, 0, vertical_scales[name], 0, 0)))
        glyph = pen.glyph()
        font["glyf"][name] = glyph
        glyph.recalcBounds(font["glyf"])
        width, _ = font["hmtx"][name]
        font["hmtx"][name] = (otRound(width * horizontal_scale), getattr(glyph, "xMin", 0))


def prepare_donor(source_dir, style, baseline, output_path):
    source_style, weight = DONOR_STYLES[style]
    path = Path(source_dir) / f"SourceSerif4Variable-{source_style}.ttf"
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_HASHES[source_style]:
        raise ValueError(f"Unexpected Source Serif source file: {path}")
    with TTFont(path) as source:
        donor = instantiateVariableFont(source, {"wght": weight, "opsz": 9}, inplace=False)
    scale_upem(donor, baseline["head"].unitsPerEm)
    baseline_cmap, donor_cmap = baseline.getBestCmap(), donor.getBestCmap()
    target_h = _bounds(baseline, baseline_cmap[ord("H")])
    source_h = _bounds(donor, donor_cmap[ord("H")])
    target_x = _bounds(baseline, baseline_cmap[ord("x")])
    source_x = _bounds(donor, donor_cmap[ord("x")])
    horizontal_scale = (target_h[2] - target_h[0]) / (source_h[2] - source_h[0]) if source_style == "Roman" else 1.0
    capital_scale = target_h[3] / source_h[3]
    lowercase_scale = target_x[3] / source_x[3]
    scales = _vertical_scales(donor, capital_scale, lowercase_scale)

    # Keep script-specific shaping and the marks it needs. Duplicate mark cmap
    # entries are resolved by the merger's Greek/Cyrillic locl substitutions.
    codepoints = {
        cp for cp in donor_cmap
        if 0x0370 <= cp <= 0x03FF or 0x0400 <= cp <= 0x052F
        or unicodedata.category(chr(cp)).startswith("M")
    }
    options = subset.Options()
    options.layout_features = ["*"]
    options.layout_scripts = sorted(SCRIPT_TAGS)
    options.hinting = False
    options.glyph_names = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codepoints)
    subsetter.subset(donor)
    _scale_positioning(donor, horizontal_scale, scales)
    _fit_outlines(donor, horizontal_scale, scales)
    donor.save(output_path)
    donor.close()
    print(f"  Source Serif {source_style}: opsz 9, weight {weight}, X {horizontal_scale:.5f}, capital Y {capital_scale:.5f}, lowercase Y {lowercase_scale:.5f}")


def expand_script_coverage(ttf_path, style, source_dir, temporary_dir):
    donor_path = os.path.join(temporary_dir, f"SourceSerif-{style}.ttf")
    with TTFont(ttf_path) as baseline:
        prepare_donor(source_dir, style, baseline, donor_path)
        original_names = set(baseline.getGlyphOrder())
        original_codepoints = set(baseline.getBestCmap())
        original_cmap = dict(baseline.getBestCmap())
        glyphs = baseline.getGlyphSet()
        original_outlines = {}
        original_widths = dict(baseline["hmtx"].metrics)
        for name in baseline.getGlyphOrder():
            pen = DecomposingRecordingPen(glyphs)
            glyphs[name].draw(pen)
            original_outlines[name] = pen.value
        metadata = {tag: copy.deepcopy(baseline[tag]) for tag in ("name", "OS/2", "hhea")}
        post_fields = {field: getattr(baseline["post"], field) for field in ("italicAngle", "underlinePosition", "underlineThickness", "isFixedPitch")}
        revision = baseline["head"].fontRevision
    merged = Merger().merge([ttf_path, donor_path])
    for tag, table in metadata.items():
        merged[tag] = table
    for field, value in post_fields.items():
        setattr(merged["post"], field, value)
    merged["head"].fontRevision = revision
    # Unicode canonically decomposes these Greek punctuation characters into
    # existing Latin punctuation. Use the same glyph for either spelling.
    for table in merged["cmap"].tables:
        if table.isUnicode():
            for greek, equivalent in CANONICAL_PUNCTUATION.items():
                table.cmap[greek] = original_cmap[equivalent]
    merged["OS/2"].recalcUnicodeRanges(merged)
    merged["OS/2"].recalcCodePageRanges(merged)

    # Keep Libron's Typo line spacing. Expand only the selection/clipping span
    # if an imported glyph needs room for its accent or descender.
    bounds = [_bounds(merged, name) for name in set(merged.getGlyphOrder()) - original_names]
    bounds = [box for box in bounds if box is not None]
    if bounds:
        ascent = max(merged["OS/2"].usWinAscent, max(otRound(box[3]) for box in bounds))
        descent = max(merged["OS/2"].usWinDescent, max(-otRound(box[1]) for box in bounds))
        merged["OS/2"].usWinAscent = ascent
        merged["OS/2"].usWinDescent = descent
        merged["hhea"].ascent = max(merged["hhea"].ascent, ascent)
        merged["hhea"].descent = min(merged["hhea"].descent, -descent)
    added = len(set(merged.getBestCmap()) - original_codepoints)
    glyphs = merged.getGlyphSet()
    for name, outline in original_outlines.items():
        pen = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(pen)
        if pen.value != outline or merged["hmtx"][name] != original_widths[name]:
            raise ValueError(f"Script import changed original Libron glyph: {name}")
    if any(merged.getBestCmap().get(cp) != name for cp, name in original_cmap.items()):
        raise ValueError("Script import changed an original Libron Unicode mapping")
    output_path = os.path.join(temporary_dir, f"Libron-{style}-merged.ttf")
    merged.save(output_path)
    merged.close()
    os.replace(output_path, ttf_path)
    print(f"  Added {added} encoded characters with Greek/Cyrillic layout data")
