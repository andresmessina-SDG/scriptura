#!/usr/bin/env python3
"""Render the website's screenshots from the real app, in every language.

    python3 tools/render-site-shots.py --sword SWORD_DIR [--only en,es]

Each shot is its own run of the app under `mutter --headless` (which maps
and lays out the window for real), with scratch XDG directories seeded by a
settings file: the language, the paper, the two panes and the passage. The
reader's own settings and data are never opened; the stores a shot needs
(the catena, the interlinear, the eBible texts) are copied into the scratch
data directory first.

SWORD_DIR is a SWORD library holding the Bibles the shots name that are not
in ~/.sword (RusOpenBible, for one); it is added through SWORD_PATH.

Writes docs/assets/img/<lang>/<shot>.webp, and reading.jpg for link
previews, then a contact sheet at site-shots.png for review. Only open
Bibles appear: the same rule tests/test_site.py holds the page to.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WAYLAND = 'scriptura-site-0'
SIZE = (1366, 733)

# The reader's Bible in each language: open texts only.
BIBLE = {'en': 'KJVA', 'es': 'SpaRV1909', 'ru': 'RusOpenBible'}
READING = {'en': 'BSB', 'es': 'SpaRV1909', 'ru': 'RusOpenBible'}

SHOTS = {
    # name: the settings for the run
    'interlinear': lambda lang: {
        'pane1_module': BIBLE[lang], 'pane2_module': 'InterlinearGreek',
        'last_book': 'John', 'last_chapter': 1, 'split_pane_mode': True},
    'voices': lambda lang: {
        'pane1_module': BIBLE[lang], 'pane2_module': 'Historical Commentaries',
        'last_book': 'John', 'last_chapter': 1, 'split_pane_mode': True},
    # Matthew 9:9 is one of the few verses where the art pane leads with a
    # painting rather than an engraving: Caravaggio's Calling of Saint Matthew.
    'art': lambda lang: {
        'pane1_module': BIBLE[lang], 'pane2_module': 'Bible Imagery',
        'last_book': 'Matthew', 'last_chapter': 9, 'split_pane_mode': True,
        'verse': 9},
    'reading': lambda lang: {
        'pane1_module': READING[lang], 'pane2_module': BIBLE[lang],
        'last_book': 'Psalms', 'last_chapter': 23, 'split_pane_mode': False,
        'reading_mode': True},
    'writing': lambda lang: {
        'pane1_module': BIBLE[lang], 'pane2_module': READING[lang],
        'last_book': 'John', 'last_chapter': 1, 'split_pane_mode': True,
        'sermon': True},
}
# Every shot in the app's light and dark: the page shows the one that
# matches the reader's paper.
SCHEMES = ('light', 'dark')

# The sermon the writing room is shown with: an example, in each language,
# quoting the open Bible that language's page uses.
SERMON_ID = '5c1a7e0b3f2d4c8e9a6b1d2f3e4a5b6c'
SERMON = {
    'en': ('In the Beginning Was the Word',
           'Before anything was made, the Word already was; and the Word has come to us.',
           '# The Word before all things\n'
           'John opens where Genesis opens: “In the beginning.” Before the first '
           'thing was made, the Word already was.\n\n'
           '> In the beginning was the Word, and the Word was with God, and the '
           'Word was God. (John 1:1)\n\n'
           '# The Word who made all things\n'
           '- Nothing that exists came to be without him (v. 3).\n'
           '- The life we have is his gift (v. 4).\n\n'
           '# The light the darkness cannot overcome\n'
           'The darkness has not seized it (v. 5). Whatever this week has held, '
           'the light still shines.\n\n'
           '# Taking it home\n'
           '1. Read John 1:1–18 aloud this week.\n'
           '2. Name one place where you need the light to shine.',
           'The Gospel of John'),
    'es': ('En el principio era el Verbo',
           'Antes de que algo fuera hecho, el Verbo ya era; y el Verbo ha venido a nosotros.',
           '# El Verbo antes de todas las cosas\n'
           'Juan comienza donde comienza el Génesis: «En el principio». Antes de '
           'que algo fuera hecho, el Verbo ya era.\n\n'
           '> En el principio era el Verbo, y el Verbo era con Dios, y el Verbo '
           'era Dios. (Juan 1:1)\n\n'
           '# El Verbo que hizo todas las cosas\n'
           '- Nada de lo que existe fue hecho sin él (v. 3).\n'
           '- La vida que tenemos es don suyo (v. 4).\n\n'
           '# La luz que las tinieblas no vencen\n'
           'Las tinieblas no la comprendieron (v. 5). Sea lo que sea que trajo '
           'esta semana, la luz sigue brillando.\n\n'
           '# Para llevar a casa\n'
           '1. Lea en voz alta Juan 1:1–18 esta semana.\n'
           '2. Nombre un lugar donde necesita que brille la luz.',
           'El Evangelio de Juan'),
    'ru': ('В начале было Слово',
           'Прежде чем что-либо было создано, Слово уже было; и Слово пришло к нам.',
           '# Слово прежде всего\n'
           'Иоанн начинает там же, где начинается Бытие: «В начале». Прежде чем '
           'что-либо было создано, Слово уже было.\n\n'
           '> В начале было Слово, и Слово было у Бога, и Слово было Бог. '
           '(Иоанна 1:1)\n\n'
           '# Слово, которым всё сотворено\n'
           '- Ничто из существующего не возникло без Него (ст. 3).\n'
           '- Жизнь, которая у нас есть, — Его дар (ст. 4).\n\n'
           '# Свет, который тьма не одолела\n'
           'Тьма не объяла его (ст. 5). Что бы ни принесла эта неделя, свет '
           'по-прежнему светит.\n\n'
           '# Что взять с собой\n'
           '1. Прочитайте вслух Иоанна 1:1–18 на этой неделе.\n'
           '2. Назовите одно место, где вам нужен свет.',
           'Евангелие от Иоанна'),
}


def _seed_sermon(data_home: Path, lang: str) -> None:
    title, idea, body, series = SERMON[lang]
    store = {'version': 1, 'sermons': {SERMON_ID: {
        'title': title, 'idea': idea, 'body': body,
        'anchors': [{'book': 'John', 'chapter': 1, 'verses': [1, 2, 3, 4, 5]}],
        'series': {'name': series, 'part': 1}, 'preached': ['2026-09-20'],
        'collect': None, 'tags': [],
        'created': '2026-09-14T09:00:00', 'modified': '2026-09-19T21:30:00'}}}
    path = data_home / 'bible-reader' / 'sermons.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding='utf-8')


# The stores a shot reads, copied from the reader's data directory.
DATA_FILES = ('catena.db', 'ebible.db', 'open_data/interlinear_greek.sqlite',
              'open_data/greek_lexicon.sqlite')


def _seed_data(data_home: Path) -> None:
    src = Path(os.environ.get('XDG_DATA_HOME',
                              Path.home() / '.local' / 'share'), 'bible-reader')
    dst = data_home / 'bible-reader'
    # The art pack is half a gigabyte of images the app only reads: copy its
    # catalogue and link the images in place.
    pack = Path(src, 'imagery')
    if pack.is_dir():
        Path(dst, 'imagery').mkdir(parents=True, exist_ok=True)
        shutil.copy2(pack / 'imagery.sqlite', Path(dst, 'imagery', 'imagery.sqlite'))
        Path(dst, 'imagery', 'images').symlink_to(pack / 'images')
    for rel in DATA_FILES:
        # A SQLite store's newest writes may still sit in its -wal journal.
        for part in (rel, rel + '-wal', rel + '-shm'):
            if Path(src, part).exists():
                Path(dst, part).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(src, part), Path(dst, part))


def run_one(lang: str, shot: str, scheme: str, sword: Path,
            data_home: Path, out: Path, timeout: float = 120.0) -> str:
    with tempfile.TemporaryDirectory(prefix='scriptura-shot-') as scratch:
        env = os.environ.copy()
        for var in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
            d = Path(scratch, var.split('_')[1].lower())
            d.mkdir(mode=0o700)
            env[var] = str(d)
        env['XDG_DATA_HOME'] = str(data_home)
        seed = {'ui_language': lang, 'tips_enabled': False,
                'open_to_today': False, 'show_crossrefs': False,
                'window_width': SIZE[0], 'window_height': SIZE[1],
                'window_maximized': False}
        spec = SHOTS[shot](lang)
        reading_mode = spec.pop('reading_mode', False)
        verse = spec.pop('verse', 1)
        sermon = spec.pop('sermon', False)
        if sermon:
            _seed_sermon(data_home, lang)
        seed.update(spec, color_scheme=scheme)
        name = shot if scheme == 'light' else f'{shot}-dark'
        cfg = Path(env['XDG_CONFIG_HOME'], 'bible-reader')
        cfg.mkdir(parents=True)
        (cfg / 'settings.json').write_text(json.dumps(seed))
        env.update({'WAYLAND_DISPLAY': WAYLAND, 'GDK_BACKEND': 'wayland',
                    'LANGUAGE': lang, 'SWORD_PATH': str(sword),
                    'SITE_SHOT_OUT': str(out / f'{lang}-{name}.png'),
                    'SITE_SHOT_READING': '1' if reading_mode else '',
                    'SITE_SHOT_VERSE': str(verse),
                    'SITE_SHOT_SERMON': SERMON_ID if sermon else ''})
        env.pop('DISPLAY', None)
        mutter = subprocess.Popen(
            ['mutter', '--headless', '--wayland', f'--wayland-display={WAYLAND}',
             '--virtual-monitor', f'{SIZE[0] + 200}x{SIZE[1] + 200}'],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            sock = Path(env['XDG_RUNTIME_DIR'], WAYLAND)
            deadline = time.monotonic() + 15.0
            while not sock.exists():
                if mutter.poll() is not None or time.monotonic() > deadline:
                    return f'{lang}-{name}: mutter --headless would not start'
                time.sleep(0.1)
            time.sleep(1.0)
            proc = subprocess.run([sys.executable, __file__, '--driver'],
                                  env=env, cwd=REPO_ROOT, timeout=timeout,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
            return proc.stdout.strip() or f'{lang}-{name}: exit {proc.returncode}'
        finally:
            mutter.terminate()
            mutter.wait()


def driver() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gsk', '4.0')
    from gi.repository import GLib, Graphene, Gsk, Gtk

    import main

    app = main.BibleApp()
    out = Path(os.environ['SITE_SHOT_OUT'])
    result: list[str] = []

    def shoot(win):
        w, h = win.get_width(), win.get_height()
        snap = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(win).snapshot(snap, w, h)
        node = snap.to_node()
        renderer = Gsk.CairoRenderer()
        renderer.realize(None)
        tex = renderer.render_texture(node, Graphene.Rect().init(0, 0, w, h))
        tex.save_to_png(str(out))
        renderer.unrealize()
        result.append(f'{out.name} {w}x{h}')

    steps = []

    target: dict = {}

    def first(win):
        win.set_default_size(*SIZE)
        win.pane1.load_reference_at_verse(win.pane1.book, win.pane1.chapter,
                                          int(os.environ.get('SITE_SHOT_VERSE', '1')))
        if os.environ.get('SITE_SHOT_READING'):
            win._set_reading_mode(True, toast=False)
        if os.environ.get('SITE_SHOT_SERMON'):
            win._open_annotations()
            target['win'] = win._annotations_win
            target['win'].set_default_size(*SIZE)

    def select(win):
        # What the Bible pane broadcasts when a reader clicks a verse: the
        # art pane receives it and shows that verse's painting.
        verse = int(os.environ.get('SITE_SHOT_VERSE', '1'))
        if verse > 1:
            win.pane2.select_verse(verse)

    def sermon(win):
        if 'win' in target:
            target['win'].select_sermon(os.environ['SITE_SHOT_SERMON'])

    def unfocus(win):
        # Opening a sermon puts the cursor in its title, which then shows
        # as selected text; a picture of the room has no cursor in it.
        if 'win' in target:
            target['win']._sermon_editor.title.select_region(0, 0)
            target['win'].set_focus(None)

    steps.append(first)
    steps.extend([lambda win: None] * 2)
    steps.append(select)
    steps.append(sermon)
    steps.extend([lambda win: None] * 3)
    steps.append(unfocus)
    steps.extend([lambda win: None] * 3)     # let panes, catena and layout settle
    steps.append(lambda win: shoot(target.get('win', win)))

    def run_next(win):
        if not steps:
            app.quit()
            return GLib.SOURCE_REMOVE
        fn = steps.pop(0)
        try:
            fn(win)
        except Exception as exc:
            result.append(f'ERROR {out.name} {fn.__name__}: {exc!r}')
        return GLib.SOURCE_CONTINUE

    app.connect('activate', lambda _a: GLib.timeout_add(
        700, run_next, app.get_active_window()))
    GLib.timeout_add_seconds(90, lambda: (app.quit(), GLib.SOURCE_REMOVE)[1])
    app.run([])
    print('\n'.join(result))
    return 1 if any(r.startswith('ERROR') for r in result) else 0


def publish(out: Path, langs) -> None:
    """PNGs into the site's webp shots, a link-preview jpg, a contact sheet."""
    from PIL import Image
    sheet_rows = []
    for lang in langs:
        row = []
        for shot in SHOTS:
            for name in (shot, f'{shot}-dark'):
                png = out / f'{lang}-{name}.png'
                if not png.exists():
                    continue
                im = Image.open(png).convert('RGB')
                dst = REPO_ROOT / 'docs' / 'assets' / 'img' / lang
                dst.mkdir(parents=True, exist_ok=True)
                im.save(dst / f'{name}.webp', quality=88, method=6)
                if name == 'reading-dark':
                    im.resize((1200, round(1200 * im.height / im.width))).save(
                        dst / 'reading.jpg', quality=82)
                row.append(im)
        sheet_rows.append(row)
    if any(sheet_rows):
        w, h = 683, 367
        cols = max(len(r) for r in sheet_rows)
        sheet = Image.new('RGB', (w * cols, h * len(sheet_rows)), 'white')
        for y, row in enumerate(sheet_rows):
            for x, im in enumerate(row):
                sheet.paste(im.resize((w, h)), (x * w, y * h))
        sheet.save(out / 'site-shots.png')


def main_() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--sword', required=True, type=Path,
                    help='SWORD library with the Bibles not in ~/.sword')
    ap.add_argument('--only', default='en,es,ru', help='languages to render')
    ap.add_argument('--shots', default=','.join(SHOTS), help='shots to render')
    ap.add_argument('--out', type=Path, default=Path('site-shots'),
                    help='where the raw PNGs and the contact sheet go')
    args = ap.parse_args()
    langs = args.only.split(',')
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    with tempfile.TemporaryDirectory(prefix='scriptura-shot-data-') as data:
        _seed_data(Path(data))
        for lang in langs:
            for shot in args.shots.split(','):
                for scheme in SCHEMES:
                    line = run_one(lang, shot, scheme, args.sword.resolve(),
                                   Path(data), args.out.resolve())
                    print(line)
                    failed += 'ERROR' in line or 'exit' in line or 'mutter' in line
    publish(args.out.resolve(), langs)
    return 1 if failed else 0


if __name__ == '__main__':
    if '--driver' in sys.argv:
        sys.exit(driver())
    sys.exit(main_())
