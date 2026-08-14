"""Each reading's chapter addresses, and the tables they are built from.

Nothing here reaches the network. What is worth testing is that the address of
a chapter is the address the publisher actually uses — a wrong one plays the
wrong chapter, or nothing, and neither shows on the page — and that the book
tables cannot silently drift out of step with the app's own canon.

The Spanish addresses below were every one of them requested against the
publisher's host when this was written; the expectations here are that
measurement written down, not a guess at a pattern.
"""
import os

import pytest

import bible_audio as ba
import sword_bridge

BSB = ba.READINGS[0]
BES = ba.READINGS[1]


@pytest.mark.parametrize('reading', ba.READINGS, ids=lambda r: r.translation)
def test_book_table_matches_the_apps_canon(reading):
    """Position in the table IS the book number in the filename, so the order
    has to be the canonical one the rest of the app uses."""
    assert [name for name, _ in reading.books] == sword_bridge._ALL_BOOKS


@pytest.mark.parametrize('reading', ba.READINGS, ids=lambda r: r.translation)
def test_every_book_has_a_distinct_file_name(reading):
    abbrevs = [abbrev for _, abbrev in reading.books]
    assert len(abbrevs) == 66
    assert len(set(abbrevs)) == 66


def test_chapter_url_matches_the_bsb_publishers_names():
    """Spot-checked against the published listing, including the books whose
    codes are not the obvious abbreviation."""
    base = 'https://openbible.com/audio/souer'
    assert ba.chapter_url(BSB, 'Genesis', 1) == f'{base}/BSB_01_Gen_001.mp3'
    assert ba.chapter_url(BSB, 'Psalms', 119) == f'{base}/BSB_19_Psa_119.mp3'
    assert ba.chapter_url(BSB, 'Song of Solomon', 8) == f'{base}/BSB_22_Sng_008.mp3'
    assert ba.chapter_url(BSB, 'Mark', 16) == f'{base}/BSB_41_Mrk_016.mp3'
    assert ba.chapter_url(BSB, 'John', 3) == f'{base}/BSB_43_Jhn_003.mp3'
    assert ba.chapter_url(BSB, 'Titus', 3) == f'{base}/BSB_56_Tts_003.mp3'
    assert ba.chapter_url(BSB, 'Revelation', 22) == f'{base}/BSB_66_Rev_022.mp3'


def test_chapter_url_matches_the_spanish_publishers_names():
    """Spanish abbreviations, and the books whose names diverge furthest from
    the English — Judges, Acts, James, Revelation."""
    base = 'https://audiotreasure.com/content/BES_AT'
    assert ba.chapter_url(BES, 'Genesis', 1) == f'{base}/01_BES_GEN_01.mp3'
    assert ba.chapter_url(BES, 'Judges', 21) == f'{base}/07_BES_JUE_21.mp3'
    assert ba.chapter_url(BES, '1 Kings', 22) == f'{base}/11_BES_1RE_22.mp3'
    assert ba.chapter_url(BES, 'Ezra', 10) == f'{base}/15_BES_ESD_10.mp3'
    assert ba.chapter_url(BES, 'Song of Solomon', 8) == f'{base}/22_BES_CAN_08.mp3'
    assert ba.chapter_url(BES, 'Acts', 28) == f'{base}/44_BES_HCH_28.mp3'
    assert ba.chapter_url(BES, '1 Thessalonians', 5) == f'{base}/52_BES_1TES_05.mp3'
    assert ba.chapter_url(BES, 'James', 5) == f'{base}/59_BES_STGO_05.mp3'
    assert ba.chapter_url(BES, 'Revelation', 22) == f'{base}/66_BES_APOC_22.mp3'


def test_spanish_psalms_take_three_digits_and_nothing_else_does():
    """The rule is the book's, not the number's: Psalm 1 is 001 while Genesis
    1 is 01. Reading it as "three digits past ninety-nine" would 404 on all
    hundred and fifty."""
    base = 'https://audiotreasure.com/content/BES_AT'
    assert ba.chapter_url(BES, 'Psalms', 1) == f'{base}/19_BES_SAL_001.mp3'
    assert ba.chapter_url(BES, 'Psalms', 99) == f'{base}/19_BES_SAL_099.mp3'
    assert ba.chapter_url(BES, 'Psalms', 150) == f'{base}/19_BES_SAL_150.mp3'
    assert ba.chapter_url(BES, 'Genesis', 1) == f'{base}/01_BES_GEN_01.mp3'
    assert ba.chapter_url(BES, 'Isaiah', 66) == f'{base}/23_BES_ISA_66.mp3'


