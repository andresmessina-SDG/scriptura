#!/usr/bin/env bash
# Run the headless checks on Fedora 44, as CI does, whatever this machine runs.
#
#   tools/in-fedora44.sh                     the suite under Broadway, then
#                                            pyflakes and mypy (CI's test job)
#   tools/in-fedora44.sh suite [ARGS]        the suite only; ARGS go to pytest
#   tools/in-fedora44.sh CMD ...             any command, e.g.
#       tools/in-fedora44.sh python3 tools/verify-stress.py nav_storm
#       tools/in-fedora44.sh python3 tools/verify-random.py --minutes 5
#
# The checkout is mounted at its own path, so output/ and reports land where
# they would on the host. ~/.sword is an overlay: the container reads your
# modules and anything it writes there (indexes, installs) is thrown away.
# The image is built on first use; `tools/in-fedora44.sh --rebuild` remakes it.
set -euo pipefail
repo="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
image=localhost/scriptura-test:f44

if [ "${1:-}" = "--rebuild" ] || ! podman image exists "$image"; then
  podman build -t "$image" "$repo/tools/fedora44"
  [ "${1:-}" = "--rebuild" ] && exit 0
fi

mounts=(-v "$repo:$repo")
[ -d "$HOME/.sword" ] && mounts+=(-v "$HOME/.sword:/root/.sword:O")

# Inside: the bundled fonts where CI puts them, then the command.
inner='
set -euo pipefail
mkdir -p /usr/share/fonts/scriptura
cp data/fonts/*.ttf data/fonts/*.otf /usr/share/fonts/scriptura/ 2>/dev/null || true
fc-cache -f >/dev/null
# CI installs KJVA and MHCC as root, which puts them in /usr/share/sword and
# not in ~/.sword; the welcome and modules scenarios depend on both. Move
# yours there (the overlay throws the move away), rather than download.
for m in kjva mhcc; do
  conf=/root/.sword/mods.d/$m.conf
  [ -f "$conf" ] || continue
  mkdir -p /usr/share/sword/mods.d && cp "$conf" /usr/share/sword/mods.d/
  rel=$(sed -n "s/^DataPath=\.\{0,1\}\/\{0,1\}//p" "$conf" | tr -d "\r" | sed "s:/*$::")
  if [ -d "/root/.sword/$rel" ]; then
    mkdir -p "/usr/share/sword/$rel" && cp -r "/root/.sword/$rel/." "/usr/share/sword/$rel/"
  else
    mkdir -p "/usr/share/sword/$(dirname "$rel")" && cp /root/.sword/"$rel"* "/usr/share/sword/$(dirname "$rel")/"
  fi
  rm "$conf"
done

suite() {
  # As CI: scratch HOME and XDG dirs, a Broadway display, and a check that
  # it is there, or every GTK test would skip and the run would look green.
  scratch=$(mktemp -d)
  for d in home config data cache runtime; do mkdir -m 700 "$scratch/$d"; done
  export HOME="$scratch/home" XDG_CONFIG_HOME="$scratch/config" \
         XDG_DATA_HOME="$scratch/data" XDG_CACHE_HOME="$scratch/cache" \
         XDG_RUNTIME_DIR="$scratch/runtime"
  gtk4-broadwayd :3 >/dev/null 2>&1 &
  for _ in $(seq 100); do
    [ -S "$XDG_RUNTIME_DIR/broadway4.socket" ] && break
    sleep 0.05
  done
  export GDK_BACKEND=broadway BROADWAY_DISPLAY=:3
  python3 -c "import gi; gi.require_version(\"Gdk\", \"4.0\"); gi.require_version(\"Gtk\", \"4.0\"); from gi.repository import Gdk, Gtk; assert Gdk.Display.get_default() is not None, \"no display: the GTK tests would all skip\""
  python3 -m pytest -q -rs -p no:cacheprovider "$@"
}

case "${1:-ci}" in
  ci)    suite
         python3 -m pyflakes *.py tests/*.py tools/*.py
         python3 -m mypy . --exclude "^tools/" ;;
  suite) shift; suite "$@" ;;
  *)     "$@" ;;
esac
'
# label=disable: the checkout is not relabelled for SELinux, which :Z would do.
exec podman run --rm --security-opt label=disable "${mounts[@]}" -w "$repo" \
  -e PYTHONDONTWRITEBYTECODE=1 "$image" bash -c "$inner" bash "$@"
