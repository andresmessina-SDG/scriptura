"""The Classics shelf in Books & More: a search hides the shelves and finds
a classic among the results; the Installed list never repeats the shelf.

Built and walked, never shown; skips without a display.
"""
import pytest
from gi.repository import Gdk, Gtk

Gtk.init_check()
if Gdk.Display.get_default() is None:
    pytest.skip('needs a display: building real GTK widgets without one '
                'segfaults rather than failing',
                allow_module_level=True)

import module_manager as mm


def _mod(name, installed=False, classic=False):
    return {'name': name, 'description': name, 'type': 'Generic Books',
            'lang': 'en', 'features': set(), 'license': '', 'size': '1000',
            'version': '1', 'locked': False, 'installed': installed,
            'collection': 'Classics' if classic else ''}


def _window(monkeypatch, mods):
    monkeypatch.setattr(mm.sword_bridge, 'list_available_modules',
                        lambda: [dict(m) for m in mods])
    monkeypatch.setattr(mm.sword_bridge, 'module_names', lambda: [])
    monkeypatch.setattr(mm.sword_bridge, 'available_updates', lambda: [])
    monkeypatch.setattr(mm.sword_bridge, 'catalog_timestamp', lambda: None)
    monkeypatch.setattr(mm.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(mm.ebible_bridge, 'installed_ids', lambda: set())
    monkeypatch.setattr(mm.ebible_bridge, 'import_stamps', lambda: {})
    monkeypatch.setattr(mm.ModuleManagerWindow, '_check_for_updates',
                        lambda self: None)
    win = mm.ModuleManagerWindow()
    win._stack.set_visible_child_name('books')
    win._refresh_tab('books', full=True)
    return win, win._tabs['books']


def _titles(widget):
    out, child = [], widget.get_first_child()
    while child is not None:
        if isinstance(child, mm.Adw.ActionRow) and child.get_title():
            out.append(child.get_title())
        out += _titles(child)
        child = child.get_next_sibling()
    return out


def test_a_search_hides_the_shelves_and_finds_the_classic_once(monkeypatch):
    win, t = _window(monkeypatch, [_mod('CWPOwen', classic=True),
                                   _mod('CWPWatson', classic=True),
                                   _mod('Pilgrim')])
    assert t['curated'].get_visible()
    assert 'CWPOwen' in _titles(t['curated'])
    t['search'].set_text('owen')
    win._refresh_tab('books')
    assert not t['curated'].get_visible()
    assert _titles(t['browse_group']).count('CWPOwen') == 1
    assert 'CWPWatson' not in _titles(t['browse_group'])
    t['search'].set_text('')
    win._refresh_tab('books')
    assert t['curated'].get_visible()


def test_an_installed_classic_is_listed_on_the_shelf_not_twice(monkeypatch):
    win, t = _window(monkeypatch, [_mod('CWPOwen', True, classic=True),
                                   _mod('Pilgrim', True)])
    assert 'CWPOwen' not in _titles(t['installed_box'])
    assert 'Pilgrim' in _titles(t['installed_box'])
    assert 'CWPOwen' in _titles(t['curated'])
    t['search'].set_text('owen')
    win._refresh_tab('books')
    assert 'CWPOwen' in _titles(t['installed_box'])


def test_only_classics_installed_leaves_no_empty_installed_group(monkeypatch):
    win, t = _window(monkeypatch, [_mod('CWPOwen', True, classic=True)])
    assert t['installed_box'].get_first_child() is None


def _scrim(win):
    stack = [win]
    while stack:
        w = stack.pop()
        if w.has_css_class('sheet-scrim'):
            return w
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    return None


def test_the_open_sheet_dims_the_list_and_closing_it_clears(monkeypatch):
    win, t = _window(monkeypatch, [_mod('CWPOwen', classic=True)])
    scrim = _scrim(win)
    assert scrim is not None and not scrim.get_visible()
    win._show_details(_mod('CWPOwen', classic=True), 'Mortification (John Owen)')
    assert scrim.get_visible()
    win._hide_card()
    assert not scrim.get_visible()
