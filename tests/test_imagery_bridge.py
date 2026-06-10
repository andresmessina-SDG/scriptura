"""Tests for imagery_bridge.py — verse-range lookup (incl. cross-chapter),
the Art/Where split, house-tradition ordering, place joins, install/remove,
and a local .tar.gz install. A tmp pack dir with the real schema is seeded
per test; imagery_dir / imagery_db_path are redirected to it and the
thread-local connection is reset."""

import os
import sqlite3
import tarfile

import pytest

import imagery_bridge


_SCHEMA = """
    CREATE TABLE imagery (
        id INTEGER PRIMARY KEY, kind TEXT, tradition TEXT, title TEXT,
        caption TEXT, book TEXT, loc_start INTEGER, loc_end INTEGER,
        passage_label TEXT, file_path TEXT, file_size INTEGER, source TEXT,
        source_url TEXT, license TEXT, attribution TEXT, artist TEXT,
        year INTEGER, iconclass TEXT);
    CREATE TABLE places (
        place_id TEXT PRIMARY KEY, ancient_name TEXT, modern_name TEXT,
        latitude REAL, longitude REAL, confidence INTEGER, photo_path TEXT,
        photo_caption TEXT, photo_credit TEXT, photo_license TEXT,
        photo_source_url TEXT);
    CREATE TABLE place_verses (
        place_id TEXT, book TEXT, chapter INTEGER, verse INTEGER);
    CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _enc(ch, v):
    return ch * 1_000_000 + v


def _img(kind, tradition, title, book, ch_start, v_start, *,
         ch_end=None, v_end=None, file_path='images/x.jpg', source='src',
         license='PD', artist=None, year=None):
    """One imagery row (id auto)."""
    loc_start = _enc(ch_start, v_start)
    loc_end = _enc(ch_end if ch_end is not None else ch_start,
                   v_end if v_end is not None else v_start)
    return (None, kind, tradition, title, None, book, loc_start, loc_end,
            None, file_path, None, source, None, license, None, artist, year,
            None)


def _seed(db_path, imagery=(), places=(), place_verses=(), meta=None):
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    if imagery:
        conn.executemany(
            'INSERT INTO imagery VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            imagery)
    if places:
        conn.executemany(
            'INSERT INTO places (place_id, ancient_name, modern_name, latitude,'
            ' longitude, confidence, photo_path) VALUES (?,?,?,?,?,?,?)', places)
    if place_verses:
        conn.executemany('INSERT INTO place_verses VALUES (?,?,?,?)',
                          place_verses)
    if meta:
        conn.executemany('INSERT INTO pack_meta VALUES (?,?)',
                          list(meta.items()))
    conn.commit()
    conn.close()


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """Redirect the pack dir/db to a tmp location; return the db path."""
    d = tmp_path / 'imagery'
    d.mkdir()
    db = d / 'imagery.sqlite'
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_dir', lambda: str(d))
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_db_path', lambda: str(db))
    imagery_bridge._reset()
    return db


def test_not_installed_without_file(pack):
    assert imagery_bridge.is_installed() is False
    assert imagery_bridge.module_names() == []
    assert imagery_bridge.art_for('John', 3, 16) == []
    assert imagery_bridge.maps_for('John', 3, 16) == []
    assert imagery_bridge.places_for('John', 3, 16) == []
    assert imagery_bridge.pack_info() == {}


def test_art_single_verse_and_abs_path(pack):
    _seed(str(pack), imagery=[
        _img('illustration', 'engraving', 'Building of the Ark', 'Genesis',
             6, 14, file_path='images/dore_ark.jpg', artist='Doré', year=1866)])
    res = imagery_bridge.art_for('Genesis', 6, 14)
    assert len(res) == 1
    assert res[0]['title'] == 'Building of the Ark'
    assert res[0]['tradition'] == 'engraving'
    # file_path resolved to an absolute path inside the (tmp) imagery dir.
    assert res[0]['path'].endswith('images/dore_ark.jpg')
    assert os.path.isabs(res[0]['path'])


def test_art_excludes_maps(pack):
    _seed(str(pack), imagery=[
        _img('illustration', 'engraving', 'Scene', 'Acts', 13, 13),
        _img('map', 'cartography', 'First Journey', 'Acts', 13, 1,
             ch_end=14, v_end=28)])
    assert [i['title'] for i in imagery_bridge.art_for('Acts', 13, 13)] == ['Scene']
    assert [m['title'] for m in imagery_bridge.maps_for('Acts', 13, 13)] \
        == ['First Journey']


def test_place_display_name_strips_disambiguation_suffix():
    # OpenBible's 'Antioch 2' / 'Galilee 1' suffixes are data, not display.
    assert imagery_bridge.place_display_name('Antioch 2') == 'Antioch'
    assert imagery_bridge.place_display_name('Galilee 1') == 'Galilee'
    assert imagery_bridge.place_display_name('Perga') == 'Perga'
    # Real digits that aren't a disambiguator stay (no such places today,
    # but the rule is: only a single trailing space-digit group is dropped).
    assert imagery_bridge.place_display_name('') == ''


def test_item_carries_navigation_target(pack):
    # The reader's clickable passage chip navigates to the start of the
    # item's covered range — book/chapter/verse must decode from loc_start.
    _seed(str(pack), imagery=[
        _img('map', 'cartography', 'First Journey', 'Acts', 13, 1,
             ch_end=14, v_end=28)])
    m = imagery_bridge.maps_for('Acts', 14, 5)[0]
    assert (m['book'], m['chapter'], m['verse']) == ('Acts', 13, 1)


def test_cross_chapter_range_containment(pack):
    # The key correctness case: a map spanning Acts 13:1–14:28 must match a
    # verse *late in chapter 13* (13:40), which naive verse_start/verse_end
    # columns would wrongly exclude.
    _seed(str(pack), imagery=[
        _img('map', 'cartography', 'First Journey', 'Acts', 13, 1,
             ch_end=14, v_end=28)])
    assert len(imagery_bridge.maps_for('Acts', 13, 40)) == 1   # inside, ch 13
    assert len(imagery_bridge.maps_for('Acts', 14, 5)) == 1    # inside, ch 14
    assert imagery_bridge.maps_for('Acts', 12, 25) == []       # just before
    assert imagery_bridge.maps_for('Acts', 14, 29) == []       # just after


def test_art_house_tradition_first(pack):
    _seed(str(pack), imagery=[
        _img('icon', 'byzantine_icon', 'Icon', 'Luke', 1, 26, year=1400),
        _img('painting', 'old_master', 'Oil', 'Luke', 1, 26, year=1450),
        _img('illustration', 'engraving', 'Engraving', 'Luke', 1, 26, year=1866),
    ])
    order = [i['tradition'] for i in imagery_bridge.art_for('Luke', 1, 26)]
    # Engraving (house style) first despite being the latest year.
    assert order == ['engraving', 'old_master', 'byzantine_icon']


def test_places_join_and_confidence_order(pack):
    _seed(
        str(pack),
        places=[
            ('perga', 'Perga', 'Perge', 0.0, 0.0, 2, 'images/perga.jpg'),
            ('antioch', 'Antioch', 'Antakya', 0.0, 0.0, 3, None),
        ],
        place_verses=[
            ('perga', 'Acts', 13, 13),
            ('antioch', 'Acts', 13, 14),
        ])
    res = imagery_bridge.places_for('Acts', 13, 13)
    assert [p['ancient_name'] for p in res] == ['Perga']
    assert res[0]['path'].endswith('images/perga.jpg')
    # A place tied to a different verse doesn't leak in.
    assert imagery_bridge.places_for('Acts', 13, 99) == []


def test_module_names_and_predicate(pack):
    _seed(str(pack), imagery=[_img('illustration', 'engraving', 'X', 'John', 1, 1)])
    assert imagery_bridge.module_names() == [imagery_bridge.MODULE_KEY]
    assert imagery_bridge.is_imagery_module(imagery_bridge.MODULE_KEY)
    assert not imagery_bridge.is_imagery_module('KJV')


def test_pack_info(pack):
    _seed(str(pack), imagery=[_img('illustration', 'engraving', 'X', 'John', 1, 1)],
          meta={'schema': '1', 'image_count': '714', 'built': '2026-06-01'})
    info = imagery_bridge.pack_info()
    assert info['image_count'] == '714'
    assert info['built'] == '2026-06-01'


def test_remove_pack(pack):
    _seed(str(pack), imagery=[_img('illustration', 'engraving', 'X', 'John', 1, 1)])
    assert imagery_bridge.is_installed()
    imagery_bridge.remove_pack()
    assert not imagery_bridge.is_installed()
    assert not pack.exists()


def test_download_and_install_from_local_targz(tmp_path, monkeypatch):
    # Build a real pack: imagery.sqlite + images/ inside a .tar.gz.
    staging = tmp_path / 'build'
    (staging / 'images').mkdir(parents=True)
    db = staging / 'imagery.sqlite'
    _seed(str(db), imagery=[
        _img('illustration', 'engraving', 'Ark', 'Genesis', 6, 14,
             file_path='images/ark.jpg')])
    (staging / 'images' / 'ark.jpg').write_bytes(b'\xff\xd8\xff')  # dummy jpeg
    archive = tmp_path / 'imagery.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(db, arcname='imagery.sqlite')
        tar.add(staging / 'images' / 'ark.jpg', arcname='images/ark.jpg')

    dest = tmp_path / 'installed'
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_dir', lambda: str(dest))
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_db_path',
                        lambda: str(dest / 'imagery.sqlite'))
    imagery_bridge._reset()
    assert not imagery_bridge.is_installed()

    prog = []
    imagery_bridge.download_and_install(
        on_progress=lambda d, t: prog.append(d), url=archive.as_uri())

    assert imagery_bridge.is_installed()
    res = imagery_bridge.art_for('Genesis', 6, 14)
    assert len(res) == 1
    assert os.path.exists(res[0]['path'])           # image extracted to disk
    assert prog and prog[-1] > 0
    assert not (dest.parent / '.imagery.tar.gz.part').exists()  # temp cleaned


def test_safe_extract_rejects_traversal(tmp_path, monkeypatch):
    # An archive trying to escape the pack dir must be refused.
    evil = tmp_path / 'evil.tar.gz'
    payload = tmp_path / 'payload'
    payload.write_text('x')
    with tarfile.open(evil, 'w:gz') as tar:
        tar.add(payload, arcname='../escape.txt')
    dest = tmp_path / 'installed'
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_dir', lambda: str(dest))
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_db_path',
                        lambda: str(dest / 'imagery.sqlite'))
    imagery_bridge._reset()
    with pytest.raises(ValueError):
        imagery_bridge.download_and_install(url=evil.as_uri())
    assert not (tmp_path / 'escape.txt').exists()


def test_resolve_parts_single(monkeypatch):
    # No `.000` part exists → single-file pack.
    sizes = {'http://x/p.tar.gz': 1234}
    monkeypatch.setattr(imagery_bridge, '_probe',
                        lambda u: sizes.get(u))
    assert imagery_bridge._resolve_parts('http://x/p.tar.gz') == [
        ('http://x/p.tar.gz', 1234)]


def test_resolve_parts_multi(monkeypatch):
    # `.000`/`.001` present, `.002` is 404 → two ordered parts, sizes summed.
    sizes = {'http://x/p.tar.gz.000': 80, 'http://x/p.tar.gz.001': 20}
    monkeypatch.setattr(imagery_bridge, '_probe',
                        lambda u: sizes.get(u))
    parts = imagery_bridge._resolve_parts('http://x/p.tar.gz')
    assert parts == [('http://x/p.tar.gz.000', 80),
                     ('http://x/p.tar.gz.001', 20)]


def test_resolve_parts_missing_raises(monkeypatch):
    # Neither parts nor a single file exist → explicit error (no silent
    # truncated install).
    monkeypatch.setattr(imagery_bridge, '_probe', lambda u: None)
    with pytest.raises(FileNotFoundError):
        imagery_bridge._resolve_parts('http://x/p.tar.gz')


def test_download_install_multipart(tmp_path, monkeypatch):
    # End-to-end: a pack split into two byte-range parts of a real tar.gz is
    # reassembled, extracted, and installed.
    import sqlite3 as _sqlite
    src = tmp_path / 'pack'
    (src / 'images').mkdir(parents=True)
    db = src / 'imagery.sqlite'
    conn = _sqlite.connect(db)
    conn.execute('CREATE TABLE imagery (id INTEGER PRIMARY KEY, kind TEXT, '
                 'tradition TEXT, title TEXT, caption TEXT, book TEXT, '
                 'loc_start INT, loc_end INT, passage_label TEXT, '
                 'file_path TEXT, file_size INT, source TEXT, source_url TEXT, '
                 'license TEXT, attribution TEXT, artist TEXT, year INT, '
                 'iconclass TEXT)')
    conn.execute("INSERT INTO imagery (kind, tradition, title, book, loc_start, "
                 "loc_end, file_path, source, license) VALUES "
                 "('illustration','engraving','t','Genesis',6000014,6000014,"
                 "'images/a.png','s','PD')")
    conn.execute('CREATE TABLE places (place_id TEXT PRIMARY KEY, '
                 'ancient_name TEXT, modern_name TEXT, latitude REAL, '
                 'longitude REAL, confidence INT, photo_path TEXT, '
                 'photo_caption TEXT, photo_credit TEXT, photo_license TEXT, '
                 'photo_source_url TEXT)')
    conn.execute('CREATE TABLE place_verses (place_id TEXT, book TEXT, '
                 'chapter INT, verse INT)')
    conn.execute('CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT)')
    conn.commit(); conn.close()
    (src / 'images' / 'a.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 4000)

    archive = tmp_path / 'imagery.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(db, 'imagery.sqlite')
        tar.add(src / 'images', 'images')
    data = archive.read_bytes()
    mid = len(data) // 2
    (tmp_path / 'imagery.tar.gz.000').write_bytes(data[:mid])
    (tmp_path / 'imagery.tar.gz.001').write_bytes(data[mid:])

    dest = tmp_path / 'installed'
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_dir', lambda: str(dest))
    monkeypatch.setattr(imagery_bridge.paths, 'imagery_db_path',
                        lambda: str(dest / 'imagery.sqlite'))
    imagery_bridge._reset()
    base = (tmp_path / 'imagery.tar.gz').as_uri()
    imagery_bridge.download_and_install(url=base)
    assert imagery_bridge.is_installed()
    assert imagery_bridge.art_for('Genesis', 6, 14)
