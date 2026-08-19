"""Every icon name the app asks for must actually resolve.

The app pins its icon theme (main._PINNED_ICON_THEME) so that a reader on
KDE, Zorin or GNOME sees one set rather than three. That trade has a cost
worth guarding: the app no longer benefits from a user theme happening to
carry a name the pinned set has dropped. A typo, or an upstream rename
between icon-theme releases, becomes a blank square in the toolbar — and a
blank square is the kind of defect nobody files.

So: scrape the names out of the source and check each one against the
pinned set plus what we ship ourselves.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ANY string literal ending in -symbolic, not just the ones passed to a
# call this file knows the shape of. The first version of this test matched
# `icon_name=`, `new_from_icon_name(` and `set_icon_name(` — and so missed
# every icon handed positionally to a helper, which was fifteen of them,
# including three the app never bundled. A test that only sees the callers
# it expects reports a clean sweep over the part it cannot see.
_NAME_RE = re.compile(r"""['"]([a-z0-9][a-z0-9._-]*-symbolic)['"]""")

# The desktop's, not ours — see main._PLATFORM_ICONS.
_PLATFORM = {'window-close-symbolic', 'window-minimize-symbolic',
             'window-maximize-symbolic', 'window-restore-symbolic'}

_SKIP_DIRS = {'flatpak-build', 'test-build-dir', '__pycache__', 'tests',
              'tools', '.git'}

# main.py names the platform icons in order to preserve them, which is the
# opposite of asking for one.
_SKIP_FILES = {'main.py'}


def _sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py') and fn not in _SKIP_FILES:
                yield os.path.join(dirpath, fn)


def icon_names():
    found = set()
    for path in _sources():
        with open(path, encoding='utf-8') as f:
            found.update(_NAME_RE.findall(f.read()))
    return sorted(found)


def _shipped():
    """Names under data/icons — our own art, which no theme can shadow
    because nothing else claims those names."""
    base = os.path.join(ROOT, 'data', 'icons')
    out = set()
    for dirpath, _d, filenames in os.walk(base):
        for fn in filenames:
            if fn.endswith(('.svg', '.png')):
                out.add(os.path.splitext(fn)[0])
    return out


def test_the_scrape_finds_the_icons():
    """A regex that quietly matches nothing would pass every check below."""
    names = icon_names()
    assert len(names) > 60, names
    assert 'scriptura-open-menu-symbolic' in names


def test_the_app_asks_for_no_icon_it_does_not_ship():
    """The point of vendoring. Every icon the app draws is one whose name
    nothing else claims, so no user theme and no future Adwaita rename can
    change it or take it away — the two ways an icon silently becomes a
    blank square on somebody else's machine."""
    shipped = _shipped()
    borrowed = [n for n in icon_names()
                if n not in shipped and n not in _PLATFORM]
    assert not borrowed, (
        f'{len(borrowed)} icon names come from the user\'s theme rather than '
        f'data/icons, so they vary by desktop: {borrowed}')


def test_the_platform_keeps_its_window_controls():
    """The deliberate exception, from the other side: we must not start
    shipping these, or the button that closes this window stops matching
    the button that closes every other one."""
    shipped = _shipped()
    for name in _PLATFORM:
        assert name not in shipped, f'{name} belongs to the desktop'


def test_every_icon_name_resolves_in_the_pinned_theme():
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Gdk
    # init_check() returns True even with no display at all, while
    # Gdk.Display.get_default() is None — and looking an icon up on a null
    # display is a segfault, not an exception.
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        pytest.skip('no display — icon lookup needs one')
    import main

    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    # Gtk.IconTheme.set_theme_name() does NOT stick while a GtkSettings
    # exists — it is overwritten from the settings property, so a test
    # written that way silently measures the developer's own desktop theme
    # instead of the pinned one. Set the property.
    Gtk.Settings.get_default().set_property(
        'gtk-icon-theme-name', main._PINNED_ICON_THEME)
    assert theme.get_theme_name() == main._PINNED_ICON_THEME
    shipped = _shipped()
    missing = [n for n in icon_names()
               if n not in shipped and not theme.has_icon(n)]
    assert not missing, (
        f'{len(missing)} icon names are in neither {main._PINNED_ICON_THEME} '
        f'nor data/icons — they will draw as blank: {missing}')


def test_our_own_icons_are_all_shipped():
    """A scriptura-* name is ours by definition: nothing else provides it,
    so a missing file is a guaranteed blank rather than a lucky fallback."""
    shipped = _shipped()
    missing = [n for n in icon_names()
               if n.startswith('scriptura') and n not in shipped]
    assert not missing, f'named but not shipped: {missing}'


def test_window_controls_are_left_to_the_desktop():
    """The one deliberate exception. If a control name ever appears in the
    pinned list, the platform stops owning its own buttons."""
    import main
    assert 'window-close-symbolic' in main._PLATFORM_ICONS
    for name in main._PLATFORM_ICONS:
        assert name.startswith('window-')
