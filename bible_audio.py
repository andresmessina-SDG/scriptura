"""The Bible read aloud, one file a chapter, in English and in Spanish.

Two readings are offered, each beside the translation it is a reading OF.

**English — the Berean Standard Bible.** The BSB's publisher commissioned three
complete readings and dedicated them to the public domain (CC0 1.0), naming the
narrators on its own audio page: audiobible.org. That is a dedication of the
*recordings*, which is a separate thing from the text's own public-domain
release and is the reason this can be offered at all — every other acclaimed
English reading investigated turned out to be either under copyright or a
patchwork of dozens of volunteers. Bob Souer's is the reading used here.

**Spanish — La Biblia en Español Sencillo.** AudioBiblia.org published the
text and a complete reading of it together in 2018 under CC BY 4.0, stating
that both may be copied and shared freely. The matching text is installable
from the eBible catalogue as `spabes`, so the wording on the page and the
wording in the ear come from one publisher. Attribution is a condition of that
licence, unlike the BSB's dedication, which is why `credit` is carried on the
record and named at the point the reading is offered.

Files come from each publisher's own host rather than from any site re-serving
them, and the address of a chapter is computed, never searched for:

    https://openbible.com/audio/souer/BSB_01_Gen_001.mp3
    https://audiotreasure.com/content/BES_AT/01_BES_GEN_01.mp3

Book number, book, chapter — all three are in both filenames. That is worth
stating plainly, because every earlier attempt at chapter audio foundered on
the same rock: matching a publisher's free-text episode titles onto a canonical
book and chapter, where a mistake plays the wrong chapter and nothing on screen
looks wrong. Here there is nothing to match. The reading offered beside a
chapter is that chapter by construction.

Neither set is trusted from a listing. The BSB's was checked against the app's
own installed module; every one of the 1189 Spanish addresses this file can
build was requested before any of it was written, and all 1189 answered. Both
of the Spanish publisher's own index gaps — Jonah, absent from the page
entirely, and Esther 10 — turned out to be omissions in the HTML, not missing
recordings.
"""
from __future__ import annotations

import os
import re
from typing import Callable, NamedTuple

import devotional_audio
import paths

#: Kept apart from the podcast episodes so trimming one can never delete the
#: other; those are a few megabytes a day, these are a few megabytes a chapter
#: and there are 1189 of them. Shared by both readings: the cache is keyed by
#: URL, and the two publishers' addresses cannot collide.
CACHE_SUBDIR = 'bible_audio'

#: How many chapters to keep. The English reading runs about 6.5 MB a chapter
#: and the Spanish about 1 MB, so this is 260 MB at worst — the same order as
#: the packs the app already stores, and enough that a sitting's worth of
#: reading stays offline. Without a bound, reading the Bible through would
#: leave some gigabytes behind that nobody asked for.
CACHE_KEEP = 40

class _Reading(NamedTuple):
    """One complete reading, and everything needed to address a chapter of it.

    `books` is in canonical order and position IS the book number the
    publisher's filenames use, so the table cannot be reordered. `filename`
    takes that number, the publisher's abbreviation and the chapter, because
    the two publishers lay their names out differently and neither is worth
    bending into the other's shape.
    """
    translation: str        # what the reading is OF; a proper name, untranslated
    base_url: str
    modules: frozenset      # normalised module keys this reading covers
    books: tuple            # ((canonical name, publisher abbreviation), ...)
    filename: Callable      # (number, abbrev, chapter) -> str
    licence: str
    licence_url: str        # where the terms are actually stated
    credit: str = ''        # named at the point of offer when the licence asks


