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

import devotional_audio
import motion
import settings
import tasks
from pane import BiblePane
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

    def play(self, _path):
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

    _on_reading_play = BiblePane._on_reading_play
    _on_reading_listen = BiblePane._on_reading_listen
    _on_reading_close = BiblePane._on_reading_close
    _on_reading_back = BiblePane._on_reading_back
    _on_reading_rate = BiblePane._on_reading_rate
    _begin_reading_fetch = BiblePane._begin_reading_fetch
    _end_reading_fetch = BiblePane._end_reading_fetch
    _show_reading_length = BiblePane._show_reading_length
    _finish_reading_fetch = BiblePane._finish_reading_fetch
    _report_audio_failure = BiblePane._report_audio_failure
    _start_reading_audio = BiblePane._start_reading_audio
    _stop_reading_audio = BiblePane._stop_reading_audio
    _on_reading_tick = BiblePane._on_reading_tick

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

    _on_devot_play = BiblePane._on_devot_play
    _begin_devot_fetch = BiblePane._begin_devot_fetch
    _clear_devot_band = BiblePane._clear_devot_band
    _end_devot_fetch = BiblePane._end_devot_fetch
    _finish_devot_fetch = BiblePane._finish_devot_fetch
    _report_audio_failure = BiblePane._report_audio_failure
    _start_devotional_audio = BiblePane._start_devotional_audio
    _stop_devotional_audio = BiblePane._stop_devotional_audio
    _on_devotional_audio_tick = BiblePane._on_devotional_audio_tick

    def __init__(self, player=None, delay_ms=motion.SPINNER_DELAY_MS):
        from gtk_utils import DelayedPulse
        self._devot_play_btn = FakeButton()
        self._devot_progress = FakeBar()
        self._devot_audio_row = object()
        self._devot_player = player
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

    def __init__(self, player=None):
        self._today_view = FakeTodayView()
        self._today_listen = ('https://example.invalid/today.mp3',
                              'A Daily Strength')
        self._today_player = player
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


# ── Speed ────────────────────────────────────────────────────────────────────

def _settings(monkeypatch, rate=1.0):
    """Never the real settings file — the stored rate is faked in memory."""
    store = {'reading_rate': rate}
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

def _real_pill():
    import gi
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk
    if Gdk.Display.get_default() is None:
        pytest.skip('needs a display: building real GTK widgets without one '
                    'segfaults rather than failing')
    Adw.init()
    from audio_pill import AudioPill
    return AudioPill(on_play_pause=lambda: None, on_back=lambda: None,
                     on_close=lambda: None, on_rate=lambda _r: None)


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


def test_an_edited_setting_cannot_ask_for_an_absurd_speed():
    from audio_pill import sane_rate
    assert sane_rate(1.5) == 1.5
    assert sane_rate(6.0) == 1.0
    assert sane_rate(0) == 1.0
