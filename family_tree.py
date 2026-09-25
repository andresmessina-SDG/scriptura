"""family_tree.py — The Bible Family Tree, the pane document.

Two views of the same Bibles behind a switch: the Family (the Bibles people
read, drawn down the page in time; the default) and the Line (every English
Bible on one track). The Family also has an outline, the same tree as an
indented list. The app remembers the view last used.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

import bible_family
import settings
from a11y import set_accessible_label
from family_line import FamilyLine
from family_view import FamilyOutline, FamilyView, paint_plate
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
        self.family = None          # built on first show: 37 widgets
        self.outline = None
        self._scrolled_for = None
        self._showing = None        # a Bible the Card asked to show

        bar = Gtk.Box(spacing=8)
        bar.set_margin_start(14)
        bar.set_margin_end(14)
        bar.set_margin_top(8)
        views = Gtk.Box()
        views.add_css_class('linked')
        self._family_btn = Gtk.ToggleButton(label=_('Family'))
        self._line_btn = Gtk.ToggleButton(label=_('Line'))
        self._line_btn.set_group(self._family_btn)
        set_accessible_label(self._family_btn, _('Show the Family'))
        set_accessible_label(self._line_btn, _('Show the Line'))
        views.append(self._family_btn)
        views.append(self._line_btn)
        switches = Adw.WrapBox(child_spacing=8, line_spacing=6, hexpand=True)
        switches.append(views)
        bar.append(switches)
        # The Family's two arrangements: by family (lanes), or by
        # literalness — every Bible slid to its place on the Line.
        self._arrangements = Gtk.Box()
        self._arrangements.add_css_class('linked')
        self._by_family = Gtk.ToggleButton(label=_('By family'))
        self._by_line = Gtk.ToggleButton(label=_('By literalness'))
        self._by_line.set_group(self._by_family)
        set_accessible_label(self._by_family, _('Arrange by family'))
        set_accessible_label(self._by_line, _('Arrange by literalness'))
        self._arrangements.append(self._by_family)
        self._arrangements.append(self._by_line)
        switches.append(self._arrangements)
        self._print_btn = Gtk.Button(
            icon_name='scriptura-document-print-symbolic')
        self._print_btn.add_css_class('flat')
        self._print_btn.set_tooltip_text(_('Print the Family as a poster'))
        set_accessible_label(self._print_btn,
                             _('Print the Family as a poster'))
        self._print_btn.connect('clicked', lambda _b: self.print_poster())
        bar.append(self._print_btn)
        # The margin notes (a burning in 1952, a Bible in every parish) are
        # history beside the drawing; a reader who wants the lines alone
        # can put them away.
        self._notes_btn = Gtk.ToggleButton(
            icon_name='scriptura-format-text-quote-symbolic')
        self._notes_btn.add_css_class('flat')
        self._notes_btn.set_tooltip_text(_('Show the margin notes'))
        set_accessible_label(self._notes_btn, _('Show the margin notes'))
        # In the wrapping row, not the bar's fixed end: one more button
        # there raised the pane's minimum past what leaves the Bible beside
        # it its room.
        switches.append(self._notes_btn)
        self._list_btn = Gtk.ToggleButton(
            icon_name='scriptura-view-list-symbolic')
        self._list_btn.add_css_class('flat')
        self._list_btn.set_tooltip_text(_('Show the Family as a list'))
        set_accessible_label(self._list_btn, _('Show the Family as a list'))
        bar.append(self._list_btn)

        self._stack = Gtk.Stack()
        # Sized by what is showing: the hidden outline's long names set the
        # whole pane's minimum at 509px, squeezing the Bible beside it.
        self._stack.set_hhomogeneous(False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self.line.widget, 'line')

        # The arrow-key walk cannot be seen, so the Family says it.
        self._hint = Gtk.Label(xalign=0, wrap=True)
        self._hint.add_css_class('family-line-meta')
        self._hint.set_margin_start(14)
        self._hint.set_margin_end(14)
        self._hint.set_margin_top(4)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(self._hint)
        box.append(self._stack)
        self.widget = box

        view = settings.get('family_tree_view')
        (self._line_btn if view == 'line' else self._family_btn
         ).set_active(True)
        self._list_btn.set_active(bool(settings.get('family_tree_outline')))
        self._notes_btn.set_active(bool(settings.get('family_tree_notes')))
        self._notes_btn.connect('toggled', self._on_notes)
        (self._by_line if settings.get('family_tree_arrangement') == 'line'
         else self._by_family).set_active(True)
        self._by_family.connect('toggled', self._on_arrangement)
        self._by_line.connect('toggled', self._on_arrangement)
        self._family_btn.connect('toggled', self._on_view)
        self._line_btn.connect('toggled', self._on_view)
        self._list_btn.connect('toggled', self._on_view)
        self._show_view()

    # ── the pane's calls ─────────────────────────────────────────────────

    def render(self):
        self.line.render()
        if self.family is not None:
            self._refresh_family()

    def reading_module(self):
        return reading_module(self._pane)

    def showing_family(self):
        """True when the Family (drawn or as a list) is showing, not the
        Line."""
        return self._family_btn.get_active()

    def show_node(self, node_id):
        """Turn to the Family and put the keyboard on one Bible there, its
        line lit: in the drawing, or in the list if the reader chose it."""
        self._family_btn.set_active(True)
        self._ensure_family()
        view = self.outline if self._list_btn.get_active() else self.family
        # It beats the scroll to the Bible being read, which a pane just
        # turned to the Family has queued already.
        self._showing = node_id
        view.show_node(node_id, lambda: setattr(self, '_showing', None))

    def show_on_line(self, node_id):
        """Turn to the Line and put the keyboard on one Bible's row."""
        self._line_btn.set_active(True)
        self.line.show_node(node_id)

    def focus_last(self):
        name = self._stack.get_visible_child_name()
        {'line': self.line, 'family': self.family,
         'outline': self.outline}[name].focus_last()

    # ── views ────────────────────────────────────────────────────────────

    def _on_view(self, btn):
        # The pair are a radio group: act once, on the one that lit.
        if btn is not self._list_btn and not btn.get_active():
            return
        settings.put('family_tree_view',
                     'family' if self._family_btn.get_active() else 'line')
        settings.put('family_tree_outline', self._list_btn.get_active())
        self._show_view()

    def _on_notes(self, btn):
        settings.put('family_tree_notes', btn.get_active())
        if self.family is not None:
            self.family.set_notes_visible(btn.get_active())

    def _show_view(self):
        family = self._family_btn.get_active()
        drawing = family and not self._list_btn.get_active()
        self._list_btn.set_visible(family)
        self._arrangements.set_visible(drawing)
        self._print_btn.set_visible(drawing)
        self._notes_btn.set_visible(drawing)
        self._hint.set_visible(drawing)
        self._hint.set_label(self._hint_text())
        if not family:
            self._stack.set_visible_child_name('line')
            return
        self._ensure_family()
        self._stack.set_visible_child_name(
            'outline' if self._list_btn.get_active() else 'family')

    def _hint_text(self):
        if self._by_line.get_active():
            return _('Each Bible sits where it lands on the Line; the lines '
                     'of descent show which families drifted. A bar is a '
                     'published range; a bracket, its makers’ own word.')
        return _('Hover or focus a Bible to light its line. Arrow keys '
                 'walk from parent to child; Enter opens its card.')

    def _on_arrangement(self, btn):
        if not btn.get_active():
            return
        arrangement = 'line' if btn is self._by_line else 'family'
        settings.put('family_tree_arrangement', arrangement)
        self._hint.set_label(self._hint_text())
        if self.family is not None:
            self.family.set_arrangement(arrangement)

    def _ensure_family(self):
        if self.family is not None:
            return
        self.family = FamilyView(
            self._open_card,
            'line' if self._by_line.get_active() else 'family')
        self.family.set_notes_visible(self._notes_btn.get_active())
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
