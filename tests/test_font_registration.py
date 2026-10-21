"""Startup must expose bundled fonts even when Flatpak caches hide them.

Each subprocess keeps the old zero-mtime cache in place, then starts through
main() and reads the same Pango family list as Appearance. No window opens,
and fontconfig and application data are confined to the test directory.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
FONT_DIR = REPO / 'data' / 'fonts'

_STARTUP = r'''
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import main
from gi.repository import Pango, PangoCairo

main.__file__ = sys.argv[2]
os.environ.pop(main._RELAUNCH_ENV, None)
font_map = PangoCairo.FontMap.get_default()
targets = {'UnifrakturMaguntia', 'Merriweather'}
before = {f.get_name() for f in font_map.list_families()} & targets
assert not before, before
cache = Path(os.environ['XDG_CACHE_HOME']) / 'fontconfig'
cached = {p: hashlib.sha256(p.read_bytes()).hexdigest()
          for p in cache.glob('*cache*')}
assert cached

class FontListApp:
    def __init__(self, unique):
        assert unique
        families = {f.get_name() for f in font_map.list_families()}
        assert targets <= families, sorted(families)
        context = font_map.create_context()
        for family in targets:
            font = font_map.load_font(context, Pango.FontDescription.from_string(family + ' 16'))
            assert family in font.describe().get_family(), font.describe().to_string()
        print(json.dumps({'before': sorted(before), 'after': sorted(families & targets)}))

    def connect(self, *_args):
        pass

    def run(self, _argv):
        pass

main.BibleApp = FontListApp
main._listen_for_session_end = lambda app: None
main.main()
assert all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest
           for p, digest in cached.items()), 'The existing cache was changed'
'''


@pytest.mark.parametrize('cached_layout', [
    'installed_parent', 'installed_files', 'source_files',
])
def test_startup_loads_fonts_hidden_by_an_existing_cache(tmp_path, cached_layout):
    if not shutil.which('fc-cache'):
        pytest.skip('fontconfig tools unavailable')
    if cached_layout == 'source_files':
        main_file = tmp_path / 'source' / 'main.py'
        parent = tmp_path / 'source' / 'data'
        fonts = parent / 'fonts'
    else:
        main_file = tmp_path / 'app' / 'share' / 'scriptura' / 'main.py'
        parent = tmp_path / 'app' / 'share' / 'fonts'
        from _version import __version__
        fonts = parent / f'scriptura-{__version__}'
    previous = parent / 'scriptura' if cached_layout == 'installed_parent' else fonts
    previous.mkdir(parents=True)
    shutil.copy(FONT_DIR / 'Newsreader[opsz,wght].ttf', previous)
    for directory in (previous, parent):
        os.utime(directory, (0, 0))

    env = os.environ.copy()
    for kind in ('CONFIG', 'DATA', 'CACHE'):
        directory = tmp_path / kind.lower()
        directory.mkdir()
        env[f'XDG_{kind}_HOME'] = str(directory)
    cache = tmp_path / 'cache' / 'fontconfig'
    cache.mkdir()
    config = tmp_path / 'fonts.conf'
    config.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
        f'<fontconfig><dir>{parent}</dir><cachedir>{cache}</cachedir></fontconfig>')
    env['FONTCONFIG_FILE'] = str(config)
    subprocess.run(['fc-cache', '-f'], env=env, check=True, timeout=30)

    if previous != fonts:
        shutil.rmtree(previous)
        fonts.mkdir()
    for name in ('UnifrakturMaguntia-Book.ttf',
                 'Merriweather[opsz,wdth,wght].ttf',
                 'Merriweather-Italic[opsz,wdth,wght].ttf'):
        shutil.copy(FONT_DIR / name, fonts)
    for directory in (fonts, parent):
        os.utime(directory, (0, 0))

    result = subprocess.run(
        [sys.executable, '-c', _STARTUP, str(REPO), str(main_file)],
        env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report == {'before': [], 'after': ['Merriweather', 'UnifrakturMaguntia']}
