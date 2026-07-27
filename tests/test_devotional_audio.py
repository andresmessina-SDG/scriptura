"""The feed-index cache is a retry floor, not a day-long trust.

refresh_index is only ever called on a miss (a lookup that found no episode
for the day on screen), so a miss must be allowed to refetch — otherwise a new
calendar day's reading, or the evening episode that publishes midday, stays
invisible until an arbitrary clock ran out. The floor only rate-limits that.
"""
import datetime
import json
import os

import devotional_audio as da


def _feed_xml(*dated_titles):
    items = ''.join(
        f'<item><title>{t}</title>'
        f'<enclosure url="https://example.test/{i}.mp3"/></item>'
        for i, t in enumerate(dated_titles))
    return f'<rss><channel>{items}</channel></rss>'


class _FakeResp:
    def __init__(self, body):
        self._body = body.encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_feed(monkeypatch, tmp_path, xml):
    """Point the cache at tmp_path and serve `xml` from every fetch, counting
    how many fetches actually happen."""
    monkeypatch.setattr(da.paths, 'cache_dir', lambda: str(tmp_path))
    calls = {'n': 0}

    def fake_urlopen(req, timeout=0):
        calls['n'] += 1
        return _FakeResp(xml)

    monkeypatch.setattr(da.urllib.request, 'urlopen', fake_urlopen)
    return calls


def _write_index(tmp_path, feed, episodes, age):
    """Write a cached index for `feed` and backdate its mtime by `age`."""
    path = da._index_path(feed)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'feed': feed, 'episodes': episodes}, fh)
    when = (datetime.datetime.now() - age).timestamp()
    os.utime(path, (when, when))


def test_miss_on_stale_cache_refetches(monkeypatch, tmp_path):
    feed = da.DAILY_STRENGTH_FEED_URL
    calls = _install_feed(monkeypatch, tmp_path,
                          _feed_xml('July 21 - Today’s Reading'))
    # Yesterday's cache: it knows the 20th, not the 21st, and predates the
    # retry floor.
    _write_index(tmp_path, feed, {'07-20': ['old', 'Yesterday']},
                 age=datetime.timedelta(hours=3))

    got = da.refresh_index(feed=feed)

    assert calls['n'] == 1, 'a stale miss must refetch'
    assert '07-21' in got


def test_miss_within_floor_is_trusted(monkeypatch, tmp_path):
    feed = da.DAILY_STRENGTH_FEED_URL
    calls = _install_feed(monkeypatch, tmp_path,
                          _feed_xml('July 21 - Today’s Reading'))
    # Just refetched: a second miss inside the floor must not hit the network.
    _write_index(tmp_path, feed, {'07-20': ['old', 'Yesterday']},
                 age=datetime.timedelta(minutes=5))

    got = da.refresh_index(feed=feed)

    assert calls['n'] == 0, 'a miss within the retry floor must be trusted'
    assert '07-21' not in got


def test_force_refetches_regardless_of_floor(monkeypatch, tmp_path):
    feed = da.DAILY_STRENGTH_FEED_URL
    calls = _install_feed(monkeypatch, tmp_path,
                          _feed_xml('July 21 - Today’s Reading'))
    _write_index(tmp_path, feed, {'07-20': ['old', 'Yesterday']},
                 age=datetime.timedelta(minutes=5))

    got = da.refresh_index(force=True, feed=feed)

    assert calls['n'] == 1
    assert '07-21' in got


def test_failed_fetch_keeps_the_old_answer(monkeypatch, tmp_path):
    feed = da.DAILY_STRENGTH_FEED_URL
    monkeypatch.setattr(da.paths, 'cache_dir', lambda: str(tmp_path))

    def boom(req, timeout=0):
        raise OSError('offline')

    monkeypatch.setattr(da.urllib.request, 'urlopen', boom)
    _write_index(tmp_path, feed, {'07-20': ['old', 'Yesterday']},
                 age=datetime.timedelta(hours=3))

    got = da.refresh_index(feed=feed)

    assert got == {'07-20': ['old', 'Yesterday']}


# ── duplicate keys: the newest recording wins ────────────────────────────
# RSS is newest-first, so the first item bearing a key is the most recent
# reading of it. All three parsers must agree — parse_feed used to assign
# rather than setdefault, and so would have served the older recording once
# the feed wrapped a full year (Morning & Evening wraps in early 2027).

def _dup_xml(*pairs):
    items = ''.join(
        f'<item><title>{t}</title><enclosure url="{u}"/></item>'
        for t, u in pairs)
    return f'<rss><channel>{items}</channel></rss>'


def test_dated_feed_keeps_the_newest_of_a_repeated_date():
    xml = _dup_xml(('July 20 | Morning', 'https://example.test/2027.mp3'),
                   ('July 20 | Morning', 'https://example.test/2026.mp3'))
    assert da.parse_feed(xml) == {'07-20:morning': 'https://example.test/2027.mp3'}


def test_daily_strength_keeps_the_newest_of_a_repeated_date():
    xml = _dup_xml(('July 20 - New Title', 'https://example.test/2027.mp3'),
                   ('July 20 - Old Title', 'https://example.test/2026.mp3'))
    assert da.parse_dated_feed(xml)['07-20'] == [
        'https://example.test/2027.mp3', 'New Title']


def test_psalms_feed_keeps_the_newest_reading_of_a_psalm():
    xml = _dup_xml(('Psalm 16 - Newer Reading', 'https://example.test/new.mp3'),
                   ('Psalm 16 - Older Reading', 'https://example.test/old.mp3'))
    assert da.parse_psalms_feed(xml)['16'] == [
        'https://example.test/new.mp3', 'Newer Reading']


def test_all_three_parsers_agree_on_precedence():
    """The bug was that they did not: one assigned while two setdefault'd."""
    dated = da.parse_feed(_dup_xml(
        ('May 3 | Evening', 'first'), ('May 3 | Evening', 'second')))
    strength = da.parse_dated_feed(_dup_xml(
        ('May 3 - A', 'first'), ('May 3 - B', 'second')))
    psalms = da.parse_psalms_feed(_dup_xml(
        ('Psalm 3 - A', 'first'), ('Psalm 3 - B', 'second')))
    assert dated['05-03:evening'] == 'first'
    assert strength['05-03'][0] == 'first'
    assert psalms['3'][0] == 'first'


def test_items_without_a_title_or_enclosure_are_skipped():
    xml = ('<rss><channel>'
           '<item><title>July 20 | Morning</title></item>'
           '<item><enclosure url="https://example.test/x.mp3"/></item>'
           '<item><title>July 21 | Morning</title>'
           '<enclosure url="https://example.test/ok.mp3"/></item>'
           '</channel></rss>')
    assert da.parse_feed(xml) == {'07-21:morning': 'https://example.test/ok.mp3'}
