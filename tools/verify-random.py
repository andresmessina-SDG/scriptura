#!/usr/bin/env python3
"""Drive the real app at random and watch for what a fixed scenario misses.

verify-stress.py repeats the same 18 scenarios. This picks each action by a
seeded random choice, in English, Spanish and Russian, and between actions
watches for what none of the scenarios measure:

- idle CPU: the app goes quiet, then must stop using the processor (the 1.9.2
  picker bug sat at 99% for every release before it was found by chance)
- a stalled main loop
- memory that keeps growing
- any ERROR record, GLib CRITICAL, raised action or crash

It runs on a hidden Broadway display, with a scratch HOME holding a copy of
~/.sword and scratch XDG dirs under ~/.cache, so the real config is not touched.
The last actions before a failure are in the report, and --seed repeats a run's
choices.

Usage:  verify-random.py [--minutes 10] [--rounds 1] [--seed N] [--lang en,es,ru]
                         [--skip peek,menu] [--display 13] [--out DIR]

--skip leaves out the named actions, to find which one a crash needs.
--display picks the Broadway display, so two runs can go at once.
VERIFY_MEM_OUT=FILE writes, at each idle check, the process's memory, Python's
share of it and the live objects by type: what found the popover leaks.

Exit 0 = nothing found, 1 = something found, 2 = the environment is unusable.
"""
from __future__ import annotations

import faulthandler
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 13                # default; --display changes it
IDLE_CPU_LIMIT = 0.25       # share of one core while nothing should be happening
STALL_SECONDS = 5.0
RSS_GROWTH_LIMIT_MB = 300
QUIET_EVERY = 40            # actions between idle checks


def _rss_mb() -> float:
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) / 1024
    return 0.0


