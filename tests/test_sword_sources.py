"""Reading more than one CrossWire repository.

The released repository supplies all but a handful of modules and publishes
each one as a zip. The Lockman Foundation's — read for LBLA and NBLA, the only
mainstream modern Spanish translations anyone may hand out — publishes no zips
at all, so a module from it is installed file by file. What is worth testing is
that the two never get confused: a module listed from one repository and
fetched from the other would ask for a zip that is not there.

Nothing here touches the network. The catalogue archives are built in memory
and the fetches are stubbed.
"""
import io
import json
import os
import tarfile

import pytest

import sword_bridge


def _catalogue(confs):
    """A mods.d.tar.gz holding `confs` — {filename: text}."""
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode='w:gz') as tar:
        for name, text in confs.items():
            data = text.encode('utf-8')
            info = tarfile.TarInfo(f'mods.d/{name}')
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return blob.getvalue()


def _conf(name, datapath=None, extra=''):
    return (f'[{name}]\n'
            f'DataPath=./modules/texts/ztext/{datapath or name.lower()}/\n'
            f'ModDrv=zText\n'
            f'Lang=es\n'
            f'Description={name} text\n{extra}')


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    """An InstallMgr shadow dir the bridge will read as the current one."""
    path = tmp_path / 'shadow'
    (path / 'mods.d').mkdir(parents=True)
    monkeypatch.setattr(sword_bridge, '_shadow_path', lambda: str(path))
    return path


# ── merging the catalogues ────────────────────────────────────────────────────

def test_extract_returns_the_names_it_wrote(tmp_path):
    mods_d = tmp_path / 'mods.d'
    mods_d.mkdir()
    written = sword_bridge._extract_catalogue(
        _catalogue({'lbla.conf': _conf('LBLA'), 'nbla.conf': _conf('NBLA')}),
        str(mods_d))
    assert sorted(written) == ['LBLA', 'NBLA']
    assert sorted(p.name for p in mods_d.iterdir()) == ['lbla.conf',
                                                        'nbla.conf']


def test_the_released_repository_wins_a_name_collision(tmp_path):
    """A module in both repositories must stay the ordinary zip install —
    otherwise it is listed from one and fetched from the other."""
    mods_d = tmp_path / 'mods.d'
    mods_d.mkdir()
    sword_bridge._extract_catalogue(
        _catalogue({'shared.conf': _conf('Shared', datapath='released')}),
        str(mods_d))
    written = sword_bridge._extract_catalogue(
        _catalogue({'shared.conf': _conf('Shared', datapath='second')}),
        str(mods_d), skip_existing=True)
    assert written == []                      # not claimed by the second source
    text = (mods_d / 'shared.conf').read_text(encoding='utf-8')
    assert 'released' in text and 'second' not in text


# ── which repository a module came from ───────────────────────────────────────

def test_a_module_with_no_recorded_source_is_from_the_released_repo(shadow):
    (shadow / sword_bridge._SOURCES_FILE).write_text(
        json.dumps({'LBLA': 'lockmanraw'}), encoding='utf-8')
    assert sword_bridge._module_source('LBLA') == 'lockmanraw'
    assert sword_bridge._module_source('SpaRV') is None


def test_a_shadow_dir_written_before_this_existed_still_installs(shadow):
    """Every shadow dir on disk today has no sources file. Each of its
    modules is from the released repository, and that is the right answer —
    not an error, and not a refusal to install."""
    assert not (shadow / sword_bridge._SOURCES_FILE).exists()
    assert sword_bridge._module_source('SpaRV') is None


def test_an_unreadable_sources_file_is_not_fatal(shadow):
    (shadow / sword_bridge._SOURCES_FILE).write_text('{ not json',
                                                     encoding='utf-8')
    assert sword_bridge._module_source('LBLA') is None


# ── the install routes by source ──────────────────────────────────────────────

