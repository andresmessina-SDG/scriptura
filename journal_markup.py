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
#: Levels four to six. One smaller heading for all three rather than three
#: more steps: the type system gains one size, and a study guide's `####`
#: sections — or our own export, which pushes an entry's `##` down to
#: `####` — stop reading as literal hashes.
_SUBHEADING = re.compile(r'^(#{4,6} )')
_QUOTE = re.compile(r'^(> ?)')
_BULLET = re.compile(r'^([-*] )')
#: A numbered line. Same tag as a bullet: what the styling does with either
#: is indent the line and hang its marker, and a second tag would mean a
#: second set of rules to keep in step for no visible difference.
_NUMBER = re.compile(r'^(\d{1,2}[.)] )')
#: A thematic break: three or more of one of `-`, `*` or `_`, alone on the
#: line. Read before the bullet, or `* * *` would be a list of stars. The
#: whole line is its marker — there are no words on it to style.
_RULE = re.compile(r'^ {0,3}([-*_])(?: *\1){2,} *$')

#: Inline emphasis. Strong is matched first and its region removed, so the
#: inner pair of '**bold**' is never read as two italics. Neither may span a
#: line break: a stray '*' three paragraphs up must not italicise the rest of
#: the entry, which is the failure that makes live styling feel broken.
_STRONG = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*')
_EMPHASIS = re.compile(r'\*(?=\S)([^*]+?)(?<=\S)\*')


