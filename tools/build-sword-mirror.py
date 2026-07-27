#!/usr/bin/env python3
"""Build a redistributable mirror of the CrossWire SWORD module repository.

CrossWire serves every SWORD module from a single host, and that host goes
down: four incidents between March and July 2026, the last one taking the
web server, wiki and bug tracker with it for nine hours. sword_bridge.py
already falls back from HTTPS to FTP, but both daemons live on that one
machine, so neither helps when the box itself is unreachable. This builds
the third tier — an independent copy Scriptura can fetch from when
CrossWire is gone entirely.

It cannot be a complete copy. Roughly a fifth of the repository by size is
licensed to CrossWire specifically, in terms that grant *them* the right to
distribute and no one else; one module says so in as many words ("No other
distribution permitted"). CrossWire keeps a read-blocked takedown/ directory
on its own FTP server, which is a fair indication of how those agreements
are enforced. So this mirrors an allowlisted subset and nothing else.

Classification is by exact match against KNOWN_LICENCES below. A licence
string that is not in that table is excluded and reported, never guessed
at — if CrossWire adds a new licence wording, this script must be updated
deliberately rather than quietly mirroring something it should not.

  Tier 1  public domain, CC0, CC-BY, CC-BY-SA, GPL, GFDL. Redistributable
          by anyone for any purpose.
  Tier 2  additionally the "freely distributable", "free non-commercial"
          and NC/ND Creative Commons texts. These permit verbatim
          non-commercial redistribution, which is what Scriptura is, and
          depend on it staying that way.

Usage:
    tools/build-sword-mirror.py --out DIR [--tier {1,2}] [--jobs N]
    tools/build-sword-mirror.py --out DIR --report-only
    tools/build-sword-mirror.py --out DIR --baseline URL|PATH

--baseline makes the rebuild incremental: modules whose Version is
unchanged since that manifest are carried over untouched, and only new or
updated ones are downloaded. The weekly refresh uses it. This matters for
politeness as much as speed — re-pulling half a gigabyte every week from
the same fragile host these outages keep taking down would be a poor way
to treat it.

Writes DIR/mods.d.tar.gz, DIR/manifest.json, DIR/changes.json and the
downloaded DIR/modules/*.zip. Upload with tools/publish-sword-mirror.sh.
"""

import argparse
import concurrent.futures
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile

CROSSWIRE_HTTPS = 'https://crosswire.org/ftpmirror/pub/sword'
CROSSWIRE_FTP = 'ftp://ftp.crosswire.org/pub/sword'

# Exact DistributionLicense strings, mapped to the tier they belong to.
# Anything absent is excluded. Keys are matched case-sensitively after
# whitespace stripping, except where CrossWire's own data varies the case
# (see _tier_for, which retries case-folded).
KNOWN_LICENCES = {
    # ── Tier 1: unrestricted redistribution ───────────────────────────
    'Public Domain': 1,
    'Creative Commons: CC0': 1,
    'Creative Commons: BY 4.0': 1,
    'Creative Commons: BY-SA 4.0': 1,
    'Creative Commons: by-sa': 1,
    'Creative Commons Attribution 3.0 Brazil': 1,
    'GPL': 1,
    'GFDL': 1,
    # ── Tier 2: verbatim non-commercial redistribution ────────────────
    'Copyrighted; Freely distributable': 2,
    'Copyrighted; Free non-commercial distribution': 2,
    'Creative Commons: BY-NC-SA 4.0': 2,
    'Creative Commons: BY-NC-ND 4.0': 2,
    'Creative Commons: by-nd 3.0': 2,
}

# Licence strings we have seen and deliberately refuse to mirror. Listed
# explicitly so the report can distinguish "known, excluded on purpose"
# from "new wording, needs a human" — only the latter is a reason to stop.
KNOWN_EXCLUDED = {
    'Copyrighted',
    'Copyrighted; Permission to distribute granted to CrossWire',
    'Copyrighted. Distribution permitted to CrossWire Bible Society',
    'copyrighted. Permission to distribute granted to CrossWire Bible Society',
    'Copyrighted. Noncommercial distribution granted to CrossWire. '
    'No other distribution permitted.',
    'Copyrighted Kitab Company - KŞ; Permission to distribute granted to '
    'CrossWire',
    # A general grant on its face, but "in SWORD format" is doing unclear
    # work and the holders are unknown to us. Excluded pending review.
    'Copyrighted; Permission granted to distribute non-commercially in '
    'SWORD format',
    'See README file',
}


