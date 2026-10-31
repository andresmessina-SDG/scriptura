"""Friction around a click on the reading text.

  * a press on the hover card closes it and lands on the text beneath; the
    card took the click and left 0.3 s later, so the click did nothing
  * no hover card for the word the lexicon below already shows
  * the other pane marks a verse already on its screen where it is, rather
    than scrolling to it on every click in this pane
  * the clicked line is kept above the bar and lexicon the click opened
  * a tap shows the hidden header only once the click has played out, and
    not at all if it opened a peek: the header slides the page's top edge,
    and that slide closed the peek the same click had just opened

Stand-ins only, the pane's own methods borrowed onto them.
"""
import types

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from pane import BiblePane  # noqa: E402
from pane_chrome import ChromeController  # noqa: E402


class _Gesture:
    def __init__(self, button):
        self.button, self.state = button, None

    def get_current_button(self):
        return self.button

    def set_state(self, state):
        self.state = state


def _gloss_pane():
    calls = []
    p = types.SimpleNamespace(calls=calls)
    p._gloss_point = lambda box, x, y: (x + 100, y + 200)
    p.dismiss_dict_peek = lambda: calls.append('dismiss')
    p._on_left_click = lambda g, n, x, y: calls.append(('left', n, x, y))
    p._on_left_release = lambda g, n, x, y: calls.append(('release', n, x, y))
    p._on_right_click = lambda g, n, x, y: calls.append(('right', n, x, y))
    return p


def test_a_left_press_on_the_card_is_a_click_on_the_text():
    p = _gloss_pane()
    g = _Gesture(Gdk.BUTTON_PRIMARY)
    BiblePane._on_gloss_pressed(p, g, 1, 5, 6, None)
    assert p.calls == ['dismiss', ('left', 1, 105, 206), ('release', 1, 105, 206)]
    assert g.state == Gtk.EventSequenceState.CLAIMED


def test_a_right_press_on_the_card_opens_the_verse_menu():
    p = _gloss_pane()
    BiblePane._on_gloss_pressed(p, _Gesture(Gdk.BUTTON_SECONDARY), 1, 5, 6, None)
    assert p.calls == ['dismiss', ('right', 1, 105, 206)]


def test_no_card_for_the_word_the_lexicon_shows(monkeypatch):
    fetched = []
    monkeypatch.setattr('tasks.submit', lambda *a, **k: fetched.append(a))
    lex = types.SimpleNamespace(get_visible=lambda: True, _current_strong='G25')
    p = types.SimpleNamespace(
        _hover_timer=1, _hover_word=(3, 8, 'G25'), _hover_preview=True,
        _hover_gloss_range=None, _peek=types.SimpleNamespace(pop=None),
        _lex_panel=lex)
    BiblePane._hover_dwell_fire(p)
    assert fetched == []
    p._hover_word = (3, 8, 'G26')
    BiblePane._hover_dwell_fire(p)
    assert len(fetched) == 1


def _follow_pane(on_screen):
    calls = []
    table = types.SimpleNamespace(lookup=lambda name: object())
    p = types.SimpleNamespace(
        calls=calls, _module='BSB', _book='John', _chapter=3,
        _buffer=types.SimpleNamespace(get_tag_table=lambda: table),
        _set_current_verse_indicator=lambda v: None,
        _cursor=types.SimpleNamespace(sync_to=lambda v: None),
        _verse_on_screen=lambda v: on_screen,
        _scroll_to_verse=lambda v: calls.append(('scroll', v)),
        _flash_verse_deferred=lambda v: calls.append(('flash', v)))
    return p


def test_a_verse_on_screen_is_marked_where_it_is(monkeypatch):
    monkeypatch.setattr(GLib, 'timeout_add', lambda ms, f, *a: f(*a))
    p = _follow_pane(on_screen=True)
    BiblePane._broadcast_verse_to_text(p, 5)
    assert p.calls == [('flash', 5)]


def test_a_verse_off_screen_is_scrolled_to():
    p = _follow_pane(on_screen=False)
    BiblePane._broadcast_verse_to_text(p, 5)
    assert p.calls == [('scroll', 5)]


class _Adj:
    def __init__(self):
        self.value = 100.0

    def get_value(self):
        return self.value

    def set_value(self, v):
        self.value = v

    def get_upper(self):
        return 5000.0

    def get_page_size(self):
        return 480.0