#: The BSB publisher's own filenames, in canonical order. These are USFM-style
#: codes and are not always the obvious abbreviation — `Sng`, `Ezk`, `Jol`,
#: `Nam`, `Mrk`, `Jhn`, `Php`, `Tts`, `Jud` — so they are recorded from the
#: published listing rather than derived from the book names. A test pins this
#: order against the app's own book list.
_BSB_BOOKS = (
    ('Genesis', 'Gen'), ('Exodus', 'Exo'), ('Leviticus', 'Lev'),
    ('Numbers', 'Num'), ('Deuteronomy', 'Deu'), ('Joshua', 'Jos'),
    ('Judges', 'Jdg'), ('Ruth', 'Rut'), ('1 Samuel', '1Sa'),
    ('2 Samuel', '2Sa'), ('1 Kings', '1Ki'), ('2 Kings', '2Ki'),
    ('1 Chronicles', '1Ch'), ('2 Chronicles', '2Ch'), ('Ezra', 'Ezr'),
    ('Nehemiah', 'Neh'), ('Esther', 'Est'), ('Job', 'Job'),
    ('Psalms', 'Psa'), ('Proverbs', 'Pro'), ('Ecclesiastes', 'Ecc'),
    ('Song of Solomon', 'Sng'), ('Isaiah', 'Isa'), ('Jeremiah', 'Jer'),
    ('Lamentations', 'Lam'), ('Ezekiel', 'Ezk'), ('Daniel', 'Dan'),
    ('Hosea', 'Hos'), ('Joel', 'Jol'), ('Amos', 'Amo'),
    ('Obadiah', 'Oba'), ('Jonah', 'Jon'), ('Micah', 'Mic'),
    ('Nahum', 'Nam'), ('Habakkuk', 'Hab'), ('Zephaniah', 'Zep'),
    ('Haggai', 'Hag'), ('Zechariah', 'Zec'), ('Malachi', 'Mal'),
    ('Matthew', 'Mat'), ('Mark', 'Mrk'), ('Luke', 'Luk'),
    ('John', 'Jhn'), ('Acts', 'Act'), ('Romans', 'Rom'),
    ('1 Corinthians', '1Co'), ('2 Corinthians', '2Co'), ('Galatians', 'Gal'),
    ('Ephesians', 'Eph'), ('Philippians', 'Php'), ('Colossians', 'Col'),
    ('1 Thessalonians', '1Th'), ('2 Thessalonians', '2Th'),
    ('1 Timothy', '1Ti'), ('2 Timothy', '2Ti'), ('Titus', 'Tts'),
    ('Philemon', 'Phm'), ('Hebrews', 'Heb'), ('James', 'Jas'),
    ('1 Peter', '1Pe'), ('2 Peter', '2Pe'), ('1 John', '1Jn'),
    ('2 John', '2Jn'), ('3 John', '3Jn'), ('Jude', 'Jud'),
    ('Revelation', 'Rev'),
)

#: The Spanish publisher's abbreviations, same canonical order. Spanish book
#: names, so almost none of them match the BSB table: `JUE`, `1RE`, `ESD`,
#: `SAL`, `CAN`, `MIQ`, `SOF`, `HCH`, `STGO`, `APOC`. Recorded from the
#: published listing and then confirmed one request at a time — Jonah's `JON`
#: is not in that listing at all and was found by probe.
_BES_BOOKS = (
    ('Genesis', 'GEN'), ('Exodus', 'EXO'), ('Leviticus', 'LEV'),
    ('Numbers', 'NUM'), ('Deuteronomy', 'DEU'), ('Joshua', 'JOS'),
    ('Judges', 'JUE'), ('Ruth', 'RUT'), ('1 Samuel', '1SA'),
    ('2 Samuel', '2SA'), ('1 Kings', '1RE'), ('2 Kings', '2RE'),
    ('1 Chronicles', '1CR'), ('2 Chronicles', '2CR'), ('Ezra', 'ESD'),
    ('Nehemiah', 'NEH'), ('Esther', 'EST'), ('Job', 'JOB'),
    ('Psalms', 'SAL'), ('Proverbs', 'PRO'), ('Ecclesiastes', 'ECL'),
    ('Song of Solomon', 'CAN'), ('Isaiah', 'ISA'), ('Jeremiah', 'JER'),
    ('Lamentations', 'LAM'), ('Ezekiel', 'EZE'), ('Daniel', 'DAN'),
    ('Hosea', 'OSE'), ('Joel', 'JOL'), ('Amos', 'AMO'),
    ('Obadiah', 'ABD'), ('Jonah', 'JON'), ('Micah', 'MIQ'),
    ('Nahum', 'NAH'), ('Habakkuk', 'HAB'), ('Zephaniah', 'SOF'),
    ('Haggai', 'HAG'), ('Zechariah', 'ZAC'), ('Malachi', 'MAL'),
    ('Matthew', 'MAT'), ('Mark', 'MAR'), ('Luke', 'LUC'),
    ('John', 'JUA'), ('Acts', 'HCH'), ('Romans', 'ROM'),
    ('1 Corinthians', '1CO'), ('2 Corinthians', '2CO'), ('Galatians', 'GAL'),
    ('Ephesians', 'EFE'), ('Philippians', 'FLP'), ('Colossians', 'COL'),
    ('1 Thessalonians', '1TES'), ('2 Thessalonians', '2TES'),
    ('1 Timothy', '1TI'), ('2 Timothy', '2TI'), ('Titus', 'TIT'),
    ('Philemon', 'FLM'), ('Hebrews', 'HEB'), ('James', 'STGO'),
    ('1 Peter', '1PE'), ('2 Peter', '2PE'), ('1 John', '1JN'),
    ('2 John', '2JN'), ('3 John', '3JN'), ('Jude', 'JUD'),
    ('Revelation', 'APOC'),
)


