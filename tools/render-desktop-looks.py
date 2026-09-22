#!/usr/bin/env python3
"""Render the app as a non-GNOME desktop would draw it, and save PNGs.

Counting squeezed widgets was not enough: GNOME's own baseline squeezes 33
of them, because a GTK widget asking for more than it gets is ordinary.
The question "does it look right" is answered by looking.

Two desktop-supplied things change the drawing:
  * the chrome font — `data/style.css` asks for Adwaita Sans, then Inter,
    then whatever `sans-serif` resolves to. **Adwaita Sans is bundled since
    2026-09-19** (data/fonts), so the fallbacks are no longer reachable on
    an installed app; forcing them here is now a regression guard, showing
    what the chrome would look like if that bundling were ever dropped.
  * `gtk-decoration-layout` — GNOME hands a headerbar one close button,
    KDE hands it an icon plus minimise, maximise and close. This half is
    live: it is the desktop's setting, not ours.

Runs each under `mutter --headless`, which maps and lays out the window
for real (Broadway does not), and writes one PNG per combination.

Usage:  python3 tools/render-desktop-looks.py [OUTDIR]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WAYLAND = 'scriptura-look-0'

COMBOS = [
    # tag,            chrome font,     decoration layout
    ('gnome',        'Adwaita Sans',  ':close'),
    ('kde',          'Noto Sans',     'icon:minimize,maximize,close'),
    ('kde-debian',   'DejaVu Sans',   'icon:minimize,maximize,close'),
]
WIDTHS = (1280, 900)

# The Today page is typography on bundled faces and barely moves. The
# surfaces that can actually break are the chrome-dense ones: the reading
# pane's toolbar, the search panel, and the lexicon panel's concordance —
# every label in them is set in the face this probe is varying.
SCENES = ('today', 'reading', 'search', 'concordance')


def run(outdir: Path, timeout: float = 600.0) -> int:
    with tempfile.TemporaryDirectory(prefix='scriptura-look-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({'open_to_today': True}))
        env['WAYLAND_DISPLAY'] = WAYLAND
        env['GDK_BACKEND'] = 'wayland'
        env['SCRIPTURA_LOOK_OUT'] = str(outdir)
        env.pop('DISPLAY', None)
        mutter = subprocess.Popen(
            ['mutter', '--headless', '--wayland',
             f'--wayland-display={WAYLAND}',
             '--virtual-monitor', '1920x1200'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            sock = Path(env['XDG_RUNTIME_DIR'], WAYLAND)
            deadline = time.monotonic() + 15.0
            while not sock.exists():
                if mutter.poll() is not None or time.monotonic() > deadline:
                    print('mutter --headless would not start', file=sys.stderr)
                    return 2
                time.sleep(0.1)
            time.sleep(1.0)
            proc = subprocess.run([sys.executable, __file__, '--driver'],
                                  env=env, cwd=REPO_ROOT, timeout=timeout,
                                  stdout=subprocess.PIPE, text=True)
            sys.stdout.write(proc.stdout)
            return proc.returncode
        finally:
            mutter.terminate()
            mutter.wait()


def driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    gi.require_version('Gsk', '4.0')
    from gi.repository import Gtk, Gdk, Gsk, GLib, Graphene

    import main

    outdir = Path(os.environ['SCRIPTURA_LOOK_OUT'])
    outdir.mkdir(parents=True, exist_ok=True)

    app = main.BibleApp()
    state: dict = {}
    written: list[str] = []
    steps: list = []

    def step(fn):
        steps.append(fn)
        return fn

    def shoot(win, name):
        """Rasterise the live window. `Gtk.WidgetPaintable` + a Cairo
        renderer, because the window is really mapped here."""
        w, h = win.get_width(), win.get_height()
        if w <= 0 or h <= 0:
            return f'{name}: window not allocated'
        paintable = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        if node is None:
            return f'{name}: snapshot gave no node'
        renderer = Gsk.CairoRenderer()
        renderer.realize(None)
        tex = renderer.render_texture(
            node, Graphene.Rect().init(0, 0, w, h))
        path = outdir / f'{name}.png'
        tex.save_to_png(str(path))
        renderer.unrealize()
        written.append(f'{path} {w}x{h}')
        return None

    @step
    def prepare(win):
        state['provider'] = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), state['provider'],
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)

    def stage(win, scene):
        """Put the window on the surface this shot is about."""
        import content
        if scene == 'today':
            return
        win._dismiss_today(animate=False)
        tagged = [m for m in content.text_bible_names()
                  if content.has_strongs(m)]
        module = 'KJV' if 'KJV' in tagged else (tagged or ['KJV'])[0]
        win.pane1._apply_module_change(module)
        win.pane1.load_reference_at_verse('1 John', 4, 8)
        if scene == 'search':
            win._search_for('strong:G26')
        elif scene == 'concordance':
            lex = win.pane1._lex_panel
            lex.set_context('1 John', module)
            lex.show('G26', 'love', morph='')

    def unstage(win, scene):
        if scene == 'search':
            win._hide_search()

    def make(tag, font, layout, width, scene):
        @step
        def apply(win, tag=tag, font=font, layout=layout, width=width,
                  scene=scene):
            state['provider'].load_from_string(
                'window { font-family: "%s"; }' % font)
            Gtk.Settings.get_default().set_property(
                'gtk-decoration-layout', layout)
            win.set_default_size(width, 860)
            state['name'] = f'{scene}-{tag}-{width}'
            state['scene'] = scene
            stage(win, scene)

        @step
        def settle_a(win):
            pass

        @step
        def settle_b(win):
            pass

        @step
        def settle_c(win):
            pass

        @step
        def settle_d(win):
            pass

        @step
        def shot(win):
            err = shoot(win, state['name'])
            if err:
                written.append('ERROR ' + err)
            unstage(win, state['scene'])

    for scene in SCENES:
        for tag, font, layout in COMBOS[:2]:
            for width in (WIDTHS if scene in ('today', 'reading')
                          else (1280,)):
                make(tag, font, layout, width, scene)

    def run_next(win):
        if not steps:
            app.quit()
            return GLib.SOURCE_REMOVE
        fn = steps.pop(0)
        try:
            fn(win)
        except Exception as exc:
            written.append(f'ERROR {fn.__name__}: {exc!r}')
        return GLib.SOURCE_CONTINUE

    def on_activate(_a):
        win = app.get_active_window()
        GLib.timeout_add(500, lambda: run_next(win))

    app.connect('activate', on_activate)
    GLib.timeout_add_seconds(420, lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])
    for line in written:
        print(line)
    return 1 if any(x.startswith('ERROR') for x in written) else 0


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(driver())
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('desktop-looks')
    sys.exit(run(target.resolve()))
