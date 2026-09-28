"""The writing page: how a journal entry or a sermon looks while it is written.

Moved out of `annotation_editors` when the page's work pushed that file past
3,100 lines. What the editors keep is what they are FOR — the fields, the
store, populate and write, the toolbar's edits to the text. What lives here
is how the sheet shows it: the face and leading, the centred column, the
paragraph styles, markers folded off the caret line and hung in the margin,
the bullets, quote bars and rules drawn in their place, the reference card,
"Saved", and HTML paste.

`WritingPageMixin` goes on `_ProseEditor`, as `AppearancePageMixin` goes on
the window: every method still runs on the editor and reads the attributes
it builds (`body`, `refs`, the tool buttons), so nothing that calls them
changed.
"""

import weakref

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gtk, GLib, Graphene, Gsk, Pango  # noqa: E402

from a11y import set_accessible_label  # noqa: E402
from i18n import N_, _  # noqa: E402
import journal_markup  # noqa: E402
from passage_export import format_reference  # noqa: E402
import motion  # noqa: E402
import settings  # noqa: E402

#: The body's own left margin. Every paragraph tag below has to carry it:
#: a tag's `left-margin` REPLACES the view's rather than adding to it, so
#: when this went from 2 to 12 with the sheet, the quote's 22 and the list's
#: 18 quietly stopped being indents of 20 and 16 and became 10 and 6. The
#: blockquote and the list flattened out and nobody's test could see it.
_BODY_MARGIN = 12
#: Where the quote and the list stand, counted from the text column's left
#: edge. Absolute margins are minted from these whenever the column moves.
_QUOTE_INSET = 20
_LIST_INSET = 22

#: The faces a writing sheet offers: the ones the app ships, so every choice
#: renders the same in the Flatpak as from source. One face for the whole
#: page, never a font per word — §4's ruling was against styling a
#: selection, which would put a second representation under the Markdown.
#: This changes how the page looks and nothing in the file. The sans faces
#: are here on purpose: sans-for-structure is the app's own voice, and the
#: words someone writes are not structure.
WRITING_FONTS = ('Newsreader', 'Noto Serif', 'EB Garamond', 'Adwaita Sans',
                 'Roboto', 'OpenDyslexic')

#: Every live prose editor, so a change of face, leading or measure reaches
#: the journal and the sermons page together.
_LIVE: 'weakref.WeakSet[WritingPageMixin]' = weakref.WeakSet()
_WRITING_CSS: Gtk.CssProvider | None = None


