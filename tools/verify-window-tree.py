#!/usr/bin/env python3
"""Widget-tree fingerprint — proves a construction refactor changed nothing.

Third harness in the family, after tools/verify-scroll-stability.py (the
"text never moves" invariant) and tools/verify-today.py (the Today page and
its players). Those two assert BEHAVIOUR. This one asserts SHAPE: it drives
the real app headless, walks every widget BibleWindow builds, and writes a
canonical description of each. Two runs are compared with diff.

Why it exists. Relocating construction code is the one kind of change the
test suite cannot see: `_build_ui` and `_build_menu_panel` build ~2,700
widgets and assert nothing, so a line dropped in the middle of a move stays
green through pytest and mypy alike. Splitting those two methods (backlog
item 21) dropped a Gtk.Separator, and only this diff caught it.

Usage — dump, change, dump, compare:

    git stash
    python3 tools/verify-window-tree.py /tmp/base
    git stash pop
    python3 tools/verify-window-tree.py /tmp/new --compare /tmp/base

Assert you reached the tree you meant to (`git diff main --stat`) before
trusting a baseline: a stash that silently fails to apply turns this into a
comparison of a branch with itself, which passes and means nothing.

Exit 0 = every configuration matched (or dumped, with no --compare),
1 = a configuration differed or a run failed, 2 = the environment is unusable.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPLAY = 7  # private XDG_RUNTIME_DIR per run, so a fixed number never collides
POLL_MS = 150
WAIT_CAP_MS = 20000
DRIVER_TIMEOUT = 120.0

#: Every configuration that reaches a different construction branch. Widths are
#: chosen to straddle the three Adw.Breakpoints installed by
#: _install_breakpoints (max-width 850/680/600), which are otherwise never
#: exercised; `today` flips the Today-page branch of _build_reading_overlay,
#: which is skipped ENTIRELY when the setting is off.
CONFIGS = (
    ('wide',       1200, False),
    ('wide-today', 1200, True),
    ('header',      700, False),   # ≤850: secondary controls fold into ⋯
    ('ultra',       560, False),   # ≤600: the rest of the chrome folds too
    ('roomy',       900, False),   # no breakpoint active
)


# ── The fingerprint ─────────────────────────────────────────────────────────

def describe(w) -> str:
    """Everything about a widget that a pure code move must not change."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk

    bits = [type(w).__name__]
    cls = w.get_css_classes()
    if cls:
        bits.append('.' + '.'.join(cls))

    if isinstance(w, Gtk.Label):
        bits.append(f'label={w.get_label()!r}')
        bits.append(f'xalign={w.get_xalign():.2f}')
    if isinstance(w, Gtk.Image) and w.get_icon_name():
        bits.append(f'icon={w.get_icon_name()}')
    # Buttons only: Adw.ActionRow also has get_icon_name, but it is deprecated
    # and the app never uses it — its icons are Gtk.Images added as prefixes,
    # which this walk reaches as children anyway.
    if isinstance(w, Gtk.Button):
        if w.get_label():
            bits.append(f'blabel={w.get_label()!r}')
        if w.get_icon_name():
            bits.append(f'icon={w.get_icon_name()}')
    tip = w.get_tooltip_text()
    if tip:
        bits.append(f'tip={tip!r}')

    if isinstance(w, Gtk.Box):
        bits.append(f'orient={int(w.get_orientation())}')
        bits.append(f'spacing={w.get_spacing()}')
        bits.append(f'homog={int(w.get_homogeneous())}')
    if isinstance(w, (Gtk.Switch, Gtk.ToggleButton, Gtk.CheckButton)):
        bits.append(f'active={int(w.get_active())}')
    if isinstance(w, Gtk.Scale):
        adj = w.get_adjustment()
        bits.append(f'value={w.get_value():.3f}')
        bits.append(f'range={adj.get_lower():.1f}..{adj.get_upper():.1f}')
    if isinstance(w, Gtk.DropDown):
        model = w.get_model()
        bits.append(f'items={model.get_n_items() if model else 0}')
        bits.append(f'selected={w.get_selected()}')
    if isinstance(w, Gtk.Revealer):
        bits.append(f'reveal={int(w.get_reveal_child())}')
        bits.append(f'trans={int(w.get_transition_type())}')
        bits.append(f'dur={w.get_transition_duration()}')
    if isinstance(w, Gtk.ScrolledWindow):
        bits.append(f'overlay_scroll={int(w.get_overlay_scrolling())}')
    if isinstance(w, Gtk.Expander):
        bits.append(f'exp_label={w.get_label()!r}')

    bits.append(f'vis={int(w.get_visible())}')
    bits.append(f'sens={int(w.get_sensitive())}')
    bits.append(f'hexp={int(w.get_hexpand())}')
    bits.append(f'vexp={int(w.get_vexpand())}')
    bits.append(f'halign={int(w.get_halign())}:{int(w.get_valign())}')
    m = (w.get_margin_start(), w.get_margin_end(),
         w.get_margin_top(), w.get_margin_bottom())
    if any(m):
        bits.append('margins=%d,%d,%d,%d' % m)
    req = w.get_size_request()
    if req[0] != -1 or req[1] != -1:
        bits.append(f'req={req[0]}x{req[1]}')
    return ' '.join(bits)


