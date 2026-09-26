"""Downloads are checked against their published checksums: the mirror's
manifest for SWORD modules, a `.sha256` beside each pack and each module of
Scriptura's own release. No network: the fetches are stubbed."""
import hashlib
import io
import os

import pytest

import fetch_errors
import sword_bridge as sb
import transfer


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, files):
    """urlopen answers from `files` {url: bytes}; anything else is a 404."""
    import urllib.error
    import urllib.request

    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url not in files:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        return _Resp(files[url])
    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)


def _hex(b):
    return hashlib.sha256(b).hexdigest()


def test_published_sums_read_what_sha256sum_writes(monkeypatch):
    url = 'https://x/pack.tar.gz'
    _serve(monkeypatch, {url + '.sha256': (
        f'{"a" * 64}  pack.tar.gz.000\n{"B" * 64} *pack.tar.gz.001\n'
        'not a sum\n').encode()})
    assert transfer.published_sums(url) == {'pack.tar.gz.000': 'a' * 64,
                                            'pack.tar.gz.001': 'b' * 64}
    _serve(monkeypatch, {url + '.sha256': ('c' * 64 + '\n').encode()})
    assert transfer.published_sums(url) == {'pack.tar.gz': 'c' * 64}
    _serve(monkeypatch, {})
    assert transfer.published_sums(url) is None     # none published: unchecked


def test_a_file_is_checked_part_by_part(tmp_path):
    one, two = b'first part', b'second part!'
    path = tmp_path / 'pack.part'
    path.write_bytes(one + two)
    parts = [('https://x/p.000', len(one)), ('https://x/p.001', len(two))]
    transfer.check_sums(str(path), parts,
                        {'p.000': _hex(one), 'p.001': _hex(two)})
    with pytest.raises(transfer.Damaged):
        transfer.check_sums(str(path), parts,
                            {'p.000': _hex(one), 'p.001': _hex(b'other')})
    single = tmp_path / 'one'
    single.write_bytes(one)
    transfer.check_sums(str(single), [('https://x/one', 0)], {'one': _hex(one)})
    with pytest.raises(transfer.Damaged):
        transfer.check_sums(str(single), [('https://x/one', 0)],
                            {'one': _hex(two)})


def test_a_damaged_download_is_said_plainly():
    assert fetch_errors.describe(transfer.Damaged('x')) == \
        'The download arrived damaged. Try again.'


def _ladder(monkeypatch, https_up, ftp_blob, mirror_blob):
    """CrossWire's HTTPS down or up, FTP answering `ftp_blob`, the mirror
    answering `mirror_blob`; returns what was fetched from where."""
    monkeypatch.setattr(sb, '_reachable',
                        lambda host, port, timeout=5:
                        https_up if port == 443 else True)
    path = 'packages/rawzip/KJV.zip'
    files = {f'{sb._CROSSWIRE_FTP}/{path}': ftp_blob,
             f'{sb._MIRROR_BASE}/KJV.zip': mirror_blob,
             f'{sb._CROSSWIRE_HTTPS}/{path}': b'from https'}
    _serve(monkeypatch, files)
    return path


def test_an_ftp_copy_that_fails_the_manifest_is_dropped_for_the_mirror(
        monkeypatch):
    good = b'the real KJV zip'
    path = _ladder(monkeypatch, False, b'changed on the way', good)
    monkeypatch.setattr(sb, '_mirror_manifest', lambda fresh=False: {
        'modules': {'KJV': {'version': '3.1', 'sha256': _hex(good)}}})
    monkeypatch.setattr(sb, '_catalogue_version', lambda name: '3.1')
    check = lambda blob, tier: sb._module_zip_ok('KJV', blob, tier)
    assert sb._fetch_crosswire(path, 10, check=check) == good


