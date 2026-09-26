"""The Module Manager's rows."""

# ── The installed eBible row's Update button ────────────────────────────────
# An installed translation used to offer nothing but Remove, so picking up a
# re-parse (the Strong's numbers the USFM parser now keeps) meant deleting
# the text and fetching it again.

from types import SimpleNamespace

import pytest
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
    win._action_rows = {}
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
    """Drive _on_eb_download with the queue stubbed out, and report
    what reached the status line."""
    import ebible_bridge
    from module_manager import ModuleManagerWindow as W

    win = W.__new__(W)
    flashed = []
    win._flash = flashed.append
    win._modules_changed = lambda: None
    win._populate = lambda: None
    win._set_progress = lambda msg: None

    def fake_submit(key, title, work, *, row=True, changes=True,
                    done_text='', then=None):
        # Completes synchronously; no thread, no network. `then` runs only
        # on success, as the queue's on_finish does.
        if err is None and then is not None:
            then(SimpleNamespace(done_text=done_text))
    win._submit = fake_submit

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


# ── A download starting or ending does not rebuild what it need not ─────────

def _small_window(monkeypatch):
    """A real window over a two-module catalogue, nothing on disk."""
    import module_manager as mm
    mods = [{'name': n, 'description': n, 'type': 'Biblical Texts',
             'lang': 'en', 'features': set(), 'license': '', 'size': '1000',
             'version': '1', 'locked': False, 'installed': False}
            for n in ('Alpha', 'Beta')]
    monkeypatch.setattr(mm.sword_bridge, 'list_available_modules',
                        lambda: [dict(m) for m in mods])
    monkeypatch.setattr(mm.sword_bridge, 'available_updates', lambda: [])
    monkeypatch.setattr(mm.sword_bridge, 'catalog_timestamp', lambda: None)
    monkeypatch.setattr(mm.ebible_bridge, 'catalog_entries', lambda: [])
    monkeypatch.setattr(mm.ebible_bridge, 'installed_ids', lambda: set())
    monkeypatch.setattr(mm.ebible_bridge, 'import_stamps', lambda: {})
    return mm, mm.ModuleManagerWindow()


@needs_display
def test_a_download_starting_turns_its_row_over_in_place(monkeypatch):
    """Redrawing every tab for a new download froze the window 0.56s."""
    import downloads
    mm, win = _small_window(monkeypatch)
    rebuilt = []
    monkeypatch.setattr(win, '_refresh_tab',
                        lambda *a, **k: rebuilt.append(a))
    job = downloads.Job('sword:Alpha', 'Alpha', downloads.CROSSWIRE, None)
    monkeypatch.setitem(downloads._jobs, job.key, job)
    win._on_job(job)
    assert rebuilt == []
    assert len(win._job_widgets.get('sword:Alpha', [])) == 1
    win.close()


@needs_display
def test_only_the_tab_on_screen_is_rebuilt_until_another_is_shown(
        monkeypatch):
    mm, win = _small_window(monkeypatch)
    rebuilt = []
    real = win._refresh_tab
    monkeypatch.setattr(win, '_refresh_tab', lambda tab_id, **k: (
        rebuilt.append((tab_id, k.get('languages'))), real(tab_id, **k)))
    win._populate(languages=False)        # a download ended
    assert rebuilt == [('bibles', False)]
    win._stack.set_visible_child_name('commentaries')
    # Never shown before, so its language list is built too, this once.
    assert rebuilt[-1] == ('commentaries', True)
    win._stack.set_visible_child_name('bibles')
    assert len(rebuilt) == 2              # already current: not rebuilt again
    win.close()


# ── The update loop ─────────────────────────────────────────────────────────

def _updates_window(monkeypatch, due=True, may=True):
    import updates
    monkeypatch.setattr(updates, 'check_due', lambda with_ebible: due)
    monkeypatch.setattr(updates, 'may_check', lambda: may)
    submitted = []
    import module_manager as mm
    real = mm.ModuleManagerWindow._submit

    def submit(self, key, title, work, **kw):
        submitted.append((key, title, kw))
        if key == 'sword:refresh':
            return 'check-job'      # never run: no network in a test
        return real(self, key, title, work, **kw)
    monkeypatch.setattr(mm.ModuleManagerWindow, '_submit', submit)
    mm_, win = _small_window(monkeypatch)
    return win, submitted


@needs_display
def test_opening_the_manager_checks_when_the_lists_are_old(monkeypatch):
    win, submitted = _updates_window(monkeypatch)
    assert [(k, t) for k, t, _kw in submitted] == \
        [('sword:refresh', 'Checking for updates…')]
    assert submitted[0][2]['row'] is False
    assert win._check_job == 'check-job'
    win.close()


@needs_display
@pytest.mark.parametrize('due, may', [(False, True), (True, False)])
def test_no_check_when_fresh_offline_or_metered(monkeypatch, due, may):
    win, submitted = _updates_window(monkeypatch, due=due, may=may)
    assert submitted == []
    win.close()


