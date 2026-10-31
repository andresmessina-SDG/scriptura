"""The note peeks and the cross-reference chips follow the reading size.

They were fixed at the interface font (the peek body 1.1em of it, ~12pt;
the chips the button size) whatever size the reader chose, 8 to 26pt. The
peek body is reading text and takes the size in full; the chips are
controls and grow by the square root above the default, never shrinking.
"""
import pytest

from styles import chip_pt, reading_size_css


def test_chips_unchanged_at_the_default_size():
    assert chip_pt(12.5, 11) == 11


def test_chips_never_shrink_below_the_interface_size():
    assert chip_pt(8, 11) == 11


def test_twice_the_text_is_root_two_the_chips():
    assert chip_pt(25, 11) == pytest.approx(11 * 2 ** 0.5)


def test_peek_body_takes_the_reading_size():
    assert '.peek-reading { font-size: 20pt; }' in reading_size_css(20, 11)


def test_a_junk_size_is_held_to_the_slider_range():
    assert '.peek-reading { font-size: 26pt; }' in reading_size_css(1e18, 11)
    assert '.peek-reading { font-size: 8pt; }' in reading_size_css(-1e18, 11)


def test_peek_width_follows_the_text_and_never_narrows():
    # At 26pt the 280px peek ran three words to a line.
    assert '.peek-reading-box { min-width: 280px; }' in reading_size_css(12.5, 11)
    assert '.peek-reading-box { min-width: 560px; }' in reading_size_css(25, 11)
    assert '.peek-reading-box { min-width: 280px; }' in reading_size_css(8, 11)
