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


@pytest.mark.parametrize('stored, expect', [
    ((1100, 700), (1100, 700)), ((320, 200), (320, 200)),
    ((-5, 700), (1100, 700)), ((900, 0), (1100, 700)), ((0, 0), (1100, 700)),
])
def test_a_window_size_below_one_pixel_means_the_default(monkeypatch, stored, expect):
    """The app writes the size it measured; a hand-edited file can hold -5,
    and gtk_window_set_default_size asserts on it."""
    import settings
    from window import stored_window_size
    monkeypatch.setattr(settings, 'get', lambda key: dict(
        window_width=stored[0], window_height=stored[1])[key])
    assert stored_window_size() == expect
