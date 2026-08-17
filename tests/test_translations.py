"""Guards for the shipped translation catalogues.

A translation is data that runs: `_('({step}/{total}) Downloading {label}…')`
is handed to .format(), so a catalogue that drops or renames a placeholder
raises KeyError in front of the user, in that language only, on a path the
English tests all pass. These checks read every catalogue in LINGUAS, so a
future language is covered the moment it is added.
"""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_DIR = os.path.join(ROOT, 'po')

BRACE = re.compile(r'\{[^}{]*\}')
PRINTF = re.compile(r'%[sdifgr%]')


def languages():
    """Codes listed in LINGUAS — the same list meson builds."""
    path = os.path.join(PO_DIR, 'LINGUAS')
    with open(path, encoding='utf-8') as f:
        return [ln.strip() for ln in f
                if ln.strip() and not ln.startswith('#')]


def _parse_po(path):
    """[(msgid, msgid_plural, [msgstr…])] — enough to check placeholders."""
    entries, cur = [], None

    def flush():
        if cur and cur['id']:
            entries.append((cur['id'], cur['plural'], cur['strs']))

    key = None
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if not line.strip():
            continue
        if line.startswith('#'):
            continue
        if line.startswith('msgid_plural '):
            key = 'plural'
            cur['plural'] = line[13:].strip()[1:-1]
        elif line.startswith('msgid '):
            flush()
            cur = {'id': line[6:].strip()[1:-1], 'plural': None, 'strs': []}
            key = 'id'
        elif line.startswith('msgstr'):
            cur['strs'].append(line.split(' ', 1)[1].strip()[1:-1])
            key = 'str'
        elif line.startswith('"'):
            chunk = line.strip()[1:-1]
            if key == 'id':
                cur['id'] += chunk
            elif key == 'plural':
                cur['plural'] += chunk
            elif key == 'str':
                cur['strs'][-1] += chunk
    flush()
    return entries


@pytest.fixture(params=languages())
def catalogue(request):
    lang = request.param
    path = os.path.join(PO_DIR, f'{lang}.po')
    assert os.path.exists(path), f'LINGUAS lists {lang} but {path} is missing'
    return lang, path


def test_every_language_in_linguas_has_a_catalogue(catalogue):
    """meson reads LINGUAS, so a code listed without its .po fails the build
    rather than this test — which is exactly why it is cheap to check here."""
    _lang, path = catalogue
    assert os.path.getsize(path) > 0


def test_placeholders_survive_translation(catalogue):
    """The failure this file exists for: a translated string is formatted, so
    a lost or invented placeholder is a KeyError in that language only."""
    lang, path = catalogue
    bad = []
    for msgid, plural, strs in _parse_po(path):
        sources = [msgid] + ([plural] if plural else [])
        for i, translated in enumerate(strs):
            if not translated:
                continue                      # untranslated falls back to English
            source = sources[min(i, len(sources) - 1)]
            for pattern in (BRACE, PRINTF):
                if sorted(pattern.findall(source)) != \
                        sorted(pattern.findall(translated)):
                    bad.append((source, translated))
    assert not bad, (
        f'{lang}: {len(bad)} placeholder mismatches, first: {bad[:3]}')


def test_the_catalogue_compiles(catalogue):
    """msgfmt --check is what the build runs; failing here names the language
    instead of failing an install with a wall of gettext output."""
    lang, path = catalogue
    msgfmt = shutil.which('msgfmt')
    if msgfmt is None:
        pytest.skip('msgfmt not installed')
    r = subprocess.run([msgfmt, '--check', '-o', os.devnull, path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'{lang}: {r.stderr}'


def test_no_string_is_left_behind_by_the_source(catalogue, tmp_path):
    """Re-extract from source and check nothing falls through to English.

    This is the only check that compares a catalogue against the authority
    rather than against itself. It caught three strings whose msgid carried
    an escape (`\\n`, `\\"`): the catalogue held a literal backslash-n where
    the source has a newline, so the ids never matched and those strings
    silently rendered in English — while msgfmt, and every check written
    around the catalogue's own idea of its ids, passed happily.

    It fires on drift too: change an English string without updating the
    translations and this names the language that fell behind.
    """
    lang, path = catalogue
    for tool in ('xgettext', 'msgmerge', 'msgattrib'):
        if shutil.which(tool) is None:
            pytest.skip(f'{tool} not installed')

    pot = tmp_path / 'scriptura.pot'
    r = subprocess.run(
        ['xgettext', '--files-from=po/POTFILES.in', '--from-code=UTF-8',
         '--keyword=_', '--keyword=N_', '-o', str(pot)],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    merged = tmp_path / 'merged.po'
    subprocess.run(['msgmerge', '--quiet', '--no-fuzzy-matching',
                    '-o', str(merged), path, str(pot)], check=True)
    left = subprocess.run(['msgattrib', '--untranslated', str(merged)],
                          capture_output=True, text=True, check=True).stdout

    stranded = [ln for ln in left.splitlines()
                if ln.startswith('#:')]
    assert not stranded, (
        f'{lang}: {len(stranded)} strings the source has but the catalogue '
        f'does not translate — {stranded[:5]}')


def test_every_book_name_is_translated(catalogue):
    """Book names are the one string set a reader meets on every screen, and
    they are dual-role — English stays the key, this is only the display
    path — so a half-translated set reads as a bug rather than a gap."""
    import window

    lang, path = catalogue
    have = {msgid: strs[0] for msgid, _p, strs in _parse_po(path) if strs}
    missing = [b for b in window.BOOKS if not have.get(b)]
    assert not missing, f'{lang}: untranslated books {missing}'


def test_book_names_stay_distinct(catalogue):
    """Two books translating to one name would make the picker ambiguous and
    silently send a reader to the wrong place."""
    import window

    lang, path = catalogue
    have = {msgid: strs[0] for msgid, _p, strs in _parse_po(path) if strs}
    names = [have[b] for b in window.BOOKS if have.get(b)]
    assert len(set(names)) == len(names), f'{lang}: duplicate book names'
