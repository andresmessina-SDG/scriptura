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
