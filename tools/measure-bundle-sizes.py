#!/usr/bin/env python3
"""Measure what each welcome bundle downloads, for `welcome._SIZES`.

The welcome cards show a size, and on first run nothing is on disk to
compute one from: neither the SWORD nor the eBible catalogue has been
fetched yet, and fetching both just to label three cards would put the
network in front of the first screen. So the sizes are measured here, by
asking each host for the length of the exact file the install fetches, and
written into welcome.py by hand.

    python3 tools/measure-bundle-sizes.py          # print the table
    python3 tools/measure-bundle-sizes.py --check  # exit 1 if welcome.py
                                                   # is more than 20% off

Needs the network, and the SWORD catalogue cached in the Module Manager
(the Lockman modules are read a file at a time from their own repository,
and only the cached conf says where).
"""
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import catena_bridge  # noqa: E402
import ebible_bridge  # noqa: E402
import open_data  # noqa: E402
import sword_bridge as sb  # noqa: E402
import welcome  # noqa: E402

#: How far a stored size may drift before --check calls it stale. Modules are
#: re-issued now and then; a card that says 40 MB for 44 is still honest.
TOLERANCE = 0.2


def _length(url):
    req = urllib.request.Request(url, method='HEAD',
                                 headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers['Content-Length'])


def _sword(name):
    source = sb._module_source(name)
    if source == sb._SCRIPTURA_SOURCE:
        return _length(f'{sb._SCRIPTURA_BASE}/{name}.zip')
    if source is None:
        # A catalogue cached before a module moved to Scriptura's release
        # still names no source for it, so ask there when CrossWire has none.
        try:
            return _length(f'{sb._CROSSWIRE_HTTPS}/packages/rawzip/{name}.zip')
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            return _length(f'{sb._SCRIPTURA_BASE}/{name}.zip')
    conf = os.path.join(sb._shadow_path() or '', 'mods.d',
                        f'{name.lower()}.conf')
    data_dir = sb._module_data_dir(sb._parse_conf(conf))
    return sum(_length(f'{sb._CROSSWIRE_HTTPS}/{source}/{data_dir}/{n}')
               for n in sb._list_remote_dir(f'{source}/{data_dir}'))


def measure(kind, ident):
    if kind == 'sword':
        return _sword(ident)
    if kind == 'ebible':
        return _length(ebible_bridge._USFM_URL.format(id=ident))
    if kind == 'opendata':
        return _length(open_data._SOURCES[ident]['url'])
    if kind == 'catena':
        return _length(catena_bridge.PACK_URL)
    raise ValueError(kind)


def main():
    items = sorted({(k, i) for table in welcome._CATALOGUE.values()
                    for entry in table.values()
                    for k, i, _l, _f in entry['items']})
    sizes = {item: measure(*item) for item in items}
    if '--check' in sys.argv:
        stale = [(item, welcome._SIZES.get(item), got)
                 for item, got in sizes.items()
                 if not welcome._SIZES.get(item)
                 or abs(got - welcome._SIZES[item]) > TOLERANCE * got]
        for item, had, got in stale:
            print(f'{item}: welcome.py says {had}, the host says {got}')
        return 1 if stale else 0
    for (kind, ident), size in sizes.items():
        print(f'    ({kind!r}, {ident!r}): {size:_},')
    return 0


if __name__ == '__main__':
    sys.exit(main())
