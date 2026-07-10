"""Interlinear reading surface — word-stack cells in original word order.

Renders a TAGNT chapter as a wrapping flow of word cells: the Greek surface
form in the reading serif with its analysis stacked beneath (gloss and
parsing by default; transliteration and Strong's number a chip away). Words
flow and wrap like text — BibleHub's skeleton — but hierarchy comes from
type, not colour: the serif belongs to scripture, apparatus is small warm
sans, and the one accent appears only on tappable things (the chips, the
word under the pointer).

Cells are plain Gtk widgets in a WordFlow (interlinear_flow) — a word-wrap
container with natural per-word widths; GtkFlowBox's uniform grid wasted
half the surface and shifted horizontally during incremental builds. A
chapter is ~500 words (~150 ms to build; the longest ~1200), so
construction is chunked through idle callbacks with a generation guard —
the first screenful paints immediately and navigation can never paint a
stale chapter, and with line-packed layout the streamed-in tail can never
move what's already on screen.
"""
import re
import threading

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib, Pango

import interlinear_data
import settings
import sword_bridge
from a11y import set_accessible_label
from interlinear_flow import WordFlow

def N_(message):
    """No-op gettext marker — the chip labels below are translated at
    display time (same pattern as open_data._SOURCES)."""
    return message


# Line id → (settings default, chip label). Order = stack order in the cell.
_LINES = [
    ('strongs',  False, N_('Strong’s')),
    ('translit', False, N_('Translit')),
    ('gloss',    True,  N_('Gloss')),
    ('parse',    True,  N_('Parsing')),
]
_SETTINGS_KEY = 'interlinear_lines'

# Cantillation marks (te'amim, U+0591–05AF) — strippable for a calmer
# Hebrew reading surface; vowel points (niqqud) always stay.
_CANTILLATION_RE = re.compile('[֑-֯]')

_CHUNK = 120            # cells per idle batch — first batch ≈ one screenful


class InterlinearReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._module = None
        self._rtl = False
        self._book = None
        self._chapter = None
        self._verse_anchors = {}     # verse -> first cell widget (scroll targets)
        self._cells = []             # (cell_box, line_labels dict)
        self._gen = 0                # invalidates in-flight chunked builds
        self._lines = self._load_line_prefs()
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ────────────────────────────────────────────────────────

    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Chip strip: which analysis lines show. Same capsule idiom as the
        # module picker's filter chips.
        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chips.set_margin_start(14)
        chips.set_margin_end(14)
        chips.set_margin_top(10)
        chips.set_margin_bottom(2)
        self._chip_btns = {}
        for line_id, _default, label in _LINES:
            btn = Gtk.ToggleButton(label=_(label))
            btn.add_css_class('interlinear-chip')
            btn.set_active(self._lines[line_id])
            set_accessible_label(btn, _(label))
            btn.connect('toggled', self._on_chip_toggled, line_id)
            self._chip_btns[line_id] = btn
            chips.append(btn)
        # Cantillation toggle — Hebrew only (shown/hidden per module). Not a
        # stacked line: it transforms the word text itself, so it has its
        # own handler rather than the visibility one above.
        self._accents_btn = Gtk.ToggleButton(label=_('Accents'))
        self._accents_btn.add_css_class('interlinear-chip')
        self._accents_btn.set_active(self._lines['accents'])
        self._accents_btn.set_tooltip_text(_('Cantillation marks'))
        set_accessible_label(self._accents_btn, _('Cantillation marks'))
        self._accents_btn.connect('toggled', self._on_accents_toggled)
        self._accents_btn.set_visible(False)
        chips.append(self._accents_btn)
        self._root.append(chips)

        self._header = Gtk.Label(xalign=0)
        self._header.add_css_class('interlinear-chap-head')
        self._header.set_margin_start(22)
        self._header.set_margin_top(14)
        self._header.set_margin_bottom(6)
        self._root.append(self._header)

        self._flow = WordFlow()
        self._flow.set_valign(Gtk.Align.START)
        self._flow.set_margin_start(18)
        self._flow.set_margin_end(18)
        self._flow.set_margin_bottom(24)

        # Quiet placeholder for chapters outside the Greek NT.
        self._empty = Gtk.Label()
        self._empty.add_css_class('dim-label')
        self._empty.set_wrap(True)
        self._empty.set_justify(Gtk.Justification.CENTER)
        self._empty.set_margin_top(80)
        self._empty.set_visible(False)

        # Attribution: the credit is part of the feature (CC BY), kept quiet.
        attrib = Gtk.Label(label=interlinear_data.ATTRIBUTION)
        attrib.add_css_class('interlinear-attrib')
        attrib.set_xalign(0)
        attrib.set_margin_start(22)
        attrib.set_margin_bottom(14)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        column.append(self._flow)
        column.append(self._empty)
        column.append(attrib)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        self._scroll.set_child(column)
        self._root.append(self._scroll)

    def _load_line_prefs(self):
        saved = settings.get(_SETTINGS_KEY) or {}
        prefs = {line_id: bool(saved.get(line_id, default))
                 for line_id, default, _label in _LINES}
        prefs['accents'] = bool(saved.get('accents', True))
        return prefs

    # ── rendering ───────────────────────────────────────────────────────────

    def render_for(self, module, book, chapter, verse):
        """Load and show a chapter; scrolls to `verse` when it's > 1.
        Re-renders only on a module/chapter change — a verse broadcast
        within the current chapter just scrolls."""
        if (module, book, chapter) == (self._module, self._book,
                                       self._chapter):
            self._scroll_to_verse(verse)
            return
        self._module = module
        self._rtl = interlinear_data.is_hebrew(module)
        self._book, self._chapter = book, chapter
        self._gen += 1
        gen = self._gen

        def fetch():
            words = interlinear_data.load_chapter(module, book, chapter)
            GLib.idle_add(self._show_chapter, gen, words, verse)

        threading.Thread(target=fetch, daemon=True).start()

    def _show_chapter(self, gen, words, verse):
        if gen != self._gen:
            return GLib.SOURCE_REMOVE
        self._flow.remove_all()
        self._cells = []
        self._verse_anchors = {}
        self._header.set_label(f'{book_label(self._book)} {self._chapter}')
        self._flow.set_rtl(self._rtl)
        self._accents_btn.set_visible(self._rtl)
        if not words:
            self._flow.set_visible(False)
            self._empty.set_label(
                _('The Hebrew Old Testament ends at Malachi.')
                if self._rtl else
                _('The Greek New Testament begins at Matthew.'))
            self._empty.set_visible(True)
            return GLib.SOURCE_REMOVE
        self._flow.set_visible(True)
        self._empty.set_visible(False)
        self._scroll.get_vadjustment().set_value(0)

        # Chunked build: append _CHUNK cells per idle tick so the first
        # screenful paints immediately and long chapters never stall input.
        def build(start):
            if gen != self._gen:
                return GLib.SOURCE_REMOVE
            last_verse = words[start - 1].verse if start else 0
            for w in words[start:start + _CHUNK]:
                if w.verse != last_verse:
                    self._append_verse_number(w.verse)
                    last_verse = w.verse
                self._append_cell(w)
            if start + _CHUNK < len(words):
                GLib.idle_add(build, start + _CHUNK)
            elif verse and verse > 1:
                # Layout needs a tick after the last append before anchor
                # positions are meaningful.
                GLib.idle_add(self._scroll_to_verse, verse)
            return GLib.SOURCE_REMOVE

        build(0)
        return GLib.SOURCE_REMOVE

    def _append_verse_number(self, verse):
        lbl = Gtk.Label(label=str(verse))
        lbl.add_css_class('interlinear-vnum')
        self._flow.append(lbl)            # WordFlow bottom-aligns per line
        self._verse_anchors[verse] = lbl

    def _append_cell(self, w):
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        cell.add_css_class('interlinear-cell')

        labels = {}
        strongs = Gtk.Label(label=w.strongs_all or w.strongs)
        strongs.add_css_class('interlinear-strongs')
        labels['strongs'] = strongs

        translit = Gtk.Label(label=w.translit)
        translit.add_css_class('interlinear-translit')
        labels['translit'] = translit

        shown = w.surface
        if self._rtl and not self._lines['accents']:
            shown = _CANTILLATION_RE.sub('', shown)
        surface = Gtk.Label(label=shown)
        surface.add_css_class(
            'interlinear-word-heb' if self._rtl else 'interlinear-word')
        labels['surface'] = surface
        labels['_surface_full'] = w.surface   # for the accents toggle

        gloss = Gtk.Label(label=w.gloss)
        gloss.add_css_class('interlinear-gloss')
        # TAGNT marks words English supplies implicitly with angle brackets
        # ('<the>'); render those as quiet annotation, not markup.
        if w.gloss.startswith('<') and w.gloss.rstrip('.,;·').endswith('>'):
            gloss.add_css_class('interlinear-gloss-implicit')
        labels['gloss'] = gloss

        if self._rtl:
            # 'HR/Ncfsa' → 'R · Ncfsa': the H is the language tag, the
            # slashes separate morphemes (prefix/stem/suffix).
            code = w.morph[1:] if w.morph.startswith('H') else w.morph
            parse = Gtk.Label(label=code.replace('/', ' · '))
            decoded = self._decode_heb_morph(w.morph)
        else:
            parse = Gtk.Label(label=w.morph.replace(' ', ' · '))
            decoded = self._decode_morph(w.morph)
        parse.add_css_class('interlinear-parse')
        if decoded:
            parse.set_tooltip_text(decoded)
        labels['parse'] = parse

        for line_id in ('strongs', 'translit'):
            labels[line_id].set_visible(self._lines[line_id])
        for line_id in ('gloss', 'parse'):
            labels[line_id].set_visible(self._lines[line_id])
        align = Gtk.Align.END if self._rtl else Gtk.Align.START
        for lbl in (strongs, translit, surface, gloss, parse):
            lbl.set_halign(align)
            lbl.set_ellipsize(Pango.EllipsizeMode.NONE)
            cell.append(lbl)

        if w.strongs:
            click = Gtk.GestureClick()
            click.connect('released', self._on_word_clicked, w)
            cell.add_controller(click)
            set_accessible_label(
                cell, f'{w.surface} — {w.gloss}' if w.gloss else w.surface)

        self._flow.append(cell)
        self._cells.append((cell, labels))

    @staticmethod
    def _decode_morph(morph):
        """'V-AAI-3S' (or compound 'P-1NS CONJ') → readable decode(s)."""
        parts = []
        for code in morph.split():
            d = sword_bridge.decode_robinson(f'robinson:{code}')
            if d:
                parts.append(d)
        return '  +  '.join(parts)

    @staticmethod
    def _decode_heb_morph(morph):
        """'HR/Ncfsa' → per-morpheme decode. decode_hebrew_morph reads one
        segment at a time; the language tag H belongs to the first segment
        only, so re-prefix the rest before decoding each."""
        segs = morph.split('/')
        parts = []
        for i, seg in enumerate(segs):
            if i > 0 and not seg.startswith('H'):
                seg = 'H' + seg
            d = sword_bridge.decode_hebrew_morph(f'oshm:{seg}')
            if d:
                parts.append(d)
        return '  +  '.join(parts)

    # ── interactions ────────────────────────────────────────────────────────

    def _on_chip_toggled(self, btn, line_id):
        on = btn.get_active()
        self._lines[line_id] = on
        settings.put(_SETTINGS_KEY, dict(self._lines))
        for _cell, labels in self._cells:
            labels[line_id].set_visible(on)
        # Cell heights changed — drop the flow's cached sizes and reflow.
        self._flow.invalidate_sizes()

    def _on_accents_toggled(self, btn):
        on = btn.get_active()
        self._lines['accents'] = on
        settings.put(_SETTINGS_KEY, dict(self._lines))
        for _cell, labels in self._cells:
            full = labels['_surface_full']
            labels['surface'].set_label(
                full if on else _CANTILLATION_RE.sub('', full))
        # Mark widths change with the marks — reflow with fresh sizes.
        self._flow.invalidate_sizes()

    def _on_word_clicked(self, _gesture, _n, _x, _y, w):
        """Route through the pane's word-click callback — the same path a
        Strong's-tagged Bible click takes (window shows the lexicon spinner,
        fetches the definition off-thread, then displays). The morph/phrase
        transient buffers are the documented click-time contract."""
        pane = self._pane
        if pane is None or not w.strongs or not pane._on_word_click:
            return
        if not w.morph:
            pane._current_morph = None
        elif self._rtl:
            pane._current_morph = f'oshm:{w.morph}'
        else:
            pane._current_morph = f'robinson:{w.morph.split()[0]}'
        pane._current_phrase = (None, None)
        pane._on_word_click(pane, w.strongs)

    def select_verse(self, verse):
        """Verse broadcast from the partner pane — scroll, don't re-render."""
        self._scroll_to_verse(verse)

    def _scroll_to_verse(self, verse):
        """Scroll so `verse` sits near the top. The FlowBox's height lands a
        layout pass (or several) after the last cell append, so a scroll
        issued right after building would clamp against a stale, too-small
        adjustment upper — poll until the upper stabilizes and can reach the
        anchor, then set the value once. (Fixed delays lose this race; a
        newer scroll/render supersedes any pending poll via the gen.)"""
        self._scroll_gen = getattr(self, '_scroll_gen', 0) + 1
        gen = self._scroll_gen
        state = {'last_upper': -1.0, 'ticks': 0, 'on_target': 0}

        def attempt():
            if gen != self._scroll_gen:
                return GLib.SOURCE_REMOVE
            adj = self._scroll.get_vadjustment()
            upper = adj.get_upper()
            state['ticks'] += 1
            if state['ticks'] > 80:
                return GLib.SOURCE_REMOVE       # give up quietly
            anchor = self._verse_anchors.get(verse)
            if anchor is None:
                # The chunked build may not have reached this verse yet —
                # keep polling until it appears (or the tick budget ends,
                # which also covers a verse number beyond the chapter).
                state['on_target'] = 0
                return GLib.SOURCE_CONTINUE
            # Anchor to the TOP OF THE LINE holding the verse number: the
            # bottom-aligned number sits ~a cell below its line's top, and
            # a scroll anchored to the label itself clips the verse's own
            # words (verse 1 ended up "slightly scrolled down" at startup).
            line_y = self._flow.line_top(anchor)
            quiet = line_y is not None and upper == state['last_upper'] \
                and upper >= line_y
            state['last_upper'] = upper
            if not quiet:
                state['on_target'] = 0
                return GLib.SOURCE_CONTINUE
            # Headroom above the verse, clamped to the (now real) range.
            target = max(0.0, min(line_y - 24,
                                  upper - adj.get_page_size()))
            if abs(adj.get_value() - target) <= 4:
                # Done only after the value HOLDS across two quiet ticks — a
                # pending relayout (e.g. a just-toggled line chip) can clamp
                # a freshly set value back to 0 after this poll would
                # otherwise have exited.
                state['on_target'] += 1
                if state['on_target'] >= 2:
                    return GLib.SOURCE_REMOVE
                return GLib.SOURCE_CONTINUE
            state['on_target'] = 0
            adj.set_value(target)
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(50, attempt)
        return GLib.SOURCE_REMOVE