def driver(minutes: float, seed: int, lang: str, action_log: str,
           skip: frozenset = frozenset()) -> int:
    import logging
    import random
    import traceback
    faulthandler.enable()
    faulthandler.dump_traceback_later(int(minutes * 60 + 180), exit=True)
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, GLib

    # VERIFY_MEM_OUT=path: at each idle check, write what memory holds, to
    # tell Python objects from native growth and name what piles up.
    mem_out = os.environ.get('VERIFY_MEM_OUT')
    if mem_out:
        import collections
        import gc
        import tracemalloc
        tracemalloc.start(1)
        mem_file = open(mem_out, 'w', buffering=1)

    def mem_sample():
        import sword_bridge as sb
        types = collections.Counter(type(o).__name__ for o in gc.get_objects())
        py_mb = tracemalloc.get_traced_memory()[0] / 1e6
        from gi.repository import Gtk as _Gtk
        def chain(w):
            names = []
            while w is not None and len(names) < 6:
                names.append(w.get_css_classes()[0] if w.get_css_classes()
                             else type(w).__name__)
                w = w.get_parent()
            return '<'.join(names)
        loose = collections.Counter(
            chain(o) for o in gc.get_objects() if isinstance(o, _Gtk.Label))
        mem_file.write(json.dumps({
            't': round(time.monotonic()), 'n': state['n'], 'rss': round(_rss_mb(), 1),
            'py_mb': round(py_mb, 1), 'objects': sum(types.values()),
            'types': dict(types.most_common(60)),
            'loose_labels': dict(loose.most_common(15)),
            'caches': {k: len(getattr(sb, k)) for k in dir(sb)
                       if k.endswith(('_cache', '_CACHE', '_maps', '_dc'))
                       and hasattr(getattr(sb, k), '__len__')},
        }) + '\n')

    problems: list[str] = []
    recent: list[str] = []
    counts: dict[str, int] = {}
    rss: list[float] = []
    idle: list[float] = []
    log_file = open(action_log, 'w', buffering=1)

    def problem(text: str) -> None:
        if len(problems) < 200:
            problems.append(text + '\n  after: ' + ' > '.join(recent[-8:]))

    class Collect(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                text = f'LOG {record.name}: {record.getMessage()}'
                if record.exc_info:
                    text += '\n' + ''.join(traceback.format_exception(*record.exc_info))
                problem(text)
    logging.getLogger().addHandler(Collect())

    def writer(level, fields, _n):
        text = GLib.log_writer_format_fields(level, fields, False)
        if (level <= GLib.LogLevelFlags.LEVEL_CRITICAL
                and 'Broadway' not in text
                and 'gdk_monitor_get_geometry' not in text
                and 'cairo_image_surface_get_width (surface) > 0' not in text
                and 'gdk_texture_save_to_png_bytes: assertion' not in text):
            # A critical from GTK carries no hint of who asked for it; the
            # Python frames say which app call was on the stack, if any.
            stack = ''.join(traceback.format_stack(limit=8)[:-1])
            problem('GLIB ' + text.strip() + '\n' + stack)
        return GLib.LogWriterOutput.HANDLED
    GLib.log_set_writer_func(writer)

    import annotation_dialogs
    import content
    import main
    import sword_bridge

    app = main.BibleApp()
    app.connect('startup', main._on_startup)
    rnd = random.Random(seed)
    BOOKS = list(sword_bridge._ALL_BOOKS)
    readable = list(content.readable_module_names())
    bibles = content.text_bible_names() or ['KJV']
    WORDS = ['love', 'grace', 'God so loved', 'Dios', 'amor', 'Бог', 'любовь', 'λόγος',
             'G3056', 'H430', 'gra*', '"in the beginning"', 'ZZZQQ', 'John 3:16', '(']

    def a_go(win):
        b = rnd.choice(BOOKS)
        win._go_to(b, rnd.randint(1, sword_bridge.chapter_count(b, None)),
                   rnd.choice([None, 1, 5, 40]))

    def a_back_fwd(win):
        rnd.choice([win._on_nav_back, win._on_nav_fwd])(None)

    def a_bible(win):
        rnd.choice([win.pane1, win.pane2])._apply_module_change(rnd.choice(bibles))

    def a_module(win):
        win.pane1._apply_module_change(rnd.choice(readable))

    def a_split(win):
        win._btn_split.set_active(not win._btn_split.get_active())

    def a_footnotes(win):
        win.pane1.set_show_footnotes(not win.pane1._show_footnotes)

    def a_headings(win):
        win.pane1.set_show_headings(not win.pane1._show_headings)

    def a_width(win):
        win.pane1.set_reading_width(rnd.choice([360, 520, 700, 900, 1400]))

    def a_font(win):
        win.pane1.set_font_size(rnd.choice([9, 12, 14, 18, 22, 36]))

    def a_resize(win):
        win.set_default_size(rnd.choice([420, 800, 1100, 1600]), rnd.choice([400, 700, 1000]))

    def a_scheme(win):
        Adw.StyleManager.get_default().set_color_scheme(rnd.choice(
            [Adw.ColorScheme.FORCE_LIGHT, Adw.ColorScheme.FORCE_DARK, Adw.ColorScheme.DEFAULT]))

    def a_picker(win):
        win._ref_pop.popup()
        GLib.timeout_add(rnd.choice([30, 150, 500]), lambda: (win._ref_pop.popdown(), False)[1])

    def a_search(win):
        win._search_panel._entry.set_text(rnd.choice(WORDS))
        win._search_panel._on_search()

    def a_peek(win):
        buf = win.pane1._buffer
        text = buf.get_text(*buf.get_bounds(), False)
        words = [w for w in text.split() if w.isalpha() and len(w) > 3]
        if words:
            w = rnd.choice(words)
            win.pane1._peek.show_dict_popup(w, text.find(w))
            GLib.timeout_add(rnd.choice([40, 200]),
                             lambda: (win.pane1.dismiss_dict_peek(), False)[1])

    def a_menu(win):
        verses = win.pane1.current_verses() or [1]
        pop = annotation_dialogs.build_study_menu(win.pane1, verses, 10, 10)
        pop.popup()
        GLib.timeout_add(rnd.choice([40, 200]), lambda: (pop.popdown(), False)[1])

    def a_bookmark(win):
        win._bookmark_here()

    def a_present(win):
        win._toggle_present_mode()
        GLib.timeout_add(rnd.choice([100, 600]),
                         lambda: (win._toggle_present_mode(), False)[1])

    def a_scroll(win):
        adj = win.pane1._view.get_vadjustment()
        if adj is not None:
            adj.set_value(rnd.uniform(adj.get_lower(), max(adj.get_lower(), adj.get_upper())))

    actions = [(a_go, 24), (a_back_fwd, 6), (a_bible, 8), (a_module, 6), (a_split, 3),
               (a_footnotes, 3), (a_headings, 2), (a_width, 3), (a_font, 3), (a_resize, 2),
               (a_scheme, 1), (a_picker, 5), (a_search, 4), (a_peek, 8), (a_menu, 5),
               (a_bookmark, 1), (a_present, 1), (a_scroll, 10)]
    unknown = skip - {a[0].__name__[2:] for a in actions}
    if unknown:
        raise SystemExit(f'--skip: no action named {", ".join(sorted(unknown))}')
    actions = [a for a in actions if a[0].__name__[2:] not in skip]
    fns = [a[0] for a in actions]
    weights = [a[1] for a in actions]
    t_end = time.monotonic() + minutes * 60
    state = {'n': 0, 'beat': time.monotonic()}

    def heartbeat():
        now = time.monotonic()
        gap = now - state['beat']
        if gap > STALL_SECONDS:
            problem(f'STALL: main loop blocked {gap:.1f} s')
        state['beat'] = now
        return GLib.SOURCE_CONTINUE

    def quiet(win, attempt=0):
        """Wait out the last action's work, then measure an idle stretch."""
        def measure():
            t0, c0 = time.monotonic(), time.process_time()

            def done():
                share = (time.process_time() - c0) / (time.monotonic() - t0)
                if share > IDLE_CPU_LIMIT and attempt == 0:
                    # Indexing or a fetch may still be finishing; look again.
                    GLib.timeout_add(8000, lambda: (quiet(win, 1), False)[1])
                    return GLib.SOURCE_REMOVE
                idle.append(round(share, 3))
                if share > IDLE_CPU_LIMIT:
                    problem(f'IDLE CPU: {share:.0%} of a core with nothing to do')
                rss.append(round(_rss_mb(), 1))
                if mem_out:
                    mem_sample()
                GLib.timeout_add(20, next_action, win)
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(3000, done)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(2500, measure)

    def next_action(win):
        if time.monotonic() > t_end:
            GLib.timeout_add(1000, lambda: (app.quit(), False)[1])
            return GLib.SOURCE_REMOVE
        fn = rnd.choices(fns, weights)[0]
        name = fn.__name__[2:]
        recent.append(name)
        del recent[:-30]
        counts[name] = counts.get(name, 0) + 1
        log_file.write(name + '\n')
        try:
            fn(win)
        except Exception:
            problem(f'ACTION {name} raised\n' + traceback.format_exc())
        state['n'] += 1
        if state['n'] % QUIET_EVERY == 0:
            quiet(win)
        else:
            GLib.timeout_add(rnd.choice([0, 20, 60, 150, 400]), next_action, win)
        return GLib.SOURCE_REMOVE

    def on_activate(_a):
        win = app.get_active_window()
        if win is None:
            problem('no window after activate')
            app.quit()
            return
        GLib.timeout_add(100, heartbeat)
        GLib.timeout_add(1500, next_action, win)
    app.connect('activate', on_activate)
    app.run([])
    faulthandler.cancel_dump_traceback_later()

    # The first samples hold the warm-up, so growth is measured from a later one.
    base = rss[len(rss) // 4] if len(rss) >= 4 else None
    growth = round(rss[-1] - base, 1) if base is not None else None
    if growth is not None and growth > RSS_GROWTH_LIMIT_MB:
        problem(f'MEMORY: grew {growth} MB after warm-up')
    print(json.dumps({
        'seed': seed, 'lang': lang, 'actions': state['n'], 'counts': counts,
        'idle_cpu': idle, 'idle_cpu_max': max(idle, default=None),
        'rss_mb': rss, 'rss_growth_mb': growth,
        'modules': len(readable), 'problems': problems,
    }, ensure_ascii=False))
    return 0


def run(minutes: float, seed: int, lang: str, home_src: Path, scratch: Path,
        skip: str = '', display: int = DISPLAY) -> dict:
    env = os.environ.copy()
    for var in ('DISPLAY', 'WAYLAND_DISPLAY'):
        env.pop(var, None)
    env['HOME'] = str(home_src)
    runtime = None
    for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
        d = scratch / f'{seed}-{var.split("_")[1].lower()}'
        d.mkdir(mode=0o700)
        env[var] = str(d)
        runtime = d
    env['GDK_BACKEND'] = 'broadway'
    env['BROADWAY_DISPLAY'] = f':{display}'
    env['GTK_A11Y'] = 'none'
    cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
    cfg.mkdir(parents=True)
    (cfg / 'settings.json').write_text(json.dumps({'ui_language': lang, 'tips_enabled': False}))
    fonts = Path(os.path.expanduser('~/.local/share/fonts/scriptura'))
    if fonts.is_dir():
        (Path(env['XDG_DATA_HOME']) / 'fonts').mkdir()
        os.symlink(fonts, Path(env['XDG_DATA_HOME']) / 'fonts' / 'scriptura')

    action_log = scratch / f'{seed}-actions.log'
    broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{display}'], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        socket = runtime / f'broadway{display + 1}.socket'
        deadline = time.monotonic() + 5
        while not socket.exists():
            if broadwayd.poll() is not None or time.monotonic() > deadline:
                return {'ENV': 'broadwayd failed to start'}
            time.sleep(0.05)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--driver',
             str(minutes), str(seed), lang, str(action_log), skip],
            env=env, cwd=REPO_ROOT, capture_output=True, text=True,
            timeout=minutes * 60 + 300)
    finally:
        broadwayd.terminate()
        broadwayd.wait()
    lines = proc.stdout.strip().splitlines()
    try:
        rep = json.loads(lines[-1])
    except (IndexError, ValueError):
        last = action_log.read_text().splitlines()[-12:] if action_log.exists() else []
        rep = {'seed': seed, 'lang': lang, 'problems': [
            f'CRASH or HANG: exit {proc.returncode}\n  after: ' + ' > '.join(last)
            + '\n' + proc.stderr[-2500:]]}
    return rep


