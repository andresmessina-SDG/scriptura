#!/usr/bin/env python3
"""Pre-release check: every downloadable data pack URL actually resolves.

Run this BEFORE tagging a release. The packs are hosted as Codeberg release
assets and are bumped by hand, independently of the app — so a `PACK_URL`
pointing at a tag that was never published is invisible in the repo, invisible
in the test suite, and only surfaces when a user clicks Install. That is a
shipped dead end, and it has happened: `catena-pack-v2` was referenced in code
for a week while only `catena-pack-v1` existed on the server, breaking first
install and update alike.

Checks, per bridge:

  catena  — a single asset; the URL must resolve, and the app-declared
            LATEST_BUILT must be a real date (it gates the Update nudge, so a
            value newer than the published pack means a button that 404s).
  imagery — a split asset; `_resolve_parts` must enumerate at least one part.
            The bare `imagery.tar.gz` 404ing is EXPECTED and not a fault:
            large packs are served as `.000/.001/…` and the resolver probes
            for those first.

Usage:  python3 tools/verify-pack-urls.py
Exit 0 = every pack reachable, 1 = at least one is not, 2 = network trouble.

Network-dependent by nature, which is why this is a release-time script and
not a pytest case — a unit test that fails on a flaky connection trains people
to ignore it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import catena_bridge
import imagery_bridge


def check_catena() -> tuple[bool, str]:
    size = imagery_bridge._probe(catena_bridge.PACK_URL)
    if size is None:
        return False, (f'404 — {catena_bridge.PACK_URL}\n'
                       f'         the release asset does not exist; publish it '
                       f'or point PACK_URL back at a tag that does')
    if size < 1_000_000:
        return False, f'suspiciously small ({size} bytes) — is it an error page?'
    return True, (f'{size / 1e6:.1f} MB, LATEST_BUILT={catena_bridge.LATEST_BUILT}')


def check_imagery() -> tuple[bool, str]:
    parts = imagery_bridge._resolve_parts(imagery_bridge.PACK_URL)
    total = sum(s for _, s in parts)
    return True, f'{len(parts)} part(s), {total / 1e6:.1f} MB'


def main() -> int:
    failed = False
    for name, check in (('catena', check_catena), ('imagery', check_imagery)):
        try:
            ok, detail = check()
        except FileNotFoundError as e:
            ok, detail = False, str(e)
        except Exception as e:                      # network, TLS, DNS…
            print(f'  {name:8} ERROR  {e!r}', file=sys.stderr)
            return 2
        print(f'  {name:8} {"ok   " if ok else "FAIL "} {detail}')
        failed |= not ok
    if failed:
        print('\na pack URL does not resolve — publishing this release would '
              'ship a dead Install button', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
