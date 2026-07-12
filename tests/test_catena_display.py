"""Tests for catena_reader's display-time repair helpers — author suffix
normalization, ALL-CAPS title taming, author-repeat stripping, and the
sentence-boundary preview cut. Pure functions; no widgets are built."""

import catena_reader
from catena_reader import (_author_label, _author_parts, _display_title,
                           _preview, _source_title)


def test_suffix_bare_locator_gains_parens_and_loses_leading_space():
    e = {'author': '1 Corinthians', 'author_suffix': ' 10:23-33'}
    assert _author_parts(e) == ('1 Corinthians', '(10:23-33)')
    assert _author_label(e) == '1 Corinthians (10:23-33)'


def test_suffix_already_parenthesized_is_not_double_wrapped():
    e = {'author': 'Alcuin of York',
         'author_suffix': ' (as quoted by Aquinas, AD 1274)'}
    assert _author_parts(e) == ('Alcuin of York',
                                '(as quoted by Aquinas, AD 1274)')
    assert '((' not in _author_label(e)


def test_suffix_prose_with_parens_kept_verbatim():
    e = {'author': 'Apollinaris of Laodicea',
         'author_suffix': ' is referenced above by Jerome (AD 420)'}
    assert _author_parts(e)[1] == 'is referenced above by Jerome (AD 420)'


def test_suffix_absent():
    assert _author_parts({'author': 'Irenaeus'}) == ('Irenaeus', '')
    assert _author_label({'author': 'Irenaeus', 'author_suffix': None}) == 'Irenaeus'


def test_display_title_tames_all_caps():
    assert _display_title('FRAGMENTS ON JOHN 12') == 'Fragments on John 12'
    assert _display_title('HOMILY XII ON GENESIS') == 'Homily XII on Genesis'


def test_display_title_keeps_locator_tokens():
    assert _display_title('THE LONG RULES, Q.37.R') == 'The Long Rules, Q.37.R'
    assert _display_title('HOMILY XII.3 ON JOHN') == 'Homily XII.3 on John'
    assert _display_title('SERMON 215:2') == 'Sermon 215:2'


def test_display_title_leaves_mixed_case_alone():
    assert _display_title('Against Heresies Book 3') == 'Against Heresies Book 3'
    assert _display_title('') == ''


def test_source_title_strips_author_repeat():
    e = {'author': 'Irenaeus',
         'source_title': 'Irenaeus Against Heresies Book 3'}
    assert _source_title(e) == 'Against Heresies Book 3'


def test_source_title_keeps_distinct_title():
    e = {'author': 'Clement of Alexandria',
         'source_title': 'The Instructor Book 1'}
    assert _source_title(e) == 'The Instructor Book 1'


def test_source_title_equal_to_author_survives():
    e = {'author': 'Irenaeus', 'source_title': 'Irenaeus'}
    assert _source_title(e) == 'Irenaeus'


def test_preview_prefers_sentence_boundary():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 70) + '. ' + 'b' * 200
    p = _preview(text)
    assert p == 'a' * (n - 70) + '.'


def test_preview_falls_back_to_word_cut():
    text = 'word ' * 200
    p = _preview(text)
    assert p.endswith('…')
    assert len(p) <= catena_reader._PREVIEW_CHARS + 1


def test_preview_ignores_too_early_sentence_break():
    text = 'Short. ' + 'a' * 400
    assert _preview(text).endswith('…')


def test_preview_word_cut_sheds_clause_punctuation():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 8) + ' flesh, and more words beyond the window'
    p = _preview(text)
    assert p.endswith('flesh…')


def test_preview_word_cut_sheds_dangling_dash_and_its_space():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 9) + ' earth - the Lord, the God of hosts'
    p = _preview(text)
    assert p.endswith('earth…')


def test_preview_never_doubles_a_source_ellipsis():
    n = catena_reader._PREVIEW_CHARS
    text = 'a' * (n - 9) + ' earth … and more words beyond the window'
    p = _preview(text)
    assert p.endswith('earth …')
    assert not p.endswith('……')
