"""Evening-paper blend math (night_light.py pure functions)."""

import re

import night_light


def test_strength_neutral_and_full():
    assert night_light.strength_for_temperature(6500) == 0.0
    assert night_light.strength_for_temperature(3500) == 1.0


def test_strength_clamps_both_ends():
    assert night_light.strength_for_temperature(2700) == 1.0
    assert night_light.strength_for_temperature(7000) == 0.0


def test_strength_midpoint_linear():
    assert abs(night_light.strength_for_temperature(5000) - 0.5) < 1e-9


def test_blend_zero_strength_is_identity():
    assert night_light.dusk_blend('#f7f4ee', 0.0) == '#f7f4ee'


def test_blend_warms_light_paper():
    out = night_light.dusk_blend('#f7f4ee', 1.0)
    assert re.fullmatch(r'#[0-9a-f]{6}', out)
    r, g, b = (int(out[i:i + 2], 16) for i in (1, 3, 5))
    orig_r, orig_g, orig_b = 0xf7, 0xf4, 0xee
    # Blue drops the most, green a little, red only by the light-paper dim.
    assert b < orig_b
    assert g < orig_g
    assert r <= orig_r
    assert (orig_b - b) > (orig_g - g) >= (orig_r - r)


def test_blend_dark_paper_stays_dark_and_valid():
    out = night_light.dusk_blend('#1e1e1e', 1.0)
    assert re.fullmatch(r'#[0-9a-f]{6}', out)
    r, g, b = (int(out[i:i + 2], 16) for i in (1, 3, 5))
    # No light-paper dim below the luminance gate: red is untouched.
    assert r == 0x1e
    assert b < 0x1e


def test_blend_monotonic_in_strength():
    blues = []
    for s in (0.25, 0.5, 0.75, 1.0):
        out = night_light.dusk_blend('#f7f4ee', s)
        blues.append(int(out[5:7], 16))
    assert blues == sorted(blues, reverse=True)


def test_blend_overdriven_strength_clamps():
    assert night_light.dusk_blend('#f7f4ee', 5.0) == \
        night_light.dusk_blend('#f7f4ee', 1.0)


# ── Whether the desktop has the interface at all ────────────────────────────

def _probe_answer(timeout_s=5):
    """Run night_light.probe to completion on a private main loop."""
    from gi.repository import GLib
    loop = GLib.MainLoop()
    out = {}

    def done(available):
        out['available'] = available
        loop.quit()

    night_light.probe(done)
    GLib.timeout_add_seconds(timeout_s, lambda: (loop.quit(), False)[1])
    loop.run()
    return out.get('available')


def test_an_absent_service_answers_no_rather_than_hanging(monkeypatch):
    """The switch in Appearance ▸ Advanced is built insensitive and waits on
    this answer. A desktop without Night Light — KDE, Xfce, a bare WM — has
    to reach the callback with False, because a probe that never calls back
    leaves the control disabled with a 'checking…' tooltip forever.

    `Gio.DBusProxy` constructs happily for a name nobody owns, which is why
    the probe tests `get_name_owner()` and not the construction.
    """
    monkeypatch.setattr(night_light, '_BUS_NAME', 'org.example.NoSuchService')
    monkeypatch.setattr(night_light, '_OBJECT_PATH',
                        '/org/example/NoSuchService')
    assert _probe_answer() is False


def test_the_probe_never_starts_a_service_to_answer_itself():
    """DO_NOT_AUTO_START: asking whether Night Light is there must not
    activate it. Without the flag the question spawns the answer."""
    import inspect
    src = inspect.getsource(night_light.probe)
    assert 'DO_NOT_AUTO_START' in src
