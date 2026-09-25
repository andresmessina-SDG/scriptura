"""Annotation dialogs — study menu, note editor, chapter-note editor,
compare-translations popover, suggested-topics chip row.

All functions take a `pane` argument (the BiblePane instance) and read
pane location state (`_module`, `_book`, `_chapter`), the view, the
buffer, and the in-place annotation refresh helper through it. The
pane keeps ownership of widget state — these are pure builders that
return / show popovers and windows.

The right-click popover is the entry point: `show_study_menu(pane,
verses, x, y)` builds the menu and wires its buttons to other
functions in this module.
"""

import logging
import re
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, Pango

from a11y import set_accessible_description, set_accessible_label, set_role
from gtk_utils import Autosave, clear_children, DelayedSpinner
import annotations
import bible_family
from family_card import paint_track, redraw_on_contrast
import content
import journal
import sermons
import settings
import export_dialog
import passage_export
import passage_print
import sword_bridge
import ebible_bridge
import open_data
from i18n import _, ngettext, C_, book_label

_log = logging.getLogger('scriptura.notes')


def highlight_swatches():
    """The four highlight colours as (hex, css class, display name).

    A function rather than a module constant so the names resolve against
    the live gettext catalogue instead of freezing at import time."""
    return [('#ffff00', 'hl-yellow', _('Yellow')),
            ('#90ee90', 'hl-green', _('Green')),
            ('#add8e6', 'hl-blue', _('Blue')),
            ('#ffa500', 'hl-orange', _('Orange'))]


def highlight_letter(color):
    """The muted initial on a swatch: the non-hue cue for a reader who cannot
    tell the four colours apart, or '' for an unrecognised hex.

    Its own translatable string per colour rather than the first letter of the
    colour name, because in Spanish *Amarillo* and *Azul* both begin with A
    and the cue then said nothing. po/es keeps the English letters; po/ru uses
    its own initials (Ж З С О), which are distinct.

    Both halves are spelt out at every call: xgettext reads literals, so a
    `C_(ctx, msg)` on variables extracts as nothing at all and the catalogue
    would hold a string the build could no longer find. The same arrangement
    `church_year.ordinal` and `i18n.month_abbr` need.
    """
    return {
        '#ffff00': C_('highlight swatch cue letter', 'Y'),
        '#90ee90': C_('highlight swatch cue letter', 'G'),
        '#add8e6': C_('highlight swatch cue letter', 'B'),
        '#ffa500': C_('highlight swatch cue letter', 'O'),
    }.get(color, '')


def highlight_name(color):
    """Display name for a stored highlight hex, or None if unrecognised.

    Used by the reading pane to say "highlighted yellow" rather than
    "#ffff00" when it announces a verse's state to AT."""
    for hex_value, _css, name in highlight_swatches():
        if hex_value == color:
            return name
    return None


def _grab_focus_once(widget):
    """idle_add target that focuses `widget` exactly once.

    Gtk.Widget.grab_focus() returns True, so a bare
    GLib.idle_add(widget.grab_focus) keeps returning a truthy value and
    re-arms itself every idle cycle — continuously stealing focus back to
    `widget`, so sibling fields (e.g. the tags entry) can never be focused.
    Returning SOURCE_REMOVE makes it a true one-shot.
    """
    widget.grab_focus()
    return GLib.SOURCE_REMOVE


# ── Right-click study menu ───────────────────────────────────────────────────

#: How much of a manuscript's title a menu row carries. The pages share one
#: width — the stack is homogeneous, so the longest label anywhere, including
#: a slide away, sets how wide the menu opens over the verse. Measured: an
#: untruncated title took it from 270px to 390px.
_TITLE_CAP = 24


def _short(title):
    """`title`, capped so one long sermon name cannot widen the whole menu."""
    title = ' '.join((title or '').split())
    return title if len(title) <= _TITLE_CAP \
        else title[:_TITLE_CAP].rstrip() + '…'


#: The icon gutter: glyph, then the gap to the words. Every row in the menu
#: measures its label from the same x, and so does every section caption —
#: three ragged left edges (caption, label, swatches) is what made his live
#: screenshot read as crooked before anything else did.
_ICON = 16
_GUTTER = 10
_ROW_PAD = 6


def _menu_row(icon_name, label, submenu=False):
    """A flat menu row: leading glyph, label, and a chevron when it leads to
    a page rather than doing something.

    Hand-built, and it has to be. `GtkPopoverMenu` gives menu semantics for
    free but **cannot show an icon** — measured under GTK 4.22: a model
    item's `icon` attribute is ignored and setting `GtkModelButton:icon`
    leaves the image hidden, because that image is only drawn for `iconic`
    (icon-only) buttons. The app draws its own line art and the menu is where
    a reader meets most of it, so the rows are ours and the semantics are put
    on by hand — see `_menu_page`.
    """
    btn = Gtk.Button()
    btn.add_css_class('flat')
    set_role(btn, Gtk.AccessibleRole.MENU_ITEM)
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=_GUTTER)
    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_pixel_size(_ICON)
    content.append(image)
    text = Gtk.Label(label=label, xalign=0, hexpand=True)
    text.set_ellipsize(Pango.EllipsizeMode.END)
    content.append(text)
    if submenu:
        chevron = Gtk.Image.new_from_icon_name('scriptura-pan-end-symbolic')
        chevron.add_css_class('dim-label')
        content.append(chevron)
    btn.set_child(content)
    return btn


