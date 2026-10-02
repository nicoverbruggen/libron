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

Libron has broad Latin coverage, including Vietnamese, plus modern Greek and Cyrillic in all four styles. Greek and Cyrillic come from Source Serif 4, fitted to Libron's height and thickness. Bulgarian, Serbian and Macedonian localized forms are retained. Polytonic Greek is not included.

The build uses optical size `9`, weight `450` for regular and italic, `650` for bold, and `675` for bold italic. It fits capitals and lowercase separately and preserves Libron's Latin outlines and typographic line spacing.

The unmodified Source Serif variable fonts in `src` are pinned to [Sourcerer commit `a87decbe`](https://github.com/nicoverbruggen/sourcerer/tree/a87decbe8c5ae349def828b4a0b314c1f2d5d227/src). The build checks their SHA-256 hashes before use. Latin edits remain in the SFD masters; the build adds Greek and Cyrillic through `scripts/expand_scripts.py`.

After a full build with Kobo variants, run `python3 -m unittest discover -s tests` in the same container to check coverage, canonical accent spellings and localized shaping. Each build also checks that importing the scripts preserves every original Latin glyph, advance width and Unicode mapping.

## License

This font is available under the [OFL license](./LICENSE).