def _keep_pane(line_bottom_in_view, view_h=480, peek_open=False):
    """A pane whose clicked line ends `line_bottom_in_view` px down the view."""
    buf = Gtk.TextBuffer()
    buf.set_text('In the beginning')
    mark = buf.create_mark(None, buf.get_start_iter(), True)
    adj = _Adj()
    loc = Gdk.Rectangle()
    loc.x, loc.y, loc.width, loc.height = 0, 0, 10, 20
    view = types.SimpleNamespace(
        get_mapped=lambda: True, get_height=lambda: view_h,
        get_iter_location=lambda it: loc,
        buffer_to_window_coords=lambda _w, x, y: (x, line_bottom_in_view - 20 + y),
        get_vadjustment=lambda: adj)
    pop = types.SimpleNamespace(get_visible=lambda: peek_open)
    p = types.SimpleNamespace(
        _keep_timer=1, _keep_mark=mark, _buffer=buf, _view=view,
        _peek=types.SimpleNamespace(pop=pop), moved=[],
        _mark_programmatic_scroll=lambda ms=0: None,
        _schedule_anchor_capture=lambda *a: None)
    return p, adj


def test_a_covered_line_is_lifted_just_clear(monkeypatch):
    anims = []

    class _Anim:
        @staticmethod
        def new(_w, a, b, _ms, target):
            anims.append((a, b, target))
            return types.SimpleNamespace(set_easing=lambda e: None,
                                         connect=lambda *a: None,
                                         play=lambda: None)
    monkeypatch.setattr('pane.Adw.TimedAnimation', _Anim)
    monkeypatch.setattr('pane.Adw.CallbackAnimationTarget',
                        types.SimpleNamespace(new=lambda f: f))
    p, adj = _keep_pane(line_bottom_in_view=530)
    BiblePane._keep_click_fire(p)
    # 530 - (480 - 12) = 62px further down.
    (a, b, frame), = anims
    assert (a, b) == (0.0, 62.0)
    frame(31.0)
    # The header reveal slides the page 40px in the same moment; the lift
    # adds to that rather than overwriting it.
    adj.value += 40
    frame(62.0)
    assert adj.value == 202.0


def test_a_visible_line_stays_put(monkeypatch):
    monkeypatch.setattr('pane.Adw.TimedAnimation', None)
    p, adj = _keep_pane(line_bottom_in_view=300)
    BiblePane._keep_click_fire(p)
    assert adj.value == 100.0


def test_an_open_peek_is_not_moved_out_from_under(monkeypatch):
    monkeypatch.setattr('pane.Adw.TimedAnimation', None)
    p, adj = _keep_pane(line_bottom_in_view=530, peek_open=True)
    BiblePane._keep_click_fire(p)
    assert adj.value == 100.0


def _tap_pane(peek_open):
    revealed = []
    pop = types.SimpleNamespace(get_visible=lambda: peek_open)
    return types.SimpleNamespace(
        _tap_reveal_timer=0, _peek=types.SimpleNamespace(pop=pop),
        _reveal_chrome=lambda: revealed.append(True),
        _on_click_outside_search=None,
        _click_settle_ms=lambda: 450,
        _tap_reveal_fire=lambda: None), revealed


def test_a_tap_shows_the_header_after_the_click(monkeypatch):
    timers = []
    monkeypatch.setattr('pane.GLib.timeout_add',
                        lambda ms, fn: timers.append((ms, fn)) or 7)
    p, revealed = _tap_pane(peek_open=False)
    BiblePane._on_pane_click(p, None, 1, 0, 0)
    assert revealed == [] and p._tap_reveal_timer == 7
    (ms, fn), = timers
    assert ms == 450
    BiblePane._tap_reveal_fire(p)
    assert revealed == [True] and p._tap_reveal_timer == 0


def test_a_tap_that_opened_a_peek_leaves_the_header_hidden():
    p, revealed = _tap_pane(peek_open=True)
    BiblePane._tap_reveal_fire(p)
    assert revealed == []


def test_a_sliding_header_lands_before_a_peek_is_placed():
    skipped = []
    c = ChromeController.__new__(ChromeController)
    c._anim = types.SimpleNamespace(skip=lambda: skipped.append(True))
    c.finish()
    assert skipped == [True]
    c._anim = None
    c.finish()
    assert skipped == [True]