def _menu_title(text):
    """What the menu is about, over the middle of it.

    It began as a dim `caption` set against the labels' left edge, and read
    as a row that had lost its icon rather than as the menu's name. A title
    belongs to the whole popover, not to the column of rows under it: it is
    centred, and set in `heading` like the compare popover's own title, so
    the menu opens saying which verse it is holding.
    """
    lbl = Gtk.Label(label=text)
    lbl.set_halign(Gtk.Align.CENTER)
    lbl.add_css_class('heading')
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_margin_top(4)
    lbl.set_margin_bottom(4)
    return lbl


def _menu_page():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_margin_start(_ROW_PAD)
    box.set_margin_end(_ROW_PAD)
    box.set_margin_top(_ROW_PAD)
    box.set_margin_bottom(_ROW_PAD)
    set_role(box, Gtk.AccessibleRole.GROUP)
    return box


def _menu_separator():
    rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    rule.set_margin_top(4)
    rule.set_margin_bottom(4)
    return rule


def _hue_row(pane, verses, popover, any_highlighted):
    """The four hues and the way off them, as one row of five equal chips.

    `Clear` is the fifth chip and not a row of its own. As a row it appeared
    and vanished with the verse under the pointer, moving everything below
    it; as a small flat button at the end of the row it read as something
    that had fallen off the end. Empty, bordered, the same box as the
    colours: it is the same act — setting the hue to none.
    """
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.set_homogeneous(True)
    row.set_margin_start(_ROW_PAD)
    row.set_margin_end(_ROW_PAD)
    row.set_margin_top(2)
    row.set_margin_bottom(4)
    for color, css_cls, name in highlight_swatches():
        btn = Gtk.Button()
        btn.set_size_request(-1, 28)
        btn.add_css_class(css_cls)
        # Muted initial as a non-hue (colorblind-safe) cue — its own string
        # per language, not the colour name's first letter (see _HL_LETTERS).
        letter = Gtk.Label(label=highlight_letter(color))
        letter.add_css_class('hl-letter')
        btn.set_child(letter)
        # Icon-/color-only control: give AT the color name (no visible change).
        set_accessible_label(btn, name)
        # A chip is a menu item like any other row: it acts and the menu
        # closes. Left as a plain `button` it was the one thing in here a
        # screen reader announced differently from its neighbours.
        set_role(btn, Gtk.AccessibleRole.MENU_ITEM)
        btn.connect('clicked',
                    lambda b, c=color: apply_highlight(pane, verses, c,
                                                       popover))
        row.append(btn)
    clear = Gtk.Button(icon_name='scriptura-edit-clear-symbolic')
    clear.set_size_request(-1, 28)
    clear.add_css_class('hl-clear')
    clear.set_tooltip_text(_('Clear Highlight'))
    set_accessible_label(clear, _('Clear Highlight'))
    set_role(clear, Gtk.AccessibleRole.MENU_ITEM)
    # Always drawn, so the row never changes shape; live only when there is
    # a highlight to take off.
    clear.set_sensitive(any_highlighted)
    clear.connect('clicked',
                  lambda b: apply_highlight(pane, verses, None, popover))
    row.append(clear)
    return row


def _slide(stack, name, back_to=None):
    """Show one page and put the keyboard on it.

    The focus move is the whole reason a submenu is usable without a mouse:
    without it the caret stays on the row that opened the page, and the next
    Down goes to the row under it on a page nobody can see.
    """
    stack.set_visible_child_name(name)
    # A popover grows to fit a taller page but never shrinks for a shorter
    # one: measured under mutter, Share opened at the main page's 546px with
    # three rows in it. Presenting again sizes the surface to the new page.
    popover = stack.get_ancestor(Gtk.Popover)
    if popover is not None and popover.get_visible():
        popover.present()
    page = stack.get_child_by_name(name)
    first = page.get_first_child()
    while first is not None and not isinstance(first, Gtk.Button):
        first = first.get_next_sibling()
    if first is not None:
        first.grab_focus()
    return back_to


def _submenu_page(stack, name, title, icon):
    """A page, with the way back at the head of it.

    A back row rather than a back button in a header: it is the first thing
    the keyboard lands on, Left and Escape reach it too, and it names where
    it returns to instead of pointing at nothing.
    """
    page = _menu_page()
    back = _menu_row('scriptura-go-previous-symbolic', title)
    back.connect('clicked', lambda b: _slide(stack, 'main'))
    page.append(back)
    page.append(_menu_separator())
    keys = Gtk.EventControllerKey()

    def on_key(_c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Escape):
            _slide(stack, 'main')
            return True
        return False

    keys.connect('key-pressed', on_key)
    page.add_controller(keys)
    stack.add_named(page, name)
    return page


def _opens(stack, name):
    """A row that leads to a page: click, Enter, or Right."""
    def wire(row):
        row.connect('clicked', lambda b: _slide(stack, name))
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed',
                     lambda _c, keyval, _code, _s: (
                         _slide(stack, name) or True)
                     if keyval == Gdk.KEY_Right else False)
        row.add_controller(keys)
        return row
    return wire


def show_study_menu(pane, verses, x, y):
    """Right-click annotation menu — highlight colors, underline, note,
    copy, compare translations. Single-verse-only actions (note, compare)
    are omitted when multiple verses are selected."""
    build_study_menu(pane, verses, x, y).popup()


