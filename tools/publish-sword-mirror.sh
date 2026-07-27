#!/usr/bin/env bash
#
# Publish a staged SWORD module mirror to GitHub Releases.
#
# Companion to tools/build-sword-mirror.py, which produces the staging
# directory this uploads. The mirror is Scriptura's last-resort source for
# SWORD modules when CrossWire's single host is unreachable — see the
# comment above _MIRROR_BASE in sword_bridge.py.
#
# Everything goes to ONE release, tagged `current`, because sword_bridge
# builds asset URLs as <base>/current/<basename> and must not have to know
# which release a given module lives in. Re-running replaces changed assets
# in place, so the download URLs are stable forever.
#
# Assets are release attachments, never git objects: they do not count
# against repository size, and nothing large ever enters git history.
#
# Prerequisites: gh (authenticated), a staged dir from build-sword-mirror.py.
#
# Usage:
#   tools/publish-sword-mirror.sh STAGING_DIR [--create]
#
#     --create   create the mirror repository first (one-time setup)
#
# Overrides via env: MIRROR_REPO.
set -euo pipefail

MIRROR_REPO="${MIRROR_REPO:-andresmessina-SDG/scriptura-sword-mirror}"
TAG="current"

STAGING="${1:-}"
if [ -z "$STAGING" ] || [ ! -d "$STAGING/modules" ]; then
  echo "usage: $0 STAGING_DIR [--create]" >&2
  echo "  (STAGING_DIR must contain modules/ and manifest.json)" >&2
  exit 1
fi
if [ ! -f "$STAGING/manifest.json" ]; then
  echo "ERROR: $STAGING/manifest.json missing — run build-sword-mirror.py first." >&2
  exit 1
fi

COUNT=$(find "$STAGING/modules" -name '*.zip' | wc -l)
SIZE=$(du -sh "$STAGING/modules" | cut -f1)

if [ "${2:-}" = "--create" ]; then
  echo ">> Creating $MIRROR_REPO ..."
  gh repo create "$MIRROR_REPO" --public \
    --description "Redistributable mirror of the CrossWire SWORD module repository, for Scriptura's offline fallback"

  # Seed it with the weekly refresh workflow and a README explaining what
  # this is and what it deliberately omits. Anyone who finds the repo
  # should be able to tell at once that it is not a complete CrossWire copy.
  SEED=$(mktemp -d)
  mkdir -p "$SEED/.github/workflows"
  cp "$(dirname "$0")/sword-mirror-workflow.yml" \
     "$SEED/.github/workflows/refresh.yml"
  cat > "$SEED/README.md" <<'MD'
# Scriptura SWORD mirror

A mirror of the **freely redistributable subset** of the [CrossWire Bible
Society](https://crosswire.org) SWORD module repository, used by
[Scriptura](https://github.com/andresmessina-SDG/scriptura) as a fallback
when CrossWire's server is unreachable.

CrossWire serves every SWORD module from a single machine, and that machine
has had repeated multi-hour outages. Scriptura tries CrossWire over HTTPS,
then over FTP, and only then falls back here.

## This is not a complete copy

Roughly a fifth of the CrossWire repository is licensed to CrossWire
specifically — the copyright holders granted distribution rights to them
and to no one else. **Those modules are deliberately excluded.** For them,
please use CrossWire directly.

Included are modules whose licences permit redistribution by anyone: public
domain, CC0, CC-BY, CC-BY-SA, GPL, GFDL, and texts marked freely or
non-commercially distributable. `manifest.json` on the release lists every
mirrored module with its licence and SHA-256.

Contents are rebuilt weekly and unmodified from CrossWire. If you hold
rights in something here and would rather it were not mirrored, please open
an issue and it will be removed.
MD
  git -C "$SEED" init -q -b main
  git -C "$SEED" add -A
  git -C "$SEED" commit -q -m "Add refresh workflow and README"
  git -C "$SEED" remote add origin "https://github.com/$MIRROR_REPO.git"
  git -C "$SEED" push -q origin main
  rm -rf "$SEED"
  echo "   seeded with README + weekly refresh workflow"
fi

if ! gh release view "$TAG" --repo "$MIRROR_REPO" >/dev/null 2>&1; then
  echo ">> Creating release '$TAG' ..."
  gh release create "$TAG" --repo "$MIRROR_REPO" \
    --title "Current mirror" \
    --notes "Mirror of the freely redistributable subset of the CrossWire SWORD repository, rebuilt by tools/build-sword-mirror.py. Modules whose licence grants distribution rights to CrossWire alone are deliberately excluded. See manifest.json for the exact contents, licences and checksums."
fi

# Withdraw first, then publish. If a licence was tightened upstream the
# module must stop being served even if a later step fails; doing it last
# would leave it downloadable for another week on any error above.
if [ -f "$STAGING/changes.json" ]; then
  REMOVED=$(python3 -c \
    'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["removed"]))' \
    "$STAGING/changes.json")
  for mod in $REMOVED; do
    echo ">> Withdrawing $mod (no longer redistributable) ..."
    gh release delete-asset "$TAG" "$mod.zip" --repo "$MIRROR_REPO" --yes \
      || echo "   (not present; nothing to withdraw)"
  done
fi

echo ">> Uploading manifest + catalogue ..."
gh release upload "$TAG" --repo "$MIRROR_REPO" --clobber \
  "$STAGING/manifest.json" "$STAGING/mods.d.tar.gz"

if [ "$COUNT" -eq 0 ]; then
  echo ">> No module bodies changed — nothing further to upload."
else
  echo ">> Uploading $COUNT modules ($SIZE) ..."
  # In batches: one gh invocation per module would be hundreds of API
  # round-trips, and passing all of them at once has overflowed argv.
  find "$STAGING/modules" -name '*.zip' -print0 \
    | xargs -0 -n 20 gh release upload "$TAG" --repo "$MIRROR_REPO" --clobber
fi

echo
echo "Done. Assets served from:"
echo "  https://github.com/$MIRROR_REPO/releases/download/$TAG/<Module>.zip"
