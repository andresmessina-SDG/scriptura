"""The right-click study menu: whether it can be shown at all, and whether
it stays the same menu as a reader accumulates writing.

A GTK popover is placed below what it points at, flipped above when that
will not fit, and — when neither fits — popped straight back down without a
word. His screenshots caught the result: in a 686x709 window the menu is
498px tall against a 607px view, and a right-click anywhere from y=180 to
y=340 opened nothing at all, while the same verse answered above and below
that band.

The fix is not a position but a minimum: inside a scroller the menu can be
smaller than its natural height, so GTK always has somewhere to put it. That
is what these measure — the natural height is still the whole menu, and the
minimum is small enough to fit a short window. `GtkPopoverMenu` carries that
scroller itself, which is one reason the menu is now built from a model.

The second invariant arrived with the model. The menu had grown to twelve
flat rows and 540px — past the 498px that broke it — and five of those rows
were conditional, appearing in the MIDDLE as the reader's own marks, entries
and sermons accumulated. So the row someone reached for moved with use. Now
everything that can appear is inside a submenu or last, and that is measured
here: a reader a year in must meet the same menu as a reader on day one.
"""

import pytest

import annotation_dialogs


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk, Gtk
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    return Gtk


def _menu(monkeypatch, verses=(10,)):
    """The popover show_study_menu parents onto a stand-in view."""
    Gtk = _gtk()
    monkeypatch.setattr(annotation_dialogs.annotations, 'get_annotations',
                        lambda *a: {})

    class _Pane:
        _module, _book, _chapter = 'KJV', 'Genesis', 11
        _view = Gtk.TextView()
        _buffer = _view.get_buffer()

    pane = _Pane()
    # Built, not shown: `popup()` on a popover whose parent has no root
    # segfaults, and the size is knowable without a window.
    popover = annotation_dialogs.build_study_menu(pane, list(verses), 100, 100)
    return Gtk, popover


def test_the_menu_can_be_smaller_than_it_wants_to_be(monkeypatch):
    """The whole defect in one number. GTK can only place a popover it can
    fit, and 498px of menu fits nowhere in a 607px column: not below a click
    at y=340, not above it either.

    The popover itself measures 0 until it is shown — it is a GtkNative and
    sizes its own surface — so the number that decides this is the child's,
    which is what the popover asks for."""
    Gtk, popover = _menu(monkeypatch)
    minimum, natural, _a, _b = popover.get_child().measure(
        Gtk.Orientation.VERTICAL, -1)
    assert natural > 150, (
        f'the menu is only {natural}px tall — if it really is this short, '
        'this guard has stopped testing anything')
    assert natural < 400, (
        f'the menu is {natural}px tall again; it fitted nowhere at 498px in '
        'his 607px view, and the grouping exists to keep it far from that')
    assert minimum <= 220, (
        f'the menu cannot shrink: {minimum}px minimum against {natural}px '
        'natural, so a short window has nowhere to put it and shows nothing')


def test_the_whole_menu_is_still_offered_where_there_is_room(monkeypatch):
    """The guard on the guard: shrinking must not cost the reader rows on a
    normal screen. The scroller propagates its natural height, so where the
    space exists the menu is its full self."""
    Gtk, popover = _menu(monkeypatch)
    scroller = popover.get_child()
    assert isinstance(scroller, Gtk.ScrolledWindow)
    assert scroller.get_propagate_natural_height()
    inner = scroller.get_child()
    rows_natural = inner.measure(Gtk.Orientation.VERTICAL, -1)[1]
    asked_natural = scroller.measure(Gtk.Orientation.VERTICAL, -1)[1]
    assert asked_natural >= rows_natural, (
        f'the scroller asks for {asked_natural}px against {rows_natural}px of '
        'menu, so rows are cut even on a screen with room for them')


# ── The same menu, however much you have written ─────────────────────────────

def _level_one(Gtk, popover):
    """The labels on the menu's first page, in order.

    A GtkPopoverMenu keeps every page in one stack, so a plain walk would
    also collect the submenus' contents; the first page is the box whose
    stack name is 'main'.
    """
    stack = None
    queue = [popover]
    while queue and stack is None:
        widget = queue.pop(0)
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Stack):
                stack = child
                break
            queue.append(child)
            child = child.get_next_sibling()
    assert stack is not None, 'no stack in the popover menu'
    page = stack.get_child_by_name('main')
    labels = []

    def walk(widget):
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) and child.get_text():
                labels.append(child.get_text())
            walk(child)
            child = child.get_next_sibling()

    walk(page)
    return labels


@pytest.fixture
def stores(tmp_path, monkeypatch):
    import annotations
    import journal
    import sermons
    monkeypatch.setattr(annotations, 'ANNOTATIONS_FILE',
                        str(tmp_path / 'a.json'))
    monkeypatch.setattr(annotations, '_cache', None)
    monkeypatch.setattr(journal, 'JOURNAL_FILE', str(tmp_path / 'j.json'))
    monkeypatch.setattr(journal, '_cache', None)
    monkeypatch.setattr(sermons, 'SERMONS_FILE', str(tmp_path / 's.json'))
    monkeypatch.setattr(sermons, '_cache', None)
    monkeypatch.setattr(sermons, '_load_failed', False)
    return annotations, journal, sermons


def _pane(Gtk):
    class _Pane:
        _module, _book, _chapter = 'KJV', 'John', 3
        _view = Gtk.TextView()
        _buffer = _view.get_buffer()
    return _Pane()


