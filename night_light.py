"""Evening paper: follow GNOME Night Light and warm/dim the reading surface.

Opt-in (Appearance ▸ Advanced, off by default). The desktop already warms
the whole screen when Night Light engages; what this adds is the paper
itself softening in step — a bright white page stops glaring through the
warm cast and reads like paper under lamplight. Tone only: the shift rides
the same CSS path as picking a paper swatch, so the reading text never
moves (GUIDANCE §2.1).

The trigger is the desktop's own rhythm (org.gnome.SettingsDaemon.Color:
NightLightActive + Temperature), not a second clock of ours — the user's
schedule, the user's dusk. Where the interface doesn't exist (non-GNOME,
sandbox without the talk-name) the monitor stays silently inert. The
Flatpak manifest must carry --talk-name=org.gnome.SettingsDaemon.Color.

Blend math is pure and unit-tested; the D-Bus monitor is a thin shell.
"""

from __future__ import annotations

from typing import Callable

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib

# Night Light's neutral point and the temperature at which the paper shift
# saturates. GNOME's default night temperature is 2700K, so most users reach
# full strength; a gentle 4500K+ setting yields a proportionally gentle page.
_NEUTRAL_K = 6500
_FULL_K = 3500

# Channel scaling at full strength: mostly a blue/green reduction (lamplight
# warmth) plus a slight dim on light papers so white pages stop glaring.
# Starting values — tuned by eye, not physics.
_GREEN_DROP = 0.06
_BLUE_DROP = 0.15
_LIGHT_DIM = 0.05

_BUS_NAME = 'org.gnome.SettingsDaemon.Color'
_OBJECT_PATH = '/org/gnome/SettingsDaemon/Color'


def strength_for_temperature(temperature_k: int) -> float:
    """Map a Night Light temperature to a 0..1 shift strength.
    6500K (neutral) → 0; 3500K or warmer → 1; linear between."""
    span = _NEUTRAL_K - _FULL_K
    return min(1.0, max(0.0, (_NEUTRAL_K - temperature_k) / span))


def dusk_blend(paper_hex: str, strength: float) -> str:
    """Shift a paper colour toward its lamplight variant. Works for any
    paper — presets, customs, dark papers — because it scales the paper's
    own channels rather than blending toward a fixed target."""
    if strength <= 0.0:
        return paper_hex
    s = min(1.0, strength)
    r = float(int(paper_hex[1:3], 16))
    g = float(int(paper_hex[3:5], 16))
    b = float(int(paper_hex[5:7], 16))
    g *= 1.0 - _GREEN_DROP * s
    b *= 1.0 - _BLUE_DROP * s
    # Light papers additionally dim a touch; dark papers are already dim.
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if lum > 0.5:
        dim = 1.0 - _LIGHT_DIM * s
        r, g, b = r * dim, g * dim, b * dim
    return '#{:02x}{:02x}{:02x}'.format(
        *(min(255, max(0, round(v))) for v in (r, g, b)))


class NightLightMonitor:
    """Watches Night Light and reports the paper-shift strength.

    Calls `on_strength(s: float)` with 0.0 while night light is off (or the
    interface is unavailable) and strength_for_temperature(T) while active —
    including live updates as the temperature ramps through dusk. `stop()`
    disconnects; the owner is responsible for restoring the neutral paper.
    """

    def __init__(self, on_strength: Callable[[float], None]) -> None:
        self._on_strength = on_strength
        self._proxy: Gio.DBusProxy | None = None
        self._changed_id = 0
        self._stopped = False
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
            _BUS_NAME, _OBJECT_PATH, _BUS_NAME, None, self._on_ready)

    def _on_ready(self, _source: object, result: Gio.AsyncResult) -> None:
        try:
            proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            return                      # not GNOME / no permission: stay inert
        if self._stopped:
            return
        self._proxy = proxy
        self._changed_id = proxy.connect(
            'g-properties-changed', self._on_props_changed)
        self._emit()

    def _on_props_changed(self, _proxy: Gio.DBusProxy,
                          _changed: GLib.Variant,
                          _invalidated: list[str]) -> None:
        self._emit()

    def _emit(self) -> None:
        assert self._proxy is not None
        active = self._proxy.get_cached_property('NightLightActive')
        temp = self._proxy.get_cached_property('Temperature')
        if active is not None and active.unpack() and temp is not None:
            s = strength_for_temperature(int(temp.unpack()))
        else:
            s = 0.0
        self._on_strength(s)

    def stop(self) -> None:
        self._stopped = True
        if self._proxy is not None and self._changed_id:
            self._proxy.disconnect(self._changed_id)
            self._changed_id = 0
        self._proxy = None
