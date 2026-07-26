"""Compose a passage into a document the reader can take away.

The app's answer to "scholars write; make the app quotable". This is the
composition layer only: it gathers what the app has already parsed for a
passage and emits Markdown or plain text. No widgets, no files, no dialogs —
which is what makes it testable against fixtures, and what lets the print
path reuse it later.

Citation follows **SBTS/Turabian**, which is what this app's readers are
marked against. For the references an exporter actually emits, SBTS and SBL
agree on the shape — abbreviated book, Arabic chapter:verse, an EN DASH for
ranges, semicolons between books — so the difference is in the details, and
these are the details, from the seminary's own short-form guide:

* the en dash between chapters and verses, never a hyphen;
* books abbreviated inside a parenthetical reference and spelled out in
  running prose, which is why `format_reference` can do either;
* commas separate verses, semicolons separate books and chapters;
* the translation is named on the FIRST quotation and thereafter only when it
  changes — the caller owns that, since only it knows what came before;
* `Ps 23` for one psalm but `Pss 23-24` for more than one.

The abbreviations themselves are the SBL Handbook §8 list, which the SBTS
Manual of Style points to. Where the seminary's own examples diverge from it
(they write `2 Chron` for SBL's `2 Chr`) the SBL form wins, by Andres's call
2026-07-26: it is the list their manual cites, and it is the one that is
complete. A book with no entry is spelled out in full rather than guessed at.

Attribution is not optional and there is no argument for it in the UI. Export
turns reading into redistribution, and a translation that leaves this app
carries its name with it wherever it goes next.
"""
from __future__ import annotations

import re

import annotations as annotations_store
import sword_bridge
from i18n import _

#: SBL Handbook §8 abbreviations, keyed by the app's own book names.
#: Sourced, not recalled — see the module docstring. Books absent here are
#: spelled out in full by `abbreviate`, which is always correct if verbose;
#: inventing a plausible-looking abbreviation would not be.
SBL_ABBREV = {
    'Genesis': 'Gen', 'Exodus': 'Exod', 'Leviticus': 'Lev',
    'Numbers': 'Num', 'Deuteronomy': 'Deut', 'Joshua': 'Josh',
    'Judges': 'Judg', 'Ruth': 'Ruth', '1 Samuel': '1 Sam',
    '2 Samuel': '2 Sam', '1 Kings': '1 Kgs', '2 Kings': '2 Kgs',
    '1 Chronicles': '1 Chr', '2 Chronicles': '2 Chr', 'Ezra': 'Ezra',
    'Nehemiah': 'Neh', 'Esther': 'Esth', 'Job': 'Job', 'Psalms': 'Ps',
    'Proverbs': 'Prov', 'Ecclesiastes': 'Eccl', 'Song of Solomon': 'Song',
    'Isaiah': 'Isa', 'Jeremiah': 'Jer', 'Lamentations': 'Lam',
    'Ezekiel': 'Ezek', 'Daniel': 'Dan', 'Hosea': 'Hos', 'Joel': 'Joel',
    'Amos': 'Amos', 'Obadiah': 'Obad', 'Jonah': 'Jonah', 'Micah': 'Mic',
    'Nahum': 'Nah', 'Habakkuk': 'Hab', 'Zephaniah': 'Zeph',
    'Haggai': 'Hag', 'Zechariah': 'Zech', 'Malachi': 'Mal',
    'Matthew': 'Matt', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
    'Acts': 'Acts', 'Romans': 'Rom', '1 Corinthians': '1 Cor',
    '2 Corinthians': '2 Cor', 'Galatians': 'Gal', 'Ephesians': 'Eph',
    'Philippians': 'Phil', 'Colossians': 'Col',
    '1 Thessalonians': '1 Thess', '2 Thessalonians': '2 Thess',
    '1 Timothy': '1 Tim', '2 Timothy': '2 Tim', 'Titus': 'Titus',
    'Philemon': 'Phlm', 'Hebrews': 'Heb', 'James': 'Jas',
    '1 Peter': '1 Pet', '2 Peter': '2 Pet', '1 John': '1 John',
    '2 John': '2 John', '3 John': '3 John', 'Jude': 'Jude',
    'Revelation': 'Rev',
}

