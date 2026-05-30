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
from gi.repository import Gtk, Adw, GLib, Gdk

import annotations
import sword_bridge
import ebible_bridge
import open_data

_log = logging.getLogger('scriptura.notes')


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

def show_study_menu(pane, verses, x, y):
    """Right-click annotation menu — highlight colors, underline, note,
    copy, compare translations. Single-verse-only actions (note, compare)
    are omitted when multiple verses are selected."""
    popover = Gtk.Popover()
    popover.set_parent(pane._view)
    popover.connect('closed', lambda p: p.unparent())
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    popover.set_pointing_to(rect)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_margin_start(6)
    box.set_margin_end(6)
    box.set_margin_top(6)
    box.set_margin_bottom(6)

    title = (f'Verse {verses[0]}'
             if len(verses) == 1
             else f'Verses {verses[0]}–{verses[-1]}')
    lbl = Gtk.Label(label=title)
    lbl.add_css_class('dim-label')
    box.append(lbl)

    # 1. Highlight color picker
    color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    color_box.set_halign(Gtk.Align.CENTER)
    for color, css_cls in [('#ffff00', 'hl-yellow'), ('#90ee90', 'hl-green'),
                            ('#add8e6', 'hl-blue'),  ('#ffa500', 'hl-orange')]:
        btn = Gtk.Button()
        btn.set_size_request(28, 28)
        btn.add_css_class(css_cls)
        btn.connect('clicked',
                    lambda b, c=color: apply_highlight(pane, verses, c, popover))
        color_box.append(btn)
    clear_btn = Gtk.Button(label='Clear Highlight')
    clear_btn.connect('clicked', lambda b: apply_highlight(pane, verses, None, popover))
    box.append(color_box)
    box.append(clear_btn)
    box.append(Gtk.Separator())

    # 2. Underline toggle
    annos = annotations.get_annotations(pane._module, pane._book, pane._chapter)
    all_underlined = all(
        (a if isinstance(a, dict) else {'underline': False}).get('underline', False)
        for a in (annos.get(str(v), {}) for v in verses)
    )
    und_lbl = 'Remove Underline' if all_underlined else 'Underline'
    und_btn = Gtk.Button(label=und_lbl)
    und_btn.connect('clicked',
                    lambda b: toggle_underline(pane, verses, not all_underlined, popover))
    box.append(und_btn)

    # 3. Note & Tags (single verse only)
    if len(verses) == 1:
        anno = annos.get(str(verses[0]), {})
        if isinstance(anno, str):
            anno = {'highlight': anno, 'underline': False, 'note': None}
        note_text = anno.get('note', '')
        current_tags = anno.get('tags', [])
        has_study = bool(note_text or current_tags)
        note_btn = Gtk.Button(label='Edit Note & Tags' if has_study else 'Note & Tags')
        note_btn.connect('clicked',
                         lambda b: _edit_note(pane, verses[0], note_text, current_tags, popover))
        box.append(note_btn)

    box.append(Gtk.Separator())

    # 4. Copy verse(s)
    copy_lbl = 'Copy verses' if len(verses) > 1 else 'Copy verse'
    copy_btn = Gtk.Button(label=copy_lbl)
    copy_btn.add_css_class('flat')
    copy_btn.connect('clicked', lambda b: copy_verse(pane, verses, popover))
    box.append(copy_btn)

    # 5. Compare translations (single verse only)
    if len(verses) == 1:
        comp_btn = Gtk.Button(label='Compare translations')
        comp_btn.add_css_class('flat')
        comp_btn.connect('clicked', lambda b: compare_translations(pane, verses[0], popover))
        box.append(comp_btn)

    popover.set_child(box)
    popover.popup()


# ── Annotation save handlers — in-place tag refresh, no re-render ───────────

def apply_highlight(pane, verses, color, popover):
    for v in verses:
        annotations.save_highlight(pane._module, pane._book, pane._chapter, v, color)
    popover.popdown()
    for v in verses:
        pane._refresh_verse_annotation(v)


def toggle_underline(pane, verses, enabled, popover):
    for v in verses:
        annotations.save_underline(pane._module, pane._book, pane._chapter, v, enabled)
    popover.popdown()
    for v in verses:
        pane._refresh_verse_annotation(v)


# ── Copy verse to clipboard ──────────────────────────────────────────────────

def copy_verse(pane, verses, popover):
    popover.popdown()
    chapter_verses = sword_bridge.load_chapter(pane._module, pane._book, pane._chapter)
    verse_map = {v: html for v, html in chapter_verses}
    lines = []
    for v in verses:
        plain = re.sub(r'<[^>]+>', '', str(verse_map.get(v, ''))).strip()
        lines.append(f'{pane._book} {pane._chapter}:{v}  {plain}')
    ref = (f'{pane._book} {pane._chapter}:{verses[0]}–{verses[-1]}'
           if len(verses) > 1 else f'{pane._book} {pane._chapter}:{verses[0]}')
    text = f'{ref} ({pane._module})\n' + '\n'.join(lines)
    pane._view.get_clipboard().set(text)
    if pane._on_toast:
        pane._on_toast(f'Copied {ref}')


