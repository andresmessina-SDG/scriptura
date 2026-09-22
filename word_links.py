"""Which dictionary article a word in a given verse is about.

Russian inflects, and a dictionary is keyed on dictionary forms, so a
double-click on `спросил` or `иисуса` finds nothing by spelling alone: the
Russian Bible dictionary answered 9.6% of the words in John that way. A
tagged Bible already knows each word's Strong's number, and Door43's
Translation Word Links say, verse by verse, which article each number is
about. A dictionary that ships those links carries them beside its data as
`links.tsv.gz` (see tools/build_russian_tw_dict.py): one line per link,
`book  chapter  verse  Strong's  key`, in app-space (KJV) numbering.

Read on first use, off the UI thread (the peek's own worker asks), and again
whenever the file changes, so a dictionary updated in the Module Manager
links at once rather than after a restart. A dictionary without the file
answers nothing, so every other dictionary is untouched.
"""
from __future__ import annotations

import gzip
import logging
import os
import re
import threading

import sword_bridge

LINKS_FILE = 'links.tsv.gz'

_log = logging.getLogger(__name__)
_lock = threading.Lock()
#: module -> (the file's mtime when read, or None when absent; the table)
_links: dict[str, tuple[float | None, dict[tuple, str]]] = {}


def _load(module_name: str) -> dict[tuple, str]:
    """The module's links, keyed (book, chapter, verse, Strong's)."""
    path = os.path.join(sword_bridge.module_data_path(module_name) or '',
                        LINKS_FILE)
    try:
        mtime: float | None = os.stat(path).st_mtime
    except OSError:
        mtime = None
    with _lock:
        cached = _links.get(module_name)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        table: dict[tuple, str] = {}
        if mtime is not None:
            try:
                with gzip.open(path, 'rt', encoding='utf-8') as fh:
                    for line in fh:
                        book, chapter, verse, number, key = (
                            line.rstrip('\n').split('\t'))
                        table[(book, int(chapter), int(verse), number)] = key
            except (OSError, ValueError, EOFError):
                _log.exception('unreadable word links in %s', module_name)
                table = {}
        _links[module_name] = (mtime, table)
        return table


def key_for(module_name: str, book: str, chapter: int, verse: int,
            strongs) -> str | None:
    """The key a linked dictionary files this word under, or None.

    `strongs` are the word's own numbers as the text tags them (`G0025`,
    `H430`); `verse` is app-space. A word two numbers link to different
    articles answers nothing rather than guess."""
    table = _load(module_name)
    if not table or not verse:
        return None
    keys = {table.get((book, chapter, verse,
                       re.sub(r'^([GH])0*', r'\1', n))) for n in strongs}
    keys.discard(None)
    return keys.pop() if len(keys) == 1 else None