def test_the_two_addresses_the_publishers_listing_omits():
    """Jonah is missing from the Spanish listing altogether and Esther stops
    at nine; both were probed and both are there. The addresses are pinned so
    a future edit cannot quietly drop the books back out."""
    base = 'https://audiotreasure.com/content/BES_AT'
    assert ba.chapter_url(BES, 'Jonah', 1) == f'{base}/32_BES_JON_01.mp3'
    assert ba.chapter_url(BES, 'Esther', 10) == f'{base}/17_BES_EST_10.mp3'


@pytest.mark.parametrize('reading', ba.READINGS, ids=lambda r: r.translation)
def test_unknown_book_or_chapter_has_no_url(reading):
    """None is the honest answer — the control is then not offered at all,
    rather than offered and broken."""
    assert ba.chapter_url(reading, 'Tobit', 1) is None
    assert ba.chapter_url(reading, '', 1) is None
    assert ba.chapter_url(reading, 'Genesis', 0) is None
    assert ba.chapter_url(reading, 'Genesis', None) is None
    assert ba.chapter_url(None, 'Genesis', 1) is None


def test_each_reading_covers_only_the_translation_it_reads():
    """A reading offered beside another translation would be one wording on
    the page and another in the ear."""
    assert ba.reading_for_module('BSB') is BSB
    assert ba.reading_for_module('eBible: engbsb') is BSB
    assert ba.reading_for_module('eBible: spabes') is BES
    assert ba.reading_for_module('KJV') is None
    assert ba.reading_for_module('eBible: engkjv') is None
    # Another Spanish translation is not this reading: the Reina-Valera in
    # the ear over the Español Sencillo on the page is exactly the failure
    # matching on module key exists to prevent.
    assert ba.reading_for_module('SpaRV') is None
    assert ba.reading_for_module('eBible: spavbl') is None
    assert ba.reading_for_module('') is None
    assert ba.reading_for_module(None) is None


def test_a_reading_that_requires_attribution_carries_the_credit():
    """CC BY is a condition, not a courtesy — the offer names the reader.
    The BSB's dedication asks for nothing, and so carries nothing."""
    assert BES.licence == 'CC BY 4.0'
    assert BES.credit == 'AudioBiblia.org'
    assert BSB.licence == 'CC0 1.0'
    assert not BSB.credit


def test_no_two_readings_claim_the_same_module():
    """Two readings covering one module would make the offer depend on table
    order, which is not something a reader could ever see or predict."""
    claimed = [key for reading in ba.READINGS for key in reading.modules]
    assert len(claimed) == len(set(claimed))


def test_cache_is_kept_apart_from_the_devotional_episodes(tmp_path,
                                                          monkeypatch):
    """Trimming chapters must never be able to delete a podcast episode."""
    monkeypatch.setattr(ba.paths, 'cache_dir', lambda: str(tmp_path))
    monkeypatch.setattr(ba.devotional_audio.paths, 'cache_dir',
                        lambda: str(tmp_path))
    url = ba.chapter_url(BSB, 'Genesis', 1)
    assert ba.cached_chapter(url) is None
    chapters = tmp_path / ba.CACHE_SUBDIR      # the lookup above created it
    (chapters / 'BSB_01_Gen_001.mp3').write_bytes(b'x')
    assert ba.cached_chapter(url) == str(chapters / 'BSB_01_Gen_001.mp3')
    # The same name under the devotional cache is a different file.
    assert ba.devotional_audio.cached_episode(url) is None


def test_trim_keeps_the_most_recent_chapters(tmp_path, monkeypatch):
    monkeypatch.setattr(ba.paths, 'cache_dir', lambda: str(tmp_path))
    directory = tmp_path / ba.CACHE_SUBDIR
    directory.mkdir()
    for i in range(6):
        path = directory / f'BSB_01_Gen_{i:03d}.mp3'
        path.write_bytes(b'x')
        os.utime(path, (1000 + i, 1000 + i))
    ba.trim_cache(keep=3)
    left = sorted(p.name for p in directory.iterdir())
    assert left == ['BSB_01_Gen_003.mp3', 'BSB_01_Gen_004.mp3',
                    'BSB_01_Gen_005.mp3']


def test_trim_is_quiet_when_there_is_no_cache_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(ba.paths, 'cache_dir', lambda: str(tmp_path))
    ba.trim_cache()          # must not raise


def test_no_two_readings_can_collide_in_the_cache():
    """The cache is one directory keyed by filename, shared by every reading.
    Two readings naming a chapter file identically would let a cached English
    chapter be served for the Spanish one — the wrong language in the ear,
    with the right words on the page and nothing on screen looking wrong."""
    seen = {}
    for reading in ba.READINGS:
        for book, _ in reading.books:
            for chapter in (1, 23, 119, 150):
                url = ba.chapter_url(reading, book, chapter)
                if url is None:
                    continue
                name = url.rsplit('/', 1)[-1]
                assert name not in seen or seen[name] == reading.translation, (
                    f'{name} is claimed by both {seen.get(name)} and '
                    f'{reading.translation}')
                seen[name] = reading.translation