def build_study_menu(pane, verses, x, y, anchor=None):
    """The menu itself, built and parented but not yet shown.

    Split from the showing so its size can be measured without a window:
    `popup()` on a popover whose parent has no root segfaults, and what
    tests/test_study_menu_fit.py needs to know is how small this can be
    made, not what it looks like on screen.

    **Grouped by verb, and the size of it fixed.** It was twelve flat rows
    and 540px of them for a reader a year in — past the 498px that once made
    this menu fit nowhere and silently not open at all — and five of those
    rows were conditional, so the row a reader reached for moved as their own
    writing accumulated. Now the things done oftenest are at the head, the
    occasional ones are one slide deep behind the verb they belong to, and
    everything that can appear or vanish is last. Same menu on day one as a
    year in.

    **Depth only where what it hides is rare.** `Share ▸` earns its slide:
    three items, all occasional, all one shape of one act. `Write ▸` did
    not — it held a single row until a reader had saved a manuscript — so
    `Write an entry` is a row on this page and `Add to “…”` sits in the last
    group with the rest of the reader's own writing.

    The pages slide inside one popover rather than flying out sideways: a
    flyout needs room beside the menu, and this menu's history is precisely
    about not having room.
    """
    # `anchor` is the toolbar's ⋮ — the visible door to this same menu. It
    # is parented to the button and left to point at the button itself; a
    # click point belongs to the text, and there is none when the menu was
    # not opened over a verse.
    popover = Gtk.Popover(accessible_role=Gtk.AccessibleRole.MENU)
    popover.set_parent(anchor if anchor is not None else pane.view)
    popover.connect('closed', lambda p: p.unparent())
    if anchor is None:
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)

    # Load this chapter's annotations once — drives the underline label, the
    # note prefill, and whether the clear chip is live.
    annos = annotations.get_annotations(pane.module, pane.book, pane.chapter)

    def _verse_anno(v):
        a = annos.get(str(v), {})
        return {'highlight': a} if isinstance(a, str) else (a or {})

    any_highlighted = any(_verse_anno(v).get('highlight') for v in verses)
    all_underlined = all(_verse_anno(v).get('underline', False)
                         for v in verses)
    single = len(verses) == 1
    anno = _verse_anno(verses[0]) if single else {}
    note_text = anno.get('note', '')
    current_tags = anno.get('tags', [])

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    stack.set_transition_duration(140)
    # The width is shared so the menu never jumps sideways mid-slide; the
    # height is not, so a short page is not padded out to the tall one.
    stack.set_hhomogeneous(True)
    stack.set_vhomogeneous(False)
    # **No `interpolate-size`.** `GtkPopoverMenu` sets it and gets away with
    # it; here it left the stack asking for the TALLEST page's height on
    # every page, so a submenu opened as its two or three rows over three
    # hundred pixels of empty popover. Measured on 4.22.5: with it on the
    # stack requests 393px whichever page shows; with it off it requests
    # 393 / 165 / 93, which is the three pages' own heights. The slide is
    # unaffected — only the height animation during it is gone.
    stack.set_interpolate_size(False)

    main = _menu_page()
    stack.add_named(main, 'main')

    # ── What this verse is marked with ──────────────────────────────────
    main.append(_menu_title(
        _('Verse {v}').format(v=verses[0]) if single
        else _('Verses {first}–{last}').format(first=verses[0],
                                               last=verses[-1])))
    main.append(_hue_row(pane, verses, popover, any_highlighted))

    underline = _menu_row(
        'scriptura-format-text-underline-symbolic',
        _('Remove Underline') if all_underlined else _('Underline'))
    underline.connect('clicked', lambda b: toggle_underline(
        pane, verses, not all_underlined, popover))
    main.append(underline)

    if single:
        note = _menu_row(
            'scriptura-document-edit-symbolic',
            _('Edit Note & Tags') if (note_text or current_tags)
            else _('Note & Tags'))
        note.connect('clicked', lambda b: _edit_note(
            pane, verses[0], note_text, current_tags, popover))
        main.append(note)

    copy = _menu_row('scriptura-edit-copy-symbolic',
                     _('Copy verse') if single else _('Copy verses'))
    copy.connect('clicked', lambda b: copy_verse(pane, verses, popover))
    main.append(copy)

    # ── What it can become ──────────────────────────────────────────────
    main.append(_menu_separator())

    # **No `Write ▸`.** It was a submenu holding ONE row until the reader
    # had written a sermon, and two ever after — under the three-to-six a
    # submenu wants, and squarely inside the rule that hiding one or two
    # actions behind a disclosure saves no space and costs discoverability.
    # Depth is only free where what it buries is rare, and writing an entry
    # from a verse is the verb this whole arc was built for. It is a row.
    #
    # The journal glyph, not the pencil the note row carries: a mark is a
    # margin and an entry is a page, and two rows under one glyph said they
    # were the same thing.
    entry = _menu_row('scriptura-journal-symbolic', _('Write an entry'))
    entry.connect('clicked', lambda b: _write_entry(pane, verses, popover))
    main.append(entry)

    share_page = _submenu_page(stack, 'share', _('Share'),
                               'scriptura-document-save-symbolic')
    export = _menu_row('scriptura-document-save-symbolic',
                       _('Export passage…'))
    export.connect('clicked', lambda b: export_dialog.export_passage(
        pane, verses, popover))
    share_page.append(export)
    # "As an image…" and not "Share as image…": the parent already says
    # share, and a page that repeats its own parent reads as a mistake. The
    # sheet it opens is still titled Share as image.
    card = _menu_row('scriptura-image-x-generic-symbolic', _('As an image…'))
    card.connect('clicked', lambda b: export_dialog.share_as_image(
        pane, verses, popover))
    share_page.append(card)
    printing = _menu_row('scriptura-document-print-symbolic', _('Print…'))
    printing.connect('clicked', lambda b: passage_print.print_passage(
        pane, verses, popover))
    share_page.append(printing)
    main.append(_opens(stack, 'share')(_menu_row(
        'scriptura-document-save-symbolic', _('Share'), submenu=True)))

    if single:
        compare = _menu_row('scriptura-view-dual-symbolic',
                            _('Compare translations'))
        compare.connect('clicked',
                        lambda b: compare_translations(pane, verses[0],
                                                       popover))
        main.append(compare)

    # ── Your own writing ────────────────────────────────────────────────
    # Everything above this separator is the same on day one as a year in.
    # Everything below it exists only because the reader has written
    # something, so it is all last, where appearing can move nothing anyone
    # was reaching for — the rule the twelve-row menu broke five times over.
    #
    # `Add to “…”` lives here rather than beside `Write an entry` for that
    # reason alone: grouped with the entry it would push Share and Compare
    # down the day a reader saved their first manuscript. Here it is in the
    # company it belongs to anyway — this group is the reader's own work on
    # this passage, collected.
    sermon = sermons.most_recent()
    written = journal.entries_on(pane.book, pane.chapter)
    preached = sermons.sermons_on(pane.book, pane.chapter)
    if sermon is not None or written or preached:
        main.append(_menu_separator())

    if sermon is not None:
        # Named, so it can never be wrong about where the words went, and
        # capped so one long manuscript title cannot widen the menu.
        collect = _menu_row(
            'scriptura-sermons-symbolic',
            _('Add to “{title}”').format(
                title=_short(sermon['title']) or _('Untitled sermon')))
        collect.connect('clicked', lambda b: _collect_verses(
            pane, verses, sermon['id'], popover))
        main.append(collect)

    recall = []
    if written:
        recall.append((
            'scriptura-journal-symbolic',
            ngettext('{n} entry on this chapter',
                     '{n} entries on this chapter',
                     len(written)).format(n=len(written)),
            lambda b: _open_journal_on(pane, popover)))
    if preached:
        recall.append((
            'scriptura-sermons-symbolic',
            ngettext('{n} sermon on this chapter',
                     '{n} sermons on this chapter',
                     len(preached)).format(n=len(preached)),
            lambda b: _open_sermons_on(pane, popover)))

    # One row costs the same inline as the submenu row that would hide it,
    # so hiding it buys nothing and charges a click — which is the rule
    # `Write ▸` broke. Two rows are worth the slide, and only two are
    # possible: entries and sermons.
    if len(recall) == 1:
        icon, label, act = recall[0]
        row = _menu_row(icon, label)
        row.connect('clicked', act)
        main.append(row)
    elif recall:
        here = _submenu_page(stack, 'here', _('Written on this chapter'),
                             'scriptura-annotations-symbolic')
        for icon, label, act in recall:
            row = _menu_row(icon, label)
            row.connect('clicked', act)
            here.append(row)
        main.append(_opens(stack, 'here')(_menu_row(
            'scriptura-annotations-symbolic', _('Written on this chapter'),
            submenu=True)))

    # A popover that fits nowhere is not shown at all. GTK places this one
    # below the pointer, flips it above when that will not fit, and if
    # neither fits it pops straight back down without a word — so in a short
    # window the menu simply did not open for a right-click anywhere in the
    # middle of the column. Measured on his 686x709 window: 498px of menu in
    # a 607px view, dead from y=180 to y=340, working above and below it.
    # Inside a scroller the menu's MINIMUM height is one row, so GTK can fit
    # it into whatever room there is and scroll the remainder; the natural
    # height still wins wherever there is space for it.
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_propagate_natural_height(True)
    scroller.set_max_content_height(560)
    scroller.set_child(stack)
    popover.set_child(scroller)
    return popover


