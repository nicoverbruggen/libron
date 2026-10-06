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
import unicodedata

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
    """Yield (lookup index, PairPos subtable) for a GPOS table, resolving Extensions."""
    if gpos is None or not hasattr(gpos.table, "LookupList") or gpos.table.LookupList is None:
        return
    for li, lookup in enumerate(gpos.table.LookupList.Lookup):
        for sub in lookup.SubTable:
            st = sub
            if lookup.LookupType == 9:  # Extension Positioning
                st = sub.ExtSubTable
            if getattr(st, "LookupType", lookup.LookupType) == 2 or hasattr(st, "PairSet") or hasattr(st, "Class1Record"):
                yield li, st


def kern_pairs(font):
    """Return {(left, right): xAdvance} for all nonzero GPOS pair kerns.

    Follows shaper semantics: within one lookup the first subtable that
    matches a pair wins and later subtables are skipped, even when the
    matching value is 0. A per-glyph (format 1) subtable matches only the
    pairs it lists; a class (format 2) subtable matches every pair whose
    left glyph is in its coverage, since class 0 catches any right glyph.
    FontForge writes a per-glyph zero in front of the class matrix to cancel
    a class kern, so this is what makes such resets show up. Values from
    different lookups add up.
    """
    pairs = {}
    if "GPOS" not in font:
        return pairs
    per_lookup = {}
    claimed_pairs = {}   # lookup index -> pairs an earlier subtable matched
    claimed_left = {}    # lookup index -> left glyphs a class subtable matched
    for li, st in _iter_pairpos(font["GPOS"]):
        lookup_pairs = per_lookup.setdefault(li, {})
        taken = claimed_pairs.setdefault(li, set())
        taken_left = claimed_left.setdefault(li, set())
        fmt = getattr(st, "Format", None)
        if fmt == 1 or hasattr(st, "PairSet"):
            first = st.Coverage.glyphs
            for gi, pairset in zip(first, st.PairSet):
                if gi in taken_left:
                    continue
                for rec in pairset.PairValueRecord:
                    key = (gi, rec.SecondGlyph)
                    if key in taken:
                        continue
                    taken.add(key)
                    v = getattr(getattr(rec, "Value1", None), "XAdvance", 0) or 0
                    if v:
                        lookup_pairs[key] = v
        elif fmt == 2 or hasattr(st, "Class1Record"):
            first = [g for g in st.Coverage.glyphs if g not in taken_left]
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
                            if (lg, rg) not in taken:
                                lookup_pairs[(lg, rg)] = v
            taken_left.update(first)
    for lookup_pairs in per_lookup.values():
        for key, v in lookup_pairs.items():
            pairs[key] = pairs.get(key, 0) + v
    return {k: v for k, v in pairs.items() if v}


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
    inherited = _inherited_kerning(added, nset, nk)
    kern_added, kern_removed, kern_changed = [], [], []
    for pair in sorted(set(ok) | set(nk)):
        ov, nv = ok.get(pair), nk.get(pair)
        if ov == nv:
            continue
        if ov is None:
            if pair[0] not in inherited and pair[1] not in inherited:
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

    def parts(glyf, g):
        return sorted(c.glyphName for c in glyf[g].components)

    # A composite that kept its components but moved them while its width
    # changed was re-centered, not redrawn: `two` around `two.lf`.
    recentered = [
        g for g in reworked
        if comp(g) and oglyf[g].isComposite() and g in width_changes
        and parts(oglyf, g) == parts(nglyf, g)
    ]

    return {
        "cmap": cmap,
        "fwd": {ch: n for n, ch in cmap.items()},
        "reworked": reworked, "added": added, "removed": removed,
        "redrawn": [g for g in reworked if g not in recentered],
        "kern_added": kern_added, "kern_removed": kern_removed,
        "kern_changed": kern_changed, "kern_inherited": inherited,
        "width_changes": width_changes,
        "is_composite": {g: comp(g) for g in width_changes},
    }


def _inherited_kerning(added, glyphs, kern):
    """{added glyph: base glyph} for added glyphs that kern exactly like a base.

    The base is the name with trailing dotted suffixes stripped until it hits
    an existing, pre-existing glyph (`Cacute.sc.loclPLK` -> `Cacute.sc`). The
    comparison maps other added glyphs to their base as well, so a pair
    `Cacute.loclPLK` -> `cacute.loclPLK` counts as `Cacute` -> `cacute`.
    Glyphs without any kerning are not reported; there is nothing to list.
    """
    added = set(added)
    base_of = {}
    for g in added:
        parts = g.split(".")
        for i in range(len(parts) - 1, 0, -1):
            cand = ".".join(parts[:i])
            if cand in glyphs and cand not in added:
                base_of[g] = cand
                break
    norm = lambda n: base_of.get(n, n)
    by_left, by_right = {}, {}
    for (l, rt), v in kern.items():
        by_left.setdefault(l, {})[norm(rt)] = v
        by_right.setdefault(rt, {})[norm(l)] = v
    out = {}
    for g, b in base_of.items():
        lg, lb = by_left.get(g, {}), by_left.get(b, {})
        rg, rb = by_right.get(g, {}), by_right.get(b, {})
        if (lg or rg) and lg == lb and rg == rb:
            out[g] = b
    return out


