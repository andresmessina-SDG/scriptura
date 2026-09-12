"""The small Markdown subset a journal entry is set in.

§6.5 ruled out a rich-text editor and that ruling stands: a font picker and
an inline colour palette would walk straight into a designed type system.
What it asked for instead was a read-only rendering of a small subset in the
detail pane — emphasis, one heading level, lists, blockquote — "because an
entry is long enough that a quoted passage wants to look quoted".

**One deviation, and it follows from autosave.** §6.5 assumed a pane that
*displays* an entry and an editor that *edits* it, so the subset could be
rendered in the first and left literal in the second. Since there is no Save
button there is no such split: the pane IS the editor, always live. So the
subset is applied to the editable buffer in place. The markers stay visible
and editable — dimmed, so they recede — and what they enclose takes the
styling. Nothing is hidden from the person who typed it, and there is no mode
to be in the wrong one of.

This module is pure: text in, spans out, no GTK. That keeps the rules
testable without a display, and keeps the rendering honest about what it
claims to have found.
"""

from __future__ import annotations

import re
from typing import Any

#: (start, end, tag) in CHARACTER offsets — what Gtk.TextBuffer's
#: get_iter_at_offset speaks, and what Python string indices already are.
Span = tuple[int, int, str]

#: A line's whole-line role, by the marker that opens it. Order matters only
#: in that '- ' and '* ' are both bullets.
_HEADING = re.compile(r'^(#{1,3} )')
_QUOTE = re.compile(r'^(> ?)')
_BULLET = re.compile(r'^([-*] )')
#: A numbered line. Same tag as a bullet: what the styling does with either
#: is indent the line and hang its marker, and a second tag would mean a
#: second set of rules to keep in step for no visible difference.
_NUMBER = re.compile(r'^(\d{1,2}[.)] )')

#: Inline emphasis. Strong is matched first and its region removed, so the
#: inner pair of '**bold**' is never read as two italics. Neither may span a
#: line break: a stray '*' three paragraphs up must not italicise the rest of
#: the entry, which is the failure that makes live styling feel broken.
_STRONG = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*')
_EMPHASIS = re.compile(r'\*(?=\S)([^*]+?)(?<=\S)\*')


def spans(text: str) -> list[Span]:
    """Every styling span in `text`, in no particular order.

    Tags used: `md-heading`, `md-quote`, `md-bullet`, `md-strong`,
    `md-emphasis`, and `md-marker` for the syntax characters themselves.
    A caller applies them; this decides nothing about how they look.
    """
    out: list[Span] = []
    offset = 0
    for line in text.split('\n'):
        out.extend(_line_spans(line, offset))
        offset += len(line) + 1      # the '\n' the split consumed
    return out


def _line_spans(line: str, base: int) -> list[Span]:
    out: list[Span] = []
    body_at = 0
    for pattern, tag in ((_HEADING, 'md-heading'), (_QUOTE, 'md-quote'),
                         (_BULLET, 'md-bullet'), (_NUMBER, 'md-bullet')):
        m = pattern.match(line)
        if m:
            out.append((base, base + len(line), tag))
            out.append((base, base + m.end(1), 'md-marker'))
            body_at = m.end(1)
            break
    out.extend(_inline_spans(line, base, body_at))
    return out


