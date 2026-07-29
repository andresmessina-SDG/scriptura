"""The desktop's media bus, for whatever the app is reading aloud.

Three surfaces play spoken audio — the listening pill over a chapter, the
pane's Spurgeon row, and the Today page's devotional disc — and all three
drive the same `devotional_audio.Player`. This publishes whichever of them is
sounding on `org.mpris.MediaPlayer2`, so the media keys, the lock screen and
the Shell's own media control act on it.

That is also why the pill holds five slots and no more: volume and remote
control belong on the desktop's media bus rather than on a reading surface.
The promise is kept here — Volume is a real control on the pipeline, not a
property reported at 1.0 and ignored.

Two things this deliberately does not offer, because the app has already
ruled them:

* **No Next / Previous.** A reading stops at the end of its chapter and does
  not read on; turning the page under a reader is the app moving the text
  without being asked. `CanGoNext` and `CanGoPrevious` are false, so nothing
  on the desktop offers a control that would do it.
* **No track list.** The pane is the chapter list.

Measured rather than assumed (2026-07-27, inside the installed Flatpak): the
sandbox grants an app its own `org.mpris.MediaPlayer2.<app-id>` name with no
`--own-name` in finish-args, in both the plain and the `.instance<pid>` form.
No manifest permission was needed and none was added. The instance form is the
one used, because the app runs NON_UNIQUE and two windows must not fight over
one name.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from gi.repository import Gio, GLib

APP_ID = 'io.github.andresmessina_SDG.Scriptura'

BUS_NAME = f'org.mpris.MediaPlayer2.{APP_ID}.instance{os.getpid()}'

OBJECT_PATH = '/org/mpris/MediaPlayer2'

ROOT_IFACE = 'org.mpris.MediaPlayer2'
PLAYER_IFACE = 'org.mpris.MediaPlayer2.Player'

#: The speed range the pill offers. Stated so a remote knows the reading can
#: be paced at all; only the pill actually passes a handler for it.
MIN_RATE = 0.75
MAX_RATE = 2.0

_XML = f"""
<node>
  <interface name="{ROOT_IFACE}">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="{PLAYER_IFACE}">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" name="Offset" type="x"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri">
      <arg direction="in" name="Uri" type="s"/>
    </method>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Metadata" type="a{{sv}}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


class Reading:
    """One spoken reading, as the desktop sees it.

    The surface hands over what it is playing and how to act on it; nothing
    is read back. `player` answers where the reading has got to and how long
    it runs, and the handlers are the surface's own controls, so a press on
    the lock screen leaves the pill (or the disc, or the row) showing exactly
    what a press on it would have.

    `on_play` and `on_pause` may be the same toggle — the bus only calls one
    of them, and only when the player is in the state that makes it mean
    something.
    """

    def __init__(self, title: str, artist: str = '', *, player: Any,
                 on_play: Callable[[], object],
                 on_pause: Callable[[], object],
                 on_stop: Callable[[], object],
                 on_rate: Callable[[float], object] | None = None) -> None:
        self.title = title
        self.artist = artist
        self.player = player
        self.on_play = on_play
        self.on_pause = on_pause
        self.on_stop = on_stop
        self.on_rate = on_rate

    @property
    def playing(self) -> bool:
        return bool(self.player is not None and self.player.playing)