# ── Annotation save handlers — in-place tag refresh, no re-render ───────────

def apply_highlight(pane, verses, color, popover):
    for v in verses:
        annotations.save_highlight(pane.module, pane.book, pane.chapter, v, color)
    popover.popdown()
    for v in verses:
        pane._refresh_verse_annotation(v)


def toggle_underline(pane, verses, enabled, popover):
    for v in verses:
        annotations.save_underline(pane.module, pane.book, pane.chapter, v, enabled)
    popover.popdown()
    for v in verses:
        pane._refresh_verse_annotation(v)


# ── Copy verse to clipboard ──────────────────────────────────────────────────

def copy_verse(pane, verses, popover):
    popover.popdown()
    chapter_verses = content.load_chapter(pane.module, pane.book, pane.chapter)
    verse_map = {v: html for v, html in chapter_verses}
    lines = []
    for v in verses:
        plain = re.sub(r'<[^>]+>', '', str(verse_map.get(v, ''))).strip()
        lines.append(f'{book_label(pane.book)} {pane.chapter}:{v}  {plain}')
    ref = (f'{book_label(pane.book)} {pane.chapter}:{verses[0]}–{verses[-1]}'
           if len(verses) > 1 else f'{book_label(pane.book)} {pane.chapter}:{verses[0]}')
    version = passage_export.version_label(pane.module)
    text = f'{ref} ({version})\n' + '\n'.join(lines)
    pane.view.get_clipboard().set(text)
    if pane._on_toast:
        pane._on_toast(_('Copied {ref}').format(ref=ref))


# ── Compare translations popover ─────────────────────────────────────────────

