"""Resumable downloads, cancel, and the free-space check (transfer.py).

The network is a fake that honours Range the way GitHub's and CrossWire's
servers do (both answer `Accept-Ranges: bytes`)."""
import io
import urllib.request
from types import SimpleNamespace

import pytest

import transfer

A = b'a' * 300_000
B = b'b' * 200_000


class _Resp(io.BytesIO):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status
        self.headers = {'Content-Length': str(len(data))}


@pytest.fixture
def server(monkeypatch):
    files = {'http://x/p.000': A, 'http://x/p.001': B}
    log = []
    honour_range = [True]

    def urlopen(req, timeout=None):
        rng = req.get_header('Range')
        log.append((req.full_url, rng))
        data = files[req.full_url]
        if rng and honour_range[0]:
            start = int(rng.split('=')[1].rstrip('-'))
            return _Resp(data[start:], 206)
        return _Resp(data, 200)
    monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
    return log, honour_range


PARTS = [('http://x/p.000', len(A)), ('http://x/p.001', len(B))]


def _stop_after(limit):
    def progress(done, total):
        if done >= limit:
            raise transfer.Cancelled()
    return progress


def test_a_stopped_download_resumes_where_it_stopped(tmp_path, server):
    log, _ = server
    part = str(tmp_path / 'pack.part')
    with pytest.raises(transfer.Cancelled):
        transfer.fetch_resumable(PARTS, part, _stop_after(350_000))
    have, total = transfer.partial(part)
    assert total == len(A) + len(B)
    assert have >= 350_000
    log.clear()
    transfer.fetch_resumable(PARTS, part)
    assert open(part, 'rb').read() == A + B
    # The first part was whole and never asked for again; the second from
    # where it stopped.
    assert [u for u, _r in log] == ['http://x/p.001']
    assert log[0][1] == f'bytes={have - len(A)}-'
    assert transfer.partial(part) is None      # complete: nothing to resume


def test_a_server_that_ignores_range_restarts_the_part(tmp_path, server):
    _log, honour = server
    part = str(tmp_path / 'pack.part')
    with pytest.raises(transfer.Cancelled):
        transfer.fetch_resumable(PARTS, part, _stop_after(100_000))
    honour[0] = False
    transfer.fetch_resumable(PARTS, part)
    assert open(part, 'rb').read() == A + B


def test_a_newer_pack_does_not_splice_onto_an_older_one(tmp_path, server):
    log, _ = server
    part = str(tmp_path / 'pack.part')
    with pytest.raises(transfer.Cancelled):
        transfer.fetch_resumable(PARTS, part, _stop_after(350_000))
    log.clear()
    transfer.fetch_resumable([('http://x/p.001', len(B))], part)
    assert open(part, 'rb').read() == B
    assert log == [('http://x/p.001', None)]


def test_no_download_starts_without_the_space_to_finish(tmp_path, server,
                                                        monkeypatch):
    log, _ = server
    monkeypatch.setattr(transfer.shutil, 'disk_usage',
                        lambda p: SimpleNamespace(free=1000))
    with pytest.raises(transfer.NoSpace) as err:
        transfer.fetch_resumable(PARTS, str(tmp_path / 'pack.part'),
                                 extra=10)
    assert err.value.need == len(A) + len(B) + 10
    assert log == []


def test_read_reports_each_chunk_to_the_bound_callback():
    seen = []
    transfer.bind(lambda d, t: seen.append((d, t)))
    try:
        data = transfer.read(_Resp(A, 200))
    finally:
        transfer.bind(None)
    assert data == A
    assert seen[-1] == (len(A), len(A))
    assert len(seen) > 1


def test_cancelling_a_read_gets_past_except_exception():
    transfer.bind(_stop_after(1))
    try:
        with pytest.raises(transfer.Cancelled):
            try:
                transfer.read(_Resp(A, 200))
            except Exception:
                pytest.fail('Cancelled was swallowed')
    finally:
        transfer.bind(None)