class _Bus:
    """The exported object. One per process, built the first time something
    is actually published — a reader who never presses play never touches the
    session bus at all."""

    def __init__(self) -> None:
        self._connection: Gio.DBusConnection | None = None
        self._registrations: list[int] = []
        self._name_id = 0
        self._reading: Reading | None = None
        self._track = 0

    def start(self) -> bool:
        """Own the name and export the object. False if the bus cannot be
        reached, which is not an error worth showing anyone: the app plays
        just as well with no desktop listening."""
        if self._connection is not None:
            return True
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(_XML)
            for interface in node.interfaces:
                self._registrations.append(connection.register_object(
                    OBJECT_PATH, interface, self._on_call, self._on_get,
                    self._on_set))
            self._name_id = Gio.bus_own_name_on_connection(
                connection, BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
        except Exception:
            return False
        self._connection = connection
        return True

    # ── What the surfaces say ────────────────────────────────────────────
    def publish(self, reading: Reading) -> None:
        self._reading = reading
        self._track += 1
        self.changed()

    def withdraw(self, reading: Reading) -> None:
        """Only the reading that is on the bus may take it off. A pane that
        stops a player it never published — and every stop path is reached on
        tidy-up whether anything was playing or not — must not silence the
        surface that actually holds the bus."""
        if self._reading is reading:
            self._reading = None
            self.changed()

    def is_current(self, reading: Reading | None) -> bool:
        return self._reading is reading

    def changed(self) -> None:
        """Restate what the desktop shows. Everything here is answered from
        the player on demand, so this only has to say *that* it changed."""
        if self._connection is None:
            return
        properties = {
            'PlaybackStatus': GLib.Variant('s', self._status()),
            'Metadata': self._metadata(),
            'CanPlay': GLib.Variant('b', self._reading is not None),
            'CanPause': GLib.Variant('b', self._reading is not None),
            'CanSeek': GLib.Variant('b', self._reading is not None),
            'Rate': GLib.Variant('d', self._rate()),
        }
        try:
            self._connection.emit_signal(
                None, OBJECT_PATH, 'org.freedesktop.DBus.Properties',
                'PropertiesChanged',
                GLib.Variant('(sa{sv}as)',
                             (PLAYER_IFACE, properties, [])))
        except Exception:
            pass

    # ── What the desktop asks ────────────────────────────────────────────
    def _status(self) -> str:
        if self._reading is None:
            return 'Stopped'
        return 'Playing' if self._reading.playing else 'Paused'

    def _rate(self) -> float:
        reading = self._reading
        player = reading.player if reading is not None else None
        return float(getattr(player, 'rate', 1.0) or 1.0)

    def _metadata(self) -> GLib.Variant:
        reading = self._reading
        if reading is None:
            return GLib.Variant('a{sv}', {})
        fields = {
            'mpris:trackid': GLib.Variant(
                'o', f'/io/github/andresmessina_SDG/Scriptura/track/'
                     f'{self._track}'),
            'xesam:title': GLib.Variant('s', reading.title or ''),
        }
        if reading.artist:
            fields['xesam:artist'] = GLib.Variant('as', [reading.artist])
        length = (reading.player.duration()
                  if reading.player is not None else None)
        if length:
            fields['mpris:length'] = GLib.Variant('x', int(length * 1e6))
        return GLib.Variant('a{sv}', fields)

    def _on_call(self, _connection: Gio.DBusConnection, _sender: str,
                 _path: str, interface: str, method: str,
                 params: GLib.Variant, invocation: Any) -> None:
        reading = self._reading
        if interface == ROOT_IFACE:
            if method == 'Raise':
                _raise_window()
            elif method == 'Quit':
                _quit()
            invocation.return_value(None)
            return
        if method == 'PlayPause' and reading is not None:
            (reading.on_pause if reading.playing else reading.on_play)()
        elif method == 'Play' and reading is not None and not reading.playing:
            reading.on_play()
        elif method == 'Pause' and reading is not None and reading.playing:
            reading.on_pause()
        elif method == 'Stop' and reading is not None:
            reading.on_stop()
        elif method == 'Seek' and reading is not None:
            if reading.player is not None:
                reading.player.seek_relative(params.unpack()[0] / 1e6)
        elif method == 'SetPosition' and reading is not None:
            if reading.player is not None:
                reading.player.seek_to(params.unpack()[1] / 1e6)
        # Next, Previous and OpenUri are declared because the interface
        # requires them and answered with nothing because this player has
        # neither a queue nor a way to be handed a file.
        invocation.return_value(None)
        self.changed()

    def _on_get(self, _connection: Gio.DBusConnection, _sender: str,
                _path: str, interface: str,
                prop: str) -> GLib.Variant | None:
        if interface == ROOT_IFACE:
            return {
                'CanQuit': GLib.Variant('b', True),
                'CanRaise': GLib.Variant('b', True),
                'HasTrackList': GLib.Variant('b', False),
                # Not localised: it is the app's name, and it is what the
                # Shell shows beside the reading.
                'Identity': GLib.Variant('s', 'Scriptura'),
                'DesktopEntry': GLib.Variant('s', APP_ID),
                'SupportedUriSchemes': GLib.Variant('as', []),
                'SupportedMimeTypes': GLib.Variant('as', []),
            }.get(prop)
        reading = self._reading
        player = reading.player if reading is not None else None
        position = player.position() if player is not None else None
        return {
            'PlaybackStatus': GLib.Variant('s', self._status()),
            'Rate': GLib.Variant('d', self._rate()),
            'Metadata': self._metadata(),
            'Volume': GLib.Variant(
                'd', float(getattr(player, 'volume', 1.0))
                if player is not None else 1.0),
            'Position': GLib.Variant('x', int((position or 0.0) * 1e6)),
            'MinimumRate': GLib.Variant(
                'd', MIN_RATE if reading is not None
                and reading.on_rate else 1.0),
            'MaximumRate': GLib.Variant(
                'd', MAX_RATE if reading is not None
                and reading.on_rate else 1.0),
            'CanGoNext': GLib.Variant('b', False),
            'CanGoPrevious': GLib.Variant('b', False),
            'CanPlay': GLib.Variant('b', reading is not None),
            'CanPause': GLib.Variant('b', reading is not None),
            'CanSeek': GLib.Variant('b', reading is not None),
            'CanControl': GLib.Variant('b', True),
        }.get(prop)

    def _on_set(self, _connection: Gio.DBusConnection, _sender: str,
                _path: str, _interface: str, prop: str,
                value: GLib.Variant) -> bool:
        reading = self._reading
        if reading is None:
            return False
        if prop == 'Volume' and reading.player is not None:
            reading.player.volume = value.get_double()
            return True
        if prop == 'Rate' and reading.on_rate is not None:
            # Snapped to a speed the pill actually offers: the reading is a
            # voice, and 1.37× is not a pace anyone chose. Imported here
            # because the pill is a Gtk module and this one is not.
            from audio_pill import RATES
            wanted = value.get_double()
            reading.on_rate(min(RATES, key=lambda r: abs(r - wanted)))
            self.changed()
            return True
        return False


_bus: _Bus | None = None
_app: Any = None


def attach(app: Any) -> None:
    """Give Raise and Quit something to act on. Called once at startup; it
    opens no connection by itself."""
    global _app
    _app = app


def _raise_window() -> None:
    if _app is None:
        return
    window = _app.get_active_window()
    if window is not None:
        window.present()


def _quit() -> None:
    if _app is not None:
        _app.quit()


def publish(reading: Reading) -> None:
    """Put a reading on the bus, replacing whatever was there.

    One reading at a time, and the last to start owns it — which is what the
    desktop expects and what a reader who pressed play last means.
    """
    global _bus
    if _bus is None:
        _bus = _Bus()
        if not _bus.start():
            _bus = None
            return
    _bus.publish(reading)


def update(reading: Reading | None) -> None:
    """Restate a reading already on the bus — paused, resumed, or its length
    finally answerable."""
    if _bus is not None and _bus.is_current(reading):
        _bus.changed()


def withdraw(reading: Reading | None) -> None:
    """Take a reading off the bus. Silent if it was never on it — every stop
    path in the app is also a tidy-up path, reached whether that surface was
    playing or not."""
    if _bus is not None and reading is not None:
        _bus.withdraw(reading)
