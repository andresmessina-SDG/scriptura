"""Guards for the Scripture in Stone gallery.

The gallery is curated in TOML, which xgettext cannot read, so every word of
it — 342 strings, four fifths of them the captions that carry the argument —
reached the reader in English whatever language the app was running in. A
Russian reader opened «Писание в камне» on a page headed "Scripture in
Stone". `tools/gen_archaeology_strings.py` mirrors the strings where the
extractor can see them; these check the two halves stay agreed, and that the
three fields deliberately left in the original stay that way.
"""

import importlib.util
import os

import pytest

import archaeology_bridge as ab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _generator():
    spec = importlib.util.spec_from_file_location(
        'gen_archaeology_strings',
        os.path.join(ROOT, 'tools', 'gen_archaeology_strings.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def loud(monkeypatch):
    """Rebuild the document with a translator that shouts.

    Every string that goes through `_()` comes back upper-cased, so the test
    can see which fields the bridge translates and which it hands through —
    without a compiled catalogue, which a source checkout does not have.
    """
    monkeypatch.setattr(ab, '_', str.upper)
    monkeypatch.setattr(ab, '_doc', None)
    monkeypatch.setattr(ab, '_doc_lang', None)
    return ab.document()


def test_the_mirror_matches_the_toml():
    """A curator who adds an artifact and forgets to regenerate gets a red
    test here rather than an untranslatable caption six months later."""
    gen = _generator()
    with open(os.path.join(ROOT, 'archaeology_strings.py'),
              encoding='utf-8') as f:
        assert f.read() == gen.render(gen.collect()), \
            'archaeology_strings.py is stale — run tools/gen_archaeology_strings.py'


def test_every_curated_field_is_translated(loud):
    """Titles, captions, dates, places, holdings, provenance, the chapter
    introductions and the glossary — the whole page a reader looks at."""
    doc = loud
    assert doc['title'].isupper() and doc['subtitle'].isupper()
    assert doc['body'].isupper()
    chapter = doc['chapters'][0]
    assert chapter['title'].isupper() and chapter['intro'].isupper()
    entry = chapter['entries'][0]
    for field in ('title', 'place', 'date', 'holding', 'provenance',
                  'caption'):
        assert entry[field].isupper(), field
    term = doc['terms'][0]
    assert term['term'].isupper() and term['definition'].isupper()
    assert doc['reading'][0]['note'].isupper()


def test_the_attribution_and_the_bibliography_are_left_as_printed(loud):
    """Two fields deliberately not marked. A photograph's licence asks us to
    carry its credit as given, and "Amihai Mazar, Archaeology of the Land of
    the Bible" is what a reader would type into a library catalogue —
    translating it would hide the book."""
    entry = loud['chapters'][0]['entries'][0]
    assert not entry['credit'].isupper()
    assert 'CC BY-SA' in entry['credit']
    assert not loud['reading'][0]['title'].isupper()


def test_an_empty_field_stays_empty():
    """`_('')` returns the catalogue's own PO header — the whole metadata
    block — so an optional field left blank would print it onto the page."""
    assert ab._t('') == ''
    assert ab._t('   ') == '   '


def test_the_verse_chip_is_localized_but_its_key_is_not(monkeypatch):
    """The chip's label is what the reader sees and the book is what drives
    the Bible pane, so only one of them may be translated. Written out in
    full, the chips read "Joshua 10:1" under a Russian UI."""
    monkeypatch.setattr(ab.i18n, 'book_label', lambda name: '<%s>' % name)
    monkeypatch.setattr(ab, '_doc', None)
    monkeypatch.setattr(ab, '_doc_lang', None)
    refs = [r for c in ab.document()['chapters']
            for e in c['entries'] for r in e['refs']]
    assert refs
    for ref in refs:
        assert ref['label'].startswith('<%s>' % ref['book'])
        assert not ref['book'].startswith('<')


def test_the_document_is_rebuilt_when_the_language_changes(monkeypatch):
    """The parse is cached, and every string in it has already been through
    `_()`. The header language picker rebuilds the window inside one run, so
    a document cached under the old language would outlive it."""
    monkeypatch.setattr(ab, '_doc', None)
    monkeypatch.setattr(ab, '_doc_lang', None)
    monkeypatch.setattr(ab.i18n, 'current_language', lambda: 'en')
    monkeypatch.setattr(ab, '_', str.upper)
    first = ab.document()['title']
    monkeypatch.setattr(ab.i18n, 'current_language', lambda: 'ru')
    monkeypatch.setattr(ab, '_', str.lower)
    assert ab.document()['title'] == first.lower()


def test_a_map_label_stays_on_the_plate():
    """The find-spot map anchors its orientation labels geographically, and
    the words are not geographic: «Персидский залив» is half again the width
    of "Persian Gulf" and hung off the right edge of the plate. Drawn onto a
    surface and read back as pixels, because what is wrong here is ink
    outside the map, not a number in the layout.
    """
    cairo = pytest.importorskip('cairo')
    import archaeology_reader as ar

    W, H = 220, 40
    right = W - 6
    for bounds in (None, (6, right)):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        cr = cairo.Context(surface)
        ar.ArchaeologyReader._stroked_text(
            cr, W - 10, 24, 'Персидский залив', 13, align='center',
            bounds=bounds)
        surface.flush()
        data = surface.get_data()
        stride = surface.get_stride()
        inked = [x for y in range(H) for x in range(W)
                 if data[y * stride + x * 4 + 3]]
        assert inked, 'nothing was drawn'
        if bounds is None:
            # The guard is worth having only if the unclamped call really does
            # run off the edge.
            assert max(inked) >= right
        else:
            assert max(inked) < right, 'a label ran past the edge of the map'
            assert min(inked) >= 0


def test_the_timeline_reads_a_date_the_translation_cannot_move():
    """The chronological axis places an artifact by finding an era token in
    its date, and the date a reader sees is prose in their own language:
    «XIV век до н. э.» carries no 'BC' and "siglo XIV a. C." carries none
    either, so a translated gallery would have drawn an empty timeline. The
    parse reads the curated English, which is kept beside the display string
    the way a verse chip keeps its book key.
    """
    import archaeology_reader as ar

    entries = [e for c in ab.document()['chapters'] for e in c['entries']]
    assert entries
    placed = [e for e in entries if ar.ArchaeologyReader._parse_year(
        e['date_key']) is not None]
    # Not every date can be placed — "Roman era" names no year — but most can,
    # and the axis is worthless if that number goes to nothing.
    assert len(placed) > len(entries) * 0.8, (
        f'only {len(placed)} of {len(entries)} artifacts reach the timeline')


def test_the_displayed_date_is_translated_and_its_key_is_not(loud):
    """Two fields, one curated string: the reader gets the translation and
    the timeline gets the token it can parse."""
    entry = loud['chapters'][0]['entries'][0]
    assert entry['date'].isupper()
    assert not entry['date_key'].isupper()
