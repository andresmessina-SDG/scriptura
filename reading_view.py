"""The reading text view and everything painted over it.

`BibleTextView` draws its own decorations — highlight bands, search and
flash cues, underlines, the sense-unit rule and the focus veil — through
GtkTextView's `snapshot_layer` hook rather than through tag properties.
The reasons are recorded on the class; the short version is that a tag
background hugs each line's own metrics (so the verse-1 drop cap and the
superscript verse numbers gave uneven bands), and that recolouring text
via a tag applied after layout desyncs from GtkTextView's cached glyph
rendering.

What each decoration is, which layer it paints on, which tag marks its
range and what switches it on is declared once in `_DECORATIONS`, so a new
mark is an entry in that list rather than another branch inside
`_draw_highlights`.

Nothing here imports `pane` — the paint layer is a leaf, which is what
keeps `pane` free to import it at module level.
"""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gsk, Graphene, Pango


def heading_line(buf, start):
    """The start of the section heading above `start`, or None if there is
    none.

    Walks back one paragraph from a unit's first verse, past the blank line
    the heading is separated by. A heading is recognised by what it LACKS:
    every verse paragraph opens under a `vnum_` tag and nothing else in the
    reading text does. Modules that carry no headings (KJV, ASV, the
    Vulgate) answer None, and the veil then starts at the verse itself.
    """
    line = start.copy()
    line.set_line_offset(0)
    for _ in range(3):
        if not line.backward_line():
            return None
        end = line.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        if not buf.get_text(line, end, False).strip():
            continue              # the blank line between heading and verse
        for tag in line.get_tags():
            if (tag.get_property('name') or '').startswith('vnum_'):
                return None       # a verse: this unit opens with no heading
        return line
    return None


def _text_colour(view):
    return view.get_color()


def _themed(view, dark, light):
    col = Gdk.RGBA()
    col.parse(dark if Adw.StyleManager.get_default().get_dark() else light)
    return col


def _lexicon_colour(view):
    return _themed(view, view._LEX_COLOR_DARK, view._LEX_COLOR_LIGHT)


def _unit_rule_colour(view):
    return _themed(view, view._UNIT_RULE_DARK, view._UNIT_RULE_LIGHT)


def _veil_colour(view):
    col = Gdk.RGBA()
    if not col.parse(view._focus_paper or '#ffffff'):
        return None
    col.alpha = view._focus_dim
    return col


class _Decoration:
    """One mark painted over the reading text.

    Declares the layer it draws on, the tag whose ranges it follows, how it
    is drawn and what switches it on — so a new mark is an entry in
    `_DECORATIONS` rather than another branch inside `_draw_highlights`.

    `colour` is a callable of the view (not a constant) because the sources
    genuinely differ: a fixed cue colour, the view's own text colour, or the
    current theme's accent.
    """

    __slots__ = ('name', 'layer', 'tag', 'style', 'colour', 'enabled')

    def __init__(self, name, layer, tag, style, colour, enabled=None):
        self.name = name
        self.layer = layer
        self.tag = tag
        self.style = style
        self.colour = colour
        self.enabled = enabled

    def on(self, view):
        return self.enabled is None or bool(self.enabled(view))


_BELOW = Gtk.TextViewLayer.BELOW_TEXT
_ABOVE = Gtk.TextViewLayer.ABOVE_TEXT

