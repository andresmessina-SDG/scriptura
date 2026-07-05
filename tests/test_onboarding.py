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
