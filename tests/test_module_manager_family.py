"""The Bible Family Tree's doors in the Module Manager: a known Bible's row
carries the Line's track and an "About" that opens the Card inside the
window; the Bibles tab offers "See all on the Line".

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


def _mod(name, installed=False):
    return {'name': name, 'description': name, 'type': 'Biblical Texts',
            'lang': 'en', 'features': set(), 'license': '', 'size': '1000',
            'version': '1', 'locked': False, 'installed': installed}


def _window(monkeypatch, installed=('KJV', 'KJVA'), **kw):
    mods = [_mod('BSB'), _mod('Alpha'), _mod('Tyndale')] + [
        _mod(n, True) for n in installed]
    monkeypatch.setattr(mm.sword_bridge, 'list_available_modules',
                        lambda: [dict(m) for m in mods])
    monkeypatch.setattr(mm.sword_bridge, 'available_updates', lambda: [])
    monkeypatch.setattr(mm.sword_bridge, 'catalog_timestamp', lambda: None)
    monkeypatch.setattr(mm.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(mm.ebible_bridge, 'installed_ids', lambda: set())
    monkeypatch.setattr(mm.ebible_bridge, 'import_stamps', lambda: {})
    monkeypatch.setattr(mm.ModuleManagerWindow, '_check_for_updates',
                        lambda self: None)
    win = mm.ModuleManagerWindow(**kw)
    win._stack.set_visible_child_name('bibles')
    win._refresh_tab('bibles', full=True)
    return win


def _all(widget, test):
    out = []
    child = widget.get_first_child()
    while child is not None:
        if test(child):
            out.append(child)
        out += _all(child, test)
        child = child.get_next_sibling()
    return out


def _tracks(widget):
    return _all(widget, lambda w: w.get_name() == 'module-family-track')


def _row(win, title):
    rows = _all(win, lambda w: isinstance(w, (mm.Adw.ActionRow,
                                               mm.Adw.ExpanderRow))
                and w.get_title() == title)
    assert rows, title
    return rows[0]


def test_a_known_bible_carries_its_track_an_unknown_one_none(monkeypatch):
    win = _window(monkeypatch)
    assert len(_tracks(_row(win, 'Berean Standard Bible'))) == 1
    assert _tracks(_row(win, 'Alpha')) == []


def test_a_bible_with_no_place_says_so_and_still_opens_its_card(monkeypatch):
    # As the Line does; the Card is still there to open.
    win = _window(monkeypatch)
    (door,) = _tracks(_row(win, 'Tyndale New Testament (1526)'))
    assert door.get_child().get_label() == 'Before the Line'
    door.emit('clicked')
    assert win._card.node_id == 'tyndale'


def test_the_track_sits_beside_the_name_in_the_rows_own_header(monkeypatch):
    # In the row's header, after the title column and before the buttons:
    # the row keeps Adwaita's padding and its one-line height.
    bsb = _row(_window(monkeypatch), 'Berean Standard Bible')
    (track,) = _tracks(bsb)
    assert track.get_parent() is bsb.get_child()
    assert track.get_prev_sibling().has_css_class('title')
    assert track.get_next_sibling().has_css_class('suffixes')
    assert track.get_valign() == Gtk.Align.CENTER
    # The subtitle is left as it was: the track is the door to the Card.
    assert 'href' not in bsb.get_subtitle()


def test_the_track_is_a_crisp_scale(monkeypatch):
    (door,) = _tracks(_row(_window(monkeypatch), 'Berean Standard Bible'))
    track = door.get_child()
    assert track.get_size_request()[0] == mm._FAMILY_TRACK_W
    # Odd, so the 1px line sits on a pixel row instead of blurring over two.
    assert track.get_content_height() % 2 == 1


def test_every_track_in_a_list_ends_at_one_x(monkeypatch):
    # Installed: Remove buttons beside an edition group's chevron. The
    # margin makes up the difference, so track + margin + buttons is one
    # width on every row.
    win = _window(monkeypatch, installed=('KJV', 'KJVA', 'ASV', 'BBE'))
    tracks = _tracks(win._tabs['bibles']['installed_box'])
    assert len(tracks) >= 2
    widths = {t.get_margin_end() + t.get_next_sibling().measure(
        Gtk.Orientation.HORIZONTAL, -1)[1] for t in tracks}
    assert len(widths) == 1


def test_a_group_carries_one_track_its_editions_none(monkeypatch):
    win = _window(monkeypatch)
    group = _row(win, 'King James Version')
    assert isinstance(group, mm.Adw.ExpanderRow)
    # The group draws its own header as an ActionRow: that one is not an
    # edition.
    header = mm._first_descendant(group, mm.Adw.ActionRow)
    editions = _all(group, lambda w: isinstance(w, mm.Adw.ActionRow)
                    and w is not header)
    assert len(editions) == 2
    assert all(_tracks(e) == [] for e in editions)
    assert len(_tracks(group)) == 1


def test_the_track_opens_the_card_in_the_window_and_esc_closes_it(
        monkeypatch):
    win = _window(monkeypatch)
    (door,) = _tracks(_row(win, 'Berean Standard Bible'))
    door.emit('clicked')
    assert win._card_split.get_show_sidebar()
    assert win._card.node_id == 'bsb'
    assert win._on_card_escape(None, Gdk.KEY_Escape, 0, 0) is True
    assert not win._card_split.get_show_sidebar()
    # With the Card closed, Esc is the window's again.
    assert win._on_card_escape(None, Gdk.KEY_Escape, 0, 0) is False


def _buttons(card):
    return [b.get_label() for b in _all(card, lambda w:
                                        isinstance(w, Gtk.Button))
            if b.get_label()]


def test_the_card_here_offers_no_pane_to_open_or_compare_in(monkeypatch):
    win = _window(monkeypatch)
    win._show_card('kjv')      # installed: KJV
    labels = _buttons(win._card)
    assert 'Open in this pane' not in labels
    assert 'Compare this verse' not in labels
    # No main window to show the Family in: no door to it.
    assert 'Show in the Family' not in labels


def test_the_card_shows_the_family_through_the_main_window(monkeypatch):
    asked = []
    win = _window(monkeypatch, on_show_in_family=asked.append)
    win._show_card('kjv')
    assert 'Show in the Family' in _buttons(win._card)
    win._card_show_in_family('kjv')
    assert asked == ['kjv'] and not win._card_split.get_show_sidebar()


def test_the_cards_install_finds_the_bible_in_the_bibles_tab(monkeypatch):
    win = _window(monkeypatch)
    win._show_card('bsb')
    win._card_install('BSB')
    assert not win._card_split.get_show_sidebar()
    assert win._tabs['bibles']['search'].get_text() == 'BSB'


def test_see_all_on_the_line_only_with_a_main_window(monkeypatch):
    def see(win):
        return [b for b in _all(win._tabs['bibles']['browse_group'],
                                lambda w: isinstance(w, Gtk.Button))
                if b.get_label() == 'See all on the Line']
    assert see(_window(monkeypatch)) == []
    asked = []
    (btn,) = see(_window(monkeypatch, on_see_line=lambda: asked.append(1)))
    btn.emit('clicked')
    assert asked == [1]


def test_a_downloading_row_hides_its_track_and_leaves_the_column(monkeypatch):
    # The progress replaces a narrower button; a track aligned to the button
    # was pushed left of every other row's while the download ran.
    import downloads
    win = _window(monkeypatch)
    bsb = _row(win, 'Berean Standard Bible')
    job = downloads.Job('sword:BSB', 'BSB', downloads.CROSSWIRE, None)
    monkeypatch.setitem(downloads._jobs, job.key, job)
    win._show_job_in_rows(job)
    (track,) = _tracks(bsb)
    assert not track.get_visible()
    # Rows drawn while it runs start with the track hidden, and the column
    # is aligned to the rows around it, not to the progress.
    win._refresh_tab('bibles', full=True)
    (track,) = _tracks(_row(win, 'Berean Standard Bible'))
    assert not track.get_visible()


def test_a_narrow_window_narrows_every_track(monkeypatch):
    win = _window(monkeypatch)
    win._set_track_width(mm._FAMILY_TRACK_NARROW)
    faces = [d.get_child() for d in _tracks(win)]
    assert faces and all(f.get_size_request()[0] == mm._FAMILY_TRACK_NARROW
                         for f in faces)
    # And the rows drawn next.
    win._refresh_tab('bibles', full=True)
    assert all(d.get_child().get_size_request()[0]
               == mm._FAMILY_TRACK_NARROW for d in _tracks(win))
    win._set_track_width(mm._FAMILY_TRACK_W)
    assert all(d.get_child().get_size_request()[0] == mm._FAMILY_TRACK_W
               for d in _tracks(win))
