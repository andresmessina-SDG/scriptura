"""The Creeds' data and its doors, without GTK.

The data is built and checked by tools/creeds/build_creeds.py; these tests
hold the shipped file to the shape the page and the reading view read, and
check the two lookups the reading view's mark depends on.
"""
import content
import creeds
import sword_bridge


def test_three_creeds_ship_in_tab_order():
    ids = [c['id'] for c in creeds.data()['creeds']]
    assert ids == list(creeds.CREED_IDS)


def test_the_module_is_listed_and_named():
    assert creeds.MODULE_KEY in creeds.module_names()
    assert creeds.MODULE_KEY in content.readable_module_names()
    assert content.type_key(creeds.MODULE_KEY) == 'creeds'
    assert sword_bridge.display_name(creeds.MODULE_KEY) == 'The Creeds'


def test_every_link_is_shaped_for_the_page():
    for c in creeds.data()['creeds']:
        for p in creeds.phrases(c['id']):
            assert p['links'], p['id']
            for link in p['links']:
                assert link['kind'] in creeds.KIND_NAMES
                assert link['text'], link['ref']
                assert 0.0 <= link['tp'] <= 1.0
                if link['kind'] == 'f':
                    assert not link['nt'], link['ref']
                if link['kind'] == 'w':
                    # The builder refuses a same-words link that shares no word.
                    assert link['shared'] > 0, link['ref']
                    assert any(hit for _w, hit, _g in link['orig_words'])


def test_disputed_lines_carry_a_note():
    for cid in creeds.CREED_IDS:
        for p in creeds.phrases(cid):
            if p.get('disputed'):
                assert p.get('note'), (cid, p['id'])


def test_each_creed_rebuilds_its_1662_opening():
    first = {cid: creeds.phrases(cid)[0]['en'] for cid in creeds.CREED_IDS}
    assert first['apostles'].startswith('I believe in God the Father Almighty')
    assert first['nicene'].startswith('I believe in one God the Father')
    assert first['athanasian'].startswith('Whosoever will be saved')


def test_athanasian_has_42_verses_and_its_sections():
    c = creeds.creed('athanasian')
    assert len(c['articles']) == 42
    assert [n for n, _name in c['sections']] == [1, 3, 29, 42]


def test_only_same_words_verses_carry_the_mark():
    # Luke 1:33 is "whose kingdom shall have no end" word for word.
    assert 33 in creeds.marker_verses('Luke', 1)
    # John 3:16 is only same teaching in the Nicene, but same words in the
    # Apostles' Latin ("Filium … unigenitum"), so it is marked.
    assert 16 in creeds.marker_verses('John', 3)
    # Genesis 1:1 is only ever same teaching.
    assert 1 not in creeds.marker_verses('Genesis', 1)


def test_a_range_marks_each_verse_in_it():
    # "dead, and buried" uses 1 Corinthians 15:3-4.
    assert {3, 4} <= creeds.marker_verses('1 Corinthians', 15)


def test_the_mark_opens_the_line_in_the_creed_showing():
    assert creeds.line_for_verse('Luke', 1, 33) == ('nicene', '7c')
    # 1 Timothy 6:13 is in both the Apostles' and the Nicene.
    assert creeds.line_for_verse('1 Timothy', 6, 13) == ('apostles', '4a')
    assert creeds.line_for_verse('1 Timothy', 6, 13,
                                 prefer='nicene') == ('nicene', '4b')
    assert creeds.line_for_verse('Genesis', 1, 1) is None


def test_info_counts_the_links():
    info = creeds.info()
    assert info['language'] == 'en'
    assert info['type'].split()[0].isdigit()


def test_no_verse_carries_the_kjv_closing_note():
    """The KJV prints an epistle's closing note ("The second epistle to the
    Corinthians was written from Philippi…") inside its last verse."""
    for c in creeds.data()['creeds']:
        for p in creeds.phrases(c['id']):
            for link in p['links']:
                assert 'was written from' not in link['text'], link['ref']
                assert not link['text'].endswith(('Tychicus.', 'Timothy.')), (
                    link['ref'])
