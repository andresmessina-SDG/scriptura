"""The bundled reading faces, and the tracking readout.

Two silent failures are pinned here. A font that is not in `data/meson.build`
is simply absent from the Flatpak — fontconfig scans the installed tree, so
the app runs, the name still sits in the Font dropdown, and choosing it falls
back to a serif with nothing said anywhere (GUIDANCE §4: repo-green is not
shipped-green). And OpenDyslexic's family name is its Reserved Font Name under
the OFL as well as the stored settings value, so translating the label would
both break the licence and stop the setting resolving.
"""
import re
from pathlib import Path

from window import OPEN_DYSLEXIC

REPO = Path(__file__).resolve().parents[1]
FONT_DIR = REPO / 'data' / 'fonts'


def _installed_data_names():
    """Every filename named in data/meson.build's install_data calls."""
    text = (REPO / 'data' / 'meson.build').read_text()
    return set(re.findall(r"'(fonts/[^']+)'", text))


def test_every_bundled_font_file_is_installed():
    listed = _installed_data_names()
    on_disk = {'fonts/' + p.name for p in FONT_DIR.iterdir() if p.is_file()}
    missing = sorted(on_disk - listed)
    assert not missing, (
        f'{missing} sit in data/fonts but are not in data/meson.build, so '
        f'they will not exist in the Flatpak — a face chosen in Appearance '
        f'would fall back to a serif and say nothing')


def test_the_dyslexia_face_ships_all_four_styles():
    """The reading text sets bold and italic, and OpenDyslexic has no variable
    build — so a missing style is not a missing style, it is the whole
    paragraph silently reverting to another family mid-sentence."""
    listed = _installed_data_names()
    for style in ('Regular', 'Bold', 'Italic', 'Bold-Italic'):
        name = f'fonts/OpenDyslexic-{style}.otf'
        assert name in listed, f'{name} is not installed'


def test_the_dyslexia_licence_travels_with_the_font():
    """OFL clause 1: the licence must accompany the font it covers."""
    assert 'fonts/OpenDyslexic-OFL.txt' in _installed_data_names()
    text = (FONT_DIR / 'OpenDyslexic-OFL.txt').read_text()
    assert 'SIL Open Font License' in text
    assert 'Reserved Font Name' in text


def test_the_family_name_is_never_translated():
    """It is the font, the settings value and the label at once."""
    source = (REPO / 'window.py').read_text()
    assert f"_('{OPEN_DYSLEXIC}')" not in source
    assert f'_("{OPEN_DYSLEXIC}")' not in source


#: 0.12 is WCAG 1.4.12's text-spacing floor, and the scale has to reach it.
WCAG_TRACKING = 0.12


def test_the_tracking_readout_names_the_default_rather_than_zero():
    """Every other row in the panel reads a quantity — 12pt, 1.5×, 540px — so
    '0%' there reads as a setting the reader has turned down to nothing,
    rather than as the face's own metrics."""
    from window import BibleWindow
    assert BibleWindow._tracking_label(0.0) != '0%'
    assert BibleWindow._tracking_label(0) != '0%'


def test_the_tracking_readout_is_a_percentage_of_the_type_size():
    from window import BibleWindow
    assert BibleWindow._tracking_label(WCAG_TRACKING) == '12%'
    assert BibleWindow._tracking_label(0.06) == '6%'
