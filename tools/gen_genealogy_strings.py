#!/usr/bin/env python3
"""Mirror the genealogy table's translatable strings into a Python file.

The curated genealogy content lives in `data/genealogy/genealogy.toml`, which
is the right format to curate in and a format xgettext cannot read. Everything
a reader sees in it — person names, name meanings, significance notes, chart
titles and intros, the classical readings — would therefore never reach
`po/scriptura.pot`, and the whole feature would stay in English while the rest
of the app spoke Spanish and Russian.

So this writes `genealogy_strings.py`: a generated module of `N_()` and
`C_()` markers, one per translatable field, listed in `po/POTFILES.in`. It is
checked in, and `tests/test_genealogy.py` fails when it drifts from the TOML —
so a curator who adds a person and forgets to regenerate gets a red test
rather than an untranslatable name six months later.

Person names are marked with a `person` context. Several of them are also book
names (Ruth, Judges), and one msgid cannot carry both roles without the two
translations fighting over it.

    ./tools/gen_genealogy_strings.py           # rewrite the file
    ./tools/gen_genealogy_strings.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_TOML = os.path.join(_ROOT, 'data', 'genealogy', 'genealogy.toml')
_OUT = os.path.join(_ROOT, 'genealogy_strings.py')

_HEADER = '''"""Generated. Do not edit — run tools/gen_genealogy_strings.py.

Every translatable string in data/genealogy/genealogy.toml, mirrored here so
xgettext can see it. Nothing imports this module at run time; it exists to be
scanned. `genealogy_bridge` translates the same strings by passing the TOML's
values through `_()` and `C_('person', ...)`, which resolve against exactly
these msgids.
"""

from i18n import N_


def C_(context: str, message: str) -> str:
    """No-op pgettext marker, deliberately named `C_`.

    xgettext is already told `--keyword=C_:1c,2` everywhere this project
    extracts — the meson glib preset and tests/test_translations.py both — and
    a marker under any other name is invisible to all of them. Shadowing the
    real `i18n.C_` is safe here precisely because nothing imports this module
    at run time: it exists to be read by xgettext, never executed.
    """
    return message


'''


def collect() -> list[tuple[str, str, str]]:
    """`(kind, context, msgid)` for every translatable field, in file order.

    Order is the TOML's own, so a regeneration produces a minimal diff and a
    reviewer can see which entry changed."""
    with open(_TOML, 'rb') as f:
        raw = tomllib.load(f)

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(msgid: str, context: str = '') -> None:
        if not msgid or not msgid.strip():
            return
        key = (context, msgid)
        if key in seen:
            return
        seen.add(key)
        out.append(('C_' if context else 'N_', context, msgid))

    meta = raw.get('meta', {})
    for field in ('title', 'subtitle', 'body'):
        add(meta.get(field, '').strip())

    for p in raw.get('person', []):
        add(p['name'], 'person')
        for form in p.get('also', []):
            add(form, 'person')
        add(p.get('meaning', ''))
        add(p.get('note', ''))

    for e in raw.get('edge', []):
        add(e.get('note', ''))

    for c in raw.get('chart', []):
        for field in ('title', 'subtitle', 'intro', 'passage', 'passage_b'):
            add(c.get(field, ''))

    for r in raw.get('reading', []):
        for field in ('title', 'body', 'attribution', 'caveat'):
            add(r.get(field, ''))

    return out


def render(entries: list[tuple[str, str, str]]) -> str:
    lines = [_HEADER, '_STRINGS = [\n']
    for kind, context, msgid in entries:
        lit = _pyquote(msgid)
        if kind == 'C_':
            lines.append('    C_(%s, %s),\n' % (_pyquote(context), lit))
        else:
            lines.append('    N_(%s),\n' % lit)
    lines.append(']\n')
    return ''.join(lines)


def _pyquote(text: str) -> str:
    """A Python literal xgettext can parse.

    Multi-line bodies become an implicit-concatenation block rather than a
    triple-quoted string, which keeps the msgid's newlines explicit and
    survives reflowing. The pieces are the call's argument directly, with no
    parentheses of their own: xgettext reads `N_('a' 'b')` and does NOT read
    `N_(('a' 'b'))` — it walks past the parenthesised group without a word,
    and the string is simply absent from the catalogue. That form hid the
    Book of Generations' opening paragraph from every translator, so the
    Russian and Spanish readers met the one page of English in the book."""
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
            print('genealogy_strings.py is stale — run '
                  'tools/gen_genealogy_strings.py', file=sys.stderr)
            return 1
        print('genealogy_strings.py is up to date (%d strings)'
              % len(collect()))
        return 0

    with open(_OUT, 'w', encoding='utf-8') as f:
        f.write(text)
    print('wrote %s (%d strings)' % (os.path.relpath(_OUT, _ROOT),
                                     len(collect())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