def test_a_mirror_copy_that_fails_the_manifest_is_refused(monkeypatch):
    path = _ladder(monkeypatch, False, None, b'stale mirror copy')
    monkeypatch.setattr(sb, '_mirror_manifest', lambda fresh=False: {
        'modules': {'KJV': {'version': '3.1', 'sha256': _hex(b'real')}}})
    monkeypatch.setattr(sb, '_catalogue_version', lambda name: '3.1')
    monkeypatch.setattr(sb, '_reachable',
                        lambda host, port, timeout=5: False)
    check = lambda blob, tier: sb._module_zip_ok('KJV', blob, tier)
    with pytest.raises(transfer.Damaged):
        sb._fetch_crosswire(path, 10, check=check)


def test_what_cannot_be_compared_is_not_refused(monkeypatch):
    entry = {'version': '3.0', 'sha256': _hex(b'old')}
    monkeypatch.setattr(sb, '_mirror_manifest',
                        lambda fresh=False: {'modules': {'KJV': entry}})
    monkeypatch.setattr(sb, '_catalogue_version', lambda name: '3.1')
    # A newer version on CrossWire than the weekly mirror has seen.
    assert sb._module_zip_ok('KJV', b'new', 'ftp')
    # A module the mirror may not hold (licensed to CrossWire alone).
    assert sb._module_zip_ok('ESV2011', b'x', 'mirror')
    # No manifest at all.
    monkeypatch.setattr(sb, '_mirror_manifest', lambda fresh=False: {})
    assert sb._module_zip_ok('KJV', b'x', 'mirror')


def test_https_is_not_second_guessed(monkeypatch):
    path = _ladder(monkeypatch, True, None, None)
    assert sb._fetch_crosswire(
        path, 10, check=lambda blob, tier: False) == b'from https'


def test_a_killed_install_leaves_no_staging_behind(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, '_SWORD_PATH', str(tmp_path))
    import time
    old = tmp_path / '.install-dead'
    (old / 'modules').mkdir(parents=True)
    hours_ago = time.time() - 2 * 3600
    os.utime(old, (hours_ago, hours_ago))
    # A young one may be another install still unpacking (the welcome
    # screen's own thread): it is left alone.
    live = tmp_path / '.install-live'
    live.mkdir()
    (tmp_path / 'mods.d').mkdir()
    new = sb._new_staging()
    assert not old.exists()
    assert live.exists()
    assert os.path.isdir(new) and (tmp_path / 'mods.d').exists()


def test_a_pack_that_fails_its_sums_is_thrown_away(monkeypatch, tmp_path):
    import catena_bridge
    import paths
    monkeypatch.setattr(paths, 'catena_db_path',
                        lambda: str(tmp_path / 'catena.db'))
    monkeypatch.setattr(transfer, 'probe', lambda url, timeout=30: 5)

    def fetch(parts, part, on_progress=None, extra=0, timeout=120):
        with open(part, 'wb') as fh:
            fh.write(b'bytes')
    monkeypatch.setattr(transfer, 'fetch_resumable', fetch)
    monkeypatch.setattr(transfer, 'published_sums',
                        lambda url, timeout=30: {'catena.db.gz': '0' * 64})
    with pytest.raises(transfer.Damaged):
        catena_bridge.download_and_install(url='https://x/catena.db.gz')
    assert not (tmp_path / 'catena.db.gz.part').exists()   # not resumed
    assert not (tmp_path / 'catena.db').exists()


def test_a_manifest_from_before_the_weekly_rebuild_is_read_again(
        monkeypatch):
    """Kept all session, the manifest refused the mirror's new copies."""
    new = b'rebuilt KJV zip'
    manifests = {False: {'modules': {'KJV': {'version': '3.1',
                                             'sha256': _hex(b'old zip')}}},
                 True: {'modules': {'KJV': {'version': '3.1',
                                            'sha256': _hex(new)}}}}
    asked = []

    def manifest(fresh=False):
        asked.append(fresh)
        return manifests[fresh]
    monkeypatch.setattr(sb, '_mirror_manifest', manifest)
    assert sb._module_zip_ok('KJV', new, 'mirror')
    assert asked == [False, True]
    assert not sb._module_zip_ok('KJV', b'bad', 'mirror')   # still refused
