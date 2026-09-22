"""The pane's peek: the small popover that answers a double-clicked word.

One reused, non-autohide popover per pane carries three kinds of peek — a
dictionary look-up, a footnote, and the lexicon panel's verse peek — so the
dismissal paths (a click in the view, Escape, a module change, a newer look-up)
cover all of them. It shows invisibly and is revealed once it has survived the
relayout a click sets off in the other pane; see `_ensure_peek_popover`.

Moved out of pane.py whole. The method bodies read the pane's state through
the proxies below exactly as they did inline; the pane stays the owner of the
view, the buffer and the reading position.
"""
import re

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango

import a11y
import content
import genealogy_bridge
import motion
import sword_bridge
import tasks
import word_links
from a11y import set_accessible_label
from gtk_utils import clear_children
from i18n import _, ngettext


def _html_to_markup(html, dark):
    # The reading view's converter. Imported at call time: pane.py imports
    # this module, so importing it back at the top would be a cycle.
    from pane import _html_to_markup as convert
    return convert(html, dark)


_DICT_SHORT_NAMES = {
    # Hand-tuned for common SWORD dict modules where the heuristic below
    # would otherwise pick a less recognisable form.
    'Easton':       "Easton's",
    'Smith':        "Smith's",
    'ISBE':         'ISBE',
    'Naves':        "Nave's",
    'Torreys':      "Torrey's",
    'WebstersDict': "Webster's 1913",
    'Wikcionario':  'Wikcionario',
}

_DICT_FLUFF_WORDS = {
    'dictionary', 'encyclopedia', 'revised', 'unabridged',
    'concise', 'of', 'the', 'english', 'language', 'bible',
    'topical', 'textbook', 'a', 'an',
    # Spanish — the app ships a Spanish interface and now a Spanish
    # dictionary, whose Description is generic in exactly the same way.
    'diccionario', 'enciclopedia', 'general', 'español', 'española',
    'lengua',
}

def _short_dict_title(mod_name, mod_desc):
    """Compact label for the dict popup tabs. SWORD descriptions can run
    to ~60 chars (e.g. "Webster's 1913 Revised Unabridged Dictionary of
    the English Language"), which wraps the StackSwitcher awkwardly and
    pushes tabs off the popup edges. Prefer a known short name; fall back
    to first 1-2 distinctive words from the description plus any
    4-digit year."""
    if mod_name in _DICT_SHORT_NAMES:
        return _DICT_SHORT_NAMES[mod_name]
    words = []
    year = None
    for raw in mod_desc.split():
        clean = raw.rstrip(',.;:').strip()
        if not clean:
            continue
        if re.fullmatch(r'\d{4}', clean):
            year = clean
            continue
        # A dash or bullet separating the name from its blurb is not a word:
        # counting it as one spent half the two-word budget and left the
        # label trailing a dangling em dash ("Wikcionario —").
        if not re.search(r'\w', clean):
            continue
        if clean.lower() in _DICT_FLUFF_WORDS:
            break
        words.append(clean)
        if len(words) >= 2:
            break
    short = ' '.join(words) if words else mod_name
    return f'{short} {year}' if year else short

def _strip_leading_headword(html, word):
    """Drop a leading headword that duplicates the peek's serif title (plus
    any indent the SWORD HTML carries). Best-effort: if nothing matches, the
    body is returned unchanged.
    """
    stripped = re.sub(
        r'^\s*(?:<[^>]+>\s*)*' + re.escape(word)
        # A middle dot means the word heads a compound label
        # ("dios · Sustantivo masculino"), where dropping the word
        # alone would strand the separator. Leave those whole.
        + r'(?!\s*·)'
        + r'(?:\s*</[^>]+>)*\s*(?:<br\s*/?>|[—:.\-,])?\s*',
        '', html, count=1, flags=re.IGNORECASE)
    return re.sub(r'^(?:\s| |&nbsp;)+', '', stripped)


