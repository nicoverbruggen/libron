#!/usr/bin/env python3
"""Diff two builds of Libron (or any TTF family) and emit a Markdown changelog.

Compares three things that actually matter for a release note, per weight:

  * Outlines  - which glyphs were redrawn (own-contour edits). Accented
                composites that merely inherit a reworked base are *not*
                listed here (their glyf entry is unchanged); they surface
                under spacing if their advance width moved.
  * Kerning   - GPOS pair adjustments that were added, removed, or changed.
  * Tracking  - per-glyph advance-width (spacing) changes, grouped by delta.

Hinting (glyf instructions) is ignored, so ttfautohint noise never shows up.

Usage:
    python3 scripts/font_diff.py OLD NEW [-o CHANGELOG.md]

OLD and NEW may each be either a single .ttf file (compared directly) or a
directory containing Libron-<Style>.ttf masters (all shared styles compared).

Run with the container python (has fonttools), e.g.:
    podman run --rm -v "$PWD":/work -w /work \\
        ghcr.io/nicoverbruggen/fntbld-oci:latest \\
        python3 scripts/font_diff.py \\
        /path/to/old-ttf out/ttf -o CHANGELOG.generated.md
"""
import argparse
import os
import sys

from fontTools.ttLib import TTFont

STYLES = ["Regular", "Bold", "Italic", "BoldItalic"]


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #
def outline_sig(glyf, name):
    """A hashable signature of a glyph's *own* outline, ignoring hinting.

    Simple glyphs -> contour points + on-curve flags.
    Composites    -> component references + offsets/transforms.
    A composite whose base glyph is redrawn keeps the same signature, so it is
    not reported as an outline change (it only moves if its width changes).
    """
    g = glyf[name]
    if getattr(g, "numberOfContours", 0) == 0 and not g.isComposite():
        return ("empty",)
    if g.isComposite():
        comps = []
        for c in g.components:
            comps.append((
                c.glyphName,
                getattr(c, "x", None), getattr(c, "y", None),
                getattr(c, "firstPt", None), getattr(c, "secondPt", None),
                getattr(c, "transform", None),
            ))
        return ("composite", tuple(comps))
    g.expand(glyf)
    return (
        "simple",
        tuple(g.endPtsOfContours or ()),
        tuple((int(x), int(y)) for x, y in g.coordinates),
        tuple(f & 1 for f in g.flags),  # on-curve bit only
    )


def _iter_pairpos(gpos):
    """Yield every PairPos subtable in a GPOS table, resolving Extensions."""
    if gpos is None or not hasattr(gpos.table, "LookupList") or gpos.table.LookupList is None:
        return
    for lookup in gpos.table.LookupList.Lookup:
        for sub in lookup.SubTable:
            st = sub
            if lookup.LookupType == 9:  # Extension Positioning
                st = sub.ExtSubTable
            if getattr(st, "LookupType", lookup.LookupType) == 2 or hasattr(st, "PairSet") or hasattr(st, "Class1Record"):
                yield st


def kern_pairs(font):
    """Return {(left, right): xAdvance} for all nonzero GPOS pair kerns."""
    pairs = {}
    if "GPOS" not in font:
        return pairs
    for st in _iter_pairpos(font["GPOS"]):
        fmt = getattr(st, "Format", None)
        if fmt == 1 or hasattr(st, "PairSet"):
            first = st.Coverage.glyphs
            for gi, pairset in zip(first, st.PairSet):
                for rec in pairset.PairValueRecord:
                    v = getattr(getattr(rec, "Value1", None), "XAdvance", 0) or 0
                    if v:
                        pairs[(gi, rec.SecondGlyph)] = v
        elif fmt == 2 or hasattr(st, "Class1Record"):
            first = st.Coverage.glyphs
            c1 = st.ClassDef1.classDefs if st.ClassDef1 else {}
            c2 = st.ClassDef2.classDefs if st.ClassDef2 else {}
            # class -> glyphs
            g1 = {}
            for g in first:
                g1.setdefault(c1.get(g, 0), []).append(g)
            g2 = {}
            for g in font.getGlyphOrder():
                g2.setdefault(c2.get(g, 0), []).append(g)
            for cls1, rec1 in enumerate(st.Class1Record):
                for cls2, rec2 in enumerate(rec1.Class2Record):
                    v = getattr(getattr(rec2, "Value1", None), "XAdvance", 0) or 0
                    if not v:
                        continue
                    for lg in g1.get(cls1, ()):
                        for rg in g2.get(cls2, ()):
                            pairs[(lg, rg)] = v
    return pairs


def widths(font):
    """{glyphName: advanceWidth}."""
    hmtx = font["hmtx"]
    return {g: hmtx[g][0] for g in font.getGlyphOrder()}


def rev_cmap(font):
    """{glyphName: 'char'} for glyphs with a Unicode mapping, for readability."""
    out = {}
    for cp, name in font.getBestCmap().items():
        out.setdefault(name, chr(cp))
    return out


