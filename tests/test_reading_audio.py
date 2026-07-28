"""What the spoken-reading controls do between the press and the sound.

A chapter is fetched before anything can be heard — six megabytes, twenty for
the longest psalm — so the wait, and any failure of it, is most of what these
controls are. The rule under test, on all three: the pause icon means playing
and nothing else, the wait shows itself once it is long enough to be worth
showing, and a failure says so instead of quietly putting the icon back.

No display and no network: each state machine is borrowed off its real class
onto stand-in widgets, and the fetch is the task runner's callbacks called by
hand.
"""
import pytest
from gi.repository import GLib

import audio_surfaces
import bible_audio
import devotional_audio
import motion
import mpris
import pane
import settings
import tasks
import window
from audio_surfaces import DevotionalAudio, ReadingAudio, _Surface
from window import BibleWindow


class FakeButton:
    def __init__(self):
        self.icon = 'media-playback-start-symbolic'
        self.tooltip = None
        self.label = None
        self.announced = []

    def set_icon_name(self, name):
        self.icon = name

    def set_tooltip_text(self, text):
        self.tooltip = text

    def update_property(self, _props, values):
        self.label = values[0]

    def get_display(self):
        return None          # a11y: any display but Broadway

    def announce(self, message, _priority):
        self.announced.append(message)


class FakePill:
    """The pill, recording what the pane tells it."""

    def __init__(self):
        self.state = 'idle'
        self.fraction = 0.0
        self.reference = ''
        self.length = ''
        self.switch = ''
        self.visible = False
        self.can_seek = False
        self.rate = 1.0
        self.announced = []

    def set_state(self, state):
        self.state = state

    def set_progress(self, fraction):
        self.fraction = fraction

    def set_reading(self, reference, length=''):
        self.reference, self.length = reference, length

    def set_switch(self, reference):
        self.switch = reference

    def set_can_seek(self, can_seek):
        self.can_seek = can_seek

    def set_rate(self, rate):
        self.rate = rate

    def present(self):
        self.visible = True

    def dismiss(self):
        self.visible = False
        self.state = 'idle'

    def is_shown(self):
        return self.visible

    # a11y announces against the pill
    def get_display(self):
        return None

    def announce(self, message, _priority):
        self.announced.append(message)


class FakeBar:
    def __init__(self):
        self.fraction = 0.0
        self.opacity = 0.0
        self.visible = False
        self.pulses = 0

    def set_fraction(self, fraction):
        self.fraction = fraction

    def set_opacity(self, opacity):
        self.opacity = opacity

    def set_visible(self, visible):
        self.visible = visible

    def pulse(self):
        self.pulses += 1


class FakePlayer:
    def __init__(self, playable=True):
        self.playing = False
        self.playable = playable
        self.seeks = []
        self.rate = 1.0
        self.played = []

    def play(self, path):
        self.played.append(path)
        self.playing = self.playable
        return self.playable

    def pause(self):
        self.playing = False

    def progress(self):
        return 0.0

    def ended(self):
        return False

    def stop(self):
        self.playing = False

    def seek_relative(self, seconds):
        self.seeks.append(seconds)
        return True

    def set_rate(self, rate):
        self.rate = rate
        return True

    def duration(self):
        return 273.0


class FakeRunner:
    """Captures what was submitted instead of running it on a thread."""

    def __init__(self):
        self.apply = None
        self.on_error = None
        self.cancelled = []

    def submit(self, key, work, apply, on_error):
        self.key, self.work, self.apply, self.on_error = (
            key, work, apply, on_error)

    def cancel(self, key):
        self.cancelled.append(key)


class FakeBus:
    """The desktop's media bus, recording instead of connecting.

    Autoused everywhere below: these tests run on a workstation with a real
    session bus, and a test suite must not put a media player on it.
    """

    Reading = mpris.Reading

    def __init__(self):
        self.published = []
        self.updated = []
        self.withdrawn = []
        self.current = None

    def publish(self, reading):
        self.published.append(reading)
        self.current = reading

    def update(self, reading):
        self.updated.append(reading)

    def withdraw(self, reading):
        if reading is not None:
            self.withdrawn.append(reading)
            if self.current is reading:
                self.current = None


@pytest.fixture(autouse=True)
def bus(monkeypatch):
    fake = FakeBus()
    monkeypatch.setattr(audio_surfaces, 'mpris', fake)
    monkeypatch.setattr(window, 'mpris', fake)
    return fake


