"""The website in docs/: in step with the app, and within its promises.

The pages are built by tools/build-site.py from site/ and from the app
itself (the version, the welcome screen's libraries). These tests fail when
someone edits docs/ by hand, changes site/ without rebuilding, or lets the
page break one of the promises it makes: nothing loaded from another site,
open Bible texts only, and the three languages saying the same things."""

import importlib.util
import os
import re
import shutil
import tomllib

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), '..')
_SPEC = importlib.util.spec_from_file_location(
    'build_site', os.path.join(_ROOT, 'tools', 'build-site.py'))
assert _SPEC is not None and _SPEC.loader is not None
build_site = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_site)

DOCS = os.path.join(_ROOT, 'docs')


def _page(lang, sub=''):
    path = os.path.join(DOCS, '' if lang == 'en' else lang, sub, 'index.html')
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _served_text():
    """Every text file the site serves, as (path, contents)."""
    for base, _dirs, files in os.walk(DOCS):
        for name in files:
            if name.endswith(('.html', '.css', '.js')):
                path = os.path.join(base, name)
                with open(path, encoding='utf-8') as fh:
                    yield path, fh.read()


def _strings(lang):
    with open(os.path.join(_ROOT, 'site', 'strings', f'{lang}.toml'), 'rb') as fh:
        return tomllib.load(fh)


@pytest.mark.parametrize('lang', build_site.LANGS)
@pytest.mark.parametrize('page', list(build_site.PAGES))
def test_page_is_built_from_site(lang, page):
    if shutil.which('msgfmt') is None:
        pytest.skip('msgfmt not installed')
    path = os.path.join(DOCS, build_site._prefix(lang), build_site.PAGES[page][1],
                        'index.html')
    with open(path, encoding='utf-8') as fh:
        assert fh.read() == build_site.render(lang, page), (
            'docs/ is out of step: run python3 tools/build-site.py')


def test_404_is_built_from_site():
    with open(os.path.join(DOCS, '404.html'), encoding='utf-8') as fh:
        assert fh.read() == build_site.render_404()


def test_whats_new_has_every_release():
    import xml.etree.ElementTree as ET
    import glob
    meta = glob.glob(os.path.join(_ROOT, 'data', '*.metainfo.xml.in'))[0]
    versions = [r.get('version') for r in ET.parse(meta).getroot().iter('release')]
    for lang in build_site.LANGS:
        page = _page(lang, 'whats-new/')
        for v in versions:
            assert f'id="v{v.replace(".", "-")}"' in page, (lang, v)
    from _version import __version__
    assert versions[0] == __version__


@pytest.mark.parametrize('name', ['site.css', 'site.js'])
def test_assets_are_built_from_site(name):
    with open(os.path.join(_ROOT, 'site', name), encoding='utf-8') as a, \
            open(os.path.join(DOCS, 'assets', name), encoding='utf-8') as b:
        assert a.read() == b.read()


def test_version_is_the_apps():
    from _version import __version__
    for lang in build_site.LANGS:
        assert __version__ in _page(lang)


def test_nothing_loads_from_another_site():
    """Links may leave; nothing may be fetched from elsewhere."""
    loads = re.compile(
        r'<(?:script|img|iframe|source|video|audio)\b[^>]*\bsrc="([^"]*)"'
        r'|<link\b[^>]*rel="(?:stylesheet|icon|apple-touch-icon|preload)"[^>]*href="([^"]*)"'
        r'|url\(\s*[\'"]?([^\'")]+)'
        r'|@import\s+[\'"]([^\'"]+)'
        r'|fetch\(\s*[\'"`]([^\'"`]+)')
    for path, text in _served_text():
        for m in loads.finditer(text):
            target = next(g for g in m.groups() if g is not None)
            assert not re.match(r'(?:[a-z]+:)?//', target, re.I), (path, target)


def test_only_open_bibles():
    """Licensed translations stay off the site, in the text and the pane."""
    # The release notes on What's new name the Bibles the app offers, which is
    # not showing their text; every page that sets Scripture is checked.
    for path, text in _served_text():
        if os.sep + 'whats-new' + os.sep in path:
            continue
        assert not re.search(r'\b(ESV|NIV|NASB|NBLA|LBLA|NLT|CSB)\b', text), path
    assert {spec['left'][1] for spec in build_site.TEXTS.values()} | {
        spec['right'][1] for spec in build_site.TEXTS.values()} == {
        'KJVA', 'BSB', 'SpaRV1909', 'spabes', 'RusOpenBible', 'russyn'}


def test_languages_say_the_same_things():
    en = _strings('en')
    for lang in ('es', 'ru'):
        other = _strings(lang)
        assert set(other) == set(en), lang
        assert set(other['js']) == set(en['js']), lang
        assert set(other['papers']) == set(en['papers']), lang
        for key in ('shots', 'claims', 'credits_html', 'rows', 'teach_rows'):
            assert other[key], (lang, key)
        assert [s['img'] for s in other['shots']] == [s['img'] for s in en['shots']]


def test_every_screenshot_exists_in_light_and_dark():
    """The page shows the dark shot on a dark paper, so both must be there."""
    for lang in build_site.LANGS:
        s = _strings(lang)
        for shot in s['shots'] + [s['teach_shot']]:
            for name in (shot['img'], shot['img'] + '-dark'):
                assert os.path.exists(os.path.join(
                    DOCS, 'assets', 'img', lang, name + '.webp')), (lang, name)
        assert os.path.exists(os.path.join(DOCS, 'assets', 'img', lang, 'reading.jpg'))


def test_every_verse_has_cross_references_and_voices():
    for lang in build_site.LANGS:
        with open(os.path.join(_ROOT, 'site', 'data', f'{lang}.json'),
                  encoding='utf-8') as fh:
            data = build_site.json.load(fh)
        assert len(data['xrefs']) == len(data['voices']) == len(data['left'])
        # OpenBible links nothing from John 1:2, and the pane says so.
        assert sum(1 for refs in data['xrefs'] if refs) >= 4, lang
        for refs, voices in zip(data['xrefs'], data['voices']):
            assert all(r['r'] and r['t'] for r in refs), lang
            assert voices and all(v['a'] and v['t'] for v in voices), lang


def test_every_clickable_word_opens_an_entry():
    for lang in build_site.LANGS:
        page = _page(lang)
        data = build_site.json.loads(
            re.search(r'id="site-data">(.*?)</script>', page, re.S).group(1)
            .replace('<\\/', '</'))['text']
        keys = {k for verse in data['left'] for _t, k in verse if k}
        assert keys, lang
        assert keys <= set(data['entries']), lang
