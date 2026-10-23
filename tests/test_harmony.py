"""The harmony's data and lookups, without GTK.

The data is built and checked by tools/harmony/build_harmony.py; these tests
hold the shipped file to the shape the page reads, and check the lookups it
makes.
"""
import content
import harmony
import sword_bridge


def test_the_module_is_listed_and_named():
    assert harmony.MODULE_KEY in harmony.module_names()
    assert harmony.MODULE_KEY in content.readable_module_names()
    assert content.type_key(harmony.MODULE_KEY) == 'harmony'
    assert sword_bridge.display_name(harmony.MODULE_KEY) == \
        'The Harmony of the Gospels'


def test_robertsons_185_sections_in_14_parts():
    ids = harmony.section_ids()
    assert len(ids) == 185 and ids[0] == '1' and ids[-1] == '184'
    parts = harmony.data()['parts']
    assert len(parts) == 14
    assert sorted(sid for p in parts for sid in p['sections']) == sorted(ids)


def test_headings_are_in_sentence_case():
    """Robertson's capitals are print, not emphasis; names keep theirs."""
    s = harmony.section('72')
    assert s['heading'].startswith('The first retirement. The Twelve return')
    assert harmony.section('143')['heading'].endswith(
        "(possibly that of John Mark's father and mother)")
    for s in harmony.data()['sections']:
        assert not s['heading'].isupper(), s['id']
    # Divine titles keep Robertson's capitals; John Mark's father does not.
    assert harmony.section('2')['heading'].endswith('as the Word (Logos)')
    assert harmony.section('58')['heading'].endswith('about the Father')
    assert 'the Son of man' in harmony.section('84')['heading']


def test_spans_come_in_canonical_order():
    """Robertson leads with Mark; the columns never reorder."""
    assert list(harmony.gospel_spans('72')) == list(harmony.GOSPELS)
    assert harmony.ref_text(harmony.gospel_spans('72')['Mark'][0]) == \
        'Mark 6:30–44'


def test_a_verse_finds_its_section():
    assert harmony.section_for_verse('Matthew', 14, 15) == '72'
    assert harmony.section_for_verse('John', 6, 5) == '72'
    # A verse Robertson's text left out is attached to its neighbour.
    assert harmony.section_for_verse('Mark', 11, 26) == '131'
    assert harmony.section_for_verse('Acts', 1, 9) is None


def test_the_lords_prayer_is_said_elsewhere_not_one_event():
    """Robertson gives two occasions (§54, §105): a fine link, not solid."""
    to_105 = [m for m in harmony.other_links('54') if m['target'] == '105']
    assert [m['kind'] for m in to_105] == ['same_words']
    assert to_105[0]['witnesses'] == ['eusebius', 'robertson']


def test_the_eusebius_lens_pairs_passages_outside_the_section():
    """§54 is Matthew alone; Eusebius sets Luke 11:1–4 beside its prayer."""
    rows = harmony.eusebius_rows('54')
    prayer = [r for r in rows if any(
        harmony.ref_text(x['span']).startswith('Luke 11:1')
        for x in r['cells'].get('Luke', []))]
    assert prayer and 'Matt' in prayer[0]['cells']
    for r in rows:
        assert r['table'] in harmony.CANON_GOSPELS


def test_textual_questions_are_stated_once_each():
    mark_end = harmony.section_for_verse('Mark', 16, 9)
    assert ('Eusebius’s tables end at Mark 16:8.', ('Mark', 16, 9)) in \
        harmony.facts(mark_end)
    assert any('7:53' in f for f, _v in harmony.facts('97'))
    assert any('Matthew 17:21' in f for f, _v in harmony.facts('87'))
    assert harmony.facts('72') == []
    # The readings open at a verse the section holds, not at Mark 16:9.
    assert harmony.facts('184')[0][1] == ('Mark', 16, 19)


def test_the_one_odd_canon_is_read_as_canon_one_and_said():
    assert harmony.canon('I.IV') == 'I'
    with_odd = [s for s in harmony.section_ids()
                if any('I.IV' in f for f, _v in harmony.facts(s))]
    assert with_odd == ['141']
    assert 'I.IV' not in harmony.canons('141')


def test_places_fall_inside_their_gospel():
    """John's temple cleansing near his start, the Synoptics' near their end."""
    john = harmony.place(harmony.gospel_spans('31')['John'][0])
    mark = harmony.place(harmony.gospel_spans('129')['Mark'][0])
    assert 0 <= john[0] < john[1] < 0.15
    assert 0.6 < mark[0] < mark[1] <= 1


def test_words_keep_text_and_strongs_in_order():
    markup = ('<w savlm="strong:G2532">And</w> <w savlm="strong:G3588 '
              'strong:G652">the apostles</w>, <w savlm="strong:G3756"/>'
              'went<note type="x">a note</note>')
    got = harmony.words(markup)
    assert ''.join(t for t, _n in got) == 'And the apostles, went'
    assert got[2] == ('the apostles', frozenset({'G3588', 'G652'}))


def test_shared_numbers_leave_out_function_words():
    a = [(1, 1, [('loaves', frozenset({'G740'})), ('and', frozenset({'G2532'}))])]
    b = [(2, 1, [('loaves', frozenset({'G740'})), ('and', frozenset({'G2532'}))])]
    c = [(3, 1, [('boat', frozenset({'G4143'}))])]
    assert harmony.shared_numbers([a, b, c]) == [{'G740'}, {'G740'}, set()]


def test_signs_sit_where_a_shared_section_begins_in_each_gospel():
    """§72 starts at Mark 6:30 and John 6:1; a one-Gospel section (§56,
    Luke 7:11) gets no sign: there is nothing to set beside it."""
    assert harmony.section_starts('Mark', 6)[30] == '72'
    assert harmony.section_starts('John', 6)[1] == '72'
    assert 11 not in harmony.section_starts('Luke', 7)
    assert harmony.section_starts('Acts', 1) == {}
    assert harmony.told('72') == (True, True, True, True)
    assert harmony.gospel_of('Luke') == 2 and harmony.gospel_of('Acts') is None


def test_a_chapter_outside_the_gospels_leaves_the_harmony_unread():
    """Every chapter's render asks for its signs; Romans must not pay for
    reading the harmony's data to learn it has none."""
    harmony.data.cache_clear()
    harmony._starts.cache_clear()
    assert harmony.section_starts('Romans', 8) == {}
    assert harmony.data.cache_info().currsize == 0


def test_the_eusebius_rows_are_worked_out_once_a_section():
    """The page asks for them on every resize of a drag."""
    assert harmony.eusebius_rows('54') is harmony.eusebius_rows('54')
    assert harmony.eusebian_sections('54') is harmony.eusebian_sections('54')


def test_the_passion_is_dense_but_bounded():
    """At most 14 signs in one chapter (Luke 9), as the research measured;
    a section Robertson resumes after a break signs only where it begins.
    Mark 14 has §152 once, at verse 26, though Robertson resumes it at 32."""
    worst = max(len(harmony.section_starts(harmony.BOOK[b], c))
                for b, n in (('Matt', 28), ('Mark', 16), ('Luke', 24),
                             ('John', 21)) for c in range(1, n + 1))
    assert worst == 14
    assert list(harmony.section_starts('Mark', 14).values()).count('152') == 1
