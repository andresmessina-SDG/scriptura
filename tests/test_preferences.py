"""The Preferences dialog: three pages, and the sense-unit rows join the
window's availability check only while the dialog is open."""

import types

import pytest

import preferences


@pytest.fixture
def win(monkeypatch):
    """`Gdk.Display.get_default()`, never `Gtk.init_check()` alone — the
    latter returns True with no display and building widgets then
    segfaults."""
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: builds real widgets')
    Adw.init()
    monkeypatch.setattr(preferences.night_light, 'probe', lambda cb: cb(True))
    nothing = lambda *_a, **_k: None  # noqa: E731
    w = types.SimpleNamespace(
        _section_rows=[], refreshed=[],
        _on_backup_clicked=nothing, _on_restore_clicked=nothing,
        _on_daily_copies_clicked=nothing, _set_church_calendar=nothing,
        _on_language_selected=nothing)
    w._refresh_section_rows = lambda: w.refreshed.append(len(w._section_rows))
    return w


def test_three_pages(win, monkeypatch):
    from gi.repository import Adw
    added = []
    monkeypatch.setattr(Adw.PreferencesDialog, 'add',
                        lambda self, page: added.append(page.get_title()))
    preferences.build(win)
    assert added == ['General', 'Reading Aids', 'Study Data']


def test_sense_unit_rows_are_checked_while_open_and_dropped_on_close(win):
    d = preferences.build(win)
    assert len(win._section_rows) == 2
    assert win.refreshed == [2], 'availability is asked as the dialog opens'
    d.emit('closed')
    assert win._section_rows == []


def test_an_unavailable_row_says_why_in_its_subtitle(win):
    preferences.build(win)
    row, note = win._section_rows[0]
    note.set_visible(True)
    assert row.get_subtitle() == 'This translation marks no sections'
    note.set_visible(False)
    assert row.get_subtitle() == ''