#: Every decoration, in paint order — bottom of the stack first, so each
#: stays visible over the ones below it (a search hit on a highlighted
#: verse, a navigation flash on either).
_DECORATIONS = (
    # The user's own highlights: a family of `hl_bg_<hex>` tags carrying
    # their colour in the name, so this entry has no single tag or colour.
    _Decoration('verse highlights', _BELOW, None, 'highlights', None),
    _Decoration('search match', _BELOW, '_search_hl', 'band',
                lambda v: v._SEARCH_COLOR),
    _Decoration('search match (current)', _BELOW, '_search_hl_cur', 'band',
                lambda v: v._SEARCH_CUR_COLOR),
    _Decoration('navigation flash', _BELOW, '_flash', 'band',
                lambda v: v._FLASH_COLOR),
    _Decoration('annotation underline', _BELOW, '_ul_text', 'underline',
                _text_colour),
    # The rule and the veil share `_cur_unit` — either can run without the
    # other, so both ask their own setting rather than the tag's presence.
    #
    # `_cur_unit` wakes the paint pass like any other decoration. It did not
    # until 2026-07-31, and the rule was therefore invisible on a chapter
    # carrying no highlight, search, flash, annotation or hover tag — the
    # tags that woke it are all created on demand, and a pane that has not
    # yet searched or flashed a verse has none of them. Measured on a clean
    # chapter: 0 rule pixels before, 70 after. The veil paints on the other
    # layer and was never affected, so the two disagreed about a unit they
    # read from the same tag.
    _Decoration('sense-unit rule', _BELOW, '_cur_unit', 'rule',
                _unit_rule_colour,
                enabled=lambda v: getattr(v, '_show_unit_rule', False)),
    _Decoration('lexicon hover', _BELOW, '_strg_hover', 'dotted',
                _lexicon_colour),
    _Decoration('focus veil', _ABOVE, '_cur_unit', 'veil', _veil_colour,
                enabled=lambda v: bool(getattr(v, '_focus_dim', 0.0))),
)


