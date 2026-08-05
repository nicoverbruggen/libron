# Changelog

## v0.24

This release adds official support for [CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader) as Libron is now available as the converted `cpfont` files which are compatible with this awesome reader app. Libron is available at 12, 14, 16 and 18 point sizes, with all four styles.

### Fixed accent placement

| Weight | Glyphs |
|---|---|
| Regular | `ù ú û ü ũ ū ŭ ů ű ȕ ȗ ụ ủ` |

The accents on these sat too far to the right, over the right stem of the `u` instead of over the middle of the letter. They are now back on the `u` anchor, which is where the other weights already placed them.

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