# ── Compare translations popover ─────────────────────────────────────────────

def compare_translations(pane, verse, popover):
    # Reuse the study menu's anchor (the click point) so the compare popover
    # opens where the user clicked, like the menu it replaces — both are
    # parented to pane._view, so the rect is in the same coordinate space.
    ok, src_rect = popover.get_pointing_to()
    popover.popdown()

    comp = Gtk.Popover()
    comp.set_parent(pane._view)
    comp.connect('closed', lambda p: p.unparent())
    if ok:
        comp.set_pointing_to(src_rect)
    else:
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = 160, 80, 1, 1
        comp.set_pointing_to(rect)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

    title = Gtk.Label(
        label=f'{pane._book} {pane._chapter}:{verse} — Translations',
        xalign=0)
    title.add_css_class('heading')
    title.set_margin_start(12)
    title.set_margin_end(12)
    title.set_margin_top(8)
    title.set_margin_bottom(6)
    outer.append(title)
    outer.append(Gtk.Separator())

    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_width(420)
    scroll.set_min_content_height(200)
    scroll.set_max_content_height(420)
    scroll.set_propagate_natural_height(True)

    # Local — two compare popovers in flight don't clobber each other.
    comp_list = Gtk.ListBox()
    comp_list.set_selection_mode(Gtk.SelectionMode.NONE)
    comp_list.add_css_class('boxed-list')
    comp_list.set_margin_start(8)
    comp_list.set_margin_end(8)
    comp_list.set_margin_top(8)
    comp_list.set_margin_bottom(8)

    spinner = Gtk.Spinner()
    spinner.start()
    spinner.set_margin_top(12)
    spinner.set_margin_bottom(12)
    comp_list.append(spinner)

    scroll.set_child(comp_list)
    outer.append(scroll)
    comp.set_child(outer)
    comp.popup()

    book, chapter = pane._book, pane._chapter

    def fetch():
        names = [m for m in sword_bridge.module_names()
                 if not sword_bridge.is_internal_use(m)
                 and sword_bridge.module_type(m) == 'Biblical Texts']
        names += ebible_bridge.module_names()
        results = []
        for mod in names:
            if ebible_bridge.is_ebible_module(mod):
                vs = ebible_bridge.load_chapter(mod, book, chapter)
            else:
                vs = sword_bridge.load_chapter(mod, book, chapter)
            v_html = next((h for vn, h in vs if vn == verse), '')
            plain = re.sub(r'<[^>]+>', '', str(v_html)).strip()
            if plain:
                results.append((mod, plain))
        GLib.idle_add(populate, results)

    def populate(results):
        if comp.get_parent() is None:
            return GLib.SOURCE_REMOVE
        child = comp_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            comp_list.remove(child)
            child = nxt
        for mod, text in results:
            row = Gtk.ListBoxRow()
            rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            rb.set_margin_start(12)
            rb.set_margin_end(12)
            rb.set_margin_top(8)
            rb.set_margin_bottom(8)
            ml = Gtk.Label(label=sword_bridge.display_name(mod), xalign=0)
            ml.add_css_class('dim-label')
            tl = Gtk.Label(label=text, xalign=0, wrap=True)
            tl.set_max_width_chars(52)
            rb.append(ml)
            rb.append(tl)
            row.set_child(rb)
            comp_list.append(row)
        return GLib.SOURCE_REMOVE

    threading.Thread(target=fetch, daemon=True).start()


# ── Note editor (Adw.Window) ─────────────────────────────────────────────────

def _edit_note(pane, verse, current_note, current_tags, parent_popover):
    """Close the parent study menu, then open the note window on the next
    idle so the parent's surface teardown finishes first (avoids Wayland
    popover-inside-popover lifecycle races)."""
    parent_popover.popdown()
    GLib.idle_add(_show_note_window, pane, verse, current_note, current_tags)


