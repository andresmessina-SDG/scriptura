"""family_tree.py — The Bible Family Tree, the pane document.

Three views of the same Bibles behind a switch: the Family (the Bibles people
read, drawn down the page in time; the default), the Line (every English
Bible on one track) and Read the difference (one verse down the Line). The
Family also has an outline, the same tree as an indented list. The app
remembers the view last used.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

import bible_family
import settings
from a11y import set_accessible_label
from family_line import FamilyLine
from family_read import FamilyRead
from family_view import FamilyOutline, FamilyView, key_widget, paint_plate
from i18n import _


def reading_module(pane):
    """The Bible being read beside this pane: the other pane's, when it shows
    one the data knows; else the Bible this pane showed before it opened the
    Family Tree."""
    root = pane.get_root() if pane is not None else None
    for other in (getattr(root, 'pane1', None), getattr(root, 'pane2', None)):
        if (other is not None and other is not pane and other.get_visible()
                and bible_family.node_for_module(other.module)):
            return other.module
    came_from = getattr(pane, '_came_from', None)
    if came_from and bible_family.node_for_module(came_from):
        return came_from
    return None


class FamilyTree:
    """The pane subsystem: the switch, and the views under it."""

    def __init__(self, pane=None):
        self._pane = pane
        self.line = FamilyLine(pane)
        self.read = FamilyRead(pane)
        self.family = None          # built on first show: 37 widgets
        self.outline = None
        self._scrolled_for = None
        self._showing = None        # a Bible the Card asked to show
        self._read_asked = False    # Compare chose the verse to read

        # The three views in the app's page switcher, the Journal's: one
        # control, the selection sliding between the words, centred over
        # what it turns. What belongs to one view sits apart and quiet: the
        # Family's own buttons at the end of this row, its arrangement
        # beside the hint under it (2026-09-26).
        self._views = Adw.ToggleGroup()
        self._views.add_css_class('round')
        self._views.add_css_class('page-switcher')
        # A tooltip only where the word is short of the name: one that
        # repeats a visible label only drops a box over the page.
        for name, label in (('family', _('Family')), ('line', _('Line')),
                            ('read', _('Read'))):
            self._views.add(Adw.Toggle(name=name, label=label))
        self._views.get_toggle_by_name('read').set_tooltip(
            _('Read the difference'))
        bar = Gtk.CenterBox()
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        bar.set_center_widget(self._views)
        tools = Gtk.Box(spacing=2)
        tools.add_css_class('family-tools')
        tools.set_valign(Gtk.Align.CENTER)
        bar.set_end_widget(tools)
        # The Family's two arrangements: by family (lanes), or by
        # literalness — every Bible slid to its place on the Line.
        self._arrangements = Gtk.Box(spacing=2)
        self._by_family = Gtk.ToggleButton(label=_('By family'))
        self._by_line = Gtk.ToggleButton(label=_('By literalness'))
        self._by_line.set_group(self._by_family)
        set_accessible_label(self._by_family, _('Arrange by family'))
        set_accessible_label(self._by_line, _('Arrange by literalness'))
        for btn in (self._by_family, self._by_line):
            btn.add_css_class('flat')
            btn.add_css_class('family-pill')
            self._arrangements.append(btn)
        self._list_btn = Gtk.ToggleButton(
            icon_name='scriptura-view-list-symbolic')
        self._list_btn.add_css_class('flat')
        self._list_btn.set_tooltip_text(_('Show the Family as a list'))
        set_accessible_label(self._list_btn, _('Show the Family as a list'))
        tools.append(self._list_btn)
        # The margin notes (a burning in 1952, a Bible in every parish) are
        # history beside the drawing; a reader who wants the lines alone
        # can put them away.
        self._notes_btn = Gtk.ToggleButton(
            icon_name='scriptura-format-text-quote-symbolic')
        self._notes_btn.add_css_class('flat')
        self._notes_btn.set_tooltip_text(_('Show the margin notes'))
        set_accessible_label(self._notes_btn, _('Show the margin notes'))
        tools.append(self._notes_btn)
        self._print_btn = Gtk.Button(
            icon_name='scriptura-document-print-symbolic')
        self._print_btn.add_css_class('flat')
        self._print_btn.set_tooltip_text(_('Print the Family as a poster'))
        set_accessible_label(self._print_btn,
                             _('Print the Family as a poster'))
        self._print_btn.connect('clicked', lambda _b: self.print_poster())
        tools.append(self._print_btn)

        self._stack = Gtk.Stack()
        # Sized by what is showing: the hidden outline's long names set the
        # whole pane's minimum at 509px, squeezing the Bible beside it.
        self._stack.set_hhomogeneous(False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self.line.widget, 'line')
        self._stack.add_named(self.read.widget, 'read')

        # Every view says in a line how to read it; the arrow-key walk
        # cannot be seen, so the Family says that. The same line under each
        # view, so the page does not jump as the switch turns.
        # Centred under the switch, like it: at the left it lined up with
        # nothing, the views' content starting well in from the edge.
        self._hint = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self._hint.add_css_class('family-line-meta')
        self._hint.set_valign(Gtk.Align.CENTER)
        # By literalness the hint is the drawing's key, drawn, not said.
        self._key = key_widget()
        self._key.set_valign(Gtk.Align.CENTER)
        under = Adw.WrapBox(child_spacing=12, line_spacing=2, align=0.5)
        under.set_margin_start(14)
        under.set_margin_end(14)
        under.set_margin_top(4)
        under.append(self._arrangements)
        under.append(self._hint)
        under.append(self._key)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(under)
        box.append(self._stack)
        self.widget = box

        view = settings.get('family_tree_view')
        self._views.set_active_name(
            view if view in ('line', 'read') else 'family')
        self._list_btn.set_active(bool(settings.get('family_tree_outline')))
        self._notes_btn.set_active(bool(settings.get('family_tree_notes')))
        self._notes_btn.connect('toggled', self._on_notes)
        (self._by_line if settings.get('family_tree_arrangement') == 'line'
         else self._by_family).set_active(True)
        self._by_family.connect('toggled', self._on_arrangement)
        self._by_line.connect('toggled', self._on_arrangement)
        self._views.connect('notify::active-name',
                            lambda _g, _p: self._on_view(None))
        self._list_btn.connect('toggled', self._on_view)
        self._show_view()

    # ── the pane's calls ─────────────────────────────────────────────────

    def render(self):
        self.line.render()
        if self.view == 'read':
            self.read.render()
        if self.family is not None:
            self._refresh_family()

    def reading_module(self):
        return reading_module(self._pane)

    def showing_family(self):
        """True when the Family (drawn or as a list) is showing, not the
        Line."""
        return self.view == 'family'

    def show_node(self, node_id):
        """Turn to the Family and put the keyboard on one Bible there, its
        line lit: in the drawing, or in the list if the reader chose it."""
        self.turn_to('family')
        self._ensure_family()
        view = self.outline if self._list_btn.get_active() else self.family
        # It beats the scroll to the Bible being read, which a pane just
        # turned to the Family has queued already.
        self._showing = node_id
        view.show_node(node_id, lambda: setattr(self, '_showing', None))

    def show_on_line(self, node_id):
        """Turn to the Line and put the keyboard on one Bible's row."""
        self.turn_to('line')
        self.line.show_node(node_id)

    def show_read(self, book, chapter, verse):
        """Turn to Read the difference at one verse."""
        self._read_asked = True
        self.read.show_verse(book, chapter, verse)
        self.turn_to('read')
        self._read_asked = False

    def focus_last(self):
        name = self._stack.get_visible_child_name()
        {'line': self.line, 'read': self.read, 'family': self.family,
         'outline': self.outline}[name].focus_last()

    # ── views ────────────────────────────────────────────────────────────

    @property
    def view(self):
        """The view showing: 'family', 'line' or 'read'."""
        return self._views.get_active_name()

    def turn_to(self, view):
        self._views.set_active_name(view)

    def _on_view(self, btn):
        """The switch turned (`btn` None) or the list toggled."""
        view = self.view
        settings.put('family_tree_view', view)
        settings.put('family_tree_outline', self._list_btn.get_active())
        if btn is None and view == 'read':
            # Turned to, it reads the verse the reader is on now; turned to
            # by Compare, show_read has set the verse already.
            if not self._read_asked:
                self.read.follow_reading()
        self._show_view()

    def _on_notes(self, btn):
        settings.put('family_tree_notes', btn.get_active())
        if self.family is not None:
            self.family.set_notes_visible(btn.get_active())

    def _show_view(self):
        family = self.view == 'family'
        drawing = family and not self._list_btn.get_active()
        self._list_btn.set_visible(family)
        self._arrangements.set_visible(drawing)
        self._print_btn.set_visible(drawing)
        self._notes_btn.set_visible(drawing)
        read = self.view == 'read'
        self._show_hint()
        if not family:
            self._stack.set_visible_child_name('read' if read else 'line')
            return
        self._ensure_family()
        self._stack.set_visible_child_name(
            'outline' if self._list_btn.get_active() else 'family')

    def _show_hint(self):
        """One short line under the switch in every view; the drawing by
        literalness shows its key there instead."""
        family = self.view == 'family'
        drawing = family and not self._list_btn.get_active()
        key = drawing and self._by_line.get_active()
        self._key.set_visible(key)
        self._hint.set_visible(not key and (not family or drawing))
        self._hint.set_label(self._hint_text())

    def _hint_text(self):
        if self.view == 'line':
            return _('Word for word at the left, free at the right. Press a '
                     'Bible to open its card.')
        if self.view == 'read':
            return _('One verse, word for word at the top, free at the '
                     'bottom. Press a Bible to open its card.')
        return _('Hover a Bible to light its line. Arrow keys walk the '
                 'family; Enter opens its card.')

    def _on_arrangement(self, btn):
        if not btn.get_active():
            return
        arrangement = 'line' if btn is self._by_line else 'family'
        settings.put('family_tree_arrangement', arrangement)
        self._show_hint()
        if self.family is not None:
            self.family.set_arrangement(arrangement)

    def _ensure_family(self):
        if self.family is not None:
            return
        self.family = FamilyView(
            self._open_card,
            'line' if self._by_line.get_active() else 'family')
        self.family.set_notes_visible(self._notes_btn.get_active())
        self.family.set_root_open(bool(settings.get('family_tree_root_open')),
                                  animate=False)
        self.family.on_root = lambda open_: settings.put(
            'family_tree_root_open', open_)
        self.outline = FamilyOutline(self._open_card)
        self._stack.add_named(self.family.widget, 'family')
        self._stack.add_named(self.outline.widget, 'outline')
        self._refresh_family()

    def _refresh_family(self):
        installed = list(getattr(self._pane, '_names', []) or [])
        reading = self.reading_module()
        target = self.family.refresh(installed, reading)
        # Scroll only when the Bible being read changes (the Line's rule):
        # a theme switch re-renders too, and must leave the reader be.
        if target is not None and target is not self._scrolled_for:
            self._scrolled_for = target
            GLib.idle_add(lambda: self._showing is None
                          and self.family.scroll_to(target) and False)

    def can_print(self):
        """Whether the poster can be printed now: from the Family drawn,
        where its Print button shows, not from the Line or the list."""
        return self._print_btn.get_visible()

    def build_print(self):
        """The print job for the poster: one page, the Family fitted to it.
        GNOME's dialog offers the paper (A3 or tabloid for a wall) and
        'Print to File' for a PDF to take to a print shop."""
        operation = Gtk.PrintOperation()
        operation.set_job_name(_('The Bible Family Tree'))
        operation.set_n_pages(1)
        operation.set_use_full_page(False)
        operation.set_unit(Gtk.Unit.POINTS)
        family = self.family
        operation.connect(
            'draw-page', lambda _op, ctx, _n: paint_plate(
                family, ctx.get_cairo_context(), ctx.get_width(),
                ctx.get_height()))
        return operation

    def print_poster(self):
        if self.family is None:
            return
        # Printed mid-slide, the Bibles would be caught half-way across.
        if self.family._animation is not None:
            self.family._animation.skip()
        root = self._pane.get_root() if self._pane is not None else None
        try:
            self.build_print().run(Gtk.PrintOperationAction.PRINT_DIALOG,
                                   root)
        except Exception:
            # A refused portal, no printers, a cancelled job: none of them
            # is a reason to take the app down.
            toast = getattr(self._pane, '_on_toast', None)
            if toast:
                toast(_('Could not print the Family'))

    def _open_card(self, node_id):
        root = self._pane.get_root() if self._pane is not None else None
        if root is not None and hasattr(root, 'show_family_card'):
            root.show_family_card(node_id, self._pane)
