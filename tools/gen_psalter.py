#!/usr/bin/env python3
"""Generate tools/psalter_plates.toml — the Utrecht Psalter psalm cycle.

The Utrecht Psalter (Utrecht University Library, Ms. 32, c. 830) illustrates
every psalm: each illustration immediately precedes its psalm's text. Utrecht
University publishes a complete IIIF digitization; its **v2 manifest embeds
the annotated edition's per-page commentary inline**, and each commentary
opens with a header like "PSALM XX (21), f. 11v." — Roman = Vulgate number,
parenthetical = the Hebrew/KJV number the app uses. (The newer per-page JSON
API carries the same data but proved unreliable; the manifest is one fetch
and self-contained.)

Quirks handled (all verified against the page scans):
  * header variants: "(9 and 10)", "(91 )", "(116, verses 1-9)" — Vulgate
    psalms that merge or split Hebrew ones, including verse-partials;
  * "(151)" is the apocryphal psalm — skipped (the app's Psalms has 150);
  * ~19 psalms have no commentary of their own in the manifest because they
    are the *lower* picture on the previous psalm's page (the embedding
    keeps only one annotation per page). Verified visually (e.g. Hebrew 44,
    114-115, 118, 150 all start as bare text at the top of the next page):
    such a psalm's illustration is on the previous psalm's page.
  * the annotation's @id page number is authoritative (the manifest attaches
    each annotation to the *following* canvas; folio arithmetic
    page = 2×folio + (7 if recto else 8) matched all 126 plain headers).

Cantica pages (the 16 biblical songs at the end) are printed to stderr for
hand-curation into curated_plates.toml — their book mapping (Exodus 15,
Habakkuk 3, Luke 1…) is editorial, not mechanical.

LICENSING: the manuscript is 9th-century; faithful reproductions of public
domain works gain no new copyright in the EU (DSM directive art. 14, as
implemented in the Netherlands), and Utrecht University serves the scans
openly (IIIF + downloads). Recorded as PD with the library named in the
attribution.

Usage: gen_psalter.py [--width 1100]
"""

import argparse
import html
import json
import re
import sys
import urllib.request

_UA = ('ScripturaImageryBuilder/1.0 '
       '(https://codeberg.org/andresmessina/scriptura)')
_MANIFEST_V2 = 'https://objects.library.uu.nl/manifest/iiif/v2/1874-284427'
_MANIFEST_V3 = 'https://objects.library.uu.nl/manifest/iiif/v3/1874-284427'

_HDR = re.compile(
    r'PSALM\s+[IVXLC]+(?:-[IVXLC]+)?\s*'
    r'\((\d+)(?:\s*(?:-|and)\s*(\d+))?'          # hebrew start / end
    r'(?:,\s*verses\s*(\d+)-(\d+))?\s*\)'         # optional verse partial
    r'\s*(?:\(the apocryphal Psalm\))?,?\s*f\.\s*(\d+)([rv])')


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--width', type=int, default=1100)
    args = ap.parse_args()

    print('fetching manifests…', file=sys.stderr)
    v3 = _get(_MANIFEST_V3)
    services = {}  # page -> IIIF image service base
    for canvas in v3['items']:
        page = int(canvas['label']['none'][0])
        services[page] = canvas['items'][0]['items'][0]['body']['service'][0]['id']

    v2 = _get(_MANIFEST_V2)
    entries = {}  # (hebrew_start, v1) -> dict
    for canvas in v2['sequences'][0]['canvases']:
        for oc in canvas.get('otherContent') or []:
            m = re.search(r'/canvas/p(\d+)/', oc.get('@id', ''))
            if not m:
                continue
            page = int(m.group(1))
            chars = html.unescape(oc['resource']['resource']['chars'])
            if 'CANTICUM' in chars.upper() or 'PSALM' not in chars:
                head = chars.split('<br')[0][:90]
                print(f'CANTICUM/other page {page}: {head}', file=sys.stderr)
            for h in _HDR.finditer(chars):
                start, end = int(h.group(1)), int(h.group(2) or h.group(1))
                if start == 151:
                    continue  # apocryphal psalm; the app's Psalms has 150
                v1 = int(h.group(3)) if h.group(3) else None
                v2_ = int(h.group(4)) if h.group(4) else None
                key = (start, v1)
                if key not in entries:
                    entries[key] = dict(page=page, end=end, v1=v1, v2=v2_,
                                        folio=f'f. {h.group(5)}{h.group(6)}')

    covered = set()
    for (s, _v1), e in entries.items():
        covered.update(range(s, e['end'] + 1))

    # Psalms whose commentary was dropped from the manifest embedding: their
    # illustration is the lower picture on the previous psalm's page.
    page_of = {}
    for (s, _v1), e in entries.items():
        for n in range(s, e['end'] + 1):
            page_of.setdefault(n, e['page'])
    for n in range(1, 151):
        if n in covered:
            continue
        prev = max(m for m in page_of if m < n)
        entries[(n, None)] = dict(page=page_of[prev], end=n, v1=None, v2=None,
                                  folio='lower picture')
        print(f'psalm {n}: assigned lower picture on page {page_of[prev]} '
              f'(after psalm {prev})', file=sys.stderr)

    print(f'{len(entries)} plates', file=sys.stderr)

    with open('psalter_plates.toml', 'w', encoding='utf-8') as f:
        f.write(
            '# GENERATED by gen_psalter.py — do not edit by hand.\n'
            '# Utrecht Psalter (Utrecht University Library, Ms. 32, c. 830):'
            ' one\n# illustration per psalm, whole-psalm verse ranges,'
            ' Hebrew/KJV numbering\n# (from the annotated edition headers'
            ' embedded in the IIIF v2 manifest).\n# Image URLs are'
            ' width-scaled IIIF requests against the library\'s own\n'
            '# image server.\n'
            '# PD: faithful reproduction of a 9th-century manuscript'
            ' (EU DSM art. 14).\n')
        for (start, v1) in sorted(entries, key=lambda k: (k[0], k[1] or 0)):
            e = entries[(start, v1)]
            end = e['end']
            if v1 is not None:
                label = f'Psalm {start}:{e["v1"]}–{e["v2"]}'
                verse, verse_end = e['v1'], e['v2']
                n_key = f'PSA{start:03d}_{e["v1"]}'
            else:
                label = (f'Psalm {start}' if end == start
                         else f'Psalms {start}–{end}')
                verse, verse_end = 1, 999
                n_key = f'PSA{start:03d}'
            f.write(f'''
[[plate]]
n = "{n_key}"
url = "{services[e['page']]}/full/{args.width},/0/default.jpg"
source_url = "https://psalter.library.uu.nl/"
title = "{label} ({e['folio']})"
book = "Psalms"
chapter = {start}
verse = {verse}
chapter_end = {end}
verse_end = {verse_end}
passage_label = "{label}"
kind = "illustration"
tradition = "illumination"
artist = "Utrecht Psalter"
year = 830
license = "PD"
attribution = "Utrecht Psalter (c. 830) — Utrecht University Library, Ms. 32"
''')
    print('wrote psalter_plates.toml', file=sys.stderr)


if __name__ == '__main__':
    main()
