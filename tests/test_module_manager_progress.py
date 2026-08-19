"""Determinate download-bar semantics (_progress_fraction).

Pure helper — the window bar is determinate exactly while download bytes
flow, and returns to the activity pulse for size-unknown downloads and
for the post-download tail (extract/parse/commit), where a bar frozen at
100% would read as hung.
"""
from module_manager import _progress_fraction


def test_fraction_while_bytes_flow():
    assert _progress_fraction(1, 4) == 0.25
    assert _progress_fraction(3, 4) == 0.75


def test_unknown_total_pulses():
    assert _progress_fraction(1024, 0) is None


def test_nothing_reported_yet_pulses():
    assert _progress_fraction(0, 4) is None


def test_tail_after_last_byte_pulses():
    assert _progress_fraction(4, 4) is None
    assert _progress_fraction(5, 4) is None


# ── The installed eBible row's Update button ────────────────────────────────
# An installed translation used to offer nothing but Remove, so picking up a
# re-parse (the Strong's numbers the USFM parser now keeps) meant deleting
# the text and fetching it again.

import pytest                                        # noqa: E402
import gi                                             # noqa: E402
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk                # noqa: E402

from module_manager import ModuleManagerWindow         # noqa: E402

# These build real widgets, and a libadwaita widget built without a display
# does not raise — it SEGFAULTS, taking the whole pytest process with it and
# every test after it. CI runs in a container with no display, so the guard
# has to come before Adw.init(), not inside the tests.
# Gtk.init_check() is NOT a display check: with no display at all it still
# returns True while Gdk.Display.get_default() is None. Ask for the display.
Gtk.init_check()
_HAVE_DISPLAY = Gdk.Display.get_default() is not None
if _HAVE_DISPLAY:
    Adw.init()

needs_display = pytest.mark.skipif(
    not _HAVE_DISPLAY, reason='builds real widgets; no display here')

_ENTRY = {'translationId': 'spaRV1909', 'shortTitle': 'Reina Valera 1909',
          'languageCode': 'spa', 'languageName': 'Spanish',
          'licenseType': 'Public Domain'}


def _row_buttons(entry, installed, stale=None):
    win = ModuleManagerWindow.__new__(ModuleManagerWindow)
    win._trash_button = lambda cb: Gtk.Button(label='Remove')
    win._eb_stale = dict(stale or {})
    win._eb_by_id = {'spaRV1909': entry}
    row = ModuleManagerWindow._make_eb_row(
        win, 'spaRV1909', 'RV1909', 'spa', 'Spanish', entry,
        installed=installed)

    def walk(widget):
        out = []
        child = widget.get_first_child()
        while child:
            if isinstance(child, Gtk.Button):
                out.append(child.get_label())
            out += walk(child)
            child = child.get_next_sibling()
        return out
    return walk(row)


@needs_display
def test_a_stale_installed_row_offers_an_update():
    assert _row_buttons(_ENTRY, installed=True,
                        stale={'spaRV1909': 'parser'}) == ['Update', 'Remove']


@needs_display
def test_a_current_installed_row_offers_only_remove():
    """The button used to stand on every installed row, before and after a
    download alike, so it could not tell a text that needed updating from one
    that had just been updated. Nothing to update, nothing to offer."""
    assert _row_buttons(_ENTRY, installed=True) == ['Remove']


@needs_display
def test_browse_row_offers_only_install():
    assert _row_buttons(_ENTRY, installed=False) == ['Install']


@needs_display
def test_the_button_explains_why_it_is_there():
    """The tooltip carries the reason, so the row says what an update would
    win rather than just offering the verb."""
    win = ModuleManagerWindow.__new__(ModuleManagerWindow)
    win._eb_by_id = {'latVUC': {'UpdateDate': '2026-08-08'}}
    assert 'formatting' in ModuleManagerWindow._eb_stale_text(
        win, 'latVUC', 'parser')
    assert '2026-08-08' in ModuleManagerWindow._eb_stale_text(
        win, 'latVUC', 'source')


# ── Which installed texts count as stale ────────────────────────────────────

def _stale(catalog, stamps):
    import ebible_bridge
    win = ModuleManagerWindow.__new__(ModuleManagerWindow)
    win._eb_by_id = catalog
    real = ebible_bridge.import_stamps
    ebible_bridge.import_stamps = lambda: stamps
    try:
        return ModuleManagerWindow._eb_stale_reasons(win)
    finally:
        ebible_bridge.import_stamps = real


def test_an_unstamped_import_is_stale():
    """Every translation installed before the stamp existed reads as NULL,
    which is exactly the state that needs a re-download."""
    assert _stale({'latVUC': _ENTRY}, {'latVUC': ('', 1)}) == \
        {'latVUC': 'parser'}


def test_a_current_import_is_not_stale():
    import ebible_bridge
    assert _stale({'latVUC': dict(_ENTRY, UpdateDate='2026-08-08')},
                  {'latVUC': ('2026-08-08', ebible_bridge.IMPORT_VERSION)}) == {}


def test_a_newer_upstream_text_is_stale():
    import ebible_bridge
    assert _stale({'latVUC': dict(_ENTRY, UpdateDate='2026-08-08')},
                  {'latVUC': ('2026-05-16', ebible_bridge.IMPORT_VERSION)}) == \
        {'latVUC': 'source'}


def test_stale_needs_a_catalogue_entry():
    """Re-downloading from a blank entry would rewrite the translation's
    title and licence as empty strings, so a text the catalogue has lost
    never reaches the button."""
    assert _stale({}, {'latVUC': ('', 1)}) == {}


# ── An update has to say it happened ────────────────────────────────────────

def _run_download(already_installed, err=None):
    """Drive _on_eb_download with the async runner stubbed out, and report
    what reached the status line."""
    import ebible_bridge
    from module_manager import ModuleManagerWindow as W

    win = W.__new__(W)
    flashed = []
    win._flash = flashed.append
    win._modules_changed = lambda: None
    win._populate = lambda: None
    win._set_progress = lambda msg: None

    def fake_run_async(work, on_done, busy_msg='', show_bar=True, retry=None):
        on_done(err)          # completes synchronously; no thread, no network
        return True
    win._run_async = fake_run_async

    real_ids = ebible_bridge.installed_ids
    ebible_bridge.installed_ids = lambda: ({'latVUC'} if already_installed
                                           else set())
    try:
        btn = Gtk.Button(label='Update')
        W._on_eb_download(win, btn, 'latVUC',
                          {'translationId': 'latVUC',
                           'shortTitle': 'Clementine Vulgate 1598'})
    finally:
        ebible_bridge.installed_ids = real_ids
    return flashed


@needs_display
def test_a_finished_update_says_so():
    """_populate rebuilds the row, so a finished update and one that never
    ran look exactly alike — the only difference the reader can see."""
    assert _run_download(already_installed=True) == \
        ['Clementine Vulgate 1598 updated']


@needs_display
def test_a_fresh_install_stays_quiet():
    """An install announces itself: the row moves to Installed and the button
    turns into a trash can. A flash on top of that would be noise."""
    assert _run_download(already_installed=False) == []


@needs_display
def test_a_failed_update_does_not_claim_success():
    assert _run_download(already_installed=True, err='HTTP 500') == []
