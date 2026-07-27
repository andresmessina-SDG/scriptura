"""The BSB reading's chapter addresses, and the table they are built from.

Nothing here reaches the network. What is worth testing is that the address of
a chapter is the address the publisher actually uses — a wrong one plays the
wrong chapter, or nothing, and neither shows on the page — and that the book
table cannot silently drift out of step with the app's own canon.
"""
import os

import bible_audio as ba
import sword_bridge


def test_book_table_matches_the_apps_canon():
    """Position in the table IS the book number in the filename, so the order
    has to be the canonical one the rest of the app uses."""
    assert [name for name, _ in ba._BOOK_FILE_NAMES] == sword_bridge._ALL_BOOKS


def test_every_book_has_a_distinct_file_name():
    abbrevs = [abbrev for _, abbrev in ba._BOOK_FILE_NAMES]
    assert len(abbrevs) == 66
    assert len(set(abbrevs)) == 66


def test_chapter_url_matches_the_publishers_names():
    """Spot-checked against the published listing, including the books whose
    codes are not the obvious abbreviation."""
    base = 'https://openbible.com/audio/souer'
    assert ba.chapter_url('Genesis', 1) == f'{base}/BSB_01_Gen_001.mp3'
    assert ba.chapter_url('Psalms', 119) == f'{base}/BSB_19_Psa_119.mp3'
    assert ba.chapter_url('Song of Solomon', 8) == f'{base}/BSB_22_Sng_008.mp3'
    assert ba.chapter_url('Mark', 16) == f'{base}/BSB_41_Mrk_016.mp3'
    assert ba.chapter_url('John', 3) == f'{base}/BSB_43_Jhn_003.mp3'
    assert ba.chapter_url('Titus', 3) == f'{base}/BSB_56_Tts_003.mp3'
    assert ba.chapter_url('Revelation', 22) == f'{base}/BSB_66_Rev_022.mp3'


def test_unknown_book_or_chapter_has_no_url():
    """None is the honest answer — the control is then not offered at all,
    rather than offered and broken."""
    assert ba.chapter_url('Tobit', 1) is None
    assert ba.chapter_url('', 1) is None
    assert ba.chapter_url('Genesis', 0) is None
    assert ba.chapter_url('Genesis', None) is None


def test_covers_only_the_translation_it_reads():
    """A reading offered beside another translation would be one wording on
    the page and another in the ear."""
    assert ba.covers_module('BSB')
    assert ba.covers_module('eBible: engbsb')
    assert not ba.covers_module('KJV')
    assert not ba.covers_module('eBible: engkjv')
    assert not ba.covers_module('')
    assert not ba.covers_module(None)


def test_cache_is_kept_apart_from_the_devotional_episodes(tmp_path,
                                                          monkeypatch):
    """Trimming chapters must never be able to delete a podcast episode."""
    monkeypatch.setattr(ba.paths, 'cache_dir', lambda: str(tmp_path))
    monkeypatch.setattr(ba.devotional_audio.paths, 'cache_dir',
                        lambda: str(tmp_path))
    url = ba.chapter_url('Genesis', 1)
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