#: U+2013. The seminary's guide names this rule first and names it twice, so
#: it is a constant rather than a literal buried in a format string.
EN_DASH = '–'


def abbreviate(book: str) -> str:
    """The book as a parenthetical reference names it."""
    return SBL_ABBREV.get(book, book)


def _runs(verses: list[int]) -> list[tuple[int, int]]:
    """Consecutive verses collapsed into (first, last) runs, so that
    16, 17, 18, 20 cites as `16-18, 20` rather than as four numbers."""
    runs: list[tuple[int, int]] = []
    for verse in sorted(set(verses)):
        if runs and verse == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], verse)
        else:
            runs.append((verse, verse))
    return runs


def format_reference(book: str, chapter: int,
                     verses: list[int] | None = None,
                     version: str | None = None,
                     prose: bool = False) -> str:
    """A citation for `book` `chapter`, optionally narrowed to `verses`.

    `prose` spells the book out, for a reference that sits in a sentence
    rather than in parentheses; the default abbreviates. `version` is
    appended bare, with no comma before it — `John 1:29 ESV` is the
    seminary's own example.

    Psalms carries its own rule: one psalm is `Ps`, more than one is `Pss`.
    A chapter reference is the psalm number here, so this reads the chapter
    span rather than the verse list.
    """
    name = book if prose else abbreviate(book)
    if book == 'Psalms' and not prose:
        name = 'Ps'          # a single chapter; `Pss` is for a span of them
    ref = f'{name} {chapter}'
    if verses:
        runs = _runs(verses)
        ref += ':' + ', '.join(
            str(a) if a == b else f'{a}{EN_DASH}{b}' for a, b in runs)
    return f'{ref} {version}' if version else ref


def format_chapter_span(book: str, first: int, last: int,
                        version: str | None = None) -> str:
    """`Pss 23-24`, `1 Cor 12-14` — a reference to whole chapters.

    Separate from `format_reference` because the plural psalm only exists
    here: it is the count of psalms that decides `Ps` against `Pss`, and a
    verse range inside one psalm never makes it plural.
    """
    name = abbreviate(book)
    if book == 'Psalms' and last > first:
        name = 'Pss'
    span = str(first) if first == last else f'{first}{EN_DASH}{last}'
    ref = f'{name} {span}'
    return f'{ref} {version}' if version else ref


def join_references(refs: list[str]) -> str:
    """Semicolons between books and chapters, per the guide's own example:
    `Dan 12:2; Matt 25:34, 46; John 5:28-29`. The commas inside a single
    reference are `format_reference`'s business."""
    return '; '.join(refs)


def _plain(html: str) -> str:
    """Verse text with the render's markup taken off.

    Tags become a space rather than nothing, because a Strong's-tagged module
    marks up individual words and joining them would run the text together.
    That space then has to be taken back off in front of punctuation: KJVA
    puts its tags between the word and the comma, so a straight strip gives
    "loved the world , that he gave" the whole way down a worksheet.
    """
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(html)))
    return re.sub(r'\s+([,.;:!?’”)])', r'\1', text).strip()


def chapter_verses(module: str, book: str, chapter: int) -> list[int]:
    """Every verse number the module renders for the chapter."""
    return [v for v, _text in sword_bridge.load_chapter(module, book, chapter)]


def pericope_verses(module: str, book: str, chapter: int,
                    verse: int) -> list[int]:
    """The sense-unit `verse` belongs to — one section heading up to the
    verse before the next one.

    Rides the headings DR4 made first-class. A module with no heading data
    (KJV, ASV and the rest carry none) has no units to speak of, so the
    honest answer is the whole chapter rather than an invented boundary.
    """
    verses = chapter_verses(module, book, chapter)
    if not verses:
        return []
    heads = sorted(sword_bridge.chapter_headings(module, book, chapter) or {})
    starts = [v for v in heads if v in verses]
    if not starts:
        return verses
    first = max((v for v in starts if v <= verse), default=verses[0])
    after = [v for v in starts if v > first]
    last = (after[0] - 1) if after else verses[-1]
    return [v for v in verses if first <= v <= last]