def _inline_spans(line: str, base: int, start_at: int) -> list[Span]:
    """Emphasis inside one line, strong first.

    `start_at` skips a line's own marker so that the '*' opening a bullet is
    never also read as the start of an italic — which would have swallowed
    the rest of the line the moment someone typed a list.
    """
    out: list[Span] = []
    taken = [False] * len(line)
    for pattern, tag, marker in ((_STRONG, 'md-strong', 2),
                                 (_EMPHASIS, 'md-emphasis', 1)):
        for m in pattern.finditer(line, start_at):
            if any(taken[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                taken[i] = True
            out.append((base + m.start(1), base + m.end(1), tag))
            out.append((base + m.start(), base + m.start(1), 'md-marker'))
            out.append((base + m.end(1), base + m.end(), 'md-marker'))
    return out


# ── References in running prose ──────────────────────────────────────────────
#
# The one piece of formatting §6.5 said earns its place, "because it turns an
# entry into something you can read *from*". The app had no free-text
# reference parser: `devotional._insert_ref` renders a link from an ALREADY
# parsed OSIS ref, and `genealogy_bridge.parse_ref` matches only
# `^<English book> <ch>:<v>$` on a string a curator wrote.
#
# WHAT THIS RECOGNISES, and why it stops there. The caller supplies the names,
# built from data that already exists: every book's localized full name
# (`book_label`, i.e. window.BOOKS through gettext) and its English name and
# SBL abbreviation. So "Juan 3:16", «От Иоанна 3:16» and "John 3:16" all link,
# in any interface language.
#
# Localized ABBREVIATIONS — Spanish "Jn", Russian «Ин.» — were left undone at
# first, because no such table existed in the repo and guessing one would have
# put wrong abbreviations into two languages: a curation job, not a parsing
# one. It turned out to be a curation job somebody had already done. SWORD's
# locale files carry a `[Book Abbrevs]` table per language, and
# `sword_bridge.book_abbreviations` reads it, so the caller now hands those
# spellings in alongside the full names — 145 of them in Spanish, 294 in
# Russian, none invented here.

#: A name, a chapter, and optionally a verse. The chapter is required — a
#: bare "John said" is not a reference. `[:.]` takes both the colon and the
#: full stop some readers use. The closing lookahead forbids only a digit
#: continuing the number, or a SECOND separator-plus-digit — so "John 3."
#: ends the reference at the chapter and leaves the full stop to the
#: sentence, while the ambiguous "John 3:16.17" links nothing at all.
_REF_TAIL = r'\s*(\d{1,3})(?:\s*[:.]\s*(\d{1,3}))?(?!\d|[:.]\d)'


#: The compiled alternation, and the names it was built from. Rebuilding it
#: per call cost 0.77ms on a 3KB body — seventy times the whole Markdown pass
#: — and it is paid on every keystroke, because the body restyles live.
_PATTERN_CACHE: tuple[int, re.Pattern[str], dict[str, str]] | None = None


def _pattern(names: dict[str, str]) -> tuple[re.Pattern[str], dict[str, str]]:
    """The matcher for `names`, and a casefolded lookup to resolve hits.

    Keyed on the mapping's identity and size rather than its contents: the
    caller holds one dict per interface language and hands back the same
    object until the language changes.
    """
    global _PATTERN_CACHE
    key = (id(names), len(names))
    if _PATTERN_CACHE is not None and _PATTERN_CACHE[0] == key[0] \
            and len(_PATTERN_CACHE[2]) == key[1]:
        return _PATTERN_CACHE[1], _PATTERN_CACHE[2]
    ordered = sorted(names, key=len, reverse=True)
    pattern = re.compile(
        r'(?<![^\W\d_])(' + '|'.join(re.escape(n) for n in ordered) + r')'
        + _REF_TAIL, re.IGNORECASE)
    folded = {k.casefold(): v for k, v in names.items()}
    _PATTERN_CACHE = (id(names), pattern, folded)
    return pattern, folded


def reference_spans(text: str, names: dict[str, str]
                    ) -> list[tuple[int, int, str, int, int | None]]:
    """Find references in `text`, as (start, end, book, chapter, verse).

    `names` maps every recognisable spelling to its canonical English book —
    the key every store, VerseKey and OSIS mapping in the app speaks. Longest
    spelling wins, so "1 John 1:1" is not read as "John 1:1" with a stray 1
    in front of it, and «От Иоанна» beats nothing but is matched whole.
    """
    if not names:
        return []
    pattern, folded = _pattern(names)
    out = []
    for m in pattern.finditer(text):
        # The match is case-insensitive, so resolve through the folded map
        # rather than scanning every spelling for each hit.
        book = folded.get(m.group(1).casefold())
        if book is None:
            continue
        verse = int(m.group(3)) if m.group(3) else None
        out.append((m.start(), m.end(), book, int(m.group(2)), verse))
    return out


def numbered_marker(line: str) -> str:
    """The '1. ' a line opens with, or '' — what a caller has to remove
    before it can renumber."""
    match = _NUMBER.match(line)
    return match.group(1) if match else ''


def plain(text: str) -> str:
    """`text` with its notation taken off and its lines joined into one.

    What a list row previews. A row's label is wrapped, ellipsized and
    capped at two lines — but a cap of two counts SOFT wraps, so an entry
    with six paragraphs drew six paragraphs and the row grew to the length
    of the writing. Joining first is what makes the cap mean anything.

    The markers come off through `spans` rather than a second set of
    patterns, so the preview can never disagree with the rendering about
    what is notation.
    """
    drop = sorted((a, b) for a, b, tag in spans(text) if tag == 'md-marker')
    out, at = [], 0
    for a, b in drop:
        out.append(text[at:a])
        at = b
    out.append(text[at:])
    return ' '.join(''.join(out).split())


#: A verse range trailing a reference the matcher has already found —
#: "John 3:16-18". Deliberately NOT part of `_REF_TAIL`: a link in the body
#: needs one place to go, and widening the tail would change the shape of
#: every span every caller unpacks. An anchor is the one thing that can hold
#: a span of verses, so the range is parsed where an anchor is made.
_RANGE = re.compile(r'\s*[-\u2013\u2014]\s*(\d{1,3})\s*$')


def parse_anchor(text: str, names: dict[str, str]) -> dict[str, Any] | None:
    """A reference typed by hand, as a journal anchor — or None.

    Takes what the body links already take ("John 3", "Juan 3:16", «От
    Иоанна 3:16»), plus a trailing range. A chapter with no verse is a
    whole-chapter anchor, which the store and the list both understand.
    """
    found = reference_spans(text, names)
    if not found:
        return None
    _start, end, book, chapter, verse = found[0]
    verses = [verse] if verse else []
    tail = _RANGE.match(text[end:])
    if verse and tail:
        last = int(tail.group(1))
        if verse < last <= verse + 176:      # Psalm 119 is the longest
            verses = list(range(verse, last + 1))
    return {'book': book, 'chapter': chapter, 'verses': verses}


#: How much of a body a preview parses. A row's label is capped at two
#: lines — about 120 characters at any sane width — so 400 is already far
#: past what can be shown, and the ellipsis lands long before a marker cut
#: in half at the end could be seen. Measured on a 2.3KB entry: 0.30ms for
#: the whole body against 0.06ms for the first 400 characters, and the list
#: renders 200 rows in a slice. 59ms of parsing per page, or 11.
_PREVIEW_SCAN = 400


def preview(text: str) -> str:
    """The one-line preview a list row shows for `text`."""
    return plain(text[:_PREVIEW_SCAN])


def to_markdown(text: str) -> str:
    """The body as Markdown, for export.

    It already is: what the reader types is the source, and the styling in
    the pane is a rendering of it rather than a separate representation. This
    exists so the export path says what it means rather than passing a bare
    string around.
    """
    return text
