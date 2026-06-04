#!/usr/bin/env fontforge -lang=py -script
"""
fix_caps_marks.py — recompose the baked capital glyphs that carry a top mark
(e.g. Ṽ Ẍ Ḱ Ṗ ...) into references, so their accents are positioned by the
font's own .case-mark system instead of hand-baked outlines.

Capitals have no top anchor in this font; common capital accents (Á À Â ...) are
built from `.case` marks placed at the base's case-center, with stacked marks
offset by a per-weight (Δx, Δy) that encodes the italic slant. This script learns
both from existing composites and applies them to the leftover baked capitals.

    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        fontforge -lang=py -script /work/scripts/fix_caps_marks.py report   # or apply

Below-marks (cedilla/ogonek/dot-below) keep anchor placement on the cap's bottom
anchor. Anything that can't be resolved is skipped and reported, never guessed.
"""
import fontforge, unicodedata, sys

FILES = ["/work/src/Libron-%s.sfd" % w for w in
         ("Regular", "Bold", "Italic", "BoldItalic")]
MODE = sys.argv[1] if len(sys.argv) > 1 else "report"


def derive_scale(font):
    from collections import Counter
    c = Counter()
    for g in font.glyphs():
        for r in g.references:
            s = (round(r[1][0], 5), round(r[1][3], 5))
            if s != (1.0, 1.0):
                c[s] += 1
    return c.most_common(1)[0][0] if c else (1.0, 1.0)


def case_center_map(font):
    """base-glyphname -> case-center x, from existing `Letter + mark.case` composites."""
    m = {}
    for g in font.glyphs():
        rf = g.references
        cc = [r for r in rf if r[0].endswith(".case")]
        bases = [r for r in rf if not r[0].endswith(".case")]
        if len(bases) == 1 and cc and bases[0][1][:4] == (1, 0, 0, 1):
            # lowest .case mark sits at the base case-center
            low = min(cc, key=lambda r: r[1][5])
            m.setdefault(bases[0][0], set()).add(round(low[1][4]))
    return {k: next(iter(v)) for k, v in m.items() if len(v) == 1}


def stack_delta(font):
    """(dx, dy) to go from the lower .case mark to the upper one, learned from
    existing two-.case-mark capitals (e.g. uni022A = O + diaeresis.case + macron.case)."""
    ds = []
    for g in font.glyphs():
        cc = [r for r in g.references if r[0].endswith(".case")]
        if len(cc) == 2:
            lo, hi = sorted(cc, key=lambda r: r[1][5])
            ds.append((hi[1][4] - lo[1][4], hi[1][5] - lo[1][5]))
    if not ds:
        return None
    return (round(sum(d[0] for d in ds) / len(ds)), round(sum(d[1] for d in ds) / len(ds)))


def base_anchor(g, cls):
    for a in g.anchorPoints:
        if a[1] == "base" and a[0] == cls:
            return (a[2], a[3])
    return None


def process(path):
    font = fontforge.open(path)
    scale = derive_scale(font)
    centers = case_center_map(font)
    delta = stack_delta(font)
    uni2g = {g.unicode: g for g in font.glyphs() if g.unicode and g.unicode > 0}

    done, skip = [], []
    for g in list(font.glyphs()):
        if g.references or len(g.foreground) == 0 or not g.unicode or g.unicode <= 0:
            continue
        try:
            ch = chr(g.unicode)
        except ValueError:
            continue
        nfd = unicodedata.normalize("NFD", ch)
        if len(nfd) < 2 or nfd == ch or unicodedata.category(nfd[0]) != "Lu":
            continue
        marks = [ord(c) for c in nfd[1:]]
        above = [cp for cp in marks if unicodedata.combining(chr(cp)) == 230]
        below = [cp for cp in marks if unicodedata.combining(chr(cp)) != 230]
        if not above:
            continue                                  # below-only caps look fine baked
        base_g = uni2g.get(ord(nfd[0]))
        if base_g is None or any(cp not in uni2g for cp in marks):
            skip.append((g.glyphname, "missing base/mark")); continue

        refs = [(base_g.glyphname, (1.0, 0, 0, 1.0, 0, 0))]

        # below-marks: anchor onto the cap's bottom anchor, scaled comb mark
        ok = True
        for cp in below:
            m = uni2g[cp]
            ma = next((a for a in m.anchorPoints if a[1] == "mark"
                       and base_anchor(base_g, a[0])), None)
            if ma is None:
                ok = False; break
            bx, by = base_anchor(base_g, ma[0])
            sx, sy = scale
            refs.append((m.glyphname, (sx, 0, 0, sy,
                                       float(round(bx - sx * ma[2])),
                                       float(round(by - sy * ma[3])))))
        if not ok:
            skip.append((g.glyphname, "below-mark has no matching cap anchor")); continue

        # above-marks: .case variants, lowest at case-center, stacking up by delta
        cx = centers.get(base_g.glyphname, round(base_g.width / 2))
        if len(above) > 1 and delta is None:
            skip.append((g.glyphname, "no stacking exemplar for 2 above-marks")); continue
        miss = [uni2g[cp].glyphname for cp in above
                if (uni2g[cp].glyphname + ".case") not in font]
        if miss:
            skip.append((g.glyphname, "no .case for " + ",".join(miss))); continue
        for i, cp in enumerate(above):
            cm = uni2g[cp].glyphname + ".case"
            x = cx + (delta[0] * i if delta else 0)
            y = (delta[1] * i if delta else 0)
            refs.append((cm, (1.0, 0, 0, 1.0, float(x), float(y))))

        done.append((g.glyphname, ch, [r[0] for r in refs]))
        if MODE == "apply":
            w = g.width
            g.clear()
            g.references = tuple(refs)
            g.width = w

    if MODE == "apply":
        font.save(path)
    return path.split("/")[-1], scale, centers.get("V"), delta, done, skip


for path in FILES:
    name, scale, _, delta, done, skip = process(path)
    print("\n" + "=" * 68)
    print("%s   scale=%.5f/%.5f  stack-delta=%s" % (name, scale[0], scale[1], delta))
    print("=" * 68)
    print("recomposed=%d  skipped=%d" % (len(done), len(skip)))
    for nm, ch, comps in done:
        print("  + %-10s %s  %s" % (nm, ch, " + ".join(comps)))
    for nm, why in skip:
        print("  ! %-10s %s" % (nm, why))
