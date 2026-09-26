"""updates.py — which installed texts have an update, for the whole app.

The Module Manager works out which Bibles, books and packs are behind; the
window's menu and the pane's module picker only need to know what it found.
The answer is saved, so it is there at the next start without reading the
catalogue again, and it changes when the Module Manager next looks.

The Module Manager also checks by itself, when it opens and its lists are
more than a week old (decided 2026-09-25). CrossWire changed 2 of 428
modules in a month and eBible 29 of 1,551, so a week is enough. It
never checks on a metered connection, and never without a network.
"""

import os
import time

from gi.repository import Gio

import settings

#: A catalogue older than this is checked when the Module Manager opens.
CHECK_AFTER_DAYS = 7
#: On a metered connection, a download bigger than this asks first.
METERED_ASK_BYTES = 50 * 1024 * 1024

_listeners: list = []


def pending() -> set:
    """The keys with an update: 'sword:NAME', 'ebible:ID', 'pack:…'."""
    return set(settings.get('module_updates') or [])


def set_pending(keys) -> None:
    keys = sorted(set(keys))
    if keys == sorted(pending()):
        return
    settings.put('module_updates', keys)
    for fn in list(_listeners):
        fn()


def listen(fn) -> None:
    _listeners.append(fn)


def unlisten(fn) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def key_for_module(name: str) -> str:
    """The update key of a module the panes show by `name`."""
    import ebible_bridge
    if ebible_bridge.is_ebible_module(name):
        return 'ebible:' + name[len(ebible_bridge.PREFIX):]
    return 'sword:' + name


def has_update(name: str) -> bool:
    return key_for_module(name) in pending()


def pack_keys() -> list:
    """The curated packs installed and behind the build this app expects:
    read from the packs themselves, no network."""
    import catena_bridge
    import imagery_bridge
    import interlinear_data
    keys = []
    if catena_bridge.is_installed() and catena_bridge.update_available():
        keys.append('pack:catena')
    if imagery_bridge.is_installed() and imagery_bridge.update_available():
        keys.append('pack:imagery')
    for name in (interlinear_data.GREEK, interlinear_data.HEBREW):
        if (interlinear_data.is_installed(name)
                and interlinear_data.needs_rebuild(name)):
            keys.append('pack:interlinear:' + name)
    return keys


def note_packs() -> None:
    """Bring the packs' part of the list up to date: a new version of the
    app can expect a newer pack before the Module Manager is next opened."""
    keep = {k for k in pending() if not k.startswith('pack:')}
    set_pending(keep | set(pack_keys()))


def _age_days(stamp) -> float | None:
    return None if stamp is None else (time.time() - stamp) / 86400


def check_due(with_ebible: bool) -> bool:
    """Whether the catalogues are missing or more than a week old. The
    eBible catalogue counts only for a reader with an eBible text."""
    import paths
    import sword_bridge
    when = sword_bridge.catalog_timestamp()
    ages = [_age_days(when.timestamp() if when else None)]
    if with_ebible:
        path = paths.ebible_catalog_path()
        ages.append(_age_days(os.path.getmtime(path)
                              if os.path.exists(path) else None))
    return any(a is None or a > CHECK_AFTER_DAYS for a in ages)


def metered() -> bool:
    return bool(Gio.NetworkMonitor.get_default().get_network_metered())


def may_check() -> bool:
    """A network, and not a metered one: the check never spends a
    reader's data allowance on its own."""
    monitor = Gio.NetworkMonitor.get_default()
    return bool(monitor.get_network_available()
                and not monitor.get_network_metered())