def main_() -> int:
    args = sys.argv[1:]
    if args[:1] == ['--driver']:
        skip = frozenset(filter(None, args[5].split(','))) if len(args) > 5 else frozenset()
        return driver(float(args[1]), int(args[2]), args[3], args[4], skip)

    def opt(flag, default):
        return args[args.index(flag) + 1] if flag in args else default
    minutes = float(opt('--minutes', '10'))
    rounds = int(opt('--rounds', '1'))
    seed = int(opt('--seed', str(int(time.time()) % 100000)))
    langs = opt('--lang', 'en,es,ru').split(',')
    skip = opt('--skip', '')
    display = int(opt('--display', str(DISPLAY)))
    out = Path(opt('--out', str(REPO_ROOT / 'output' / 'random-test')))
    out.mkdir(parents=True, exist_ok=True)

    base = Path.home() / '.cache' / 'scriptura-verify'
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='random-', dir=base))
    worst = 0
    try:
        # A real copy: nothing the run writes can reach the reader's library.
        home = scratch / 'home'
        home.mkdir()
        real = Path(os.path.expanduser('~/.sword'))
        if real.is_dir():
            shutil.copytree(real, home / '.sword')
        for r in range(rounds):
            for i, lang in enumerate(langs):
                s = seed + r * len(langs) + i
                rep = run(minutes, s, lang, home, scratch, skip, display)
                if 'ENV' in rep:
                    print(rep['ENV'], file=sys.stderr)
                    return 2
                (out / f'{s}-{lang}.json').write_text(
                    json.dumps(rep, indent=1, ensure_ascii=False))
                bad = rep.get('problems', [])
                print(f'seed {s} {lang}: {rep.get("actions", "?")} actions, '
                      f'peak idle CPU {rep.get("idle_cpu_max")}, '
                      f'memory growth {rep.get("rss_growth_mb")} MB, '
                      f'{len(bad)} problems', flush=True)
                seen: set[str] = set()
                for p in bad:
                    head = p.split('\n')[0][:120]
                    if head not in seen:
                        seen.add(head)
                        print('    ' + p.replace('\n', '\n    ')[:1800], flush=True)
                if bad:
                    worst = 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return worst


if __name__ == '__main__':
    sys.exit(main_())
