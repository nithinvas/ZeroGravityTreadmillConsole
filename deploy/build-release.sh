#!/usr/bin/env bash
# Builds a release tarball to carry to the N100 on a USB stick.
#
# Run this on the Mac (or in CI). It builds the UI, drops everything the
# appliance does not need — node_modules, virtualenvs, test data, git history —
# and writes dist/trendmill-<version>.tar.gz plus its SHA-256.
#
# The appliance never builds the UI itself: no Node, no npm, no network needed
# for the part that is most likely to differ between machines.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/trendmill/__init__.py")"
[ -n "$VERSION" ] || { echo "could not read __version__ from backend/trendmill/__init__.py" >&2; exit 1; }
STAMP="$(date -u +%Y%m%d%H%M)"
NAME="trendmill-${VERSION}+${STAMP}"

echo "Building the UI..."
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)
[ -f "$ROOT/frontend/dist/index.html" ] || { echo "the UI did not build" >&2; exit 1; }

echo "Running the tests..."
(cd "$ROOT/backend" && uv run pytest -q)
(cd "$ROOT/frontend" && npx vitest run)

echo "Packing $NAME..."
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME"
# Only what the appliance runs: the backend source, the built UI, the deploy files.
rsync -a --exclude='__pycache__' --exclude='.venv' --exclude='.pytest_cache' \
      --exclude='.mypy_cache' --exclude='.ruff_cache' \
      "$ROOT/backend/" "$STAGE/$NAME/backend/"
mkdir -p "$STAGE/$NAME/frontend"
rsync -a "$ROOT/frontend/dist/" "$STAGE/$NAME/frontend/dist/"
rsync -a "$ROOT/deploy/" "$STAGE/$NAME/deploy/"
cp "$ROOT/README.md" "$STAGE/$NAME/"
mkdir -p "$STAGE/$NAME/docs" && cp "$ROOT/docs/design.md" "$ROOT/docs/deployment.md" "$STAGE/$NAME/docs/" 2>/dev/null || true
printf '%s\n' "$NAME" > "$STAGE/$NAME/VERSION"

mkdir -p "$OUT"
# COPYFILE_DISABLE stops macOS adding its own extended attributes to the archive;
# without it, GNU tar on the appliance prints a screenful of warnings about
# "LIBARCHIVE.xattr.com.apple.provenance" while extracting a perfectly good file.
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$OUT/$NAME.tar.gz" -C "$STAGE" "$NAME"
(cd "$OUT" && shasum -a 256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256")

echo
echo "Wrote $OUT/$NAME.tar.gz"
echo "     $(cat "$OUT/$NAME.tar.gz.sha256")"
echo
echo "Copy it to a USB stick, then on the mini PC:"
echo "  tar -xzf $NAME.tar.gz && sudo ./$NAME/deploy/provision.sh"
