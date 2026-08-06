"""The high-contrast sheet has to go on and come off exactly once each.

Attaching a provider twice leaves two copies on the display and only one comes
off again, so the app would be stuck in high contrast after the setting was
turned back off — and nothing on screen says which provider is talking. The
swap exists at all because GTK 4.22 accepts
`@media (prefers-contrast: more)` from an application provider and then
applies nothing inside it, so there is no declarative way to do this.

No display: the two provider calls are static methods, so they can be watched
directly.
"""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

import styles


class FakeManager:
    def __init__(self, high_contrast=False):
        self.high_contrast = high_contrast

    def get_high_contrast(self):
        return self.high_contrast


def _watch(monkeypatch):
    """Record every add/remove instead of touching a real display."""
    calls = []
    monkeypatch.setattr(
        Gtk.StyleContext, 'add_provider_for_display',
        lambda display, provider, priority: calls.append(
            ('add', provider, priority)))
    monkeypatch.setattr(
        Gtk.StyleContext, 'remove_provider_for_display',
        lambda display, provider: calls.append(('remove', provider)))
    monkeypatch.setattr(styles, '_hc_attached', False)
    provider = object()
    monkeypatch.setattr(styles, '_hc_provider', provider)
    return calls, provider


def test_the_sheet_goes_on_when_the_desktop_asks_for_contrast(monkeypatch):
    calls, provider = _watch(monkeypatch)
    styles._apply_high_contrast(None, FakeManager(True))
    assert calls == [('add', provider,
                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)]


def test_it_sits_one_step_above_the_base_sheet(monkeypatch):
    """.reading-page-flush is more specific than the .reading-page edge the hc
    sheet puts back, so the correction has to win on provider priority rather
    than on the selector."""
    calls, _provider = _watch(monkeypatch)
    styles._apply_high_contrast(None, FakeManager(True))
    assert calls[0][2] > Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION


def test_a_second_notification_does_not_attach_it_twice(monkeypatch):
    """Adw.StyleManager emits notify::high-contrast on a colour-scheme change
    too, so this runs more often than the setting actually changes."""
    calls, _provider = _watch(monkeypatch)
    manager = FakeManager(True)
    styles._apply_high_contrast(None, manager)
    styles._apply_high_contrast(None, manager)
    assert len(calls) == 1


def test_turning_it_off_takes_the_sheet_away(monkeypatch):
    calls, provider = _watch(monkeypatch)
    manager = FakeManager(True)
    styles._apply_high_contrast(None, manager)
    manager.high_contrast = False
    styles._apply_high_contrast(None, manager)
    assert calls[-1] == ('remove', provider)


def test_nothing_happens_when_the_sheet_never_loaded(monkeypatch):
    """A missing data/style-hc.css is logged and left alone — the app runs
    unstyled for contrast rather than not at all."""
    calls, _provider = _watch(monkeypatch)
    monkeypatch.setattr(styles, '_hc_provider', None)
    styles._apply_high_contrast(None, FakeManager(True))
    assert calls == []