def test_install_takes_the_zip_path_for_a_released_module(shadow, monkeypatch):
    calls = []
    monkeypatch.setattr(sword_bridge, '_module_source', lambda _n: None)
    monkeypatch.setattr(sword_bridge, '_fetch_crosswire',
                        lambda path, _t: calls.append(path) or _stub_zip())
    monkeypatch.setattr(sword_bridge, '_reset', lambda: None)
    monkeypatch.setattr(sword_bridge, '_safe_extract', lambda *a: None)
    monkeypatch.setattr(sword_bridge, '_zip_conf_members', lambda _i: [])
    sword_bridge.install_module('SpaRV')
    assert calls == ['packages/rawzip/SpaRV.zip']


def _stub_zip():
    blob = io.BytesIO()
    with __import__('zipfile').ZipFile(blob, 'w') as zf:
        zf.writestr('mods.d/spaRV.conf', '[SpaRV]\n')
    return blob.getvalue()


def test_install_fetches_file_by_file_for_a_lockman_module(shadow, tmp_path,
                                                           monkeypatch):
    """The whole point of the second path: no zip is ever asked for, and the
    files land where the conf's DataPath says."""
    (shadow / 'mods.d' / 'lbla.conf').write_text(_conf('LBLA'),
                                                 encoding='utf-8')
    home = tmp_path / 'sword'
    home.mkdir()
    monkeypatch.setattr(sword_bridge, '_SWORD_PATH', str(home))
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: 'lockmanraw')
    monkeypatch.setattr(sword_bridge, '_list_remote_dir',
                        lambda path, **k: ['ot.bzz', 'ot.bzs'])
    fetched = []
    monkeypatch.setattr(
        sword_bridge, '_fetch_crosswire',
        lambda path, _t: fetched.append(path) or b'data:' + path.encode())
    monkeypatch.setattr(sword_bridge, '_reset', lambda: None)

    sword_bridge.install_module('LBLA')

    assert fetched == ['lockmanraw/modules/texts/ztext/lbla/ot.bzz',
                       'lockmanraw/modules/texts/ztext/lbla/ot.bzs']
    data = home / 'modules' / 'texts' / 'ztext' / 'lbla'
    assert sorted(p.name for p in data.iterdir()) == ['ot.bzs', 'ot.bzz']
    assert (home / 'mods.d' / 'lbla.conf').exists()


def test_a_lockman_install_writes_nothing_when_a_fetch_fails(shadow, tmp_path,
                                                             monkeypatch):
    """Everything is pulled before anything is written, so a fetch that dies
    halfway leaves no half-installed module behind."""
    (shadow / 'mods.d' / 'lbla.conf').write_text(_conf('LBLA'),
                                                 encoding='utf-8')
    home = tmp_path / 'sword'
    home.mkdir()
    monkeypatch.setattr(sword_bridge, '_SWORD_PATH', str(home))
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: 'lockmanraw')
    monkeypatch.setattr(sword_bridge, '_list_remote_dir',
                        lambda path, **k: ['ot.bzz', 'ot.bzs'])

    def _fetch(path, _t):
        if path.endswith('ot.bzs'):
            raise RuntimeError('connection lost')
        return b'data'
    monkeypatch.setattr(sword_bridge, '_fetch_crosswire', _fetch)
    monkeypatch.setattr(sword_bridge, '_reset', lambda: None)

    with pytest.raises(RuntimeError):
        sword_bridge.install_module('LBLA')
    assert not (home / 'modules').exists()
    assert not (home / 'mods.d' / 'lbla.conf').exists()


def test_a_module_missing_from_the_cached_list_says_so(shadow, monkeypatch):
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: 'lockmanraw')
    with pytest.raises(RuntimeError, match='Refresh'):
        sword_bridge.install_module('LBLA')


def test_a_datapath_that_escapes_the_sword_dir_is_refused(shadow, tmp_path,
                                                          monkeypatch):
    """The same guard the zip path enforces. DataPath is written by whoever
    built the module, and here it is joined onto the sword root."""
    (shadow / 'mods.d' / 'evil.conf').write_text(
        '[Evil]\nDataPath=./../../../../tmp/pwned/\nModDrv=zText\n',
        encoding='utf-8')
    home = tmp_path / 'sword'
    home.mkdir()
    monkeypatch.setattr(sword_bridge, '_SWORD_PATH', str(home))
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: 'lockmanraw')
    with pytest.raises(ValueError, match='escapes'):
        sword_bridge.install_module('Evil')