def _verse_rect(pane, verse):
    """A 1px rectangle on the verse itself, in `pane._view` coordinates.

    What a popover points at when nobody clicked anything — the keyboard and
    the toolbar's ⋮ both arrive here with no pointer position, and a fixed
    corner of the view would put the card somewhere the verse is not.
    """
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = 160, 80, 1, 1
    ranges = pane._verse_ranges(verse)
    if ranges:
        location = pane.view.get_iter_location(ranges[1])
        rect.x, rect.y = pane.view.buffer_to_window_coords(
            Gtk.TextWindowType.WIDGET, location.x, location.y)
    return rect


def compare_translations(pane, verse, popover=None):
    # Reuse the study menu's anchor (the click point) so the compare popover
    # opens where the user clicked, like the menu it replaces — both are
    # parented to pane._view, so the rect is in the same coordinate space.
    # Opened from the toolbar the menu is parented to a button instead, and
    # its rect would mean nothing here; the verse's own position is used.
    ok, src_rect = (False, None)
    if popover is not None:
        if popover.get_parent() is pane.view:
            ok, src_rect = popover.get_pointing_to()
        popover.popdown()

    comp = Gtk.Popover()
    comp.set_parent(pane.view)
    comp.connect('closed', lambda p: p.unparent())
    comp.set_pointing_to(src_rect if ok else _verse_rect(pane, verse))

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    title = Gtk.Label(
        label=_('{ref} — Translations').format(
            ref=f'{book_label(pane.book)} {pane.chapter}:{verse}'),
        xalign=0)
    title.add_css_class('heading')
    title.set_hexpand(True)

    # Other languages: off by default, so a compare reads within the
    # language on the page. Shown only when a Bible in another language is
    # installed — with none there is nothing to switch.
    #
    # Decided here, before the popover is shown, from the installed Bibles'
    # languages — never later, when the verses arrive. Revealing the switch
    # then made the header taller on a popover already on screen, and
    # GNOME Shell dismissed the resized popup: Compare flashed and closed on
    # every route. The rows are safe; they fill a scroller of fixed limits.
    names = _compare_names()
    reading = pane.module
    lang = content.language_code(reading)
    _same, other_names = _split_by_language(
        [(m, '') for m in names], content.language_code, lang)
    others_lbl = Gtk.Label(label=_('Other languages'))
    others_lbl.add_css_class('dim-label')
    others = Gtk.Switch(valign=Gtk.Align.CENTER,
                        active=bool(settings.get('compare_other_languages')))
    set_accessible_label(others, _('Other languages'))
    others_lbl.set_visible(bool(other_names))
    others.set_visible(bool(other_names))

    header = Gtk.Box(spacing=8)
    header.set_margin_start(12)
    header.set_margin_end(12)
    header.set_margin_top(8)
    header.set_margin_bottom(6)
    header.append(title)
    header.append(others_lbl)
    header.append(others)
    outer.append(header)

    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_width(420)
    scroll.set_min_content_height(200)
    scroll.set_max_content_height(420)
    scroll.set_propagate_natural_height(True)

    # Local — two compare popovers in flight don't clobber each other.
    comp_list = Gtk.ListBox()
    comp_list.set_selection_mode(Gtk.SelectionMode.NONE)
    comp_list.add_css_class('compare-list')
    comp_list.set_margin_start(8)
    comp_list.set_margin_end(8)
    comp_list.set_margin_top(8)
    comp_list.set_margin_bottom(8)

    # Delayed: cached chapter loads populate the list well under the
    # perception threshold, so the spinner only appears for a cold fetch.
    spinner = Gtk.Spinner()
    spinner.set_visible(False)
    spinner.set_margin_top(12)
    spinner.set_margin_bottom(12)
    comp_list.append(spinner)
    delayed_spinner = DelayedSpinner(spinner)
    delayed_spinner.start()

    scroll.set_child(comp_list)
    outer.append(scroll)
    comp.set_child(outer)
    comp.popup()

    book, chapter = pane.book, pane.chapter

    def fetch():
        results = []
        for mod in names:
            vs = content.load_chapter(mod, book, chapter)
            # `verse` is app-space; the rows carry the module's own
            # numbering, which on a Synodal or Vulgate psalter counts the
            # superscription. Without this the comparison showed «Псалом
            # Давида, когда он бежал…» where the KJV column shows verse 1.
            want = sword_bridge.map_target_verse(mod, book, chapter, verse)
            v_html = next((h for vn, h in vs if vn == want), '')
            plain = re.sub(r'<[^>]+>', '', str(v_html)).strip()
            if plain:
                results.append((mod, plain))
        # From word for word to free, so every compare reads as the spectrum.
        order = bible_family.order_by_line([mod for mod, _t in results])
        results.sort(key=lambda r: order.index(r[0]))
        GLib.idle_add(populate, results)

    shown = {}

    def populate(results):
        delayed_spinner.stop()
        if comp.get_parent() is None:
            return GLib.SOURCE_REMOVE
        # Languages are read here, on the UI thread: a module's config read
        # is not guarded against the worker that loads the verses.
        same, other = _split_by_language(results, content.language_code, lang)
        shown['same'], shown['other'] = same, other
        fill()
        return GLib.SOURCE_REMOVE

    def on_others(sw, _pspec):
        settings.put('compare_other_languages', sw.get_active())
        fill()
        # A popover grows for a longer list but never shrinks for a shorter
        # one; presenting again sizes it to the rows now in it.
        comp.present()

    others.connect('notify::active', on_others)

    def fill():
        if 'same' not in shown:
            return
        clear_children(comp_list)
        rows = shown['same'] + (shown['other'] if others.get_active() else [])
        for mod, text in rows:
            row = Gtk.ListBoxRow()
            rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            rb.set_margin_start(12)
            rb.set_margin_end(12)
            rb.set_margin_top(8)
            rb.set_margin_bottom(8)
            head = Gtk.Box(spacing=12)
            ml = Gtk.Label(label=sword_bridge.display_name(mod), xalign=0,
                           hexpand=True)
            ml.add_css_class('compare-version')
            head.append(ml)
            spot = bible_family.place(mod)
            if spot is not None:
                words = _line_words(spot)
                head.append(_line_tick(spot, words))
                set_accessible_description(row, words)
            tl = Gtk.Label(label=text, xalign=0, wrap=True)
            tl.set_max_width_chars(52)
            rb.append(head)
            rb.append(tl)
            row.set_child(rb)
            comp_list.append(row)

    threading.Thread(target=fetch, daemon=True).start()


