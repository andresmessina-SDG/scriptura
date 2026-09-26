#!/bin/sh
# Upload release assets together with their checksums.
#
#   tools/publish-release-asset.sh TAG FILE [FILE ...]
#
# The app checks every pack and every module from Scriptura's own releases
# against the `<asset>.sha256` published beside it, and refuses a download
# that does not match. So an asset must never go up without its sums: a
# re-uploaded pack with the old .sha256 beside it would be refused by every
# copy of the app. This writes FILE.sha256 (what `sha256sum` prints) for each
# FILE and uploads both, replacing any of the same name.
#
# A pack split into parts (`imagery.tar.gz.000`, `.001`, …) is checked part
# by part against ONE file named after the pack: pass the parts and set
# SUMS_NAME to the pack's name, e.g.
#   SUMS_NAME=imagery.tar.gz tools/publish-release-asset.sh imagery-pack-v1 \
#       imagery.tar.gz.0*
#
# Afterwards, `python3 tools/verify-pack-urls.py` must be green.
set -eu
[ $# -ge 2 ] || { sed -n '2,20p' "$0"; exit 2; }
TAG=$1; shift
REPO=${REPO:-andresmessina-SDG/scriptura}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
if [ -n "${SUMS_NAME:-}" ]; then
  (cd "$(dirname "$1")" && sha256sum $(for f in "$@"; do basename "$f"; done)) \
    > "$TMP/$SUMS_NAME.sha256"
  gh release upload "$TAG" --repo "$REPO" --clobber "$@" "$TMP/$SUMS_NAME.sha256"
else
  for f in "$@"; do
    (cd "$(dirname "$f")" && sha256sum "$(basename "$f")") > "$TMP/$(basename "$f").sha256"
    gh release upload "$TAG" --repo "$REPO" --clobber "$f" "$TMP/$(basename "$f").sha256"
  done
fi
