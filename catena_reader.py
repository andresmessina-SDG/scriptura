"""catena_reader.py — the Historical Commentaries pane subsystem.

Renders the "chorus" of church-history voices on the verse the partnered
Bible pane is showing: chronological cards grouped by era, each with the
author, year, source link, and the quote (previewed, expandable). Mirrors
genbook_reader's shape — a class the pane composes and drives — but owns
a card list rather than the flowing TextView.
"""

import html
import logging

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio
from a11y import set_accessible_label

import catena_bridge

_log = logging.getLogger('scriptura.catena')

# Chronological order for the era filter chips and dividers.
_ERA_ORDER = ['Ante-Nicene', 'Nicene & Post-Nicene', 'Medieval',
              'Reformation', 'Modern', 'Unknown']

# Quotes longer than this get a "more"/"less" toggle (the card shows only
# a short preview string until expanded) so a 1,000-word Augustine entry
# doesn't bury the others — and its full layout isn't built until read.
_PREVIEW_CHARS = 320

# Cap the cards rendered at once. A handful of verses (John 1:1 has 100+)
# would otherwise spawn hundreds of wrapping labels that re-flow on every
# pane resize. The rest surface behind a "show all" button.
_CARD_CAP = 25

# Show the per-figure author filter only once a verse has enough voices
# that scanning by eye gets tedious.
_AUTHOR_FILTER_MIN = 6