def _compare_names():
    """Every installed Bible a compare can list."""
    names = [m for m in sword_bridge.module_names()
             if not sword_bridge.is_internal_use(m)
             and sword_bridge.module_type(m) == 'Biblical Texts']
    return names + ebible_bridge.module_names()


def _split_by_language(results, lang_of, lang):
    """[(module, text)] split into the Bibles in `lang` and the rest, each
    keeping its order. The Bible being read leads, in its own language,
    whatever language the app is in. An unknown `lang`, or one no row
    shares, counts everything as one language: the list never opens empty
    behind a switch.
    """
    same = [r for r in results if lang and lang_of(r[0]) == lang]
    if not same:
        return list(results), []
    return same, [r for r in results if lang_of(r[0]) != lang]


def _line_words(spot):
    """Where a Bible sits on the Line, and on whose word, as a sentence."""
    zone = bible_family.zone_label(spot.value)
    if spot.kind == 'band':
        return _('{zone}, where published charts place it').format(zone=zone)
    if spot.kind == 'measured':
        return _('{zone}, as measured in Scriptura').format(zone=zone)
    return _('{zone}, as its makers describe it').format(zone=zone)


def _line_tick(spot, words):
    """A small copy of the Line's track, with this Bible's mark on it.

    The marks are the Line's own: a filled dot on a soft range where published
    charts place it, a ring where Scriptura measured it, a bracket where only
    its makers' description is known. A Bible past the free end is pinned there.
    """
    area = Gtk.DrawingArea()
    area.set_content_width(56)
    area.set_content_height(12)
    area.set_valign(Gtk.Align.CENTER)
    area.set_tooltip_text(words)
    area.set_draw_func(
        lambda a, cr, w, h: paint_track(cr, w, h, spot, a.get_color()))
    redraw_on_contrast(area)
    return area


def _open_journal_on(pane, parent_popover):
    """Open the journal on this chapter's entries.

    Same teardown dance as the other doors: the window is built on the next
    idle, after the study menu has finished closing.
    """
    parent_popover.popdown()
    root = pane.view.get_root()
    if root is None or not hasattr(root, '_open_journal_on'):
        return
    book, chapter = pane.book, pane.chapter
    GLib.idle_add(lambda: root._open_journal_on(book, chapter)
                  or GLib.SOURCE_REMOVE)


def _open_sermons_on(pane, parent_popover):
    """Open the sermons page on this chapter's manuscripts.

    Same teardown dance as the journal door beside it: the window is built
    on the next idle, after the study menu has finished closing.
    """
    parent_popover.popdown()
    root = pane.view.get_root()
    if root is None or not hasattr(root, '_open_sermons_on'):
        return
    book, chapter = pane.book, pane.chapter
    GLib.idle_add(lambda: root._open_sermons_on(book, chapter)
                  or GLib.SOURCE_REMOVE)


def collected_quote(pane, verses):
    """(markdown, anchor) for the verses selected in `pane`.

    The form a collected passage takes in a manuscript: the words as a
    blockquote, then the reference — which the body's own parser turns back
    into a link, because it is spelled the way the reader's language spells
    it.

    App space for the anchor, the module's own numbering for the text: the
    pane speaks its module, and a Synodal psalter's verse 1 is app verse 0.
    """
    chapter_verses = content.load_chapter(pane.module, pane.book,
                                          pane.chapter)
    verse_map = {v: html for v, html in chapter_verses}
    words = ' '.join(
        re.sub(r'<[^>]+>', '', str(verse_map.get(v, ''))).strip()
        for v in verses).strip()
    ref = f'{book_label(pane.book)} {pane.chapter}:{verses[0]}'
    if len(verses) > 1:
        ref = f'{ref}\u2013{verses[-1]}'
    app = [annotations.app_verse(pane.module, pane.book, pane.chapter, v)
           for v in verses]
    anchor = {'book': pane.book, 'chapter': pane.chapter,
              'verses': [v for v in app if v is not None]}
    text = f'> {words} — {ref}' if words else ref
    return text, anchor


def _collect_verses(pane, verses, sermon_id, parent_popover):
    """Add the selected verses to a sermon, from the reading page."""
    parent_popover.popdown()
    text, anchor = collected_quote(pane, verses)
    root = pane.view.get_root()
    if root is None or not hasattr(root, 'collect_into_sermon'):
        return
    # The window toasts: the reader is looking at the reading page and
    # nothing visible moved, and every collecting door owes the same words.
    root.collect_into_sermon(sermon_id, text, anchor)


