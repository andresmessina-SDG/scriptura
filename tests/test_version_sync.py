"""The version is written down in three places; they must agree.

`meson.build` decides what the build is called, `_version.py` is what the
About dialog reports, and the newest `<release>` in the metainfo is what
software centres show. Nothing tied them together: preparing 1.4.0 bumped
meson and the metainfo, and `_version.py` — whose own docstring says it is
"kept in sync manually" — was left at 1.3.0. The build was correct, signed
and ready to publish while the About dialog still said 1.3.0.

Manual synchronisation is the defect. This is the cheap guard.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METAINFO = ROOT / 'data' / 'io.github.andresmessina_SDG.Scriptura.metainfo.xml.in'


def _meson_version():
    text = (ROOT / 'meson.build').read_text()
    match = re.search(r"^\s*version:\s*'([^']+)'", text, re.M)
    assert match, 'meson.build has no project version'
    return match.group(1)


def _module_version():
    text = (ROOT / '_version.py').read_text()
    match = re.search(r"^__version__\s*=\s*'([^']+)'", text, re.M)
    assert match, '_version.py has no __version__'
    return match.group(1)


def _newest_release():
    releases = ET.parse(METAINFO).getroot().find('releases')
    assert releases is not None and len(releases), 'metainfo has no releases'
    # Newest first is the AppStream convention and how this file is written.
    return releases[0].get('version')


def test_about_dialog_matches_the_build():
    assert _module_version() == _meson_version(), (
        '_version.py and meson.build disagree — the About dialog would '
        'report a different version from the one being built')


def test_metainfo_announces_the_version_being_built():
    assert _newest_release() == _meson_version(), (
        'the newest metainfo <release> is not the version meson builds — '
        'software centres would show the wrong changelog')


def test_releases_are_newest_first():
    """The other two tests read releases[0]; this is what makes that valid."""
    def key(version):
        return tuple(int(p) for p in version.split('.'))

    versions = [r.get('version')
                for r in ET.parse(METAINFO).getroot().find('releases')]
    assert versions == sorted(versions, key=key, reverse=True), versions