def attribution(module: str) -> str:
    """The line every export carries, naming the text it is quoting.

    Not a setting and not removable. A card or a worksheet outlives the app
    it left, and the translation's name is the only thing travelling with it
    that says whose words these are.
    """
    info = sword_bridge.module_info(module) or {}
    name = _short_name(info.get('description') or '')
    return (_('Text from {name} ({module}).').format(name=name, module=module)
            if name else _('Text from {module}.').format(module=module))


def _short_name(description: str) -> str:
    """The translation's name, without the cataloguing tail.

    A SWORD Description is written for a module list, not for a citation:
    KJVA's runs to "King James Version (1769) with Strongs Numbers and
    Morphology and CatchWords, including Apocrypha (without glosses)", which
    is nobody's idea of an attribution line. The name is what precedes the
    first bracket or comma, and everything after it is provenance.

    Swept across every module installed here before it shipped — GUIDANCE §4
    on heuristic taming — and it is deliberately conservative: it only ever
    cuts, so the worst case is a name that keeps a word too many.
    """
    cut = re.split(r'\s*[(,]', description.strip(), maxsplit=1)[0]
    return cut.strip() or description.strip()


def _note_lines(module: str, book: str, chapter: int,
                verses: list[int]) -> list[tuple[int, str]]:
    """The reader's own marks on these verses, as (verse, description)."""
    data = annotations_store.get_annotations(module, book, chapter) or {}
    out = []
    for verse in verses:
        entry = data.get(str(verse))
        if not isinstance(entry, dict):
            continue
        parts = []
        note = (entry.get('note') or '').strip()
        if note:
            parts.append(note)
        highlight = entry.get('highlight')
        if highlight:
            parts.append(_('highlighted {colour}').format(colour=highlight))
        tags = [t for t in (entry.get('tags') or []) if t]
        if tags:
            parts.append(_('tagged {tags}').format(tags=', '.join(tags)))
        if parts:
            out.append((verse, ' — '.join(parts)))
    return out


def build(module: str, book: str, chapter: int,
          verses: list[int] | None = None, *,
          notes: bool = True, markdown: bool = True,
          version: str | None = None) -> str:
    """The document.

    `verses` narrows to a selection or a sense-unit; None takes the chapter.
    `notes` carries the reader's own marks, which are on by default because
    a worksheet without them is something they could have got anywhere.
    The deeper layers the research doc lists — interlinear, textual variants,
    the catena voices — are not gathered here yet; they are off-by-default
    toggles, and unbuilt. See BACKLOG item 15.
    """
    rendered = sword_bridge.load_chapter(module, book, chapter)
    wanted = set(verses) if verses else None
    rows = [(v, _plain(t)) for v, t in rendered
            if wanted is None or v in wanted]
    numbers = [v for v, _t in rows]
    heading = format_reference(book, chapter, verses if wanted else None,
                               version=version or module)

    lines: list[str] = []
    if markdown:
        lines.append(f'# {heading}')
        lines.append('')
        for verse, text in rows:
            lines.append(f'> **{verse}** {text}')
        lines.append('')
    else:
        lines.append(heading)
        lines.append('')
        for verse, text in rows:
            lines.append(f'{verse} {text}')
        lines.append('')

    if notes:
        marks = _note_lines(module, book, chapter, numbers)
        if marks:
            lines.append(f'## {_("Notes")}' if markdown else _('Notes'))
            lines.append('')
            for verse, description in marks:
                ref = format_reference(book, chapter, [verse])
                lines.append(f'- **{ref}** — {description}' if markdown
                             else f'{ref} — {description}')
            lines.append('')

    lines.append('---' if markdown else '')
    lines.append(attribution(module))
    return '\n'.join(lines).rstrip() + '\n'
