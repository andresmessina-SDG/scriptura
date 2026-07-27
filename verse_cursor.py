"""Keyboard access to the verse and word gestures (WCAG 2.1.1, Level A).

Every study action in the reading pane used to be a `Gtk.GestureClick` and
nothing else: click a verse to select it, right-click for the study menu,
click a Strong's word for the lexicon, double-click any word for the
dictionary, click a marker for the footnote. None had a keyboard path, so a
reader who cannot use a pointer could navigate the text but never act on it.

This adds the missing model: a **verse cursor** with two tiers.

* **Verse tier** — ↑/↓ move between the verses of the chapter. The cursor
  reuses the current-verse indicator the pane already paints for clicks, so
  nothing new is drawn, and every move announces the verse and its annotation
  state through the same path the pointer flow uses.
* **Word tier** — ←/→ step through the words of the current verse, entered
  from the verse tier and left with Escape. Enter activates whatever the word
  carries: a Strong's number opens the lexicon, a footnote marker opens its
  peek, and a plain word opens the dictionary — the three word gestures the
  pointer already had.

Why a verse cursor rather than GTK's caret: a `GtkTextView` will not move its
caret at all while `cursor-visible` is false (measured — the `move-cursor`
signal is a no-op), so the caret route would have meant putting a blinking
text cursor in the middle of the reading page. The verse cursor rides
structure the buffer already carries (the `vnum_` tags) and draws nothing new.

The scroll invariant is the constraint that shapes the rest: moving the cursor
may need to bring a verse into view, and that must go through the pane's own
scroll-safe path (`_scroll_to_verse`), never a raw adjustment write.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

import a11y


class VerseCursor:
    """Keyboard cursor over the verses of the rendered chapter.

    Composed into `BiblePane` as `pane._cursor`; the pane installs its key
    controller on the reading view. Holds no widgets of its own — it drives
    the pane's existing indicator, scroll, and announcement machinery."""

    def __init__(self, pane):
        self._pane = pane
        # Verse the cursor sits on, or None when it has not been placed yet.
        self._verse = None
        # Word tier: (start_offset, end_offset) of the stepped word, or None
        # when the cursor is at the verse tier.
        self._word = None
        # Memoised _verses() for the current buffer; see on_render.
        self._verses_cache = None

    # ── State ─────────────────────────────────────────────────────────────

    @property
    def verse(self):
        return self._verse

    @property
    def in_word_tier(self):
        return self._word is not None

    def clear(self):
        """Drop cursor state — for a re-render into different content."""
        self._verse = None
        self._word = None
        self._verses_cache = None

    def on_render(self):
        """The buffer was rebuilt — drop what belonged to the old one.

        Word-tier state is buffer OFFSETS, so it cannot outlive the buffer it
        was measured against. `clear` only runs on a module change, so before
        this a chapter change kept them: stepping into a word, changing
        chapter, then pressing Enter resolved last chapter's offsets against
        the new text and acted on whatever now sat there.

        The verse number is deliberately kept — it is a reference rather than
        an offset, and `_step_verse` already re-validates it against the new
        chapter, so the reader stays where they were reading."""
        self._word = None
        self._verses_cache = None

    def sync_to(self, verse_num):
        """Follow a selection that came from somewhere else (a click, a
        cross-pane broadcast) so the keyboard resumes where the reader is."""
        if verse_num:
            self._verse = verse_num
            self._word = None

    # ── Key handling ──────────────────────────────────────────────────────

    def on_key(self, _controller, keyval, _keycode, state):
        """Key handler for the reading view. Returns True when handled.

        Only Bible panes get a verse cursor: commentary and generic-book
        panes render sections rather than numbered verses, so there is
        nothing for it to step through."""
        pane = self._pane
        if not pane._is_verse_navigable():
            return False
        # Never eat a shortcut. Ctrl/Alt combinations belong to the window's
        # actions (Alt+arrows change chapter, Ctrl+F opens find).
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False

        if keyval == Gdk.KEY_Down:
            return self._step_verse(1)
        if keyval == Gdk.KEY_Up:
            return self._step_verse(-1)
        if keyval == Gdk.KEY_Right:
            return self._step_word(1)
        if keyval == Gdk.KEY_Left:
            return self._step_word(-1)
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Menu):
            return self._activate()
        if keyval == Gdk.KEY_Escape:
            return self._leave_word_tier()
        if keyval == Gdk.KEY_bracketright:
            return self._step_unit(1)
        if keyval == Gdk.KEY_bracketleft:
            return self._step_unit(-1)
        return False

    # ── Verse tier ────────────────────────────────────────────────────────

    def _verses(self):
        """Verse numbers rendered in this chapter, ascending.

        Read from the buffer's own `vnum_` tags rather than the pane's
        `_rendered_verses` list: the tags are exactly what `_verse_ranges`
        can resolve, so the cursor can never stop on a verse the rest of the
        machinery cannot find.

        Memoised for the life of the buffer. The walk is a table-wide
        `foreach` with a Python callback reading a GObject property per tag,
        and a Strong's-tagged chapter carries thousands of them — measured at
        5.9 ms, a third of a frame, which every repeat of a held arrow key
        paid twice over on `[`/`]`. `on_render` drops the cache when the tags
        are rebuilt, which is the only thing that can change the answer."""
        if self._verses_cache is not None:
            return self._verses_cache
        found = []

        def collect(tag, _data):
            name = tag.get_property('name') or ''
            if name.startswith('vnum_'):
                try:
                    found.append(int(name.split('_')[1]))
                except (ValueError, IndexError):
                    pass

        self._pane._buffer.get_tag_table().foreach(collect, None)
        self._verses_cache = sorted(found)
        return self._verses_cache

    def _step_verse(self, delta):
        verses = self._verses()
        if not verses:
            return False
        self._word = None
        if self._verse is None or self._verse not in verses:
            # First press places the cursor rather than jumping: start from
            # what the reader is already looking at.
            target = (self._pane._selected_verse
                      or self._pane._find_topmost_visible_verse()
                      or verses[0])
            if target not in verses:
                target = verses[0]
        else:
            i = verses.index(self._verse) + delta
            if i < 0 or i >= len(verses):
                return False  # let the chapter edge fall through to scrolling
            target = verses[i]
        self._place(target)
        return True

    def _place(self, verse_num):
        """Move the cursor to a verse: indicator, scroll, announcement."""
        pane = self._pane
        self._verse = verse_num
        pane._selected_verse = verse_num
        pane._set_current_verse_indicator(verse_num)
        # The pane's own scroll path — never a raw adjustment write, or the
        # reading text moves under the reader (ARCHITECTURE's north star).
        pane._scroll_to_verse(verse_num)
        pane._announce_verse_state(verse_num)
        # Keep the other pane in step, exactly as a click would.
        if pane._on_verse_select:
            pane._on_verse_select(pane, verse_num)

    # ── Sense-unit tier ───────────────────────────────────────────────────

    def _unit_starts(self):
        """Verse numbers that open a sense-unit, ascending.

        A unit begins wherever the module supplied a section heading, so the
        boundaries are the publisher's own — the same data the headings are
        rendered from, not a division we invented. Intersected with the
        verses actually rendered, so a heading attached to a verse this
        chapter didn't render can't strand the cursor.

        Bibles only, matching exactly where _display draws headings. A
        commentary pane is verse-navigable and its module does carry heading
        attributes, but none of them are drawn there — and MHCC's are
        per-verse boilerplate ("Chapter Outline") rather than sense-units,
        so jumping between them would swallow the key to move one verse with
        nothing on screen to show for it."""
        pane = self._pane
        if pane._module_type != 'Biblical Texts' or not pane._show_headings:
            return []
        rendered = set(self._verses())
        return sorted(v for v in pane._rendered_headings if v in rendered)

    def _step_unit(self, delta):
        """[ and ] — move a whole thought at a time rather than a verse.

        Silent on modules that carry no headings: there are no units, so
        there is nothing to jump between and the key is released (graceful
        absence, the same rule the headings themselves follow)."""
        starts = self._unit_starts()
        if not starts:
            return False
        self._word = None
        here = self._verse or self._pane._selected_verse
        if here is None:
            target = starts[0]
        elif delta > 0:
            later = [v for v in starts if v > here]
            if not later:
                return False   # last unit — release the key
            target = later[0]
        else:
            # Back to the top of the current unit first, the way a "previous
            # section" control behaves in a document reader; only a second
            # press leaves for the unit before it.
            earlier = [v for v in starts if v < here]
            if not earlier:
                return False
            current_start = max((v for v in starts if v <= here), default=None)
            if current_start is not None and here > current_start:
                target = current_start
            else:
                target = earlier[-1]
        self._place(target)
        self._announce_unit(target)
        return True

    def _announce_unit(self, verse_num):
        """Lead with the heading — the unit's name is the useful part of
        arriving, and _place has already announced the bare reference."""
        heads = self._pane._rendered_headings.get(verse_num) or []
        if heads:
            a11y.announce(self._pane._view, heads[0])

    # ── Word tier ─────────────────────────────────────────────────────────

    def _word_spans(self):
        """(start, end) buffer offsets for each word of the current verse.

        Walks the verse's text range with the buffer's own word boundaries,
        so it follows the same notion of a word the dictionary peek uses."""
        pane = self._pane
        if self._verse is None:
            return []
        ranges = pane._verse_ranges(self._verse)
        if not ranges:
            return []
        _vnum_start, start, end = ranges
        spans = []
        it = start.copy()
        while it.compare(end) < 0:
            if not it.starts_word() and not it.forward_word_end():
                break
            w_end = it.copy()
            if not w_end.ends_word():
                w_end.forward_word_end()
            w_start = w_end.copy()
            w_start.backward_word_start()
            if w_start.compare(end) >= 0:
                break
            if not spans or spans[-1] != (w_start.get_offset(),
                                          w_end.get_offset()):
                spans.append((w_start.get_offset(), w_end.get_offset()))
            it = w_end.copy()
            if not it.forward_word_end():
                break
            it.backward_word_start()
        return spans

    def _step_word(self, delta):
        if self._verse is None:
            # ←/→ with no verse cursor yet: place one, don't swallow the key
            # into a tier the reader hasn't entered.
            return self._step_verse(0) if delta > 0 else False
        spans = self._word_spans()
        if not spans:
            return False
        if self._word is None:
            i = 0 if delta > 0 else len(spans) - 1
        else:
            try:
                i = spans.index(self._word) + delta
            except ValueError:
                i = 0
            if i < 0 or i >= len(spans):
                return False  # at the verse edge; leave the key alone
        self._word = spans[i]
        self._announce_word()
        return True

    def _leave_word_tier(self):
        if self._word is None:
            return False
        self._word = None
        if self._verse is not None:
            self._pane._announce_verse_state(self._verse)
        return True

    def _word_iters(self):
        buf = self._pane._buffer
        s, e = self._word
        return buf.get_iter_at_offset(s), buf.get_iter_at_offset(e)

    def _announce_word(self):
        """Say the word and what pressing Enter on it would do."""
        pane = self._pane
        start, end = self._word_iters()
        word = pane._buffer.get_text(start, end, False).strip()
        targets, _it = pane._targets_at_iter(start)
        if targets['fnote']:
            hint = _('footnote — press Enter to read')
        elif targets['strong']:
            hint = _('press Enter to look up')
        else:
            hint = _('press Enter for the dictionary')
        a11y.announce(pane._view, f'{word}, {hint}')

    # ── Activation ────────────────────────────────────────────────────────

    def _activate(self):
        """Enter: open the study menu on the verse, or act on the word."""
        if self._verse is None:
            return False
        return self._activate_word() if self._word else self._activate_verse()

    def _activate_verse(self):
        pane = self._pane
        ranges = pane._verse_ranges(self._verse)
        if not ranges:
            return False
        # The study menu points at a rectangle; give it the verse's own
        # position so the popover opens where the cursor visibly is.
        x, y = self._view_coords(ranges[1])
        import annotation_dialogs
        annotation_dialogs.show_study_menu(pane, [self._verse], x, y)
        return True

    def _activate_word(self):
        pane = self._pane
        start, _end = self._word_iters()
        targets, it = pane._targets_at_iter(start)
        if targets['fnote']:
            pane._show_footnote_peek(targets['fnote'], it)
            return True
        if targets['strong'] and pane._on_word_click:
            # The window reads display context off the pane rather than from
            # arguments, so set it the way the click path does before firing.
            pane._current_morph = targets['morph']
            pane._current_phrase = (None, None)
            pane._on_word_click(pane, targets['strong'])
            return True
        word = pane._buffer.get_text(*self._word_iters(), False).strip()
        if word:
            pane._show_dict_popup(word, self._word[0])
        return True

    def _view_coords(self, it):
        """Widget coordinates for a buffer iter, for anchoring a popover."""
        view = self._pane._view
        rect = view.get_iter_location(it)
        return view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, rect.x, rect.y)
