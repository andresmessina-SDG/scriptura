"""OverlayManager logic: jump parsing + overlay mutual-exclusion (no real UI).

_parse_jump is pure (BOOKS + versification); _close_other_overlays is exercised
against fake split/revealer widgets that record their visibility calls."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import overlays


class _Split:
    def __init__(self):
        self.shown = None

    def set_show_sidebar(self, v):
        self.shown = v


class _Revealer:
    def __init__(self):
        self.revealed = None

    def set_reveal_child(self, v):
        self.revealed = v


def _mgr():
    win = types.SimpleNamespace(
        _menu_split=_Split(), _search_split=_Split(),
        _jump_revealer=_Revealer())
    return overlays.OverlayManager(win)


def test_close_other_overlays_keeps_only_the_named_one():
    m = _mgr()
    m._close_other_overlays(keep='search')
    assert m._win._menu_split.shown is False
    assert m._win._jump_revealer.revealed is False
    assert m._win._search_split.shown is None  # untouched — it's the kept one


def test_close_other_overlays_none_closes_all_three():
    m = _mgr()
    m._close_other_overlays()
    assert m._win._menu_split.shown is False
    assert m._win._search_split.shown is False
    assert m._win._jump_revealer.revealed is False


def test_parse_jump_exact_beats_prefix():
    m = _mgr()
    # "Job" must not silently become "Joshua".
    assert m._parse_jump('Job')[0] == 'Job'
    assert m._parse_jump('Job 5')[:2] == ('Job', 5)


def test_parse_jump_chapter_and_verse():
    m = _mgr()
    assert m._parse_jump('John 3:16') == ('John', 3, 16)
    assert m._parse_jump('John 3')[2] is None


def test_parse_jump_prefix_and_clamp():
    m = _mgr()
    # Prefix match; chapter beyond the book clamps to its last.
    assert m._parse_jump('Gen')[0] == 'Genesis'
    b, ch, _v = m._parse_jump('Genesis 999')
    assert b == 'Genesis' and ch == 50


def test_parse_jump_rejects_junk():
    m = _mgr()
    assert m._parse_jump('') is None
    assert m._parse_jump('Zzznotabook') is None


# ── Reading mode ─────────────────────────────────────────────────────────────

class _Vis:
    def __init__(self, v=True):
        self.visible = v

    def set_visible(self, v):
        self.visible = v


class _Reveal:
    def __init__(self, revealed=False):
        self.revealed = revealed

    def set_reveal_child(self, v):
        self.revealed = v

    def get_reveal_child(self):
        return self.revealed

    def set_show_sidebar(self, v):
        self.revealed = v


class _Pane:
    def __init__(self):
        self._toolbar = _Vis()
        self.strips = 0

    def _animate_page_strip(self):
        self.strips += 1


def _reading_mgr():
    calls = []
    win = types.SimpleNamespace(
        _header=_Vis(), pane1=_Pane(), pane2=_Pane(),
        _menu_split=_Reveal(), _search_split=_Reveal(),
        _jump_revealer=_Reveal(), _crossref_revealer=_Reveal(),
        _exit_reading_revealer=_Reveal(), _present_mode=False,
        _dismiss_today=lambda: calls.append('dismiss_today'),
        _toast=lambda msg: calls.append(('toast', msg)),
        _present_update_controls=lambda y: calls.append(('present_ctrl', y)),
        _set_present_mode=lambda on: calls.append(('present_mode', on)))
    return overlays.OverlayManager(win), calls


def test_set_reading_mode_on_hides_chrome_and_overlays():
    m, calls = _reading_mgr()
    m._set_reading_mode(True)
    assert m._reading_mode is True
    assert m._win._header.visible is False
    assert m._win.pane1._toolbar.visible is False
    assert m._win.pane2._toolbar.visible is False
    assert m._win.pane1.strips == 1 and m._win.pane2.strips == 1
    # Floating panels dismissed; entering is "an action" so Today goes too.
    assert m._win._menu_split.revealed is False
    assert m._win._crossref_revealer.revealed is False
    assert 'dismiss_today' in calls
    assert any(c[0] == 'toast' for c in calls if isinstance(c, tuple))


def test_set_reading_mode_off_restores_header():
    m, _ = _reading_mgr()
    m._set_reading_mode(True)
    m._set_reading_mode(False, toast=False)
    assert m._reading_mode is False
    assert m._win._header.visible is True


def test_reading_motion_noop_when_not_in_reading_mode():
    m, _ = _reading_mgr()
    m._on_reading_mouse_motion(None, 0, 5)
    assert m._reading_hover_timer is None


def test_reading_motion_arms_timer_in_trigger_zone(monkeypatch):
    m, _ = _reading_mgr()
    m._reading_mode = True
    monkeypatch.setattr(overlays.GLib, 'timeout_add', lambda ms, fn: 4242)
    m._on_reading_mouse_motion(None, 0, m._READING_TRIGGER_ZONE_PX - 1)
    assert m._reading_hover_timer == 4242


def test_reading_motion_routes_to_present_controls_when_presenting():
    m, calls = _reading_mgr()
    m._reading_mode = True
    m._win._present_mode = True
    m._on_reading_mouse_motion(None, 0, 300)
    assert ('present_ctrl', 300) in calls
