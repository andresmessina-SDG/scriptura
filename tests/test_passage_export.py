"""What an exported passage says, and how it cites itself.

The citation rules are SBTS/Turabian, from the seminary's own short-form
guide, and they are the reason this file exists: a reference that a grader
would mark wrong is a defect, and none of it is visible in the app.
"""
import annotations as annotations_store
import passage_export
import sword_bridge
from passage_export import (EN_DASH, abbreviate, build, format_chapter_span,
                            format_reference, join_references,
                            pericope_verses)

CHAPTER = [(15, 'Verse fifteen.'), (16, 'For God so <i>loved</i> the world.'),
           (17, 'Verse seventeen.'), (18, 'Verse eighteen.'),
           (19, 'Verse nineteen.')]


def _sword(monkeypatch, headings=None):
    monkeypatch.setattr(sword_bridge, 'load_chapter',
                        lambda *_a: list(CHAPTER))
    monkeypatch.setattr(sword_bridge, 'chapter_headings',
                        lambda *_a: dict(headings or {}))
    monkeypatch.setattr(sword_bridge, 'module_info',
                        lambda _m: {'description': 'King James Version'})


def _notes(monkeypatch, data):
    monkeypatch.setattr(annotations_store, 'get_annotations',
                        lambda *_a: data)


# ── The citation ─────────────────────────────────────────────────────────────

def test_a_range_takes_an_en_dash_not_a_hyphen():
    """The guide names this rule first. A hyphen here is simply wrong."""
    ref = format_reference('John', 3, [16, 17, 18])
    assert ref == f'John 3:16{EN_DASH}18'
    assert '-' not in ref


def test_consecutive_verses_collapse_and_gaps_take_commas():
    """`Matt 25:34, 46` — commas separate verses, and a run is one span."""
    assert format_reference('Matthew', 25, [34, 46]) == 'Matt 25:34, 46'
    assert (format_reference('Revelation', 20, [13, 15])
            == 'Rev 20:13, 15')
    assert (format_reference('John', 5, [28, 29, 31])
            == f'John 5:28{EN_DASH}29, 31')


def test_books_are_abbreviated_in_a_reference_and_spelled_out_in_prose():
    """Both forms are required: abbreviated inside parentheses, written out
    when the reference sits in a sentence."""
    assert format_reference('1 Corinthians', 12) == '1 Cor 12'
    assert (format_reference('1 Corinthians', 12, prose=True)
            == '1 Corinthians 12')


def test_the_translation_follows_the_reference_with_no_comma():
    """`John 1:29 ESV`, which is the guide's own example."""
    assert (format_reference('John', 1, [29], version='ESV')
            == 'John 1:29 ESV')


def test_one_psalm_is_ps_and_several_are_pss():
    """The one rule that is genuinely peculiar to this style."""
    assert format_reference('Psalms', 23) == 'Ps 23'
    assert format_chapter_span('Psalms', 23, 23) == 'Ps 23'
    assert format_chapter_span('Psalms', 23, 24) == f'Pss 23{EN_DASH}24'
    # A verse range inside one psalm never makes it plural.
    assert format_reference('Psalms', 23, [1, 2, 3]) == f'Ps 23:1{EN_DASH}3'


def test_semicolons_separate_books_and_chapters():
    """The guide's string, rebuilt from the parts."""
    assert join_references([
        format_reference('Daniel', 12, [2]),
        format_reference('Matthew', 25, [34, 46]),
        format_reference('John', 5, [28, 29]),
    ]) == f'Dan 12:2; Matt 25:34, 46; John 5:28{EN_DASH}29'


def test_every_book_the_app_offers_has_an_abbreviation():
    """A missing entry is not a crash — it spells the book out — but the
    canonical sixty-six should never be reaching that fallback."""
    import window
    missing = [b for b in window.BOOKS if b not in passage_export.SBL_ABBREV]
    assert missing == []


def test_an_unknown_book_is_spelled_out_rather_than_guessed_at():
    assert abbreviate('Epistle to the Laodiceans') == 'Epistle to the Laodiceans'


# ── The document ─────────────────────────────────────────────────────────────

