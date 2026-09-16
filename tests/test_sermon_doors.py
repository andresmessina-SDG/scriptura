"""What each collecting door actually puts into a manuscript.

The doors themselves are menu rows on a live pane; what is worth holding is
the TEXT each one lands, because that is what a reader is left with in the
middle of their own prose — and the anchor beside it, without which a sermon
quotes a passage it is invisible at.
"""
import pytest

import annotation_dialogs
import annotations
import sermons


@pytest.fixture
def display():
    from gi.repository import Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display')


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'annotations.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(annotations, '_verse_map_cache', {})
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 'sermons.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    return tmp_path


class _Pane:
    """The three fields `collected_quote` reads off a pane."""

    def __init__(self, module='KJVA', book='Matthew', chapter=13):
        self.module = module
        self.book = book
        self.chapter = chapter


@pytest.fixture
def chapter(monkeypatch):
    """One chapter of rendered verses, as `content.load_chapter` returns
    them — markup included, because stripping it is part of the job."""
    monkeypatch.setattr(
        annotation_dialogs.content, 'load_chapter',
        lambda module, book, ch: [
            (3, '<w>Behold</w>, a sower went forth to sow;'),
            (4, 'And when he sowed, some seeds fell by the way side'),
        ])


# ── The verse door ──────────────────────────────────────────────────────────

def test_a_collected_verse_is_a_quote_and_a_reference(isolated, chapter):
    text, anchor = annotation_dialogs.collected_quote(_Pane(), [3])
    assert text == '> Behold, a sower went forth to sow; — Matthew 13:3'
    assert anchor == {'book': 'Matthew', 'chapter': 13, 'verses': [3]}


def test_collected_verses_run_together_under_one_reference(isolated, chapter):
    text, anchor = annotation_dialogs.collected_quote(_Pane(), [3, 4])
    assert text.endswith('— Matthew 13:3–4')
    assert 'way side' in text
    assert anchor['verses'] == [3, 4]


def test_a_verse_the_module_cannot_render_still_collects_its_reference(
        isolated, chapter):
    text, _anchor = annotation_dialogs.collected_quote(_Pane(), [99])
    assert text == 'Matthew 13:99'


def test_the_anchor_is_app_space(isolated, chapter, monkeypatch):
    """The pane speaks its module's numbering; an anchor holds the app's.
    A Synodal psalter's verse 1 is app verse 0, and a sermon anchored to the
    module's number would sit on the line above."""
    monkeypatch.setattr(annotations, 'app_verse',
                        lambda module, book, ch, v: v - 1)
    _text, anchor = annotation_dialogs.collected_quote(_Pane(), [3])
    assert anchor['verses'] == [2]


# ── The lexicon door ────────────────────────────────────────────────────────

def _lexicon(display):
    import lexicon_panel
    return lexicon_panel.LexiconPanel()


def test_the_lexicon_collects_a_gloss_not_the_article(isolated, display):
    panel = _lexicon(display)
    panel._current_strong = 'G4687'
    panel._def_buf.set_text(
        'σπείρω speirō\n'
        'to sow, scatter seed. Of the word of God, Mk 4:14. '
        'Metaphorically, of sowing to the Spirit, Gal 6:8.')
    assert panel.collected_gloss() == (
        'σπείρω speirō (G4687) — to sow, scatter seed')


def test_a_one_line_entry_collects_as_itself(isolated, display):
    panel = _lexicon(display)
    panel._current_strong = 'H3068'
    panel._def_buf.set_text('יְהֹוָה Yehovah')
    assert panel.collected_gloss() == 'יְהֹוָה Yehovah (H3068)'


def test_an_empty_lexicon_collects_nothing(isolated, display):
    panel = _lexicon(display)
    panel._def_buf.set_text('')
    assert panel.collected_gloss() == ''


def test_the_lexicon_offers_the_door_only_when_a_sermon_exists(isolated,
                                                              display):
    panel = _lexicon(display)
    panel._sync_collect_button(True)
    assert not panel._collect_btn.get_visible()
    sermons.save('s1', title='The Sower Went Forth')
    panel._sync_collect_button(True)
    assert panel._collect_btn.get_visible()
    assert 'Sower' in panel._collect_btn.get_tooltip_text()


def test_the_lexicon_offers_no_door_with_no_entry_on_screen(isolated,
                                                            display):
    sermons.save('s1', title='The Sower Went Forth')
    panel = _lexicon(display)
    panel._sync_collect_button(False)
    assert not panel._collect_btn.get_visible()


# ── The target ──────────────────────────────────────────────────────────────

def test_every_door_aims_at_the_sermon_last_written_in(isolated):
    """Named in the row, so it can never be wrong about where the words
    went — and not a pin, which is one more thing to get out of sync."""
    sermons.save('s1', title='The Sower Went Forth')
    sermons.save('s2', title='The Least of All Seeds')
    assert sermons.most_recent()['title'] == 'The Least of All Seeds'
    sermons.save('s1', title='The Sower Went Forth', body='more')
    assert sermons.most_recent()['title'] == 'The Sower Went Forth'
