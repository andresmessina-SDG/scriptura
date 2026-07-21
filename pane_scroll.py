"""ScrollKeeper — the reading-anchor / generation / pin machinery that is the
"reading text never moves" north star, extracted from BiblePane
(STRUCTURAL_ANALYSIS.md §5.4 / Step 1, part 2).

It owns the persisted reading locus (`_reading_anchor`), the render generation
counter that kills superseded corrections (`_anchor_seq`), the scroll-intent
tracking that separates the reader's hand from layout churn (`_last_scroll_*`,
`_scrollbar_held`, `_ignore_scroll_until`), and the capture / apply / settle /
pin loops that hold the reader's place across re-renders and resizes.

It holds a back-reference to its pane and reads the pane's widgets and render
state through the small proxy properties below, so the method bodies are the
inline originals unchanged. The pane keeps thin delegates (and forwarding
`_reading_anchor` / `_anchor_seq` properties) so every render, navigation, and
signal-handler call site is untouched. The scroll-stability matrix
(tools/verify-scroll-stability.py) guards every path.
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk


def _is_fnote_marker_char(it):
    """True when the iter sits on a footnote-marker glyph (superscript
    letter) — identified by its fnote: tag."""
    return any((t.get_property('name') or '').startswith('fnote:')
               for t in it.get_tags())


def _visible_chars_between(start, until):
    """Count chars in [start, until) that aren't footnote-marker glyphs.
    Walks tag-toggle segments (the tag set is constant between toggles)
    rather than chars — commentary sections run to thousands of chars and
    this is on the scroll-settle path."""
    count = 0
    cur = start.copy()
    while cur.compare(until) < 0:
        seg_end = cur.copy()
        if not seg_end.forward_to_tag_toggle(None) or seg_end.compare(until) > 0:
            seg_end.assign(until)
        if not _is_fnote_marker_char(cur):
            count += seg_end.get_offset() - cur.get_offset()
        cur.assign(seg_end)
    return count


def _forward_visible_chars(it, count, limit):
    """Advance `it` past `count` non-marker chars, never crossing `limit`.
    Segment walk, mirror of _visible_chars_between."""
    remaining = count
    while remaining > 0 and it.compare(limit) < 0:
        seg_end = it.copy()
        if not seg_end.forward_to_tag_toggle(None) or seg_end.compare(limit) > 0:
            seg_end.assign(limit)
        seg_len = seg_end.get_offset() - it.get_offset()
        if seg_len <= 0:
            break
        if _is_fnote_marker_char(it):
            it.assign(seg_end)
            continue
        if seg_len >= remaining:
            it.forward_chars(remaining)
            return
        remaining -= seg_len
        it.assign(seg_end)


class ScrollKeeper:
    _SCROLL_KEYVALS = frozenset((
        Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down,
        Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_space,
        Gdk.KEY_KP_Up, Gdk.KEY_KP_Down, Gdk.KEY_KP_Page_Up,
        Gdk.KEY_KP_Page_Down, Gdk.KEY_KP_Home, Gdk.KEY_KP_End,
    ))

    def __init__(self, pane):
        self._pane = pane
        # The persisted reading locus. Re-deriving the anchor from viewport
        # geometry after every re-render ratchets (wrap boundaries shift with
        # footnote markers), so it is computed once and reused until the USER
        # moves: real scrolls and navigation clear it, restores do not.
        self._reading_anchor = None
        # Bumped whenever the buffer is rebuilt; in-flight anchor corrections
        # compare against it and die if superseded.
        self._anchor_seq = 0
        # Deadline for _mark_programmatic_scroll (µs, monotonic): adjustment
        # changes before it are treated as programmatic and never feed chrome.
        self._ignore_scroll_until = 0
        # Debounce source for the post-scroll anchor re-capture, its
        # quiescence-retry counter, and the last time the reading adjustment's
        # value changed (any cause).
        self._anchor_capture_id = 0
        self._settle_retries = 0
        self._last_value_change = 0
        self._last_scroll_value = 0.0
        # True while an anchor re-assert idle is queued (dedupe for per-frame
        # resize storms, e.g. dragging the lexicon divider).
        self._anchor_apply_pending = False
        # Only real input says "the reader moved": wheel/touchpad, scroll keys,
        # or a scrollbar drag. Value changes without recent input are churn.
        self._last_scroll_input = 0
        self._scrollbar_held = False

    # ── Proxies to pane-owned widgets / render state ─────────────────────────
    # The method bodies below reference these exactly as they did inline; the
    # proxies keep the pane the single owner of the widgets and render lists.

    @property
    def _view(self):
        return self._pane._view

    @property
    def _buffer(self):
        return self._pane._buffer

    @property
    def _reading_scroll(self):
        return self._pane._reading_scroll

    @property
    def _rendered_verses(self):
        return self._pane._rendered_verses

    @property
    def _present_verses(self):
        return getattr(self._pane, '_present_verses', None)

    @property
    def _chrome(self):
        return self._pane._chrome

    def _content_child(self):
        return self._pane._content_child()

    # ── Scroll-intent tracking ───────────────────────────────────────────────

    def _on_reading_scroll(self, adj):
        """React to a reading-scroll value change: re-capture the reading
        locus on a genuine user scroll and drive the chrome band. Only engages
        for the flowing Bible text — card views scroll their own containers."""
        v = adj.get_value()
        delta = v - self._last_scroll_value
        self._last_scroll_value = v
        self._last_value_change = GLib.get_monotonic_time()
        if (GLib.get_monotonic_time() < self._ignore_scroll_until
                or self._content_child() != 'text'
                or not self._user_scroll_recent()):
            self._chrome.reset_accum()
            return
        # A real user scroll moves the reading locus — the persisted
        # anchor no longer describes it. Re-capture once the motion
        # settles so resizes can keep holding the reader's place.
        self._reading_anchor = None
        self._schedule_anchor_capture()
        # The chrome band reacts to this scroll (reveal near the top, else
        # accumulate directional motion past the hysteresis thresholds).
        self._chrome.on_scroll(v, delta)

    def _on_wheel_input(self, controller, _dx, _dy):
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            return False  # Ctrl+wheel is zoom, not scrolling
        self._last_scroll_input = GLib.get_monotonic_time()
        return False  # never consume — the ScrolledWindow scrolls

    def _on_scroll_key_input(self, _controller, keyval, _keycode, _state):
        if keyval in self._SCROLL_KEYVALS:
            self._last_scroll_input = GLib.get_monotonic_time()
        return False

    def _on_scrollbar_pressed(self):
        self._scrollbar_held = True

    def _on_scrollbar_released(self, *_args):
        self._scrollbar_held = False
        self._last_scroll_input = GLib.get_monotonic_time()

    def _user_scroll_recent(self):
        """Did the reader actually touch a scroll input lately? (Wheel
        ticks animate the adjustment for a few hundred ms; a held
        scrollbar counts for as long as it's held.)"""
        return (self._scrollbar_held
                or GLib.get_monotonic_time() - self._last_scroll_input
                < 1_500_000)

    def _mark_programmatic_scroll(self, ms=400):
        """Call before (or while) moving the reading scroll from code —
        renders, verse navigation, anchor restores. _on_reading_scroll
        ignores adjustment changes until the deadline passes, so layout
        work never flips the toolbar."""
        self._ignore_scroll_until = GLib.get_monotonic_time() + ms * 1000

    # ── Anchor capture / apply / settle / pins ───────────────────────────────

    def _on_viewport_resized(self):
        """Viewport height changed (lexicon paned, window resize). The
        text layout re-estimates line heights on resize, and with a
        constant adjustment value that silently shifts which text sits
        under the viewport. Re-assert the reading anchor — text-based, so
        immune to estimate corrections — to hold the reader's place.
        Not during the strip animation: its per-frame scroll compensation
        is authoritative there, and re-asserting the (stale) anchor
        would fight it. Deduped — a divider drag fires per-frame height
        changes, and each apply spawns its own correction sources."""
        if (not self._chrome.is_animating()
                and not self._anchor_apply_pending
                and self._reading_anchor is not None
                and self._rendered_verses):
            self._anchor_apply_pending = True

            def apply():
                self._anchor_apply_pending = False
                if self._reading_anchor is not None:
                    self._apply_scroll_anchor(self._reading_anchor)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(apply)

    def _settle_capture_anchor(self):
        """Runs shortly after a scroll settles: record the new reading
        locus so a later resize/re-render can hold it. If the adjustment
        is still moving (a pending scroll_to completing, validation
        churn), re-arm instead of capturing a mid-flight position — a
        resize would then faithfully restore the wrong place."""
        self._anchor_capture_id = 0
        quiet_for = GLib.get_monotonic_time() - self._last_value_change
        if quiet_for < 200_000 and self._settle_retries < 20:
            self._settle_retries += 1
            self._schedule_anchor_capture()
            return GLib.SOURCE_REMOVE
        self._settle_retries = 0
        self._capture_scroll_anchor()
        return GLib.SOURCE_REMOVE

    def _schedule_anchor_capture(self, ms=250):
        """(Re)arm the post-scroll anchor capture — called for user scrolls
        and for programmatic jumps alike, so a reading anchor exists at
        (nearly) all times for resizes to re-assert. Retries are counted
        in _settle_capture_anchor; a fresh schedule resets them."""
        if self._anchor_capture_id:
            GLib.source_remove(self._anchor_capture_id)
            self._settle_retries = 0
        self._anchor_capture_id = GLib.timeout_add(
            ms, self._settle_capture_anchor)

    def _capture_scroll_anchor(self):
        """Pixel-exact reading locus at the viewport top: (verse, char
        offset within the verse's rendered range, px of the anchor line
        already scrolled past the top edge). The restore counterpart is
        _apply_scroll_anchor. Returns None when nothing anchorable is
        rendered — callers fall back to the coarser top-verse probe."""
        if not self._view.get_realized() or self._rendered_verses is None:
            return None
        # The user hasn't scrolled since the last capture/restore — their
        # reading locus is, by definition, where we last anchored it.
        # Reusing it makes toggle round-trips exact instead of re-deriving
        # (and re-erring) from geometry every time.
        if self._reading_anchor is not None:
            return self._reading_anchor
        adj = self._reading_scroll.get_vadjustment()
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT,
            max(40, self._view.get_left_margin() + 20), 1)
        # by, NOT adj+1: window→buffer conversion subtracts the view's top
        # margin, and the snap below must compare get_iter_location values
        # (same layout frame as by) against the converted probe — mixing
        # frames put the reference more than a line off and made the
        # snap flip-flop.
        probe_y = by
        ok, it = self._view.get_iter_at_location(bx, by)
        if not ok:
            return None
        # get_iter_at_location can land a display line off when the probe
        # falls into inter-line spacing (pixels_below_lines / CSS
        # line-height). Snap along display lines until the iter's own
        # reported box (per get_iter_location — the same measurement the
        # restore uses) is the last one starting at or above the probe.
        # Without this the captured pixel delta exceeds a line height and
        # every capture→restore round trip ratchets the view up one line.
        loc = self._view.get_iter_location(it)
        guard = 0
        while loc.y > probe_y and guard < 8:
            if not self._view.backward_display_line(it):
                break
            loc = self._view.get_iter_location(it)
            guard += 1
        while guard < 8:
            nxt = it.copy()
            if not self._view.forward_display_line(nxt):
                break
            nloc = self._view.get_iter_location(nxt)
            if nloc.y <= probe_y:
                it, loc = nxt, nloc
                guard += 1
            else:
                break
        vtag = None
        hops = 0
        while vtag is None:
            for tag in it.get_tags():
                name = tag.get_property('name') or ''
                if name.startswith('vnum_'):
                    vtag = tag
                    break
            if vtag is None:
                # The probe landed on untagged content (chapter heading,
                # blank line). Walk forward to the first verse on screen
                # instead of giving up — a miss here used to mean "jump
                # to the chapter start". Anonymous span tags toggle often,
                # so allow a generous number of hops.
                hops += 1
                if hops > 32 or not it.forward_to_tag_toggle(None):
                    return None
        try:
            verse = int(vtag.get_property('name').split('_', 1)[1])
        except (ValueError, IndexError):
            return None
        start = it.copy()
        if not start.starts_tag(vtag):
            start.backward_to_tag_toggle(vtag)
        # Count visible-text chars only, skipping footnote-marker glyphs
        # (fnote: tags): markers come and go with the f* toggle, so an
        # offset counted over them can't round-trip between the two buffer
        # states — the residual one-line-per-toggle walk the toggle had.
        offset_in_verse = _visible_chars_between(start, it)
        # Negative when the anchor sits below the viewport top (heading
        # case above) — the restore then reproduces that gap exactly.
        delta = adj.get_value() - self._view.get_iter_location(it).y
        self._reading_anchor = (verse, offset_in_verse, delta)
        return self._reading_anchor

    def _apply_scroll_anchor(self, anchor):
        """Scroll so the anchored character's line sits at the same pixel
        offset from the viewport top as when it was captured. scroll_to_mark
        does the rough placement (its pending-scroll survives GTK's lazy
        line validation, which a bare set_value does not), then corrective
        passes re-assert the exact pixel once geometry has settled."""
        verse, offset_in_verse, delta = anchor
        self._mark_programmatic_scroll()
        verse = self._resolve_present_verse(verse)
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse}')
        if tag is None:
            return GLib.SOURCE_REMOVE
        it = self._buffer.get_start_iter()
        if not it.has_tag(tag) and not it.forward_to_tag_toggle(tag):
            return GLib.SOURCE_REMOVE
        end = it.copy()
        end.forward_to_tag_toggle(tag)
        # Advance offset_in_verse VISIBLE chars (mirror of the capture's
        # marker-skipping count), stopping at the verse edge.
        _forward_visible_chars(it, offset_in_verse, end)
        mark = self._buffer.create_mark(None, it, True)
        self._view.scroll_to_mark(mark, 0.0, True, 0.0, 0.0)
        seq = self._anchor_seq
        input_t0 = self._last_scroll_input
        state = {'last_y': None, 'polls': 0}

        def stale():
            # Superseded by a newer render, the user grabbed the wheel or
            # scrollbar mid-correction (their motion wins), or the chrome
            # strip is animating (its per-frame compensation owns the
            # adjustment) — stop steering.
            return (seq != self._anchor_seq
                    or self._scrollbar_held
                    or self._chrome.is_animating()
                    or self._last_scroll_input != input_t0)

        def reassert():
            if mark.get_deleted():
                return False
            if stale():
                self._buffer.delete_mark(mark)
                return False
            self._mark_programmatic_scroll()
            loc = self._view.get_iter_location(
                self._buffer.get_iter_at_mark(mark))
            self._reading_scroll.get_vadjustment().set_value(loc.y + delta)
            return loc.y

        def correct():
            y = reassert()
            if y is False:
                return GLib.SOURCE_REMOVE
            state['polls'] += 1
            # GTK keeps revalidating line-height estimates for a while
            # after a render or resize, shifting geometry under earlier
            # corrections — poll until the anchor's y stops moving.
            if y == state['last_y'] or state['polls'] >= 12:
                self._buffer.delete_mark(mark)
                return GLib.SOURCE_REMOVE
            state['last_y'] = y
            GLib.timeout_add(120, correct)
            return GLib.SOURCE_REMOVE

        def pin(_widget, _clock):
            # Frame-rate glue while validation churns: without it the
            # 120ms polls visibly chase the shifting layout (the "text
            # moves around a bit" on lexicon-panel open). Never deletes
            # the mark — the poll loop owns cleanup and stops this by
            # deleting it.
            if mark.get_deleted() or stale():
                return GLib.SOURCE_REMOVE
            reassert()
            return GLib.SOURCE_CONTINUE

        # Default-idle runs after GTK's validation cycle (and with it
        # scroll_to_mark's pending scroll). The tick callback rides the
        # frame clock, which may not tick headless — the poll loop is the
        # fallback that always runs.
        GLib.idle_add(correct)
        self._view.add_tick_callback(pin)
        return GLib.SOURCE_REMOVE

    def _find_topmost_visible_verse(self):
        if not self._view.get_realized():
            return None
        bx, by = self._view.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT,
            max(40, self._view.get_left_margin() + 20),
            4,
        )
        ok, it = self._view.get_iter_at_location(bx, by)
        if not ok:
            return None
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith('vnum_'):
                try:
                    return int(name.split('_', 1)[1])
                except (ValueError, IndexError):
                    continue
        return None

    def _resolve_present_verse(self, verse_num):
        """Map a requested verse to one actually rendered this chapter.
        If the exact verse is missing (e.g. an inner verse of a \\v 1-2
        bridge, or a stale cross-ref from a different versification), fall
        back to the nearest preceding verse so navigation lands on real
        text instead of nowhere."""
        present = self._present_verses
        if not present or verse_num in present:
            return verse_num
        earlier = [v for v in present if v < verse_num]
        return max(earlier) if earlier else verse_num

    def _scroll_to_verse_silent(self, verse_num):
        self._mark_programmatic_scroll()
        self._reading_anchor = None  # a jump IS a new reading locus
        self._schedule_anchor_capture(400)  # …and worth holding, too
        verse_num = self._resolve_present_verse(verse_num)
        tag = self._buffer.get_tag_table().lookup(f'vnum_{verse_num}')
        if not tag:
            return GLib.SOURCE_REMOVE
        it = self._buffer.get_start_iter()
        if not it.has_tag(tag):
            if not it.forward_to_tag_toggle(tag):
                return GLib.SOURCE_REMOVE
        mark = self._buffer.create_mark(None, it, True)
        self._view.scroll_to_mark(mark, 0.0, True, 0.0, 0.0)
        self._buffer.delete_mark(mark)
        return GLib.SOURCE_REMOVE
