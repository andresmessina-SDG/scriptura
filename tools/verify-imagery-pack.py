#!/usr/bin/env python3
"""Pre-publish check: a freshly built imagery pack is complete and honest.

Run this after `build_imagery_pack.py` and BEFORE the asset leaves the
machine. It exists because the published pack went stale for two months
without anything noticing: the catalog held 269 images where the sources
define 1,257, every NT epistle portrait was missing, and the app, the test
suite and the release page all looked fine. Nothing here is a unit test —
these are facts about a built artifact, and there is no artifact in the repo.

Five gates, each of which stops the publish on its own:

  1. counts     — rows, books, traditions, sources, against any older copies
                  given with --against. A rebuild that LOSES plates is the
                  failure this is really watching for.
  2. coverage   — every plate the TOMLs define is either in the catalog or
                  named in the build log as a fetch that failed. An
                  unexplained shortfall is not acceptable; an upstream file
                  withdrawn from Commons is, once it has been read.
  3. epistles   — EPI01-EPI21 must return rows. That was the headline symptom
                  of the stale pack, so it gets its own gate.
  4. images     — every file_path row has its file on disk at the recorded
                  size. A row whose JPEG did not land is worse than no row.
  5. meta       — pack_meta agrees with the catalog it describes. The Update
                  button in Module Manager compares `built` dates, so a pack
                  that lies about its own date is one nobody is offered.

Usage:
    python3 tools/verify-imagery-pack.py <packdir> [--log <build.log>]
                                         [--against <other-packdir> ...]

Exit 0 = every gate passed, 1 = at least one failed.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sqlite3
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))

#: Plate TOMLs, as (catalog `source` value, the word the build log uses when
#: a fetch fails). The three vocabularies do not agree — the CLI calls it
#: `oils`, the catalog says `oldmaster`, the log says `oils` — so both are
#: written down rather than derived. The programmatic sources (openbible
#: places, genmaps) define no plates and are not reconcilable this way, so
#: they are absent by design.
PLATE_SOURCES = {
    'schnorr_plates.toml': ('schnorr_1860', 'plate'),
    'dore_plates.toml': ('dore_1866', 'dore'),
    'tissot_plates.toml': ('tissot', 'tissot'),
    'icon_plates.toml': ('icons', 'icon'),
    'stained_glass_plates.toml': ('glass', 'glass'),
    'oldmaster_plates.toml': ('oldmaster', 'oils'),
    'manuscript_plates.toml': ('manuscripts', 'mss'),
    'curated_plates.toml': ('curated', 'curated'),
    'psalter_plates.toml': ('psalter', 'psalter'),
    'hurlbut_maps.toml': ('hurlbut_1882', 'map'),
    'modern_maps.toml': ('wikimedia_svg', 'modern'),
}

#: Every ingest the builder runs when told nothing — the set `pack_meta`
#: should record for a complete pack.
ALL_CLI_SOURCES = {
    'curated', 'dore', 'genmaps', 'glass', 'hurlbut', 'icons', 'manuscripts',
    'modern', 'oils', 'openbible', 'psalter', 'schnorr', 'tissot',
}

_FAILED = re.compile(r'^\s*!\s+(\S+)\s+(\S+)\s+fetch failed: (.*)$')


class Report:
    """Gate results, so every gate runs and the whole picture is printed
    once — a run that stopped at the first failure would hide the rest, and
    the rebuild is too slow to repeat five times."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, gate: str, detail: str) -> bool:
        print(f'  {"PASS" if ok else "FAIL"}  {detail}')
        if not ok:
            self.failures.append(f'{gate}: {detail}')
        return ok


