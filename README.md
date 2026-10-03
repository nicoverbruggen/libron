# <img src="./icon.png" width=20px> Libron

**Libron** is a modified version of [Readerly](https://github.com/nicoverbruggen/readerly) with various edits to give the font a more neutral look. 

The original font was imported and has been manually edited using [FontForge](https://fontforge.org). All modified source files are available in the `src` directory.

## Specimen

<img src="./specimen.svg" width=400px>

## General changes

Libron started as an attempt to make Readerly feel a little more appropriate for reading on e-readers. Some of the more expressive details that are part of Readerly stood out more than I wanted.

In particular, some of the serifs and capital forms seemed too distracting as I was reading.

What started as a few tweaks to the serifs to make the different font files a little more neutral has gradually developed into a broader reworking of Readerly's design:

- Many uppercase and lowercase letters, figures and punctuation marks have now been redrawn or refined across all four styles. 
- Spacing and kerning have been adjusted alongside the outlines to create a more even reading texture.
- Accented characters have been rebuilt where necessary, so that they remain consistent with their base glyphs.
- Synthetic small caps were added to the font, based on scaled down capitals for each four styles.

The result keeps Readerly's proportions and overall character, but has a calmer and more neutral appearance intended specifically for reading books. As such, it is a successor to Readerly.

## Building Libron

### Automatic builds

When a commit of Libron is tagged, a version is automatically released. The version number set in [VERSION](./VERSION) is used when building the font, and is embedded within the font.

The following variants are generated:

- Libron for desktop (`TTF`)
- Libron for [Kobo devices](https://github.com/nicoverbruggen/kobo-font-fix) (`KF TTF`)
- Libron's webfont variant (`WOFF2`) 

Libron for devices running CrossPoint Reader (`cpfont`) is built and published in [ebook-fonts](https://github.com/nicoverbruggen/ebook-fonts).

### Building locally

You can run `./local-build.sh` if you have Podman installed to build the definitive fonts. If you have all dependencies installed locally, you can also use `./build.py` to build the font with Python.

## Language coverage

Libron has broad Latin coverage, including Vietnamese, plus modern and polytonic Greek and Cyrillic in all four styles. Greek and Cyrillic come from Source Serif 4, fitted to Libron's height and thickness. Bulgarian, Serbian and Macedonian localized forms are retained. Modern and polytonic Greek use Literata's accent and breathing-mark outlines, fitted onto the existing Greek letters. The Greek Extended block and combining breathing marks, circumflex and iota subscript are supported. Capital breathing marks and accents sit to the left; length marks sit above. Iota subscripts sit below both lowercase and capital letters. Greek small caps are available in regular and bold, including the polytonic forms.

The imported glyphs were fitted at optical size `9`, weight `450` for regular and italic, `650` for bold, and `675` for bold italic. Capitals and lowercase were fitted separately. The SFD masters contain the fitted outlines, combining-mark positioning and localized forms. The build exports them directly and preserves Libron's typographic line spacing.

The Greek marks come from Literata 3.103 at optical size `12`, with weights `400` and `700` for regular and bold and their corresponding italics. The marks are scaled uniformly to the Greek lowercase height; combined marks retain Literata's internal spacing. The fitted outlines are stored in the SFD masters and need no additional build dependency.

Greek and Cyrillic letters use Libron's Latin shapes where Source Serif shares those shapes and Libron has the corresponding Latin glyph. This includes shared small caps and localized forms. Related accented forms retain their Greek or Cyrillic marks, fitted to the new bases. Small caps retain the existing Greek and Cyrillic small-cap heights. The remaining donor italic letters are sheared to match Libron's drawn stem angles, with separate adjustments for capitals and lowercase. Accents follow the fitted bases without changing their shapes.

All glyph edits now belong in the Libron SFD masters. The donor-fitting recipe and original Latin masters remain available in the Git history before the migration.

After a full build with Kobo variants, run `python3 -m unittest discover -s tests` in the same container to check coverage, canonical accent spellings and localized shaping.

## License

This font is available under the [OFL license](./LICENSE).
