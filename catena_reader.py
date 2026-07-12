"""catena_reader.py — the Historical Commentaries pane subsystem.

Renders the "chorus" of church-history voices on the verse the partnered
Bible pane is showing: a clamped reading column grouped by era, each voice
an author eyebrow, the source title, and the quote (previewed, expandable).
Mirrors genbook_reader's shape — a class the pane composes and drives — but
owns the voice column rather than the flowing TextView.
"""

import html
import logging
import re

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from a11y import set_accessible_label
from gtk_utils import clear_children
from i18n import N_

import catena_bridge
import imagery_bridge

_log = logging.getLogger('scriptura.catena')

# The DB's era values in chronological order, each mapped to a display name
# and the one-line deck its section header opens with (both translated at
# display time; the raw era value stays the filter key).
_ERAS = {
    'Ante-Nicene': (
        N_('Ante-Nicene'),
        N_('The church of the martyrs, before the council of Nicaea.')),
    'Nicene & Post-Nicene': (
        N_('Nicene & Post-Nicene'),
        N_('The great councils and the doctors of the undivided church.')),
    'Medieval': (
        N_('Medieval'),
        N_('Cloister and cathedral school: faith seeking understanding.')),
    'Reformation': (
        N_('Reformation'),
        N_('The sixteenth century returns to the sources.')),
    'Modern': (
        N_('Modern'),
        N_('The same conversation, carried into the modern age.')),
    'Unknown': (
        N_('Uncertain date'),
        N_('Voices whose dates the record does not preserve.')),
}
_ERA_ORDER = list(_ERAS)

# Quotes longer than this get a Read more/Show less toggle (the voice shows
# only a short preview string until expanded) so a 1,000-word Augustine
# entry doesn't bury the others — and its full layout isn't built until read.
_PREVIEW_CHARS = 320

# Cap the voices rendered at once. A handful of verses (John 1:1 has 100+)
# would otherwise spawn hundreds of wrapping labels that re-flow on every
# pane resize. The rest surface behind a "show all" button.
_VOICE_CAP = 25

# Show the per-figure author filter only once a verse has enough voices
# that scanning by eye gets tedious.
_AUTHOR_FILTER_MIN = 6

# Comfortable reading measure — the same clamp as the Scripture in Stone
# gallery, so the two study surfaces share one column.
_TEXT_W = 680

# Words kept lowercase when taming an ALL-CAPS source title.
_TITLE_SMALL_WORDS = {'a', 'an', 'and', 'at', 'by', 'for', 'from', 'in',
                      'of', 'on', 'or', 'the', 'to', 'with'}


class CatenaReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._book = None
        self._chapter = None
        self._verse = None
        self._entries = []
        self._era_filter = None  # None == "All"
        self._author_query = ''  # per-figure substring filter
        self._show_all = False   # cap rendered voices until the user asks
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ────────────────────────────────────────────────────────

    @staticmethod
    def _clamp(child):
        c = Adw.Clamp(maximum_size=_TEXT_W,
                      tightening_threshold=int(_TEXT_W * 0.85))
        c.set_child(child)
        return c

    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        head_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        head_row.add_css_class('catena-header')
        self._header = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self._header.add_css_class('title-4')
        head_row.append(self._header)
        # The author filter hides behind this toggle: at rest the pane opens
        # with header, chips, first voice — the full-width entry appears only
        # when asked for.
        self._search_btn = Gtk.ToggleButton(icon_name='system-search-symbolic')
        self._search_btn.add_css_class('flat')
        self._search_btn.set_valign(Gtk.Align.CENTER)
        self._search_btn.set_visible(False)
        self._search_btn.set_tooltip_text(_('Filter by author'))
        set_accessible_label(self._search_btn, _('Filter by author'))
        self._search_btn.connect('toggled', self._on_search_toggled)
        head_row.append(self._search_btn)
        self._root.append(self._clamp(head_row))

        self._author_entry = Gtk.SearchEntry()
        self._author_entry.set_placeholder_text(_('Filter by author…'))
        self._author_entry.set_margin_start(14)
        self._author_entry.set_margin_end(14)
        self._author_entry.set_margin_top(2)
        self._author_entry.set_margin_bottom(10)
        self._author_entry.connect('search-changed', self._on_author_search)
        self._author_entry.connect('stop-search', self._on_stop_search)
        self._author_entry.set_visible(False)
        self._root.append(self._clamp(self._author_entry))

        self._chip_box = Adw.WrapBox(child_spacing=6, line_spacing=6)
        self._chip_box.add_css_class('catena-chips')
        self._root.append(self._clamp(self._chip_box))

        # Places named in the verse under commentary (from the imagery pack,
        # when installed) — outline chips opening a small place dialog, so a
        # quote on Acts 13 can highlight Pisidian Antioch without displacing
        # either pane. Hidden when the pack is absent or the verse names none.
        self._place_box = Adw.WrapBox(child_spacing=6, line_spacing=6)
        self._place_box.add_css_class('catena-chips')
        self._root.append(self._clamp(self._place_box))

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        self._list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                             vexpand=True)
        self._list.add_css_class('catena-list')
        self._list.add_css_class('catena-page')
        scroll.set_child(self._clamp(self._list))
        self._root.append(scroll)

        # Font scaling: the .catena-* sizes are em-relative, so one base
        # font-size on the column scales the whole document with the app's
        # reading font size (apply_font_size, called by the pane).
        self._font_provider = Gtk.CssProvider()
        self._list.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ── public drive ──────────────────────────────────────────────────────────

    def render_for(self, book, chapter, verse):
        """Show commentary on a verse (driven by the partnered Bible pane)."""
        self._book, self._chapter, self._verse = book, chapter, verse
        self._era_filter = None
        self._show_all = False
        self._author_query = ''
        if self._author_entry.get_text():
            self._author_entry.set_text('')  # guarded no-op rebuild below
        self._search_btn.set_active(False)   # fold the filter away
        try:
            self._entries = catena_bridge.lookup(book, chapter, verse) \
                if book and chapter and verse else []
        except Exception:
            _log.exception('catena lookup failed')
            self._entries = []
        self._rebuild()
        self.apply_font_size(getattr(self._pane, '_font_size', None))

    # ── font scaling ──────────────────────────────────────────────────────────

    def apply_font_size(self, pt):
        """Scale the voice column from the app's reading font size (the
        .catena-* sizes are em-relative). Called on render and whenever the
        pane's appearance changes."""
        if not pt:
            return
        self._font_provider.load_from_data(
            f'.catena-page {{ font-size: {pt}pt; }}'.encode())

    # ── rendering ──────────────────────────────────────────────────────────────

    def _clear(self, box):
        clear_children(box)

    def _rebuild(self):
        self._clear(self._list)
        self._clear(self._chip_box)
        self._build_place_chips()

        if not self._book:
            self._header.set_text(_('Historical Commentaries'))
            self._search_btn.set_visible(False)
            self._list.append(self._status(
                _('Open a Bible alongside this pane'),
                _('Select a verse there to see how the church has read it '
                  'across the centuries.')))
            return

        ref = f'{book_label(self._book)} {self._chapter}:{self._verse}'
        n = len(self._entries)
        self._search_btn.set_visible(n > _AUTHOR_FILTER_MIN)

        shown = [
            e for e in self._entries
            if (self._era_filter is None or e['era'] == self._era_filter)
            and (not self._author_query
                 or self._author_query in e['author'].lower())
        ]

        filtering = self._era_filter is not None or bool(self._author_query)
        if not n:
            self._header.set_text(ref)
        else:
            if filtering:
                count = _('{shown} of {total}').format(
                    shown=len(shown), total=n)
            else:
                count = ngettext('{n} voice', '{n} voices', n).format(n=n)
            # Structure bold, statistics quiet: the count rides dimmed after
            # the reference (markup composed here, outside the translated
            # strings).
            self._header.set_markup(
                '{ref} <span alpha="55%">· {count}</span>'.format(
                    ref=GLib.markup_escape_text(ref),
                    count=GLib.markup_escape_text(count)))

        self._build_chips()

        if not self._entries:
            self._list.append(self._status(
                _('No historical commentary on this verse'),
                _('Try a neighbouring verse, or a passage the fathers wrote '
                  'about more often.')))
            return

        if not shown:
            self._list.append(self._status(
                _('No voices match this filter'),
                _('Clear the author filter or choose a different era.')))
            return

        display = shown if self._show_all else shown[:_VOICE_CAP]
        prev_era = None
        for e in display:
            if e['era'] != prev_era:
                self._list.append(self._era_header(e['era']))
                prev_era = e['era']
            self._list.append(self._voice(e))

        if len(shown) > len(display):
            more = Gtk.Button(label=ngettext(
                'Show all {n} voice', 'Show all {n} voices', len(shown)).format(n=len(shown)))
            more.add_css_class('flat')
            more.set_margin_top(8)
            more.connect('clicked', self._on_show_all)
            self._list.append(more)

    def _build_chips(self):
        present = {e['era'] for e in self._entries}
        if len(present) <= 1:
            self._chip_box.set_visible(False)
            return
        self._chip_box.set_visible(True)
        ordered = ['All'] + [era for era in _ERA_ORDER if era in present]
        for value in ordered:
            label = _('All') if value == 'All' else _era_name(value)
            chip = Gtk.ToggleButton(label=label)
            chip.add_css_class('catena-chip')
            active = (value == 'All' and self._era_filter is None) \
                or (value == self._era_filter)
            if active:
                chip.set_active(True)
            chip.connect('toggled', self._on_chip_toggled, value)
            self._chip_box.append(chip)

    def _build_place_chips(self):
        self._clear(self._place_box)
        places = []
        if self._book and self._chapter and self._verse:
            try:
                places = imagery_bridge.places_for(
                    self._book, self._chapter, self._verse)
            except Exception:
                _log.exception('place lookup failed')
        self._place_box.set_visible(bool(places))
        if not places:
            return
        lead = Gtk.Label(label=_('Places'))
        lead.add_css_class('caption')
        lead.add_css_class('catena-meta')
        lead.set_valign(Gtk.Align.CENTER)
        self._place_box.append(lead)
        for place in places:
            disp = imagery_bridge.place_display_name(place['ancient_name'])
            chip = Gtk.Button(label=disp)
            chip.add_css_class('xref-chip')
            chip.add_css_class('catena-chip-place')
            chip.set_can_shrink(True)
            chip.set_tooltip_text(_('About {place}').format(place=disp))
            set_accessible_label(
                chip, _('About {place}').format(place=disp))
            chip.connect('clicked', self._on_place_chip, place)
            self._place_box.append(chip)

    def _on_place_chip(self, _btn, place):
        # Imported here, not at module top: imagery_reader pulls in the zoom
        # viewer machinery, which the catena pane otherwise never needs.
        from imagery_reader import present_place_dialog
        present_place_dialog(self._root.get_root(), place)

    def _on_chip_toggled(self, chip, value):
        if not chip.get_active():
            # Keep exactly one chip active: re-press if the user untoggled it.
            current = 'All' if self._era_filter is None else self._era_filter
            if value == current:
                chip.set_active(True)
            return
        new_filter = None if value == 'All' else value
        if new_filter == self._era_filter:
            return
        self._era_filter = new_filter
        self._show_all = False
        self._rebuild()

    def _on_show_all(self, _btn):
        self._show_all = True
        self._rebuild()

    def _on_search_toggled(self, btn):
        active = btn.get_active()
        self._author_entry.set_visible(active)
        if active:
            self._author_entry.grab_focus()
        elif self._author_entry.get_text():
            self._author_entry.set_text('')  # fires search-changed → rebuild

    def _on_stop_search(self, _entry):
        self._search_btn.set_active(False)   # Esc folds the filter away

    def _on_author_search(self, entry):
        q = entry.get_text().strip().lower()
        if q == self._author_query:
            return  # guard the programmatic clear in render_for
        self._author_query = q
        self._show_all = False
        self._rebuild()

    def _era_header(self, era):
        """Era section header — the Stone gallery's chapter voice: accent
        semibold sans over a one-line italic serif deck."""
        name, deck = _ERAS.get(era, (None, None))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class('catena-era')
        title = Gtk.Label(label=_(name) if name else era, xalign=0, wrap=True)
        title.add_css_class('catena-era-title')
        box.append(title)
        if deck:
            sub = Gtk.Label(label=_(deck), xalign=0, wrap=True)
            sub.add_css_class('catena-era-deck')
            box.append(sub)
        return box

    def _voice(self, e):
        """One voice of the catena — the author eyebrow (with year and the
        copy action), the source title, and the serif quote. No card box:
        voices sit on the window background, separated by rhythm alone."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class('catena-voice')

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        eyebrow = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        eyebrow.add_css_class('catena-eyebrow')
        name, suffix = _author_parts(e)
        markup = ('<span variant="smallcaps" letter_spacing="1024">{a}</span>'
                  .format(a=GLib.markup_escape_text(name)))
        # The suffix ("(as quoted by Aquinas, AD 1274)") and year are asides,
        # not the name — they ride dimmed, outside the small caps.
        dim = [suffix] if suffix else []
        year = _year_label(e['year'])
        if year:
            dim.append(f'· {year}')
        if dim:
            markup += ' <span alpha="55%">{d}</span>'.format(
                d=GLib.markup_escape_text(' '.join(dim)))
        eyebrow.set_markup(markup)
        head.append(eyebrow)

        text = html.unescape(e['text']).strip()
        copy = Gtk.Button(icon_name='edit-copy-symbolic')
        copy.add_css_class('flat')
        copy.add_css_class('circular')
        copy.add_css_class('catena-copy')
        copy.set_valign(Gtk.Align.START)
        copy.set_tooltip_text(_('Copy quote'))
        set_accessible_label(copy, _('Copy quote'))
        copy.connect('clicked', self._on_copy, e, text)
        head.append(copy)
        box.append(head)

        title = _source_title(e)
        if title or e.get('source_url'):
            src = Gtk.Label(xalign=0, wrap=True)
            src.add_css_class('catena-source')
            shown = title or _('Source')
            if e.get('source_url'):
                # The title itself is the link — quiet at rest, clay on hover
                # (.catena-source link). underline="none": Pango underlines
                # label links itself, outside CSS reach.
                src.set_markup(
                    '<a href="{u}"><span underline="none">{t}</span></a>'
                    .format(u=GLib.markup_escape_text(e['source_url']),
                            t=GLib.markup_escape_text(shown)))
            else:
                src.set_text(shown)
            box.append(src)

        quote = Gtk.Label(xalign=0, wrap=True, selectable=True)
        quote.add_css_class('catena-quote')
        # Selectable, but not focusable: keeps drag-select and right-click
        # Copy while dropping the blinking caret a focused read-only label
        # would show (the Stone reader's read-only-prose pattern).
        quote.set_focusable(False)
        quote.set_margin_top(2)
        box.append(quote)
        if self._pane is not None:
            self._pane._attach_dict_to_label(quote)

        if len(text) > _PREVIEW_CHARS:
            # Lazy: hold only a short preview string until the user expands,
            # so a long quote's full Pango layout is never built unless read.
            preview = _preview(text)
            quote.set_text(preview)
            toggle = Gtk.Button(label=_('Read more'))
            toggle.add_css_class('catena-more')
            toggle.set_halign(Gtk.Align.START)
            state = {'expanded': False}
            toggle.connect('clicked', self._toggle_more, state, quote,
                           preview, text)
            box.append(toggle)
        else:
            quote.set_text(text)

        return box

    def _toggle_more(self, btn, state, quote, preview, full):
        state['expanded'] = not state['expanded']
        quote.set_text(full if state['expanded'] else preview)
        btn.set_label(_('Show less') if state['expanded'] else _('Read more'))

    def _on_copy(self, btn, e, text):
        """Copy the quote citation-ready: the text, then an attribution line
        (author, source, year, reference)."""
        bits = [_author_label(e)]
        title = _source_title(e)
        if title:
            bits.append(title)
        attribution = ', '.join(bits)
        year = _year_label(e['year'])
        if year:
            attribution = f'{attribution} ({year})'
        ref = f'{book_label(self._book)} {self._chapter}:{self._verse}'
        line = _('— {attribution}, on {ref}').format(
            attribution=attribution, ref=ref)
        btn.get_clipboard().set(f'{text}\n{line}')
        # Quiet confirmation: the icon flips to a check for a moment.
        btn.set_icon_name('object-select-symbolic')

        def _restore():
            btn.set_icon_name('edit-copy-symbolic')
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(1200, _restore)

    def _status(self, title, detail):
        page = Adw.StatusPage()
        page.set_icon_name('accessories-dictionary-symbolic')
        page.set_title(title)
        page.set_description(detail)
        page.set_vexpand(True)
        return page


def _preview(text):
    """Short preview of a long quote. Prefer ending at the last sentence
    boundary in the window — a word-boundary cut can land right after a
    paragraph opener ("Secondly,…") — falling back to the last word plus an
    ellipsis when the final sentence break comes too early. A sentence-ended
    preview keeps its own punctuation and no ellipsis."""
    cut = text[:_PREVIEW_CHARS]
    ends = [m.end() for m in re.finditer(r'[.!?]["”’)]?(?=\s)', cut)]
    if ends and ends[-1] >= int(_PREVIEW_CHARS * 0.6):
        return cut[:ends[-1]].rstrip()
    # The word cut sheds any clause punctuation it landed on ("flesh,…" —
    # one combined strip set, so "earth -" loses the space behind the dash
    # too), and never doubles an ellipsis the source text already carries.
    tail = cut.rsplit(' ', 1)[0].rstrip(' \t\n,;:–—-')
    return tail if tail.endswith('…') else tail + '…'


def _era_name(era):
    """Display name for a DB era value (translated; raw value on a miss)."""
    name = _ERAS.get(era, (None, ''))[0]
    return _(name) if name else era


def _author_parts(e):
    """(author, display suffix). Suffixes arrive in two shapes: bare verse
    locators (' 10:23-33') that need parentheses, and ones that carry their
    own — '(as quoted by Aquinas, AD 1274)', or prose like 'is referenced
    above by Jerome (AD 420)'. Wrap only when none are present; always strip
    the stray leading space."""
    suffix = (e.get('author_suffix') or '').strip()
    if suffix and '(' not in suffix:
        suffix = f'({suffix})'
    return e['author'], suffix


def _author_label(e):
    """Author with the suffix, one line — the copy line's attribution."""
    name, suffix = _author_parts(e)
    return f'{name} {suffix}' if suffix else name


