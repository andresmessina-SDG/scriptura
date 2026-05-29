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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('mods.d/evil.conf', _conf('Evil', datapath='../../../../escape/'))
        z.writestr('../../../../escape/x', b'pwn')
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