def walk(w, out: list[str], depth: int = 0) -> None:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk

    # No cycle guard: a GTK widget tree IS a tree. An id()-keyed guard is
    # actively wrong here — PyGObject wrappers are transient, so a freed
    # wrapper's id is handed to an unrelated widget and most of the tree
    # vanishes as a bogus "cycle" (measured: 136 lines instead of 2,664).
    out.append('  ' * depth + describe(w))
    child = w.get_first_child()
    while child is not None:
        walk(child, out, depth + 1)
        child = child.get_next_sibling()
    # A MenuButton's popover is not among its children.
    if isinstance(w, Gtk.MenuButton) and w.get_popover() is not None:
        out.append('  ' * (depth + 1) + '[popover]')
        walk(w.get_popover(), out, depth + 2)


def fingerprint(win) -> list[str]:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk

    lines: list[str] = []
    win._ensure_menu_panel()      # normally an idle; the panel is the point
    walk(win, lines)

    lines += ['', '# adaptive layout']
    bp = win.get_current_breakpoint()
    lines.append(f'current_breakpoint = '
                 f'{bp.get_condition().to_string() if bp else None}')
    for name in ('_bp_header', '_bp_panes', '_bp_ultra'):
        b = getattr(win, name, None)
        lines.append(f'{name} = '
                     f'{b.get_condition().to_string() if b else None}')

    lines += ['', '# window attributes holding widgets']
    for name in sorted(vars(win)):
        v = vars(win)[name]
        if isinstance(v, Gtk.Widget):
            lines.append(f'{name}: {type(v).__name__}')

    lines += ['', '# plain construction state']
    for name in sorted(vars(win)):
        v = vars(win)[name]
        # GObject handler ids are deliberately EXCLUDED. They look like an
        # ordering fingerprint and are not: they come off a global counter that
        # GTK's own internal connections advance, so how much layout ran before
        # the lazy menu-panel idle fired changes them. Measured on one
        # unchanged tree across three runs: 8414, 8414, 8419.
        if name.endswith('_handler'):
            continue
        if isinstance(v, (int, bool, float, str, type(None))):
            lines.append(f'{name} = {v!r}')
        elif isinstance(v, (list, tuple, dict, set)):
            lines.append(f'{name}: {type(v).__name__} len={len(v)}')
    return lines


# ── Driver: runs inside the app's process ───────────────────────────────────

def run_driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import GLib

    import main

    out = Path(os.environ['SCRIPTURA_TREE_OUT'])
    width = int(os.environ['SCRIPTURA_TREE_WIDTH'])
    app = main.BibleApp()
    S: dict = {'tries': 0}

    def dump() -> int:
        try:
            lines = fingerprint(S['win'])
        except Exception:
            import traceback
            print(json.dumps({'ok': False, 'traceback': traceback.format_exc()}))
            app.quit()
            return GLib.SOURCE_REMOVE
        out.write_text('\n'.join(lines) + '\n')
        print(json.dumps({'ok': True, 'widgets': len(lines)}))
        app.quit()
        return GLib.SOURCE_REMOVE

    def wait_ready() -> int:
        S['tries'] += 1
        win = S.get('win')
        # Ready once the reading pane has a real allocation — or give up at the
        # cap and fingerprint whatever was built (never an open wait).
        if win is not None and win.pane1.get_width() > 0:
            return dump()
        if S['tries'] * POLL_MS >= WAIT_CAP_MS:
            return dump()
        return GLib.SOURCE_CONTINUE

    def kickoff() -> int:
        win = app.get_active_window()
        if win is None:
            return GLib.SOURCE_CONTINUE
        S['win'] = win
        win.set_default_size(width, 800)
        GLib.timeout_add(POLL_MS, wait_ready)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(POLL_MS, kickoff)
    GLib.timeout_add(int(DRIVER_TIMEOUT * 1000) // 2,
                     lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])
    return 0


