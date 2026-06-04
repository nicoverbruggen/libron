#!/usr/bin/env fontforge -lang=py -script
"""
recompose_accents.py — rebuild accented composites so the *composed* (anchor-derived)
position is used, instead of stale reference offsets or baked-in decomposed outlines.

Run inside the fntbld-oci container (which ships FontForge + Python):

    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        fontforge -lang=py -script /work/scripts/recompose_accents.py report
    podman run --rm -v "$PWD":/work ghcr.io/nicoverbruggen/fntbld-oci \
        fontforge -lang=py -script /work/scripts/recompose_accents.py apply

Two passes:
  PASS A  recompute the translation of every anchor-based composite that already uses
          references, KEEPING its existing scale and component choice. Fixes stale
          offsets (e.g. the agrave family) with zero design change.
  PASS B  recompose decomposed canonical composites (uni01CE, Ccedilla, ...) into
          references:
            - lowercase / anchored bases  -> scaled comb marks placed via anchors
            - uppercase bases             -> .case marks + the x-offset learned from
                                             sibling uppercase composites of that base
          Anything that can't be resolved faithfully is SKIPPED and reported, never guessed.
"""
import fontforge, unicodedata, sys, os

FILES = [
    "/work/src/Libron-Regular.sfd",
    "/work/src/Libron-Bold.sfd",
    "/work/src/Libron-Italic.sfd",
    "/work/src/Libron-BoldItalic.sfd",
]
MODE = sys.argv[1] if len(sys.argv) > 1 else "report"


def has_mark_anchor(g):
    return any(a[1] == "mark" for a in g.anchorPoints)


def derive_scale(font):
    """Most common non-identity (sx,sy) among existing mark references."""
    from collections import Counter
    c = Counter()
    for g in font.glyphs():
        for r in g.references:
            sx, sy = round(r[1][0], 5), round(r[1][3], 5)
            if (sx, sy) != (1.0, 1.0):
                c[(sx, sy)] += 1
    return c.most_common(1)[0][0] if c else (1.0, 1.0)


def case_offset_map(font):
    """base-glyphname -> x offset, learned from existing `Letter + mark.case` composites."""
    m = {}
    for g in font.glyphs():
        refs = g.references
        if len(refs) != 2:
            continue
        (n0, t0), (n1, t1) = (refs[0][0], refs[0][1]), (refs[1][0], refs[1][1])
        # base ref identity, mark ref is a `.case` mark at identity scale
        if n1.endswith(".case") and round(t1[0], 5) == 1.0 and round(t1[3], 5) == 1.0 \
           and t0[:4] == (1, 0, 0, 1):
            m.setdefault(n0, set()).add(round(t1[4]))
    # keep only bases with a single consistent offset
    return {k: next(iter(v)) for k, v in m.items() if len(v) == 1}


def place_anchored(base_g, marks_with_scale):
    """Resolve base + marks via matching anchor classes. Order is discovered dynamically,
    so single marks and stacks both work. Returns ref list or None if unresolvable."""
    refs = [(base_g.glyphname, (1.0, 0, 0, 1.0, 0, 0))]
    providers = {}  # class -> (x, y) in composed space
    for a in base_g.anchorPoints:
        if a[1] == "base":
            providers[a[0]] = (a[2], a[3])
    remaining = list(marks_with_scale)
    while remaining:
        progressed = False
        for i, (m, (sx, sy)) in enumerate(remaining):
            chosen = next((a for a in m.anchorPoints
                           if a[1] == "mark" and a[0] in providers), None)
            if chosen is None:
                continue
            cls, mx, my = chosen[0], chosen[2], chosen[3]
            px, py = providers[cls]
            tx, ty = px - sx * mx, py - sy * my
            refs.append((m.glyphname, (sx, 0, 0, sy, float(round(tx)), float(round(ty)))))
            del providers[cls]                       # a base anchor hosts one mark
            for a in m.anchorPoints:                 # expose this mark's stack anchors
                if a[1] == "basemark":
                    providers[a[0]] = (sx * a[2] + tx, sy * a[3] + ty)
            remaining.pop(i)
            progressed = True
            break
        if not progressed:
            return None
    return refs


