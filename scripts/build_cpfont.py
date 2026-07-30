#!/usr/bin/env python3
"""Build CrossPoint Reader CPFONT v4 files for Libron."""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TTF_DIR = ROOT / "out" / "ttf"
DEFAULT_OUTPUT_DIR = ROOT / "out" / "cpfont"
CONVERTER_COMMIT = "2ceeeccd5ae8f2693eef71388d3f0a4137c1fcc9"
CONVERTER_BASE_URL = (
    "https://raw.githubusercontent.com/crosspoint-reader/crosspoint-reader/"
    f"{CONVERTER_COMMIT}/lib/EpdFont/scripts"
)
CONVERTER_FILES = ("fontconvert_sdcard.py", "cpfont_version.py")
STYLES = {
    "regular": TTF_DIR / "Libron-Regular.ttf",
    "bold": TTF_DIR / "Libron-Bold.ttf",
    "italic": TTF_DIR / "Libron-Italic.ttf",
    "bolditalic": TTF_DIR / "Libron-BoldItalic.ttf",
}


def download_converter(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in CONVERTER_FILES:
        target = destination / filename
        if target.is_file():
            continue
        url = f"{CONVERTER_BASE_URL}/{filename}"
        print(f"Downloading pinned CrossPoint converter: {filename}")
        temporary = target.with_suffix(f"{target.suffix}.download")
        try:
            urllib.request.urlretrieve(url, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return destination / "fontconvert_sdcard.py"


def validate_inputs() -> None:
    missing = [str(path.relative_to(ROOT)) for path in STYLES.values() if not path.is_file()]
    if not missing:
        return
    print("Missing built Libron TTFs:", file=sys.stderr)
    for path in missing:
        print(f"  {path}", file=sys.stderr)
    print("\nRun `python3 build.py` first.", file=sys.stderr)
    raise SystemExit(1)


def validate_cpfont(path: Path) -> None:
    header = path.read_bytes()[:32]
    if len(header) != 32:
        raise RuntimeError(f"{path} has a truncated CPFONT header")
    magic, version, flags, style_count = struct.unpack("<8sHHB19x", header)
    if magic != b"CPFONT\x00\x00":
        raise RuntimeError(f"{path} has invalid CPFONT magic")
    if version != 4 or flags != 1 or style_count != 4:
        raise RuntimeError(
            f"{path} has unexpected header values: "
            f"version={version}, flags={flags}, styles={style_count}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default="12,14,16,18",
        help="Comma-separated point sizes (default: 12,14,16,18)",
    )
    parser.add_argument(
        "--intervals",
        default="reading",
        help="CrossPoint interval preset(s) (default: reading)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory (default: out/cpfont)",
    )
    parser.add_argument(
        "--converter-dir",
        type=Path,
        help="Use an existing directory containing the two converter scripts",
    )
    args = parser.parse_args()

    validate_inputs()
    converter_dir = args.converter_dir or ROOT / "tmp" / "crosspoint-converter"
    converter = (
        converter_dir / "fontconvert_sdcard.py"
        if args.converter_dir
        else download_converter(converter_dir)
    )
    version_module = converter_dir / "cpfont_version.py"
    if not converter.is_file() or not version_module.is_file():
        parser.error(
            "--converter-dir must contain fontconvert_sdcard.py and cpfont_version.py"
        )

    output_dir = args.output_dir.resolve()
    command = [
        sys.executable,
        str(converter),
        "--intervals",
        args.intervals,
        "--sizes",
        args.sizes,
        "--name",
        "Libron",
        "--output-dir",
        str(output_dir),
    ]
    for style, path in STYLES.items():
        command.extend((f"--{style}", str(path)))

    subprocess.run(command, check=True)

    sizes = [int(value.strip()) for value in args.sizes.split(",")]
    outputs = [output_dir / f"Libron_{size}.cpfont" for size in sizes]
    for output in outputs:
        validate_cpfont(output)

    print("\nValidated CPFONT v4 outputs:")
    for output in outputs:
        print(f"  {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
