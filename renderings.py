"""How a Bible in the reader's language renders a Strong's number.

A Spanish or Russian reader gets the English Strong's entry and, under it,
one line naming a Bible and the words it uses: "Reina-Valera 1909: amor,
caridad". It is not a definition — no open Spanish or Russian lexicon exists —
it is the usage list Strong's own entries end with, counted from a tagged
Bible by tools/build_renderings.py into data/renderings/{lang}.tsv.

English readers get nothing here: the English entry already says it.
"""

import os
import re

from i18n import _, current_language


def N_(message: str) -> str:
    return message


_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'data', 'renderings')

#: language → the Bible the file was counted from, as the line names it.
SOURCES = {
    'es': N_('Reina-Valera 1909'),
    'ru': N_('Russian Literal Open Bible'),
}

_tables: dict[str, dict[str, list[str]]] = {}
_KEY = re.compile(r'([GH])0*(\d+)', re.I)


def _table(lang: str) -> dict[str, list[str]]:
    if lang not in _tables:
        table: dict[str, list[str]] = {}
        try:
            with open(os.path.join(_DIR, f'{lang}.tsv'), encoding='utf-8') as f:
                for line in f:
                    if line.startswith('#') or '\t' not in line:
                        continue
                    key, words = line.rstrip('\n').split('\t', 1)
                    table[key] = words.split(' | ')
        except OSError:
            pass
        _tables[lang] = table
    return _tables[lang]


def words(strong: str, lang: str) -> list[str]:
    """The renderings for 'G0026' / 'H430a' / 'G26' in `lang`, or []."""
    m = _KEY.search(strong or '')
    if not m or lang not in SOURCES:
        return []
    return _table(lang).get(f'{m.group(1).upper()}{int(m.group(2))}', [])


def line(strong: str) -> str | None:
    """The line for the reader's language, or None: in English, for a number
    the Bible leaves untranslated, and where no file shipped."""
    lang = current_language()
    found = words(strong, lang)
    if not found:
        return None
    return _('{bible}: {words}').format(bible=_(SOURCES[lang]),
                                        words=', '.join(found))