def fetch(path, timeout=120):
    """Download `path` from CrossWire, HTTPS first then FTP.

    Mirrors the ladder in sword_bridge._fetch_crosswire so that building
    the mirror works on exactly the days the mirror exists for.
    """
    try:
        with urllib.request.urlopen(f'{CROSSWIRE_HTTPS}/{path}',
                                    timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError) as exc:
        print(f'  HTTPS failed ({exc}) — trying FTP', file=sys.stderr)
    with urllib.request.urlopen(f'{CROSSWIRE_FTP}/{path}',
                                timeout=timeout) as resp:
        return resp.read()


def parse_catalogue(data):
    """Yield (module_name, licence, version) from a mods.d.tar.gz blob."""
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.name.endswith('.conf') or member.isdir():
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            text = fh.read().decode('utf-8', 'replace')
            name = re.search(r'^\[(.+?)\]', text, re.M)
            if not name:
                continue
            licence = re.search(r'^DistributionLicense\s*=\s*(.+)$', text, re.M)
            version = re.search(r'^Version\s*=\s*(.+)$', text, re.M)
            yield (name.group(1).strip(),
                   licence.group(1).strip() if licence else '',
                   version.group(1).strip() if version else '')


# CrossWire's data varies capitalisation on otherwise identical wording, so
# the exact-match table is backed by a case-folded one. Built once: it was
# being rebuilt on every miss.
_FOLDED_LICENCES = {k.casefold(): v for k, v in KNOWN_LICENCES.items()}


def _tier_for(licence):
    """Tier number for a licence string, or None if it must not be mirrored."""
    if licence in KNOWN_LICENCES:
        return KNOWN_LICENCES[licence]
    return _FOLDED_LICENCES.get(licence.casefold())


def classify(catalogue, max_tier):
    """Split the catalogue into (included, excluded, unknown) lists."""
    included, excluded, unknown = [], [], []
    for name, licence, version in catalogue:
        tier = _tier_for(licence)
        if tier is not None and tier <= max_tier:
            included.append({'module': name, 'licence': licence,
                             'tier': tier, 'version': version})
        elif tier is not None or licence in KNOWN_EXCLUDED:
            excluded.append((name, licence))
        elif not licence:
            excluded.append((name, '<no DistributionLicense field>'))
        else:
            unknown.append((name, licence))
    return included, excluded, unknown


def download_module(entry, out_dir):
    """Fetch one module zip, verify it opens, and record size + digest."""
    name = entry['module']
    dest = os.path.join(out_dir, f'{name}.zip')
    if os.path.exists(dest):
        blob = open(dest, 'rb').read()
    else:
        try:
            blob = fetch(f'packages/rawzip/{name}.zip')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return entry, 'missing upstream'
            raise
        # A truncated download that still unzips would poison the mirror
        # silently, so validate before it is written where publish can see it.
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            if zf.testzip() is not None:
                return entry, 'corrupt archive'
        tmp = dest + '.part'
        with open(tmp, 'wb') as fh:
            fh.write(blob)
        os.replace(tmp, dest)
    entry['bytes'] = len(blob)
    entry['sha256'] = hashlib.sha256(blob).hexdigest()
    return entry, None


def load_baseline(ref):
    """Read a previously published manifest from a URL or path.

    A missing baseline is not an error — it just means a full build. That
    keeps the weekly job working on its first run, before any manifest has
    ever been published.
    """
    try:
        if ref.startswith(('http://', 'https://')):
            with urllib.request.urlopen(ref, timeout=60) as resp:
                data = json.load(resp)
        else:
            with open(ref) as fh:
                data = json.load(fh)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f'  no usable baseline ({exc}) — building everything',
              file=sys.stderr)
        return {}
    return {e['module']: e for e in data.get('modules', [])}