# ── what must never be re-served ──────────────────────────────────────────────

def test_the_lockman_licence_is_never_mirrored():
    """Lockman's permission runs to CrossWire, not to us: a reader may fetch
    LBLA from CrossWire's own host, and Scriptura's mirror may not carry it.
    Reading a second repository is exactly the change that makes forgetting
    this possible, so the refusal is pinned here rather than left to the
    builder's own reading of the licence table.
    """
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        'tools', 'build-sword-mirror.py')
    spec = importlib.util.spec_from_file_location('build_sword_mirror', path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    licence = 'Copyrighted; Permission to distribute granted to CrossWire'
    assert licence not in builder.KNOWN_LICENCES
    assert licence in builder.KNOWN_EXCLUDED
    # And the builder reads the released repository only, so a module that
    # exists solely in another one can never reach it in the first place.
    source = open(path, encoding='utf-8').read()
    assert "fetch('raw/mods.d.tar.gz'" in source


# ── the directory listing ─────────────────────────────────────────────────────

def test_the_listing_keeps_only_plain_filenames(monkeypatch):
    """A repository listing is not a place a path should ever need repairing,
    so anything with a separator in it is dropped rather than sanitised."""
    page = ('<a href="?C=N;O=D">Name</a>'
            '<a href="/ftpmirror/pub/sword/">Parent</a>'
            '<a href="ot.bzz">ot.bzz</a>'
            '<a href="nt.bzs">nt.bzs</a>'
            '<a href="sub/dir/file">nested</a>')

    class _Resp:
        def read(self):
            return page.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _Resp())
    assert sword_bridge._list_remote_dir('lockmanraw/x') == ['ot.bzz',
                                                             'nt.bzs']


def test_a_nested_directory_stops_the_install(monkeypatch):
    """Quietly skipping a subdirectory would install a module missing half of
    itself, which reads on screen as a Bible with no text."""
    page = ('<a href="ot.bzz">ot.bzz</a>'
            '<a href="extra/">extra/</a>')

    class _Resp:
        def read(self):
            return page.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError, match='subdirectories'):
        sword_bridge._list_remote_dir('lockmanraw/x')


def test_a_corrupt_second_catalogue_does_not_lose_the_first(tmp_path,
                                                            monkeypatch):
    """Losing LBLA is not a reason to lose the other four hundred modules —
    and a truncated archive is exactly as survivable as a failed download."""
    home = tmp_path / 'home'
    (home / '.sword' / 'InstallMgr').mkdir(parents=True)
    monkeypatch.setattr(os.path, 'expanduser',
                        lambda p: p.replace('~', str(home)))

    good = _catalogue({'sparv.conf': _conf('SpaRV')})

    def _fetch(path, _t):
        if path.startswith(sword_bridge._RELEASED_SOURCE):
            return good
        return b'not a gzip archive at all'
    monkeypatch.setattr(sword_bridge, '_fetch_crosswire', _fetch)
    monkeypatch.setattr(sword_bridge, '_fetch_scriptura', _no_network)

    sword_bridge.refresh_source()          # must not raise

    shadow = next((home / '.sword' / 'InstallMgr').iterdir())
    assert (shadow / 'mods.d' / 'sparv.conf').exists()
    assert json.loads(
        (shadow / sword_bridge._SOURCES_FILE).read_text()) == {}


def test_an_unreachable_crosswire_explains_itself(monkeypatch):
    """These modules have no mirror by licence, so a socket error must not
    reach the reader as the whole story."""
    import urllib.error

    def _boom(*a, **k):
        raise urllib.error.URLError('connection refused')
    monkeypatch.setattr('urllib.request.urlopen', _boom)
    with pytest.raises(RuntimeError, match='no backup mirror'):
        sword_bridge._list_remote_dir('lockmanraw/x')