class PeekController:

    def __init__(self, pane):
        self._pane = pane
        #: The shared popover, built on first use.
        self.pop = None
        # The self-heal's state: True while the reader (or this code) closed
        # the peek on purpose; how many reshows this show has spent; when it
        # opened; the pending reveal; the running fade.
        self._dict_user_closed = False
        self._dict_retries = 0
        self._dict_open_at = 0
        self._dict_reveal_timer = 0
        self._peek_fade = None
        # The dictionary body's height cap, and the verse the looked-up word
        # sits in (the genealogy fragment disambiguates on it).
        self._dict_max_body = 320
        self._peek_verse = 0

    # ── Proxies to pane-owned state ──────────────────────────────────────────

    @property
    def _view(self):
        return self._pane.view

    @property
    def _buffer(self):
        return self._pane._buffer

    @property
    def _book(self):
        return self._pane.book

    @property
    def _chapter(self):
        return self._pane.chapter

    @property
    def _module(self):
        return self._pane.module

    @property
    def _chapter_footnotes(self):
        return self._pane._chapter_footnotes

    @property
    def _lex_panel(self):
        return self._pane._lex_panel

    @property
    def _on_open_lineage(self):
        return self._pane._on_open_lineage

    @property
    def _hover_gloss_range(self):
        return self._pane._hover_gloss_range

    @_hover_gloss_range.setter
    def _hover_gloss_range(self, value):
        self._pane._hover_gloss_range = value

    def on_dict_click(self, gesture, n_press, x, y):
        # Any click in the view dismisses an open dict peek (it's non-autohide,
        # so we close it ourselves).
        existing = self.pop
        if existing is not None and existing.get_visible():
            self._dict_user_closed = True
            existing.popdown()
        if n_press != 2:
            return
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return
        # Suppress on navigation links (devref) and footnote markers (the
        # first click already opened the note peek); Strong's-tagged words
        # should still open the dict popup on double-click — the lexicon
        # opens on the first click, the dict on the second.
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith(('devref:', 'fnote:')):
                return
        word_start = it.copy()
        word_end = it.copy()
        if not word_start.starts_word():
            word_start.backward_word_start()
        if not word_end.ends_word():
            word_end.forward_word_end()
        word = self._buffer.get_text(word_start, word_end, False).strip()
        if word and word.replace("'", '').replace('’', '').isalpha():
            offset = word_start.get_offset()
            # Small defer off the click dispatch; the popover shows invisibly
            # and is revealed only once stable, so we don't need to wait out
            # the relayout cascade here.
            GLib.timeout_add(100, self.show_dict_popup, word, offset)

    def attach_to_label(self, label):
        """Wire the double-click dictionary peek onto a card label (commentary
        quote, caption, archaeology body). Makes the text selectable so GTK's
        native double-click selects the word; a CAPTURE-phase click then reads
        that selection and shows the same peek used in the reading view."""
        if label is None:
            return
        label.set_selectable(True)
        g = Gtk.GestureClick.new()
        g.set_button(1)
        g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        g.connect('pressed', self._on_label_dict_click, label)
        label.add_controller(g)

    def _on_label_dict_click(self, gesture, n_press, x, y, label):
        # Any click dismisses an open peek (it's non-autohide). Defer the
        # lookup so the label has settled its native double-click selection.
        existing = self.pop
        if existing is not None and existing.get_visible():
            self._dict_user_closed = True
            existing.popdown()
        if n_press == 2:
            GLib.timeout_add(50, self._label_dict_lookup, label, int(x), int(y))

    def _label_dict_lookup(self, label, x, y):
        non_empty, s, e = label.get_selection_bounds()
        if non_empty:
            word = label.get_text()[s:e].strip()
            if word and word.replace("'", '').replace('’', '').isalpha():
                rect = Gdk.Rectangle()
                rect.x, rect.y, rect.width, rect.height = x, y, 1, 1
                self.show_dict_popup_at(word, label, rect)
        return GLib.SOURCE_REMOVE

    def _dict_reshow(self, pop):
        """Re-show the dict peek after the relayout cascade unmapped it (see
        the self-heal note in _show_dict_popup). Still invisible (opacity 0)
        until it survives long enough to be revealed."""
        if self.pop is pop and not self._dict_user_closed:
            pop.set_opacity(0.0)
            pop.popup()
            self._dict_arm_reveal(pop)
        return GLib.SOURCE_REMOVE

    def _dict_arm_reveal(self, pop):
        """Reveal the peek once it has stayed mapped briefly — i.e. the
        relayout cascade is over. Re-armed on every (re)show and cancelled
        whenever a close interrupts, so opacity only reaches 1 on a stable
        show and the user never sees the intervening churn."""
        if self._dict_reveal_timer:
            GLib.source_remove(self._dict_reveal_timer)
        self._dict_reveal_timer = GLib.timeout_add(130, self._dict_reveal, pop)

    def _dict_reveal(self, pop):
        self._dict_reveal_timer = 0
        if self.pop is pop and not self._dict_user_closed:
            self._peek_fade_in(pop)
        return GLib.SOURCE_REMOVE

    def _peek_fade_in(self, pop):
        """Fade the stable peek up to full opacity (EASE_FADE) instead of a
        hard flip — the reveal step only; the show-when-stable/self-heal
        choreography around it is untouched. Adw.TimedAnimation follows
        gtk-enable-animations, so reduced motion collapses this back to
        the instant flip."""
        prev = self._peek_fade
        if prev is not None:
            prev.pause()
        target = Adw.PropertyAnimationTarget.new(pop, 'opacity')
        anim = Adw.TimedAnimation.new(
            pop, pop.get_opacity(), 1.0, motion.DURATION_MICRO, target)
        anim.set_easing(motion.EASE_FADE)
        self._peek_fade = anim
        anim.play()

    def dismiss(self):
        """Close an open dictionary peek. Returns True if one was open — the
        window's Escape handler uses this (the peek is non-focusable, so it
        never sees the key itself)."""
        self._hover_gloss_range = None  # a dismissed gloss can re-dwell
        pop = self.pop
        if pop is not None and pop.get_visible():
            self._dict_user_closed = True
            pop.popdown()
            return True
        return False

    def _peek_room(self, anchor_widget, rect, pop):
        """Point `pop` at whichever side of `rect` has more room, and return
        the pixels available on that side.

        A popover taller than the window is never placed: GTK closes it the
        moment it is shown, the self-heal reshows it, and after twelve rounds
        the peek is simply unopenable. So every peek whose body can run long
        measures the room first and caps itself to it (_peek_scroller). Room
        is measured in the window, where the popover actually lives — it can
        extend up over the toolbar."""
        root = anchor_widget.get_root()
        y, win_h = rect.y, anchor_widget.get_height()
        if root is not None:
            ok, pt = anchor_widget.compute_point(
                root, Graphene.Point().init(float(rect.x), float(rect.y)))
            if ok:
                y = pt.y
            win_h = root.get_height()
        above, below = y, win_h - (y + rect.height)
        if above > below:
            pop.set_position(Gtk.PositionType.TOP)
            return above
        pop.set_position(Gtk.PositionType.BOTTOM)
        return below

    @staticmethod
    def _peek_scroller(child, avail, chrome=86):
        """Wrap a peek's body so a long one scrolls inside the popover instead
        of demanding a height that cannot be placed. `chrome` is what the
        popover spends around the body — caption, margins, arrow. A short body
        keeps its natural height and never shows a bar."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(int(max(140, min(420, avail - chrome))))
        scroll.set_child(child)
        return scroll

    def show_anchored(self, anchor_widget, rect, content):
        """Show `content` in the shared self-healing peek popover, anchored
        at `rect` in `anchor_widget`. The lexicon panel's verse peek rides
        the same instance as the dictionary/footnote peeks, so the reshow-
        until-stable machinery and the dismissal paths (Escape, module
        change, new lookup) cover it too.

        `content` arrives whole (header and body together), so the cap wraps
        all of it: a long verse or gloss scrolls with its own caption rather
        than being unopenable."""
        pop = self._ensure_peek_popover(anchor_widget)
        # A dictionary fetch already in flight can't replace this peek's
        # content when it returns.
        tasks.cancel(f'peek:{id(self._pane)}')
        avail = self._peek_room(anchor_widget, rect, pop)
        pop.set_pointing_to(rect)
        pop.set_child(self._peek_scroller(content, avail, chrome=40))
        # Invisible until it has survived the post-click relayout churn —
        # the same show-when-stable dance as the dictionary peek.
        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._dict_arm_reveal(pop)

    def dismiss_lexicon_peek(self):
        """Dismiss the shared peek only when it's the lexicon panel's verse
        peek (anchored on the def view) — clicks inside the lexicon must
        not reach across and close a reading-view dict/footnote peek."""
        pop = self.pop
        if (pop is not None and pop.get_visible()
                and pop.get_parent() is self._lex_panel.def_view):
            self._dict_user_closed = True
            pop.popdown()

    def _verse_at_offset(self, offset):
        """The verse number a buffer offset falls in, or 0.

        The genealogy table disambiguates on the verse — one name covers many
        people, and "this Jacob" means the one this verse is about. The
        `vnum_` tags are already on the text; the right-click menu reads them
        the same way."""
        it = self._buffer.get_iter_at_offset(offset)
        for tag in it.get_tags():
            name = tag.get_property('name') or ''
            if name.startswith('vnum_'):
                try:
                    return int(name.split('_')[1])
                except (ValueError, IndexError):
                    return 0
        return 0

    def show_dict_popup(self, word, word_offset):
        # TextView entry point: compute the word's rectangle in the view's
        # widget coords, then hand off to the shared peek anchored on the view.
        self._peek_verse = self._verse_at_offset(word_offset)
        start = self._buffer.get_iter_at_offset(word_offset)
        end = start.copy()
        if not end.ends_word():
            end.forward_word_end()
        r1 = self._view.get_iter_location(start)
        r2 = self._view.get_iter_location(end)
        wx1, wy1 = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r1.x, r1.y)
        wx2, _wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r2.x, r2.y)
        rect = Gdk.Rectangle()
        rect.x = wx1
        rect.y = wy1
        rect.width = max(1, wx2 - wx1) if r2.y == r1.y else max(1, r1.width)
        rect.height = r1.height
        self.show_dict_popup_at(word, self._view, rect,
                                strongs=self._strongs_at_offset(word_offset))

    def _strongs_at_offset(self, offset):
        """The Strong's numbers the text tags this word with, or ()."""
        it = self._buffer.get_iter_at_offset(offset)
        return tuple(name[5:] for tag in it.get_tags()
                     if (name := tag.get_property('name') or '')
                     .startswith('strg:'))

    def _ensure_peek_popover(self, anchor_widget):
        """The shared non-autohide peek popover — dictionary look-ups and
        footnote markers use the same reused instance, so the dismissal
        paths (click in view, Esc, module change) cover both. Created once
        per pane with the self-heal closed-handler; re-parented to whichever
        widget anchors the current peek."""
        # Guard the self-heal (below) against our own teardown/rebuild: True
        # while we intentionally close or replace the popover.
        self._dict_user_closed = True
        # Whatever shows next isn't the hover gloss (the gloss path re-sets
        # this after the show) — so the grace machinery can't dismiss a
        # click-opened peek.
        self._hover_gloss_range = None
        pop = self.pop
        if pop is None:
            pop = Gtk.Popover()
            pop.set_has_arrow(True)
            pop.set_autohide(False)
            pop.set_can_focus(False)
            # Clicking a word re-renders the other pane (cross-pane verse
            # sync); that relayout cascade unmaps a freshly-shown popover no
            # matter where it's parented — a Gtk.Popover can't survive a
            # concurrent relayout. So self-heal: if it's torn down within the
            # settle window and the user didn't dismiss it, re-show until the
            # layout goes quiet (the stable state the popover lives in).
            def _on_closed(p):
                # Cancel a pending reveal — the show was interrupted, so it
                # wasn't stable; the next reshow re-arms it. An in-flight
                # fade is stopped too, or its remaining frames would fight
                # the reshow's opacity-0.
                if self._dict_reveal_timer:
                    GLib.source_remove(self._dict_reveal_timer)
                    self._dict_reveal_timer = 0
                fade = self._peek_fade
                if fade is not None:
                    fade.pause()
                    self._peek_fade = None
                if (not self._dict_user_closed
                        and self.pop is p
                        and self._dict_retries < 12
                        and GLib.get_monotonic_time() - self._dict_open_at
                        < 1_200_000):
                    self._dict_retries += 1
                    GLib.timeout_add(60, self._dict_reshow, p)
            pop.connect('closed', _on_closed)
            self.pop = pop
        else:
            pop.popdown()
        # Parent to the anchor widget so the arrow anchors on the word in that
        # widget's own coordinate space (parenting elsewhere mis-anchors it).
        # Re-parent when the lookup comes from a different widget (e.g. the
        # reading view vs. a commentary card label).
        if pop.get_parent() is not anchor_widget:
            if pop.get_parent() is not None:
                pop.unparent()
            pop.set_parent(anchor_widget)
        return pop

    def show_footnote_peek(self, key, it):
        """Show a footnote's body in the shared peek popover, anchored at
        the clicked marker letter. `key` is '{verse}:{n}' from the fnote:
        tag. Content is already in memory (no fetch), and the click doesn't
        trigger a cross-pane re-render, so unlike the dictionary peek this
        shows immediately — no stability wait, just the shared fade-in —
        and the self-heal machinery stays armed anyway in case some other
        relayout lands on it."""
        try:
            verse_s, n = key.split(':', 1)
            verse = int(verse_s)
        except ValueError:
            return
        entry = self._chapter_footnotes.get((verse, n))
        if not entry:
            return
        ftype, body, letter = entry
        r = self._view.get_iter_location(it)
        wx, wy = self._view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, r.x, r.y)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = (
            wx, wy, max(1, r.width), r.height)

        pop = self._ensure_peek_popover(self._view)
        # A dictionary fetch already in flight can't replace this note's
        # content when it returns.
        tasks.cancel(f'peek:{id(self._pane)}')
        # Open on whichever side of the marker has more room, and cap the body
        # to what fits there. A translator's note is one line; a commentator's
        # is an essay (Straubinger writes 2,377 characters on Psalm 51:13), and
        # an uncapped peek that tall is unopenable — see _peek_room. That is
        # why the failure looked arbitrary: a short note two lines below the
        # unopenable one opened first time.
        avail = self._peek_room(self._view, rect, pop)
        pop.set_pointing_to(rect)

        dark = Adw.StyleManager.get_default().get_dark()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_size_request(280, -1)
        cap_text = (_('Cross-references ({letter}) · verse {v}')
                    if ftype == 'crossReference'
                    else _('Footnote ({letter}) · verse {v}')).format(
                        letter=letter, v=verse)
        cap = Gtk.Label(label=cap_text, xalign=0)
        cap.add_css_class('caption')
        cap.add_css_class('dim-label')
        content.append(cap)
        lbl = Gtk.Label(xalign=0, wrap=True)
        lbl.add_css_class('fnote-body')
        lbl.set_max_width_chars(40)
        try:
            lbl.set_markup(_html_to_markup(body, dark))
        except Exception:
            lbl.set_text(re.sub(r'<[^>]+>', '', body))
        # The caption stays put and only the note scrolls, so a long note
        # keeps the letter and verse it belongs to in view.
        content.append(self._peek_scroller(lbl, avail))
        for m in ('top', 'bottom', 'start', 'end'):
            getattr(content, f'set_margin_{m}')(14)
        pop.set_child(content)
        # The peek is a transient panel the reader opened deliberately, and
        # its body never takes focus — announce it, or the note is silent.
        a11y.set_role(content, Gtk.AccessibleRole.NOTE)
        set_accessible_label(content, cap_text)
        a11y.labelled_by(lbl, cap)
        a11y.announce(self._view, f'{cap_text}. {lbl.get_text()}')

        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._peek_fade_in(pop)

    def show_dict_popup_at(self, word, anchor_widget, rect, strongs=()):
        # A lightweight "Look Up" peek anchored at the double-clicked word,
        # not a detached window centred on the screen. Deep study still goes
        # through the Strong's lexicon panel. `anchor_widget`/`rect` say where
        # to point the arrow (the reading view, or a card label).
        #
        # The popover is *non-autohide* and reused per pane: an autohide
        # popover grabs the pointer the instant it's shown, so the very
        # double-click that opened it would read as a click-outside and dismiss
        # it. We dismiss it ourselves instead — on any click in the view
        # (_on_dict_click), a new lookup, or a module change.

        pop = self._ensure_peek_popover(anchor_widget)

        # Open the peek on whichever side of the word has more room, and cap
        # the definition height so the whole popover *fits* on that side. If it
        # doesn't fit, GTK flips it to the other side but strands the arrow on
        # the original edge (pointing away from the word) — capping avoids the
        # flip entirely. Room is measured in the window, where the popover
        # actually lives (it can extend up over the toolbar).
        root = anchor_widget.get_root()
        ok, pt = anchor_widget.compute_point(
            root, Graphene.Point().init(float(rect.x), float(rect.y)))
        word_y = pt.y if ok else rect.y
        win_h = root.get_height() if root is not None else anchor_widget.get_height()
        room_above = word_y
        room_below = win_h - (word_y + rect.height)
        if room_above > room_below:
            pop.set_position(Gtk.PositionType.TOP)
            avail = room_above
        else:
            pop.set_position(Gtk.PositionType.BOTTOM)
            avail = room_below
        # ~130px is the title + tabs + popover chrome above the scrolled body.
        self._dict_max_body = int(max(140, min(320, avail - 130)))
        pop.set_pointing_to(rect)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # Cap to the window width so the popover doesn't overflow a narrow
        # window; 360 is the comfortable width when there's room.
        _root = self._pane.get_root()
        _win_w = _root.get_width() if _root is not None else 0
        body.set_size_request(
            360 if _win_w <= 0 else max(260, min(360, _win_w - 24)), -1)
        pop.set_child(body)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(28)
        spinner.set_margin_bottom(28)
        spinner.set_halign(Gtk.Align.CENTER)
        body.append(spinner)
        # Arm the self-heal, then show *invisibly*: the relayout cascade may
        # unmap the popover a few times before the layout settles. Opacity 0
        # until it has stayed up briefly (see _dict_arm_reveal) hides that
        # churn — the user only ever sees the final, stable peek. (Shown with a
        # spinner first so the wrapped TextView can measure its natural height
        # once mapped; building before showing collapses it to a sliver.)
        self._dict_retries = 0
        self._dict_open_at = GLib.get_monotonic_time()
        self._dict_user_closed = False
        pop.set_opacity(0.0)
        pop.popup()
        self._dict_arm_reveal(pop)

        def _clear():
            clear_children(body)

        def _status(icon, title, desc):
            # Hand-built (not Adw.StatusPage): StatusPage is vexpand and
            # collapses in a small popover, leaving the disclaimer invisible.
            # A plain box reports a real natural height the popover sizes to.
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_margin_top(22)
            box.set_margin_bottom(22)
            box.set_margin_start(24)
            box.set_margin_end(24)
            box.set_valign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(36)
            img.add_css_class('dim-label')
            box.append(img)
            t = Gtk.Label(label=title)
            t.add_css_class('title-4')
            t.set_wrap(True)
            t.set_justify(Gtk.Justification.CENTER)
            box.append(t)
            d = Gtk.Label(label=desc)
            d.add_css_class('dim-label')
            d.set_wrap(True)
            d.set_justify(Gtk.Justification.CENTER)
            d.set_max_width_chars(34)
            box.append(d)
            body.append(box)

        def _headword_title(text):
            # Serif title echoing the app's chapter headings, so the peek
            # reads as a Scriptura entry rather than a system tooltip.
            lbl = Gtk.Label(label=text[:1].upper() + text[1:], xalign=0)
            lbl.add_css_class('dict-headword')
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_margin_start(18)
            lbl.set_margin_end(18)
            lbl.set_margin_top(10)
            lbl.set_margin_bottom(2)
            return lbl

        def _strip_headword(html):
            return _strip_leading_headword(html, word)

        def _add_text(html, box=None, source=None):
            if box is None:
                box = body
            dark = Adw.StyleManager.get_default().get_dark()
            # Source attribution for the single-dictionary case (the tabs carry
            # it when there are several).
            if source:
                cap = Gtk.Label(label=source, xalign=0)
                cap.add_css_class('caption')
                cap.add_css_class('dim-label')
                cap.set_margin_start(18)
                cap.set_margin_bottom(6)
                box.append(cap)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_propagate_natural_height(True)
            scroll.set_max_content_height(self._dict_max_body)
            # Floor the body so a long entry can't collapse to a sliver when
            # the natural-height measurement under-reports (it does for some
            # popover positions). A short entry sits in this min with a little
            # slack rather than scrolling.
            scroll.set_min_content_height(min(self._dict_max_body, 200))
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_wrap_mode(Gtk.WrapMode.WORD)
            tv.set_left_margin(18)
            tv.set_right_margin(18)
            tv.set_top_margin(4)
            tv.set_bottom_margin(14)
            # Breathe — the app reads generously everywhere else.
            tv.set_pixels_below_lines(3)
            tv.set_pixels_inside_wrap(3)
            buf = tv.get_buffer()
            html = _strip_headword(html)
            markup = _html_to_markup(html, dark)
            try:
                buf.insert_markup(buf.get_end_iter(), markup, -1)
            except Exception:
                buf.set_text(re.sub(r'<[^>]+>', '', html))
            scroll.set_child(tv)
            box.append(scroll)

        def _build_source_tabs(results):
            # Underline tabs matching the module picker, not a chunky
            # StackSwitcher.
            tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            tabs.add_css_class('module-tabs')
            tabs.set_halign(Gtk.Align.START)
            tabs.set_margin_start(10)
            tabs.set_margin_top(2)
            tabs.set_margin_bottom(7)
            stack = Gtk.Stack()
            stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            stack.set_transition_duration(120)
            stack.set_vhomogeneous(False)
            btns: dict = {}

            def _on_tab(btn, mn):
                if not btn.get_active():
                    if stack.get_visible_child_name() == mn:
                        btn.set_active(True)   # enforce exactly-one
                    return
                # Switch first, then clear the others — deactivating a sibling
                # re-enters this handler, and it must see the new selection so
                # it doesn't snap itself back on.
                stack.set_visible_child_name(mn)
                for k, b in btns.items():
                    if k != mn and b.get_active():
                        b.set_active(False)

            # Already ranked by `fetch` — re-sorting here by description
            # is what put Webster's 1913 in front of Wikcionario.
            ordered = results
            for mn, md, html in ordered:
                page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                _add_text(html, page)
                stack.add_named(page, mn)
                btn = Gtk.ToggleButton(label=_short_dict_title(mn, md))
                btns[mn] = btn
                btn.connect('toggled', _on_tab, mn)
                tabs.append(btn)
            first = ordered[0][0]
            btns[first].set_active(True)
            stack.set_visible_child_name(first)
            body.append(tabs)
            body.append(stack)

        def _lineage_fragment():
            """The compact 'who were their parents and children' answer, for a
            word the curated genealogy table knows.

            Text, not a drawing. The peek is a 260-360px popover with its body
            capped between 140 and 320px; a chart does not fit there, and
            anything that changes the popover's natural height can bring back
            the arrow-flip the cap exists to prevent. So the fragment's own
            measured height is taken OFF the dictionary body's cap below,
            leaving the whole peek exactly as tall as it was."""
            frag = genealogy_bridge.fragment_for(
                word, self._book, self._chapter,
                self._peek_verse or 0)
            if frag is None:
                return None
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.add_css_class('peek-lineage')
            box.set_margin_start(18)
            box.set_margin_end(18)
            box.set_margin_top(2)
            box.set_margin_bottom(8)

            def _row(label, people, muted):
                if not people:
                    return
                r = Gtk.Label(xalign=0)
                r.add_css_class('peek-lineage-row')
                if muted:
                    r.add_css_class('dim-label')
                names = ', '.join(GLib.markup_escape_text(n)
                                  for _pid, n, _ref in people)
                r.set_markup('<b>%s</b>  %s'
                             % (GLib.markup_escape_text(label), names))
                r.set_wrap(True)
                box.append(r)

            _row(_('Parents'), frag['parents'], True)
            if frag['mother']:
                _row(_('Mother'), [(frag['mother'][0], frag['mother'][1], '')],
                     True)
            _row(_('Children'), frag['children'], True)
            if frag['note']:
                nl = Gtk.Label(label=frag['note'], xalign=0)
                nl.add_css_class('peek-lineage-note')
                nl.set_wrap(True)
                box.append(nl)
            if frag['ambiguous']:
                # Never silently pick a Zechariah: say that the name covers
                # more than one person and let the reader open the chart.
                amb = Gtk.Label(xalign=0)
                amb.add_css_class('peek-lineage-note')
                amb.set_wrap(True)
                amb.set_markup(GLib.markup_escape_text(
                    ngettext('%d other person carries this name',
                             '%d other people carry this name',
                             len(frag['ambiguous'])) % len(frag['ambiguous'])))
                box.append(amb)
            if frag['chart'] and self._on_open_lineage:
                link = Gtk.Button(label=_('See the whole line'))
                link.add_css_class('flat')
                link.add_css_class('peek-lineage-link')
                link.set_halign(Gtk.Align.START)
                link.connect('clicked', lambda *_a: self._on_open_lineage(
                    self._pane, self._book, self._chapter,
                    self._peek_verse or 1))
                box.append(link)
            return box

        def populate(results):
            _clear()
            frag = _lineage_fragment()
            if frag is not None:
                body.append(frag)
                # Re-measure, do not assume: the ~130px chrome constant was
                # measured for title + tabs and knows nothing about this box.
                _min, nat = frag.measure(Gtk.Orientation.VERTICAL, -1)[:2]
                self._dict_max_body = max(
                    100, self._dict_max_body - max(nat, _min))
            if not results:
                # Names what was actually searched rather than describing what
                # dictionaries hold. The old line taught that they "index
                # proper nouns and key terms" and offered “covenant,”
                # “Abraham,” “atonement” — true of Easton's, false of the
                # general dictionary the Spanish reader has (Wikcionario
                # answers ordinary vocabulary), and the English examples were
                # the wrong words to try in any case.
                _status('scriptura-system-search-symbolic',
                        _('No entry for “%s”') % word,
                        (_('Searched %s. Another dictionary may carry it — '
                           'the Module Manager lists more.')
                         % ', '.join(searched)) if searched else
                        _('Another dictionary may carry it — the Module '
                          'Manager lists more.'))
            else:
                body.append(_headword_title(word))
                if len(results) == 1:
                    mn, md, html = results[0]
                    _add_text(html, source=_short_dict_title(mn, md))
                else:
                    _build_source_tabs(results)

        def show_no_dicts():
            _clear()
            frag = _lineage_fragment()
            if frag is not None:
                # The table answers even with no dictionary installed, which is
                # the common case in a language whose only dictionary is a
                # general one.
                body.append(_headword_title(word))
                body.append(frag)
                return
            _status('scriptura-dialog-information-symbolic',
                    _('No dictionaries installed'),
                    # Named two English dictionaries by name, which is the
                    # wrong advice for a reader who reads in Spanish.
                    _('Add one from the Module Manager, then double-click '
                      'the word again.'))

        # Filled by `fetch` so the empty state can name what it looked in.
        searched: list = []

        def fetch(_task):
            dicts = sword_bridge.installed_dict_modules()
            if not dicts:
                return None
            searched[:] = [_short_dict_title(mn, md) for mn, md in dicts]
            return self.dict_results(word, dicts, strongs=strongs)

        # Latest-wins on the shared peek key: a newer lookup, footnote, or
        # anchored peek supersedes this fetch, so a late return can't
        # overwrite the popover's current content. A raised lookup lands as
        # "no entry" instead of stranding the spinner (details in the log).
        tasks.submit(f'peek:{id(self._pane)}', fetch,
                     lambda results: (show_no_dicts() if results is None
                                      else populate(results)),
                     on_error=lambda _exc: populate([]))
        return GLib.SOURCE_REMOVE

    def dict_results(self, word, dicts, strongs=()):
        """Every dictionary that answers `word`, in the order the tabs open.

        Which tab opens matters more than which tabs exist. Two things decide
        it, in this order:

          * an exact hit beats a de-inflected one. The de-inflection is
            English, so it strips the `s` from Spanish `pues` and finds
            Webster's `Pue` — "to make a low whistling sound; to chirp, as
            birds" — a confident answer to a question nobody asked.
          * then the reading module's own language. A reader in a Spanish
            Bible should not have to click past French to reach Spanish.

        Everything still gets a tab; this only chooses which one is already
        open.

        Through content, and normalised: `sword_bridge.module_language`
        answers '' for every eBible translation, so a reader on the Nueva
        Biblia Viva — the Spanish reading tier's own Bible — had no language
        to match and got the tabs alphabetically, English first. The codes
        are normalised because eBible spells the language 'spa' where SWORD
        spells it 'es'.

        **It lives out here, and not in the closure that calls it, because
        the closure could not see the `content` module at all.** Its enclosing
        method binds a local `content` (the popover's box, now `body`), so
        `content.language_code` resolved to a `Gtk.Box` and every double-click
        raised `AttributeError` inside the task worker — which the peek
        reports as "no entry", so the dictionary looked empty rather than
        broken. At method scope there is nothing to shadow it, and the sort
        is reachable by a test that needs no display.
        """
        lang = content.language_code(self._module)
        verse = (sword_bridge.map_verse_to_app(
            self._module, self._book, self._chapter, self._peek_verse)
            if strongs and self._peek_verse else 0)
        results = []
        for mod_name, mod_desc in dicts:
            # A verse-aware link names the article this very word is about,
            # which no spelling can: it goes first, and counts as exact.
            key = word_links.key_for(mod_name, self._book, self._chapter,
                                     verse, strongs) if verse else None
            html, exact = ('', False)
            if key:
                html = sword_bridge.lookup_dict_entry(mod_name, key)[0]
                exact = bool(html)
            if not html:
                html, exact = sword_bridge.lookup_dict_entry(mod_name, word)
            if html:
                same = bool(lang) and content.language_code(mod_name) == lang
                results.append((mod_name, mod_desc, html, exact, same))
        results.sort(key=lambda r: (not r[3], not r[4], r[1].lower()))
        return [(mn, md, html) for mn, md, html, _e, _s in results]
