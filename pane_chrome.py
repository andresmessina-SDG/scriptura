"""ChromeController — the pane's auto-hiding toolbar band and its strip
compensation, extracted from BiblePane (STRUCTURAL_ANALYSIS.md §5.4 / Step 1).

Owns the chrome-reveal state (the revealed flag and the scroll-direction
accumulator) and the reveal/hide *strip animation* that keeps the reading
glyphs screen-fixed while the toolbar slides. It holds a back-reference to its
pane for the widgets it must move (the toolbar revealer, the page card's top
margin, the reading adjustment) and for the scroll-anchor collaborators it
pokes when the viewport top genuinely moves — `_reading_anchor` stays owned by
the pane's scroll machinery, which this only invalidates.

Behaviour is identical to the inline version it replaced; the scroll-stability
matrix (tools/verify-scroll-stability.py) guards every path it touches.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk

import motion


class ChromeController:
    # Reveal near the top of the chapter; otherwise a hysteresis accumulator —
    # motion in one direction accumulates and only flips the bar past a
    # threshold, biased so revealing is easier than hiding.
    TOP_DEADZONE = 64.0
    HIDE_THRESHOLD = 48.0
    SHOW_THRESHOLD = 24.0

    def __init__(self, pane):
        self._pane = pane
        self.revealed = True
        self._accum = 0.0
        # Running Adw.TimedAnimation for the chrome strip (reveal/hide), or
        # None when the strip is at rest.
        self._anim = None

    def is_animating(self):
        """Whether the strip animation currently owns the reading adjustment.
        The scroll-anchor machinery consults this: while it is True the
        per-frame strip compensation is authoritative and the anchor must not
        fight it."""
        return self._anim is not None

    def reset_accum(self):
        self._accum = 0.0

    def on_scroll(self, v, delta):
        """The chrome half of the pane's reading-scroll handler: reveal near
        the top, else accumulate directional motion past the thresholds. A
        direction reversal resets the accumulator."""
        # Always reveal near the top of the chapter.
        if v <= self.TOP_DEADZONE:
            self._accum = 0.0
            self.set_revealed(True)
            return
        if (delta > 0) != (self._accum > 0):
            self._accum = 0.0
        self._accum += delta
        if self.revealed and self._accum > self.HIDE_THRESHOLD:
            self.set_revealed(False)
        elif not self.revealed and self._accum < -self.SHOW_THRESHOLD:
            self.set_revealed(True)

    def reveal(self):
        """Force the pane toolbar back into view (tap, focus, module change)."""
        self._accum = 0.0
        self.set_revealed(True)

    def set_revealed(self, reveal):
        """Toggle the toolbar revealer, with asymmetric motion timing: exits
        are brisk (get out of the way), entrances gentler (arrive softly)."""
        if reveal == self.revealed:
            return
        self.revealed = reveal
        self._accum = 0.0
        p = self._pane
        p._toolbar_revealer.set_transition_duration(280 if reveal else 200)
        p._toolbar_revealer.set_reveal_child(reveal)
        self.animate_strip()

    def _strip_targets(self):
        """(base, toolbar) strip heights: base chrome that never auto-hides
        (the devotional date bar) and the auto-hiding toolbar."""
        p = self._pane
        base = 0
        if p._is_devotional:
            base = p._date_nav.measure(Gtk.Orientation.VERTICAL, -1)[1]
        return base, p._toolbar.measure(Gtk.Orientation.VERTICAL, -1)[1]

    def animate_strip(self):
        """Slide the page card's top edge in step with the toolbar, keeping the
        glyphs screen-fixed: each frame the card top moves by dm and the scroll
        value moves by dm with it, so hiding the chrome unveils a strip of
        earlier text (reclaiming the space) instead of dragging the page up —
        and revealing tucks it back."""
        p = self._pane
        base, tb = self._strip_targets()
        target = base + (tb if self.revealed else 0)
        if self._anim is not None:
            self._anim.pause()
            self._anim = None
        start = p._lex_paned.get_margin_top()
        if start == target:
            return
        adj = p._reading_scroll.get_vadjustment()
        last = {'m': start}

        def frame(value):
            m = round(value)
            dm = m - last['m']
            if dm == 0:
                return
            last['m'] = m
            p._lex_paned.set_margin_top(m)
            p._mark_programmatic_scroll()
            adj.set_value(adj.get_value() + dm)

        def done(_anim):
            self._anim = None
            # The viewport top edge genuinely moved — the old anchor's
            # pixel delta no longer describes the reading locus.
            p._reading_anchor = None
            p._capture_scroll_anchor()

        anim = Adw.TimedAnimation.new(
            p._lex_paned, start, target,
            (motion.DURATION_EMPHASIZED if self.revealed
             else motion.DURATION_STANDARD),
            Adw.CallbackAnimationTarget.new(frame))
        # The strip is an on-screen reposition (the card top and the scroll
        # value travel together), not an enter/exit — symmetric easing, set
        # explicitly rather than riding the library default.
        anim.set_easing(motion.EASE_MOVE)
        anim.connect('done', done)
        self._anim = anim
        anim.play()

        def force_finish():
            # A stalled frame clock (headless, hidden window) must not leave
            # the strip mid-flight and the anchor machinery suppressed — jump
            # to the end state.
            if self._anim is anim:
                anim.skip()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(600, force_finish)

    def sync_view_top_margin(self):
        """Reserve the chrome band's current strip height above the reading
        page, so the page keeps its original below-the-toolbar look — rounded
        corners, gutter and all. Reveal/hide transitions animate this margin
        with a compensating scroll (see animate_strip) so the text never rides
        along."""
        p = self._pane
        if self._anim is not None:
            self._anim.pause()
            self._anim = None
        base, tb = self._strip_targets()
        p._lex_paned.set_margin_top(base + (tb if self.revealed else 0))
