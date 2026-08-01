"""Tests for the SWORD module sideload helpers in sword_bridge.py —
in-memory zip inspection, selective install, version comparison, cipher
key writing, and the zip path-traversal guard. None of these touch the
SWORD library; _SWORD_PATH is redirected to a tmp dir per test."""

import io
import os
import zipfile

import pytest

import sword_bridge


# ── fixtures / helpers ─────────────────────────────────────────────────────────

@pytest.fixture
def sword_home(tmp_path, monkeypatch):
    """Redirect _SWORD_PATH to a throwaway dir and start with nothing
    installed."""
    home = tmp_path / 'sword'
    (home / 'mods.d').mkdir(parents=True)
    monkeypatch.setattr(sword_bridge, '_SWORD_PATH', str(home))
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: [])
    return home


def _conf(name, *, version='1.0', locked=False, datapath=None):
    datapath = datapath or f'./modules/texts/ztext/{name.lower()}/'
    lines = [
        f'[{name}]',
        f'DataPath={datapath}',
        'ModDrv=zText',
        f'Description={name} test module',
        'Lang=en',
        f'Version={version}',
    ]
    if locked:
        lines.append('CipherKey=')
    return '\n'.join(lines) + '\n'


def _make_zip(modules):
    """modules: list of (name, conf_text, [(path, bytes), ...])."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, conf, datafiles in modules:
            z.writestr(f'mods.d/{name.lower()}.conf', conf)
            for path, content in datafiles:
                z.writestr(path, content)
    return buf.getvalue()


# ── cmp_version ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('a,b,expected', [
    ('2.3', '2.1', 1),
    ('1.0', '1.0', 0),
    ('1.9', '1.10', -1),      # numeric, not lexical
    ('2.0', '1.9.9', 1),
    ('1.0', '1', 1),          # longer is newer when prefix matches
    ('1.0a', '1.0', 1),       # non-numeric component sorts after numeric
])
def test_cmp_version(a, b, expected):
    assert sword_bridge.cmp_version(a, b) == expected


# ── _parse_conf_lines ──────────────────────────────────────────────────────────

def test_parse_conf_lines_captures_version_and_cipher():
    info = sword_bridge._parse_conf_lines(_conf('Foo', version='3.1', locked=True).splitlines())
    assert info['name'] == 'Foo'
    assert info['version'] == '3.1'
    assert 'cipherkey' in info and info['cipherkey'] == ''


def test_parse_conf_lines_no_cipher_key_absent():
    info = sword_bridge._parse_conf_lines(_conf('Foo').splitlines())
    assert 'cipherkey' not in info


# ── _category_from_info ────────────────────────────────────────────────────────

def test_category_from_moddrv():
    assert sword_bridge._category_from_info({'moddrv': 'zText'}) == 'Biblical Texts'
    assert sword_bridge._category_from_info({'moddrv': 'zCom'}) == 'Commentaries'
    assert sword_bridge._category_from_info({'moddrv': 'zLD'}) == 'Lexicons / Dictionaries'


# ── inspect_module_zip ─────────────────────────────────────────────────────────

def test_inspect_single_module(sword_home):
    z = _make_zip([('KJVx', _conf('KJVx', version='2.3'),
                    [('modules/texts/ztext/kjvx/ot.bzs', b'a' * 1000)])])
    mods = sword_bridge.inspect_module_zip(z)
    assert len(mods) == 1
    m = mods[0]
    assert m['name'] == 'KJVx'
    assert m['version'] == '2.3'
    assert m['type'] == 'Biblical Texts'
    assert m['size'] == 1000
    assert m['locked'] is False
    assert m['installed'] is False
    assert m['installed_version'] is None


def test_inspect_detects_locked(sword_home):
    z = _make_zip([('Nasbx', _conf('Nasbx', locked=True), [])])
    mods = sword_bridge.inspect_module_zip(z)
    assert mods[0]['locked'] is True


def test_inspect_multi_module(sword_home):
    z = _make_zip([
        ('Aaa', _conf('Aaa'), []),
        ('Bbb', _conf('Bbb'), []),
    ])
    names = {m['name'] for m in sword_bridge.inspect_module_zip(z)}
    assert names == {'Aaa', 'Bbb'}


def test_inspect_marks_installed(sword_home, monkeypatch):
    monkeypatch.setattr(sword_bridge, 'module_names', lambda: ['KJVx'])
    # Lay down an installed conf so installed_version can read it.
    (sword_home / 'mods.d' / 'kjvx.conf').write_text(_conf('KJVx', version='1.0'))
    z = _make_zip([('KJVx', _conf('KJVx', version='2.3'), [])])
    m = sword_bridge.inspect_module_zip(z)[0]
    assert m['installed'] is True
    assert m['installed_version'] == '1.0'


def test_inspect_rejects_non_sword_zip(sword_home):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('readme.txt', 'hello')
    with pytest.raises(ValueError, match='SWORD module'):
        sword_bridge.inspect_module_zip(buf.getvalue())


def test_inspect_rejects_bad_zip(sword_home):
    with pytest.raises(ValueError, match='valid .zip'):
        sword_bridge.inspect_module_zip(b'definitely not a zip')


# ── install_module_from_zip ────────────────────────────────────────────────────

def test_install_extracts_selected_only(sword_home):
    z = _make_zip([
        ('Aaa', _conf('Aaa'), [('modules/texts/ztext/aaa/ot.bzs', b'x' * 10)]),
        ('Bbb', _conf('Bbb'), [('modules/texts/ztext/bbb/ot.bzs', b'y' * 10)]),
    ])
    sword_bridge.install_module_from_zip(z, ['Aaa'])
    assert (sword_home / 'mods.d' / 'aaa.conf').exists()
    assert (sword_home / 'modules/texts/ztext/aaa/ot.bzs').exists()
    assert not (sword_home / 'mods.d' / 'bbb.conf').exists()
    assert not (sword_home / 'modules/texts/ztext/bbb').exists()


def test_install_writes_cipher_key(sword_home):
    z = _make_zip([('Nasbx', _conf('Nasbx', locked=True), [])])
    sword_bridge.install_module_from_zip(z, ['Nasbx'], {'Nasbx': 'SECRET42'})
    conf = (sword_home / 'mods.d' / 'nasbx.conf').read_text()
    assert 'CipherKey=SECRET42' in conf
    # The original empty CipherKey line must not survive alongside it.
    assert conf.count('CipherKey=') == 1


def test_install_blocks_path_traversal(sword_home, tmp_path):
    # The DataPath itself is innocent; the data member under it escapes.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('mods.d/evil.conf', _conf('Evil', datapath='./modules/x/'))
        z.writestr('modules/x/../../../../escape/pwn', b'pwn')
    with pytest.raises(ValueError, match='Unsafe path'):
        sword_bridge.install_module_from_zip(buf.getvalue(), ['Evil'])
    assert not (tmp_path.parent / 'escape').exists()


def test_installed_version_reads_conf(sword_home):
    (sword_home / 'mods.d' / 'foo.conf').write_text(_conf('Foo', version='4.2'))
    assert sword_bridge.installed_version('Foo') == '4.2'
    assert sword_bridge.installed_version('Missing') == ''


# ── is_encrypted_module ────────────────────────────────────────────────────────

def test_is_encrypted_module_true_for_locked(sword_home):
    (sword_home / 'mods.d' / 'nasbx.conf').write_text(_conf('Nasbx', locked=True))
    assert sword_bridge.is_encrypted_module('Nasbx') is True


def test_is_encrypted_module_false_for_plain(sword_home):
    (sword_home / 'mods.d' / 'kjvx.conf').write_text(_conf('KJVx'))
    assert sword_bridge.is_encrypted_module('KJVx') is False


def test_is_encrypted_module_false_when_missing(sword_home):
    assert sword_bridge.is_encrypted_module('Nope') is False


# ── can_remove_module ──────────────────────────────────────────────────────────

def test_can_remove_user_module(sword_home):
    (sword_home / 'mods.d' / 'kjvx.conf').write_text(_conf('KJVx'))
    assert sword_bridge.can_remove_module('KJVx') is True


def test_cannot_remove_absent_module(sword_home):
    # Not in the user's ~/.sword (e.g. a system module or unknown) -> not
    # removable through the in-app control.
    assert sword_bridge.can_remove_module('SystemOnly') is False


# ── remove_module (DataPath containment) ───────────────────────────────────────

def test_remove_module_deletes_its_own_data(sword_home):
    (sword_home / 'mods.d' / 'kjvx.conf').write_text(_conf('KJVx'))
    data = sword_home / 'modules/texts/ztext/kjvx'
    data.mkdir(parents=True)
    (data / 'ot.bzs').write_bytes(b'x')
    sword_bridge.remove_module('KJVx')
    assert not data.exists()
    assert not (sword_home / 'mods.d' / 'kjvx.conf').exists()


def test_remove_module_refuses_datapath_outside_sword(sword_home, tmp_path):
    # An embedded `..` survives lstrip('./'), so this conf used to resolve
    # outside ~/.sword and be rmtree'd.
    victim = tmp_path / 'Documents'
    victim.mkdir()
    (victim / 'thesis.odt').write_bytes(b'years of work')
    (sword_home / 'mods.d' / 'evil.conf').write_text(
        _conf('Evil', datapath='./modules/texts/../../../Documents'))
    with pytest.raises(ValueError, match='DataPath'):
        sword_bridge.remove_module('Evil')
    assert (victim / 'thesis.odt').exists()
    # The refusal must come before anything is deleted.
    assert (sword_home / 'mods.d' / 'evil.conf').exists()


def test_install_refuses_datapath_outside_sword(sword_home, tmp_path):
    z = _make_zip([('Evil', _conf('Evil', datapath='modules/../../../escape'), [])])
    with pytest.raises(ValueError, match='DataPath'):
        sword_bridge.install_module_from_zip(z, ['Evil'])
    assert not (sword_home / 'mods.d' / 'evil.conf').exists()


# ── _fetch_crosswire (HTTPS → FTP fallback) ────────────────────────────────────

@pytest.fixture
def fake_urlopen(monkeypatch):
    """Record fetched URLs and script each one's outcome.

    `outcomes` maps a tier name — 'https', 'ftp' or 'mirror' — to either
    bytes (served) or an exception (raised); `calls` records every URL
    tried, in order. The mirror needs its own key despite also being an
    https:// URL, or it would inherit CrossWire's scripted outcome.

    Reachability is scripted per host under 'reachable:<host>', falling
    back to 'reachable' for both. Per-host matters because CrossWire's two
    daemons share one machine but fail independently.
    """
    import urllib.request

    calls = []
    outcomes = {}

    class _Resp:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _tier(url):
        if url.startswith(sword_bridge._MIRROR_BASE):
            return 'mirror'
        return url.split(':')[0]

    def _fake(url, timeout=None):
        calls.append((url, timeout))
        result = outcomes[_tier(url)]
        if isinstance(result, Exception):
            raise result
        return _Resp(result)

    def _fake_reachable(host, port, timeout=5):
        return outcomes.get(f'reachable:{host}',
                            outcomes.get('reachable', True))

    monkeypatch.setattr(urllib.request, 'urlopen', _fake)
    # The reachability probe opens a real socket; drive it from the script
    # so no test touches the network.
    monkeypatch.setattr(sword_bridge, '_reachable', _fake_reachable)
    return calls, outcomes


def test_fetch_prefers_https(fake_urlopen):
    calls, outcomes = fake_urlopen
    outcomes['https'] = b'over-https'
    assert sword_bridge._fetch_crosswire('raw/mods.d.tar.gz', 60) == b'over-https'
    # FTP is never dialled while the web server answers.
    assert [c[0] for c in calls] == [
        'https://crosswire.org/ftpmirror/pub/sword/raw/mods.d.tar.gz']
    assert calls[0][1] == 60


def test_fetch_falls_back_to_ftp_when_https_unreachable(fake_urlopen):
    import socket
    import urllib.error

    calls, outcomes = fake_urlopen
    outcomes['https'] = urllib.error.URLError(socket.timeout('timed out'))
    outcomes['ftp'] = b'over-ftp'
    assert sword_bridge._fetch_crosswire('packages/rawzip/KJV.zip', 120) == b'over-ftp'
    assert [c[0] for c in calls] == [
        'https://crosswire.org/ftpmirror/pub/sword/packages/rawzip/KJV.zip',
        'ftp://ftp.crosswire.org/pub/sword/packages/rawzip/KJV.zip',
    ]
    assert calls[1][1] == 120


def test_fetch_does_not_retry_ftp_on_http_error(fake_urlopen):
    import urllib.error

    calls, outcomes = fake_urlopen
    # The web server answered — a 404 is a real answer about a real path,
    # so FTP would only repeat it. Surface it instead of dialling twice.
    outcomes['https'] = urllib.error.HTTPError(
        'https://crosswire.org/', 404, 'Not Found', {}, None)
    with pytest.raises(urllib.error.HTTPError):
        sword_bridge._fetch_crosswire('packages/rawzip/Nope.zip', 120)
    assert len(calls) == 1


def test_fetch_skips_https_when_web_server_is_down(fake_urlopen):
    calls, outcomes = fake_urlopen
    # The July 2026 shape: httpd gone, FTP still serving from the same box.
    outcomes['reachable:crosswire.org'] = False
    outcomes['ftp'] = b'over-ftp'
    assert sword_bridge._fetch_crosswire('raw/mods.d.tar.gz', 60) == b'over-ftp'
    # No dead-air wait on a port that is not listening: HTTPS is not dialled.
    assert [c[0] for c in calls] == [
        'ftp://ftp.crosswire.org/pub/sword/raw/mods.d.tar.gz']


def test_fetch_falls_back_to_mirror_when_host_is_gone(fake_urlopen):
    """Neither daemon answers — the whole machine is unreachable."""
    calls, outcomes = fake_urlopen
    outcomes['reachable'] = False
    outcomes['mirror'] = b'from-mirror'
    got = sword_bridge._fetch_crosswire('packages/rawzip/KJV.zip', 120)
    assert got == b'from-mirror'
    # Straight to the mirror: neither dead port is dialled.
    assert [c[0] for c in calls] == [f'{sword_bridge._MIRROR_BASE}/KJV.zip']


def test_mirror_flattens_nested_paths(fake_urlopen):
    """Release assets are a flat namespace, so raw/… must collapse."""
    calls, outcomes = fake_urlopen
    outcomes['reachable'] = False
    outcomes['mirror'] = b'catalogue'
    sword_bridge._fetch_crosswire('raw/mods.d.tar.gz', 60)
    assert [c[0] for c in calls] == [
        f'{sword_bridge._MIRROR_BASE}/mods.d.tar.gz']


def test_fetch_tries_mirror_when_ftp_answers_then_fails(fake_urlopen):
    """A listening FTP port that then errors must not strand the caller."""
    import urllib.error

    calls, outcomes = fake_urlopen
    outcomes['reachable:crosswire.org'] = False
    outcomes['ftp'] = urllib.error.URLError('connection reset')
    outcomes['mirror'] = b'from-mirror'
    got = sword_bridge._fetch_crosswire('packages/rawzip/KJV.zip', 120)
    assert got == b'from-mirror'
    assert [c[0] for c in calls] == [
        'ftp://ftp.crosswire.org/pub/sword/packages/rawzip/KJV.zip',
        f'{sword_bridge._MIRROR_BASE}/KJV.zip',
    ]


def test_module_absent_from_mirror_explains_the_licence_reason(fake_urlopen):
    """CrossWire-only licensed modules are absent by design, not by error."""
    import urllib.error

    calls, outcomes = fake_urlopen
    outcomes['reachable'] = False
    outcomes['mirror'] = urllib.error.HTTPError(
        sword_bridge._MIRROR_BASE, 404, 'Not Found', {}, None)
    with pytest.raises(RuntimeError, match='not in the backup mirror'):
        sword_bridge._fetch_crosswire('packages/rawzip/NASB.zip', 120)