def spans(text: str) -> list[Span]:
    """Every styling span in `text`, in no particular order.

    Tags used: `md-heading`, `md-subheading`, `md-rule`, `md-quote`, `md-bullet`, `md-strong`,
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
    if _RULE.match(line):
        return [(base, base + len(line), 'md-rule'),
                (base, base + len(line), 'md-marker')]
    out: list[Span] = []
    body_at = 0
    for pattern, tag in ((_HEADING, 'md-heading'),
                         (_SUBHEADING, 'md-subheading'), (_QUOTE, 'md-quote'),
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

#: The full stop an abbreviation wears in print — "Rom. 10:9", "1 Cor.
#: 15:20" — which Chicago, SBL in print and most study guides all use. Taken
#: only when a chapter AND a verse follow it: "we read John. 3 of us stayed"
#: is a sentence ending on a name, and a full stop before a bare number is
#: too weak a sign to call it a reference.
_ABBREV_STOP = r'(?:\.(?=\s*\d{1,3}\s*[:.]\s*\d))?'

#: A verse cited inside the passage already under discussion — "v. 48",
#: "vv. 45-46" — which is how a study guide cites once it has named the
#: passage. It has no book of its own, so it is resolved against the last
#: full reference before it, and links nothing when there is none.
_RELATIVE = re.compile(r'(?<![^\W\d_])vv?\.\s*(\d{1,3})(?!\d|[:.]\d)',
                       re.IGNORECASE)


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
        + _ABBREV_STOP + _REF_TAIL, re.IGNORECASE)
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
    A "v. 48" after a full reference is returned too, in text order.
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
    return _with_relative(text, out)


def _with_relative(text: str,
                   found: list[tuple[int, int, str, int, int | None]]
                   ) -> list[tuple[int, int, str, int, int | None]]:
    """`found` with every "v. 48" that follows one of its references.

    The book and chapter are the nearest full reference ABOVE, in the same
    body — never one further down, and never a guess when there is none.
    """
    if not found:
        return found
    out = list(found)
    for m in _RELATIVE.finditer(text):
        above = [f for f in found if f[1] <= m.start()]
        if above:
            _a, _b, book, chapter, _v = above[-1]
            out.append((m.start(), m.end(), book, chapter, int(m.group(1))))
    return sorted(out)


def numbered_marker(line: str) -> str:
    """The '1. ' a line opens with, or '' — what a caller has to remove
    before it can renumber."""
    match = _NUMBER.match(line)
    return match.group(1) if match else ''


def list_marker(line: str) -> str:
    """The bullet, number or quote marker `line` opens with, or ''.

    A heading is deliberately not one of them: it opens no run, and a second
    heading conjured under the first is never what pressing Enter meant.
    """
    for pattern in (_QUOTE, _BULLET, _NUMBER):
        match = pattern.match(line)
        if match:
            return match.group(1)
    return ''


def line_marker(line: str) -> str:
    """Any whole-line marker `line` opens with, heading included, or ''.

    What a new marker has to REPLACE rather than sit in front of: '- 1. one'
    is a bullet whose text reads '1. one', which is not what pressing the
    bullet on a numbered line asks for.
    """
    match = _HEADING.match(line) or _SUBHEADING.match(line)
    return match.group(1) if match else list_marker(line)


def next_marker(line: str) -> str:
    """What a new line under `line` opens with — the same bullet or quote,
    the next number, or '' when `line` opens no list."""
    match = _NUMBER.match(line)
    if match:
        return _with_number(match.group(1), int(match.group(1)[:-2]) + 1)
    return list_marker(line)


def _with_number(marker: str, n: int) -> str:
    """`marker` carrying `n` instead of its own number, its separator kept —
    ('3) ', 7) gives '7) '."""
    return f'{n}{marker[-2]} '


def renumber(lines: list[str]) -> list[str]:
    """A run of numbered lines, counting from the first one's own number.

    Continuing a list is not enough by itself: an item inserted in the middle
    leaves every number below it one short, and 1. 2. 2. 3. is a list that has
    to be retyped by hand. A run that does not start at 1 keeps its own first
    number — the reader put it there.

    Returns the lines unchanged unless every one of them is numbered: this
    renumbers, and never numbers a line that was not already.
    """
    markers = [numbered_marker(line) for line in lines]
    if not all(markers):
        return list(lines)
    base = int(markers[0][:-2])
    return [_with_number(marker, base + i) + line[len(marker):]
            for i, (line, marker) in enumerate(zip(lines, markers))]


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
    """The one-line preview a list row shows for `text`.

    Headings and rules are left out: the row already leads with the title,
    and a manuscript's first heading is usually that title again — a sermon
    row read "The Sower Four soils Read Mark 4:1-9. the path rocky ground".
    List items are set apart with ' · ', where bare spaces ran them into one
    broken sentence. A body that is nothing but headings keeps them, or the
    row would say nothing at all. `plain` itself is unchanged: the word count
    reads it.
    """
    head = text[:_PREVIEW_SCAN]
    parts: list[tuple[bool, str]] = []
    for line in head.split('\n'):
        if (_HEADING.match(line) or _SUBHEADING.match(line)
                or _RULE.match(line)):
            continue
        words = plain(line)
        if words:
            parts.append((bool(_BULLET.match(line) or _NUMBER.match(line)),
                          words))
    if not parts:
        return plain(head)
    out = parts[0][1]
    for (was_item, _w), (item, words) in zip(parts, parts[1:]):
        out += (' · ' if was_item and item else ' ') + words
    return out


def to_markdown(text: str) -> str:
    """The body as Markdown, for export.

    It already is: what the reader types is the source, and the styling in
    the pane is a rendering of it rather than a separate representation. This
    exists so the export path says what it means rather than passing a bare
    string around.
    """
    return text


# ── Pasting from a web page ─────────────────────────────────────────────────
#
# What a reader copies from a browser, a word processor or a Bible site
# arrives as HTML beside the plain text. Taking the plain text, as the view
# does by default, throws away every heading, list and emphasis the reader
# could see when they copied it. This keeps the part of it the subset can
# say, as the subset says it, and drops the rest: colours, fonts, links'
# addresses, images. What comes out is ordinary Markdown in the buffer —
# exactly what the reader could have typed.

from html.parser import HTMLParser

_SUPERSCRIPT = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')
_BLOCKS = {'p', 'div', 'section', 'article', 'header', 'footer', 'main',
           'table', 'tr', 'pre', 'figure', 'figcaption', 'dl', 'dt', 'dd'}
_SKIP = {'script', 'style', 'head', 'title', 'template', 'noscript'}


def _style_flags(style: str) -> tuple[bool | None, bool | None]:
    """(bold, italic) that an inline `style` sets, None where it is silent.

    Google Docs marks nothing with <b>; it says font-weight:700 on a span,
    and wraps the whole paste in a <b style="font-weight:normal">.
    """
    bold = italic = None
    for decl in style.lower().split(';'):
        key, _, value = decl.partition(':')
        key, value = key.strip(), value.strip()
        if key == 'font-weight':
            bold = value in ('bold', 'bolder') or (
                value.isdigit() and int(value) >= 600)
        elif key == 'font-style':
            italic = value in ('italic', 'oblique')
    return bold, italic


class _ToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.runs: list[tuple[str, bool, bool]] = []
        self.prefix = ''
        self.styles: list[tuple[str, bool | None, bool | None]] = []
        self.lists: list[list[int]] = []   # [counter] per ol, [] per ul
        self.quote = 0
        self.skip = 0
        self.sup = 0

    # Inline style is a stack, so a </span> closes only what its <span> set.
    def _flag(self, index: int) -> bool:
        for entry in reversed(self.styles):
            if entry[index] is not None:
                return bool(entry[index])
        return False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        style = dict(attrs).get('style') or ''
        bold, italic = _style_flags(style)
        if tag in ('b', 'strong') and bold is None:
            bold = True
        if tag in ('i', 'em', 'cite') and italic is None:
            italic = True
        self.styles.append((tag, bold, italic))
        if tag == 'br':
            self.styles.pop()
            self.runs.append(('\n', False, False))
        elif tag == 'sup':
            self.sup += 1
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._close_block()
            self.prefix = '#' * int(tag[1]) + ' '
        elif tag == 'blockquote':
            self._close_block()
            self.quote += 1
        elif tag in ('ul', 'ol'):
            self._close_block()
            self.lists.append([0] if tag == 'ol' else [])
        elif tag == 'li':
            self._close_block()
            if self.lists and self.lists[-1]:
                self.lists[-1][0] += 1
                self.prefix = f'{self.lists[-1][0]}. '
            else:
                self.prefix = '- '
        elif tag == 'hr':
            self.styles.pop()
            self._close_block()
            self.blocks.append('---')
        elif tag in _BLOCKS:
            self._close_block()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        for i in range(len(self.styles) - 1, -1, -1):
            if self.styles[i][0] == tag:
                del self.styles[i:]
                break
        if tag == 'sup':
            self.sup = max(0, self.sup - 1)
        elif tag == 'blockquote':
            self._close_block()
            self.quote = max(0, self.quote - 1)
        elif tag in ('ul', 'ol'):
            self._close_block()
            if self.lists:
                self.lists.pop()
        elif tag in _BLOCKS or tag == 'li' or tag in (
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._close_block()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        # HTML's own rule: any run of whitespace is one space.
        text = re.sub(r'\s+', ' ', data)
        if self.sup and text.strip().isdigit():
            text = text.strip().translate(_SUPERSCRIPT)
        if text:
            self.runs.append((text, self._flag(1), self._flag(2)))

    def _close_block(self) -> None:
        lines = _inline(self.runs).split('\n')
        self.runs = []
        # Runs meet with a space each side of an element's edge; one is
        # enough.
        body = [re.sub(r' {2,}', ' ', line).strip() for line in lines
                if line.strip()]
        if body:
            head = self.prefix + body[0]
            # A heading holds one line; a list item's later lines stay in it.
            text = '\n'.join([head] + body[1:])
            if self.quote:
                text = '\n'.join('> ' + line for line in text.split('\n'))
            self.blocks.append(text)
        self.prefix = ''

    def result(self) -> str:
        self._close_block()
        out: list[str] = []
        for i, block in enumerate(self.blocks):
            # List items and quoted lines sit together; everything else is
            # its own paragraph, a blank line apart, as the reader types it.
            if i:
                kind = _item_kind(block)
                tight = kind and kind == _item_kind(self.blocks[i - 1])
                out.append('\n' if tight else '\n\n')
            out.append(block)
        return ''.join(out).strip()


def _item_kind(block: str) -> str:
    """'list' or 'quote' for a block that sits tight against its own kind,
    '' for a paragraph."""
    if block.startswith('> '):
        return 'quote'
    return 'list' if _BULLET.match(block) or _NUMBER.match(block) else ''


def _inline(runs: list[tuple[str, bool, bool]]) -> str:
    """Runs of (text, bold, italic) as the subset writes them.

    Adjacent runs of one style are merged first, and the markers close
    against the words, never against a space — '** word **' is notation the
    subset will not read back, so the spaces step outside the pair.
    """
    merged: list[list] = []
    for text, bold, italic in runs:
        if merged and merged[-1][1:] == [bold, italic]:
            merged[-1][0] += text
        else:
            merged.append([text, bold, italic])
    out = []
    for text, bold, italic in merged:
        marker = ('**' if bold else '') + ('*' if italic else '')
        core = text.strip()
        if not marker or not core or '\n' in core:
            out.append(text)
            continue
        lead = text[:len(text) - len(text.lstrip())]
        tail = text[len(text.rstrip()):]
        out.append(f'{lead}{marker}{core}{marker[::-1]}{tail}')
    return ''.join(out)


def from_html(html: str) -> str:
    """`html` as the Markdown subset: headings, lists, quotes, rules,
    bold and italic. Everything else is kept as its text or dropped."""
    parser = _ToMarkdown()
    parser.feed(html)
    parser.close()
    return parser.result()
