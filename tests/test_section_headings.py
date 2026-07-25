"""Section-heading parsing — which preverse titles count as pericopes.

SWORD hands preverse titles over as a raw markup blob in the entry
attributes (never in renderText output), and not every <title> in it is a
section heading. These cover the filtering rules; the live attribute read
itself is exercised against real modules by the app.
"""
from sword_bridge import _titles_from_raw


def test_plain_section_title():
    raw = '<title type="section">The Baptism of Jesus</title>'
    assert _titles_from_raw(raw) == ['The Baptism of Jesus']


def test_untyped_title_counts():
    # BSB's real section heads carry no type attribute at all.
    assert _titles_from_raw('<title>The First Disciples</title>') \
        == ['The First Disciples']


def test_lexham_x_s_type_counts():
    raw = '<title type="x-s">Yahweh the Shepherd</title>'
    assert _titles_from_raw(raw) == ['Yahweh the Shepherd']


def test_parallel_passage_refs_are_not_headings():
    # BSB ships cross references as titles; rendering them as section
    # heads would put "(Ezekiel 34:11-24)" where a heading belongs.
    raw = ('<title type="parallel"> (<reference osisRef="Ezek.34.11">'
           'Ezekiel 34:11-24</reference>)</title>')
    assert _titles_from_raw(raw) == []


def test_psalm_superscription_is_not_a_heading():
    # Canonical text, not an editorial division.
    raw = '<title type="psalm">A Psalm of David.</title>'
    assert _titles_from_raw(raw) == []


def test_inner_markup_is_stripped():
    raw = '<title type="section">The <hi type="italic">Great</hi> Commission</title>'
    assert _titles_from_raw(raw) == ['The Great Commission']


def test_entities_are_unescaped():
    raw = '<title type="section">Moses &amp; Aaron</title>'
    assert _titles_from_raw(raw) == ['Moses & Aaron']


def test_whitespace_is_collapsed():
    raw = '<title type="section">\n  Crossing   the\n  Red Sea\n</title>'
    assert _titles_from_raw(raw) == ['Crossing the Red Sea']


def test_multiple_titles_keep_document_order():
    raw = ('<title type="section">First</title>'
           '<div sID="x" type="x-p"/>'
           '<title type="section">Second</title>')
    assert _titles_from_raw(raw) == ['First', 'Second']


def test_empty_title_is_dropped():
    assert _titles_from_raw('<title type="section">   </title>') == []


def test_blob_without_titles_yields_nothing():
    # The preverse blob routinely carries paragraph milestones and nothing else.
    assert _titles_from_raw('<div sID="gen6509" type="x-p"/>') == []


def test_mixed_blob_keeps_only_the_heading():
    raw = ('<title type="parallel">(<reference osisRef="Isa.40.1">Isaiah 40</reference>)</title>'
           '<title type="section">John the Baptist Prepares the Way</title>')
    assert _titles_from_raw(raw) == ['John the Baptist Prepares the Way']


# ── inline titles in commentaries ────────────────────────────────────────
# Enabling SWORD's Headings option for the Bible feature also makes
# commentaries emit their own titles inline, carrying a type attribute.

from pane import _html_to_markup


def test_typed_inline_title_becomes_a_heading():
    # Clarke uses type="x-s", MHC type="x-s3". A bare <title> pattern
    # missed both, and the generic tag-strip then left the text as
    # ordinary prose in the middle of the commentary.
    out = _html_to_markup('<title type="x-s">The Creation.</title>Body text',
                          True)
    assert 'The Creation.' in out
    assert 'letter_spacing="800"' in out


def test_untyped_inline_title_still_becomes_a_heading():
    out = _html_to_markup('<title>Plain Title</title>Body', True)
    assert 'letter_spacing="800"' in out


def test_inline_title_is_dropped_when_headings_are_off():
    # These only became visible when the Headings option was enabled, so
    # the Appearance toggle has to govern them too.
    out = _html_to_markup('<title type="x-s">The Creation.</title>Body text',
                          True, show_headings=False)
    assert 'The Creation.' not in out
    assert 'Body text' in out


def test_parallel_reference_title_is_never_a_heading():
    out = _html_to_markup(
        '<title type="parallel">(Isaiah 40)</title>Body', True)
    assert 'Isaiah 40' not in out
    assert 'Body' in out


def test_title_text_never_survives_as_bare_prose():
    # The bug: tags stripped, text kept, no heading formatting.
    for kind in ('x-s', 'x-s3', 'section', ''):
        attr = f' type="{kind}"' if kind else ''
        out = _html_to_markup(f'<title{attr}>Heading Here</title>Body', True)
        assert ('letter_spacing="800"' in out) or ('Heading Here' not in out)
