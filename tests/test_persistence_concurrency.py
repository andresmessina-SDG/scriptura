"""A timer already writing must finish before the shutdown save writes."""

import json
import threading

import pytest

import module_positions
import settings


@pytest.mark.parametrize('store', [settings, module_positions])
def test_flush_waits_for_running_save_and_persists_latest_state(
        tmp_path, monkeypatch, store):
    if store._save_timer is not None:
        store._save_timer.cancel()
    target = tmp_path / (store.__name__ + '.json')
    monkeypatch.setattr(store, '_FILE', str(target))
    monkeypatch.setattr(store, '_save_timer', None)
    state_name = '_cache' if store is settings else '_state'
    old = {'KJVA': {'kind': 'genbook', 'genbook_path': '/Old'}}
    latest = {'KJVA': {'kind': 'genbook', 'genbook_path': '/Latest_entry'}}
    monkeypatch.setattr(store, state_name, old)
    writing, release = threading.Event(), threading.Event()
    flushing, finished = threading.Event(), threading.Event()
    errors = []
    real_dump = json.dump

    def paused_dump(data, fh, **kwargs):
        if threading.current_thread() is timer:
            writing.set()
            assert release.wait(5)
        return real_dump(data, fh, **kwargs)

    def run_timer():
        try:
            store._on_debounce_fire()
        except BaseException as exc:
            errors.append(exc)

    def run_flush():
        flushing.set()
        try:
            store.flush()
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    monkeypatch.setattr(json, 'dump', paused_dump)
    timer = threading.Thread(target=run_timer)
    final_save = threading.Thread(target=run_flush)
    timer.start()
    try:
        assert writing.wait(5)
        setattr(store, state_name, latest)
        final_save.start()
        assert flushing.wait(5)
        # The timer holds an open .tmp. A flush that returns now can rename
        # it under that writer, which then corrupts the final JSON file.
        assert not finished.wait(0.1)
    finally:
        release.set()
        timer.join(5)
        if final_save.ident is not None:
            final_save.join(5)
    assert not timer.is_alive() and not final_save.is_alive()
    assert not errors
    assert json.loads(target.read_text()) == latest
    assert not target.with_suffix('.json.tmp').exists()
