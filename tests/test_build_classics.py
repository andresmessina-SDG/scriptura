"""The classics converter: what it links, and what it leaves alone.

The press sets every reference in one modern style, so the finder works on
that style; these cases are shapes measured in its signed EPUBs. Whether a
verse exists is SWORD's question, answered here by a stand-in canon.
"""
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import build_classics as bc  # noqa: E402

from genbook_reader import _BIBLE_REF  # noqa: E402
from pane import _html_to_markup  # noqa: E402


@pytest.fixture(autouse=True)
def canon(monkeypatch):
    """150 chapters of 40 verses each, except Jude's one chapter of 25."""
    def exists(book, chapter, verse):
        if book == 'Jude':
            return chapter == 1 and 1 <= verse <= 25
        return 1 <= chapter <= 150 and 1 <= verse <= 40
    monkeypatch.setattr(bc, 'verse_exists', exists)


def _links(text):
    refs = bc.Refs()
    out = refs.link(text)
    import re
    return re.findall(r'<reference osisRef="Bible:([^"]+)">([^<]*)</reference>', out)


def test_a_reference_links_to_its_first_verse():
    assert _links('the apostle, Rom 8:13, “If ye') == [('Rom.8.13', 'Rom 8:13')]


def test_a_numbered_book_and_a_range():
    assert _links('see 1 Cor 9:27 and Isa 57:16–18.') == [
        ('1Cor.9.27', '1 Cor 9:27'), ('Isa.57.16-Isa.57.18', 'Isa 57:16–18')]


def test_a_verse_list_stays_one_link():
    assert _links('Isa 57:17, 18. (2.) We') == [('Isa.57.17', 'Isa 57:17, 18')]


def test_a_comma_before_another_book_ends_the_list():
    assert _links('Gen 3:15, 1 Cor 10:4') == [
        ('Gen.3.15', 'Gen 3:15'), ('1Cor.10.4', '1 Cor 10:4')]


def test_a_chapter_after_a_semicolon_is_the_same_book():
    assert _links('Ezek 11:19; 36:26, “I will') == [
        ('Ezek.11.19', 'Ezek 11:19'), ('Ezek.36.26', '36:26')]


def test_a_colon_after_the_verse_is_punctuation():
    assert _links('Rom 8:13: “The body') == [('Rom.8.13', 'Rom 8:13')]


def test_a_bare_chapter_links_after_an_abbreviation_only():
    assert _links('Heman’s condition, Ps 88; his life') == [('Ps.88.1', 'Ps 88')]
    assert _links('as John 3 times said') == []


def test_a_one_chapter_book_takes_its_number_as_the_verse():
    assert _links('ungodly men, Jude 4, turning') == [('Jude.1.4', 'Jude 4')]


def test_the_old_style_in_a_note():
    assert _links('Isa. liii. 12') == [('Isa.53.12', 'Isa. liii. 12')]


def test_verse_n_reads_the_last_book_in_the_paragraph():
    refs = bc.Refs()
    refs.link('Col 3:5, “Mortify.” Such as were “risen,” ')
    out = refs.link('verse 1; such as were dead')
    assert 'osisRef="Bible:Col.3.1">verse 1<' in out


def test_verse_n_with_no_book_before_it_stays_text():
    assert _links('the second verse 4 of the poem') == []


def test_a_new_paragraph_forgets_the_book():
    refs = bc.Refs()
    refs.link('Col 3:5')
    refs.reset()
    assert '<reference' not in refs.link('verse 1')


def test_a_verse_no_bible_has_is_refused_and_left_as_text():
    refs = bc.Refs()
    out = refs.link('Ps 17:98')
    assert '<reference' not in out
    assert refs.refused == ['Ps 17:98']


def test_text_is_escaped_around_a_link():
    out = bc.Refs().link('a < b & Rom 8:13')
    assert out.startswith('a &lt; b &amp; <reference')


# ── Emphasis around links ───────────────────────────────────────────────────

def test_emphasis_closes_around_a_link_and_an_inner_run():
    body = ('The <hi type="small-caps">second</hi> rule, '
            '<reference osisRef="Bible:Rom.8.13">Rom 8:13</reference> — end')
    assert bc._wrap('italic', body) == (
        '<hi type="italic">The </hi><hi type="small-caps">second</hi>'
        '<hi type="italic"> rule, </hi>'
        '<reference osisRef="Bible:Rom.8.13">Rom 8:13</reference>'
        '<hi type="italic"> — end</hi>')


# ── A whole EPUB ────────────────────────────────────────────────────────────

