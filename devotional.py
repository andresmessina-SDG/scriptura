"""Devotional rendering — OSIS-XML to Pango markup, applied to a
Gtk.TextBuffer.

Devotional modules in SWORD (Spurgeon's Morning & Evening, Daily Light,
etc.) store entries as small OSIS fragments with a <title>, one or more
<p> blocks, and embedded <reference osisRef="...">passages</reference>
links. SME-style modules pack two devotionals (morning + evening) into a
single entry; we label section boundaries so the user can see where one
ends and the next begins.

This module is intentionally state-free — every function takes the
buffer to write into as a parameter. The BiblePane keeps ownership of
the buffer and orchestrates when to call render_osis().
"""

import re
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Pango


def render_osis(buffer, raw, dark):
    """Render a devotional entry's raw OSIS into `buffer`.

    Inserts title, clickable references, italic quotes, and body
    paragraphs as Pango markup. Clickable references get a named
    `devref:OSISREF` tag — the BiblePane's left-click handler reads
    that tag and routes the click to navigation.

    `dark` chooses a darker/lighter link color appropriate for the
    current theme.
    """
    link_color = '#4a9dff' if dark else '#1a6ac4'

    title_m = re.search(r'<title[^>]*>(.*?)</title>', raw, re.DOTALL)
    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ''

    p_blocks = re.findall(r'<p\b[^>]*>(.*?)</p>', raw, re.DOTALL)

    if not p_blocks:
        # No structured paragraphs — fall back to plain stripped text.
        if title:
            buffer.insert_markup(
                buffer.get_end_iter(),
                f'<b><big>{GLib.markup_escape_text(title)}</big></b>\n\n', -1)
        plain = re.sub(r'<[^>]+>', ' ', raw).strip()
        buffer.insert(buffer.get_end_iter(), re.sub(r'\s+', ' ', plain))
        return

    if title:
        buffer.insert_markup(
            buffer.get_end_iter(),
            f'<b><big>{GLib.markup_escape_text(title)}</big></b>\n\n', -1)

    # Section detection: a <p> with both an italic quote AND a <reference>
    # marks the start of a devotional section. SME packs morning + evening
    # into one entry, so multi-section entries get labelled boundaries.
    def _is_section_header(p):
        return bool(
            re.search(r'<hi\b[^>]*type=["\']italic["\'][^>]*>', p) and
            re.search(r'<reference\b', p)
        )

    section_starts = [i for i, p in enumerate(p_blocks) if _is_section_header(p)]
    multi_section  = len(section_starts) > 1
    labels = ([_('Morning'), _('Evening')]
              if len(section_starts) == 2
              else [_('Part {n}').format(n=i + 1)
                    for i in range(len(section_starts))])

    section_idx = -1
    for i, p in enumerate(p_blocks):
        if i in section_starts:
            section_idx += 1
            if multi_section:
                if section_idx > 0:
                    buffer.insert_markup(buffer.get_end_iter(), '\n', -1)
                label = (labels[section_idx]
                         if section_idx < len(labels)
                         else _('Part {n}').format(n=section_idx + 1))
                buffer.insert_markup(
                    buffer.get_end_iter(),
                    f'<b><big>{GLib.markup_escape_text(label)}</big></b>\n', -1)
            # Italic quote on first line of section
            quote_m = re.search(
                r'<hi\b[^>]*type=["\']italic["\'][^>]*>(.*?)</hi>',
                p, re.DOTALL)
            if quote_m:
                quote = re.sub(r'<[^>]+>', '', quote_m.group(1)).strip()
                if quote:
                    buffer.insert_markup(
                        buffer.get_end_iter(),
                        f'<i>{GLib.markup_escape_text(quote)}</i>\n', -1)
            # Clickable reference (Bible:OSIS or plain OSIS)
            ref_m = re.search(
                r'<reference[^>]+osisRef="([^"]+)"[^>]*>(.*?)</reference>',
                p, re.DOTALL)
            if ref_m:
                osis_ref = ref_m.group(1)
                display  = re.sub(r'<[^>]+>', '', ref_m.group(2)).strip() or osis_ref
                clean    = osis_ref[6:] if osis_ref.startswith('Bible:') else osis_ref
                _insert_ref(buffer, display, clean, link_color)
                buffer.insert(buffer.get_end_iter(), '\n')
            buffer.insert(buffer.get_end_iter(), '\n')
        else:
            text = re.sub(r'<lb\s*/?>', '\n', p)
            text = re.sub(r'<[^>]+>', '', text).strip()
            text = re.sub(r'\s+', ' ', text)
            if text:
                buffer.insert(buffer.get_end_iter(), text + '\n\n')


def _insert_ref(buffer, display_text, osis_ref, link_color):
    """Insert a clickable reference into the buffer. Creates (or reuses)
    a named `devref:OSISREF` tag — the BiblePane's left-click handler
    routes clicks on that tag to navigation."""
    start_offset = buffer.get_char_count()
    buffer.insert(buffer.get_end_iter(), display_text)
    end_offset = buffer.get_char_count()
    tag_name = f'devref:{osis_ref}'
    tag = buffer.get_tag_table().lookup(tag_name)
    if not tag:
        tag = buffer.create_tag(
            tag_name,
            foreground=link_color,
            underline=Pango.Underline.SINGLE,
        )
    s = buffer.get_iter_at_offset(start_offset)
    e = buffer.get_iter_at_offset(end_offset)
    buffer.apply_tag(tag, s, e)