def _write_entry(pane, verses, parent_popover):
    """Start a journal entry on the selected verse or verses.

    Closes the study menu first and opens on the next idle, the same as the
    note editor: a window built while the parent popover is still tearing
    down races the Wayland surface lifecycle.
    """
    parent_popover.popdown()
    # App space, because that is what an anchor holds — the pane speaks its
    # module's numbering, and a Synodal psalter's verse 1 is app verse 0.
    app = [annotations.app_verse(pane.module, pane.book, pane.chapter, v)
           for v in verses]
    anchors = [{'book': pane.book, 'chapter': pane.chapter,
                'verses': [v for v in app if v is not None]}]
    root = pane.view.get_root()
    if root is None or not hasattr(root, '_open_annotations'):
        return
    GLib.idle_add(lambda: root._open_annotations({'anchors': anchors})
                  or GLib.SOURCE_REMOVE)


# ── Note editor (Adw.Window) ─────────────────────────────────────────────────

def _edit_note(pane, verse, current_note, current_tags, parent_popover):
    """Close the parent study menu, then open the note window on the next
    idle so the parent's surface teardown finishes first (avoids Wayland
    popover-inside-popover lifecycle races)."""
    parent_popover.popdown()
    GLib.idle_add(_show_note_window, pane, verse, current_note, current_tags)


def _show_note_window(pane, verse, current_note, current_tags):
    root = pane.view.get_root()
    dialog = Adw.Dialog()
    dialog.set_title(f'{book_label(pane.book)} {pane.chapter}:{verse}')
    dialog.set_content_width(420)
    dialog.set_content_height(360)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)
    header = Adw.HeaderBar()
    toolbar_view.add_top_bar(header)

    # No Save button: the note writes itself once typing pauses, and again
    # when the dialog closes. See gtk_utils.Autosave.
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(14)
    box.set_margin_end(14)
    box.set_margin_top(12)
    box.set_margin_bottom(14)
    toolbar_view.set_content(box)

    # The verse itself, above the field. A note is written about words, and
    # the editor should carry them rather than send the reader back for them.
    try:
        quoted = passage_export.verse_text(
            pane.module, pane.book, pane.chapter, [verse])
    except Exception:
        _log.exception('verse text for the note editor failed')
        quoted = ''
    if quoted:
        quote = Gtk.Label(label=quoted, xalign=0)
        quote.set_wrap(True)
        # Capped at four lines: Esther 8:9 wants 169px of this 360px dialog and
        # would squeeze the note field it sits above. The whole verse is on the
        # page behind the dialog, and one hover away here.
        quote.set_lines(4)
        quote.set_ellipsize(Pango.EllipsizeMode.END)
        quote.set_tooltip_text(quoted)
        set_accessible_label(quote, quoted)
        quote.add_css_class('journal-verse')
        box.append(quote)

    scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scrolled.set_min_content_height(160)
    # Soft inset field — a faint surface tint + rounded corners (matching the
    # reading page) instead of GNOME's hard view-frame. overflow:HIDDEN clips
    # the TextView to the rounded corners; the TextView paints transparent so
    # the tint shows through (see .note-field in style.css).
    scrolled.add_css_class('note-field')
    scrolled.set_overflow(Gtk.Overflow.HIDDEN)
    entry = Gtk.TextView()
    entry.set_editable(True)
    entry.set_cursor_visible(True)
    entry.set_wrap_mode(Gtk.WrapMode.WORD)
    entry.set_left_margin(10)
    entry.set_right_margin(10)
    entry.set_top_margin(8)
    entry.set_bottom_margin(8)
    note_buf = entry.get_buffer()
    note_buf.set_text(current_note or '')
    scrolled.set_child(entry)
    box.append(scrolled)

    tags_lbl = Gtk.Label(label=_('Topics (comma-separated)'), xalign=0)
    tags_lbl.add_css_class('dim-label')
    box.append(tags_lbl)

    tags_entry = Gtk.Entry()
    safe_tags = [str(t) for t in (current_tags or []) if t]
    tags_entry.set_text(', '.join(safe_tags))
    tags_entry.set_placeholder_text(_('e.g. Salvation, Prayer, Prophecy'))
    box.append(tags_entry)

    try:
        suggested = build_suggested_topics(pane.book, pane.chapter, verse, tags_entry)
        box.append(suggested)
    except Exception:
        _log.exception('suggested topics failed')

    # Connected after the fields are filled above: set_text() emits
    # `changed`, and connecting first would queue a write for every editor
    # merely opened.
    auto = Autosave(
        lambda: _save_note_window(pane, verse, note_buf, tags_entry))
    note_buf.connect('changed', lambda _b: auto.schedule())
    tags_entry.connect('changed', lambda _e: auto.schedule())
    dialog.connect('closed', lambda _d: auto.flush())

    dialog.present(root)
    GLib.idle_add(_grab_focus_once, entry)
    return GLib.SOURCE_REMOVE


def _save_note_window(pane, verse, note_buf, tags_entry):
    start, end = note_buf.get_bounds()
    annotations.save_note(pane.module, pane.book, pane.chapter, verse,
                           note_buf.get_text(start, end, True))
    raw = tags_entry.get_text().strip()
    tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
    annotations.save_tags(pane.module, pane.book, pane.chapter, verse, tags)
    pane._refresh_verse_annotation(verse)


# ── Suggested topics chip row (OpenBible topics) ────────────────────────────