def _show_note_window(pane, verse, current_note, current_tags):
    root = pane._view.get_root()
    dialog = Adw.Dialog()
    dialog.set_title(f'{pane._book} {pane._chapter}:{verse}')
    dialog.set_content_width(420)
    dialog.set_content_height(360)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)
    header = Adw.HeaderBar()
    toolbar_view.add_top_bar(header)

    save_btn = Gtk.Button(label='Save')
    save_btn.add_css_class('suggested-action')
    header.pack_end(save_btn)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(14)
    box.set_margin_end(14)
    box.set_margin_top(12)
    box.set_margin_bottom(14)
    toolbar_view.set_content(box)

    scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scrolled.set_min_content_height(160)
    entry = Gtk.TextView()
    entry.set_editable(True)
    entry.set_cursor_visible(True)
    entry.set_wrap_mode(Gtk.WrapMode.WORD)
    entry.set_left_margin(8)
    entry.set_right_margin(8)
    entry.set_top_margin(6)
    entry.set_bottom_margin(6)
    note_buf = entry.get_buffer()
    note_buf.set_text(current_note or '')
    scrolled.set_child(entry)
    # Frame gives the GNOME standard "view" background — distinct from the
    # surrounding window so the input area reads as an editable field.
    frame = Gtk.Frame()
    frame.set_child(scrolled)
    box.append(frame)

    tags_lbl = Gtk.Label(label='Topics (comma-separated)', xalign=0)
    tags_lbl.add_css_class('dim-label')
    box.append(tags_lbl)

    tags_entry = Gtk.Entry()
    safe_tags = [str(t) for t in (current_tags or []) if t]
    tags_entry.set_text(', '.join(safe_tags))
    tags_entry.set_placeholder_text('e.g. Salvation, Prayer, Prophecy')
    box.append(tags_entry)

    try:
        suggested = build_suggested_topics(pane._book, pane._chapter, verse, tags_entry)
        box.append(suggested)
    except Exception as e:
        _log.exception('suggested topics failed')

    save_btn.connect('clicked',
                     lambda b: _save_note_window(pane, verse, note_buf, tags_entry, dialog))

    dialog.present(root)
    GLib.idle_add(_grab_focus_once, entry)
    return GLib.SOURCE_REMOVE


def _save_note_window(pane, verse, note_buf, tags_entry, dialog):
    start, end = note_buf.get_bounds()
    annotations.save_note(pane._module, pane._book, pane._chapter, verse,
                           note_buf.get_text(start, end, True))
    raw = tags_entry.get_text().strip()
    tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
    annotations.save_tags(pane._module, pane._book, pane._chapter, verse, tags)
    dialog.close()
    pane._refresh_verse_annotation(verse)


# ── Suggested topics chip row (OpenBible topics) ────────────────────────────

def build_suggested_topics(book, chapter, verse, tags_entry):
    """Chip row that fetches OpenBible topics for the verse and appends
    each one to tags_entry on click. Hidden if no topics for this verse
    or the topics file isn't downloaded. Stateless — does not need the
    pane reference, just book/chapter/verse and the target entry widget."""
    wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    wrapper.set_visible(False)

    hint = Gtk.Label(label='Suggested', xalign=0)
    hint.add_css_class('dim-label')
    hint.add_css_class('caption')
    wrapper.append(hint)

    chip_scroll = Gtk.ScrolledWindow()
    chip_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    chip_scroll.set_propagate_natural_height(True)
    chip_scroll.set_min_content_height(36)
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
            if not topics:
                return False
            for topic in topics:
                btn = Gtk.Button(label=topic)
                btn.add_css_class('pill')
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
    data = annotations.get_chapter_note_data(pane._module, pane._book, pane._chapter)
    note = data['note'] if data else ''
    tags = data['tags'] if data else []

    root = pane._view.get_root()
    dialog = Adw.Dialog()
    dialog.set_title(f'{pane._book} {pane._chapter} — Chapter Note')
    dialog.set_content_width(420)
    dialog.set_content_height(360)

    toolbar_view = Adw.ToolbarView()
    dialog.set_child(toolbar_view)
    header = Adw.HeaderBar()
    toolbar_view.add_top_bar(header)

    save_btn = Gtk.Button(label='Save')
    save_btn.add_css_class('suggested-action')
    header.pack_end(save_btn)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_start(14)
    box.set_margin_end(14)
    box.set_margin_top(12)
    box.set_margin_bottom(14)
    toolbar_view.set_content(box)

    scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scrolled.set_min_content_height(160)
    tv = Gtk.TextView()
    tv.set_editable(True)
    tv.set_cursor_visible(True)
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.set_left_margin(8)
    tv.set_right_margin(8)
    tv.set_top_margin(6)
    tv.set_bottom_margin(6)
    buf = tv.get_buffer()
    buf.set_text(note)
    scrolled.set_child(tv)
    frame = Gtk.Frame()
    frame.set_child(scrolled)
    box.append(frame)

    tags_lbl = Gtk.Label(label='Topics (comma-separated)', xalign=0)
    tags_lbl.add_css_class('dim-label')
    box.append(tags_lbl)

    tags_entry = Gtk.Entry()
    safe_tags = [str(t) for t in (tags or []) if t]
    tags_entry.set_text(', '.join(safe_tags))
    tags_entry.set_placeholder_text('e.g. Creation, Covenant')
    box.append(tags_entry)

    save_btn.connect('clicked',
                     lambda b: _save_chapter_note(pane, buf, tags_entry, dialog))

    dialog.present(root)
    GLib.idle_add(_grab_focus_once, tv)


def _save_chapter_note(pane, buf, tags_entry, dialog):
    start, end = buf.get_bounds()
    annotations.save_chapter_note(
        pane._module, pane._book, pane._chapter,
        buf.get_text(start, end, True))
    raw = tags_entry.get_text().strip()
    tags = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
    annotations.save_chapter_note_tags(
        pane._module, pane._book, pane._chapter, tags)
    dialog.close()
    pane._update_chapter_note_indicator()
