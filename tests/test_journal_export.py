"""What leaves the app, and what it carries with it.

A document outlives the app it left, so the translation's name travels with
it — that is the licensing guardrail, and the whole reason this goes through
passage_export rather than being written out by hand. The previous exporter
was hand-rolled and carried neither a citation nor a stamp.
"""
import pytest

import annotations
import journal
import passage_export


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'journal.json'))
    monkeypatch.setattr(journal, '_cache', None)
    return tmp_path


@pytest.fixture
def quoting(monkeypatch):
    """Stand in for an installed translation, so these run on CI too."""
    monkeypatch.setattr(passage_export, 'verse_text',
                        lambda m, b, c, v: 'For God so loved the world')
    monkeypatch.setattr(passage_export, 'version_label', lambda m: 'BSB')
    monkeypatch.setattr(passage_export, 'attribution',
                        lambda m: 'Text from Berean Standard Bible (BSB).')


def _mark(book='John', chapter=3, verse=16, **kw):
    row = {'kind': 'mark', 'book': book, 'chapter': chapter,
           'verse': str(verse), 'app_verse': verse, 'highlight': None,
           'underline': False, 'note': None, 'tags': [],
           'is_chapter_note': False, 'created': '2026-09-10T08:00:00',
           'modified': '2026-09-10T08:00:00'}
    row.update(kw)
    return row


def _entry(**kw):
    row = {'kind': 'entry', 'id': 'e1', 'book': None, 'chapter': None,
           'app_verse': None, 'verse': None, 'highlight': None,
           'underline': False, 'note': None, 'is_chapter_note': False,
           'title': '', 'body': '', 'date': '2026-09-06', 'anchors': [],
           'plan': None, 'collect': None, 'tags': [],
           'created': None, 'modified': None}
    row.update(kw)
    return row


# ── The guardrail ────────────────────────────────────────────────────────────

def test_the_attribution_stamp_is_present(isolated, quoting):
    doc = passage_export.build_annotations([_mark(note='a note')], 'BSB')
    assert 'Text from Berean Standard Bible (BSB).' in doc


def test_nothing_quoted_means_nothing_claimed(isolated, quoting):
    """A document with no scripture in it must not claim to carry someone's
    text — a verse-less entry is the reader's words alone."""
    doc = passage_export.build_annotations(
        [_entry(title='A sermon', body='my own words')], 'BSB')
    assert 'Text from' not in doc
    assert 'my own words' in doc


def test_a_whole_chapter_anchor_is_not_quoted(isolated, quoting):
    """Quoting a whole chapter into a list of notes is not an export, it is
    a Bible — so a chapter anchor cites without quoting, and the stamp does
    not appear for it either."""
    doc = passage_export.build_annotations(
        [_entry(title='Day 1',
                anchors=[{'book': 'Genesis', 'chapter': 1, 'verses': []}])],
        'BSB')
    assert 'For God so loved' not in doc
    assert 'Text from' not in doc


def test_a_chapter_note_is_cited_but_not_quoted(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(is_chapter_note=True, app_verse=None, verse=None,
               note='about the whole chapter')], 'BSB')
    assert 'about the whole chapter' in doc
    assert 'For God so loved' not in doc


# ── The citation ─────────────────────────────────────────────────────────────

def test_a_mark_carries_an_sbl_citation_with_the_version(isolated, quoting):
    doc = passage_export.build_annotations([_mark(note='n')], 'BSB')
    assert 'John 3:16 BSB' in doc


def test_an_entrys_anchors_are_joined_as_one_citation(isolated, quoting):
    doc = passage_export.build_annotations(
        [_entry(title='Trinity VII', anchors=[
            {'book': 'Romans', 'chapter': 6, 'verses': [3, 4]},
            {'book': 'Matthew', 'chapter': 5, 'verses': [20]}])], 'BSB')
    assert 'Rom 6:3–4 BSB; Matt 5:20 BSB' in doc


def test_the_psalms_rule_survives_the_journey(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(book='Psalms', chapter=23, verse=1, note='n')], 'BSB')
    assert 'Ps 23:1' in doc


# ── Content ──────────────────────────────────────────────────────────────────

def test_the_verse_the_mark_is_about_is_quoted(isolated, quoting):
    doc = passage_export.build_annotations([_mark(note='n')], 'BSB')
    assert '> For God so loved the world' in doc


def test_an_entrys_body_passes_through_as_markdown(isolated, quoting):
    """It already IS Markdown — it is what the reader typed — so escaping it
    would print literal asterisks in their own document."""
    doc = passage_export.build_annotations(
        [_entry(title='t', body='a **bold** word')], 'BSB')
    assert 'a **bold** word' in doc


