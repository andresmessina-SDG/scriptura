"""Tests for onboarding.HintController — the fire-once contextual-hint logic.
Pure-Python (the GTK present callback is injected), so no display needed.
Settings are isolated the same way as test_settings.py: monkeypatch the
module globals, never env vars (paths bind at import)."""

import pytest

import settings
import onboarding


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    if settings._save_timer is not None:
        settings._save_timer.cancel()
    monkeypatch.setattr(settings, '_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(settings, '_cache', None)
    monkeypatch.setattr(settings, '_load_failed', False)
    monkeypatch.setattr(settings, '_save_timer', None)
    yield tmp_path
    if settings._save_timer is not None:
        settings._save_timer.cancel()


def _controller():
    """A controller that records every message it presents."""
    shown: list[str] = []
    return onboarding.HintController(shown.append), shown


# ── Fire-once ────────────────────────────────────────────────────────────────

def test_first_call_fires(isolated):
    ctrl, shown = _controller()
    assert ctrl.maybe_fire('first_render') is True
    assert len(shown) == 1


def test_second_call_does_not_fire(isolated):
    ctrl, shown = _controller()
    ctrl.maybe_fire('first_render')
    assert ctrl.maybe_fire('first_render') is False
    assert len(shown) == 1


def test_distinct_keys_fire_independently(isolated):
    ctrl, shown = _controller()
    assert ctrl.maybe_fire('first_render') is True
    assert ctrl.maybe_fire('first_verse_click') is True
    assert ctrl.maybe_fire('first_lexicon') is True
    assert len(shown) == 3


def test_seen_persists_across_controllers(isolated):
    """A hint shown in one session must not fire in the next — the guard
    lives in settings, not the controller instance."""
    ctrl1, _ = _controller()
    ctrl1.maybe_fire('first_render')
    ctrl2, shown2 = _controller()
    assert ctrl2.maybe_fire('first_render') is False
    assert shown2 == []


def test_fired_key_recorded_in_settings(isolated):
    ctrl, _ = _controller()
    ctrl.maybe_fire('first_render')
    assert 'first_render' in settings.get('hints_seen')


# ── Master switch ────────────────────────────────────────────────────────────

def test_disabled_never_fires(isolated):
    settings.put('tips_enabled', False)
    ctrl, shown = _controller()
    assert ctrl.maybe_fire('first_render') is False
    assert shown == []


def test_disabled_does_not_consume_the_hint(isolated):
    """A hint suppressed because tips are off must still be available if the
    user turns tips back on — don't mark it seen when it never showed."""
    settings.put('tips_enabled', False)
    ctrl, _ = _controller()
    ctrl.maybe_fire('first_render')
    assert 'first_render' not in (settings.get('hints_seen') or [])
    settings.put('tips_enabled', True)
    assert ctrl.maybe_fire('first_render') is True


# ── Unknown keys ─────────────────────────────────────────────────────────────

def test_unknown_key_never_fires(isolated):
    ctrl, shown = _controller()
    assert ctrl.maybe_fire('not_a_hint') is False
    assert shown == []


def test_enabled_by_default(isolated):
    assert onboarding.HintController.enabled() is True


# ── The lexicon hint only fires where tapping pays off ───────────────────────

def test_lexicon_hint_is_silent_without_strongs(isolated, monkeypatch):
    """"Tap any word" fires once ever. A reader whose Bibles carry no
    Strong's — NBLA and LBLA, the Spanish bundle's own opening pair —
    would spend that one firing on a pane where tapping does nothing."""
    import content
    import window

    ctrl, shown = _controller()
    monkeypatch.setattr(content, 'has_strongs', lambda name: name == 'KJV')

    class _Pane:
        def __init__(self, module, visible=True):
            self._module = module
            self._visible = visible

        def get_visible(self):
            return self._visible

        def set_lexicon_enabled(self, on):
            pass

    def fire(p1, p2):
        win = window.BibleWindow.__new__(window.BibleWindow)
        win.pane1, win.pane2 = p1, p2
        win._hints = ctrl
        win.lex_toggle = type('T', (), {'get_active': lambda self: True})()
        window.BibleWindow._on_lex_toggle(win, None)
        return len(shown)

    # Neither pane tagged: silent.
    assert fire(_Pane('NBLA'), _Pane('LBLA')) == 0
    # Pane 2 tagged and visible: word study works there, so the hint earns
    # its one firing.
    assert fire(_Pane('NBLA'), _Pane('KJV')) == 1


def test_lexicon_hint_ignores_a_hidden_second_pane(isolated, monkeypatch):
    """A closed split is not a place the reader can tap."""
    import content
    import window

    ctrl, shown = _controller()
    monkeypatch.setattr(content, 'has_strongs', lambda name: name == 'KJV')

    class _Pane:
        def __init__(self, module, visible=True):
            self._module, self._visible = module, visible

        def get_visible(self):
            return self._visible

        def set_lexicon_enabled(self, on):
            pass

    win = window.BibleWindow.__new__(window.BibleWindow)
    win.pane1, win.pane2 = _Pane('NBLA'), _Pane('KJV', visible=False)
    win._hints = ctrl
    win.lex_toggle = type('T', (), {'get_active': lambda self: True})()
    window.BibleWindow._on_lex_toggle(win, None)
    assert shown == []


# ── The welcome window's language picker and the install ────────────────────

def test_the_language_picker_locks_once_an_install_starts(monkeypatch):
    """Switching language rebuilds the window — which, mid-install, threw
    the reader back to the chooser with the download still running and free
    to start a second one. Once a bundle is chosen the language choice is
    spent: the window hands off to the reading window as soon as it lands."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Gdk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('builds real widgets; no display here')

    import threading
    import i18n
    import welcome

    # A source checkout has no compiled catalogues, so only English is on
    # offer and the picker is (rightly) not built at all. Give it two.
    monkeypatch.setattr(i18n, 'available_languages',
                        lambda: [('en', 'English'), ('es', 'Español')])
    monkeypatch.setattr(threading, 'Thread',
                        lambda *a, **k: type('T', (), {'start': lambda s: None})())
    win = welcome.WelcomeWindow(on_ready=lambda *a: None)
    # The picker is the first page now, and the way back to it is the arrow
    # in the bar — so that is what must not be live mid-download. Changing
    # language then would swap the catalogue under the worker thread and
    # leave half of one library beside half of another.
    assert win._back_to_lang.get_sensitive()

    win._on_card_clicked(None, 'reading')
    assert win._stack.get_visible_child_name() == 'progress'
    assert not win._back_to_lang.get_sensitive(), \
        'the way back stayed live mid-install'

    win._on_back(None)
    assert win._back_to_lang.get_sensitive(), \
        'the way back stayed locked after Back'


def test_a_rebuild_leaves_the_reader_on_the_page_they_were_on(monkeypatch):
    """Belt and braces for the same defect: a stack rebuilt from scratch
    shows its first page unless told otherwise."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Gdk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('builds real widgets; no display here')

    import welcome

    win = welcome.WelcomeWindow(on_ready=lambda *a: None)
    win._stack.set_visible_child_name('progress')
    win._rebuild()
    assert win._stack.get_visible_child_name() == 'progress'