def _runner(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(tasks, 'submit', runner.submit)
    monkeypatch.setattr(tasks, 'cancel', runner.cancel)
    return runner


def _pump(ms):
    """Run the default main context until `ms` have elapsed."""
    done = []
    GLib.timeout_add(ms, lambda: done.append(1) and GLib.SOURCE_REMOVE)
    ctx = GLib.MainContext.default()
    while not done:
        ctx.iteration(True)


# ════ The chapter reading (pane toolbar) ═════════════════════════════════════

class Reading:
    """The chapter-reading control, widgets stubbed out."""

    _on_reading_play = ReadingAudio._on_reading_play
    _on_reading_listen = ReadingAudio._on_reading_listen
    _on_reading_close = ReadingAudio._on_reading_close
    _on_reading_back = ReadingAudio._on_reading_back
    _on_reading_rate = ReadingAudio._on_reading_rate
    _begin_reading_fetch = ReadingAudio._begin_reading_fetch
    _end_reading_fetch = ReadingAudio._end_reading_fetch
    _show_reading_length = ReadingAudio._show_reading_length
    _finish_reading_fetch = ReadingAudio._finish_reading_fetch
    _report_audio_failure = _Surface._report_audio_failure
    _start_reading_audio = ReadingAudio._start_reading_audio
    _stop_reading_audio = ReadingAudio._stop_reading_audio
    _on_reading_tick = ReadingAudio._on_reading_tick
    _reading_is_live = ReadingAudio._reading_is_live
    _restate_pill_reading = ReadingAudio._restate_pill_reading
    _live_reference = ReadingAudio._live_reference
    _on_reading_switch = ReadingAudio._on_reading_switch
    _reading_series = ReadingAudio._reading_series
    _publish_reading_media = ReadingAudio._publish_reading_media

    def __init__(self, cached=None, player=None):
        self._pill = FakePill()
        self._reading_url = 'https://example.invalid/BSB_01_Gen_001.mp3'
        self._reading_scripture = True
        self._reading_player = player
        self._reading_tick = None
        self._reading_fetching = False
        self._reading_reference = 'John 3'
        self._reading_length = ''
        self._reading_key = 'reading-audio:test'
        self._sounding = None
        self._pending = None
        self._reading_media = None
        self._cached = cached
        self.toasts = []
        self._on_toast = self.toasts.append

    def _cached_reading(self, _url):
        return self._cached


# ── The wait ─────────────────────────────────────────────────────────────────

def test_fetching_never_shows_the_pause_icon(monkeypatch):
    """The bug this control had: pause meant "downloading" for as long as the
    file took, then silently meant nothing."""
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    assert c._pill.state == 'fetching'
    assert c._reading_fetching


def test_fetching_says_so_to_a_screen_reader(monkeypatch):
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    assert 'Fetching the reading' in c._pill.announced


def test_a_cached_chapter_plays_without_any_fetch_state(monkeypatch):
    """Nothing to wait for, so nothing to show."""
    _runner(monkeypatch)
    c = Reading(cached='/tmp/Gen_001.mp3', player=FakePlayer())
    c._on_reading_play()
    assert not c._reading_fetching
    assert c._pill.state == 'playing'
    assert c._pill.can_seek


def test_the_thread_shows_position_only_once_playing(monkeypatch):
    """While fetching, the thread is the pill's own busy indicator — the pane
    must not write a position over it."""
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    assert c._pill.state == 'fetching'
    assert c._pill.fraction == 0.0


def test_the_length_is_stated_when_the_file_opens(monkeypatch):
    _runner(monkeypatch)
    c = Reading(player=FakePlayer())
    c._finish_reading_fetch('/tmp/Gen_001.mp3')
    assert c._pill.reference == 'John 3'
    assert c._pill.length == '4:33'


# ── The failure ──────────────────────────────────────────────────────────────

def test_failed_fetch_explains_itself(monkeypatch):
    """The whole point: the icon going back to play is not an explanation."""
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    c._finish_reading_fetch(None)     # what fetch_chapter answers every
    assert c.toasts == ['Could not fetch the reading']    # failure with
    assert c._pill.state == 'idle'
    assert not c._reading_fetching


def test_failed_fetch_reaches_a_screen_reader(monkeypatch):
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    c._finish_reading_fetch(None)
    assert c._pill.announced[-1] == 'Could not fetch the reading'


def test_a_raised_fetch_error_lands_in_the_same_place(monkeypatch):
    """fetch_chapter swallows its exceptions and returns None, but the runner
    still has an error path — both must end at the same message."""
    runner = _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    runner.on_error(OSError('no route to host'))
    assert c.toasts == ['Could not fetch the reading']


def test_a_file_the_pipeline_refuses_explains_itself(monkeypatch):
    """A fetch can succeed and playback still fail — a truncated file, no
    audio sink. That reset was silent too."""
    _runner(monkeypatch)
    c = Reading(player=FakePlayer(playable=False))
    c._finish_reading_fetch('/tmp/Gen_001.mp3')
    assert c.toasts == ['Could not play the reading']
    assert c._pill.state == 'idle'


def test_a_failed_fetch_leaves_the_pill_standing(monkeypatch):
    """It goes back to offering the reading rather than vanishing: the reader
    pressed play, and the answer to a failure is a control they can press
    again, not an empty page."""
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_listen(None)             # headphones, then play
    c._on_reading_play()
    c._finish_reading_fetch(None)
    assert c._pill.visible
    assert c._pill.state == 'idle'
    assert c._pill.reference == 'John 3'


# ── Second thoughts ──────────────────────────────────────────────────────────

def test_pressing_again_stops_the_fetch(monkeypatch):
    runner = _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    c._on_reading_play()
    assert runner.cancelled == ['reading-audio:test']
    assert not c._reading_fetching
    assert c._pill.state == 'idle'
    assert c.toasts == []                  # asked for, not a failure


def test_navigating_away_stops_the_fetch(monkeypatch):
    """Otherwise the chapter that was on screen when play was pressed starts
    playing after the reader has moved to another one."""
    runner = _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    c._stop_reading_audio()                # what _sync_reading_audio calls
    assert runner.cancelled == ['reading-audio:test']
    assert not c._reading_fetching
    assert c.toasts == []


def test_a_stopped_fetch_can_be_started_again(monkeypatch):
    runner = _runner(monkeypatch)
    c = Reading()
    c._on_reading_play()
    c._on_reading_play()
    c._on_reading_play()
    assert c._reading_fetching
    assert runner.apply is not None


# ════ The devotional (pane date row) ═════════════════════════════════════════

class Devotional:
    """The date row's morning/evening player, widgets stubbed out."""

    _on_devot_play = DevotionalAudio._on_devot_play
    _begin_devot_fetch = DevotionalAudio._begin_devot_fetch
    _clear_devot_band = DevotionalAudio._clear_devot_band
    _end_devot_fetch = DevotionalAudio._end_devot_fetch
    _finish_devot_fetch = DevotionalAudio._finish_devot_fetch
    _report_audio_failure = _Surface._report_audio_failure
    _start_devotional_audio = DevotionalAudio._start_devotional_audio
    _stop_devotional_audio = DevotionalAudio._stop_devotional_audio
    _on_devotional_audio_tick = DevotionalAudio._on_devotional_audio_tick
    _publish_devot_media = DevotionalAudio._publish_devot_media

    def __init__(self, player=None, delay_ms=motion.SPINNER_DELAY_MS):
        from gtk_utils import DelayedPulse
        self._devot_play_btn = FakeButton()
        self._devot_progress = FakeBar()
        self._devot_audio_row = object()
        self._devot_player = player
        self._devot_media = None
        self._devot_tick = None
        self._devot_date = None
        self._devot_session = 'morning'
        self._devot_fetching = False
        self._devot_key = 'devot-audio:test'
        self._devot_wait = DelayedPulse(
            show=lambda: self._devot_progress.set_visible(True),
            tick=self._devot_progress.pulse,
            hide=self._clear_devot_band, delay_ms=delay_ms)
        self.relabelled = 0
        self.toasts = []
        self._on_toast = self.toasts.append

    def _refresh_devot_labels(self):
        # The real one restates Morning/Evening from the day; here it is
        # enough to know the control asks to be re-worded.
        self.relabelled += 1


def _devotional(monkeypatch, cached=None, player=None):
    _runner(monkeypatch)
    monkeypatch.setattr(devotional_audio, 'episode_url',
                        lambda *_a: 'https://example.invalid/today.mp3')
    monkeypatch.setattr(devotional_audio, 'cached_episode',
                        lambda *_a, **_k: cached)
    return Devotional(player=player)


def test_devotional_fetch_never_shows_the_pause_icon(monkeypatch):
    c = _devotional(monkeypatch)
    c._on_devot_play(None)
    assert c._devot_play_btn.icon == 'media-playback-stop-symbolic'
    assert c._devot_fetching
    c._end_devot_fetch()


def test_devotional_failure_explains_itself(monkeypatch):
    c = _devotional(monkeypatch)
    c._on_devot_play(None)
    c._finish_devot_fetch(None)
    assert c.toasts == ['Could not fetch the reading']
    assert c._devot_play_btn.icon == 'media-playback-start-symbolic'
    assert c._devot_play_btn.announced[-1] == 'Could not fetch the reading'
    assert c.relabelled == 1               # Morning/Evening restated


def test_devotional_cached_episode_plays_at_once(monkeypatch):
    c = _devotional(monkeypatch, cached='/tmp/today.mp3',
                    player=FakePlayer())
    c._on_devot_play(None)
    assert not c._devot_fetching
    assert c._devot_play_btn.icon == 'media-playback-pause-symbolic'
    assert c._devot_progress.visible


def test_devotional_second_press_stops_the_fetch(monkeypatch):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(devotional_audio, 'episode_url',
                        lambda *_a: 'https://example.invalid/today.mp3')
    monkeypatch.setattr(devotional_audio, 'cached_episode',
                        lambda *_a, **_k: None)
    c = Devotional()
    c._on_devot_play(None)
    c._on_devot_play(None)
    assert runner.cancelled == ['devot-audio:test']
    assert not c._devot_fetching
    assert c.toasts == []


def test_devotional_day_change_stops_the_fetch(monkeypatch):
    c = _devotional(monkeypatch)
    c._on_devot_play(None)
    c._stop_devotional_audio()             # what _sync_devotional_audio calls
    assert not c._devot_fetching
    assert not c._devot_progress.visible


# ════ The Today disc (window + page) ═════════════════════════════════════════

class FakeTodayView:
    def __init__(self):
        self.states = []
        self.fraction = None

    def set_listen(self, title, playing=False, fetching=False):
        self.states.append(('fetching' if fetching
                            else 'playing' if playing else 'rest', title))

    def set_listen_progress(self, fraction, showing=True):
        self.fraction = fraction if showing else 0.0


class Today:
    """The Today page's listen disc, view and toasts stubbed out."""

    _on_today_listen = BibleWindow._on_today_listen
    _end_today_fetch = BibleWindow._end_today_fetch
    _finish_today_fetch = BibleWindow._finish_today_fetch
    _start_today_listen = BibleWindow._start_today_listen
    _stop_today_listen = BibleWindow._stop_today_listen
    _on_today_listen_tick = BibleWindow._on_today_listen_tick
    _publish_today_media = BibleWindow._publish_today_media

    def __init__(self, player=None):
        self._today_view = FakeTodayView()
        self._today_listen = ('https://example.invalid/today.mp3',
                              'A Daily Strength')
        self._today_player = player
        self._today_media = None
        self._today_listen_tick = None
        self._today_fetching = False
        self.toasts = []
        self.announced = []

    # window.py announces against the window itself
    def get_display(self):
        return None

    def announce(self, message, _priority):
        self.announced.append(message)

    def _toast(self, message):
        self.toasts.append(message)


def _today(monkeypatch, cached=None, player=None):
    _runner(monkeypatch)
    monkeypatch.setattr(devotional_audio, 'cached_episode',
                        lambda *_a, **_k: cached)
    return Today(player=player)


def test_today_fetch_never_shows_the_pause_icon(monkeypatch):
    c = _today(monkeypatch)
    c._on_today_listen()
    assert c._today_view.states[-1][0] == 'fetching'
    assert c._today_fetching
    assert 'Fetching the reading' in c.announced


def test_today_failure_explains_itself(monkeypatch):
    c = _today(monkeypatch)
    c._on_today_listen()
    c._finish_today_fetch(None)
    assert c.toasts == ['Could not fetch the reading']
    assert c.announced[-1] == 'Could not fetch the reading'
    assert c._today_view.states[-1] == ('rest', 'A Daily Strength')
    assert not c._today_fetching


def test_today_cached_episode_plays_at_once(monkeypatch):
    c = _today(monkeypatch, cached='/tmp/today.mp3', player=FakePlayer())
    c._on_today_listen()
    assert not c._today_fetching
    assert [s[0] for s in c._today_view.states] == ['playing', 'playing']
    assert c.toasts == []


def test_today_second_press_stops_the_fetch(monkeypatch):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(devotional_audio, 'cached_episode',
                        lambda *_a, **_k: None)
    c = Today()
    c._on_today_listen()
    c._on_today_listen()
    assert runner.cancelled and runner.cancelled[0].startswith('today-audio:')
    assert not c._today_fetching
    assert c._today_view.states[-1][0] == 'rest'
    assert c.toasts == []


def test_today_dismissal_stops_the_fetch(monkeypatch):
    """_dismiss_today drops the page and calls this; a landing fetch would
    otherwise start playing into an empty screen."""
    runner = _runner(monkeypatch)
    monkeypatch.setattr(devotional_audio, 'cached_episode',
                        lambda *_a, **_k: None)
    c = Today()
    c._on_today_listen()
    c._stop_today_listen()
    assert runner.cancelled and runner.cancelled[0].startswith('today-audio:')
    assert not c._today_fetching


def test_today_file_the_pipeline_refuses_explains_itself(monkeypatch):
    c = _today(monkeypatch, player=FakePlayer(playable=False))
    c._finish_today_fetch('/tmp/today.mp3')
    assert c.toasts == ['Could not play the reading']


# ── The headphone entry point ────────────────────────────────────────────────

def test_headphones_summon_the_pill_without_starting_anything(monkeypatch):
    """The split the whole redesign rests on: headphones open the listening
    surface, play starts the reading."""
    runner = _runner(monkeypatch)
    c = Reading()
    c._on_reading_listen(None)
    assert c._pill.visible
    assert c._pill.state == 'idle'
    assert runner.apply is None             # nothing fetched, nothing played


def test_headphones_again_put_it_away(monkeypatch):
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_listen(None)
    c._on_reading_listen(None)
    assert not c._pill.visible


def test_closing_the_pill_silences_what_it_was_controlling(monkeypatch):
    """A player dismissed while sounding would leave audio running with no
    control left to reach it."""
    _runner(monkeypatch)
    player = FakePlayer()
    c = Reading(cached='/tmp/Gen_001.mp3', player=player)
    c._on_reading_listen(None)
    c._on_reading_play()
    assert player.playing
    c._on_reading_close()
    assert not player.playing
    assert not c._pill.visible


def test_back_fifteen_only_when_there_is_a_player(monkeypatch):
    _runner(monkeypatch)
    c = Reading()
    c._on_reading_back()                    # no player yet: must not raise
    player = FakePlayer()
    c._reading_player = player
    c._on_reading_back()
    assert player.seeks == [-15]


# ── Paging on while a reading sounds ─────────────────────────────────────────
# Andres's ruling, 2026-07-26: a reading plays on when the reader navigates
# away — on the condition that the pause and the stop stay reachable. That
# condition is the whole reason the pill may not be put away below.

class Paging(Reading):
    """`Reading`, plus what re-offering a chapter needs. The pane's sync is
    what used to stop the reading, so it is the thing under test here."""

    _sync_reading_audio = ReadingAudio._sync_reading_audio
    _offer_reading_audio = ReadingAudio._offer_reading_audio
    _dismiss_pill_if_idle = ReadingAudio._dismiss_pill_if_idle

    class Item:
        """The toolbar's headphones and the box holding them: this test cares
        only whether they are offered, and what they are called."""

        def __init__(self):
            self.visible, self.tooltip = False, ''

        def set_visible(self, visible):
            self.visible = visible

        def set_tooltip_text(self, text):
            self.tooltip = text

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reading_audio = self.Item()
        self._reading_play_btn = self.Item()
        self._module = 'BSB'
        self._book, self._chapter = 'John', 3
        self.covered = True

    def _is_verse_navigable(self):
        return True


def _paging(monkeypatch, **kwargs):
    """A pane whose chapter can be changed, with the two module-level calls
    `_sync_reading_audio` makes standing in for the real address book."""
    c = Paging(**kwargs)
    monkeypatch.setattr(audio_surfaces, 'set_accessible_label',
                        lambda *a: None)
    monkeypatch.setattr(bible_audio, 'covers_module', lambda _m: c.covered)
    monkeypatch.setattr(
        bible_audio, 'chapter_url',
        lambda book, chapter: f'https://example.invalid/{book}_{chapter}.mp3')
    return c


def _listening(monkeypatch, **kwargs):
    """A pane with the pill up and John 3 sounding from the cache."""
    c = _paging(monkeypatch, cached='/tmp/John_003.mp3', **kwargs)
    c._sync_reading_audio()
    c._on_reading_listen(None)
    c._on_reading_play()
    return c


def test_paging_on_leaves_the_reading_sounding(monkeypatch):
    """The contradiction this closes: the pill names what is sounding so the
    reader can page on and still know what they are hearing, and paging on
    used to be exactly what stopped it."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    player = FakePlayer()
    c = _listening(monkeypatch, player=player)
    assert player.playing
    c._chapter = 4                          # the reader pages on
    c._sync_reading_audio()
    assert player.playing
    assert c._pill.state == 'playing'


def test_paging_on_cannot_put_the_pill_away(monkeypatch):
    """His condition on the ruling. The pill holds the only pause and the only
    stop, so a chapter with nothing to listen to may withdraw the toolbar's
    headphones but not the controls of a reading already under way."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    player = FakePlayer()
    c = _listening(monkeypatch, player=player)
    c.covered = False                       # a translation with no reading
    c._book = 'John'                        # and not a psalm either
    c._sync_reading_audio()
    assert c._pill.visible                  # the stop is still reachable
    assert player.playing
    assert not c._reading_audio.visible     # but nothing is offered here


def test_the_same_chapter_puts_the_pill_away_when_nothing_sounds(monkeypatch):
    """The other half of that rule: with nothing under way there is nothing to
    keep the pill up for."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch)
    c._on_reading_listen(None)
    c.covered = False
    c._sync_reading_audio()
    assert not c._pill.visible


def test_the_pill_keeps_naming_what_is_sounding(monkeypatch):
    """Not the chapter on screen. The two part company the moment the reader
    pages on, and the sounding one wins — it is what the controls act on."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _listening(monkeypatch, player=FakePlayer())
    c._chapter = 4
    c._sync_reading_audio()
    assert c._reading_reference == 'John 4'         # the offer moved
    assert c._pill.reference == 'John 3'            # the reading did not


def test_resuming_after_paging_on_resumes_what_was_sounding(monkeypatch):
    """Pause, page on, press play: that button has been showing John 3 all
    along, so it resumes John 3. Starting the chapter now on screen would be
    the pill doing something other than what it says, and would lose the
    reader's place in the reading they paused."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    player = FakePlayer()
    c = _listening(monkeypatch, player=player)
    c._on_reading_play()                            # pause
    assert not player.playing
    c._chapter = 4
    c._cached = '/tmp/John_004.mp3'
    c._sync_reading_audio()
    c._on_reading_play()                            # resume
    assert player.playing
    assert player.played[-1] == '/tmp/John_003.mp3'
    assert c._pill.reference == 'John 3'


def test_a_fetch_landing_after_paging_on_names_what_was_asked_for(monkeypatch):
    """A chapter is six megabytes and can be twenty, so the reader may well
    have paged on before it arrives. What plays is what they pressed play on,
    and the pill has to say so."""
    runner = _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch, player=FakePlayer())    # nothing cached
    c._sync_reading_audio()
    c._on_reading_listen(None)
    c._on_reading_play()
    c._chapter = 4
    c._sync_reading_audio()
    runner.apply('/tmp/John_003.mp3')
    assert c._pill.reference == 'John 3'
    assert c._sounding[0] == '/tmp/John_003.mp3'


# ── Reading this one instead ─────────────────────────────────────────────────
# The affordance that paging on made necessary: with John 3 sounding and John 4
# on screen there was no way to start John 4 except closing the pill, which
# stops John 3. Every player puts that control on the item rather than on the
# transport; this app has no list of items, so it goes on the pill, named after
# the chapter it would start, and only while there are two references to tell
# apart.

def test_no_switch_while_the_reader_is_where_the_reading_is(monkeypatch):
    """The ordinary case. Nothing has parted company, so a control offering to
    start what is already sounding would be a control that does nothing."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _listening(monkeypatch, player=FakePlayer())
    assert c._pill.switch == ''


def test_paging_on_offers_the_chapter_on_screen(monkeypatch):
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _listening(monkeypatch, player=FakePlayer())
    c._chapter = 4
    c._sync_reading_audio()
    assert c._pill.reference == 'John 3'         # still in hand
    assert c._pill.switch == 'John 4'            # and on offer


def test_nothing_sounding_offers_nothing(monkeypatch):
    """The pill is up, the reader is paging: with nothing in hand the play
    button already starts the chapter on screen, and a second control saying
    the same thing is one too many."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch)
    c._on_reading_listen(None)
    c._chapter = 4
    c._sync_reading_audio()
    assert c._pill.switch == ''


def test_a_chapter_with_no_reading_is_not_offered(monkeypatch):
    """A translation the reading does not cover, or a book it has no file for.
    The pill stays up holding the stop, but there is nothing here to start."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _listening(monkeypatch, player=FakePlayer())
    c.covered = False
    c._chapter = 4
    c._sync_reading_audio()
    assert c._pill.visible
    assert c._pill.switch == ''


def _reusable(monkeypatch, player):
    """A switch stops the reading in hand, and a stopped player is dropped —
    so starting the next chapter builds one. Hand it the same stand-in instead
    of a real pipeline."""
    monkeypatch.setattr(devotional_audio, 'Player', lambda: player)
    return player


def test_the_switch_starts_the_chapter_on_screen(monkeypatch):
    _runner(monkeypatch)
    _settings(monkeypatch)
    player = _reusable(monkeypatch, FakePlayer())
    c = _listening(monkeypatch, player=player)
    c._chapter = 4
    c._cached = '/tmp/John_004.mp3'
    c._sync_reading_audio()
    c._on_reading_switch()
    assert player.played[-1] == '/tmp/John_004.mp3'
    assert player.playing
    assert c._pill.reference == 'John 4'
    assert c._pill.switch == ''                  # the two are one again


def test_the_switch_abandons_a_fetch_it_replaces(monkeypatch):
    """Pressed while the chapter in hand is still on its way: that fetch is
    six megabytes of a reading the reader has just said they do not want."""
    runner = _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch,                         # nothing cached
                player=_reusable(monkeypatch, FakePlayer()))
    c._sync_reading_audio()
    c._on_reading_listen(None)
    c._on_reading_play()
    c._chapter = 4
    c._sync_reading_audio()
    assert c._pill.switch == 'John 4'
    c._on_reading_switch()
    assert c._reading_key in runner.cancelled
    assert c._pill.state == 'fetching'               # now for John 4
    runner.apply('/tmp/John_004.mp3')
    assert c._sounding == ('/tmp/John_004.mp3', 'John 4')


