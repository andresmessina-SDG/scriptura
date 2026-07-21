"""Spoken audio for Spurgeon's *Morning and Evening*, from the publisher's
own podcast feed.

Crossway publish the whole devotional as a daily podcast, two episodes per
calendar day, titled "July 20 | Morning" and "July 20 | Evening". That is a
(month, day, session) key, which is exactly how the devotional itself is
organised — so an episode can be matched to the entry on screen without
guessing at anything. A public podcast feed is published precisely so that
arbitrary clients may play it; nothing here scrapes a page or depends on
undocumented internals.

Two decisions worth keeping:

* **Episodes are cached, never streamed.** The app reads offline and keeps no
  telemetry; streaming would put a request on the publisher's analytics host
  every time the reader pressed play. One download per episode (~5 MB) is
  quieter, works on a train, and hands the pipeline a local file.
* **The pipeline is explicit, not `Gtk.MediaFile`.** GTK's media widget routes
  through GStreamer's `decodebin3`, which was measured aborting outright on
  these files (`gstdecodebin3.c: assertion failed: (collection)`) while the
  same audio decoded cleanly through `mpegaudioparse ! mpg123audiodec`. The
  format is known — it is always MP3 — so nothing needs to be auto-detected
  and the fragile path can simply be avoided.

The network is touched only when a devotional this feed actually reads is
open, and then only to fetch the day's episode once.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import urllib.request

import paths

#: Crossway's feed for the devotional. Resolved from the podcast's public
#: directory listing; the publisher's own channel, not a mirror.
FEED_URL = 'https://feeds.megaphone.fm/morningandevening'

#: "Daily Strength: A 365-Day Devotional for Men" — the same publisher, but
#: its feed is a ROLLING THIRTY-DAY WINDOW rather than a back catalogue, so a
#: date outside it simply does not exist. Only the current day is ever offered:
#: today is always in the window, and a control that worked in July and failed
#: in October for reasons no reader could see would be worse than none.
DAILY_STRENGTH_FEED_URL = 'https://feeds.megaphone.fm/dailystrength'

#: "July 20 - Discipleship through Discipline" — a date and the day's title.
_DATED_TITLE = re.compile(
    r'^\s*([A-Z][a-z]+)\s+(\d{1,2})\s*[-–—]\s*(.+?)\s*$')


#: "In the Lord I Take Refuge" — Dane Ortlund's daily devotions through the
#: Psalms, one episode a psalm, from the same publisher. Its titles carry the
#: psalm number outright ("Psalm 16 - You Will Not Abandon My Soul"), so the
#: key is the number itself and nothing has to be inferred from position.
PSALMS_FEED_URL = 'https://feeds.megaphone.fm/CXW8316192394'

#: "Psalm 16 - You Will Not Abandon My Soul". The subtitle is the episode's
#: own title for the psalm and is kept for display; the number is the key.
_PSALM_TITLE = re.compile(r'^\s*Psalm\s+(\d{1,3})\s*(?:[-–—]\s*(.*))?$')

#: The floor between refetches of a feed index. refresh_index is only ever
#: called on a miss — a lookup that found no episode for the day (or psalm) on
#: screen — so a miss should refetch, in case the feed has published since the
#: cache was written: a new calendar day's reading, or the evening episode that
#: appears midday. This floor only rate-limits that, so paging across days a
#: feed hasn't published, or repeated Today syncs, can't hammer the publisher.
#: An hour is short enough that today's reading appears the first time it is
#: looked for, and long enough to keep the app off the network the rest of the
#: time. (An earlier 20-hour "trust" meant a new day's episode stayed invisible
#: all morning — the cache was still "fresh" but predated the reading.)
MISS_RETRY_FLOOR = datetime.timedelta(hours=1)

#: The hour from which the evening reading is the one meant. NOON, not the
#: evensong hour the Today page uses for its epigraph: this is a book of two
#: readings a day, and by any reckoning the afternoon belongs to the second
#: one. At 16:00 an afternoon reader was handed the morning reading and had to
#: go looking for the other.
EVENING_HOUR = 12

_UA = 'Scriptura (Bible reader; +https://codeberg.org/andresmessina/scriptura)'

#: "July 20 | Evening" — the publisher's own title format.
_TITLE = re.compile(
    r'^\s*([A-Z][a-z]+)\s+(\d{1,2})\s*\|\s*(Morning|Evening)\s*$')

_MONTHS = {m: i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'], start=1)}


#: SWORD module keys that are this book. "SME" is CrossWire's own key for
#: Spurgeon's Morning and Evening.
_KNOWN_KEYS = {'sme'}


def covers_module(module_name: str) -> bool:
    """Whether this feed is a reading of *this* devotional.

    The feed is one publisher reading one book. Offering its audio beside a
    different devotional would put the wrong words over the right page, so the
    module has to be the one the feed actually reads.

    The name given is the SWORD module KEY, not the title shown in the header
    — CrossWire ships this devotional as "SME" while the header reads
    "Spurgeon — Morning & Evening". Matching only the readable title silently
    matched nothing at all. The key is checked first; the descriptive test is
    kept for other packagings of the same book.
    """
    n = re.sub(r'[^a-z]', '', (module_name or '').lower())
    if n in _KNOWN_KEYS:
        return True
    return 'spurgeon' in n and 'morning' in n and 'evening' in n


def session_for_hour(hour: int) -> str:
    """Which half of the day an entry means at this hour."""
    return 'evening' if hour >= EVENING_HOUR else 'morning'


def _index_path(feed: str = FEED_URL) -> str:
    name = {PSALMS_FEED_URL: 'psalms',
            DAILY_STRENGTH_FEED_URL: 'daily_strength'}.get(feed, 'devotional')
    return os.path.join(paths.cache_dir(), f'{name}_audio_index.json')


def parse_psalms_feed(xml: str) -> dict[str, list[str]]:
    """{'<psalm number>': [url, subtitle]} for every psalm the feed carries.

    The trailer and the publisher's book previews carry no psalm number and
    are skipped — an episode whose psalm cannot be read is one the player does
    not offer.
    """
    out: dict[str, list[str]] = {}
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        ti = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>',
                       block, re.S)
        url = re.search(r'<enclosure[^>]*url="([^"]+)"', block)
        if not ti or not url:
            continue
        m = _PSALM_TITLE.match(re.sub(r'\s+', ' ', ti.group(1)).strip())
        if not m:
            continue
        n = int(m.group(1))
        if not 1 <= n <= 150:
            continue
        # Later entries win: the feed has run more than one cycle, and the
        # most recent reading of a psalm is the one at the top.
        out.setdefault(str(n), [url.group(1), (m.group(2) or '').strip()])
    return out


def parse_dated_feed(xml: str) -> dict[str, list[str]]:
    """{'MM-DD': [url, title]} for a feed whose episodes are titled by date."""
    out: dict[str, list[str]] = {}
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        ti = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>',
                       block, re.S)
        url = re.search(r'<enclosure[^>]*url="([^"]+)"', block)
        if not ti or not url:
            continue
        m = _DATED_TITLE.match(re.sub(r'\s+', ' ', ti.group(1)).strip())
        if not m:
            continue
        month = _MONTHS.get(m.group(1))
        if not month:
            continue
        out.setdefault(f'{month:02d}-{int(m.group(2)):02d}',
                       [url.group(1), m.group(3)])
    return out


def todays_strength(date: datetime.date) -> tuple[str, str] | None:
    """(url, the day's title) for today's reading, or None.

    Today only, by design — see DAILY_STRENGTH_FEED_URL.
    """
    got = _load_index(DAILY_STRENGTH_FEED_URL).get(
        f'{date.month:02d}-{date.day:02d}')
    if isinstance(got, list) and got:
        return got[0], (got[1] if len(got) > 1 else '')
    return None


def psalm_episode_url(number: int) -> tuple[str, str] | None:
    """(url, the episode's title for this psalm), or None."""
    got = _load_index(PSALMS_FEED_URL).get(str(number))
    if isinstance(got, list) and got:
        return got[0], (got[1] if len(got) > 1 else '')
    return None


def _episode_dir() -> str:
    d = os.path.join(paths.cache_dir(), 'devotional_audio')
    os.makedirs(d, exist_ok=True)
    return d


def parse_feed(xml: str) -> dict[str, str]:
    """{'MM-DD:session': enclosure_url} for every episode the feed carries.

    Titles that are not a dated episode — the channel trailer, say — are
    skipped rather than guessed at. An episode whose title cannot be read is
    an episode the player does not offer.
    """
    out: dict[str, str] = {}
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        t = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>',
                      block, re.S)
        url = re.search(r'<enclosure[^>]*url="([^"]+)"', block)
        if not t or not url:
            continue
        m = _TITLE.match(re.sub(r'\s+', ' ', t.group(1)).strip())
        if not m:
            continue
        month = _MONTHS.get(m.group(1))
        if not month:
            continue
        out[f'{month:02d}-{int(m.group(2)):02d}:{m.group(3).lower()}'] = \
            url.group(1)
    return out


def _load_index(feed: str = FEED_URL):
    try:
        with open(_index_path(feed), encoding='utf-8') as fh:
            return json.load(fh).get('episodes', {})
    except (OSError, ValueError):
        return {}


def _recently_refetched(feed: str = FEED_URL) -> bool:
    """Whether the index was refetched within the retry floor — in which case a
    fresh miss is trusted rather than triggering another fetch."""
    try:
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(
            os.path.getmtime(_index_path(feed)))
    except OSError:
        return False
    return age < MISS_RETRY_FLOOR


def refresh_index(force: bool = False, feed: str = FEED_URL):
    """The episode index, refetched on a miss unless it was refetched within
    the last MISS_RETRY_FLOOR.

    Blocking network work — call from a task worker. Returns the cached index
    unchanged if the fetch fails: a feed that cannot be reached should leave
    yesterday's answer standing, not erase it.
    """
    cached = _load_index(feed)
    if cached and not force and _recently_refetched(feed):
        return cached
    parse = {PSALMS_FEED_URL: parse_psalms_feed,
             DAILY_STRENGTH_FEED_URL: parse_dated_feed}.get(feed, parse_feed)
    try:
        req = urllib.request.Request(feed, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            episodes = parse(resp.read().decode('utf-8', 'replace'))
    except Exception:
        return cached
    if not episodes:
        return cached
    try:
        with open(_index_path(feed), 'w', encoding='utf-8') as fh:
            json.dump({'feed': feed, 'episodes': episodes}, fh)
    except OSError:
        pass
    return episodes


def episode_url(date: datetime.date, session: str,
                index: dict[str, str] | None = None) -> str | None:
    """The publisher's URL for one day's morning or evening reading, or None.

    None is the honest answer for a day the feed has not published — the
    control is simply not offered, rather than offered and broken.
    """
    idx = _load_index() if index is None else index
    return idx.get(f'{date.month:02d}-{date.day:02d}:{session}')


def cached_episode(url: str) -> str | None:
    """The local copy of an episode, if it has already been fetched."""
    p = os.path.join(_episode_dir(), _cache_name(url))
    return p if os.path.exists(p) else None


def _cache_name(url: str) -> str:
    base = os.path.basename(url.split('?', 1)[0]) or 'episode'
    return re.sub(r'[^A-Za-z0-9._-]', '_', base)[-64:]


def fetch_episode(url: str) -> str | None:
    """Download an episode and return its local path (or None).

    Blocking — call from a task worker. Written to a .part file and renamed,
    so an interrupted download can never be mistaken for a playable one.
    """
    have = cached_episode(url)
    if have:
        return have
    dest = os.path.join(_episode_dir(), _cache_name(url))
    part = dest + '.part'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=60) as resp, \
                open(part, 'wb') as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
        os.replace(part, dest)
        return dest
    except Exception:
        try:
            os.unlink(part)
        except OSError:
            pass
        return None


class Player:
    """One devotional playing at a time, on an explicit GStreamer pipeline.

    Deliberately small: play, pause, stop, and where it has got to. There is
    no scrubber and no time readout, because this is a devotional being read
    aloud rather than a media library — see the Today page's own restraint.
    """

    def __init__(self) -> None:
        self._pipeline = None
        self._path: str | None = None

    @staticmethod
    def _gst():
        """The Gst module, version-pinned and initialised once.

        Imported here rather than at module scope so that a build without
        GStreamer still loads the app; pinned every time because an
        unversioned `from gi.repository import Gst` warns.
        """
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init(None)
        return Gst

    #: Memoised: initialising GStreamer builds its plugin registry and probes
    #: hardware video drivers, which was measured taking seconds on a cold
    #: cache. This is asked on every date change, so it must be paid once.
    _available: bool | None = None

    @staticmethod
    def available() -> bool:
        """Whether GStreamer can be used at all in this build.

        Only ever reached when the reader has turned the feature on — the
        caller checks the setting first, so a default install never
        initialises GStreamer at all.
        """
        if Player._available is None:
            try:
                Player._gst()
                Player._available = True
            except Exception:
                Player._available = False
        return Player._available

    def _build(self, path: str):
        Gst = self._gst()
        # Explicit, because the format is known. decodebin3 — which
        # Gtk.MediaFile uses — was measured aborting on these files.
        return Gst.parse_launch(
            f'filesrc location="{path}" ! mpegaudioparse ! mpg123audiodec'
            ' ! audioconvert ! audioresample ! autoaudiosink')

    def play(self, path: str) -> bool:
        """Start (or resume) a file. True if the pipeline took it."""
        Gst = self._gst()
        if self._pipeline is not None and self._path != path:
            self.stop()
        if self._pipeline is None:
            try:
                self._pipeline = self._build(path)
            except Exception:
                self._pipeline = None
                return False
            self._path = path
        pipeline = self._pipeline
        if pipeline is None:
            return False
        return bool(pipeline.set_state(Gst.State.PLAYING)
                    != Gst.StateChangeReturn.FAILURE)

    def pause(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(self._gst().State.PAUSED)

    def stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(self._gst().State.NULL)
        self._pipeline = None
        self._path = None

    @property
    def playing(self) -> bool:
        if self._pipeline is None:
            return False
        return self._pipeline.get_state(0)[1] == self._gst().State.PLAYING

    def progress(self) -> float:
        """How far through, 0.0–1.0. Zero until the pipeline knows."""
        if self._pipeline is None:
            return 0.0
        Gst = self._gst()
        ok_p, pos = self._pipeline.query_position(Gst.Format.TIME)
        ok_d, dur = self._pipeline.query_duration(Gst.Format.TIME)
        if not (ok_p and ok_d) or dur <= 0:
            return 0.0
        return max(0.0, min(1.0, pos / dur))

    def ended(self) -> bool:
        """Whether playback has run to the end of the file."""
        return self._pipeline is not None and self.progress() >= 0.999
