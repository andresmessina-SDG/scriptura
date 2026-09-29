"""The sermon delivery view: the manuscript full-screen, to preach from.

MANUSCRIPT_RESEARCH §8.6. What every dedicated sermon tool ships, and what
this one keeps: large type and nothing else on screen, an elapsed timer, and
the preacher's own bracketed cues set apart from what is said. What it
refuses: a teleprompter that scrolls on a clock and preaches the sermon for
you. The preacher scrolls.

`present_mode`'s pattern — fullscreen, chrome gone, type scaled — and not its
widget: `PresentView` is chapter-shaped and cannot show prose. So this is a
window of its own, over the Annotations window, holding a read-only view of
the text `journal_markup.for_delivery` makes from the manuscript.

The ground is dark whatever the theme: a lit page is glare in a dim church,
and the room sees the preacher's face, not the screen.
"""

import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from a11y import set_accessible_label  # noqa: E402
from i18n import _  # noqa: E402
import journal_markup  # noqa: E402
import settings  # noqa: E402
import writing_page  # noqa: E402

#: The words' size, and the measure, as a share of the window's width —
#: the mockup's 27px on a 1366px laptop, and larger on a larger screen.
_TYPE_SHARE = 1 / 48
_TYPE_MIN = 22
#: About 45 characters a line, which is what 22em holds in Noto Serif:
#: short enough to keep one's place in with a glance up and back. A narrower
#: face gets larger type to hold the same, and a wider one a wider column.
#: Kept at 22em, Newsreader held 54 and EB Garamond 57, in letters that
#: also looked smaller.
_MEASURE_EMS = 22
_MEASURE_FACE = 'Noto Serif'


def _elapsed(seconds):
    """'4:07', or '1:04:07' past the hour."""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


