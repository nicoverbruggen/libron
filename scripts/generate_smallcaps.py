#!/usr/bin/env fontforge -lang=py -script
"""
generate_smallcaps.py — build synthetic small caps for Libron and wire them up.

Based on the draft scripts iblazhko contributed in issue #3. One pass does
everything, in this order, for all four masters:

  1. GLYPHS. Every capital (Unicode category Lu) gets a `<name>.sc` glyph.
       - Plain capitals (drawn outlines): scale from cap height to a little
         above x-height (SC_HEIGHT_RATIO), then thicken the strokes with
         changeWeight() so the result is not a thin, shrunken cap. Contours that sit entirely below the baseline
         (cedillas, breves below) are scaled but not thickened, the same way
         marks on composites are handled below. Thickening those small shapes
         breaks them.
       - Composite capitals (references, e.g. Agrave = A + gravecomb.case):
         scale the references, then point the base at the finished `<Base>.sc`
         so the letter matches its standalone small cap exactly. The `.case`
         marks stay scaled and unthickened.
       Every small cap also gets a little extra space on each side: small caps
       are set more openly than the capitals they come from.

  2. KERNING. Derived from the font's own kerning, scaled by the same ratio.
       - The class subtable gets mirror classes: for each class that holds
         capitals, a class of their `.sc` twins. Small cap against small cap,
         capital against small cap (the `T` in `Trevelyan`), and punctuation
         on either side all inherit the capital pairs' values.
       - The explicit pair subtable gets the same derivation for its
         capital pairs.

  3. FEATURES. `smcp` (lowercase -> `.sc`) and `c2sc` (capital -> `.sc`),
       inserted BEFORE `liga`. Lookups run in order, and if `liga` ran first
       "office" would turn into a small-cap o, a lowercase ffi ligature and
       small-cap c e.

This is a mechanical result. Real small caps are drawn, not scaled, and a
manual pass over weight, counters and spacing will still improve it. It is
good enough to read with, which is the point for an e-reader font.

Run inside the fntbld-oci container:

    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        fontforge -lang=py -script /work/scripts/generate_smallcaps.py report
    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        fontforge -lang=py -script /work/scripts/generate_smallcaps.py apply

The script refuses to run on a master that already has `.sc` glyphs. To
regenerate after changing a constant, restore the four masters from the
commit before small caps were added, then run apply again.
"""
import fontforge, psMat, sys, unicodedata

FILES = [
    "/work/src/Libron-Regular.sfd",
    "/work/src/Libron-Bold.sfd",
    "/work/src/Libron-Italic.sfd",
    "/work/src/Libron-BoldItalic.sfd",
]
MODE = sys.argv[1] if len(sys.argv) > 1 else "report"

# Small cap height as a multiple of the x-height. Exactly x-height reads as
# odd lowercase on the page; drawn small caps sit a little above it.
SC_HEIGHT_RATIO = 1.07
# Stroke width added back after scaling down, in font units per master. Chosen so a small cap's
# stem matches the lowercase stem of the same master: measured on the built fonts as the width
# of `l` and of the small cap `I` at mid height, the difference being what changeWeight() adds.
# A capital scaled to small cap size is thinner than the lowercase in every master, and by a
# different amount in each, so one ratio for all four does not fit.
EMBOLDEN_UNITS = {
    "Libron-Regular": 28,
    "Libron-Bold": 36,
    "Libron-Italic": 20,
    "Libron-BoldItalic": 32,
}
# Extra sidebearing on each side of a small cap, as a fraction of the em.
TRACKING_RATIO = 0.01

LANGUAGE_SYSTEMS = (("DFLT", ("dflt",)), ("latn", ("dflt", "MOL ", "ROM ")))
SMCP_LOOKUP = "'smcp' Lowercase to Small Capitals in Latin"
C2SC_LOOKUP = "'c2sc' Capitals to Small Capitals in Latin"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def measure(font, chars, axis):
    """Highest ('top') or lowest ('bottom') bbox edge among the given chars."""
    idx = 3 if axis == "top" else 1
    pick = max if axis == "top" else min
    hits = []
    for ch in chars:
        name = fontforge.nameFromUnicode(ord(ch))
        if name in font and font[name].isWorthOutputting():
            bb = font[name].boundingBox()
            if bb != (0, 0, 0, 0):
                hits.append(bb[idx])
    return pick(hits) if hits else None


