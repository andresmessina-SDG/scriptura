#!/usr/bin/env python3
"""Check a built SWORD dictionary module before it is offered.

Installs the zip into a scratch SWORD folder (never the reader's own) and
reads it back the way the app does:

* the count — every key the build wrote is there, in order, none empty;
* the verse references — each OSIS reference of the 66 books names a
  chapter and verse the KJV has (deuterocanonical ones are counted apart:
  the app's verse space has none of them);
* the markup — every entry turns into Pango markup the word peek can show;
* the reach — how many verses the bar's Dictionaries set would gain.

Usage:  python3 tools/validate_dict_module.py MODULE.zip [--expect N]
Exit 0 when nothing is wrong.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('zip')
    ap.add_argument('--expect', type=int, help='the number of keys built')
    args = ap.parse_args()

    home = tempfile.mkdtemp(prefix='dictcheck-')
    sword = os.path.join(home, '.sword')
    with zipfile.ZipFile(args.zip) as zf:
        zf.extractall(sword)
        conf = next(n for n in zf.namelist() if n.startswith('mods.d/'))
    os.environ['HOME'] = home
    os.environ['SWORD_PATH'] = sword
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    import Sword
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Pango
    import open_data
    import verse_articles
    import sword_bridge
    from pane import _html_to_markup

    name = re.search(r'^\[(.+)\]', open(os.path.join(sword, conf),
                                         encoding='utf-8').read(), re.M).group(1)
    mgr = Sword.SWMgr(sword)
    mod = mgr.getModule(name)
    if mod is None:
        print(f'{name}: the module does not load')
        return 1

    keys, empty, unsorted, bad_markup = [], [], 0, []
    in_kjv = out_of_bounds = deutero = unread = 0
    verses = set()
    vk = Sword.VerseKey()
    mod.setPosition(Sword.SW_POSITION(1))
    prev = None
    while not sword_bridge._walk_ended(mod.popError()):
        raw = str(mod.getRawEntry())
        key = str(mod.getKeyText())
        keys.append(key)
        if prev is not None and key < prev:
            unsorted += 1
        prev = key
        if not re.sub(r'<[^>]+>|\s', '', raw):
            empty.append(key)
        try:
            Pango.parse_markup(_html_to_markup(raw, False), -1, '\0')
        except Exception as exc:
            bad_markup.append((key, str(exc)[:80]))
        for value in re.findall(r'osisRef="([^"]+)"', raw):
            for one in value.split():
                osis = re.sub(r'(^|-)[^:\s-]+:', r'\1', one)
                book = osis.split('.')[0]
                if book not in open_data._OSIS_BOOKS:
                    deutero += 1
                    continue
                first = osis.split('-')[0].split('.')
                if len(first) == 2:
                    first.append('1')
                if len(first) != 3:
                    unread += 1
                    continue
                b = open_data._OSIS_BOOKS[book]
                c, v = int(first[1]), int(first[2])
                vk.setText(f'{b} {c}:{v}')
                if vk.getChapter() != c or vk.getVerse() != v:
                    out_of_bounds += 1
                    if out_of_bounds <= 10:
                        print(f'  out of bounds in {key}: {one}')
                else:
                    in_kjv += 1
        verses.update(verse_articles.cited_verses(raw))
        mod.increment()

    print(f'{name}: {len(keys)} keys'
          + (f' (expected {args.expect})' if args.expect else '')
          + f'; {len(empty)} empty; {unsorted} out of order')
    print(f'verse references: {in_kjv} in the KJV, {out_of_bounds} out of '
          f'bounds, {deutero} deuterocanonical, {unread} unreadable')
    print(f'markup: {len(bad_markup)} entries the peek cannot show '
          f'{bad_markup[:5]}')
    print(f'reach: {len(verses)} verses cited')
    wrong = (empty or unsorted or bad_markup or out_of_bounds or unread
             or (args.expect and len(keys) != args.expect))
    return 1 if wrong else 0


if __name__ == '__main__':
    sys.exit(main())