def _bsb_filename(number: int, abbrev: str, chapter: int) -> str:
    return f'BSB_{number:02d}_{abbrev}_{chapter:03d}.mp3'


def _bes_filename(number: int, abbrev: str, chapter: int) -> str:
    """Two digits of chapter everywhere except the Psalms, which take three.

    Not a "three digits past ninety-nine" rule, which is what it looks like
    from a glance at the listing and what would 404 on all hundred and fifty:
    Psalm 1 is `SAL_001` while Genesis 1 is `GEN_01`. The width belongs to the
    book, not to the number.
    """
    width = 3 if number == 19 else 2
    return f'{number:02d}_BES_{abbrev}_{chapter:0{width}d}.mp3'


#: Every reading on offer. `modules` is the set a reading may be offered
#: beside — CrossWire's SWORD key and the app's eBible key for the same
#: translation. A reading must not be offered beside a different translation:
#: it would be one wording on the page and another in the ear, which is worse
#: than silence.
READINGS = (
    _Reading(
        translation='Berean Standard Bible',
        # Souer's is the reading the wider web re-hosts, and the only one of
        # the three whose files carry the plain name with no narrator suffix.
        base_url='https://openbible.com/audio/souer',
        modules=frozenset({'bsb', 'ebibleengbsb'}),
        books=_BSB_BOOKS,
        filename=_bsb_filename,
        licence='CC0 1.0',
        # Nothing is in the files themselves — they carry no artist or
        # copyright frame — so anything crediting this reading points here
        # rather than at file metadata.
        licence_url='https://audiobible.org/',
    ),
    _Reading(
        translation='La Biblia en Español Sencillo',
        base_url='https://audiotreasure.com/content/BES_AT',
        # One eBible key: the text ships as `spabes`. The publisher's SWORD
        # build of the same text lives in a repository the app does not read.
        modules=frozenset({'ebiblespabes'}),
        books=_BES_BOOKS,
        filename=_bes_filename,
        licence='CC BY 4.0',
        licence_url='https://audiotreasure.com/AT_BES.htm',
        credit='AudioBiblia.org',
    ),
)


#: Book name -> (book number, abbreviation), per reading. Built once: the
#: lookup runs on every navigation, and position in `books` is the book
#: number, so this is the only place that correspondence is spelled out.
_NUMBERED = {
    reading.translation: {name: (number, abbrev) for number, (name, abbrev)
                          in enumerate(reading.books, start=1)}
    for reading in READINGS
}


def _key(module_name: str) -> str:
    """A module name reduced to the letters in it.

    Matched on the module KEY rather than the title shown in the header —
    matching a readable title is how the Spurgeon control came to match
    nothing at all.
    """
    return re.sub(r'[^a-z]', '', (module_name or '').lower())


def reading_for_module(module_name: str) -> _Reading | None:
    """The reading that is a reading of the module on screen, if any."""
    key = _key(module_name)
    for reading in READINGS:
        if key in reading.modules:
            return reading
    return None


def chapter_url(reading: _Reading, book: str, chapter: int) -> str | None:
    """The publisher's URL for one chapter, or None for a book that is not in
    the reading (the Apocrypha, say)."""
    if reading is None:
        return None
    got = _NUMBERED[reading.translation].get(book)
    if got is None or not isinstance(chapter, int) or chapter < 1:
        return None
    number, abbrev = got
    return f'{reading.base_url}/{reading.filename(number, abbrev, chapter)}'


def cached_chapter(url: str) -> str | None:
    """The local copy of a chapter, if it has already been fetched."""
    return devotional_audio.cached_episode(url, sub=CACHE_SUBDIR)


def fetch_chapter(url: str) -> str | None:
    """Download a chapter and return its local path (or None).

    Blocking — call from a task worker.
    """
    path = devotional_audio.fetch_episode(url, sub=CACHE_SUBDIR)
    if path:
        trim_cache()
    return path


def trim_cache(keep: int = CACHE_KEEP) -> None:
    """Drop the least recently fetched chapters beyond `keep`.

    Best effort: a file that cannot be removed is left alone rather than
    reported, because failing to tidy a cache is not something to interrupt a
    reader over.
    """
    directory = os.path.join(paths.cache_dir(), CACHE_SUBDIR)
    try:
        entries = [os.path.join(directory, n) for n in os.listdir(directory)
                   if n.endswith('.mp3')]
    except OSError:
        return
    if len(entries) <= keep:
        return
    try:
        entries.sort(key=os.path.getmtime)
    except OSError:
        return
    for path in entries[:len(entries) - keep]:
        try:
            os.unlink(path)
        except OSError:
            pass