@needs_display
def test_a_check_that_fails_says_nothing(monkeypatch):
    import downloads
    win, _submitted = _updates_window(monkeypatch)
    job = downloads.Job('sword:refresh', 'Checking for updates…',
                        downloads.CROSSWIRE, None, row=False)
    job.state, job.error = downloads.FAILED, OSError('no route')
    win._check_job = job
    errors = []
    monkeypatch.setattr(win, '_set_error', lambda *a, **k: errors.append(a))
    win._on_job(job)
    assert errors == []
    win.close()


@needs_display
def test_update_rows_say_their_size_and_what_changed(monkeypatch):
    import updates
    win, _s = _updates_window(monkeypatch, due=False)
    new = {'name': 'Alpha', 'description': 'Alpha', 'type': 'Biblical Texts',
           'lang': 'en', 'features': set(), 'license': '',
           'size': str(3 * 1024 * 1024), 'version': '2.0', 'locked': False,
           'installed': True, 'history': {'2.0': 'New text source'}}
    beta = dict(new, name='Beta', history={})
    win._updates = [(new, '1.0'), (beta, '1.0')]
    started = []
    monkeypatch.setattr(win, '_on_install',
                        lambda b, m, r: started.append(m['name']))
    t = win._tabs['bibles']
    win._rebuild_updates(t)
    alpha = t['update_rows'][0]
    assert alpha.get_subtitle() == \
        'Update from v1.0 to v2.0 · 3.0 MB · New text source'
    every = t['updates_group'].get_header_suffix()
    assert every is not None and every.get_label() == 'Update All'
    every.emit('clicked')
    assert started == ['Alpha', 'Beta']
    win._updates = [(new, '1.0')]
    win._rebuild_updates(t)
    assert t['updates_group'].get_header_suffix() is None
    # What the menu's dot reads, set by the Module Manager's reading.
    monkeypatch.setattr(win, '_eb_stale_reasons', lambda: {'x': 'source'})
    monkeypatch.setattr(mm_sword(), 'available_updates',
                        lambda: [(new, '1.0')])
    win._populate(languages=False)
    assert {'sword:Alpha', 'ebible:x'} <= updates.pending()
    updates.set_pending([])
    win.close()


def mm_sword():
    import module_manager
    return module_manager.sword_bridge


@needs_display
def test_a_big_download_on_a_metered_connection_asks_first(monkeypatch):
    import updates
    from gi.repository import Adw
    win, _s = _updates_window(monkeypatch, due=False)
    shown, went = [], []
    monkeypatch.setattr(Adw.AlertDialog, 'present',
                        lambda self, parent: shown.append(self))
    monkeypatch.setattr(updates, 'metered', lambda: True)
    win._ask_if_metered(60 * 1024 * 1024, lambda: went.append(True))
    assert len(shown) == 1 and went == []
    shown[0].emit('response', 'download')
    assert went == [True]
    win._ask_if_metered(5 * 1024 * 1024, lambda: went.append('small'))
    assert went[-1] == 'small' and len(shown) == 1
    monkeypatch.setattr(updates, 'metered', lambda: False)
    win._ask_if_metered(600 * 1024 * 1024, lambda: went.append('free'))
    assert went[-1] == 'free' and len(shown) == 1
    win.close()


@needs_display
def test_each_tab_counts_its_own_updates(monkeypatch):
    """The menu said 5 and the Bibles tab 4: the fifth, the imagery pack,
    was under Books & More, with nothing to say so."""
    import updates
    win, _s = _updates_window(monkeypatch, due=False)
    bible = {'name': 'Alpha', 'type': 'Biblical Texts', 'version': '2'}
    comm = {'name': 'Gamma', 'type': 'Commentaries', 'version': '2'}
    monkeypatch.setattr(mm_sword(), 'available_updates',
                        lambda: [(bible, '1'), (comm, '1')])
    monkeypatch.setattr(win, '_eb_stale_reasons',
                        lambda: {'spaRV1909': 'source'})
    monkeypatch.setattr(updates, 'pack_keys', lambda: ['pack:imagery'])
    win._populate(languages=False)
    badges = {tid: t['page'].get_badge_number()
              for tid, t in win._tabs.items()}
    assert badges == {'bibles': 2, 'commentaries': 1, 'study': 0,
                      'books': 1}
    updates.set_pending([])
    win.close()


# ── Progress as a ring around Cancel ────────────────────────────────────────

def test_megabytes_round_rather_than_cut():
    import module_manager as mm
    assert mm._mb(34_600_000) == '33'       # 32.997: the row says ~33 MB
    assert mm._mb(2_700_000) == '2.6'