class CatenaReader:
    def __init__(self, pane=None):
        self._pane = pane
        self._book = None
        self._chapter = None
        self._verse = None
        self._entries = []
        self._era_filter = None  # None == "All"
        self._author_query = ''  # per-figure substring filter
        self._show_all = False   # cap rendered cards until the user asks
        self._build_widget()

    @property
    def widget(self):
        return self._root

    # ── construction ────────────────────────────────────────────────────────

    def _build_widget(self):
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._header = Gtk.Label(xalign=0, wrap=True)
        self._header.add_css_class('title-4')
        self._header.add_css_class('catena-header')
        self._root.append(self._header)

        # Per-figure filter — appears only when a verse has many voices.
        self._author_entry = Gtk.SearchEntry()
        self._author_entry.set_placeholder_text(_('Filter by author…'))
        self._author_entry.set_margin_start(14)
        self._author_entry.set_margin_end(14)
        self._author_entry.set_margin_top(2)
        self._author_entry.set_margin_bottom(10)
        self._author_entry.connect('search-changed', self._on_author_search)
        self._author_entry.set_visible(False)
        self._root.append(self._author_entry)

        self._chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._chip_box.add_css_class('catena-chips')
        self._root.append(self._chip_box)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        self._list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._list.add_css_class('catena-list')
        scroll.set_child(self._list)
        self._root.append(scroll)

    # ── public drive ──────────────────────────────────────────────────────────

    def render_for(self, book, chapter, verse):
        """Show commentary on a verse (driven by the partnered Bible pane)."""
        self._book, self._chapter, self._verse = book, chapter, verse
        self._era_filter = None
        self._show_all = False
        self._author_query = ''
        if self._author_entry.get_text():
            self._author_entry.set_text('')  # guarded no-op rebuild below
        try:
            self._entries = catena_bridge.lookup(book, chapter, verse) \
                if book and chapter and verse else []
        except Exception:
            _log.exception('catena lookup failed')
            self._entries = []
        self._rebuild()

    # ── rendering ──────────────────────────────────────────────────────────────

    def _clear(self, box):
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _rebuild(self):
        self._clear(self._list)
        self._clear(self._chip_box)

        if not self._book:
            self._header.set_text(_('Historical Commentaries'))
            self._list.append(self._status(
                _('Open a Bible alongside this pane'),
                _('Select a verse there to see how the early church, the '
                  'medieval doctors, and the Reformers read it.')))
            return

        ref = f'{book_label(self._book)} {self._chapter}:{self._verse}'
        n = len(self._entries)
        self._author_entry.set_visible(n > _AUTHOR_FILTER_MIN)

        shown = [
            e for e in self._entries
            if (self._era_filter is None or e['era'] == self._era_filter)
            and (not self._author_query
                 or self._author_query in e['author'].lower())
        ]

        filtering = self._era_filter is not None or bool(self._author_query)
        if not n:
            self._header.set_text(ref)
        elif filtering:
            self._header.set_text(
                _('{ref} · {shown} of {total}').format(
                    ref=ref, shown=len(shown), total=n))
        else:
            self._header.set_text(ngettext(
                '{ref} · {n} voice', '{ref} · {n} voices', n).format(ref=ref, n=n))

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

        display = shown if self._show_all else shown[:_CARD_CAP]
        prev_era = None
        for e in display:
            if e['era'] != prev_era:
                self._list.append(self._era_divider(e['era']))
                prev_era = e['era']
            self._list.append(self._card(e))

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
            chip = Gtk.ToggleButton(label=_('All') if value == 'All' else value)
            chip.add_css_class('pill')
            active = (value == 'All' and self._era_filter is None) \
                or (value == self._era_filter)
            if active:
                chip.set_active(True)
                chip.add_css_class('suggested-action')
            chip.connect('toggled', self._on_chip_toggled, value)
            self._chip_box.append(chip)

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

    def _on_author_search(self, entry):
        q = entry.get_text().strip().lower()
        if q == self._author_query:
            return  # guard the programmatic clear in render_for
        self._author_query = q
        self._show_all = False
        self._rebuild()

    def _era_divider(self, era):
        lbl = Gtk.Label(label=f'·· {era} ··', xalign=0)
        lbl.add_css_class('catena-era')
        lbl.add_css_class('caption')
        return lbl

    def _card(self, e):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class('card')
        card.add_css_class('catena-card')

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        author = e['author']
        if e.get('author_suffix'):
            author = f'{author} ({e["author_suffix"]})'
        author_lbl = Gtk.Label(label=author, xalign=0, hexpand=True, wrap=True)
        author_lbl.add_css_class('catena-author')
        head.append(author_lbl)
        year_lbl = Gtk.Label(label=_year_label(e['year']), xalign=1)
        year_lbl.add_css_class('caption')
        year_lbl.add_css_class('catena-meta')
        year_lbl.set_valign(Gtk.Align.START)
        head.append(year_lbl)
        card.append(head)

        if e.get('source_title') or e.get('source_url'):
            src_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            src_lbl = Gtk.Label(label=e.get('source_title') or _('Source'),
                                xalign=0, hexpand=True, wrap=True)
            src_lbl.add_css_class('caption')
            src_lbl.add_css_class('catena-meta')
            src_row.append(src_lbl)
            if e.get('source_url'):
                link = Gtk.Button(icon_name='adw-external-link-symbolic')
                link.add_css_class('flat')
                link.add_css_class('circular')
                link.set_valign(Gtk.Align.CENTER)
                link.set_tooltip_text(_('Open source'))
                set_accessible_label(link, _('Open source'))
                link.connect('clicked', self._open_url, e['source_url'])
                src_row.append(link)
            card.append(src_row)

        text = html.unescape(e['text']).strip()
        quote = Gtk.Label(xalign=0, wrap=True, selectable=True)
        quote.add_css_class('catena-quote')
        quote.set_margin_top(2)
        card.append(quote)

        if len(text) > _PREVIEW_CHARS:
            # Lazy: hold only a short preview string until the user expands,
            # so a long quote's full Pango layout is never built unless read.
            preview = text[:_PREVIEW_CHARS].rsplit(' ', 1)[0].rstrip() + '…'
            quote.set_text(preview)
            toggle = Gtk.Button(label=_('more'))
            toggle.add_css_class('flat')
            toggle.set_halign(Gtk.Align.START)
            toggle.connect('clicked', self._toggle_more, quote, preview, text)
            card.append(toggle)
        else:
            quote.set_text(text)

        return card

    def _toggle_more(self, btn, quote, preview, full):
        if btn.get_label() == _('more'):
            quote.set_text(full)
            btn.set_label(_('less'))
        else:
            quote.set_text(preview)
            btn.set_label(_('more'))

    def _open_url(self, _btn, url):
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except Exception:
            _log.exception('could not open %s', url)

    def _status(self, title, detail):
        page = Adw.StatusPage()
        page.set_icon_name('accessories-dictionary-symbolic')
        page.set_title(title)
        page.set_description(detail)
        page.set_vexpand(True)
        return page


def _year_label(year):
    if year is None or year == 9999:
        return ''
    if year < 0:
        return _('c. {year} BC').format(year=-year)
    return _('c. {year} AD').format(year=year)