# ── Orchestrator: scratch env + broadwayd, one per configuration ────────────

def dump_config(name: str, width: int, today: bool, dest: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix='scriptura-tree-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                    'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['GDK_BACKEND'] = 'broadway'
        env['BROADWAY_DISPLAY'] = f':{DISPLAY}'
        env['SCRIPTURA_TREE_OUT'] = str(dest)
        env['SCRIPTURA_TREE_WIDTH'] = str(width)
        # Offline, or this tool cries wolf. The Today page fetches the Daily
        # Strength feed and offers a Listen control only if it lands in time,
        # so a run that reached the network differs from one that did not —
        # tooltip, visibility and _today_listen all move, none of it
        # construction. A refused proxy fails instantly and the scratch
        # XDG_CACHE_HOME guarantees no index is cached from an earlier run.
        for var in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            env[var] = 'http://127.0.0.1:1'
        env['no_proxy'] = env['NO_PROXY'] = ''

        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / 'settings.json').write_text(json.dumps({'open_to_today': today}))

        broadwayd = subprocess.Popen(['gtk4-broadwayd', f':{DISPLAY}'], env=env,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        try:
            socket = Path(env['XDG_RUNTIME_DIR'],
                          f'broadway{DISPLAY + 1}.socket')
            deadline = time.monotonic() + 5.0
            while not socket.exists():
                if broadwayd.poll() is not None or time.monotonic() > deadline:
                    print('broadwayd failed to start', file=sys.stderr)
                    return False
                time.sleep(0.05)
            try:
                subprocess.run([sys.executable, __file__, '--driver'],
                               env=env, cwd=REPO_ROOT, timeout=DRIVER_TIMEOUT,
                               stdout=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                print(f'{name}: driver timed out', file=sys.stderr)
                return False
            return dest.exists()
        finally:
            broadwayd.terminate()
            broadwayd.wait()


def orchestrate() -> int:
    parser = argparse.ArgumentParser(
        description='Fingerprint the window widget tree in every '
                    'construction configuration.')
    parser.add_argument('outdir', help='directory to write the dumps into')
    parser.add_argument('--compare', metavar='DIR',
                        help='baseline directory to diff against; any '
                             'difference exits 1')
    parser.add_argument('--only', metavar='NAME',
                        help='one configuration: '
                             + ', '.join(c[0] for c in CONFIGS))
    args = parser.parse_args()

    import shutil
    if shutil.which('gtk4-broadwayd') is None:
        print('gtk4-broadwayd not found (Fedora package gtk4)', file=sys.stderr)
        return 2

    configs = [c for c in CONFIGS if args.only in (None, c[0])]
    if not configs:
        print(f'unknown configuration {args.only!r}', file=sys.stderr)
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    failed = False

    for name, width, today in configs:
        dest = outdir / f'{name}.txt'
        if not dump_config(name, width, today, dest):
            print(f'{name}: FAILED to dump')
            failed = True
            continue
        lines = dest.read_text().splitlines()
        if not args.compare:
            print(f'{name}: {len(lines)} lines -> {dest}')
            continue
        base = Path(args.compare) / f'{name}.txt'
        if not base.exists():
            print(f'{name}: no baseline at {base}')
            failed = True
            continue
        delta = list(difflib.unified_diff(
            base.read_text().splitlines(), lines,
            fromfile=str(base), tofile=str(dest), lineterm='', n=1))
        if delta:
            print(f'{name}: DIFFERS ({len(lines)} lines)')
            print('\n'.join(delta[:60]))
            if len(delta) > 60:
                print(f'... {len(delta) - 60} more diff lines')
            failed = True
        else:
            print(f'{name}: identical ({len(lines)} lines)')

    if failed:
        return 1
    print('\nall configurations '
          + ('matched the baseline' if args.compare else 'dumped'))
    return 0


if __name__ == '__main__':
    sys.exit(run_driver() if '--driver' in sys.argv else orchestrate())
