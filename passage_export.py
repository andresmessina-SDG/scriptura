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
import catena_bridge
import interlinear_data
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
    import sword_bridge
    return sword_bridge.plain_text(html)


def _md(text: str, markdown: bool) -> str:
    """Text that will survive being read as Markdown.

    TAGNT glosses mark a supplied word with angle brackets — `<the>` — and a
    Markdown reader treats that as an unknown HTML tag and drops it, so the
    interlinear silently lost exactly the words it had gone to the trouble of
    marking. Escaped rather than rewritten: the brackets are the source's own
    convention and mean something.

    Only the characters that change the structure. A `*` in a reader's note
    will italicise and that is a cosmetic surprise; a swallowed word is not.
    """
    if not markdown:
        return text
    return text.replace('\\', '\\\\').replace('<', '\\<').replace('>', '\\>')


def verse_text(module: str, book: str, chapter: int,
               verses: list[int] | None = None) -> str:
    """The passage as one run of plain prose, verse numbers left out.

    What a card is set in: a card is a quotation, and a quotation carries its
    reference underneath rather than numerals through the middle of it.
    """
    wanted = set(verses) if verses else None
    return ' '.join(
        _plain(html)
        for verse, html in sword_bridge.load_chapter(module, book, chapter)
        if wanted is None or verse in wanted).strip()


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


# ── The depth layers ─────────────────────────────────────────────────────────
# Each is off by default and each degrades to nothing: a reader without the
# interlinear packs or the catena pack gets a worksheet with no gap in it,
# rather than a heading over an apology. All three read from disk, so the
# caller runs `build` off the UI thread (GUIDANCE §7) — this module stays
# synchronous, which is what keeps it testable.

#: The two editions the tradition actually argues about. A word attested in
#: one and not the other is what a textual note is for; TAGNT names both in
#: its own `editions` field, so neither is inferred.
CRITICAL_EDITION = 'NA28'
RECEIVED_EDITION = 'TR'


def _editions(raw: str) -> set[str]:
    """The edition list as a set. `TR»1` means TR carries the word in a
    different position — still TR, so the marker is dropped: this compares
    presence, and word order is a claim the data would not support here."""
    return {part.split('»')[0].strip()
            for part in str(raw).split('+') if part.strip()}


def is_variant(editions: str) -> bool:
    """Whether the critical and received texts disagree about this word."""
    eds = _editions(editions)
    return (CRITICAL_EDITION in eds) != (RECEIVED_EDITION in eds)


def interlinear_module_for(book: str) -> str | None:
    """The installed interlinear covering `book`, or None.

    Asked of the data rather than worked out from a testament boundary: a
    module answers `chapter_count` 0 for a book it does not carry, which is
    the same question without a table to keep in step.
    """
    for name in interlinear_data.module_names():
        if (interlinear_data.is_installed(name)
                and interlinear_data.chapter_count(name, book) > 0):
            return name
    return None


def interlinear_rows(book: str, chapter: int,
                     verses: list[int] | None = None
                     ) -> list[tuple[int, list]]:
    """The original-language words of each verse, in order."""
    name = interlinear_module_for(book)
    if name is None:
        return []
    wanted = set(verses) if verses else None
    grouped: dict[int, list] = {}
    for word in interlinear_data.load_chapter(name, book, chapter):
        if wanted is None or word.verse in wanted:
            grouped.setdefault(word.verse, []).append(word)
    return sorted(grouped.items())


def variant_rows(book: str, chapter: int,
                 verses: list[int] | None = None
                 ) -> list[tuple[int, list]]:
    """Only the words the editions disagree about."""
    name = interlinear_module_for(book)
    if name is None:
        return []
    wanted = set(verses) if verses else None
    grouped: dict[int, list] = {}
    for word in interlinear_data.chapter_variants(name, book, chapter):
        if wanted is not None and word.verse not in wanted:
            continue
        if is_variant(word.editions):
            grouped.setdefault(word.verse, []).append(word)
    return sorted(grouped.items())


def catena_rows(book: str, chapter: int,
                verses: list[int] | None = None
                ) -> list[tuple[int, list]]:
    """The fathers' voices on each verse."""
    if not catena_bridge.is_installed():
        return []
    out = []
    for verse in (verses or []):
        entries = catena_bridge.lookup(book, chapter, verse)
        if entries:
            out.append((verse, entries))
    return out


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
          version: str | None = None,
          interlinear: bool = False, variants: bool = False,
          catena: bool = False) -> str:
    """The document.

    `verses` narrows to a selection or a sense-unit; None takes the chapter.
    `notes` carries the reader's own marks, which are on by default because a
    worksheet without them is something they could have got anywhere. The
    three depth layers are off by default: a plain reader gets a clean sheet
    and a scholar asks for the depth.

    A layer whose data is not installed contributes nothing at all — no
    heading, no note of absence. The reader knows what they have.
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
                safe = _md(description, markdown)
                lines.append(f'- **{ref}** — {safe}' if markdown
                             else f'{ref} — {description}')
            lines.append('')

    def section(title: str, rows: list[tuple[int, list]],
                render) -> None:
        if not rows:
            return
        lines.append(f'## {title}' if markdown else title)
        lines.append('')
        for verse, items in rows:
            ref = format_reference(book, chapter, [verse])
            head = f'**{ref}**' if markdown else ref
            lines.append(f'{head} {render(items)}' if markdown
                         else f'{ref} {render(items)}')
            lines.append('')

    if interlinear:
        section(_('Interlinear'),
                interlinear_rows(book, chapter, numbers),
                lambda words: ' · '.join(
                    _md(f'{w.surface} ({w.translit}) {w.gloss}'.strip(),
                        markdown)
                    for w in words))

    if variants:
        section(_('Textual variants'),
                variant_rows(book, chapter, numbers),
                lambda words: ' · '.join(
                    _md(_('{surface} “{gloss}” — {editions}').format(
                        surface=w.surface, gloss=w.gloss,
                        editions=', '.join(sorted(_editions(w.editions)))),
                        markdown)
                    for w in words))

    if catena:
        section(_('Voices'),
                catena_rows(book, chapter, numbers),
                lambda entries: '\n\n'.join(
                    f'*{e["author"]}* — {_md(_plain(e["text"]), markdown)}'
                    if markdown
                    else f'{e["author"]} — {_plain(e["text"])}'
                    for e in entries))

    lines.append('---' if markdown else '')
    lines.append(attribution(module))
    return '\n'.join(lines).rstrip() + '\n'
