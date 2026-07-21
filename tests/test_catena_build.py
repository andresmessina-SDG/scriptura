"""Tests for build_catena_pack.py's build-time normalizers — the ALL-CAPS
title taming, author-repeat stripping, and suffix parenthesization that were
formerly repaired at display time in catena_reader. Loaded by path because the
build tool lives under tools/, off the test import path."""

import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    'build_catena_pack',
    os.path.join(os.path.dirname(__file__), '..', 'tools',
                 'build_catena_pack.py'))
assert _SPEC is not None and _SPEC.loader is not None  # by-path load must resolve
bcp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bcp)


def test_tame_title_all_caps():
    assert bcp.tame_title('FRAGMENTS ON JOHN 12') == 'Fragments on John 12'
    assert bcp.tame_title('HOMILY XII ON GENESIS') == 'Homily XII on Genesis'


def test_tame_title_keeps_locator_tokens():
    assert bcp.tame_title('THE LONG RULES, Q.37.R') == 'The Long Rules, Q.37.R'
    assert bcp.tame_title('HOMILY XII.3 ON JOHN') == 'Homily XII.3 on John'
    assert bcp.tame_title('SERMON 215:2') == 'Sermon 215:2'


def test_tame_title_leaves_mixed_case_alone():
    assert bcp.tame_title(
        'Against Heresies Book 3') == 'Against Heresies Book 3'
    assert bcp.tame_title('') == ''


def test_clean_source_title_strips_author_repeat():
    assert bcp.clean_source_title(
        'Irenaeus Against Heresies Book 3', 'Irenaeus') \
        == 'Against Heresies Book 3'
    # tames ALL-CAPS and strips the repeat in one pass
    assert bcp.clean_source_title(
        'IRENAEUS AGAINST HERESIES BOOK 3', 'Irenaeus') \
        == 'Against Heresies Book 3'


def test_clean_source_title_keeps_distinct_title():
    assert bcp.clean_source_title(
        'The Instructor Book 1', 'Clement of Alexandria') \
        == 'The Instructor Book 1'


def test_clean_source_title_equal_to_author_survives():
    assert bcp.clean_source_title('Irenaeus', 'Irenaeus') == 'Irenaeus'


def test_clean_source_title_empty_is_none():
    assert bcp.clean_source_title('', 'Irenaeus') is None
    assert bcp.clean_source_title(None, 'Irenaeus') is None


def test_clean_suffix_bare_locator_gains_parens():
    assert bcp.clean_suffix(' 10:23-33') == '(10:23-33)'


def test_clean_suffix_already_parenthesized_not_double_wrapped():
    assert bcp.clean_suffix(' (as quoted by Aquinas, AD 1274)') \
        == '(as quoted by Aquinas, AD 1274)'


def test_clean_suffix_prose_with_parens_kept():
    assert bcp.clean_suffix(' is referenced above by Jerome (AD 420)') \
        == 'is referenced above by Jerome (AD 420)'


def test_clean_suffix_absent_is_none():
    assert bcp.clean_suffix(None) is None
    assert bcp.clean_suffix('') is None
    assert bcp.clean_suffix('   ') is None


def test_parse_location_shapes():
    enc = bcp.encode
    assert bcp.parse_location('3_16') == (enc(3, 16), enc(3, 16))
    assert bcp.parse_location('3_16-18') == (enc(3, 16), enc(3, 18))
    # cross-chapter range (the pericope John 7:53-8:11)
    assert bcp.parse_location('7_53-8_11') == (enc(7, 53), enc(8, 11))


def test_parse_location_multi_verse_block_spans_first_to_last():
    # A curator's list "20_23-24-26" is filed as one span, verses 23 through 26.
    enc = bcp.encode
    assert bcp.parse_location('20_23-24-26') == (enc(20, 23), enc(20, 26))
    assert bcp.parse_location('20_27-29-29') == (enc(20, 27), enc(20, 29))
    assert bcp.parse_location('20_35-36-38') == (enc(20, 35), enc(20, 38))


def test_author_correction_maps_theodore():
    c = bcp.AUTHOR_CORRECTIONS['Theodore Stratelates']
    assert c['author'] == 'Theodore of Heraclea'
    assert c['category'] == 'Eastern & Byzantine Theology'