# ── Scriptura's own repository ───────────────────────────────────────────────
#
# The Spanish dictionary is built by tools/build_spanish_dict.py and exists
# nowhere else, so it is served from Scriptura's own release rather than from
# CrossWire or from the mirror. What matters is the same thing the two
# CrossWire repositories are tested for: that a module is fetched from the
# repository it was listed from.


def _no_network(*_a, **_k):
    raise AssertionError('a test reached the network')


def test_our_catalogue_is_recorded_against_our_source(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    (home / '.sword' / 'InstallMgr').mkdir(parents=True)
    monkeypatch.setattr(os.path, 'expanduser',
                        lambda p: p.replace('~', str(home)))
    monkeypatch.setattr(
        sword_bridge, '_fetch_crosswire',
        lambda path, _t: _catalogue({'sparv.conf': _conf('SpaRV')}))
    monkeypatch.setattr(
        sword_bridge, '_fetch_scriptura',
        lambda name, _t: _catalogue({'wikcionario.conf': _conf('Wikcionario')}))

    sword_bridge.refresh_source()

    shadow = next((home / '.sword' / 'InstallMgr').iterdir())
    sources = json.loads((shadow / sword_bridge._SOURCES_FILE).read_text())
    assert sources == {'Wikcionario': sword_bridge._SCRIPTURA_SOURCE}
    assert (shadow / 'mods.d' / 'wikcionario.conf').exists()
    assert (shadow / 'mods.d' / 'sparv.conf').exists()


def test_our_repository_being_unreachable_does_not_lose_the_refresh(
        tmp_path, monkeypatch):
    """A reader whose network reached CrossWire but not GitHub keeps the four
    hundred modules they just catalogued."""
    home = tmp_path / 'home'
    (home / '.sword' / 'InstallMgr').mkdir(parents=True)
    monkeypatch.setattr(os.path, 'expanduser',
                        lambda p: p.replace('~', str(home)))
    monkeypatch.setattr(
        sword_bridge, '_fetch_crosswire',
        lambda path, _t: _catalogue({'sparv.conf': _conf('SpaRV')}))

    def _down(_name, _t):
        raise OSError('github unreachable')
    monkeypatch.setattr(sword_bridge, '_fetch_scriptura', _down)

    sword_bridge.refresh_source()          # must not raise

    shadow = next((home / '.sword' / 'InstallMgr').iterdir())
    assert (shadow / 'mods.d' / 'sparv.conf').exists()
    assert json.loads((shadow / sword_bridge._SOURCES_FILE).read_text()) == {}


def test_install_fetches_our_module_from_our_release(shadow, monkeypatch):
    calls = []
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: sword_bridge._SCRIPTURA_SOURCE)
    monkeypatch.setattr(sword_bridge, '_fetch_crosswire', _no_network)
    monkeypatch.setattr(sword_bridge, '_fetch_scriptura',
                        lambda name, _t: calls.append(name) or _stub_zip())
    monkeypatch.setattr(sword_bridge, '_reset', lambda: None)
    monkeypatch.setattr(sword_bridge, '_safe_extract', lambda *a: None)
    monkeypatch.setattr(sword_bridge, '_zip_conf_members', lambda _i: [])

    sword_bridge.install_module('Wikcionario')

    assert calls == ['Wikcionario.zip']


def test_our_module_never_takes_the_file_by_file_path(shadow, monkeypatch):
    """`_install_raw_module` is for a repository that publishes no zips.
    Ours publishes one per module, and sending it down that path would walk
    a directory listing that does not exist."""
    monkeypatch.setattr(sword_bridge, '_module_source',
                        lambda _n: sword_bridge._SCRIPTURA_SOURCE)
    monkeypatch.setattr(sword_bridge, '_install_raw_module', _no_network)
    monkeypatch.setattr(sword_bridge, '_fetch_scriptura',
                        lambda _n, _t: _stub_zip())
    monkeypatch.setattr(sword_bridge, '_reset', lambda: None)
    monkeypatch.setattr(sword_bridge, '_safe_extract', lambda *a: None)
    monkeypatch.setattr(sword_bridge, '_zip_conf_members', lambda _i: [])

    sword_bridge.install_module('Wikcionario')      # must not raise
