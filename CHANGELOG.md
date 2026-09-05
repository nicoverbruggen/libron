# Changelog

## v0.25

### Small caps

Libron now has small caps in all four styles, through the `smcp` and `c2sc` features. They are derived from the capitals: scaled to a little above the x-height, thickened to match the lowercase stems, spaced more openly, and kerned from the capitals' own pairs.

**Note**: KOReader, Calibre and browsers use these native small caps correctly. Kobo's built-in reader ignores the `smcp` and `c2sc` font features and shrinks the capitals with its native renderer. Use [NickelTypeFix](https://github.com/nicoverbruggen/NickelTypeFix) to get native small caps working.

## v0.24

Libron now supports [CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader). The converted `cpfont` files are built and published in [ebook-fonts](https://github.com/nicoverbruggen/ebook-fonts), at 12, 14, 16 and 18 point sizes, with all four styles.

### Fixed accent placement

| Weight | Glyphs |
|---|---|
| Regular | `ù ú û ü ũ ū ŭ ů ű ȕ ȗ ụ ủ` |

The accents on these sat too far to the right, over the right stem of the `u` instead of over the middle of the letter. They are now back on the `u` anchor, which is where the other weights already placed them.

As part of this release, v0.10 of [kobofix.py](https://github.com/nicoverbruggen/kobo-font-fix) is now being used to build the `KF` variant of Libron.

## v0.23

As part of this release, v0.9.2 of [kobofix.py](https://github.com/nicoverbruggen/kobo-font-fix) is now being used to build the `KF` variant of Libron.

## v0.22

### Adjusted outlines

| Weight | Glyphs |
|---|---|
| Regular | `S i j s` |
| Bold | `5 C S Z c i j n r` |
| Italic | `5` |

## v0.21

### Adjusted outlines

| Weight | Glyphs |
|---|---|
| Regular | `C E F G K L M N V W Z b c d h i k l m n p r s u v w` |

### Updated kerning

| Weight | Added | Removed | Retuned |
|---|---|---|---|
| Regular | `a→l` | — | — |

### Updated spacing

| Weight | Glyphs |
|---|---|
| Regular | `c` |

## v0.20

### Adjusted outlines

| Weight | Glyphs |
|---|---|
| Regular | `A E F H L a b d g h i j q s t u y z` |
| Bold | `A E F L g q t u y z` |
| Italic | `A E F L` |
| Bold Italic | `A E F L` |

### Updated kerning

| Weight | Added | Removed | Retuned |
|---|---|---|---|
| Regular | `d→c d→e d→o r→i t→h t→k` | `e→s` | `J→a d→v` |
| Italic | — | — | `F→r` |
| Bold Italic | — | — | `F→r` |

### Updated spacing

| Weight | Glyphs |
|---|---|
| Regular | `E F L a d k` |
| Bold | `E F L` |

As part of this release, v0.9.1 of [kobofix.py](https://github.com/nicoverbruggen/kobo-font-fix) is now being used to build the `KF` variant of Libron.

## v0.11

Updated to v0.8 of [kobofix.py](https://github.com/nicoverbruggen/kobo-font-fix) with improved hinting.

## v0.10

Initial public release as the successor to [Readerly](https://github.com/nicoverbruggen/readerly).