# --------------------------------------------------------------------------- #
# Per-style comparison
# --------------------------------------------------------------------------- #
def label(name, cmap):
    ch = cmap.get(name)
    return f"`{name}`" + (f" ({ch})" if ch and ch != name else "")


def compare_style(old_path, new_path):
    old, new = TTFont(old_path), TTFont(new_path)
    ocmap, ncmap = rev_cmap(old), rev_cmap(new)
    cmap = {**ocmap, **ncmap}

    oglyf, nglyf = old["glyf"], new["glyf"]
    oset, nset = set(old.getGlyphOrder()), set(new.getGlyphOrder())
    shared = oset & nset

    # Outlines (own-contour edits only)
    reworked = sorted(
        g for g in shared
        if outline_sig(oglyf, g) != outline_sig(nglyf, g)
    )
    added = sorted(nset - oset)
    removed = sorted(oset - nset)

    # Kerning
    ok, nk = kern_pairs(old), kern_pairs(new)
    kern_added, kern_removed, kern_changed = [], [], []
    for pair in sorted(set(ok) | set(nk)):
        ov, nv = ok.get(pair), nk.get(pair)
        if ov == nv:
            continue
        if ov is None:
            kern_added.append((pair, nv))
        elif nv is None:
            kern_removed.append((pair, ov))
        else:
            kern_changed.append((pair, ov, nv))

    # Tracking / spacing (advance widths)
    ow, nw = widths(old), widths(new)
    width_changes = {}  # glyph -> (old, new)
    for g in shared:
        if ow[g] != nw[g]:
            width_changes[g] = (ow[g], nw[g])

    def comp(g):
        return nglyf[g].isComposite()

    return {
        "cmap": cmap,
        "reworked": reworked, "added": added, "removed": removed,
        "redrawn_base": [g for g in reworked if not comp(g)],
        "redrawn_comp": [g for g in reworked if comp(g)],
        "kern_added": kern_added, "kern_removed": kern_removed,
        "kern_changed": kern_changed,
        "width_changes": width_changes,
        "spacing_base": [g for g in width_changes if not comp(g)],
        "is_composite": {g: comp(g) for g in width_changes},
    }


def render_style(style, r):
    cmap = r["cmap"]
    L = lambda n: label(n, cmap)
    out = [f"### {style}\n"]
    changed = any([
        r["reworked"], r["added"], r["removed"],
        r["kern_added"], r["kern_removed"], r["kern_changed"], r["width_changes"],
    ])
    if not changed:
        out.append("_No changes._\n")
        return "\n".join(out)

    # Outlines
    if r["reworked"] or r["added"] or r["removed"]:
        out.append("**Outlines**\n")
        if r["reworked"]:
            out.append(f"- Redrawn ({len(r['reworked'])}): " +
                       ", ".join(L(g) for g in r["reworked"]))
        if r["added"]:
            out.append(f"- Added ({len(r['added'])}): " +
                       ", ".join(L(g) for g in r["added"]))
        if r["removed"]:
            out.append(f"- Removed ({len(r['removed'])}): " +
                       ", ".join(L(g) for g in r["removed"]))
        out.append("")

    # Kerning
    if r["kern_added"] or r["kern_removed"] or r["kern_changed"]:
        out.append("**Kerning**\n")
        for (l, rt), v in r["kern_added"]:
            out.append(f"- Added {L(l)} → {L(rt)}: {v:+d}")
        for (l, rt), v in r["kern_removed"]:
            out.append(f"- Removed {L(l)} → {L(rt)} (was {v:+d})")
        for (l, rt), ov, nv in r["kern_changed"]:
            out.append(f"- {L(l)} → {L(rt)}: {ov:+d} → {nv:+d} ({nv-ov:+d})")
        out.append("")

    # Tracking / spacing, grouped by delta, base letters first
    if r["width_changes"]:
        out.append("**Tracking / spacing (advance width)**\n")
        base = {g: d for g, d in r["width_changes"].items() if not r["is_composite"][g]}
        comp = {g: d for g, d in r["width_changes"].items() if r["is_composite"][g]}
        if base:
            for g in sorted(base):
                o, n = base[g]
                out.append(f"- {L(g)}: {o} → {n} ({n-o:+d})")
        if comp:
            # collapse inherited composite shifts by delta
            by_delta = {}
            for g, (o, n) in comp.items():
                by_delta.setdefault(n - o, []).append(g)
            out.append(f"- _Inherited by {len(comp)} composites:_")
            for delta in sorted(by_delta):
                gs = ", ".join(L(g) for g in sorted(by_delta[delta]))
                out.append(f"  - {delta:+d}: {gs}")
        out.append("")

    return "\n".join(out)


def _is_base(name, cmap):
    """A base glyph = one mapped to a single ASCII letter (A-Z / a-z)."""
    c = cmap.get(name)
    return bool(c and len(c) == 1 and c.isascii() and c.isalpha())


