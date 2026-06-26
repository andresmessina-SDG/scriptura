#!/usr/bin/env bash
#
# Build, sign, and stage the Scriptura Flatpak repository for one-click install.
#
# Output is written to ./public/ . Upload that directory's *contents* to the
# `pages` branch of a Codeberg repo named `pages` (served at the user root,
# https://andresmessina.codeberg.page/). Users then install in one click via
#   https://andresmessina.codeberg.page/scriptura.flatpakref
# and receive updates automatically whenever you re-run this and re-upload.
#
# Prerequisites:
#   - flatpak, flatpak-builder, ostree, gpg
#   - GNOME 50 Platform + Sdk installed (flatpak install flathub org.gnome.{Platform,Sdk}//50)
#   - a signing key in $SIGN_HOME (generated once — see FLATPAK_RELEASE.md)
#
# Overrides via env: SIGN_HOME, BASE_URL.
set -euo pipefail
cd "$(dirname "$0")/.."                       # repo root

SIGN_HOME="${SIGN_HOME:-$HOME/.scriptura-flatpak-signing}"
BASE_URL="${BASE_URL:-https://andresmessina.codeberg.page}"
HOMEPAGE="https://codeberg.org/andresmessina/bible-reader"
MANIFEST="page.codeberg.andresmessina.Scriptura.yml"
APPID="page.codeberg.andresmessina.Scriptura"
BUILDDIR="flatpak-build"
OUT="public"
REPO="$OUT/repo"

FPR=$(gpg --homedir "$SIGN_HOME" --list-keys --with-colons 2>/dev/null \
        | awk -F: '/^fpr/{print $10; exit}')
if [ -z "${FPR:-}" ]; then
  echo "ERROR: no signing key in $SIGN_HOME — see FLATPAK_RELEASE.md (one-time setup)." >&2
  exit 1
fi

echo ">> [1/4] Building and exporting to signed ostree repo ..."
mkdir -p "$OUT"
flatpak-builder --force-clean \
  --repo="$REPO" --gpg-homedir="$SIGN_HOME" --gpg-sign="$FPR" \
  "$BUILDDIR" "$MANIFEST"

echo ">> [2/4] Dropping the .Debug ref (end users don't need it) ..."
ostree --repo="$REPO" refs --delete \
  "runtime/$APPID.Debug/x86_64/master" 2>/dev/null || true

echo ">> [3/4] Pruning + static deltas + signed summary/appstream ..."
flatpak build-update-repo --prune --generate-static-deltas \
  --gpg-homedir="$SIGN_HOME" --gpg-sign="$FPR" --title="Scriptura" "$REPO"

echo ">> [4/4] Writing .flatpakref / .flatpakrepo / index.html ..."
PUBKEY=$(gpg --homedir "$SIGN_HOME" --export "$FPR" | base64 -w0)
cat > "$OUT/scriptura.flatpakref" <<EOF
[Flatpak Ref]
Title=Scriptura
Name=$APPID
Branch=master
Url=$BASE_URL/repo
Homepage=$HOMEPAGE
Comment=Read and study the Bible in depth
IsRuntime=false
SuggestRemoteName=scriptura
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
GPGKey=$PUBKEY
EOF
cat > "$OUT/scriptura.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Scriptura
Url=$BASE_URL/repo
Homepage=$HOMEPAGE
Comment=Signed Flatpak repository for Scriptura
GPGKey=$PUBKEY
EOF
cat > "$OUT/index.html" <<EOF
<!doctype html><html lang="en"><meta charset="utf-8">
<title>Scriptura — install for Linux</title>
<body style="font-family:sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem">
<h1>Scriptura</h1>
<p>A focused Bible study app for the Linux desktop.</p>
<p><a href="scriptura.flatpakref"><b>Install (Flatpak)</b></a></p>
<p>Or from a terminal:</p>
<pre>flatpak install $BASE_URL/scriptura.flatpakref</pre>
<p><a href="$HOMEPAGE">Source code</a></p>
</body></html>
EOF

echo
echo ">> Done. Staged in ./$OUT/ (repo: $(du -sh "$REPO" | cut -f1))."
echo ">> Next: publish ./$OUT/ to Codeberg Pages — see FLATPAK_RELEASE.md."
