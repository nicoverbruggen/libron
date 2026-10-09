# Agent Instructions

- Do not edit `CHANGELOG.md` or create new Python scripts unless explicitly requested. If either is needed, ask first.
- Keep font edits in the FontForge source files by default. Change other files only when the task requires it, such as release work.
- Use the `fntbld-oci` container for build-related tasks instead of native host tooling. This container has access to Python with `fonttools`, and also FontForge.
- Always validate that the build script works correctly when applying changes.
- Preferred command from the repository root:
  `podman run --rm -v "$PWD":/work -w /work ghcr.io/nicoverbruggen/fntbld-oci:latest python3 build.py`
- When creating a new release, bump `VERSION` in the repository's root first.
- Before tagging a new release, update the specimen layout or sample text, change [scripts/generate_specimens.py](./scripts/generate_specimens.py).