def test_the_pill_names_the_chapter_being_fetched(monkeypatch):
    """Not the one that came on screen while the reader waited. The controls
    beside the name belong to the fetch, so the name has to as well."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch, player=FakePlayer())
    c._sync_reading_audio()
    c._on_reading_listen(None)
    c._on_reading_play()
    c._chapter = 4
    c._sync_reading_audio()
    assert c._pill.reference == 'John 3'


def test_a_stopped_fetch_leaves_the_chapter_on_screen_named(monkeypatch):
    """Once the fetch is abandoned the pill governs nothing, so it goes back
    to naming what the reader is looking at — with nothing on offer."""
    _runner(monkeypatch)
    _settings(monkeypatch)
    c = _paging(monkeypatch, player=FakePlayer())
    c._sync_reading_audio()
    c._on_reading_listen(None)
    c._on_reading_play()
    c._chapter = 4
    c._sync_reading_audio()
    c._on_reading_play()                             # stop the fetch
    assert c._pill.reference == 'John 4'
    assert c._pill.switch == ''


def test_turning_spoken_readings_off_silences_a_reading(monkeypatch):
    """Paging on is not a request for silence; this is. It also puts the pill
    away, which it may only do because it has stopped the reading first."""
    _runner(monkeypatch)
    store = _settings(monkeypatch)
    player = FakePlayer()
    c = _listening(monkeypatch, player=player)
    store['show_audio'] = False
    c._sync_reading_audio()
    assert not player.playing
    assert c._sounding is None
    assert not c._pill.visible


# ── Speed ────────────────────────────────────────────────────────────────────

def _settings(monkeypatch, rate=1.0, show_audio=True):
    """Never the real settings file — the stored rate is faked in memory."""
    store = {'reading_rate': rate, 'show_audio': show_audio}
    monkeypatch.setattr(settings, 'get', lambda key: store.get(key))
    monkeypatch.setattr(settings, 'put',
                        lambda key, value: store.__setitem__(key, value))
    return store


def test_choosing_a_speed_reaches_the_player_and_is_remembered(monkeypatch):
    _runner(monkeypatch)
    store = _settings(monkeypatch)
    player = FakePlayer()
    c = Reading(player=player)
    c._on_reading_rate(1.5)
    assert player.rate == 1.5
    assert store['reading_rate'] == 1.5
    assert c._pill.rate == 1.5              # and the pill says so


def test_a_speed_chosen_with_nothing_playing_is_still_remembered(monkeypatch):
    _runner(monkeypatch)
    store = _settings(monkeypatch)
    c = Reading()                            # no player yet
    c._on_reading_rate(0.75)                 # must not raise
    assert store['reading_rate'] == 0.75


def test_every_reading_starts_at_the_stored_speed(monkeypatch):
    """A fresh pipeline plays at 1.0, so the chosen speed has to be asked for
    again on every chapter."""
    _runner(monkeypatch)
    _settings(monkeypatch, rate=1.25)
    player = FakePlayer()
    c = Reading(player=player)
    c._finish_reading_fetch('/tmp/Gen_001.mp3')
    assert player.rate == 1.25


def test_the_offered_speeds_and_how_they_are_written():
    from audio_pill import RATES, format_rate
    assert RATES[:2] == (0.75, 1.0) and RATES[-1] == 2.0
    assert format_rate(1.0) == '1\u00d7'          # not "1.0x"
    assert format_rate(1.25) == '1.25\u00d7'
    assert format_rate(1.5) == '1.5\u00d7'        # no trailing zero


# ── The pill itself ──────────────────────────────────────────────────────────
# Real widgets, and these do need a display — the rest of this file does not.
# `Adw.init()` alone is not enough and does not say so: it returns perfectly
# well with no display, and then building the pill's own buttons segfaults
# inside GTK on the Gtk.Box constructor. Nor does Gtk.init_check() catch it,
# which answers True either way. A display either exists or it does not, and
# Gdk.Display.get_default() is the one call that reports which.

def _real_pill(on_switch=None):
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    from audio_pill import AudioPill
    return AudioPill(on_play_pause=lambda: None, on_back=lambda: None,
                     on_close=lambda: None, on_rate=lambda _r: None,
                     on_switch=on_switch)


def test_pausing_does_not_wipe_the_position_off_the_thread():
    """It did: leaving any state stopped the pulse, and stopping the pulse
    zeroed the bar, so pressing pause dropped the thread to nothing until the
    next tick put it back."""
    pill = _real_pill()
    pill.set_state('playing')
    pill.set_progress(0.4)
    pill.set_state('idle')                  # pause
    assert pill._thread.get_fraction() == 0.4


def test_a_finished_fetch_does_clear_the_thread():
    """The other half of the same rule: a pulsing bar holds no fraction, so
    leaving a fetch has to put it back to zero."""
    pill = _real_pill()
    pill.set_state('fetching')
    pill.set_state('idle')
    assert pill._thread.get_fraction() == 0.0


def test_reopening_while_it_is_still_leaving_is_not_swallowed():
    """get_visible() stays true through the 150ms leaving animation, so asking
    the widget whether it was up lost a press made during it."""
    pill = _real_pill()
    pill.present()
    pill.dismiss()
    pill.present()                          # pressed before the fade finished
    assert pill.is_shown()


def test_the_switch_is_absent_until_there_are_two_readings_to_tell_apart():
    """The sixth slot exists in one state only, and the pill starts outside
    it: five controls, and a name for what is sounding."""
    pill = _real_pill(on_switch=lambda: None)
    assert not pill._switch_btn.get_visible()
    pill.set_switch('John 4')
    assert pill._switch_btn.get_visible()
    assert pill._switch_content.get_label() == 'John 4'
    pill.set_switch('')                     # the reader comes back to it
    assert not pill._switch_btn.get_visible()


def test_the_switch_says_which_chapter_it_would_start():
    """To a screen reader as well as in the tooltip: "John 4" alone is a
    label that could as easily mean the one being read."""
    pill = _real_pill(on_switch=lambda: None)
    pill.set_switch('John 4')
    assert 'John 4' in pill._switch_btn.get_tooltip_text()
    assert 'instead' in pill._switch_btn.get_tooltip_text()


def test_a_pill_with_nowhere_to_switch_never_shows_the_control():
    """The pane always wires it, but the pill is built to stand without one —
    a control whose press goes nowhere must not be offered."""
    pill = _real_pill()
    pill.set_switch('John 4')
    assert not pill._switch_btn.get_visible()


def test_an_edited_setting_cannot_ask_for_an_absurd_speed():
    from audio_pill import sane_rate
    assert sane_rate(1.5) == 1.5
    assert sane_rate(6.0) == 1.0
    assert sane_rate(0) == 1.0


# ── What reaches the desktop's media bus ─────────────────────────────────────

def test_a_sounding_chapter_reaches_the_desktop(monkeypatch, bus):
    """The reading the pill holds is the reading the lock screen names."""
    c = Reading(cached='/tmp/Gen_001.mp3', player=FakePlayer())
    _runner(monkeypatch)
    c._on_reading_play()
    assert len(bus.published) == 1
    assert bus.published[0].title == 'John 3'
    assert bus.published[0].artist == bible_audio.TRANSLATION


def test_a_psalm_episode_names_its_own_series(monkeypatch, bus):
    """Not every reading the pill carries is a chapter of the Bible."""
    c = Reading(cached='/tmp/psalm.mp3', player=FakePlayer())
    c._reading_scripture = False
    _runner(monkeypatch)
    c._on_reading_play()
    assert bus.published[0].artist == devotional_audio.PSALMS_SERIES


def test_a_resume_is_the_same_track_not_a_new_one(monkeypatch, bus):
    """Republishing would tell every remote a new reading had begun, and
    restart the desktop's idea of the track."""
    player = FakePlayer()
    c = Reading(cached='/tmp/Gen_001.mp3', player=player)
    _runner(monkeypatch)
    c._on_reading_play()
    c._on_reading_play()                    # pause
    c._on_reading_play()                    # resume
    assert len(bus.published) == 1
    assert bus.updated                      # but the desktop was told


