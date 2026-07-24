"""PresentController — the presentation-mode cluster extracted from BibleWindow
(STRUCTURAL_ANALYSIS.md T2 / Step 4, part 4).

Presentation mode is built on top of reading mode: it hides the window chrome
(via OverlayManager's _set_reading_mode), goes fullscreen, and projects the
source pane's passage onto the large-type PresentView surface, with its own
cross-chapter/jump navigation, an off-thread chapter loader, and a
pointer-driven control strip. This owns all that plus the strip widgets and the
presentation location/parallel state; the only present state left on the window
is the PresentView widget itself (built in _build_ui, used by the key handler).

It holds a back-reference to its window and reaches the panes, the PresentView,
and the reading-mode / fullscreen / toast hooks it drives through the proxy
properties below, so the method bodies are the inline originals unchanged (only
the module-level BOOKS constant is qualified as window.BOOKS). The window keeps
thin same-named delegates plus a forwarding _present_mode property, so every
action, key-controller, PresentView callback, and OverlayManager hook is
untouched. Imported lazily in BibleWindow.__init__ for the same BOOKS
load-order reason as the other controllers.
"""
import re
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import sword_bridge
import tasks
from a11y import set_accessible_label
import window


class PresentController:
    def __init__(self, win):
        self._win = win
        self._present_mode = False

    # ── Proxy access to window-owned widgets / panes / hooks ─────────────────
    @property
    def pane1(self):
        return self._win.pane1

    @property
    def pane2(self):
        return self._win.pane2

    @property
    def _present_view(self):
        return self._win._present_view

    @property
    def _menu_split(self):
        return self._win._menu_split

    @property
    def _reading_mode(self):
        return getattr(self._win, '_reading_mode', False)

    @property
    def _set_reading_mode(self):
        return self._win._set_reading_mode

    @property
    def _toast(self):
        return self._win._toast

    @property
    def fullscreen(self):
        return self._win.fullscreen

    @property
    def unfullscreen(self):
        return self._win.unfullscreen

    @property
    def is_fullscreen(self):
        return self._win.is_fullscreen

    @property
    def get_height(self):
        return self._win.get_height

    def _toggle_present_mode(self):
        self._set_present_mode(not getattr(self, '_present_mode', False))

    def _set_present_mode(self, on):
        on = bool(on)
        if on == getattr(self, '_present_mode', False):
            return
        self._present_mode = on
        if on:
            self._present_was_reading = getattr(self, '_reading_mode', False)
            self._present_was_fullscreen = self.is_fullscreen()
            self._set_reading_mode(True, toast=False)
            self._show_present()
            self.fullscreen()
            self._toast(
                _('Presentation — Esc to exit, controls at the bottom edge'))
        else:
            self._present_show_controls(False)
            self._present_view.set_visible(False)
            if not getattr(self, '_present_was_fullscreen', False):
                self.unfullscreen()
            if not getattr(self, '_present_was_reading', False):
                self._set_reading_mode(False, toast=False)

    def _present_source_pane(self):
        """The pane whose passage projects. The primary pane leads; fall back to
        the secondary if only it has a navigable chapter loaded."""
        if self.pane1.current_passage() is not None:
            return self.pane1
        if self.pane2.get_visible() and self.pane2.current_passage() is not None:
            return self.pane2
        return self.pane1

    def _present_bilingual_source(self):
        """(primary, secondary) panes when a parallel projection is possible:
        split view, both showing a navigable Bible chapter, on the same
        reference, in different modules. Else None. Primary is pane1."""
        if not self.pane2.get_visible():
            return None
        p1 = self.pane1.current_passage()
        p2 = self.pane2.current_passage()
        if p1 is None or p2 is None:
            return None
        if (p1[0], p1[1]) != (p2[0], p2[1]):        # same book & chapter
            return None
        if self.pane1._module == self.pane2._module:  # two views of one text
            return None
        return (self.pane1, self.pane2)

    def _show_present(self):
        bi = self._present_bilingual_source()
        pane = bi[0] if bi else self._present_source_pane()
        self._present_module = pane._module
        self._present_module_b = bi[1]._module if bi else None
        self._present_bilingual = bool(bi)          # user intent, per session
        # Invalidate any cross/jump load still in flight from a previous present
        # session so it can't clobber the passage we're about to show.
        tasks.cancel(f'present:{id(self)}')
        # Header is already hidden (reading mode), so the window height minus the
        # surface's own padding is a good pre-allocation viewport estimate — lets
        # the very first page pre-fit instead of flashing an overflow.
        self._present_view.set_viewport_hint(self.get_height() - 80)
        self._present_view.set_appearance(pane.reading_appearance())
        passage = pane.current_passage()
        if passage is None:
            # Nothing navigable to project (e.g. a lexicon/imagery module) —
            # show the surface with a gentle placeholder rather than a blank.
            self._present_book = None
            self._present_view.show_placeholder(
                _('Open a Bible passage to present it.'))
        else:
            book, chapter, translation, verses = passage
            self._present_book, self._present_chapter = book, chapter
            secondary = None
            if bi:
                _b, _c, trans_b, verses_b = bi[1].current_passage()
                secondary = (trans_b, verses_b)
            # Both panes' verses are already fetched — load synchronously (no
            # worker thread needed) so the first slide is ready instantly.
            self._present_view.load_chapter(
                book, chapter, translation, verses,
                focus_verse=pane.current_verse(), secondary=secondary)
            self._present_view.set_parallel(bool(bi))
        self._present_view.set_visible(True)
        self._sync_present_controls()

    # ── Cross-chapter navigation (presentation) ───────────────────────────────
    # Stepping off either end of a chapter rolls into the adjacent one, so the
    # arrows are always live. Present mode navigates its own location; the
    # source pane is left where it was (exit returns you to your study spot).
    def _adjacent_chapter(self, book, chapter, delta):
        """(book, chapter) one chapter forward/back from here, crossing book
        boundaries; None at the very start / end of the canon."""
        try:
            idx = window.BOOKS.index(book)
        except ValueError:
            return None
        module = self._present_module
        if delta > 0:
            if chapter < sword_bridge.chapter_count(book, module):
                return (book, chapter + 1)
            if idx < len(window.BOOKS) - 1:
                return (window.BOOKS[idx + 1], 1)
            return None
        if chapter > 1:
            return (book, chapter - 1)
        if idx > 0:
            prev = window.BOOKS[idx - 1]
            return (prev, sword_bridge.chapter_count(prev, module))
        return None

    def _load_chapter_verses(self, module, book, chapter):
        import ebible_bridge
        if ebible_bridge.is_ebible_module(module):
            return ebible_bridge.load_chapter(module, book, chapter)
        return sword_bridge.load_chapter(module, book, chapter)

    def _present_cross(self, delta):
        """Load the chapter `delta` away into the presentation surface, landing
        on its first page (forward) or last page (backward). A canon edge or an
        empty (out-of-coverage) chapter leaves the current slide unchanged."""
        if not getattr(self, '_present_book', None):
            return
        nxt = self._adjacent_chapter(
            self._present_book, self._present_chapter, delta)
        if nxt is None:
            return
        book, chapter = nxt
        self._present_load_async(
            book, chapter, land='first' if delta > 0 else 'last')

    def _present_jump(self, book, chapter, verse):
        """Jump the presentation to an arbitrary reference (from the Ctrl+L bar)
        without moving the source pane. Opens on the page holding `verse` when
        one is given. A book the presenting module doesn't carry leaves the
        slide unchanged and says so, rather than projecting a blank."""
        if book not in window.BOOKS:
            return
        chapter = max(1, min(chapter,
                             sword_bridge.chapter_count(book,
                                                        self._present_module)))
        self._present_load_async(
            book, chapter, focus_verse=verse, empty_toast=True)

    def _present_load_async(self, book, chapter, *, land='first',
                            focus_verse=None, empty_toast=False):
        """Load a chapter for the presentation surface off the UI thread, then
        show it on the main loop — so a slow module never stalls the projected
        display mid-roll. The tasks runner drops any load a newer navigation
        has superseded (and _show_present cancels the key on entry), so rapid
        arrow-rolls can't paint a stale chapter."""
        module = self._present_module
        module_b = (self._present_module_b
                    if getattr(self, '_present_bilingual', False) else None)

        def work(_task):
            try:
                verses = self._load_chapter_verses(module, book, chapter)
            except Exception:
                verses = []
            translation = sword_bridge.display_name(module)
            secondary = None
            if module_b:
                try:
                    verses_b = self._load_chapter_verses(module_b, book, chapter)
                except Exception:
                    verses_b = []
                # Only offer the second column where it actually has this
                # chapter — otherwise this chapter degrades cleanly to single.
                if any(re.sub(r'<[^>]+>', '', str(h)).strip()
                       for _v, h in verses_b):
                    secondary = (sword_bridge.display_name(module_b), verses_b)
            return verses, translation, secondary

        tasks.submit(
            f'present:{id(self)}', work,
            lambda res: self._present_load_finish(
                book, chapter, *res, land, focus_verse, empty_toast),
            on_error=lambda _exc: self._present_load_finish(
                book, chapter, [], '', None, land, focus_verse, empty_toast))

    def _present_load_finish(self, book, chapter, verses, translation,
                             secondary, land, focus_verse, empty_toast):
        if not getattr(self, '_present_mode', False):
            return GLib.SOURCE_REMOVE           # present exited meanwhile
        if not any(re.sub(r'<[^>]+>', '', str(h)).strip() for _v, h in verses):
            if empty_toast:
                self._toast(_('%s isn’t in this translation.') % book_label(book))
            return GLib.SOURCE_REMOVE           # canon edge / out of coverage
        self._present_book, self._present_chapter = book, chapter
        self._present_view.load_chapter(
            book, chapter, translation, verses,
            land=land, focus_verse=focus_verse, secondary=secondary)
        # Honour the session's parallel intent, but only where the second column
        # actually loaded (an out-of-coverage chapter shows single).
        self._present_view.set_parallel(
            bool(secondary) and getattr(self, '_present_bilingual', False))
        self._sync_present_controls()
        return GLib.SOURCE_REMOVE

    # ── Presentation control strip ────────────────────────────────────────────
    # A floating OSD bar (media-overlay style, theme-neutral over any paper)
    # with the step + toggle controls. Shown by pointer position (near the
    # bottom edge) rather than an idle timer, so it never hops on its own;
    # keyboard-only presenting leaves it hidden for a clean slide.
    def _build_present_controls(self, overlay):
        def icon_button(icon, tooltip, handler, toggle=False):
            btn = (Gtk.ToggleButton() if toggle else Gtk.Button())
            btn.set_icon_name(icon)
            btn.add_css_class('flat')
            btn.set_tooltip_text(tooltip)
            set_accessible_label(btn, tooltip)
            btn.connect('toggled' if toggle else 'clicked', handler)
            return btn

        self._present_prev_btn = icon_button(
            'go-previous-symbolic', _('Previous'),
            lambda _b: self._present_step(self._present_view.step_prev))
        self._present_next_btn = icon_button(
            'go-next-symbolic', _('Next'),
            lambda _b: self._present_step(self._present_view.step_next))
        self._present_numbers_btn = icon_button(
            'view-list-ordered-symbolic', _('Verse numbers'),
            lambda b: self._present_view.set_show_numbers(b.get_active()),
            toggle=True)
        # A stylized "V" (Verse) reads better here than any stock icon — the
        # paged/fullscreen glyphs looked like copy/fullscreen.
        self._present_gran_btn = Gtk.ToggleButton()
        self._present_gran_btn.add_css_class('flat')
        _vglyph = Gtk.Label(label='V')
        _vglyph.add_css_class('present-verse-glyph')
        self._present_gran_btn.set_child(_vglyph)
        self._present_gran_btn.set_tooltip_text(_('One verse per page'))
        set_accessible_label(self._present_gran_btn, _('One verse per page'))
        self._present_gran_btn.connect(
            'toggled',
            lambda b: self._present_view.set_verse_at_a_time(b.get_active()))
        # Parallel (bilingual) toggle — only meaningful, and only shown, when a
        # second translation is loaded (see _sync_present_controls).
        self._present_parallel_btn = icon_button(
            'view-dual-symbolic', _('Parallel — both translations'),
            lambda b: self._present_toggle_parallel(b.get_active()),
            toggle=True)
        self._present_zoom_out_btn = icon_button(
            'zoom-out-symbolic', _('Smaller text'),
            lambda _b: self._present_view.bump_size(-1))
        self._present_zoom_in_btn = icon_button(
            'zoom-in-symbolic', _('Larger text'),
            lambda _b: self._present_view.bump_size(1))
        self._present_exit_btn = icon_button(
            'window-close-symbolic', _('Exit presentation'),
            lambda _b: self._set_present_mode(False))

        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        strip.add_css_class('osd')
        strip.add_css_class('toolbar')
        strip.add_css_class('present-controls')
        strip.append(self._present_prev_btn)
        strip.append(self._present_next_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_numbers_btn)
        strip.append(self._present_gran_btn)
        strip.append(self._present_parallel_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_zoom_out_btn)
        strip.append(self._present_zoom_in_btn)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(self._present_exit_btn)

        self._present_controls_revealer = Gtk.Revealer()
        self._present_controls_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP)
        self._present_controls_revealer.set_transition_duration(200)
        self._present_controls_revealer.set_halign(Gtk.Align.CENTER)
        self._present_controls_revealer.set_valign(Gtk.Align.END)
        self._present_controls_revealer.set_margin_bottom(28)
        self._present_controls_revealer.set_child(strip)
        self._present_controls_revealer.set_reveal_child(False)
        overlay.add_overlay(self._present_controls_revealer)

        self._present_controls_shown = False

    def _sync_present_controls(self):
        """Reflect the view's current toggle state on the strip. The setters the
        buttons drive are idempotent, so mirroring back here can't loop."""
        if not hasattr(self, '_present_numbers_btn'):
            return
        self._present_numbers_btn.set_active(self._present_view.show_numbers)
        self._present_gran_btn.set_active(self._present_view.verse_at_a_time)
        # The parallel toggle only appears when a second translation is loaded.
        self._present_parallel_btn.set_visible(self._present_view.has_secondary)
        self._present_parallel_btn.set_active(self._present_view.parallel)

    def _present_toggle_parallel(self, on):
        """Show both translations (on) or collapse to the primary. Records the
        session intent so cross-chapter rolls keep the presenter's choice."""
        self._present_bilingual = bool(on)
        self._present_view.set_parallel(bool(on))
        self._sync_present_controls()

    def _present_step(self, op):
        op()
        self._sync_present_controls()

    # Show the strip while the pointer is within this many px of the bottom
    # (near the controls), hide it once the pointer moves up to read. Purely
    # position-driven — no idle timer — so it never hops on its own.
    _PRESENT_CONTROL_ZONE_PX = 150

    def _present_update_controls(self, y):
        if not getattr(self, '_present_mode', False):
            return
        height = self.get_height()
        if not height:
            return
        self._present_show_controls(y > height - self._PRESENT_CONTROL_ZONE_PX)

    def _present_show_controls(self, show):
        show = bool(show)
        if show == self._present_controls_shown:
            return                              # only act on an actual edge
        self._present_controls_shown = show
        if show:
            self._sync_present_controls()
        self._present_controls_revealer.set_reveal_child(show)

    def _on_present_menu_clicked(self, _row):
        # Menu entry point (F5 is the shortcut). Close the menu first so it
        # isn't left open behind the fullscreen surface.
        self._menu_split.set_show_sidebar(False)
        self._set_present_mode(True)