def test_a_marks_note_is_escaped_where_escaping_matters(isolated, quoting):
    """`_md` escapes only what changes the structure — angle brackets, which
    a Markdown reader drops silently. A stray '*' is left alone on purpose:
    a cosmetic italic is a surprise, a swallowed word is a loss."""
    doc = passage_export.build_annotations(
        [_mark(note='the supplied <the> word')], 'BSB')
    assert '\\<the\\>' in doc


def test_highlight_and_underline_are_named(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(highlight='#ffff00', underline=True, note='n')], 'BSB')
    assert 'Highlight' in doc and 'Underline' in doc


def test_tags_are_carried(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(note='n', tags=['covenant', 'grace'])], 'BSB')
    assert '#covenant' in doc and '#grace' in doc


def test_an_untitled_entry_still_has_a_heading(isolated, quoting):
    doc = passage_export.build_annotations([_entry(body='words')], 'BSB')
    assert 'Untitled entry' in doc


def test_the_plain_text_form_has_no_markdown_furniture(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(note='n')], 'BSB', markdown=False)
    assert '# ' not in doc
    assert '> ' not in doc
    assert 'John 3:16 BSB' in doc


def test_the_order_given_is_the_order_written(isolated, quoting):
    doc = passage_export.build_annotations(
        [_mark(book='Genesis', chapter=1, verse=1, note='first'),
         _mark(book='John', chapter=3, verse=16, note='second')], 'BSB')
    assert doc.index('first') < doc.index('second')


def test_an_empty_list_still_produces_a_document(isolated, quoting):
    doc = passage_export.build_annotations([], 'BSB')
    assert doc.strip()
    assert 'Text from' not in doc


def test_a_heading_inside_an_entry_nests_under_it(isolated, quoting):
    """The document heads at '#' and an entry at '##', so a reader's own
    '# The collect' must become '### The collect' — otherwise it outranks
    the entry containing it and the outline comes out inverted."""
    doc = passage_export.build_annotations(
        [_entry(title='Trinity VII', body='# The collect\n\ntext')], 'BSB')
    assert '### The collect' in doc
    assert '\n# The collect' not in doc


def test_heading_demotion_stops_at_six(isolated, quoting):
    doc = passage_export.build_annotations(
        [_entry(title='t', body='###### deep')], 'BSB')
    assert '###### deep' in doc
    assert '#######' not in doc


def test_a_row_of_hashes_is_not_a_heading(isolated, quoting):
    doc = passage_export.build_annotations(
        [_entry(title='t', body='###')], 'BSB')
    assert '\n###\n' in doc


def test_the_quoted_verse_leaves_app_space_through_the_right_door(
        isolated, monkeypatch):
    """Stored numbers are APP space. Handing them to verse_text raw quotes a
    Synodal psalter's superscription instead of the line the mark is on —
    the app-verse-0 trap the store was keyed to avoid."""
    asked = []
    monkeypatch.setattr(passage_export, 'verse_text',
                        lambda m, b, c, v: asked.append(list(v)) or 'text')
    monkeypatch.setattr(passage_export, 'version_label', lambda m: 'X')
    monkeypatch.setattr(passage_export, 'attribution', lambda m: 'Text from X.')
    monkeypatch.setattr(passage_export.annotations_store, 'module_verse',
                        lambda m, b, c, v: v + 1)   # a superscribed psalter

    passage_export.build_annotations(
        [_mark(book='Psalms', chapter=3, verse=1, note='n')], 'Psalter')
    assert asked == [[2]], 'app verse 1 must leave as the module\'s verse 2'


def test_a_verse_the_module_cannot_render_is_simply_not_quoted(
        isolated, monkeypatch):
    monkeypatch.setattr(passage_export, 'verse_text', lambda m, b, c, v: 'text')
    monkeypatch.setattr(passage_export, 'version_label', lambda m: 'X')
    monkeypatch.setattr(passage_export, 'attribution', lambda m: 'Text from X.')
    monkeypatch.setattr(passage_export.annotations_store, 'module_verse',
                        lambda m, b, c, v: None)
    doc = passage_export.build_annotations([_mark(note='n')], 'X')
    assert 'Text from' not in doc


def test_the_document_is_named_for_the_page_it_came_from(isolated, quoting):
    """A document of journal entries headed "Annotations" tells the reader
    the wrong thing about what is in it."""
    doc = passage_export.build_annotations(
        [_entry(title='t', body='b')], 'BSB', title='Journal')
    assert doc.startswith('# Journal')
    assert passage_export.build_annotations(
        [_mark(note='n')], 'BSB').startswith('# Annotations')

