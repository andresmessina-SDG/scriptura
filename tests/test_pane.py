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