class DeliveryWindow(Adw.Window):
    """One manuscript, full-screen, until Esc."""

    def __init__(self, title, body, **kw):
        super().__init__(**kw)
        self.add_css_class('sermon-delivery')
        self.set_title(title or _('Sermon'))
        self._title = title
        self._started = time.monotonic()
        self._size = 0

        self._place = Gtk.Label(xalign=0, hexpand=True,
                                ellipsize=Pango.EllipsizeMode.END)
        self._clock = Gtk.Label(label=_elapsed(0))
        self._clock.add_css_class('delivery-clock')
        self._clock.set_tooltip_text(_('Time since you began'))
        top = Gtk.Box(spacing=24)
        top.add_css_class('delivery-top')
        top.append(self._place)
        top.append(self._clock)

        self._view = Gtk.TextView(editable=False, cursor_visible=False,
                                  wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self._view.add_css_class('delivery-text')
        set_accessible_label(self._view, title or _('Sermon'))
        buf = self._view.get_buffer()
        self._install_tags(buf)
        text, spans = journal_markup.for_delivery(body)
        buf.set_text(text)
        for a, b, tag in spans:
            if tag != 'md-table':
                buf.apply_tag_by_name(tag, buf.get_iter_at_offset(a),
                                      buf.get_iter_at_offset(b))
        # Set on columns in `_fit`, once the type has a size to measure.
        self._tables = [(a, b) for a, b, tag in spans if tag == 'md-table']
        self._headings = [
            (buf.create_mark(None, buf.get_iter_at_offset(a), True), text[a:b])
            for a, b, tag in sorted(spans)
            if tag in ('md-heading', 'md-subheading')]

        self._scroll = Gtk.ScrolledWindow(vexpand=True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER,
                                Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_child(self._view)
        # 'changed' too: the heading positions are read off the layout, which
        # is not there when the window is built, and every heading measured
        # then sits at the top.
        for signal in ('value-changed', 'changed'):
            self._scroll.get_vadjustment().connect(
                signal, lambda _a: self._sync_place())

        foot = Gtk.Label(label=_('↑ ↓ scroll · ← → headings · Esc leave'),
                         xalign=0)
        foot.add_css_class('delivery-foot')

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(top)
        page.append(self._scroll)
        page.append(foot)
        self.set_content(page)

        self._css = Gtk.CssProvider()
        self._view.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self.connect('realize', lambda *_a: self._fit())

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._on_key)
        self.add_controller(keys)

        self._tick = GLib.timeout_add_seconds(1, self._on_tick)
        self.connect('close-request', self._on_close)
        self._sync_place()
        self.fullscreen()

    # ── The text ────────────────────────────────────────────────────────

    @staticmethod
    def _install_tags(buf):
        buf.create_tag('md-heading', weight=Pango.Weight.BOLD, scale=1.2,
                       pixels_above_lines=18, pixels_below_lines=6)
        buf.create_tag('md-subheading', weight=Pango.Weight.BOLD,
                       pixels_above_lines=14, pixels_below_lines=4)
        buf.create_tag('md-strong', weight=Pango.Weight.BOLD)
        buf.create_tag('md-emphasis', style=Pango.Style.ITALIC)
        buf.create_tag('md-quote', style=Pango.Style.ITALIC,
                       pixels_above_lines=8, pixels_below_lines=8)
        buf.create_tag('md-rule', justification=Gtk.Justification.CENTER)
        # A cue is a note to the preacher, not a line to say: gold and
        # italic, the colour nothing else on this page is.
        buf.create_tag('md-cue', style=Pango.Style.ITALIC,
                       foreground_rgba=_rgba('#c9a15a'))

    def _fit(self):
        """Size the type and the measure to the screen the window fills.

        Read off the monitor at realize, before the first frame: sized from
        its own allocation the window would paint once at the size it had
        before going full-screen, then jump.
        """
        surface = self.get_surface()
        monitor = (self.get_display().get_monitor_at_surface(surface)
                   if surface is not None else None)
        if monitor is None:
            return
        width = monitor.get_geometry().width
        base = max(_TYPE_MIN, round(width * _TYPE_SHARE))
        face = settings.get('writing_font')
        if face not in writing_page.WRITING_FONTS:
            face = settings.default('writing_font')
        # Measured on the sermon's own words, so a Russian manuscript is
        # measured in the letters it is drawn in.
        buf = self._view.get_buffer()
        sample = ' '.join(buf.get_text(buf.get_start_iter(),
                                       buf.get_end_iter(), False).split())
        sample = (sample or _SAMPLE)[:2000]
        widths = []
        for f in (face, _MEASURE_FACE):
            layout = self._layout(f, base)
            layout.set_text(sample, -1)
            widths.append(layout.get_size()[0])
        ratio = widths[0] / widths[1]
        size = max(base, round(base / ratio))
        self._size = size
        column = round(_MEASURE_EMS * base * max(1.0, ratio))
        # The reader's Line spacing, read as ems: 1.5× is 1.5em on every
        # face. GTK multiplies the FACE's own leading, so passed straight
        # through it came to 1.64em in Newsreader and 2.07em in Noto Serif —
        # a third fewer lines on the screen, for a choice of face.
        layout = self._layout(face, size)
        layout.set_text('x\nx', -1)
        two = layout.get_size()[1]
        layout.set_text('x', -1)
        natural = (two - layout.get_size()[1]) / Pango.SCALE
        factor = settings.get('line_spacing') * size / natural
        self._css.load_from_data((
            f"textview.delivery-text {{ font-family: '{face}', 'Noto Serif', "
            f"serif; font-size: {size}px; "
            f"line-height: {factor:.3f}; }}").encode())
        side = max(24, (width - column) // 2)
        self._view.set_left_margin(side)
        self._view.set_right_margin(side)
        self._set_columns(face, size)

    def _layout(self, face, size, weight=Pango.Weight.NORMAL):
        """A layout in the view's face and size, to measure with."""
        font = Pango.FontDescription()
        # The view's own fallback: Newsreader has no Cyrillic, and text
        # measured in whatever Pango picked instead is not the text drawn.
        font.set_family(f'{face},Noto Serif')
        font.set_absolute_size(size * Pango.SCALE)
        font.set_weight(weight)
        layout = self._view.create_pango_layout('')
        layout.set_font_description(font)
        return layout

    def _set_columns(self, face, size):
        """Each table's cells on tab stops at its widest cell per column.

        Measured in bold, which the header is: a column set by its regular
        cells would let a bold header run into the next.
        """
        layout = self._layout(face, size, Pango.Weight.BOLD)
        buf = self._view.get_buffer()
        for a, b in self._tables:
            start, end = buf.get_iter_at_offset(a), buf.get_iter_at_offset(b)
            widths: list[int] = []
            for row in buf.get_text(start, end, True).split('\n'):
                for i, cell in enumerate(row.split('\t')):
                    layout.set_text(cell, -1)
                    w = layout.get_pixel_size()[0]
                    if i < len(widths):
                        widths[i] = max(widths[i], w)
                    else:
                        widths.append(w)
            stops = Pango.TabArray.new(max(1, len(widths) - 1), True)
            x = 0
            for i, w in enumerate(widths[:-1]):
                x += w + size
                stops.set_tab(i, Pango.TabAlign.LEFT, x)
            buf.apply_tag(buf.create_tag(None, tabs=stops), start, end)

    # ── Where the preacher is ───────────────────────────────────────────

    def _heading_ys(self):
        buf = self._view.get_buffer()
        return [(self._view.get_line_yrange(buf.get_iter_at_mark(m))[0], name)
                for m, name in self._headings]

    def _sync_place(self):
        """The title, and the heading the page is under."""
        top = self._scroll.get_vadjustment().get_value()
        under = ''
        for y, name in self._heading_ys():
            if y > top + 1:
                break
            under = name
        self._place.set_label(' · '.join(p for p in (self._title, under) if p))

    def _to_heading(self, step):
        adj = self._scroll.get_vadjustment()
        top = adj.get_value()
        ys = [y for y, _name in self._heading_ys()]
        if step > 0:
            later = [y for y in ys if y > top + 1]
            target = later[0] if later else None
        else:
            earlier = [y for y in ys if y < top - 1]
            target = earlier[-1] if earlier else 0
        if target is not None:
            adj.set_value(target)

    def _on_key(self, _ctl, keyval, _code, state):
        adj = self._scroll.get_vadjustment()
        line = (self._size or _TYPE_MIN) * settings.get('line_spacing')
        page = adj.get_page_size() * 0.85
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        moves = {
            Gdk.KEY_Down: line, Gdk.KEY_Up: -line,
            Gdk.KEY_Page_Down: page, Gdk.KEY_Page_Up: -page,
            Gdk.KEY_space: -page if shift else page,
        }
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif keyval in moves:
            adj.set_value(adj.get_value() + moves[keyval])
        elif keyval == Gdk.KEY_Home:
            adj.set_value(adj.get_lower())
        elif keyval == Gdk.KEY_End:
            adj.set_value(adj.get_upper())
        elif keyval == Gdk.KEY_Right:
            self._to_heading(1)
        elif keyval == Gdk.KEY_Left:
            self._to_heading(-1)
        else:
            return False
        return True

    # ── The clock ───────────────────────────────────────────────────────

    def _on_tick(self):
        self._clock.set_label(_elapsed(time.monotonic() - self._started))
        return GLib.SOURCE_CONTINUE

    def _on_close(self, _win):
        if self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0
        return False


#: What an empty manuscript is measured on.
_SAMPLE = ('The sower does not choose the soil before he sows. He throws '
           'the seed wide, as if every patch of ground might yet bear.')


def _rgba(spec):
    colour = Gdk.RGBA()
    colour.parse(spec)
    return colour
