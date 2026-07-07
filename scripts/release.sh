#!/usr/bin/env bash
#
# Prepare a Libron release. This does NOT tag or push -- you do that yourself
# after reviewing the result. It:
#
#   1. Reads the target version from VERSION and refuses to run if a matching
#      tag (vX.Y) already exists (or CHANGELOG.md already has that section).
#   2. Builds the previous release and the current sources, diffs the compiled
#      fonts (outlines / kerning / tracking), and inserts that section at the
#      top of CHANGELOG.md, directly under "# Changelog" and a blank line.
#
# Compiled-font diffing catches everything the source view misses -- notably
# class-based kerning (one big KernClass2 matrix a text diff won't surface).
#
# Usage:
#   scripts/release.sh [BASELINE_TAG]
#
#   BASELINE_TAG   release to diff against (default: newest existing tag)
#   --rebuild      rebuild current TTFs too (default: reuse out/ttf if present)
#
# Requires: podman + the fntbld-oci image (FontForge + fonttools), per AGENTS.md.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

IMAGE="ghcr.io/nicoverbruggen/fntbld-oci:latest"
BASELINE=""
REBUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) BASELINE="$1"; shift ;;
  esac
done

VERSION="$(tr -d '[:space:]' < VERSION)"
TAG="v${VERSION}"

# --- 1. Validate ----------------------------------------------------------- #
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "error: tag ${TAG} already exists -- bump VERSION before releasing" >&2
  exit 1
fi
if grep -qE "^## ${TAG}([[:space:]]|$)" CHANGELOG.md; then
  echo "error: CHANGELOG.md already has a ${TAG} section" >&2
  exit 1
fi

# Baseline = newest existing tag unless one was given.
if [[ -z "$BASELINE" ]]; then
  BASELINE="$(git tag --sort=-version:refname | head -1 || true)"
fi
[[ -z "$BASELINE" ]] && { echo "error: no baseline tag to diff against" >&2; exit 1; }
echo ">> releasing ${TAG}, diffing against ${BASELINE}" >&2

run() { podman run --rm -v "$1":/work -w /work "$IMAGE" "${@:2}"; }

# --- 2a. Builds ------------------------------------------------------------ #
if [[ "$REBUILD" == 1 || ! -f out/ttf/Libron-Regular.ttf ]]; then
  echo ">> building current (${VERSION})" >&2
  run "$REPO" python3 build.py >/dev/null
fi

WT="$(mktemp -d)"
BASE_TTF="$REPO/.release-baseline-ttf"
SECTION="$REPO/.release-section.md"
cleanup() { git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT" "$BASE_TTF" "$SECTION"; }
trap cleanup EXIT

echo ">> building baseline ${BASELINE}" >&2
git worktree add --detach "$WT" "$BASELINE" >/dev/null 2>&1
run "$WT" python3 build.py >/dev/null
rm -rf "$BASE_TTF"; cp -R "$WT/out/ttf" "$BASE_TTF"

# --- 2b. Diff -> section --------------------------------------------------- #
run "$REPO" python3 scripts/font_diff.py .release-baseline-ttf out/ttf \
  --family Libron --summary --title "${TAG}" -o .release-section.md

# Note a bump of the pinned kobo-font-fix (kobofix.py) version, if any.
kobo_ver() { grep -oE 'kobo-font-fix/[^/]+/kobofix\.py' "$1/build.py" \
  | sed -E 's#.*kobo-font-fix/([^/]+)/kobofix\.py#\1#' | head -1; }
OLD_KOBO="$(kobo_ver "$WT" || true)"
NEW_KOBO="$(kobo_ver "$REPO" || true)"
if [[ -n "$NEW_KOBO" && "$OLD_KOBO" != "$NEW_KOBO" ]]; then
  printf '\nAs part of this release, %s of [kobofix.py](https://github.com/nicoverbruggen/kobo-font-fix) is now being used to build the `KF` variant of Libron.\n' \
    "$NEW_KOBO" >> .release-section.md
  echo ">> noted kobo-font-fix bump ${OLD_KOBO:-none} -> ${NEW_KOBO}" >&2
fi

# --- 2c. Insert at the top of CHANGELOG.md --------------------------------- #
python3 - "$TAG" <<'PY'
import sys
tag = sys.argv[1]
sec = open(".release-section.md").read().rstrip("\n").split("\n")
if sec and sec[0].startswith("# "):
    sec[0] = "#" + sec[0]            # "# vX.Y" -> "## vX.Y"
section = "\n".join(sec)

cl = open("CHANGELOG.md").read()
head, _, rest = cl.partition("\n")   # head = "# Changelog"
rest = rest.lstrip("\n")
open("CHANGELOG.md", "w").write(f"{head}\n\n{section}\n\n{rest}")
print(f">> inserted {tag} section at top of CHANGELOG.md", file=sys.stderr)
PY

echo ">> done. Review CHANGELOG.md, then commit + tag ${TAG} yourself." >&2