def process(path):
    font = fontforge.open(path)
    scale = derive_scale(font)
    coff = case_offset_map(font)
    uni2glyph = {g.unicode: g for g in font.glyphs() if g.unicode and g.unicode > 0}

    a_changed, a_same = [], 0
    b_done, b_skip = [], []

    # ---- PASS A: recompute existing anchor-based composites in place ----
    for g in font.glyphs():
        refs = g.references
        if not refs:
            continue
        bases = [r for r in refs if not has_mark_anchor(font[r[0]])]
        marks = [r for r in refs if has_mark_anchor(font[r[0]])]
        if len(bases) != 1 or not marks:
            continue                                  # uppercase(.case)/unusual -> leave
        base_g = font[bases[0][0]]
        new = place_anchored(base_g, [(font[r[0]], (r[1][0], r[1][3])) for r in marks])
        if new is None:
            continue
        old = [(r[0], tuple(round(x, 3) for x in r[1])) for r in refs]
        new_r = [(n, tuple(round(x, 3) for x in t)) for n, t in new]
        # only a translation shift > 0.5u counts as a real change (ignore sub-unit churn)
        old_t = {n: (t[4], t[5]) for n, t in old}
        real = any(n not in old_t
                   or abs(t[4] - old_t[n][0]) > 0.5 or abs(t[5] - old_t[n][1]) > 0.5
                   for n, t in new_r)
        if real:
            a_changed.append((g.glyphname, old, new_r))
            if MODE == "apply":
                g.references = tuple(new)
        else:
            a_same += 1

    # ---- PASS B: recompose decomposed canonical composites ----
    for g in font.glyphs():
        if g.references or len(g.foreground) == 0 or not g.unicode or g.unicode <= 0:
            continue
        try:
            ch = chr(g.unicode)
        except ValueError:
            continue
        nfd = unicodedata.normalize("NFD", ch)
        if len(nfd) < 2 or nfd == ch:
            continue                                  # not a composite
        base_cp, mark_cps = ord(nfd[0]), [ord(c) for c in nfd[1:]]
        if base_cp not in uni2glyph or any(cp not in uni2glyph for cp in mark_cps):
            b_skip.append((g.glyphname, "missing base/mark glyph"))
            continue
        base_g = uni2glyph[base_cp]
        upper = unicodedata.category(nfd[0]) == "Lu"

        # soft-dotted i/j drop their dot under an above-mark -> use the dotless base
        if base_cp in (0x69, 0x6A):
            above = any(a[1] == "mark" and a[0] == "Anchor-0"
                        for cp in mark_cps for a in uni2glyph[cp].anchorPoints)
            dl = "dotlessi" if base_cp == 0x69 else "uni0237"
            if above and dl in font:
                base_g = font[dl]

        built = None
        if not upper:                                 # lowercase / anchored regime
            built = place_anchored(
                base_g, [(uni2glyph[cp], scale) for cp in mark_cps])
            why = "anchored"
        if built is None and len(mark_cps) == 1:      # uppercase .case regime
            case_mark = font[uni2glyph[mark_cps[0]].glyphname + ".case"] \
                if (uni2glyph[mark_cps[0]].glyphname + ".case") in font else None
            if case_mark is not None and base_g.glyphname in coff:
                built = [(base_g.glyphname, (1.0, 0, 0, 1.0, 0, 0)),
                         (case_mark.glyphname,
                          (1.0, 0, 0, 1.0, float(coff[base_g.glyphname]), 0.0))]
                why = "case-offset"
        if built is None:
            b_skip.append((g.glyphname, "unresolved (%s base, %d marks)"
                           % ("upper" if upper else "lower", len(mark_cps))))
            continue

        b_done.append((g.glyphname, why, [r[0] for r in built]))
        if MODE == "apply":
            w = g.width
            g.clear()
            g.references = tuple(built)
            g.width = w

    if MODE == "apply":
        font.save(path)

    return os.path.basename(path), scale, a_changed, a_same, b_done, b_skip


def main():
    for path in FILES:
        name, scale, a_changed, a_same, b_done, b_skip = process(path)
        print("\n" + "=" * 72)
        print("%s   (mark scale %.5f / %.5f)" % (name, scale[0], scale[1]))
        print("=" * 72)
        print("PASS A  recomputed=%d  unchanged=%d" % (len(a_changed), a_same))
        for nm, old, new in a_changed:
            om = dict((n, t) for n, t in old)
            nm_ = dict((n, t) for n, t in new)
            for k in nm_:
                if om.get(k) != nm_[k]:
                    print("    %-16s %-18s %s -> %s" % (nm, k, om.get(k), nm_[k]))
        print("PASS B  recomposed=%d  skipped=%d" % (len(b_done), len(b_skip)))
        for nm, why, comps in b_done:
            print("    + %-16s [%s] %s" % (nm, why, " + ".join(comps)))
        if b_skip:
            print("  -- skipped (left decomposed, need manual review) --")
            for nm, reason in b_skip:
                print("    ! %-16s %s" % (nm, reason))


main()
