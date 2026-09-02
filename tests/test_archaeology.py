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
import tomllib

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
    assert entry['credit'].endswith('Osama S. M. Amin \u00b7 CC BY-SA 4.0')
    assert not loud['reading'][0]['title'].isupper()


def test_only_the_word_that_introduces_a_credit_is_translated(loud):
    """`photo` is ours, not the photographer's, and it was the last English
    word on 47 of the 56 translated cards. The name and licence beside it are
    what the attribution actually is, and stay exactly as printed."""
    with open(ab._DOC_FILE, 'rb') as fh:
        raw = tomllib.load(fh)
    shown = {e['title']: e['credit'] for c in loud['chapters']
             for e in c['entries']}
    prefixed = 0
    for entry in raw['entry']:
        printed = entry['credit']
        rendered = shown[entry['title'].upper()]
        if printed.startswith('photo '):
            prefixed += 1
            assert rendered == 'PHOTO ' + printed[len('photo '):]
        else:
            assert rendered == printed
    assert prefixed == 47


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


def test_the_three_bands_a_photograph_can_be_in():
    """Load, hold, drop — and a gap between the last two.

    Without the gap a plate resting on the edge is decoded, dropped and
    decoded again as the reader nudges the scrollbar, which is worse than
    either answer on its own.
    """
    import archaeology_reader as ar
    page, top = 1000.0, 5000.0
    # In view.
    assert ar._band(5200, 5620, top, page) == (True, False)
    # Just past the load margin: not worth decoding, not yet worth dropping.
    assert ar._band(7100, 7520, top, page) == (False, False)
    # Far below, and far above.
    assert ar._band(9500, 9920, top, page) == (False, True)
    assert ar._band(100, 520, top, page) == (False, True)


def test_render_decodes_no_photographs():
    """56 plates are built up front — a Box does not virtualise — and each
    `set_filename` decodes its file there and then: 383ms and 126MB to open a
    pane showing two of them. Rendering must leave every one of them empty
    and let the viewport ask for what it needs."""
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    import archaeology_reader as ar
    reader = ar.ArchaeologyReader()
    reader.render()
    assert len(reader._lazy) == 56
    assert not [pic for _plate, pic, _path in reader._lazy
                if pic.get_paintable() is not None]
    # The paths are still there to load from, and they exist on disk.
    assert all(os.path.exists(path) for _plate, _pic, path in reader._lazy)
