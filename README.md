# Libron

Libron is a modified version of [Readerly](https://github.com/nicoverbruggen/readerly) with various edits to make its serifs, which I found a little exaggerated, less pronounced, which gives the font a more neutral look.

This is an experimental modification, and I may roll these changes into Readerly 2.0 at some point. For now, this is a test font and I'm currently evaluating it.

> [!WARNING]
> Because the starting point of this font was Readerly's static build (regular and italic), this repository generates a fake bold version (bold), unlike Readerly.

## What's next

### Done

- Regular: Numbers, lowercase, uppercase alphabet and bearing (v1)
- Italic: Numbers, lowercase, uppercase alphabet
- Bold: Numbers, uppercase alphabet
- Bold Italic: Numbers

### To do

- Bold: Lowercase alphabet
- Bold italic: Uppercase and lowercase alphabet
- Italic, bold, bold italic left and right bearing checks


## How to build

You can run `./local-build.sh` if you have Podman installed to build the definitive fonts.

## General changes

The changes made to this font are mostly to amend some of the stylistically heavy serifs that were originally part of Newsreader. Due to the size changes applied with Readerly, I figured it would be a good idea to remove certain aspects of the serif design to make it less disruptive and loud when reading books. 

- For example, many capitals have been modified, e.g. `C`, `E`, `F`, `G`, `L` and `S` have very noticeably been trimmed down.
- Certain glyphs have been reworked: `T` is one such example, but some lowercase characters, too, like `d`, `i`, `j`, `t`, `r` and `u`.
- Minor adjustments have been made across the board to serifs, as well.
