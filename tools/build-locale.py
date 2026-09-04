#!/usr/bin/env python3
"""Compile `po/*.po` into a locale tree a source checkout can read.

meson compiles the catalogues at install time, so `python3 main.py` from the
repo has none and `i18n.available_languages()` answers English alone. The
language picker hides itself below two languages, which meant a whole shipped
feature — and the Spanish and Russian interfaces reached through it — was
invisible to anyone testing from the tree. This fills the `locale/` that
`i18n.localedir()` falls back to.

Only rebuilds a catalogue whose `.po` is newer than its `.mo`, so it is cheap
enough to run before every launch; `--force` ignores that. Codes come from
`po/LINGUAS`, the same list meson reads, so a language cannot be live here and
missing from the install.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO = os.path.join(ROOT, 'po')
OUT = os.path.join(ROOT, 'locale')


def languages():
    """The codes in po/LINGUAS, comments and blanks dropped."""
    with open(os.path.join(PO, 'LINGUAS'), encoding='utf-8') as fh:
        return [ln.strip() for ln in fh
                if ln.strip() and not ln.startswith('#')]


def main(argv):
    force = '--force' in argv
    if not os.path.isdir(os.path.join(ROOT, '.git')):
        # An installed tree has real catalogues and localedir() prefers them;
        # writing a second set beside the source would only confuse things.
        print('not a source checkout — nothing to build', file=sys.stderr)
        return 1
    built, fresh = [], []
    for code in languages():
        po = os.path.join(PO, f'{code}.po')
        if not os.path.isfile(po):
            print(f'{code}: no {code}.po', file=sys.stderr)
            return 1
        mo = os.path.join(OUT, code, 'LC_MESSAGES', 'scriptura.mo')
        if (not force and os.path.isfile(mo)
                and os.path.getmtime(mo) >= os.path.getmtime(po)):
            fresh.append(code)
            continue
        os.makedirs(os.path.dirname(mo), exist_ok=True)
        # --check would reject a po mid-translation; this tool exists to let
        # one be looked at, so only the format has to hold.
        r = subprocess.run(['msgfmt', '-o', mo, po],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f'{code}: msgfmt failed\n{r.stderr}', file=sys.stderr)
            return 1
        built.append(code)
    parts = []
    if built:
        parts.append('built ' + ', '.join(built))
    if fresh:
        parts.append('up to date ' + ', '.join(fresh))
    print('locale: ' + ('; '.join(parts) if parts else 'nothing in LINGUAS'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