def _own_char(name, cmap):
    """The character a glyph represents, ignoring a style suffix.

    `five.lf` -> '5', `Eogonek.sc` -> 'Ę'. Unencoded glyphs give None. The
    encoded `five` is a composite that merely references the unmapped
    `five.lf`, where the contour lives, so this is what lets an edit to the
    variant show up under its character.
    """
    for cand in (name, name.split(".", 1)[0]):
        c = cmap.get(cand)
        if c and len(c) == 1:
            # show a combining mark on a dotted circle, as code charts do
            return "◌" + c if unicodedata.category(c) == "Mn" else c
    return None


def _stem_char(name, cmap):
    """The unaccented character behind a glyph: `aacute` -> 'a', `k.sc` -> 'k'."""
    c = _own_char(name, cmap)
    if c is None:
        return None
    return unicodedata.normalize("NFD", c[-1])[0]


def _stem_name(name, r):
    """The glyph a variant descends from, keeping its suffix: `aacute.sc` -> `a.sc`."""
    core, dot, suffix = name.partition(".")
    c = _stem_char(core, r["cmap"])
    return r["fwd"].get(c, core) + dot + suffix


def _collapse(entries, r):
    """Group kern entries that only differ by accents on either glyph.

    `entries` holds (pair, *values). Yields (pair, values, count, stem pair):
    the base pair when it is part of the group, else its first member, plus
    how many members the group has. Values must match to merge.
    """
    groups = {}
    for pair, *vals in entries:
        key = (_stem_name(pair[0], r), _stem_name(pair[1], r), tuple(vals))
        groups.setdefault(key, []).append(pair)
    out = []
    for (sl, sr, vals), members in groups.items():
        rep = (sl, sr) if (sl, sr) in members else members[0]
        out.append((rep, vals, len(members), (sl, sr)))
    return sorted(out)


def render_style(style, r):
    cmap = r["cmap"]
    L = lambda n: label(n, cmap)

    def tail(rep, n, stem):
        if n == 1:
            return ""
        forms = "form" if n == 2 else "forms"
        if rep == stem:
            return f" (+{n - 1} accented {forms})"
        return f" (+{n - 1} other {forms} of {L(stem[0])} → {L(stem[1])})"
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
    if r["kern_added"] or r["kern_removed"] or r["kern_changed"] or r["kern_inherited"]:
        out.append("**Kerning**\n")
        for (l, rt), (v,), n, stem in _collapse(r["kern_added"], r):
            out.append(f"- Added {L(l)} → {L(rt)}: {v:+d}{tail((l, rt), n, stem)}")
        for (l, rt), (v,), n, stem in _collapse(r["kern_removed"], r):
            out.append(f"- Removed {L(l)} → {L(rt)} (was {v:+d}){tail((l, rt), n, stem)}")
        for (l, rt), (ov, nv), n, stem in _collapse(r["kern_changed"], r):
            out.append(f"- {L(l)} → {L(rt)}: {ov:+d} → {nv:+d} ({nv-ov:+d}){tail((l, rt), n, stem)}")
        if r["kern_inherited"]:
            pairs = ", ".join(f"{L(g)} as {L(b)}"
                              for g, b in sorted(r["kern_inherited"].items()))
            out.append(f"- Added glyphs kerned the same as their base form: {pairs}")
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


def _own_spacing(g, r):
    """True if a width change is the glyph's own, not inherited from its stem.

    `aacute` widening along with `a` is noise; `Eogonek` changing while `E`
    did not is a real edit. A composite is its own stem when it just wraps
    an unencoded contour glyph, like `two` around `two.lf`.
    """
    if not r["is_composite"][g]:
        return True
    stem = r["fwd"].get(_stem_char(g, r["cmap"]))
    return stem is None or stem == g or stem not in r["width_changes"]


def render_summary(rows):
    """A compact, per-character changelog section: one table per category.

    Outlines and spacing list the character a glyph stands for, with style
    suffixes dropped and inherited width shifts left out. Kerning pairs are
    reduced to their unaccented stems, so `k→a` covers `k→á`. Each table
    lists only the weights that actually changed.
    """
    pretty = {"BoldItalic": "Bold Italic"}
    outlines, kerning, spacing, addrem = [], [], [], []

    def unique(items):
        seen, out = set(), []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out

    for style, r in rows:
        cmap, name = r["cmap"], pretty.get(style, style)
        own = lambda g: _own_char(g, cmap)
        stem = lambda g: _stem_char(g, cmap)

        rb = sorted({own(g) for g in r["redrawn"] if own(g)})
        if rb:
            outlines.append((name, f"`{' '.join(rb)}`"))

        def stems(entries):
            return unique(f"{stem(l)}→{stem(rt)}" for (l, rt), *_ in entries
                          if stem(l) and stem(rt))
        ka, kr, kc = (stems(r[k]) for k in ("kern_added", "kern_removed", "kern_changed"))
        if ka or kr or kc:
            cell = lambda p: f"`{' '.join(p)}`" if p else "—"
            kerning.append((name, cell(ka), cell(kr), cell(kc)))

        sb = sorted({own(g) for g in r["width_changes"] if own(g) and _own_spacing(g, r)})
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

    table("### Adjusted outlines", ["Weight", "Glyphs"], outlines)
    table("### Updated kerning", ["Weight", "Added", "Removed", "Retuned"], kerning)
    table("### Updated spacing", ["Weight", "Glyphs"], spacing)
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