def plan(included, baseline):
    """Split included modules into (fetch, carried) against a baseline.

    A module is carried over when the baseline holds it at the same
    Version. Modules with no Version field either side are treated as
    static: CrossWire does re-cut those occasionally, so --full exists to
    force a rebuild when that is suspected.
    """
    fetch, carried = [], []
    for entry in included:
        old = baseline.get(entry['module'])
        if old and old.get('version', '') == entry['version'] \
                and old.get('sha256'):
            carried.append({**entry, 'bytes': old['bytes'],
                            'sha256': old['sha256']})
        else:
            fetch.append(entry)
    return fetch, carried


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True, help='staging directory')
    ap.add_argument('--tier', type=int, choices=(1, 2), default=2,
                    help='highest licence tier to include (default 2)')
    ap.add_argument('--jobs', type=int, default=6,
                    help='parallel downloads (default 6)')
    ap.add_argument('--report-only', action='store_true',
                    help='classify and print totals, download nothing')
    ap.add_argument('--baseline', metavar='URL|PATH',
                    help='published manifest.json; fetch only what changed')
    ap.add_argument('--full', action='store_true',
                    help='ignore --baseline and re-download everything')
    args = ap.parse_args()

    print('Fetching catalogue…')
    catalogue_blob = fetch('raw/mods.d.tar.gz', timeout=60)
    catalogue = sorted(parse_catalogue(catalogue_blob))
    print(f'  {len(catalogue)} modules in CrossWire catalogue')

    included, excluded, unknown = classify(catalogue, args.tier)
    print(f'  {len(included)} included (tier <= {args.tier})')
    print(f'  {len(excluded)} excluded by licence')

    if unknown:
        print(f'\n{len(unknown)} UNRECOGNISED licence string(s) — these are '
              'not mirrored. Review and add to KNOWN_LICENCES or '
              'KNOWN_EXCLUDED:', file=sys.stderr)
        for name, licence in unknown:
            print(f'  {name:24s} {licence}', file=sys.stderr)

    if args.report_only:
        return 0

    baseline = {}
    if args.baseline and not args.full:
        print(f'Reading baseline {args.baseline} …')
        baseline = load_baseline(args.baseline)
    to_fetch, carried = plan(included, baseline)

    # Anything the baseline published that is no longer eligible must come
    # down again. A licence can be tightened upstream, and continuing to
    # serve a module after that is exactly the failure this mirror's whole
    # design is meant to avoid.
    eligible = {e['module'] for e in included}
    removed = sorted(set(baseline) - eligible)

    os.makedirs(args.out, exist_ok=True)
    modules_dir = os.path.join(args.out, 'modules')
    os.makedirs(modules_dir, exist_ok=True)

    with open(os.path.join(args.out, 'mods.d.tar.gz'), 'wb') as fh:
        fh.write(catalogue_blob)

    if baseline:
        print(f'  {len(carried)} unchanged, {len(to_fetch)} to fetch, '
              f'{len(removed)} to withdraw')

    print(f'\nDownloading {len(to_fetch)} modules to {modules_dir}…')
    done, skipped, fetched = list(carried), [], []
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(download_module, e, modules_dir)
                   for e in to_fetch]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            entry, problem = fut.result()
            if problem:
                skipped.append((entry['module'], problem))
            else:
                done.append(entry)
                fetched.append(entry['module'])
            if i % 25 == 0 or i == len(to_fetch):
                print(f'  {i}/{len(to_fetch)}')

    total = sum(e['bytes'] for e in done)
    manifest = {
        'source': 'https://crosswire.org/ftpmirror/pub/sword',
        'tier': args.tier,
        'modules': sorted(done, key=lambda e: e['module'].lower()),
        'catalogue_sha256': hashlib.sha256(catalogue_blob).hexdigest(),
    }
    with open(os.path.join(args.out, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
        fh.write('\n')

    # Consumed by publish-sword-mirror.sh: what to withdraw, and whether
    # there is anything to publish at all.
    changes = {
        'fetched': sorted(fetched),
        'unchanged': len(carried),
        'removed': removed,
        'unrecognised': [n for n, _lic in unknown],
    }
    with open(os.path.join(args.out, 'changes.json'), 'w') as fh:
        json.dump(changes, fh, indent=1, sort_keys=True)
        fh.write('\n')

    print(f'\n{len(done)} modules, {total / 1048576:.0f} MB')
    if removed:
        print(f'{len(removed)} to withdraw: {", ".join(removed)}')
    if skipped:
        print(f'{len(skipped)} skipped:')
        for name, why in skipped:
            print(f'  {name:24s} {why}')
    print(f'manifest: {os.path.join(args.out, "manifest.json")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