def test_stopping_takes_the_reading_off_the_bus(monkeypatch, bus):
    c = Reading(cached='/tmp/Gen_001.mp3', player=FakePlayer())
    _runner(monkeypatch)
    c._on_reading_play()
    published = bus.published[0]
    c._stop_reading_audio()
    assert bus.withdrawn == [published]
    assert bus.current is None


def test_the_desktops_pause_leaves_the_pill_showing_paused(monkeypatch, bus):
    """The bus acts through the pill's own handlers, so the two can never
    disagree about what is happening."""
    c = Reading(cached='/tmp/Gen_001.mp3', player=FakePlayer())
    _runner(monkeypatch)
    c._on_reading_play()
    bus.published[0].on_pause()
    assert c._pill.state == 'idle'


def test_the_desktops_stop_puts_the_player_away(monkeypatch, bus):
    """Stop means stop: the pill carries the only controls there are, so
    silencing a reading while leaving it up would strand them."""
    c = Reading(cached='/tmp/Gen_001.mp3', player=FakePlayer())
    _runner(monkeypatch)
    c._on_reading_play()
    bus.published[0].on_stop()
    assert c._sounding is None
    assert not c._pill.visible


def test_a_speed_set_from_a_remote_is_the_speed_the_pill_shows(monkeypatch,
                                                               bus):
    monkeypatch.setattr(settings, 'put', lambda *_a: None)
    player = FakePlayer()
    c = Reading(cached='/tmp/Gen_001.mp3', player=player)
    _runner(monkeypatch)
    c._on_reading_play()
    bus.published[0].on_rate(1.5)
    assert c._pill.rate == 1.5
    assert player.rate == 1.5