def test_the_passage_carries_its_text_without_markup(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    doc = build('KJV', 'John', 3, [16, 17])
    assert 'For God so loved the world.' in doc
    assert '<i>' not in doc
    assert 'Verse fifteen' not in doc          # outside the selection


def test_the_heading_is_the_citation(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    doc = build('KJV', 'John', 3, [16, 17, 18])
    assert doc.splitlines()[0] == f'# John 3:16{EN_DASH}18 KJV'


def test_no_selection_takes_the_whole_chapter(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    doc = build('KJV', 'John', 3)
    assert doc.splitlines()[0] == '# John 3 KJV'
    assert 'Verse nineteen.' in doc


def test_the_readers_own_marks_travel_with_it(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {'16': {'note': 'the hinge of the chapter',
                                'highlight': 'yellow', 'tags': ['grace']}})
    doc = build('KJV', 'John', 3, [16])
    assert 'the hinge of the chapter' in doc
    assert 'yellow' in doc and 'grace' in doc
    assert 'John 3:16' in doc


def test_notes_can_be_left_behind(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {'16': {'note': 'private'}})
    assert 'private' not in build('KJV', 'John', 3, [16], notes=False)


def test_a_verse_with_no_mark_contributes_no_note_line(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {'16': {'highlight': None, 'tags': []}})
    assert 'Notes' not in build('KJV', 'John', 3, [16])


def test_every_export_names_the_translation(monkeypatch):
    """Attribution is not a setting. Export is redistribution, and the text
    has to say whose words it carries wherever it ends up."""
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    for markdown in (True, False):
        doc = build('KJV', 'John', 3, [16], markdown=markdown)
        assert 'King James Version' in doc
        assert 'KJV' in doc


def test_plain_text_carries_no_markdown_furniture(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {'16': {'note': 'a mark'}})
    doc = build('KJV', 'John', 3, [16], markdown=False)
    assert '#' not in doc and '>' not in doc and '**' not in doc
    assert 'a mark' in doc


def test_tagged_markup_does_not_leave_gaps_before_punctuation(monkeypatch):
    """KJVA marks up individual words, so its tags sit between the word and
    the comma. Stripping them naively gave "the world , that he gave" the
    whole way down a worksheet."""
    monkeypatch.setattr(
        sword_bridge, 'load_chapter',
        lambda *_a: [(16, 'loved the <w x="1">world</w> , that he gave '
                          '<w x="2">him</w> .')])
    monkeypatch.setattr(sword_bridge, 'chapter_headings', lambda *_a: {})
    monkeypatch.setattr(sword_bridge, 'module_info', lambda _m: {})
    _notes(monkeypatch, {})
    doc = build('KJVA', 'John', 3, [16])
    assert 'world, that he gave him.' in doc
    assert ' ,' not in doc and ' .' not in doc


def test_the_attribution_names_the_translation_not_its_catalogue_entry():
    """A SWORD Description is written for a module list. KJVA's runs to
    "King James Version (1769) with Strongs Numbers and Morphology and
    CatchWords, including Apocrypha (without glosses)"."""
    assert passage_export._short_name(
        'King James Version (1769) with Strongs Numbers and Morphology and '
        'CatchWords, including Apocrypha (without glosses)'
    ) == 'King James Version'
    # Only ever cuts: a name with no tail survives whole.
    assert passage_export._short_name(
        "Young's Literal Translation") == "Young's Literal Translation"
    assert passage_export._short_name('') == ''


# ── The depth layers ─────────────────────────────────────────────────────────

class FakeWord:
    def __init__(self, verse, surface, translit, gloss, editions, in_stream):
        self.verse, self.surface, self.translit = verse, surface, translit
        self.gloss, self.editions, self.in_stream = gloss, editions, in_stream


def _layers(monkeypatch, words=(), variants=(), voices=()):
    import catena_bridge
    import interlinear_data
    monkeypatch.setattr(interlinear_data, 'module_names',
                        lambda: ['InterlinearGreek'])
    monkeypatch.setattr(interlinear_data, 'is_installed', lambda _n: True)
    monkeypatch.setattr(interlinear_data, 'chapter_count', lambda *_a: 21)
    monkeypatch.setattr(interlinear_data, 'load_chapter',
                        lambda *_a: list(words))
    monkeypatch.setattr(interlinear_data, 'chapter_variants',
                        lambda *_a: list(variants))
    monkeypatch.setattr(catena_bridge, 'is_installed', lambda: True)
    monkeypatch.setattr(catena_bridge, 'lookup', lambda *_a: list(voices))


def test_the_depth_layers_are_absent_unless_asked_for(monkeypatch):
    """A plain reader gets a clean sheet."""
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    _layers(monkeypatch,
            words=[FakeWord(16, 'οὕτως', 'houtōs', 'Thus', 'NA28+TR', True)],
            voices=[{'author': 'Augustine', 'text': 'A voice.'}])
    doc = build('KJVA', 'John', 3, [16])
    assert 'Interlinear' not in doc and 'Voices' not in doc
    assert 'Augustine' not in doc


def test_the_interlinear_carries_surface_translit_and_gloss(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    _layers(monkeypatch,
            words=[FakeWord(16, 'θεὸς', 'theos', 'God', 'NA28+TR', True)])
    doc = build('KJVA', 'John', 3, [16], interlinear=True)
    assert '## Interlinear' in doc
    assert 'θεὸς (theos) God' in doc


def test_a_supplied_word_survives_being_read_as_markdown(monkeypatch):
    """TAGNT marks a supplied word `<the>`, and a Markdown reader treats that
    as an unknown tag and drops it — losing the very words the source went to
    the trouble of marking."""
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    _layers(monkeypatch,
            words=[FakeWord(16, 'ὁ', 'ho', '<the>', 'NA28+TR', True)])
    assert r'\<the\>' in build('KJVA', 'John', 3, [16], interlinear=True)
    # Plain text has no such reader, so it keeps the source's own convention.
    assert '<the>' in build('KJVA', 'John', 3, [16],
                            interlinear=True, markdown=False)


def test_only_words_the_editions_disagree_about_are_variants(monkeypatch):
    """The real case this was measured on: John 3:16's αὐτοῦ is carried by
    Treg, TR and Byz but not by the critical text."""
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    _layers(monkeypatch, variants=[
        FakeWord(16, 'θεὸς', 'theos', 'God',
                 'NA28+NA27+Tyn+SBL+WH+Treg+TR+Byz', True),
        FakeWord(16, 'αὐτοῦ', 'autou', 'of him', 'Treg+TR+Byz', False),
    ])
    doc = build('KJVA', 'John', 3, [16], variants=True)
    assert 'αὐτοῦ' in doc and 'TR' in doc
    assert 'θεὸς' not in doc          # every edition carries it


def test_a_word_order_marker_is_not_a_presence_variant():
    """`TR»1` still means TR carries the word. Treating the marker as a
    different edition would report every re-ordering as an omission."""
    assert not passage_export.is_variant('NA28+TR»1+Byz»1')
    assert passage_export.is_variant('NA28+SBL')
    assert passage_export.is_variant('TR+Byz')


def test_the_voices_name_who_is_speaking(monkeypatch):
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    _layers(monkeypatch, voices=[
        {'author': 'John Chrysostom', 'text': 'Marvel <b>not</b>.'}])
    doc = build('KJVA', 'John', 3, [16], catena=True)
    assert '## Voices' in doc
    assert 'John Chrysostom' in doc
    assert 'Marvel not.' in doc and '<b>' not in doc


def test_a_layer_with_nothing_installed_leaves_no_trace(monkeypatch):
    """No heading, and no note of absence. The reader knows what they have."""
    import catena_bridge
    import interlinear_data
    _sword(monkeypatch)
    _notes(monkeypatch, {})
    monkeypatch.setattr(interlinear_data, 'module_names', lambda: [])
    monkeypatch.setattr(catena_bridge, 'is_installed', lambda: False)
    doc = build('KJVA', 'John', 3, [16],
                interlinear=True, variants=True, catena=True)
    assert 'Interlinear' not in doc
    assert 'Textual variants' not in doc
    assert 'Voices' not in doc
    assert 'King James Version' in doc     # the sheet is still a sheet


# ── Pericope scope (what DR4 made possible) ──────────────────────────────────

def test_a_pericope_runs_from_its_heading_to_the_next(monkeypatch):
    _sword(monkeypatch, headings={16: ['God so loved the world'],
                                  18: ['Belief and judgment']})
    assert pericope_verses('ESV', 'John', 3, 16) == [16, 17]
    assert pericope_verses('ESV', 'John', 3, 17) == [16, 17]
    assert pericope_verses('ESV', 'John', 3, 18) == [18, 19]


def test_text_before_the_first_heading_is_its_own_run(monkeypatch):
    """It ends where the first heading begins, rather than swallowing the
    unit that heading names — a chapter can open with material that belongs
    to no section, and that opening is a unit of its own."""
    _sword(monkeypatch, headings={16: ['God so loved the world']})
    assert pericope_verses('ESV', 'John', 3, 15) == [15]
    assert pericope_verses('ESV', 'John', 3, 16) == [16, 17, 18, 19]


def test_a_module_with_no_headings_has_no_units_to_invent(monkeypatch):
    """KJV, ASV and the rest carry no heading data at all. The whole chapter
    is the honest answer; a guessed boundary would not be."""
    _sword(monkeypatch, headings={})
    assert pericope_verses('KJV', 'John', 3, 16) == [15, 16, 17, 18, 19]