def catalog(packdir: str) -> sqlite3.Connection:
    path = os.path.join(packdir, 'imagery.sqlite')
    if not os.path.exists(path):
        sys.exit(f'no imagery.sqlite in {packdir}')
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def summarise(conn: sqlite3.Connection) -> dict[str, int]:
    q = conn.execute
    return {
        'images': q('SELECT COUNT(*) FROM imagery').fetchone()[0],
        'books': q('SELECT COUNT(DISTINCT book) FROM imagery').fetchone()[0],
        'traditions':
            q('SELECT COUNT(DISTINCT tradition) FROM imagery').fetchone()[0],
        'sources': q('SELECT COUNT(DISTINCT source) FROM imagery').fetchone()[0],
        'places': q('SELECT COUNT(*) FROM places').fetchone()[0],
    }


def gate_counts(rep: Report, conn: sqlite3.Connection,
                others: list[str]) -> None:
    print('\n1. counts')
    new = summarise(conn)
    print(f'      built: {new}')
    for other in others:
        try:
            old = summarise(catalog(other))
        except SystemExit as exc:
            print(f'  SKIP  {other}: {exc}')
            continue
        print(f'      {other}: {old}')
        for key in ('images', 'books'):
            rep.check(new[key] >= old[key], 'counts',
                      f'{key} {new[key]} >= {old[key]} in {other}')