def category(font, name):
    """Unicode general category of a glyph, or None for unencoded glyphs."""
    if name not in font:
        return None
    uni = font[name].unicode
    if uni is None or uni <= 0:
        return None
    try:
        return unicodedata.category(chr(uni))
    except ValueError:
        return None


def is_capital(font, name):
    return category(font, name) == "Lu"


def is_nonletter(font, name):
    cat = category(font, name)
    return cat is not None and not cat.startswith("L")


def sc_name(name):
    return f"{name}.sc"


# --------------------------------------------------------------------------- #
# 1. Glyphs
# --------------------------------------------------------------------------- #
def split_below_baseline(layer):
    """Split a layer into (body, below): contours whose top is at or under the
    baseline go into `below`. Those are detached marks (cedilla, breve below)."""
    body = fontforge.layer()
    below = fontforge.layer()
    body.is_quadratic = below.is_quadratic = layer.is_quadratic
    for contour in layer:
        if contour.boundingBox()[3] <= 0:
            below += contour
        else:
            body += contour
    return body, below


def make_plain_sc(font, name, ratio, embolden, tracking):
    base = font[name]
    body, below = split_below_baseline(base.layers[1])
    scale = psMat.scale(ratio, ratio)

    sc = font.createChar(-1, sc_name(name))
    sc.layers[1] = body
    sc.anchorPoints = base.anchorPoints
    sc.transform(scale)
    sc.changeWeight(embolden, "auto")
    # changeWeight()'s stroke offsetting does not add curve extrema back.
    sc.addExtrema()

    if len(below) > 0:
        below.transform(scale)
        merged = sc.layers[1]
        merged += below
        sc.layers[1] = merged

    sc.transform(psMat.translate(tracking, 0))
    sc.width = round(base.width * ratio) + 2 * tracking


def make_composite_sc(font, name, ratio, tracking, capset):
    base = font[name]
    sc = font.createChar(-1, sc_name(name))
    sc.layers[1] = base.layers[1]
    sc.references = base.references
    sc.anchorPoints = base.anchorPoints
    sc.transform(psMat.scale(ratio, ratio))

    swapped = []
    swapped_count = 0
    for ref_name, matrix, selected in sc.references:
        is_uniform_scale = (
            abs(matrix[0] - ratio) < 1e-4
            and abs(matrix[3] - ratio) < 1e-4
            and abs(matrix[1]) < 1e-6
            and abs(matrix[2]) < 1e-6
        )
        if ref_name in capset and sc_name(ref_name) in font and is_uniform_scale:
            # The `.sc` twin is already scaled and already carries its own
            # tracking on the left, so reset the scale to identity and keep
            # the scaled translation. Side-by-side bases (the D and Z of a
            # DZ digraph) each need the previous base's right tracking too.
            dx = matrix[4] + 2 * tracking * swapped_count
            swapped.append((sc_name(ref_name), (1.0, 0.0, 0.0, 1.0, dx, matrix[5]), False))
            swapped_count += 1
        else:
            # Marks keep their scaled size and follow the base's tracking.
            swapped.append((ref_name, matrix[:4] + (matrix[4] + tracking, matrix[5]), selected))
    sc.references = tuple(swapped)
    sc.width = round(base.width * ratio) + 2 * tracking


def build_glyphs(font, ratio, embolden, tracking):
    capset = {g.glyphname for g in font.glyphs() if is_capital(font, g.glyphname)}
    plain = sorted(n for n in capset if len(font[n].references) == 0)
    composite = sorted(n for n in capset if len(font[n].references) > 0)

    # Plain capitals first: composites point at their `.sc` twins, and no
    # composite in this font nests on another composite.
    if MODE == "apply":
        for name in plain:
            make_plain_sc(font, name, ratio, embolden, tracking)
        for name in composite:
            make_composite_sc(font, name, ratio, tracking, capset)
    return plain, composite, capset