def test_the_devotional_row_reaches_the_desktop_too(monkeypatch, bus):
    c = _devotional(monkeypatch, cached='/tmp/me.mp3', player=FakePlayer())
    c._on_devot_play(None)
    assert bus.published[0].artist == devotional_audio.MORNING_EVENING_SERIES
    c._stop_devotional_audio()
    assert bus.current is None


def test_the_today_disc_reaches_the_desktop_too(monkeypatch, bus):
    c = _today(monkeypatch, cached='/tmp/today.mp3', player=FakePlayer())
    c._on_today_listen()
    assert bus.published[0].title == 'A Daily Strength'
    assert bus.published[0].artist == devotional_audio.DAILY_STRENGTH_SERIES
    c._stop_today_listen()
    assert bus.current is None

# ── The wiring, in a real widget tree ────────────────────────────────────────
# The tests above stub every widget, which is what makes them fast and what
# lets them assert behaviour. What they cannot see is whether the surfaces are
# actually PLUGGED IN: BACKLOG item 24b moved both of them out of BiblePane,
# and the whole risk of that move sits in the handful of places the pane still
# has to hand them a parent. A stub answers every append() happily.

def _real_tree():
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()


class StubPane:
    """Only what the surfaces read back off the pane."""

    def __init__(self):
        self._module, self._book, self._chapter = 'BSB', 'John', 3
        self._devotional_date = None
        self._on_toast = None

    def _is_verse_navigable(self):
        return True


