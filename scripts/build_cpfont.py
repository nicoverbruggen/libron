#!/usr/bin/env python3
"""Build CrossPoint Reader bundles from Libron's exported TTFs.

Run build.py first. Each file in out/cpfont/Libron contains all four styles
at one reading size. Copy the Libron directory into /fonts on the SD card.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
CONVERTER_COMMIT = "2ceeeccd5ae8f2693eef71388d3f0a4137c1fcc9"
CONVERTER_URL = (
    "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-reader/"
    f"{CONVERTER_COMMIT}/lib/EpdFont/scripts"
)
CONVERTER_FILES = ("fontconvert_sdcard.py", "cpfont_version.py")
SIZES = (12, 14, 16, 18)
LINE_PERCENT = 35
STYLE_FLAGS = {
    "Regular": "--regular",
    "Bold": "--bold",
    "Italic": "--italic",
    "BoldItalic": "--bolditalic",
}


def validate_cpfont(path):
    """Require a CPFONT v4 bundle with 2-bit greyscale and four styles."""
    with path.open("rb") as handle:
        header = handle.read(32)
    if len(header) != 32:
        raise RuntimeError(f"{path}: truncated CPFONT header")
    magic, version, flags, styles = struct.unpack("<8sHHB19x", header)
    if (magic, version, flags, styles) != (b"CPFONT\0\0", 4, 1, 4):
        raise RuntimeError(f"{path}: unexpected CPFONT header")


def prepare_font(source, destination):
    """Match ebook-fonts' relaxed spacing without changing the exported TTF."""
    copied = destination / source.name
    shutil.copy2(source, copied)
    subprocess.run(
        ["font-line", "percent", str(LINE_PERCENT), str(copied)],
        check=True, capture_output=True, text=True,
    )
    relaxed = copied.with_name(f"{copied.stem}-linegap{LINE_PERCENT}.ttf")
    with TTFont(relaxed) as font:
        os2, hhea = font["OS/2"], font["hhea"]
        os2.sTypoAscender = hhea.ascent
        os2.sTypoDescender = hhea.descent
        os2.sTypoLineGap = hhea.lineGap
        font.save(relaxed)
    return relaxed


def build_crosspoint(ttf_dir, out_dir, temporary_dir, family="Libron"):
    if not shutil.which("font-line"):
        raise RuntimeError("font-line is required. Run in the fntbld-oci container.")
    work = Path(temporary_dir) / "crosspoint"
    work.mkdir(parents=True, exist_ok=True)
    converter_dir = work / "converter"
    converter_dir.mkdir(exist_ok=True)
    for filename in CONVERTER_FILES:
        target = converter_dir / filename
        print(f"  Downloading pinned CrossPoint converter: {filename}")
        urllib.request.urlretrieve(f"{CONVERTER_URL}/{filename}", target)

    # Build in temporary storage. Replace the output only after all sizes pass.
    family_dir = work / family
    command = [
        sys.executable, str(converter_dir / "fontconvert_sdcard.py"),
        "--intervals", "reading",
        "--sizes", ",".join(map(str, SIZES)),
        "--name", family,
        "--output-dir", str(family_dir),
    ]
    for style, flag in STYLE_FLAGS.items():
        source = Path(ttf_dir) / f"{family}-{style}.ttf"
        command.extend((flag, str(prepare_font(source, work))))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"CrossPoint converter exited with code {result.returncode}")
    for size in SIZES:
        validate_cpfont(family_dir / f"{family}_{size}.cpfont")

    destination = Path(out_dir) / family
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(family_dir, destination)
    total = sum(path.stat().st_size for path in destination.glob("*.cpfont"))
    print(f"  {family}: {len(SIZES)} sizes, four styles, {total / 1024 / 1024:.1f} MB -> {destination}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="libron-crosspoint-") as temporary_dir:
        build_crosspoint(ROOT / "out/ttf", ROOT / "out/cpfont", temporary_dir)
