"""What the desktop sees of a reading, and what a remote can do to it.

The bus is exercised without one: `_Bus` is built and asked the same
questions D-Bus would ask, so the interface can be tested on a machine with
no session bus at all (CI). That the wiring reaches a REAL bus is a different
claim, and `tools/verify-today.py` makes it against the running app.
"""
from gi.repository import GLib

import mpris


class FakePlayer:
    def __init__(self, playing=True):
        self.playing = playing
        self.rate = 1.0
        self.volume = 1.0
        self.seeks = []
        self.positions = []

    def duration(self):
        return 273.0

    def position(self):
        return 12.0

    def seek_relative(self, seconds):
        self.seeks.append(seconds)
        return True

    def seek_to(self, seconds):
        self.positions.append(seconds)
        return True


class FakeInvocation:
    def __init__(self):
        self.returned = 0

    def return_value(self, _value):
        self.returned += 1


def _reading(player=None, **kwargs):
    calls = []
    player = FakePlayer() if player is None else player
    reading = mpris.Reading(
        'John 3', 'Berean Standard Bible', player=player,
        on_play=lambda: calls.append('play'),
        on_pause=lambda: calls.append('pause'),
        on_stop=lambda: calls.append('stop'), **kwargs)
    return reading, calls


def _bus(reading=None):
    bus = mpris._Bus()
    if reading is not None:
        bus.publish(reading)
    return bus


def _get(bus, prop, interface=mpris.PLAYER_IFACE):
    return bus._on_get(None, None, mpris.OBJECT_PATH, interface, prop)


def _call(bus, method, params=None):
    invocation = FakeInvocation()
    bus._on_call(None, None, mpris.OBJECT_PATH, mpris.PLAYER_IFACE, method,
                 params, invocation)
    return invocation


# ── What the desktop is told ─────────────────────────────────────────────────

def test_the_bus_name_is_this_app_and_this_instance():
    """The app runs NON_UNIQUE, so two windows must not fight over one name."""
    assert mpris.BUS_NAME.startswith(
        'org.mpris.MediaPlayer2.io.github.andresmessina_SDG.Scriptura.instance')
    assert mpris.BUS_NAME.endswith(str(__import__('os').getpid()))


def test_nothing_playing_is_stopped_and_uncontrollable():
    bus = _bus()
    assert _get(bus, 'PlaybackStatus').get_string() == 'Stopped'
    assert not _get(bus, 'CanPlay').get_boolean()
    assert _get(bus, 'Metadata').unpack() == {}


def test_a_published_reading_is_named_and_timed():
    reading, _ = _reading()
    metadata = _get(_bus(reading), 'Metadata').unpack()
    assert metadata['xesam:title'] == 'John 3'
    assert metadata['xesam:artist'] == ['Berean Standard Bible']
    assert metadata['mpris:length'] == 273_000_000     # microseconds
    assert metadata['mpris:trackid'].startswith('/io/github/')


def test_a_paused_reading_says_paused_not_stopped():
    reading, _ = _reading(player=FakePlayer(playing=False))
    assert _get(_bus(reading), 'PlaybackStatus').get_string() == 'Paused'


def test_position_is_reported_in_microseconds():
    reading, _ = _reading()
    assert _get(_bus(reading), 'Position').get_int64() == 12_000_000


def test_the_app_never_offers_to_read_on():
    """A reading stops at the end of its chapter; turning the page under a
    reader is the app moving the text without being asked. So no desktop
    anywhere offers a control that would do it."""
    bus = _bus(_reading()[0])
    assert not _get(bus, 'CanGoNext').get_boolean()
    assert not _get(bus, 'CanGoPrevious').get_boolean()
    assert not _get(bus, 'HasTrackList', mpris.ROOT_IFACE).get_boolean()


def test_a_reading_with_no_speed_control_states_no_speed_range():
    """Only the pill paces a reading. A remote is told the truth about the
    other two rather than offered a slider that does nothing."""
    bus = _bus(_reading()[0])
    assert _get(bus, 'MinimumRate').get_double() == 1.0
    assert _get(bus, 'MaximumRate').get_double() == 1.0
    paced, _ = _reading(on_rate=lambda _r: None)
    assert _get(_bus(paced), 'MaximumRate').get_double() == mpris.MAX_RATE