def _source_title(e):
    """Display form of an entry's source title: ALL-CAPS tamed, and a leading
    repeat of the author's name dropped — the pack's titles often embed it
    ("Irenaeus Against Heresies Book 3" under an IRENAEUS eyebrow)."""
    title = _display_title(e.get('source_title') or '')
    author = e['author']
    if author and title.lower().startswith(author.lower()):
        rest = title[len(author):].lstrip(' ,:;-–—')
        if rest:
            title = rest[0].upper() + rest[1:]
    return title


def _display_title(title):
    """Tame an ALL-CAPS source title ("FRAGMENTS ON JOHN 12") to title case.
    Display-time repair until the pack rebuild normalizes titles at build
    time; a title with any lowercase in it passes through untouched."""
    if not title or any(c.islower() for c in title):
        return title
    words = []
    for i, w in enumerate(title.split()):
        lw = w.lower()
        if i and lw in _TITLE_SMALL_WORDS:
            words.append(lw)
        elif re.fullmatch('[IVXLCDM]+', w):
            words.append(w)          # roman numeral (HOMILY XII)
        elif any(c.isdigit() for c in w) and not w.isdigit():
            words.append(w)          # locator token (Q.37.R, XII.3, 215:2)
        else:
            words.append(w.capitalize())
    return ' '.join(words)


def _year_label(year):
    if year is None or year == catena_bridge._UNKNOWN_YEAR:
        return ''
    if year < 0:
        return _('c. {year} BC').format(year=-year)
    return _('c. {year} AD').format(year=year)