def _chip_wheel_scroll(_ctrl, dx, dy, scroll):
    # Map whichever axis the device reports onto the row's horizontal scroll.
    adj = scroll.get_hadjustment()
    delta = dx if abs(dx) > abs(dy) else dy
    adj.set_value(adj.get_value() + delta * 60)
    return True


def build_suggested_topics(book, chapter, verse, tags_entry):
    """Chip row that fetches OpenBible topics for the verse and appends
    each one to tags_entry on click. Hidden if no topics for this verse
    or the topics file isn't downloaded. Stateless — does not need the
    pane reference, just book/chapter/verse and the target entry widget."""
    wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    wrapper.set_visible(False)

    hint = Gtk.Label(label=_('Suggested'), xalign=0)
    hint.add_css_class('dim-label')
    hint.add_css_class('caption')
    wrapper.append(hint)

    chip_scroll = Gtk.ScrolledWindow()
    # EXTERNAL (not AUTOMATIC): no scrollbar is drawn — the slim outline chips
    # no longer mask it, so it would otherwise read as a strikethrough line
    # through them (the same fix as the cross-ref bar). Wheel scroll is wired
    # explicitly since EXTERNAL won't translate a vertical wheel to horizontal.
    chip_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
    chip_scroll.set_propagate_natural_height(True)
    chip_scroll.set_min_content_height(36)
    chip_scroll.set_valign(Gtk.Align.CENTER)
    wheel = Gtk.EventControllerScroll.new(
        Gtk.EventControllerScrollFlags.BOTH_AXES)
    wheel.connect('scroll', _chip_wheel_scroll, chip_scroll)
    chip_scroll.add_controller(wheel)
    chip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    chip_scroll.set_child(chip_box)
    wrapper.append(chip_scroll)

    def append_topic(_btn, text):
        existing = [t.strip() for t in tags_entry.get_text().split(',') if t.strip()]
        if text not in existing:
            existing.append(text)
        tags_entry.set_text(', '.join(existing))

    def fetch():
        topics = open_data.get_topics(book, chapter, verse) if verse else []

        def apply():
            # Bail if the editor was closed before the fetch returned — appending
            # to a finalized widget would emit GTK-CRITICALs (cf. the compare
            # popover's get_parent() guard).
            if chip_box.get_root() is None:
                return False
            if not topics:
                return False
            for topic in topics:
                btn = Gtk.Button(label=topic)
                # Slim outline chip — same family as the cross-ref bar's chips,
                # so the suggestions read lighter than the field they feed.
                btn.add_css_class('xref-chip')
                btn.connect('clicked', append_topic, topic)
                chip_box.append(btn)
            wrapper.set_visible(True)
            return False
        GLib.idle_add(apply)

    threading.Thread(target=fetch, daemon=True).start()
    return wrapper


# ── Chapter note popover ────────────────────────────────────────────────────

def show_chapter_note(pane):
    """Modal editor for the chapter's overall note and its topical tags.

    An Adw.Dialog (not a popover): a TextView inside an autohide popover
    doesn't reliably receive keyboard input on Wayland, so this mirrors the
    verse note editor's dialog pattern."""
    data = annotations.get_chapter_note_data(pane.module, pane.book, pane.chapter)
    note = data['note'] if data else ''
    tags = data['tags'] if data else []

    root = pane.view.get_root()
    dialog = Adw.Dialog()
    dialog.set_title(_('{ref} — Chapter Note').format(
        ref=f'{book_label(pane.book)} {pane.chapter}'))
    dialog.set_content_width(420)
    dialog.set_content_height(360)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)
    header = Adw.HeaderBar()
    toolbar_view.add_top_bar(header)

    # No Save button — see the verse note editor above.
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(14)
    box.set_margin_end(14)
    box.set_margin_top(12)
    box.set_margin_bottom(14)
    toolbar_view.set_content(box)

    scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scrolled.set_min_content_height(160)
    scrolled.add_css_class('note-field')
    scrolled.set_overflow(Gtk.Overflow.HIDDEN)
    tv = Gtk.TextView()
    tv.set_editable(True)
    tv.set_cursor_visible(True)
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.set_left_margin(10)
    tv.set_right_margin(10)
    tv.set_top_margin(8)
    tv.set_bottom_margin(8)
    buf = tv.get_buffer()
    buf.set_text(note)
    scrolled.set_child(tv)
    box.append(scrolled)

    tags_lbl = Gtk.Label(label=_('Topics (comma-separated)'), xalign=0)
    tags_lbl.add_css_class('dim-label')
    box.append(tags_lbl)

    tags_entry = Gtk.Entry()
    safe_tags = [str(t) for t in (tags or []) if t]
    tags_entry.set_text(', '.join(safe_tags))
    tags_entry.set_placeholder_text(_('e.g. Creation, Covenant'))
    box.append(tags_entry)

    auto = Autosave(lambda: _save_chapter_note(pane, buf, tags_entry))
    buf.connect('changed', lambda _b: auto.schedule())
    tags_entry.connect('changed', lambda _e: auto.schedule())
    dialog.connect('closed', lambda _d: auto.flush())

    dialog.present(root)
    GLib.idle_add(_grab_focus_once, tv)


def _save_chapter_note(pane, buf, tags_entry):
    start, end = buf.get_bounds()
    annotations.save_chapter_note(
        pane.module, pane.book, pane.chapter,
        buf.get_text(start, end, True))
    raw = tags_entry.get_text().strip()
    tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
    annotations.save_chapter_note_tags(
        pane.module, pane.book, pane.chapter, tags)
    pane._update_chapter_note_indicator()
