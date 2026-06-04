#!/usr/bin/env bash
#
# Build Libron locally inside the fntbld container via Podman.
#
# This mirrors the CI build: it mounts the repository into the prebuilt
# fntbld image (which bundles FontForge, ttfautohint, fonttools, brotli,
# and skia-pathops) and runs build.py. Generated fonts appear in ./out
# on the host.
#
# Usage:
#   ./local-build.sh                 # full build
#   ./local-build.sh --customize     # any build.py flags are passed through
#   ./local-build.sh --kobofix       # also generate Kobo (KF) font variants
#
set -euo pipefail

IMAGE="${FNTBLD_IMAGE:-ghcr.io/nicoverbruggen/fntbld-oci:latest}"

# Resolve the repository root (directory of this script) so the build works
# no matter where it is invoked from.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman not found. Install Podman from https://podman.io" >&2
  exit 1
fi

echo "Building Libron with ${IMAGE}"
echo

# Translate --kobofix shorthand to --with-kobofix for build.py
set -- "${@/--kobofix/--with-kobofix}"

podman run --rm \
  -v "${REPO_DIR}":/work:z \
  -w /work \
  "${IMAGE}" \
  python3 build.py "$@"

echo
echo "Done. Fonts are in:"
echo "  ${REPO_DIR}/out/ttf"
echo "  ${REPO_DIR}/out/kf"