def test_the_menu_is_the_same_shape_a_year_in(stores):
    """The defect the model was built to fix: a highlight, a note, two
    entries and a sermon used to add four rows in the MIDDLE of the menu, so
    Copy verse sat at row 8 on day one and row 12 a year later."""
    Gtk = _gtk()
    annotations, journal, sermons = stores
    pane = _pane(Gtk)

    bare = _level_one(Gtk, annotation_dialogs.build_study_menu(
        pane, [16], 100, 100))

    annotations.save_highlight(None, 'John', 3, 16, '#ffff00')
    annotations.save_note(None, 'John', 3, 16, 'a note')
    journal.save('j1', title='one',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}])
    sermons.save('s1', title='The Sower Went Forth',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': []}])
    full = _level_one(Gtk, annotation_dialogs.build_study_menu(
        pane, [16], 100, 100))

    # One row is added — the recall submenu — and it is the LAST one, so
    # nothing a reader was aiming at has moved. The note row is allowed to
    # say `Edit Note & Tags` once there is a note: a label that changes in
    # place moves nothing.
    def same(labels):
        return [t.removeprefix('Edit ') for t in labels]

    assert same(full[:len(bare)]) == same(bare), (bare, full)
    assert len(full) - len(bare) == 1
    assert 'chapter' in full[-1]


def test_a_sermons_title_cannot_stretch_the_menu(stores):
    """`Add to “…”` carries a manuscript's title, and inline it set the
    width of the whole menu. Inside the Write submenu it cannot."""
    Gtk = _gtk()
    _annotations, _journal, sermons = stores
    pane = _pane(Gtk)
    narrow = annotation_dialogs.build_study_menu(pane, [16], 100, 100)
    narrow_w = narrow.get_child().measure(Gtk.Orientation.HORIZONTAL, -1)[1]
    sermons.save('s1', title='A Very Long Sermon Title Indeed, On The Sower')
    wide = annotation_dialogs.build_study_menu(pane, [16], 100, 100)
    wide_w = wide.get_child().measure(Gtk.Orientation.HORIZONTAL, -1)[1]
    assert wide_w == narrow_w, (narrow_w, wide_w)


def _stack(Gtk, popover):
    """The page stack, wherever GTK's scroller has put it."""
    queue = [popover]
    while queue:
        widget = queue.pop(0)
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Stack):
                return child
            queue.append(child)
            child = child.get_next_sibling()
    raise AssertionError('no page stack in the menu')


def _rows(Gtk, popover, page='main'):
    """The row buttons on one page, as {label: button}.

    The rows are the app's own: a GtkPopoverMenu cannot carry an icon, and
    the glyphs are half of what this menu says.
    """
    stack = _stack(Gtk, popover)
    out = {}

    def walk(widget):
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                labels = []

                def inner(w):
                    c = w.get_first_child()
                    while c is not None:
                        if isinstance(c, Gtk.Label) and c.get_text():
                            labels.append(c.get_text())
                        inner(c)
                        c = c.get_next_sibling()

                inner(child)
                if labels:
                    out[' '.join(labels)] = child
            walk(child)
            child = child.get_next_sibling()

    walk(stack.get_child_by_name(page))
    return out


def test_every_row_is_a_menu_item(stores):
    """What a box of plain buttons could not give: a screen reader heard
    twelve `button`s in a popover with no role at all. The rows are still
    hand-built — they have to be, for the glyphs — so the semantics are put
    on by hand and checked here."""
    Gtk = _gtk()
    popover = annotation_dialogs.build_study_menu(_pane(Gtk), [16], 100, 100)
    assert popover.get_accessible_role().value_nick == 'menu'
    rows = _rows(Gtk, popover)
    assert rows, 'no rows on the first page'
    for label, row in rows.items():
        assert row.get_accessible_role().value_nick == 'menu-item', label


def test_every_row_on_a_page_carries_its_own_glyph(stores):
    """Two rows under one icon is what said a margin note and a page of
    journal were the same thing."""
    Gtk = _gtk()
    _a, journal, sermons = stores
    journal.save('j1', title='one',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': [16]}])
    sermons.save('s1', title='a sermon',
                 anchors=[{'book': 'John', 'chapter': 3, 'verses': []}])
    popover = annotation_dialogs.build_study_menu(_pane(Gtk), [16], 100, 100)
    for page in ('main', 'write', 'share', 'here'):
        icons = []
        for label, row in _rows(Gtk, popover, page).items():
            child = row.get_child().get_first_child()
            if isinstance(child, Gtk.Image):
                icons.append(child.get_icon_name())
        assert len(icons) == len(set(icons)), (page, icons)


def test_the_rows_still_do_what_they_say(stores):
    """A row wired to nothing looks exactly like a row that works."""
    Gtk = _gtk()
    annotations, _journal, _sermons = stores
    pane = _pane(Gtk)
    pane._refreshed = []
    pane._refresh_verse_annotation = pane._refreshed.append
    popover = annotation_dialogs.build_study_menu(pane, [16], 100, 100)
    _rows(Gtk, popover)['Underline'].emit('clicked')
    stored = annotations.get_annotations('KJV', 'John', 3)
    assert stored.get('16', {}).get('underline') is True, stored


def test_a_submenu_row_opens_its_page_and_comes_back(stores):
    """The slide is the whole reason the groups are affordable: a flyout
    needs room beside the menu, and this menu's history is about not having
    room."""
    Gtk = _gtk()
    popover = annotation_dialogs.build_study_menu(_pane(Gtk), [16], 100, 100)
    stack = _stack(Gtk, popover)
    assert stack.get_visible_child_name() == 'main'
    _rows(Gtk, popover)['Write'].emit('clicked')
    assert stack.get_visible_child_name() == 'write'
    # The back row names the page it is on, as GTK's own submenus do.
    _rows(Gtk, popover, 'write')['Write'].emit('clicked')
    assert stack.get_visible_child_name() == 'main'
