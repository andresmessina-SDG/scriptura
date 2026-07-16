"""Tests for the small pure helpers on BiblePane that don't need a live
widget tree. _resolve_present_verse is called via the class on a stand-in
`self` so we don't have to construct GTK objects."""

from pane import BiblePane


def _resolve(present, target):
    obj = type('Stub', (), {})()
    obj._present_verses = present
    return BiblePane._resolve_present_verse(obj, target)


def test_resolve_present_verse_exact_match():
    assert _resolve([1, 2, 3], 2) == 2


def test_resolve_present_verse_bridge_inner_falls_back():
    # \v 1-2 stores text under verse 1 only; a jump to 2 lands on 1.
    assert _resolve([1, 3, 4], 2) == 1


def test_resolve_present_verse_no_earlier_returns_request():
    # Nothing before the target — leave it unchanged (caller no-ops).
    assert _resolve([5, 6], 2) == 2


def test_resolve_present_verse_unset_returns_request():
    obj = type('Stub', (), {})()
    assert BiblePane._resolve_present_verse(obj, 7) == 7


# ── _printable_ratio (wrong-cipher-key detection) ─────────────────────────────

from pane import _printable_ratio


def test_printable_ratio_plain_english():
    assert _printable_ratio('For God so loved the world') == 1.0


def test_printable_ratio_greek_and_hebrew_are_printable():
    # Valid non-Latin scripts must not be flagged as gibberish.
    assert _printable_ratio('Ἐν ἀρχῇ ἦν ὁ λόγος') > 0.95
    assert _printable_ratio('בְּרֵאשִׁית בָּרָא אֱלֹהִים') > 0.95


def test_printable_ratio_garbage_drops_below_threshold():
    garbage = ''.join(chr(c) for c in range(0, 32)) * 3 + '�' * 20
    assert _printable_ratio(garbage) < 0.6


def test_printable_ratio_empty_is_one():
    assert _printable_ratio('') == 1.0


# ── _is_bad_cipher (wrong-key decision) ───────────────────────────────────────

from pane import _is_bad_cipher


def test_bad_cipher_compressed_empty_but_in_index():
    # Compressed module, wrong key: decompression fails -> empty, but the
    # verses exist in the index. That's a bad key, not a coverage gap.
    assert _is_bad_cipher(all_empty=True, chapter_in_index=True, ratio=1.0) is True


def test_bad_cipher_coverage_gap_not_flagged():
    # Empty and not in the index -> genuine coverage gap.
    assert _is_bad_cipher(all_empty=True, chapter_in_index=False, ratio=1.0) is False


def test_bad_cipher_uncompressed_gibberish():
    assert _is_bad_cipher(all_empty=False, chapter_in_index=False, ratio=0.5) is True


def test_bad_cipher_readable_content_ok():
    assert _is_bad_cipher(all_empty=False, chapter_in_index=False, ratio=0.98) is False


def test_bad_cipher_ratio_boundary():
    # Threshold is < 0.6 (exclusive).
    assert _is_bad_cipher(False, False, 0.59) is True
    assert _is_bad_cipher(False, False, 0.60) is False


# ── footnote marker labels ────────────────────────────────────────────────────

from pane import _fn_label, _substitute_footnote_markers


def test_fn_label_full_alphabet_including_q():
    labels = [_fn_label(i) for i in range(26)]
    assert labels == list('abcdefghijklmnopqrstuvwxyz')


def test_fn_label_wraps_bijective_base26():
    assert _fn_label(26) == 'aa'
    assert _fn_label(27) == 'ab'
    assert _fn_label(51) == 'az'
    assert _fn_label(52) == 'ba'
    # No collisions across a note-heavy chapter's worth of markers.
    labels = [_fn_label(i) for i in range(120)]
    assert len(set(labels)) == len(labels)


def test_substitute_markers_offsets_and_multichar_labels():
    vnotes = {str(n): ('', f'note {n}') for n in range(1, 30)}
    markup = ''.join(f'v{n}[[FN_{n}]] ' for n in range(1, 30))
    out, markers, nxt = _substitute_footnote_markers(markup, vnotes, False)
    assert nxt == 29
    assert '[[FN_' not in out
    # Rebuild the inserted plain text the way the buffer sees it and check
    # each recorded offset lands exactly on its label.
    import re as _re
    plain = _re.sub(r'<[^>]+>', '', out)
    for off, n, label in markers:
        assert plain[off:off + len(label)] == label
    # 27th and later markers wrap into two-char labels.
    assert markers[26][2] == 'aa'


def test_substitute_markers_skips_tokens_without_bodies():
    out, markers, nxt = _substitute_footnote_markers(
        'word[[FN_1]] tail[[FN_2]]', {'2': ('', 'only note two')}, False)
    assert nxt == 1
    assert len(markers) == 1
    assert markers[0][1] == '2'
    assert markers[0][2] == 'a'


# ── _gloss_from_strong_entry (hover-preview card text) ───────────────────

def test_gloss_strips_number_and_usage_list():
    raw = ("7462 ra`ah raw-aw' a primitive root; to tend a flock; i.e. "
           "pasture it; generally to rule:--X break, companion, keep "
           "company with, devour, eat up, pastor, + shearing house")
    from pane import _gloss_from_strong_entry
    g = _gloss_from_strong_entry(raw)
    assert g.startswith("ra`ah")          # caption already has the number
    assert ':--' not in g and 'shearing' not in g
    assert g.endswith('rule.')


def test_gloss_keeps_lemma_led_entries_and_caps():
    from pane import _gloss_from_strong_entry
    raw = 'ἀγάπη , -ης, ἡ love, goodwill, esteem. ' + 'scholarly note ' * 60
    g = _gloss_from_strong_entry(raw)
    assert g.startswith('ἀγάπη')
    assert len(g) <= 361 and g.endswith('…')


def test_gloss_short_usage_head_keeps_full_text():
    # A tiny head ('of Hebrew origin') is no glance — keep the whole entry.
    from pane import _gloss_from_strong_entry
    g = _gloss_from_strong_entry('3 of Hebrew origin:--Abaddon')
    assert g == 'of Hebrew origin:--Abaddon'


def test_gloss_empty_entry_gives_empty():
    from pane import _gloss_from_strong_entry
    assert _gloss_from_strong_entry(None) == ''
    assert _gloss_from_strong_entry('<b></b>') == ''