def test_the_headphones_are_built_into_the_toolbar_it_is_given():
    _real_tree()
    from gi.repository import Gtk
    toolbar = Gtk.Box()
    audio = ReadingAudio(StubPane(), toolbar)
    assert toolbar.get_first_child() is audio._reading_audio
    # Offered only when there is something behind it — the same rule the
    # stubbed tests assert, here against the real widget.
    assert not audio._reading_audio.get_visible()


def test_the_pill_is_reachable_for_the_overlay_and_the_paper():
    """The pane adds the pill to its chrome overlay and casts it in the
    reading paper. Both go through `.pill`, so it has to be a real one."""
    _real_tree()
    from gi.repository import Gtk
    audio = ReadingAudio(StubPane(), Gtk.Box())
    assert audio.pill is audio._pill
    Gtk.Overlay().add_overlay(audio.pill)      # what the pane does with it
    audio.pill.set_appearance('#f7f4ee', '#1a1a1a')


def test_the_devotional_controls_are_built_into_the_row_it_is_given():
    _real_tree()
    from gi.repository import Gtk
    row = Gtk.Box()
    devot = DevotionalAudio(StubPane())
    devot.build(row)
    assert row.get_first_child() is devot._devot_audio_row
    assert not devot._devot_audio_row.get_visible()
    # The hairline is placed by the PANE, under the row rather than in it, so
    # it must be reachable and unparented when build() returns.
    assert devot.progress.get_parent() is None
    Gtk.Box().append(devot.progress)