_NAV = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
        '<nav epub:type="toc"><ol>'
        '<li><a href="part.xhtml">Part I</a><ol>'
        '<li><a href="ch1.xhtml">Chapter I</a></li>'
        '<li><a href="ch1.xhtml#later">A heading inside it</a></li>'
        '</ol></li></ol></nav></body></html>')
_CH1 = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><body><section>'
        '<h3>Chapter I</h3>'
        '<p><span class="smallcaps">Having</span> laid this, Rom 8:13'
        '<a class="noteref" href="#fn-1" epub:type="noteref"><sup>1</sup></a>'
        ' and <em>so</em> on.</p>'
        '<ol><li>First</li><li>Second</li></ol>'
        '<section class="notes"><aside id="fn-1" epub:type="footnote">'
        '<p><a href="#nr-1" role="doc-backlink">1.</a> Owen’s note.</p>'
        '</aside></section></section></body></html>')
_PART = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
         '<body><section><h2>Part I</h2></section></body></html>')
_OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
        '<dc:title>A Test Book</dc:title><dc:creator>John Owen</dc:creator>'
        '</metadata><manifest><item id="nav" href="nav.xhtml" properties="nav"/>'
        '</manifest></package>')
_CONTAINER = ('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:'
              'opendocument:xmlns:container"><rootfiles><rootfile '
              'full-path="OEBPS/content.opf"/></rootfiles></container>')


@pytest.fixture
def epub(tmp_path):
    path = tmp_path / 'book.epub'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('META-INF/container.xml', _CONTAINER)
        z.writestr('OEBPS/content.opf', _OPF)
        z.writestr('OEBPS/nav.xhtml', _NAV)
        z.writestr('OEBPS/part.xhtml', _PART)
        z.writestr('OEBPS/ch1.xhtml', _CH1)
    return str(path)


def test_the_tree_is_the_epubs_contents(epub):
    entries, book = bc.convert([epub], bc.Refs())
    assert [k for k, _ in entries] == ['/Part I', '/Part I/Chapter I']
    assert book.title == 'A Test Book'


def test_an_entry_carries_its_text_links_notes_and_list(epub):
    entries, _ = bc.convert([epub], bc.Refs())
    body = dict(entries)['/Part I/Chapter I']
    assert '<hi type="small-caps">Having</hi>' in body
    assert '<reference osisRef="Bible:Rom.8.13">Rom 8:13</reference>' in body
    assert '<hi type="super" n="note">1</hi>' in body
    assert '<p>1. First</p><p>2. Second</p>' in body
    assert body.endswith('<title>Notes</title><p><hi type="super">1</hi> '
                         'Owen’s note.</p></div>')
    assert 'Chapter I' not in body.split('<p>')[0]   # the title is the key


def test_the_module_reads_as_the_epub(epub):
    entries, _ = bc.convert([epub], bc.Refs())
    assert bc.check([epub], entries) == []


def test_a_word_lost_on_the_way_is_caught(epub):
    entries, _ = bc.convert([epub], bc.Refs())
    entries = [(k, b.replace(' and ', ' ')) for k, b in entries]
    assert bc.check([epub], entries)


def test_volumes_become_parts_of_one_module(epub):
    entries, _ = bc.convert([epub, epub], bc.Refs())
    keys = [k for k, _ in entries]
    assert keys[0] == '/Volume 1' and '/Volume 2/Part I/Chapter I' in keys


# ── The reader ──────────────────────────────────────────────────────────────

def test_the_reader_links_bible_references_only():
    html = ('<reference osisRef="Bible:Rom.8.13">Rom 8:13</reference> '
            '<reference osisRef="Title_Page">Title Page</reference>')
    assert [m.group(1) for m in _BIBLE_REF.finditer(html)] == ['Bible:Rom.8.13']


def test_small_caps_render_as_small_caps():
    markup = _html_to_markup('<hi type="small-caps">Having</hi> laid', False)
    assert '<span variant="small-caps">Having</span>' in markup


# ── The Module Manager ──────────────────────────────────────────────────────

def test_a_classic_is_known_by_its_conf():
    import sword_bridge
    info = sword_bridge._parse_conf_lines(
        ['[CWPPilgrim]', 'Description=The Pilgrim’s Progress (John Bunyan)',
         'ModDrv=RawGenBook', 'Collection=Classics'])
    assert info['collection'] == 'Classics'
    import module_manager
    assert module_manager._is_classic({'collection': 'Classics'})
    assert not module_manager._is_classic({'name': 'Didache'})


def test_every_classic_has_a_name_in_the_picker():
    import sword_bridge
    for module in bc.CLASSICS.values():
        assert sword_bridge.display_name(module) != module
