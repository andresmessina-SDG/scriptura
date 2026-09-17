"""A stored paper colour that is not one is no paper.

settings.json is written by the app in `#rrggbb` only, but a file edited by
hand can hold anything, and `is_dark_paper('Paper')` raised while the window
was being built: the app would not open until the file was fixed.
"""
import pytest

from pane import auto_reading_ink, valid_paper


@pytest.mark.parametrize('value', ['#f7f4ee', '#FBFBFB', '#000000'])
def test_a_colour_is_kept(value):
    assert valid_paper(value) == value


@pytest.mark.parametrize('value', ['Paper', '', None, '#fff', '#f7f4eez',
                                   'f7f4ee', 3, ['#f7f4ee']])
def test_anything_else_is_no_paper(value):
    assert valid_paper(value) is None


def test_the_ink_is_derived_from_a_checked_paper():
    assert auto_reading_ink(valid_paper('Paper') or '#f7f4ee') == \
        auto_reading_ink('#f7f4ee')