def test_the_app_says_which_desktop_entry_it_is():
    """How the Shell finds the app's name and icon — there is no artUrl."""
    bus = _bus()
    assert _get(bus, 'Identity', mpris.ROOT_IFACE).get_string() == 'Scriptura'
    assert _get(bus, 'DesktopEntry',
                mpris.ROOT_IFACE).get_string() == mpris.APP_ID


# ── What a remote can do ─────────────────────────────────────────────────────

def test_play_and_pause_only_act_where_they_mean_something():
    """Both handlers may be one toggle — the pill's is — so the bus, not the
    surface, is what keeps a Pause from starting a paused reading."""
    reading, calls = _reading()
    bus = _bus(reading)
    _call(bus, 'Play')                      # already playing
    assert calls == []
    _call(bus, 'Pause')
    assert calls == ['pause']
    reading.player.playing = False
    _call(bus, 'Pause')                     # already paused
    assert calls == ['pause']
    _call(bus, 'Play')
    assert calls == ['pause', 'play']


def test_playpause_follows_whichever_state_it_is_in():
    reading, calls = _reading()
    bus = _bus(reading)
    _call(bus, 'PlayPause')
    assert calls == ['pause']
    reading.player.playing = False
    _call(bus, 'PlayPause')
    assert calls == ['pause', 'play']


def test_stop_reaches_the_surfaces_own_stop():
    reading, calls = _reading()
    _call(_bus(reading), 'Stop')
    assert calls == ['stop']


def test_seek_is_taken_as_the_offset_it_is():
    reading, _ = _reading()
    bus = _bus(reading)
    _call(bus, 'Seek', GLib.Variant('(x)', (-15_000_000,)))
    assert reading.player.seeks == [-15.0]
    _call(bus, 'SetPosition',
          GLib.Variant('(ox)', ('/io/github/x', 60_000_000)))
    assert reading.player.positions == [60.0]


def test_next_and_previous_are_answered_with_nothing():
    """Declared because the interface requires them; a remote that presses
    one gets a reply, not an error, and the reading carries on."""
    reading, calls = _reading()
    bus = _bus(reading)
    assert _call(bus, 'Next').returned == 1
    assert _call(bus, 'Previous').returned == 1
    assert calls == []


def test_a_speed_from_a_remote_snaps_to_one_the_app_offers():
    asked = []
    reading, _ = _reading(on_rate=asked.append)
    bus = _bus(reading)
    assert bus._on_set(None, None, mpris.OBJECT_PATH, mpris.PLAYER_IFACE,
                       'Rate', GLib.Variant('d', 1.37))
    assert asked == [1.25]


def test_a_speed_is_refused_where_the_surface_has_no_speed():
    reading, _ = _reading()
    bus = _bus(reading)
    assert not bus._on_set(None, None, mpris.OBJECT_PATH, mpris.PLAYER_IFACE,
                           'Rate', GLib.Variant('d', 1.5))


def test_volume_is_a_real_control_not_a_reported_number():
    """The pill carries no volume on the argument that volume belongs to the
    desktop. This is where that promise is kept."""
    reading, _ = _reading()
    bus = _bus(reading)
    assert bus._on_set(None, None, mpris.OBJECT_PATH, mpris.PLAYER_IFACE,
                       'Volume', GLib.Variant('d', 0.4))
    assert reading.player.volume == 0.4
    assert _get(bus, 'Volume').get_double() == 0.4


# ── Whose reading it is ──────────────────────────────────────────────────────

def test_the_last_reading_to_start_owns_the_bus():
    first, _ = _reading()
    second, _ = _reading()
    bus = _bus(first)
    bus.publish(second)
    assert bus.is_current(second)
    assert not bus.is_current(first)


def test_a_surface_cannot_take_a_reading_it_does_not_hold_off_the_bus():
    """Every stop path in the app is also a tidy-up path, reached whether
    that surface was playing or not."""
    playing, _ = _reading()
    other, _ = _reading()
    bus = _bus(playing)
    bus.withdraw(other)
    assert bus.is_current(playing)
    bus.withdraw(playing)
    assert _get(bus, 'PlaybackStatus').get_string() == 'Stopped'
