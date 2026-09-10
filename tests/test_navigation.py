"""Back/forward history logic of NavigationController (no GTK, no settings).

_go_to is stubbed so these exercise only the stack bookkeeping — the part
most likely to regress in the BibleWindow extraction (STRUCTURAL Step 4)."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import navigation


class _Btn:
    def __init__(self):
        self.sensitive = None

    def set_sensitive(self, v):
        self.sensitive = v


def _make():
    win = types.SimpleNamespace(_back_btn=_Btn(), _fwd_btn=_Btn())
    nav = navigation.NavigationController(win)
    calls = []
    nav._go_to = lambda *a, **k: calls.append((a, k))  # stub the funnel
    return nav, calls


def test_push_nav_back_caps_at_nav_max():
    nav, _ = _make()
    for i in range(nav._NAV_MAX + 25):
        nav._push_nav_back(('Genesis', i))
    assert len(nav._nav_back) == nav._NAV_MAX
    # Oldest entries fall off the front; the newest is kept.
    assert nav._nav_back[-1] == ('Genesis', nav._NAV_MAX + 24)


def test_back_then_forward_round_trips():
    nav, calls = _make()
    nav._current_loc = ('John', 3)
    nav._nav_back = [('Genesis', 1), ('Exodus', 2)]

    nav._on_nav_back(None)
    # Popped Exodus 2; John 3 pushed onto forward; navigated there (no record).
    assert calls[-1] == (('Exodus', 2), {'record': False})
    assert nav._nav_fwd == [('John', 3)]
    assert nav._nav_back == [('Genesis', 1)]

    nav._current_loc = ('Exodus', 2)  # _go_to was stubbed, so set it by hand
    nav._on_nav_fwd(None)
    assert calls[-1] == (('John', 3), {'record': False})
    assert nav._nav_fwd == []
    assert nav._nav_back == [('Genesis', 1), ('Exodus', 2)]


def test_nav_back_noop_on_empty_stack():
    nav, calls = _make()
    nav._nav_back = []
    nav._on_nav_back(None)
    assert calls == []


def test_update_nav_btns_reflects_stack_state():
    nav, _ = _make()
    nav._nav_back = [('Genesis', 1)]
    nav._nav_fwd = []
    nav._update_nav_btns()
    assert nav._back_btn.sensitive is True
    assert nav._fwd_btn.sensitive is False


# ── Refused navigation says why ─────────────────────────────────────────────
# Every non-nav caller funnels through _go_to too — a Scripture in Stone
# link to 2 Maccabees, a Strong's or cross-reference link, a search result
# from another module, a bookmark. On a 66-book library those all returned
# in silence, which reads as a dead button.

def _make_refusable(holder=None, appendix=True):
    """A controller whose book lookup is under the test's control."""
    win = types.SimpleNamespace(_back_btn=_Btn(), _fwd_btn=_Btn(),
                                _today_suppress=False, toasts=[])
    win._toast = win.toasts.append
    nav = navigation.NavigationController(win)
    nav._book_module = lambda book: holder
    nav.nav_books = lambda: (['Genesis', 'John'] +
                             (['2 Maccabees'] if appendix else []))
    return nav, win


def test_a_book_no_open_module_carries_says_so():
    nav, win = _make_refusable(holder=None)
    nav._go_to('2 Maccabees', 3, 7)
    assert win.toasts == ['2 Maccabees isn’t in this translation.']


def test_an_unlisted_book_says_so_too():
    """No open module carries any appendix book, so it is off the list
    as well as unanswerable — one message covers both."""
    nav, win = _make_refusable(holder=None, appendix=False)
    nav._go_to('2 Maccabees', 3, 7)
    assert len(win.toasts) == 1


def test_the_startup_devotional_auto_nav_stays_quiet():
    """It moves pane 1 beneath the Today page; the reader asked for
    nothing and must not be told a book is missing."""
    nav, win = _make_refusable(holder=None)
    win._today_suppress = True
    nav._go_to('2 Maccabees', 3, 7)
    assert win.toasts == []


def test_a_navigation_that_lands_does_not_toast():
    nav, win = _make_refusable(holder='KJVA')
    nav._sync_nav_books = lambda: None
    nav._update_ref_label = lambda *a: None
    nav._push_recent = lambda *a: None
    win._dismiss_today = lambda: None
    nav._update_nav_btns = lambda: None
    win.book_drop = types.SimpleNamespace(set_selected=lambda i: None)
    win.chapter_drop = types.SimpleNamespace(set_model=lambda m: None,
                                             set_selected=lambda i: None)
    win.pane1 = win.pane2 = types.SimpleNamespace(
        load_reference=lambda *a: None, load_reference_at_verse=lambda *a: None)
    nav._open_panes = lambda: []
    import sword_bridge
    orig = sword_bridge.chapter_count_in
    sword_bridge.chapter_count_in = lambda m, b: 15
    try:
        nav._go_to('2 Maccabees', 3, 7)
    finally:
        sword_bridge.chapter_count_in = orig
    assert win.toasts == []
    assert nav._current_loc == ('2 Maccabees', 3)
