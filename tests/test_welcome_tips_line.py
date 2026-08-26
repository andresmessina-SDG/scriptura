"""The welcome window's one line pointing at the gesture reference.

Inside the app that reference has two routes, and a newcomer may meet
neither: an unlabelled icon in the menu footer, and a button on a hint that
fires once and never again. The welcome window is the one place a newcomer
is certain to read, so it carries a line naming the dialog.

Real widgets, so a display is needed: building GTK widgets without one
segfaults inside GTK rather than failing, and Gdk.Display.get_default is the
only call that reports which you have. Nothing here is ever presented — the
window is constructed and walked, never shown.
"""

import pytest

import welcome


def _walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _window(monkeypatch):
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    # A card click would otherwise start a real download thread.
    monkeypatch.setattr(welcome.WelcomeWindow, '_install_worker',
                        lambda self, bundle: None)
    return welcome.WelcomeWindow(on_ready=lambda: None)


def _text(widget):
    """All label text under `widget`, including its own — the button carries
    an icon beside its label, so the text is a child, not `get_label()`."""
    from gi.repository import Gtk
    own = widget.get_label() if isinstance(widget, Gtk.Button) else None
    return ' '.join([own or ''] + [w.get_text() for w in _walk(widget)
                                   if isinstance(w, Gtk.Label)])


def _tips_buttons(root):
    from gi.repository import Gtk
    return [w for w in _walk(root)
            if isinstance(w, Gtk.Button) and 'Tips' in _text(w)]


def test_the_chooser_offers_one_route_to_the_reference(monkeypatch):
    assert len(_tips_buttons(_window(monkeypatch))) == 1


def test_the_line_names_the_dialog_so_it_can_be_found_again(monkeypatch):
    # Naming it is the whole point: the reader has to recognise the menu's
    # tips button later, when nothing is there to explain it.
    assert 'Tips & Gestures' in _text(_tips_buttons(_window(monkeypatch))[0])


def test_it_shows_the_mark_the_menu_uses(monkeypatch):
    # The reference lives behind an unlabelled icon in the menu footer, so the
    # line is only worth its space if it shows that same mark. Nothing shares
    # the name between the two files, hence the tie: the icon this button
    # carries must be a name window.py also uses. Matched against whole string
    # constants in the parse tree, so prose that mentions it does not count.
    import ast
    from pathlib import Path

    from gi.repository import Gtk
    btn = _tips_buttons(_window(monkeypatch))[0]
    icons = [w.get_icon_name() for w in _walk(btn)
             if isinstance(w, Gtk.Image)]
    assert len(icons) == 1

    tree = ast.parse(Path(welcome.__file__).with_name('window.py').read_text())
    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert icons[0] in strings


def test_clicking_it_opens_the_reference_over_the_welcome_window(monkeypatch):
    presented = []

    class _StubDialog:
        def present(self, parent):
            presented.append(parent)

    calls = []

    def _build(**kwargs):
        calls.append(kwargs)
        return _StubDialog()

    monkeypatch.setattr(welcome.onboarding, 'build_tips_dialog', _build)
    win = _window(monkeypatch)
    _tips_buttons(win)[0].emit('clicked')

    assert presented == [win]
    # No `on_shortcuts`: that dialog belongs to the reading window, which does
    # not exist yet. Passing one would offer a row that leads nowhere.
    assert calls == [{}]


def test_the_install_page_carries_no_route(monkeypatch):
    # The window closes itself on handoff and would take an open dialog with
    # it, so the line lives only where the reader is still deciding.
    win = _window(monkeypatch)
    bundle = welcome.bundles_for('en')[0]
    win._on_card_clicked(None, bundle)

    assert win._stack.get_visible_child_name() == 'progress'
    assert not _tips_buttons(win._stack.get_visible_child())
