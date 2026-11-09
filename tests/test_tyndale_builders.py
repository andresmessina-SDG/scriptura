"""The Tyndale dictionary and study-notes builders: the reading of the
release's verse links, headwords and markup."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import build_tyndale_dict as d  # noqa: E402
import build_tyndale_notes as n  # noqa: E402


def test_link_shapes_become_osis():
    assert d.osis_refs('1Sam.25.2-42') == ['1Sam.25.2-1Sam.25.42']
    assert d.osis_refs('Gen.1.1-2.3') == ['Gen.1.1-Gen.2.3']
    assert d.osis_refs('Deut.16.1-8,16-17') == [
        'Deut.16.1-Deut.16.8', 'Deut.16.16-Deut.16.17']
    assert d.osis_refs('Ps.23.1,4') == ['Ps.23.1', 'Ps.23.4']
    assert d.osis_refs('Exod.2.1b-9') == ['Exod.2.1-Exod.2.9']
    assert d.osis_refs('1Kgs.22.51--2Kgs.1.18') == ['1Kgs.22.51-2Kgs.1.18']
    assert d.osis_refs('Ps.23') == ['Ps.23']
    assert d.osis_refs('') == []


def test_the_release_book_codes_are_mended():
    assert d.osis_refs('Pr.3.5') == ['Prov.3.5']
    assert d.osis_refs('1Jn.4.8') == ['1John.4.8']
    assert d.osis_refs('Tb.1.1') == ['Tob.1.1']
    assert d.osis_refs('4Macc.13.17') == ['4Macc.13.17']


def test_a_verse_no_bible_has_is_not_linked():
    assert d._exists('Ps.23.1')
    assert not d._exists('Ps.17.98')
    assert not d._exists('Eccl.13.1')
    assert d._exists('Tob.1.1')            # outside the 66: left alone


def test_headwords():
    assert d._key('Abel (Person)') == 'ABEL'
    assert d._key('Aaron’s Rod*') == 'AARON’S ROD'


def test_same_named_articles_join_under_one_key():
    arts = [('AbelPerson', 'Abel (Person)', '<p class="fl">The second son.</p>'),
            ('AbelPlace', 'Abel (Place)', '<p class="fl">A town.</p>')]
    entries, report = d.build_entries(arts, {})
    assert list(entries) == ['ABEL']
    assert entries['ABEL'].startswith('<h3>Person</h3>')
    assert '<h3>Place</h3>' in entries['ABEL']
    assert not report['short'] and not report['empty']


def test_a_joined_entry_survives_the_peeks_headword_strip():
    # The peek titles the entry "Abel" and strips "Abel" from its front.
    from pane_peek import _strip_leading_headword
    arts = [('AbelPerson', 'Abel (Person)', '<p class="fl">The second son.</p>'),
            ('AbelPlace', 'Abel (Place)', '<p class="fl">A town.</p>')]
    entries, _ = d.build_entries(arts, {})
    assert _strip_leading_headword(entries['ABEL'], 'Abel').startswith(
        '<h3>Person</h3>')


def test_a_main_article_goes_first_unheaded():
    arts = [('SinPlace', 'Sin* (Place)', '<p class="fl">A city.</p>'),
            ('Sin', 'Sin', '<p class="fl">Disobedience to God.</p>')]
    entries, _ = d.build_entries(arts, {})
    assert entries['SIN'].startswith('<p>Disobedience')
    assert '<h3>Place</h3><p>A city.</p>' in entries['SIN']


def test_bare_paragraphs_and_headings_with_ids_are_kept():
    body = ('<p class="h1">ADAM</p><p>Body text.</p>'
            '<p class="h2" id="X">The Significance</p><p>More.</p>')
    out = d.render(body, {}, [], [])
    assert 'Body text.' in out and 'More.' in out
    assert '<h3>The Significance</h3>' in out
    assert 'ADAM' not in out


def test_links_with_attributes_and_small_capitals():
    bad = []
    text = d._inline('the <span class="divine-name">Lord</span> '
                     '(<a class="apocrypha" href="?bref=Jdt.2.24">2:24</a>) '
                     'in the <span class="sc">nlt</span>', bad)
    assert 'LORD' in text and 'NLT' in text
    assert '<reference osisRef="Bible:Jdt.2.24">2:24</reference>' in text


def test_a_note_leads_with_its_verse_and_words():
    bad = []
    text = n._inline('<span class="sn-ref"><a href="?bref=Isa.53.5">53:5</a></span> '
                     '<span class="sn-excerpt">he was pierced</span>: See also '
                     '<a href="?bref=Zech.12.10">Zech 12:10</a>.', bad)
    assert text.startswith('<hi type="bold"><reference osisRef="Bible:Isa.53.5">')
    assert '<hi type="bold">he was pierced</hi>' in text
    assert '<reference osisRef="Bible:Zech.12.10">' in text


def test_a_chapter_link_opens_its_first_verse():
    text = n._inline('<a href="?bref=Ps.23">Ps 23</a>', [])
    assert 'osisRef="Bible:Ps.23.1"' in text


def test_a_note_on_a_verse_the_kjv_lacks_moves_back():
    # The NLT's 3 John 15 is the end of the KJV's verse 14.
    assert n._place('3Jn.1.15') == ('3 John', 1, 14)
    assert n._place('Gen.1.1-2.3') == ('Genesis', 1, 1)
    assert n._place('Pr.1.1-31.31') == ('Proverbs', 1, 1)


def test_the_divine_name_stays_in_the_bold_of_the_quoted_words():
    text = n._inline('<span class="sn-excerpt-divine-name">Lord</span>'
                     '<span class="sn-excerpt"> God</span> (Hebrew)', [])
    assert text.startswith('<hi type="bold">LORD</hi><hi type="bold"> God</hi>')
