"""The Berean Standard Bible read aloud, one file a chapter.

The BSB's publisher commissioned three complete readings and dedicated them to
the public domain (CC0 1.0), naming the narrators on its own audio page:
audiobible.org. That is a dedication of the *recordings*, which is a separate
thing from the text's own public-domain release and is the reason this can be
offered at all — every other acclaimed English reading investigated turned out
to be either under copyright or a patchwork of dozens of volunteers.

Bob Souer's reading is the one used here. Files come from the publisher's own
host rather than from any site re-serving them, and the address of a chapter is
computed, never searched for:

    https://openbible.com/audio/souer/BSB_01_Gen_001.mp3

Book number, book, chapter — all three are in the filename. That is worth
stating plainly, because every earlier attempt at chapter audio foundered on
the same rock: matching a publisher's free-text episode titles onto a canonical
book and chapter, where a mistake plays the wrong chapter and nothing on screen
looks wrong. Here there is nothing to match. The reading offered beside a
chapter is that chapter by construction.

The set was checked against the app's own installed BSB module before any of
this was written: sixty-six books, 1189 chapters, every book's chapter count
agreeing exactly.
"""
from __future__ import annotations

import os
import re

import devotional_audio
import paths

#: Which of the three dedicated readings to offer. Souer's is the one the
#: wider web re-hosts, and the only one whose files carry the plain
#: `BSB_<nn>_<Book>_<ccc>.mp3` name with no narrator suffix.
NARRATOR = 'souer'

BASE_URL = f'https://openbible.com/audio/{NARRATOR}'

#: Where the dedication is actually stated. Nothing is in the files themselves
#: — they carry no artist or copyright frame — so anything crediting this
#: reading should point here rather than at file metadata.
LICENCE_URL = 'https://audiobible.org/'

#: Kept apart from the podcast episodes so trimming one can never delete the
#: other; those are a few megabytes a day, these are a few megabytes a chapter
#: and there are 1189 of them.
CACHE_SUBDIR = 'bible_audio'

#: How many chapters to keep. At roughly 6.5 MB a chapter this is about 260 MB
#: — the same order as the packs the app already stores, and enough that a
#: sitting's worth of reading stays offline. Without a bound, reading the Bible
#: through would leave some gigabytes behind that nobody asked for.
CACHE_KEEP = 40

#: The publisher's own filenames, in canonical order; position is the book
#: number the filename uses. These are USFM-style codes and are not always the
#: obvious abbreviation — `Sng`, `Ezk`, `Jol`, `Nam`, `Mrk`, `Jhn`, `Php`,
#: `Tts`, `Jud` — so they are recorded from the published listing rather than
#: derived from the book names. A test pins this order against the app's own
#: book list.
_BOOK_FILE_NAMES = (
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

_BY_BOOK = {name: (number, abbrev) for number, (name, abbrev)
            in enumerate(_BOOK_FILE_NAMES, start=1)}

#: The module keys this reading is a reading OF — CrossWire's SWORD key and the
#: app's eBible key for the same translation. The reading must not be offered
#: beside a different translation: it would be one wording on the page and
#: another in the ear, which is worse than silence.
_KNOWN_KEYS = {'bsb', 'ebibleengbsb'}


def covers_module(module_name: str) -> bool:
    """Whether this reading is a reading of the module on screen.

    Matched on the module KEY rather than the title shown in the header —
    matching a readable title is how the Spurgeon control came to match
    nothing at all.
    """
    return re.sub(r'[^a-z]', '', (module_name or '').lower()) in _KNOWN_KEYS


def chapter_url(book: str, chapter: int) -> str | None:
    """The publisher's URL for one chapter, or None for a book that is not in
    the reading (the Apocrypha, say)."""
    got = _BY_BOOK.get(book)
    if got is None or not isinstance(chapter, int) or chapter < 1:
        return None
    number, abbrev = got
    return f'{BASE_URL}/BSB_{number:02d}_{abbrev}_{chapter:03d}.mp3'


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