def render_summary(rows):
    """A compact, base-glyph-focused changelog section: one table per category.

    Kerning and spacing are filtered to base (ASCII-letter) glyphs, so the
    accented-variant noise (which only tracks its base) drops out. Each table
    lists only the weights that actually changed.
    """
    pretty = {"BoldItalic": "Bold Italic"}
    outlines, kerning, spacing, addrem = [], [], [], []

    for style, r in rows:
        cmap, name = r["cmap"], pretty.get(style, style)
        base = lambda g: _is_base(g, cmap)

        rb = [g for g in r["redrawn_base"] if base(g)]
        if rb:
            outlines.append((name, f"`{' '.join(rb)}`"))

        ka = [f"{l}→{rt}" for (l, rt), _ in r["kern_added"] if base(l) and base(rt)]
        kr = [f"{l}→{rt}" for (l, rt), _ in r["kern_removed"] if base(l) and base(rt)]
        kc = [f"{l}→{rt}" for (l, rt), _, _ in r["kern_changed"] if base(l) and base(rt)]
        for action, pairs in (("Added", ka), ("Removed", kr), ("Retuned", kc)):
            if pairs:
                kerning.append((name, action, f"`{' '.join(pairs)}`"))

        sb = sorted(g for g in r["spacing_base"] if base(g))
        if sb:
            spacing.append((name, f"`{' '.join(sb)}`"))

        if r["added"] or r["removed"]:
            addrem.append(f"{name}: +{len(r['added'])} / −{len(r['removed'])}")

    out = []

    def table(intro, headers, items):
        if not items:
            return
        out.append(intro)
        out.append("")
        out.append("| " + " | ".join(headers) + " |")
        out.append("|" + "|".join(["---"] * len(headers)) + "|")
        out.extend("| " + " | ".join(row) + " |" for row in items)
        out.append("")

    table("The following outlines have been adjusted:", ["Weight", "Glyphs"], outlines)
    table("The following kern changes have been made:", ["Weight", "Change", "Pairs"], kerning)
    table("Spacing has been adjusted:", ["Weight", "Glyphs"], spacing)
    if addrem:
        out.extend(["Glyphs added / removed: " + "; ".join(addrem) + ".", ""])

    return "\n".join(out).rstrip()


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #
def resolve(path, family=None):
    """Return {style: ttf_path}. `path` may be a file or a directory.

    A directory may hold several families (e.g. a shared fonts folder), so we
    group `<family>-<Style>.ttf` by family. If exactly one family is present it
    is used; otherwise --family must disambiguate. This avoids silently picking
    an unrelated family's Regular.
    """
    if os.path.isfile(path):
        return {"": path}
    per_style = {}          # style -> list of (family, filepath)
    families = set()
    for style in STYLES:
        suf = f"-{style.lower()}.ttf"
        for fn in sorted(os.listdir(path)):
            if fn.lower().endswith(suf):
                fam = fn[: -len(suf)]
                per_style.setdefault(style, []).append((fam, os.path.join(path, fn)))
                families.add(fam)
    if not families:
        sys.exit(f"error: no <family>-<Style>.ttf files found in {path}")
    if family is None:
        if len(families) == 1:
            family = next(iter(families))
        else:
            sys.exit(f"error: {path} holds multiple families "
                     f"({', '.join(sorted(families))}); pass --family NAME")
    found = {}
    for style, cands in per_style.items():
        for fam, fp in cands:
            if fam.lower() == family.lower():
                found[style] = fp
                break
    if not found:
        sys.exit(f"error: no '{family}-<Style>.ttf' in {path} "
                 f"(available: {', '.join(sorted(families))})")
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", help="old TTF file or directory of masters")
    ap.add_argument("new", help="new TTF file or directory of masters")
    ap.add_argument("-o", "--out", help="write Markdown here (default: stdout)")
    ap.add_argument("--title", default="Changelog", help="H1 title")
    ap.add_argument("--family", help="family name to select when a directory "
                                     "holds several (e.g. Libron)")
    ap.add_argument("--summary", action="store_true",
                    help="emit one dense table across weights instead of the "
                         "full per-glyph / per-pair listing")
    args = ap.parse_args()

    old_map, new_map = resolve(args.old, args.family), resolve(args.new, args.family)
    styles = [s for s in ([""] + STYLES) if s in old_map and s in new_map]
    if not styles:
        sys.exit("error: no matching styles between the two inputs")

    def ver(path):
        try:
            v = TTFont(path)["name"].getDebugName(5) or "?"
            return v.split(";")[0].strip()  # drop "; ttfautohint (...)"
        except Exception:
            return "?"

    results = [(style, compare_style(old_map[style], new_map[style])) for style in styles]
    md = [f"# {args.title}\n"]
    if args.summary:
        md.append(render_summary(results))
    else:
        md.append(f"_{ver(old_map[styles[0]])} → {ver(new_map[styles[0]])}_\n")
        for style, r in results:
            md.append(render_style(style or os.path.basename(old_map[style]), r))

    text = "\n".join(md).rstrip() + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