def gate_coverage(rep: Report, conn: sqlite3.Connection,
                  log_path: str | None) -> None:
    print('\n2. coverage against the plate TOMLs')
    skipped: dict[str, list[str]] = {}
    if log_path and os.path.exists(log_path):
        with open(log_path, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = _FAILED.match(line)
                if m:
                    skipped.setdefault(m.group(1), []).append(
                        f'{m.group(2)} ({m.group(3).strip()})')
    elif log_path:
        print(f'  note: no build log at {log_path} — '
              f'a shortfall cannot be explained without it')

    for toml_name, (source, log_word) in sorted(PLATE_SOURCES.items()):
        with open(os.path.join(HERE, toml_name), 'rb') as f:
            doc = tomllib.load(f)
        # Each file names its own array — plate, map, icon, glass, painting —
        # and holds exactly one at the top level. Take the list rather than
        # the first key: hurlbut_maps.toml nests further arrays inside each
        # entry, and counting `[[` in the text gives 50 where there are 20.
        defined = len(next(v for v in doc.values() if isinstance(v, list)))
        # Distinct files, not rows: one Hurlbut map carries several passages
        # and so writes several rows against a single image.
        built = conn.execute(
            'SELECT COUNT(DISTINCT file_path) FROM imagery WHERE source = ?',
            (source,)).fetchone()[0]
        failed = skipped.get(log_word, [])
        unaccounted = defined - built - len(failed)
        rep.check(unaccounted == 0, 'coverage',
                  f'{source}: {built} built + {len(failed)} failed '
                  f'of {defined} defined'
                  + ('' if unaccounted == 0
                     else f' — {unaccounted} unaccounted for'))
        if failed:
            print(f'        upstream gone: {", ".join(failed)}')


def gate_epistles(rep: Report, conn: sqlite3.Connection) -> None:
    print('\n3. the NT epistle portraits (EPI01-EPI21)')
    rows = conn.execute(
        "SELECT file_path, book FROM imagery "
        "WHERE file_path LIKE 'images/cur_EPI%' ORDER BY file_path").fetchall()
    rep.check(len(rows) == 21, 'epistles', f'{len(rows)} of 21 present')
    have = {os.path.basename(p).split('.')[0].replace('cur_', '')
            for p, _b in rows}
    want = {f'EPI{n:02d}' for n in range(1, 22)}
    if want - have:
        print(f'        missing: {", ".join(sorted(want - have))}')


def gate_images(rep: Report, conn: sqlite3.Connection, packdir: str) -> None:
    print('\n4. images beside the catalog')
    absent, wrong_size = [], []
    rows = conn.execute(
        'SELECT file_path, file_size FROM imagery').fetchall()
    for rel, recorded in rows:
        if not rel:
            continue
        path = os.path.join(packdir, rel)
        if not os.path.exists(path):
            absent.append(rel)
        elif recorded and os.path.getsize(path) != recorded:
            wrong_size.append(f'{rel} ({os.path.getsize(path)} != {recorded})')
    rep.check(not absent, 'images',
              f'{len(rows) - len(absent)} of {len(rows)} files on disk')
    for rel in absent[:10]:
        print(f'        absent: {rel}')
    rep.check(not wrong_size, 'images',
              f'{len(wrong_size)} files disagree with their recorded size')
    for item in wrong_size[:10]:
        print(f'        {item}')

    # And the other way round. With --reuse-images a staging directory
    # outlives the run that filled it, so a plate dropped from a TOML leaves
    # its image behind — shipped, paid for in the download, and reachable
    # from nothing.
    referenced = {rel for rel, _s in rows if rel}
    referenced |= {p for (p,) in conn.execute(
        'SELECT DISTINCT photo_path FROM places WHERE photo_path IS NOT NULL')}
    images = os.path.join(packdir, 'images')
    on_disk = {f'images/{name}' for name in os.listdir(images)}
    orphans = on_disk - referenced
    rep.check(not orphans, 'images',
              f'{len(on_disk)} files on disk, {len(orphans)} reachable from '
              f'no row')
    for rel in sorted(orphans)[:10]:
        print(f'        orphan: {rel}')


def gate_meta(rep: Report, conn: sqlite3.Connection, packdir: str) -> None:
    print('\n5. pack_meta honest')
    meta = dict(conn.execute('SELECT key, value FROM pack_meta').fetchall())
    print(f'      {meta}')
    counted = conn.execute('SELECT COUNT(*) FROM imagery').fetchone()[0]
    places = conn.execute('SELECT COUNT(*) FROM places').fetchone()[0]
    rep.check(meta.get('image_count') == str(counted), 'meta',
              f"image_count {meta.get('image_count')} == {counted} rows")
    rep.check(meta.get('place_count') == str(places), 'meta',
              f"place_count {meta.get('place_count')} == {places} rows")
    # The Update button compares this date against the app's LATEST_BUILT, so
    # a pack older than its own contents is one that never gets offered.
    # Checked against the catalog's own mtime rather than today's date: a
    # build that starts in the evening and finishes after midnight is honest,
    # and `built == today` calls it a liar every time.
    built = meta.get('built', '')
    wrote = datetime.date.fromtimestamp(
        os.path.getmtime(os.path.join(packdir, 'imagery.sqlite'))).isoformat()
    rep.check(built == wrote, 'meta',
              f'built {built!r} matches the catalog mtime {wrote!r}')
    # `sources` records the ingests that were RUN, in the CLI's own
    # vocabulary — which is a third naming again, unrelated to the `source`
    # column (CLI `oils` writes rows saying `oldmaster`). What it is worth
    # checking is that a partial build is not about to be published as a
    # whole one: `--source schnorr` produces a perfectly honest pack that
    # happens to hold a twentieth of the art.
    declared = set(meta.get('sources', '').split(','))
    missing = ALL_CLI_SOURCES - declared
    rep.check(not missing, 'meta',
              f'all {len(ALL_CLI_SOURCES)} sources were built'
              + ('' if not missing else f' — missing {sorted(missing)}'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('packdir', help='the freshly built pack staging directory')
    ap.add_argument('--log', help='the build log, which names failed fetches')
    ap.add_argument('--against', action='append', default=[],
                    help='an older pack directory the rebuild must not regress'
                         ' on (repeatable)')
    args = ap.parse_args()

    conn = catalog(args.packdir)
    rep = Report()
    gate_counts(rep, conn, args.against)
    gate_coverage(rep, conn, args.log)
    gate_epistles(rep, conn)
    gate_images(rep, conn, args.packdir)
    gate_meta(rep, conn, args.packdir)

    print()
    if rep.failures:
        print(f'{len(rep.failures)} gate(s) failed — do not publish:')
        for line in rep.failures:
            print(f'  - {line}')
        return 1
    print('all gates passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
