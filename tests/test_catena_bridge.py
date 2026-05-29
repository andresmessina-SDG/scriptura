"""Tests for catena_bridge.py — verse lookup with range containment,
chronological ordering, install/remove state, and pack metadata. A tmp
SQLite file with the real pack schema is seeded per test; catena_db_path
is redirected to it and the thread-local connection is reset."""

import sqlite3

import pytest

import catena_bridge


def _enc(ch, v):
    return ch * 1_000_000 + v


def _seed(path, rows, meta=None):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE quotes (
            book TEXT, loc_start INTEGER, loc_end INTEGER, author TEXT,
            author_suffix TEXT, year INTEGER, era TEXT, source_title TEXT,
            source_url TEXT, wiki_url TEXT, text TEXT);
        CREATE TABLE pack_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.executemany('INSERT INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
    if meta:
        conn.executemany('INSERT INTO pack_meta VALUES (?,?)', list(meta.items()))
    conn.commit()
    conn.close()


def _q(book, ch, v, author, year, era, *, end=None, text='t'):
    e = _enc(ch, v)
    return (book, e, end if end is not None else e, author, None, year, era,
            None, None, None, text)


@pytest.fixture
def pack(tmp_path, monkeypatch):
    db = tmp_path / 'catena.db'
    monkeypatch.setattr(catena_bridge.paths, 'catena_db_path', lambda: str(db))
    catena_bridge._reset()  # drop any connection cached by a prior test
    return db


def test_not_installed_without_file(pack):
    assert catena_bridge.is_installed() is False
    assert catena_bridge.module_names() == []
    assert catena_bridge.lookup('John', 3, 16) == []
    assert catena_bridge.pack_info() == {}


def test_lookup_single_verse(pack):
    _seed(str(pack), [_q('John', 3, 16, 'Augustine of Hippo', 430,
                         'Nicene & Post-Nicene', text='For God so loved')])
    res = catena_bridge.lookup('John', 3, 16)
    assert len(res) == 1
    assert res[0]['author'] == 'Augustine of Hippo'
    assert res[0]['era'] == 'Nicene & Post-Nicene'
    assert res[0]['text'] == 'For God so loved'


def test_lookup_range_containment(pack):
    # A pericope entry spanning John 7:53-8:11.
    _seed(str(pack), [_q('John', 7, 53, 'Jerome', 420, 'Nicene & Post-Nicene',
                         end=_enc(8, 11))])
    assert len(catena_bridge.lookup('John', 8, 3)) == 1   # inside the span
    assert catena_bridge.lookup('John', 8, 12) == []      # just past it
    assert catena_bridge.lookup('John', 7, 52) == []      # just before it


def test_lookup_orders_oldest_first_unknown_last(pack):
    _seed(str(pack), [
        _q('John', 3, 16, 'Later', 1500, 'Reformation'),
        _q('John', 3, 16, 'NoDate', 9999, 'Unknown'),
        _q('John', 3, 16, 'Earliest', 220, 'Ante-Nicene'),
        _q('John', 3, 16, 'NullDate', None, 'Unknown'),
    ])
    res = [r['author'] for r in catena_bridge.lookup('John', 3, 16)]
    # Known dates ascending first; the two unknown-date entries last (their
    # order relative to each other doesn't matter).
    assert res[:2] == ['Earliest', 'Later']
    assert set(res[2:]) == {'NoDate', 'NullDate'}


def test_lookup_scoped_to_book(pack):
    _seed(str(pack), [
        _q('John', 3, 16, 'A', 200, 'Ante-Nicene'),
        _q('Romans', 3, 16, 'B', 200, 'Ante-Nicene'),
    ])
    assert [r['author'] for r in catena_bridge.lookup('John', 3, 16)] == ['A']


def test_module_names_and_predicate(pack):
    _seed(str(pack), [_q('John', 1, 1, 'A', 100, 'Ante-Nicene')])
    assert catena_bridge.module_names() == [catena_bridge.MODULE_KEY]
    assert catena_bridge.is_catena_module(catena_bridge.MODULE_KEY)
    assert not catena_bridge.is_catena_module('KJV')


def test_pack_info(pack):
    _seed(str(pack), [_q('John', 1, 1, 'A', 100, 'Ante-Nicene')],
          meta={'schema': '1', 'quote_count': '1', 'built': '2026-05-29'})
    info = catena_bridge.pack_info()
    assert info['schema'] == '1'
    assert info['quote_count'] == '1'


def test_remove_pack(pack):
    _seed(str(pack), [_q('John', 1, 1, 'A', 100, 'Ante-Nicene')])
    assert catena_bridge.is_installed()
    catena_bridge.remove_pack()
    assert not catena_bridge.is_installed()
    assert not pack.exists()