# --------------------------------------------------------------------------- #
# 2. Kerning
# --------------------------------------------------------------------------- #
def kern_subtables(font):
    """(pair_subtable, class_subtable) of the 'kern' lookup, either may be None."""
    lookups = [l for l in font.gpos_lookups if font.getLookupInfo(l)[0] == "gpos_pair"]
    pair = klass = None
    for lookup in lookups:
        for sub in font.getLookupSubtables(lookup):
            if font.isKerningClass(sub):
                klass = klass or sub
            else:
                pair = pair or sub
    return pair, klass


def class_kind(font, members):
    """'cap' if the class holds capitals, 'lower' if lowercase only, else 'other'."""
    cats = {category(font, n) for n in (members or ())}
    if "Lu" in cats:
        return "cap"
    if "Ll" in cats:
        return "lower"
    return "other"


def derive_class_kerning(font, subtable, ratio, capset):
    """Extend the class matrix with `.sc` mirror classes.

    Returns (firsts, seconds, offsets, mirrored_first_count, mirrored_second_count).
    """
    firsts, seconds, offsets = font.getKerningClass(subtable)
    n_first, n_second = len(firsts), len(seconds)

    def mirror(classes):
        out = []
        for idx, members in enumerate(classes):
            twins = tuple(sc_name(n) for n in (members or ()) if n in capset)
            if twins:
                out.append((idx, twins))
        return out

    first_mirrors = mirror(firsts)
    second_mirrors = mirror(seconds)
    first_kinds = [class_kind(font, c) for c in firsts]
    second_kinds = [class_kind(font, c) for c in seconds]

    new_firsts = tuple(firsts) + tuple(t for _, t in first_mirrors)
    new_seconds = tuple(seconds) + tuple(t for _, t in second_mirrors)
    width = len(new_seconds)

    def old(i, j):
        return offsets[i * n_second + j]

    def scaled(i, j):
        return int(round(old(i, j) * ratio))

    new_offsets = [0] * (len(new_firsts) * width)
    # Existing block, unchanged.
    for i in range(n_first):
        for j in range(n_second):
            new_offsets[i * width + j] = old(i, j)
    # Anything followed by a small cap: capitals and punctuation inherit the
    # capital's value; lowercase before a small cap stays unkerned.
    for i in range(n_first):
        if first_kinds[i] == "lower":
            continue
        for jj, (j, _) in enumerate(second_mirrors):
            new_offsets[i * width + n_second + jj] = scaled(i, j)
    # A small cap followed by anything: same rule on the other side.
    for ii, (i, _) in enumerate(first_mirrors):
        row = (n_first + ii) * width
        for j in range(n_second):
            if second_kinds[j] != "lower":
                new_offsets[row + j] = scaled(i, j)
        for jj, (j, _) in enumerate(second_mirrors):
            new_offsets[row + n_second + jj] = scaled(i, j)

    return new_firsts, new_seconds, tuple(new_offsets), len(first_mirrors), len(second_mirrors)


def derive_pair_kerning(font, subtable, ratio, capset):
    """Explicit pairs to add: [(first, second, value)] derived from capital pairs."""
    pairs = []
    for g in font.glyphs():
        first = g.glyphname
        for entry in g.getPosSub(subtable):
            if entry[1] != "Pair":
                continue
            second, value = entry[2], entry[5]
            if not value:
                continue
            v = int(round(value * ratio))
            if not v:
                continue
            first_cap = first in capset
            second_cap = second in capset
            if first_cap and second_cap:
                pairs.append((sc_name(first), sc_name(second), v))
                pairs.append((first, sc_name(second), v))
                pairs.append((sc_name(first), second, v))
            elif first_cap and is_nonletter(font, second):
                pairs.append((sc_name(first), second, v))
            elif second_cap and is_nonletter(font, first):
                pairs.append((first, sc_name(second), v))
    return pairs


def build_kerning(font, ratio, capset):
    pair_sub, class_sub = kern_subtables(font)
    stats = {}
    if class_sub is not None:
        firsts, seconds, offsets, n_f, n_s = derive_class_kerning(font, class_sub, ratio, capset)
        stats["class mirrors"] = f"{n_f} first, {n_s} second"
        if MODE == "apply":
            font.alterKerningClass(class_sub, firsts, seconds, offsets)
    if pair_sub is not None:
        pairs = derive_pair_kerning(font, pair_sub, ratio, capset)
        stats["explicit pairs"] = len(pairs)
        if MODE == "apply":
            for first, second, value in pairs:
                font[first].addPosSub(pair_sub, second, 0, 0, value, 0, 0, 0, 0, 0)
    return stats


