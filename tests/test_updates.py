"""The update loop: when the Module Manager checks, what it remembers, and
what the rest of the app shows from it."""
import os
import time
from datetime import datetime, timedelta

import pytest

import settings
import sword_bridge
import updates


def test_the_list_is_remembered_and_listeners_hear_a_change():
    heard = []
    updates.listen(lambda: heard.append(True))
    try:
        updates.set_pending(['sword:KJV', 'ebible:spaRV1909'])
        assert updates.pending() == {'sword:KJV', 'ebible:spaRV1909'}
        assert settings.get('module_updates') == ['ebible:spaRV1909',
                                                  'sword:KJV']
        updates.set_pending(['ebible:spaRV1909', 'sword:KJV'])
        assert heard == [True]          # the same list again is no change
    finally:
        updates._listeners.clear()
        updates.set_pending([])


def test_a_module_is_known_by_its_key():
    assert updates.key_for_module('KJV') == 'sword:KJV'
    import ebible_bridge
    assert updates.key_for_module(ebible_bridge.PREFIX + 'spaRV1909') == \
        'ebible:spaRV1909'


def test_the_check_is_due_when_a_list_is_missing_or_a_week_old(
        monkeypatch, tmp_path):
    import paths
    cat = tmp_path / 'ebible_catalog.csv'
    monkeypatch.setattr(paths, 'ebible_catalog_path', lambda: str(cat))
    stamp = {'when': None}
    monkeypatch.setattr(sword_bridge, 'catalog_timestamp',
                        lambda: stamp['when'])
    assert updates.check_due(False)                 # never downloaded
    stamp['when'] = datetime.now() - timedelta(days=2)
    assert not updates.check_due(False)
    # The eBible list counts only for a reader with an eBible text.
    assert updates.check_due(True)
    cat.write_text('')
    assert not updates.check_due(True)
    old = time.time() - 8 * 86400
    os.utime(cat, (old, old))
    assert updates.check_due(True)
    stamp['when'] = datetime.now() - timedelta(days=8)
    assert updates.check_due(False)


def test_a_check_never_runs_offline_or_metered(monkeypatch):
    import importlib
    real = importlib.reload(updates)
    try:
        class Monitor:
            available, metered = True, False

            def get_network_available(self):
                return self.available

            def get_network_metered(self):
                return self.metered
        mon = Monitor()
        monkeypatch.setattr(real.Gio.NetworkMonitor, 'get_default',
                            lambda: mon)
        assert real.may_check()
        mon.metered = True
        assert not real.may_check() and real.metered()
        mon.metered, mon.available = False, False
        assert not real.may_check()
    finally:
        real.may_check = lambda: False      # as conftest leaves it


def test_the_catalogue_keeps_what_each_version_changed():
    info = sword_bridge._parse_conf_lines([
        '[KJV]', 'Version=3.1', 'History_2.6=Fixed bugs.',
        'History_3.1=(2023-07-19) Conf version updated to 3.1'])
    assert info['history'] == {'2.6': 'Fixed bugs.',
                               '3.1': '(2023-07-19) Conf version updated to '
                                      '3.1'}
    mod = {'version': '3.1', 'history': info['history']}
    assert sword_bridge.newest_history(mod).startswith('(2023-07-19)')
    # No line for its own version: the newest there is, by version order.
    assert sword_bridge.newest_history(
        {'version': '4', 'history': {'2.10': 'b', '2.9': 'a'}}) == 'b'
    assert sword_bridge.newest_history({'version': '1'}) == ''