def refresh_writing_style():
    """Set the writing face and leading from settings, on every sheet.

    The leading is the reading page's own setting: the sheet sat at
    Newsreader's native 1.17 while every reading surface ran at 1.5, and a
    reader who needs looser lines to read needs them to write as well. The
    measure follows `reading_width` the same way, in `_fit_page`.
    """
    global _WRITING_CSS
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _WRITING_CSS is None:
        _WRITING_CSS = Gtk.CssProvider()
        # Above the app's sheet, which sets these classes at APPLICATION.
        Gtk.StyleContext.add_provider_for_display(
            display, _WRITING_CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    face = settings.get('writing_font')
    if face not in WRITING_FONTS:
        face = settings.default('writing_font')
    # Noto Serif behind every face: it ships with the app and carries the
    # Cyrillic that Newsreader and EB Garamond lack.
    _WRITING_CSS.load_from_data((
        f".journal-entry-body, .journal-entry-heading {{ "
        f"font-family: '{face}', 'Noto Serif', serif; }} "
        f".journal-entry-body {{ line-height: {settings.get('line_spacing')}; }}"
    ).encode())
    for editor in list(_LIVE):
        editor._font_label.set_label(face)
        editor._name_font_button(face)
        editor.body.queue_resize()


def _decode_html(data):
    """Clipboard HTML as text. Chromium hands it over as UTF-16 with a
    byte-order mark; everything else sends UTF-8."""
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return data.decode('utf-16', errors='replace')
    return data.decode('utf-8', errors='replace')


class _SheetScroll(Gtk.ScrolledWindow):
    """The body's scroller, which sets the text column before laying out.

    Column first, then chain up — the reading pane's order, and for its
    reason: margins set after the allocation re-queue a resize the scroller
    has already finished with.
    """

    def __init__(self, fit, **kw):
        super().__init__(**kw)
        self._fit = fit

    def do_size_allocate(self, width, height, baseline):
        self._fit(width)
        Gtk.ScrolledWindow.do_size_allocate(self, width, height, baseline)


#: The paragraph styles, as Pages and Notes name them: what the menu says,
#: the marker it writes, the size its words are set at, and its key. Three
#: sizes of heading and no more — below the third a level stops being
#: something a reader can see, so `####` and deeper take the third's size.
_STYLES = [
    (N_('Body'), '', 1.0, '<Control>0'),
    (N_('Heading'), '# ', 1.25, '<Control>1'),
    (N_('Subheading'), '## ', 1.12, '<Control>2'),
    (N_('Minor Heading'), '### ', 1.0, '<Control>3'),
]


class _WritingView(Gtk.TextView):
    """The body: a text view that also draws what a hidden marker stood
    for — the bullet of a '- ', the bar and field of a '> ', the line of a
    '---'.

    Drawn under the text, in buffer coordinates, from geometry the editor
    already holds: x from the column's own margins, y from line ranges.
    Never from `get_iter_location`, whose x is a letter late for every
    hidden character before it on the line.
    """

    def __init__(self, editor):
        super().__init__()
        # Weak: the editor owns the view, and a cycle would outlive both.
        self._editor = weakref.ref(editor)

    def do_snapshot_layer(self, layer, snapshot):
        editor = self._editor()
        if layer == Gtk.TextViewLayer.BELOW_TEXT and editor is not None:
            editor._draw_page(self, snapshot)

class WritingPageMixin:
    """The writing page's look and its handlers, for `_ProseEditor`."""

    def _build_font_menu(self):
        """The face the sheet is set in, named in words at the end of the row.

        A word rather than an icon: the choice is a name, and the name is
        what a reader looks for. Inside, each face is spelled in itself, as
        toggles in one group so AT hears a radio choice.
        """
        face = settings.get('writing_font')
        self._font_label = Gtk.Label(label=face, xalign=0)
        self._font_label.connect('realize', self._pin_font_label)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        inner.append(Gtk.Image(icon_name='scriptura-font-x-generic-symbolic'))
        inner.append(self._font_label)
        # The glyph says "font" before the name is read, and the arrow says
        # it opens: a bare word in a row of icons read as a label.
        btn = Gtk.MenuButton(child=inner, always_show_arrow=True)
        btn.add_css_class('flat')
        btn.add_css_class('journal-font-menu')
        btn.set_focus_on_click(False)
        btn.set_tooltip_text(_('Font'))
        self._font_button = btn
        self._name_font_button(face)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        group = None
        self._font_choices = {}
        for name in WRITING_FONTS:
            label = Gtk.Label(label=name, xalign=0)
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_family_new(name))
            # Regular, whatever the button's own label weight: a face shown
            # bold is not the face the page will be set in.
            attrs.insert(Pango.attr_weight_new(Pango.Weight.NORMAL))
            label.set_attributes(attrs)
            choice = Gtk.ToggleButton(child=label)
            choice.add_css_class('flat')
            if group is None:
                group = choice
            else:
                choice.set_group(group)
            choice.set_active(name == face)
            choice.connect('toggled', self._on_font_chosen, name, btn)
            column.append(choice)
            self._font_choices[name] = choice
        popover = Gtk.Popover()
        popover.set_child(column)
        # Opened from any sheet, it has to show that sheet's truth: another
        # page may have changed the face since this one was built.
        popover.connect('show', lambda _p: self._font_choices[
            self._font_label.get_label()].set_active(True))
        btn.set_popover(popover)
        return btn

    def _pin_title(self, title):
        """Hold the title at the height of the tallest face on offer.

        Each face brings its own line height, so the title stood 20px tall
        in Newsreader and 34px in OpenDyslexic, and a change of face moved
        every row under it. Measured as `GtkText` measures itself: the taller
        of the laid-out line and the font's ascent plus descent.
        """
        context = title.get_pango_context()
        base = context.get_font_description()
        tallest = 0
        for face in WRITING_FONTS:
            desc = base.copy()
            desc.set_family(f'{face}, Noto Serif, serif')
            metrics = context.get_metrics(desc, None)
            layout = Pango.Layout.new(context)
            layout.set_font_description(desc)
            layout.set_text('Ág', -1)
            extent = metrics.get_ascent() + metrics.get_descent()
            tallest = max(tallest, layout.get_pixel_size()[1],
                          -(-extent // Pango.SCALE))
        # On the text inside, so the entry's own padding stays on top.
        title.get_delegate().set_size_request(-1, tallest)

    def _pin_font_label(self, label):
        """Size the font button to the longest face name, so the tools
        beside it hold still when the face changes."""
        label.set_size_request(max(
            label.create_pango_layout(name).get_pixel_size()[0]
            for name in WRITING_FONTS), -1)

    def _name_font_button(self, face):
        set_accessible_label(self._font_button,
                             _('Font: {name}').format(name=face))

    def _build_style_menu(self):
        """Body, Heading, Subheading, Minor Heading — each set as it will
        look, with its key beside it, the way Pages and Notes show styles.

        One button where there was a Heading toggle that could only write
        `#`: a sub-heading had to be typed, and a new reader does not know
        the notation to type.
        """
        btn = Gtk.MenuButton(icon_name='scriptura-format-text-heading-symbolic',
                             always_show_arrow=True)
        btn.add_css_class('flat')
        btn.add_css_class('journal-style-menu')
        btn.set_focus_on_click(False)
        btn.set_tooltip_text(_('Paragraph Style'))
        set_accessible_label(btn, _('Paragraph Style'))
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        group = None
        self._style_choices: dict[str, Gtk.ToggleButton] = {}
        for label, marker, scale, keys in _STYLES:
            name = Gtk.Label(label=_(label), xalign=0, hexpand=True)
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_scale_new(scale))
            attrs.insert(Pango.attr_weight_new(
                Pango.Weight.BOLD if marker else Pango.Weight.NORMAL))
            name.set_attributes(attrs)
            name.add_css_class('journal-entry-body')
            ok, key, mods = Gtk.accelerator_parse(keys)
            hint = Gtk.Label(label=Gtk.accelerator_get_label(key, mods))
            hint.add_css_class('dim-label')
            hint.add_css_class('caption')
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            row.append(name)
            row.append(hint)
            choice = Gtk.ToggleButton(child=row)
            choice.add_css_class('flat')
            if group is None:
                group = choice
            else:
                choice.set_group(group)
            choice.connect('clicked', self._on_style_chosen, marker, btn)
            column.append(choice)
            self._style_choices[marker] = choice
        popover = Gtk.Popover()
        popover.set_child(column)
        popover.connect('show', lambda _p: self._style_choices[
            self._line_style()].set_active(True))
        btn.set_popover(popover)
        self._style_button = btn
        return btn

    def _line_style(self):
        """The style marker of the caret's line: '', '# ', '## ' or '### '
        (deeper headings answer as the third, whose size they take)."""
        buf = self.body.get_buffer()
        line = self._line_text(buf, buf.get_iter_at_mark(
            buf.get_insert()).get_line())
        marker = journal_markup.line_marker(line)
        if not marker.startswith('#'):
            return ''
        return marker if len(marker) <= 4 else '### '

    def _on_style_chosen(self, _choice, marker, btn):
        btn.popdown()
        self._set_style(marker)

    def _set_style(self, marker):
        """Make every line the selection touches `marker`'s style.

        Set, not toggled: choosing Heading on a heading leaves it one. Body
        takes off whatever whole-line role a line had, list and quote
        included, as Body does in Pages.
        """
        buf = self.body.get_buffer()
        bounds = buf.get_selection_bounds()
        a, b = bounds if bounds else 2 * (
            buf.get_iter_at_mark(buf.get_insert()),)
        first, last = self._selected_lines(a, b)
        buf.begin_user_action()
        for n in range(last, first - 1, -1):
            if marker:
                self._set_marker(buf, n, marker)
                continue
            existing = journal_markup.line_marker(self._line_text(buf, n))
            if existing:
                at = buf.get_iter_at_line(n)[1]
                stop = buf.get_iter_at_line(n)[1]
                stop.forward_chars(len(existing))
                buf.delete(at, stop)
        buf.end_user_action()
        self.body.grab_focus()

    def _sync_tools(self):
        """Press the buttons for what the caret is in."""
        buf = self.body.get_buffer()
        table = buf.get_tag_table()
        bounds = buf.get_selection_bounds()
        caret = buf.get_iter_at_mark(buf.get_insert())
        probe = bounds[0] if bounds else caret

        def styled(name):
            tag = table.lookup(name)
            if probe.has_tag(tag):
                return True
            # At the end of a styled word the caret sits after its last
            # letter; the letter before it is what the reader is "in".
            before = probe.copy()
            return bool(not bounds and before.backward_char()
                        and before.has_tag(tag))

        line = self._line_text(buf, caret.get_line())
        marker = journal_markup.line_marker(line)
        states = {'**': styled('md-strong'), '*': styled('md-emphasis'),
                  '> ': marker.startswith('>'),
                  '- ': marker in ('- ', '* '),
                  'number': bool(journal_markup.numbered_marker(line))}
        for key, btn in self._tool_buttons.items():
            if btn.get_active() != states.get(key, False):
                btn.set_active(states.get(key, False))
        inner = self._style_button.get_first_child()
        if marker.startswith('#'):
            inner.set_state_flags(Gtk.StateFlags.CHECKED, False)
        else:
            inner.unset_state_flags(Gtk.StateFlags.CHECKED)

    def _on_font_chosen(self, choice, name, btn):
        if not choice.get_active() or name == settings.get('writing_font'):
            return
        settings.put('writing_font', name)
        refresh_writing_style()
        btn.popdown()

    # ── The text column ─────────────────────────────────────────────────
    #
    # Every writing app worth copying caps the line: iA Writer at 64, 72 or
    # 80 characters, Obsidian at 700px. The sheet capped nothing, and ran
    # 78 characters a line with the list showing, 125 with it hidden and 139
    # in writing mode — the view meant to be best read worst. It now takes
    # the reading page's own measure (`reading_width`, 540px: about 70
    # characters of Newsreader at the body's size, measured with Pango) and
    # centres it, which also leaves a margin wide enough for iA's other
    # habit: the `#` and `>` that open a line hang in it, so the words keep
    # one left edge and a marker coming and going never moves them.

    #: The size of each heading level's words, by marker length ('# ' is 2).
    _LEVEL_SCALE = {2: 1.25, 3: 1.12}
    #: Letter spacing after each character of a bullet's marker, in Pango
    #: units: 3px each after the dash and the space, about a bullet's gap.
    _BULLET_SPACING = 3 * Pango.SCALE

    def _fit_page(self, width):
        """Centre the column in `width`, and re-hang the markers to fit it.

        Cheap when nothing moved: the key is the face and the margin, and
        allocation runs far more often than either changes.
        """
        if width <= 0:
            return
        measure = int(settings.get('reading_width') or 540)
        side = max(_BODY_MARGIN, (width - measure) // 2)
        face = self.body.get_pango_context().get_font_description()
        key = (face.to_string() if face else '', side)
        if key == self._page_key:
            return
        self._page_key = key
        self.body.set_left_margin(side)
        self.body.set_right_margin(side)
        self._body_hint.set_margin_start(side + 1)
        table = self.body.get_buffer().get_tag_table()
        table.lookup('md-quote').set_property('left-margin', side + _QUOTE_INSET)
        table.lookup('md-bullet').set_property('left-margin', side + _LIST_INSET)
        for marker, tag in self._hangs.items():
            self._hang(tag, marker, side)
        self.body.queue_draw()

    def _hang(self, tag, marker, side):
        """Set `tag` so `marker` sits in the margin and its words start on
        the column's edge — or as far out as the margin allows, at a narrow
        window where it cannot all fit.

        Both properties, because a NEGATIVE indent in Pango does not push
        the first line out: it pulls every wrapped line in. So the paragraph
        starts a marker's width to the left, and the wrapped lines come back
        to the edge the words began on.
        """
        edge = side + (0 if marker[0] == '#' else
                       _QUOTE_INSET if marker[0] == '>' else _LIST_INSET)
        width = min(self._marker_width(marker), max(0, side - 2))
        tag.set_property('left-margin', edge - width)
        tag.set_property('indent', -width)

    def _marker_width(self, marker):
        """How wide `marker` is drawn, in its line's size and weight.

        A marker is drawn at 0.8 of its line; a heading's line is its
        level's size, and a list number is set at full size as words are.
        """
        bold = marker[0] == '#'
        italic = marker[0] == '>'
        if marker[0].isdigit():
            scale = 1.0
        elif bold:
            scale = 0.8 * self._LEVEL_SCALE.get(len(marker), 1.0)
        else:
            scale = 0.8
        # Measured as the view lays it out: the marker, then a letter of
        # the words, and where that letter starts. Pango shares a run's
        # letter spacing across its edge, so a marker measured alone came
        # out a pixel short and a bullet's words moved when it showed.
        layout = self.body.create_pango_layout(marker + 'x')
        end = len(marker.encode())
        attrs = Pango.AttrList()
        chosen = [Pango.attr_scale_new(scale)]
        if marker in ('- ', '* '):
            chosen.append(Pango.attr_letter_spacing_new(self._BULLET_SPACING))
        if bold:
            chosen.append(Pango.attr_weight_new(Pango.Weight.BOLD))
        if italic:
            chosen.append(Pango.attr_style_new(Pango.Style.ITALIC))
        for attr in chosen:
            attr.start_index, attr.end_index = 0, end
            attrs.insert(attr)
        layout.set_attributes(attrs)
        return round(layout.index_to_pos(end).x / Pango.SCALE)

    def _hang_tag(self, marker):
        """The tag that hangs `marker` in the margin."""
        tag = self._hangs.get(marker)
        if tag is None:
            tag = self.body.get_buffer().create_tag(None)
            self._hang(tag, marker, self.body.get_left_margin())
            self._hangs[marker] = tag
        return tag

    #: Every tag a line's styling is made of, taken off before it is re-read.
    _LINE_TAGS = ('md-strong', 'md-emphasis', 'md-heading', 'md-subheading',
                  'md-rule', 'md-quote', 'md-bullet', 'md-marker',
                  'md-hidden', 'md-list-number', 'md-level-1', 'md-level-2',
                  'md-bullet-mark')

    def _restyle_lines(self, buf, first, last):
        """Re-read lines `first`..`last`: the subset's own spans, then what
        this page adds — a heading's size, a marker hung in the margin on a
        line being written, the marker hidden on every other line.

        A list's number is never hidden. It is not notation standing in for
        a bullet the page can draw; it is the item's number.
        """
        total = buf.get_line_count()
        first = max(0, min(first, total - 1))
        last = max(first, min(last, total - 1))
        start = buf.get_iter_at_line(first)[1]
        if last + 1 < total:
            end = buf.get_iter_at_line(last + 1)[1]
        else:
            end = buf.get_end_iter()
        for tag in self._LINE_TAGS:
            buf.remove_tag_by_name(tag, start, end)
        for hang in self._hangs.values():
            buf.remove_tag(hang, start, end)
        shown = self._shown_lines()
        at = start.get_offset()
        # Hidden markers included: they are the entry, whatever is drawn.
        for n, line in enumerate(buf.get_text(start, end, True).split('\n'),
                                 start=first):
            revealed = shown is not None and shown[0] <= n <= shown[1]
            number = journal_markup.numbered_marker(line)
            for a, b, tag in journal_markup.spans(line):
                s = buf.get_iter_at_offset(at + a)
                e = buf.get_iter_at_offset(at + b)
                buf.apply_tag_by_name(tag, s, e)
                if tag != 'md-marker':
                    continue
                if number and a == 0 and b == len(number):
                    buf.apply_tag_by_name('md-list-number', s, e)
                    continue
                if a == 0 and line[:2] in ('- ', '* ') and b == 2:
                    buf.apply_tag_by_name('md-bullet-mark', s, e)
                if not revealed:
                    buf.apply_tag_by_name('md-hidden', s, e)
            marker = journal_markup.line_marker(line)
            whole = (buf.get_iter_at_offset(at),
                     buf.get_iter_at_offset(at + len(line)))
            if marker.startswith('#') and len(marker) in self._LEVEL_SCALE:
                buf.apply_tag_by_name(f'md-level-{len(marker) - 1}', *whole)
            if marker and (revealed or number):
                buf.apply_tag(self._hang_tag(marker), *whole)
            at += len(line) + 1

    # ── Which lines show their markers ──────────────────────────────────
    #
    # The markers fold away once the writer leaves a line, and come back on
    # the line the caret or the selection is on, so the notation is there
    # to edit exactly where the reader is editing. A selection shows every
    # line it touches: what is copied from it is then the entry as written,
    # markers and all, and never a version with its notation silently gone.
    #
    # Every marker that opens a line hangs in the margin when it shows, so
    # the words do not move as it comes and goes. Only an inline pair —
    # '**', '*' — takes room in the line when it appears.

    def _set_writing(self, on):
        if self._writing != on:
            self._writing = on
            self._sync_reveal()

    def _leaves_writing(self, widget):
        focus = Gtk.EventControllerFocus()
        focus.connect('enter', lambda _c: self._set_writing(False))
        widget.add_controller(focus)

    def _reveal_range(self):
        """The lines that should show their markers now, or None."""
        if not self._writing:
            return None
        buf = self.body.get_buffer()
        bounds = buf.get_selection_bounds()
        if bounds:
            return self._selected_lines(*bounds)
        line = buf.get_iter_at_mark(buf.get_insert()).get_line()
        return line, line

    def _shown_lines(self):
        if self._shown is None:
            return None
        buf = self.body.get_buffer()
        first, last = (buf.get_iter_at_mark(m).get_line() for m in self._shown)
        return first, last

    def _sync_reveal(self):
        """Fold the lines that stopped being written, unfold the new ones."""
        buf = self.body.get_buffer()
        want, had = self._reveal_range(), self._shown_lines()
        if want == had:
            return
        if self._shown is not None:
            for mark in self._shown:
                buf.delete_mark(mark)
            self._shown = None
        if want is not None:
            first, last = (buf.create_mark(None, buf.get_iter_at_line(n)[1],
                                           True) for n in want)
            self._shown = (first, last)
        for lines in (had, want):
            if lines is not None:
                self._restyle_lines(buf, *lines)

    def _on_mark_set(self, buf, _where, mark):
        if mark is buf.get_insert() or mark is buf.get_selection_bound():
            self._ref_card.popdown()
            self._sync_reveal()
            self._sync_tools()

    # ── What the hidden markers leave behind, drawn ─────────────────────

    def _draw_page(self, view, snapshot):
        """The quote's bar and field, a rule's line, a bullet's dot."""
        buf = view.get_buffer()
        table = buf.get_tag_table()
        quote, rule, bullet = (table.lookup(n) for n in
                               ('md-quote', 'md-rule', 'md-bullet'))
        visible = view.get_visible_rect()
        bottom = visible.y + visible.height
        side = view.get_left_margin()
        right = view.get_width() - view.get_right_margin()
        ink = view.get_color()
        shown = self._shown_lines()
        it = view.get_line_at_y(visible.y)[0]
        run = None
        while True:
            y, h = view.get_line_yrange(it)
            if it.has_tag(quote):
                run = (run[0] if run else y, y + h)
            elif run is not None:
                self._draw_quote(snapshot, ink, side, right, run)
                run = None
            if y > bottom:
                break
            n = it.get_line()
            if not (shown is not None and shown[0] <= n <= shown[1]):
                if it.has_tag(rule):
                    self._draw_rule(snapshot, ink, side, right, y + h / 2)
                elif it.has_tag(bullet) and it.get_char() in ('-', '*'):
                    self._draw_bullet(snapshot, ink, side, y, it.get_char())
            if not it.forward_line():
                break
        if run is not None:
            self._draw_quote(snapshot, ink, side, right, run)

    @staticmethod
    def _tint(ink, alpha):
        colour = Gdk.RGBA()
        colour.red, colour.green, colour.blue = ink.red, ink.green, ink.blue
        colour.alpha = ink.alpha * alpha
        return colour

    def _draw_quote(self, snapshot, ink, side, right, run):
        """A faint rounded field with a bar down its left edge — the rule a
        quotation carries in print, which a text tag could never draw."""
        y0, y1 = run
        x = side + _QUOTE_INSET - 16
        field = Graphene.Rect().init(x, y0, max(1, right - x), y1 - y0)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(field, min(6, (y1 - y0) / 2))
        snapshot.push_rounded_clip(rounded)
        snapshot.append_color(self._tint(ink, 0.05), field)
        snapshot.append_color(self._tint(ink, 0.30),
                              Graphene.Rect().init(x, y0, 3, y1 - y0))
        snapshot.pop()

    def _draw_rule(self, snapshot, ink, side, right, y):
        snapshot.append_color(self._tint(ink, 0.22), Graphene.Rect().init(
            side, round(y), max(1, right - side), 1))

    def _draw_bullet(self, snapshot, ink, side, y, dash):
        """The dot a hidden '- ' stands for, centred where the dash shows
        when its line is written in, in the body's own face so it sits on
        the line's baseline as a typed bullet would."""
        spacing = float(settings.get('line_spacing'))
        key = (dash, self._page_key, spacing)
        if self._dot is None or self._dot[0] != key:
            layout = self.body.create_pango_layout('\u2022')
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_line_height_new(spacing))
            layout.set_attributes(attrs)
            glyph = self.body.create_pango_layout(dash)
            small = Pango.AttrList()
            small.insert(Pango.attr_scale_new(0.8))
            glyph.set_attributes(small)
            centre = (_LIST_INSET - self._marker_width(dash + ' ')
                      + glyph.get_pixel_size()[0] / 2)
            self._dot = (key, layout,
                         centre - layout.get_pixel_size()[0] / 2)
        _key, layout, dx = self._dot
        snapshot.save()
        snapshot.translate(Graphene.Point().init(side + dx, y))
        snapshot.append_layout(layout, self._tint(ink, 0.85))
        snapshot.restore()

    def _build_ref_card(self):
        card = Gtk.Popover(autohide=False, has_arrow=True)
        card.add_css_class('journal-ref-card')
        card.set_position(Gtk.PositionType.BOTTOM)
        # Never takes the keyboard: the reader clicked to write, and the
        # next keystroke belongs in the body. It closes when the caret moves.
        card.set_can_focus(False)
        self._ref_go = Gtk.Button()
        self._ref_go.add_css_class('flat')
        self._ref_go.set_focus_on_click(False)
        self._ref_go.set_tooltip_text(_('Ctrl+click a reference to go there '
                                        'directly'))
        self._ref_go.connect('clicked', self._on_ref_go)
        card.set_child(self._ref_go)
        card.set_parent(self.body)
        return card

    def _offer_ref(self, hit):
        start, end, book, chapter, verse = hit
        self._ref_hit = hit
        where = format_reference(book, chapter, [verse] if verse else None)
        self._ref_go.set_label(_('Go to {reference}').format(reference=where))
        buf = self.body.get_buffer()
        # Cursor locations, not iter locations: the caret's line shows its
        # markers, but a reference is placed right either way this route.
        a = self.body.get_cursor_locations(buf.get_iter_at_offset(start))[0]
        b = self.body.get_cursor_locations(buf.get_iter_at_offset(end))[0]
        x0, y0 = self.body.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, a.x, a.y)
        x1, _y = self.body.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, b.x, b.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y = x0, y0
        rect.width, rect.height = max(1, x1 - x0), a.height
        self._ref_card.set_pointing_to(rect)
        self._ref_card.popup()

    def _on_ref_go(self, _btn):
        self._ref_card.popdown()
        _a, _b, book, chapter, verse = self._ref_hit
        self._on_navigate(book, chapter, verse or 1)

    # ── Saved ───────────────────────────────────────────────────────────

    def _flash_saved(self):
        """Show "Saved" for a moment: in quickly, out slowly. Opacity only,
        so the caption line never reflows around it."""
        self._fade_saved(1, 150)
        if self._saved_source:
            GLib.source_remove(self._saved_source)
        self._saved_source = GLib.timeout_add(motion.SAVED_HOLD_MS,
                                              self._unflash_saved)

    def _unflash_saved(self):
        self._saved_source = 0
        self._fade_saved(0, 400)
        return GLib.SOURCE_REMOVE

    def _fade_saved(self, to, ms):
        fade = self._saved_fade
        fade.pause()
        fade.set_value_from(self._saved.get_opacity())
        fade.set_value_to(to)
        fade.set_duration(ms)
        fade.play()

    # ── Paste ───────────────────────────────────────────────────────────
    #
    # Copied from a web page or a word processor, text arrives with HTML
    # beside it. The view's own paste takes only the plain text, and every
    # heading, list and emphasis the reader could see when they copied is
    # lost. This takes the HTML when there is some and writes what the
    # subset can say of it (`journal_markup.from_html`).

    def _on_paste(self, view):
        clipboard = view.get_clipboard()
        if not clipboard.get_formats().contain_mime_type('text/html'):
            return
        view.stop_emission_by_name('paste-clipboard')
        clipboard.read_async(['text/html'], GLib.PRIORITY_DEFAULT, None,
                             self._on_html_read)

    def _on_html_read(self, clipboard, result):
        try:
            stream, _mime = clipboard.read_finish(result)
            data = stream.read_bytes(8 * 1024 * 1024, None).get_data() or b''
            stream.close(None)
        except GLib.Error:
            data = b''
        text = journal_markup.from_html(_decode_html(data)) if data else ''
        buf = self.body.get_buffer()
        if not text:
            # Nothing the subset could keep: the plain text, as before.
            buf.paste_clipboard(clipboard, None, True)
            return
        buf.begin_user_action()
        buf.delete_selection(True, True)
        buf.insert_at_cursor(text)
        buf.end_user_action()
        self.body.scroll_mark_onscreen(buf.get_insert())