# --------------------------------------------------------------------------- #
# 3. Features
# --------------------------------------------------------------------------- #
def build_pairs(font, capset):
    """(lowercase, .sc) for smcp and (capital, .sc) for c2sc."""
    smcp, c2sc = [], {}
    for g in font.glyphs():
        if category(font, g.glyphname) != "Ll":
            continue
        upper = chr(g.unicode).upper()
        if len(upper) != 1:
            continue  # no 1:1 uppercase (sharp s, the fi/fl ligatures)
        upper_name = fontforge.nameFromUnicode(ord(upper))
        if upper_name in capset:
            smcp.append((g.glyphname, sc_name(upper_name)))
    for name in sorted(capset):
        c2sc[name] = sc_name(name)
    return sorted(smcp), sorted(c2sc.items())


def add_single_lookup(font, lookup, feature, after, mapping):
    font.addLookup(lookup, "gsub_single", (), ((feature, LANGUAGE_SYSTEMS),), after)
    subtable = f"{lookup} subtable"
    font.addLookupSubtable(lookup, subtable)
    for source, target in mapping:
        font[source].addPosSub(subtable, target)


def build_features(font, capset):
    smcp, c2sc = build_pairs(font, capset)
    liga = [l for l in font.gsub_lookups if l.startswith("'liga'")]
    before = None
    if liga:
        idx = font.gsub_lookups.index(liga[0])
        if idx == 0:
            raise SystemExit("liga is the first GSUB lookup; cannot insert smcp before it")
        before = font.gsub_lookups[idx - 1]
    if MODE == "apply":
        add_single_lookup(font, SMCP_LOOKUP, "smcp", before, smcp)
        add_single_lookup(font, C2SC_LOOKUP, "c2sc", SMCP_LOOKUP, c2sc)
    return len(smcp), len(c2sc), liga[0] if liga else None


# --------------------------------------------------------------------------- #
def process(path):
    font = fontforge.open(path)
    existing = [g.glyphname for g in font.glyphs() if g.glyphname.endswith(".sc")]
    if existing:
        raise SystemExit(f"{path}: already has {len(existing)} .sc glyphs; remove them first")
    if any(l.startswith("'smcp'") for l in font.gsub_lookups):
        raise SystemExit(f"{path}: already has an smcp lookup")

    cap_h = measure(font, "HIOX", "top")
    xht_h = measure(font, "xuvw", "top")
    if cap_h is None or xht_h is None:
        raise SystemExit(f"{path}: could not measure cap height / x-height")
    ratio = xht_h * SC_HEIGHT_RATIO / cap_h
    if font.fontname not in EMBOLDEN_UNITS:
        raise SystemExit(f"{path}: no emboldening value for {font.fontname}; add one to EMBOLDEN_UNITS")
    embolden = EMBOLDEN_UNITS[font.fontname]
    tracking = round(font.em * TRACKING_RATIO)

    plain, composite, capset = build_glyphs(font, ratio, embolden, tracking)
    kern_stats = build_kerning(font, ratio, capset)
    n_smcp, n_c2sc, liga = build_features(font, capset)

    if MODE == "apply":
        font.save(path)

    verb = "created" if MODE == "apply" else "would create"
    print("\n" + "=" * 72)
    print(f"{font.fontname}   (scale {ratio:.4f}, embolden +{embolden}u, tracking +{tracking}u/side)")
    print("=" * 72)
    print(f"{verb} {len(plain)} plain + {len(composite)} composite small caps")
    for key, value in kern_stats.items():
        print(f"kerning {key}: {value}")
    print(f"smcp: {n_smcp} substitutions, c2sc: {n_c2sc}, inserted before {liga}")
    font.close()


def main():
    for path in FILES:
        process(path)
    if MODE != "apply":
        print("\n(report mode -- no changes written; re-run with 'apply' to save)")


main()