class BibleTextView(Gtk.TextView):
    """TextView that paints verse highlights itself, as bands of a uniform
    height, instead of relying on tag backgrounds.

    A tag background hugs each line's run/line metrics, so the enlarged
    verse-1 drop cap (which makes its wrapped line ~2× taller) and the small
    superscript verse numbers (shorter runs) produced uneven block heights and
    notches. Drawing the band ourselves decouples its height from the line:
    every line of a highlight gets `body_height + 2·pad`. GTK lays text at the
    line-box top with the line-height leading added below, so the band is
    anchored to the line top — uniform regardless of line spacing — letting the
    drop cap rise above it and the numbers sit flush. Highlights are marked by
    zero-visual `hl_bg_<hex>` tags (applied in BiblePane._apply_anno_tags); we
    read their ranges and colors here. Drawn before the text (chained super),
    and the `.bible-view` background is transparent, so the band sits behind
    the glyphs.
    """

    __gtype_name__ = 'BibleTextView'

    _HL_PAD = 2
    _HL_RADIUS = 6   # softly-rounded band corners (band height ~ body + 4px)
    # Transient cues (search match, navigation flash) are painted as bands
    # only — they carry NO text-foreground tag. Recolouring the text via a tag
    # applied/removed after the initial layout desyncs from this custom band
    # paint (GtkTextView keeps a cached glyph rendering that a bare queue_draw
    # doesn't revalidate), which showed up as light-on-light during a flash and
    # black-on-dark after it. So instead the band is a *translucent,
    # mid-luminance* colour: it tints visibly while leaving the reading text
    # legible whatever its colour — light text in dark mode, dark text in light
    # mode, and the black text of a user highlight a flash happens to land on.
    # Current sense-unit rule: quiet enough to sit in the periphery, since
    # it moves as the reader scrolls and must never pull the eye off the
    # text (GUIDANCE §9 calm technology).
    _UNIT_RULE_WIDTH = 2.0
    _UNIT_RULE_INSET = 14.0
    _UNIT_RULE_LIGHT = 'rgba(176,118,44,0.42)'
    _UNIT_RULE_DARK = 'rgba(214,150,54,0.36)'
    _SEARCH_COLOR = 'rgba(214,150,40,0.40)'   # amber, search matches
    # The find bar's *current* match — same amber hue, near-opaque so it reads
    # as "you are here" against the soft bands on the other matches (Safari's
    # yellow-all / orange-current split, kept in one colour family).
    _SEARCH_CUR_COLOR = 'rgba(224,150,36,0.85)'
    _FLASH_COLOR = 'rgba(232,120,32,0.44)'    # orange, navigation flash
    # Annotation + lexicon underlines are painted (not Pango underlines) so they
    # stay uniform under the 200% verse-1 drop cap. Thickness, and the muted
    # accent of the hover/lexicon dotted underline (per theme).
    _UL_THICK = 1.5
    _LEX_COLOR_DARK = '#7fa3c1'
    _LEX_COLOR_LIGHT = '#5a7fa3'

    def do_snapshot_layer(self, layer, snapshot):
        # Paint our bands/underlines via GtkTextView's BELOW_TEXT hook rather
        # than overriding do_snapshot. Overriding do_snapshot breaks the view's
        # internal scroll/viewport pipeline — it leaves stale glyph "trails"
        # while scrolling under stricter GTK backends (e.g. the Flatpak
        # runtime). snapshot_layer is the supported extension point and draws
        # in buffer coordinate space, so no buffer_to_window_coords is needed.
        if layer == _BELOW:
            try:
                self._draw_highlights(snapshot)
            except Exception:
                pass  # never let a paint glitch blank the reading view
        elif layer == _ABOVE:
            try:
                self._draw_above(snapshot)
            except Exception:
                pass

    def _draw_above(self, snapshot):
        """The decorations that paint over the text rather than under it."""
        table = self.get_buffer().get_tag_table()
        for dec in _DECORATIONS:
            if dec.layer != _ABOVE or not dec.on(self):
                continue
            tag = table.lookup(dec.tag)
            if tag is None:
                continue
            colour = dec.colour(self)
            if colour is None:
                continue
            if dec.style == 'veil':
                self._draw_focus_veil(snapshot, tag, colour)

    def _metrics(self):
        m = self.get_pango_context().get_metrics(None, None)
        return m.get_ascent() / Pango.SCALE, m.get_descent() / Pango.SCALE

    def _hl_tags(self):
        out = []
        table = self.get_buffer().get_tag_table()
        def collect(t, _d):
            name = t.get_property('name') or ''
            if name.startswith('hl_bg_'):
                out.append((t, name[len('hl_bg_'):]))
        table.foreach(collect, None)
        return out

    def _draw_highlights(self, snapshot):
        buf = self.get_buffer()
        table = buf.get_tag_table()
        hl_tags = self._hl_tags()
        below = [d for d in _DECORATIONS if d.layer == _BELOW]
        # Nothing to paint unless some waking decoration is actually present.
        # The highlight family counts as present when any hl_bg_ tag exists.
        if not any(bool(hl_tags) if d.style == 'highlights'
                   else table.lookup(d.tag) is not None
                   for d in below):
            return
        vr = self.get_visible_rect()
        _, lo = self.get_iter_at_location(0, vr.y)
        _, hi = self.get_iter_at_location(0, vr.y + vr.height)
        hi.forward_line()
        asc, desc = self._metrics()
        for dec in below:
            if not dec.on(self):
                continue
            if dec.style == 'highlights':
                for tag, hexcol in hl_tags:
                    self._draw_tag_layer(snapshot, buf, tag, hexcol,
                                         lo, hi, asc, desc)
                continue
            tag = table.lookup(dec.tag)
            if tag is None:
                continue
            colour = dec.colour(self)
            if colour is None:
                continue
            if dec.style == 'band':
                self._draw_tag_layer(snapshot, buf, tag, colour,
                                     lo, hi, asc, desc)
            elif dec.style in ('underline', 'dotted'):
                # Painted rather than Pango underlines so they stay uniform
                # under the 200% verse-1 drop cap.
                for s, e in self._tag_ranges(buf, tag, lo, hi):
                    self._draw_band(snapshot, s, e, colour, asc, desc,
                                    underline=True,
                                    dotted=dec.style == 'dotted')
            elif dec.style == 'rule':
                self._draw_unit_rule(snapshot, buf, tag, lo, hi, colour)

    def set_unit_rule(self, enabled):
        """Whether to draw the margin rule beside the current unit. Asked
        separately from the tag, which the focus veil also reads."""
        self._show_unit_rule = bool(enabled)
        self.queue_draw()

    def set_focus_paper(self, paper_hex, dim):
        """The paper the veil is drawn in, and how strongly. `dim` of 0 is
        off, and is the default — nothing here paints until the reader asks
        for it."""
        self._focus_paper = paper_hex
        self._focus_dim = float(dim)
        self.queue_draw()

    def _draw_focus_veil(self, snapshot, tag, colour):
        """Quiet everything but the sense-unit being read.

        A paper-coloured veil over the text ABOVE and BELOW the current unit,
        drawn on GtkTextView's own ABOVE_TEXT hook. Nothing is retagged and
        no glyph is recoloured: a foreground tag applied after layout desyncs
        from the cached glyph rendering (the same trap the highlight bands
        were written around), and it would be buffer work on every scroll.
        The veil is paint, so the text cannot move — which is what lets this
        exist beside the scroll north-star at all.

        The unit itself comes from `_cur_unit`, the tag the margin rule
        already uses, so the two agree by construction and the reader can run
        either, both, or neither.
        """
        buf = self.get_buffer()
        vr = self.get_visible_rect()
        _, lo = self.get_iter_at_location(0, vr.y)
        _, hi = self.get_iter_at_location(0, vr.y + vr.height)
        hi.forward_line()
        ranges = list(self._tag_ranges(buf, tag, lo, hi))
        width = float(self.get_width())
        if not ranges:
            # Nothing of the unit is on screen — which also happens when the
            # tag is stale or the buffer has just been rebuilt. FAIL OPEN:
            # veiling the whole viewport here would blank the reading text
            # over a bookkeeping detail, and unlit paper is never worth a
            # page the reader cannot read. (It did exactly that once.)
            return
        top = self.get_iter_location(ranges[0][0])
        bottom = self.get_iter_location(ranges[-1][1])
        # The unit's own heading stays lit with it: it is the title of what is
        # being read, and quieting it leaves the reader in a passage with its
        # name greyed out. The heading is not inside the tag — SWORD hands it
        # over separately from the verse text — so the veil's top is walked
        # back over it here rather than by widening the tag, which the margin
        # rule also reads and was approved without it.
        heading = heading_line(buf, ranges[0][0])
        self._veil(snapshot, colour, vr.y,
                   top.y if heading is None
                   else self.get_iter_location(heading).y, width)
        self._veil(snapshot, colour, bottom.y + bottom.height,
                   vr.y + vr.height, width)

    @staticmethod
    def _veil(snapshot, colour, y0, y1, width):
        if y1 > y0:
            snapshot.append_color(
                colour, Graphene.Rect().init(0, y0, width, y1 - y0))

    def _draw_unit_rule(self, snapshot, buf, tag, lo, hi, col):
        """Vertical rule beside the sense-unit being read.

        Spans the unit's full height, clipped to the visible rect so a long
        unit costs the same as a short one. Sits inside the left margin, so
        it never shifts the reading measure — the text does not move when
        the mark appears, which is the whole point."""
        # _tag_ranges is a generator — materialise it before indexing, or
        # the TypeError vanishes into do_snapshot_layer's paint guard and
        # the rule simply never appears.
        ranges = list(self._tag_ranges(buf, tag, lo, hi))
        if not ranges:
            return
        start, end = ranges[0][0], ranges[-1][1]
        top = self.get_iter_location(start)
        bot = self.get_iter_location(end)
        y0 = top.y
        y1 = bot.y + bot.height
        if y1 <= y0:
            return
        x = max(2.0, self.get_left_margin() - self._UNIT_RULE_INSET)
        snapshot.append_color(
            col, Graphene.Rect().init(x, y0, self._UNIT_RULE_WIDTH, y1 - y0))

    def _draw_tag_layer(self, snapshot, buf, tag, color, lo, hi, asc, desc):
        if tag is None:
            return
        rgba = Gdk.RGBA()
        if not rgba.parse(color):
            return
        for start, end in self._tag_ranges(buf, tag, lo, hi):
            self._draw_band(snapshot, start, end, rgba, asc, desc)

    def _tag_ranges(self, buf, tag, lo, hi):
        it = lo.copy()
        if not it.has_tag(tag) and not it.forward_to_tag_toggle(tag):
            return
        while it.compare(hi) < 0:
            if it.has_tag(tag):
                s = it.copy()
                e = it.copy()
                e.forward_to_tag_toggle(tag)
                yield s, (e if e.compare(hi) < 0 else hi.copy())
                it = e.copy()
            elif not it.forward_to_tag_toggle(tag):
                return

    _BAND_WS = (' ', '\t', ' ', '\n', '\r')

    def _skip_ws_fwd(self, start, end):
        """First non-whitespace iter in [start, end), else end."""
        it = start.copy()
        while it.compare(end) < 0 and it.get_char() in self._BAND_WS:
            if not it.forward_char():
                break
        return it

    def _trim_ws_end(self, start, end):
        """Iter just past the last non-whitespace char in [start, end)."""
        it = end.copy()
        while it.compare(start) > 0:
            probe = it.copy()
            probe.backward_char()
            if probe.get_char() in self._BAND_WS:
                it = probe
            else:
                break
        return it

    def _draw_band(self, snapshot, start, end, rgba, asc, desc,
                   underline=False, dotted=False):
        pad = self._HL_PAD
        body = asc + desc
        band_h = body + 2 * pad
        # Start on real text — skips the leading space before the verse number
        # and any blank line, so band_top and the x-extent are measured from
        # the same (text-bearing) display line.
        cur = self._skip_ws_fwd(start.copy(), end)
        while cur.compare(end) < 0:
            line_end = cur.copy()
            has_end = self.forward_display_line_end(line_end)
            seg_end = line_end if (has_end and line_end.compare(end) < 0) else end.copy()
            # A verse can cross a paragraph break (rendered as a blank line);
            # the band must pause in the gap and resume on the next paragraph,
            # never bridge it. So a segment never spans a hard newline.
            scan = cur.copy()
            while scan.compare(seg_end) < 0:
                if scan.get_char() == '\n':
                    seg_end = scan
                    break
                if not scan.forward_char():
                    break
            # Trim trailing whitespace so the band hugs the last glyph instead
            # of bleeding onto the space render appends after every verse.
            seg_last = self._trim_ws_end(cur, seg_end)
            if seg_last.compare(cur) > 0:
                r0 = self.get_iter_location(cur)
                r1 = self.get_iter_location(seg_last)
                # Anchor the band's top to the display line's *start* so a verse
                # that begins mid-line with the small raised number shares one
                # top with its neighbours. (GTK lays text at the line-box top
                # with the line-height leading below, so the line top is the
                # body-text top regardless of line spacing.)
                ls = cur.copy()
                self.backward_display_line_start(ls)
                # snapshot_layer draws in buffer coordinates, so use the iter
                # locations directly — GTK applies the scroll/viewport offset.
                wx0 = int(r0.x)
                wy = int(self.get_iter_location(ls).y - pad)
                wx1 = int(r1.x)
                seg_w = max(1.0, wx1 - wx0)
                if underline:
                    # Thin line at a fixed offset below the body baseline —
                    # asc is the uniform font ascent, so the line sits at the
                    # same height on every display line, drop cap included.
                    base_uy = wy + pad + asc + 1.0
                    if dotted:
                        # Sit 2px below a solid annotation line so the two read
                        # as parallel lines (not a smear) when a word is both
                        # underlined and hovered for its definition.
                        uy = base_uy + 2.0
                        x = wx0
                        while x < wx1:
                            w = min(2.0, wx1 - x)
                            snapshot.append_color(
                                rgba, Graphene.Rect().init(
                                    x, uy, w, self._UL_THICK))
                            x += 5.0   # 2px dot + 3px gap
                    else:
                        urect = Graphene.Rect().init(
                            wx0, base_uy, seg_w, self._UL_THICK)
                        rounded = Gsk.RoundedRect()
                        # Radius must never exceed half the smallest side, or
                        # the rounded region is degenerate (pixman "invalid
                        # rectangle") — seg_w can be ~1px on a narrow column.
                        rounded.init_from_rect(
                            urect, min(self._UL_THICK / 2, seg_w / 2))
                        snapshot.push_rounded_clip(rounded)
                        snapshot.append_color(rgba, urect)
                        snapshot.pop()
                else:
                    rect = Graphene.Rect().init(wx0, wy, seg_w, band_h)
                    rounded = Gsk.RoundedRect()
                    # Clamp radius to half the smallest side so a ~1px-wide
                    # segment (narrow column) can't make a degenerate region.
                    rounded.init_from_rect(
                        rect, min(self._HL_RADIUS, seg_w / 2, band_h / 2))
                    snapshot.push_rounded_clip(rounded)
                    snapshot.append_color(rgba, rect)
                    snapshot.pop()
            # Advance past this segment, then skip whitespace / blank lines so
            # the next segment starts on real text.
            cur = seg_end.copy()
            if not cur.forward_char():
                break
            cur = self._skip_ws_fwd(cur, end)