@needs_display
def test_a_row_shows_its_job_as_a_ring_and_words_in_one_column(
        monkeypatch):
    import downloads
    win, _s = _updates_window(monkeypatch, due=False)
    alpha = downloads.Job('sword:Alpha', 'Alpha', downloads.CROSSWIRE, None)
    alpha.state, alpha.done, alpha.total = downloads.RUNNING, 1, 4
    beta = downloads.Job('sword:Beta', 'Beta', downloads.CROSSWIRE, None)
    for job in (alpha, beta):
        monkeypatch.setitem(downloads._jobs, job.key, job)
        win._on_job(job)
    (a_label, a_ring), = win._job_widgets['sword:Alpha']
    (b_label, b_ring), = win._job_widgets['sword:Beta']
    assert (a_ring.state, a_ring.fraction) == (downloads.RUNNING, 0.25)
    assert b_ring.state == downloads.QUEUED and b_label.get_text() == 'Queued'
    # One width for every row's words, whatever they say.
    assert a_label.get_size_request()[0] == b_label.get_size_request()[0] > 0
    alpha.phase = 'Reading the text…'
    alpha.done = alpha.total = 0
    win._on_job(alpha)
    assert a_ring.fraction is None           # unknown: the arc goes round
    win.close()


@needs_display
def test_the_lists_download_turns_refresh_into_a_spinner(monkeypatch):
    import downloads
    from gi.repository import Adw
    win, _s = _updates_window(monkeypatch, due=False)
    job = downloads.Job('sword:refresh', 'Checking for updates…',
                        downloads.CROSSWIRE, None, row=False)
    job.state = downloads.RUNNING
    monkeypatch.setitem(downloads._jobs, job.key, job)
    win._sync_bar()
    btn = win._tabs['bibles']['refresh']
    assert isinstance(btn.get_child(), Adw.Spinner)
    assert btn.get_tooltip_text() == 'Checking for updates…'
    assert not win._progress.get_visible()   # not across the window
    job.state = downloads.DONE
    monkeypatch.delitem(downloads._jobs, job.key)
    win._sync_bar()
    assert not isinstance(btn.get_child(), Adw.Spinner)
    assert btn.get_tooltip_text() == 'Refresh the catalogue'
    win.close()


@needs_display
def test_a_burst_of_jobs_ending_rebuilds_once(monkeypatch):
    """Update All ends many jobs at nearly the same time; rebuilt once per
    job, back to back, sixteen rebuilds froze the window for 3.2 s."""
    import time
    import downloads
    from gi.repository import GLib
    win, _s = _updates_window(monkeypatch, due=False)
    built = []
    monkeypatch.setattr(win, '_populate',
                        lambda languages=True: built.append(languages))
    for i in range(16):
        job = downloads.Job(f'sword:M{i}', f'M{i}', downloads.CROSSWIRE, None)
        job.state = downloads.DONE
        win._on_job(job)
    lists = downloads.Job('sword:refresh', 'lists', downloads.CROSSWIRE,
                          None, row=False)
    lists.state = downloads.DONE
    win._on_job(lists)
    assert built == []
    ctx = GLib.MainContext.default()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    assert built == [True]      # once, with the language lists (a refresh)
    win.close()


@needs_display
def test_a_burst_of_finished_downloads_is_said_once(monkeypatch):
    """Update All ended 59 jobs in seconds, and a screen reader was made to
    read all 59 sentences."""
    import time
    import downloads
    import module_manager as mm
    from gi.repository import GLib
    win, _s = _updates_window(monkeypatch, due=False)
    said = []
    monkeypatch.setattr(mm, 'announce', lambda _w, text, **k: said.append(text))
    monkeypatch.setattr(win, '_populate', lambda languages=True: None)

    def end(key, text):
        job = downloads.Job(key, key, downloads.CROSSWIRE, None,
                            done_text=text)
        job.state = downloads.DONE
        win._on_job(job)

    def settle():
        ctx = GLib.MainContext.default()
        stop = time.monotonic() + 0.6
        while time.monotonic() < stop:
            ctx.iteration(False)
            time.sleep(0.01)
    end('sword:A', 'A installed')
    settle()
    assert said == ['A installed']          # one: in its own words
    for i in range(5):
        end(f'sword:B{i}', f'B{i} installed')
    settle()
    assert said[1:] == ['5 downloads finished']
    assert win._status.get_text() == '5 downloads finished'
    win.close()


@needs_display
def test_a_flash_never_covers_an_error(monkeypatch):
    """"5 downloads finished", just after a failure, replaced its words and
    hid its Retry."""
    win, _s = _updates_window(monkeypatch, due=False)
    win._set_error('KJV: The server isn’t answering.', retry=lambda: None)
    win._flash('5 downloads finished')
    assert win._status.get_text() == 'KJV: The server isn’t answering.'
    assert win._retry_btn.get_visible()
    win.close()


def test_removing_from_the_picker_takes_its_update_with_it(monkeypatch):
    import types
    import module_picker
    import updates
    updates.set_pending(['sword:KJV', 'sword:ASV'])
    monkeypatch.setattr(module_picker.content, 'remove', lambda name: None)
    picker = module_picker.ModulePicker.__new__(module_picker.ModulePicker)
    picker._pane = types.SimpleNamespace(
        _on_toast=None, _on_modules_changed=lambda: None)
    picker._do_remove('KJV')
    assert updates.pending() == {'sword:ASV'}
    updates.set_pending([])
