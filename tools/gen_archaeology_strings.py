#!/usr/bin/env python3
"""Mirror the Scripture in Stone gallery's translatable strings into Python.

The curated gallery lives in `data/archaeology/scripture_in_stone.toml`, which
is the right format to curate in and a format xgettext cannot read. So every
word a reader sees in it — the artifact titles, the captions that carry the
argument, the chapter introductions, the glossary — stayed in English while
the rest of the app spoke Spanish and Russian: a Russian reader opened
«Писание в камне» on a page headed "Scripture in Stone".

This writes `archaeology_strings.py`: a generated module of `N_()` markers,
one per translatable field, listed in `po/POTFILES.in`. It is checked in, and
`tests/test_archaeology.py` fails when it drifts from the TOML, so a curator
who adds an artifact and forgets to regenerate gets a red test rather than an
untranslatable caption six months later.

Four fields are deliberately NOT marked:

  `credit`     an attribution — "photo Oren Rozen · CC BY-SA 4.0" — which the
               licence asks us to carry as given.
  `source`     a URL.
  `reading.title`
               a bibliography. "Amihai Mazar, Archaeology of the Land of the
               Bible" is what a reader would type into a library catalogue;
               translating it would hide the book. The `note` under each one
               is prose, and is marked.
  `refs.book`  a Bible book name, which is a key everywhere else in the app.
               `archaeology_bridge` runs it through `i18n.book_label`, the one
               place book names are translated, so the chips read «Иисус
               Навин 10:1» without a second set of msgids to keep in step.

    ./tools/gen_archaeology_strings.py           # rewrite the file
    ./tools/gen_archaeology_strings.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_TOML = os.path.join(_ROOT, 'data', 'archaeology', 'scripture_in_stone.toml')
_OUT = os.path.join(_ROOT, 'archaeology_strings.py')

_HEADER = '''"""Generated. Do not edit — run tools/gen_archaeology_strings.py.

Every translatable string in data/archaeology/scripture_in_stone.toml,
mirrored here so xgettext can see it. Nothing imports this module at run
time; it exists to be scanned. `archaeology_bridge` translates the same
strings by passing the TOML's values through `_()`, which resolves against
exactly these msgids.
"""

from i18n import N_


'''


def collect() -> list[str]:
    """Every translatable msgid, in file order.

    Order is the TOML's own, so a regeneration produces a minimal diff and a
    reviewer can see which entry changed."""
    with open(_TOML, 'rb') as f:
        raw = tomllib.load(f)

    out: list[str] = []
    seen: set[str] = set()

    def add(msgid: str) -> None:
        if not msgid or not msgid.strip():
            return
        text = msgid.strip()
        if text in seen:
            return
        seen.add(text)
        out.append(text)

    intro = raw.get('intro', {})
    for field in ('title', 'subtitle', 'body'):
        add(intro.get(field, ''))

    for c in raw.get('chapter', []):
        add(c.get('title', ''))
        add(c.get('intro', ''))

    for e in raw.get('entry', []):
        for field in ('title', 'place', 'date', 'holding', 'provenance',
                      'caption'):
            add(e.get(field, ''))

    for d in raw.get('detail', []):
        add(d.get('caption', ''))

    for t in raw.get('term', []):
        add(t.get('term', ''))
        add(t.get('definition', ''))

    for r in raw.get('reading', []):
        add(r.get('note', ''))

    return out


def render(msgids: list[str]) -> str:
    lines = [_HEADER, '_STRINGS = [\n']
    for msgid in msgids:
        lines.append('    N_(%s),\n' % _pyquote(msgid))
    lines.append(']\n')
    return ''.join(lines)


def _pyquote(text: str) -> str:
    """A Python literal xgettext can parse.

    Multi-line bodies become an implicit-concatenation block, the pieces
    handed to the call directly: xgettext reads `N_('a' 'b')` and walks past
    `N_(('a' 'b'))` without a word, which is how the Book of Generations kept
    its opening paragraph out of every catalogue.
    """
    if '\n' not in text:
        return _one(text)
    parts = text.split('\n')
    out = []
    for i, part in enumerate(parts):
        tail = '\\n' if i < len(parts) - 1 else ''
        lit = _one(part)[:-1] + tail + "'"
        out.append(lit if i == 0 else '\n       ' + lit)
    return ''.join(out)


def _one(text: str) -> str:
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if the generated file is out of date')
    args = ap.parse_args()

    text = render(collect())
    if args.check:
        try:
            with open(_OUT, encoding='utf-8') as f:
                current = f.read()
        except OSError:
            current = ''
        if current != text:
            print('archaeology_strings.py is stale — run '
                  'tools/gen_archaeology_strings.py', file=sys.stderr)
            return 1
        print('archaeology_strings.py is up to date (%d strings)'
              % len(collect()))
        return 0

    with open(_OUT, 'w', encoding='utf-8') as f:
        f.write(text)
    print('wrote %s (%d strings)' % (os.path.relpath(_OUT, _ROOT),
                                     len(collect())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
