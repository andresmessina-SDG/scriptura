"""The heading on a place card."""
import pytest

import imagery_reader


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: the card labels are real Gtk.Labels')


def _heading(ancient, modern):
    place = {'ancient_name': ancient, 'modern_name': modern}
    return imagery_reader._place_labels(place)[0].get_label()


def test_modern_name_follows_the_bible_name(display):
    assert _heading('Sychar', 'Askar') == 'Sychar · today Askar'


def test_a_name_unchanged_today_is_said_once(display):
    assert _heading('Hauran', 'Hauran') == 'Hauran'
    # OpenBible's numeric suffix is not a different name.
    assert _heading('Samaria 2', 'Samaria') == 'Samaria'
    assert _heading('Самария', 'Самария') == 'Самария'
