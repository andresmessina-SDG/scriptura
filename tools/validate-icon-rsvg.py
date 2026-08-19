#!/usr/bin/env python3
"""Stand-in for /usr/libexec/flatpak-validate-icon on a host with no SVG loader.

`flatpak build-export` validates every icon it exports by shelling out to
flatpak-validate-icon, which loads the file through gdk-pixbuf. librsvg
2.60 removed its gdk-pixbuf loader, so on an up-to-date Fedora nothing can
load an SVG that way and the export dies with "Format not recognized" —
for a file that is perfectly valid. Point flatpak at this instead:

    FLATPAK_VALIDATE_ICON=$PWD/tools/validate-icon-rsvg.py ./tools/publish-flatpak-repo.sh

SVGs are checked with librsvg itself, through GObject introspection, which
is the same renderer the missing loader used to wrap. Anything else is
handed to the real helper, so PNGs are validated exactly as before. The
checks mirror flatpak's own: a recognised format, no larger than the
maximum asked for, and square.
"""
import os
import subprocess
import sys

REAL = os.environ.get('FLATPAK_VALIDATE_ICON_REAL',
                      '/usr/libexec/flatpak-validate-icon')


def main(argv):
    args = [a for a in argv[1:] if a != '--sandbox']
    if len(args) != 3:
        print('Usage: validate-icon-rsvg.py [--sandbox] WIDTH HEIGHT PATH',
              file=sys.stderr)
        return 1
    max_w, max_h, path = int(args[0]), int(args[1]), args[2]

    def reject(msg):
        # stderr, not stdout: flatpak quotes the helper's stderr in its own
        # "is not a valid icon: %s" line, and printing elsewhere leaves the
        # reason blank in the only message anyone sees.
        print(msg, file=sys.stderr)
        return 1

    if not path.endswith('.svg'):
        return subprocess.call([REAL] + argv[1:])

    import gi
    gi.require_version('Rsvg', '2.0')
    from gi.repository import Rsvg
    try:
        handle = Rsvg.Handle.new_from_file(path)
    except Exception:
        return reject('Format not recognized')

    has_w, width, has_h, height, has_box, box = handle.get_intrinsic_dimensions()
    if has_w and has_h:
        w, h = width.length, height.length
    elif has_box:
        w, h = box.width, box.height
    else:
        return reject('Format not recognized')
    # gdk-pixbuf reported whole pixels, and the icons say things like
    # "15.9727" — comparing the raw floats would call a square icon oblong.
    w, h = round(w), round(h)

    if w > max_w or h > max_h:
        return reject(f'Image too large ({w:g}x{h:g}). Max. size {max_w}x{max_h}')
    if w != h:
        return reject(f'Expected a square icon but got: {w:g}x{h:g}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
