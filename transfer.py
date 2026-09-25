"""Moving bytes: chunked reads that report progress and can be cancelled,
resumable downloads, and a free-space check before a big one.

GTK-free, so the backends can use it. The download queue (downloads.py)
binds a progress callback to the worker thread; the backends call `read`
or `fetch_resumable` and never need to know whether a queue is watching.
"""

import json
import os
import shutil
import threading
import urllib.request

_CHUNK = 64 * 1024
_local = threading.local()


class Cancelled(BaseException):
    """The reader cancelled the download.

    A BaseException, not an Exception: several download loops report
    progress inside `try: … except Exception: pass`, so that a failing
    progress callback cannot fail a download. Cancelling has to get past
    those, and every cleanup in them is a `finally` or `except
    BaseException` already."""


class NoSpace(OSError):
    """Not enough free disk space for a download: `need` and `free` bytes."""

    def __init__(self, need, free):
        super().__init__(28, f'needs {need} bytes free, {free} free')
        self.need, self.free = need, free


def bind(progress):
    """Send this thread's `read` progress to `progress(done, total)`, or
    stop with None."""
    _local.progress = progress


def report(done, total):
    progress = getattr(_local, 'progress', None)
    if progress is not None:
        progress(done, total)


def read(resp):
    """The whole body of `resp`, read in chunks so that the bound progress
    callback hears each one (and can cancel between them)."""
    headers = getattr(resp, 'headers', None)
    total = int((headers.get('Content-Length') if headers else 0) or 0)
    parts, done = [], 0
    while True:
        chunk = resp.read(_CHUNK)
        if not chunk:
            break
        parts.append(chunk)
        done += len(chunk)
        report(done, total)
    return b''.join(parts)


def ensure_space(path, need):
    """Raise NoSpace unless the file system holding `path` has `need` bytes
    free. `path` may not exist yet; its nearest existing parent is asked."""
    probe = path
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    free = shutil.disk_usage(probe or '/').free
    if need > free:
        raise NoSpace(need, free)


def probe(url, timeout=30):
    """The size a server reports for `url` (a HEAD request), or 0 when it
    does not say."""
    req = urllib.request.Request(url, method='HEAD')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.headers.get('Content-Length') or 0)


def _meta_path(part):
    return part + '.json'


def partial(part: str) -> tuple[int, int] | None:
    """(bytes so far, total bytes) of a download stopped part-way into
    `part`, or None when there is none to resume."""
    try:
        with open(_meta_path(part), encoding='utf-8') as fh:
            meta = json.load(fh)
        have = os.path.getsize(part)
    except (OSError, ValueError):
        return None
    total = sum(meta.get('sizes', []))
    if not have or not total or have >= total:
        return None
    return have, total


def discard(part):
    """Delete a stopped download and its note."""
    for p in (part, _meta_path(part)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def fetch_resumable(parts, part, on_progress=None, extra=0, timeout=120):
    """Download `parts`, [(url, size)] in order, concatenated into `part`.

    A stopped download of the same parts continues where it stopped: the
    parts already whole are skipped and the one cut off is asked for from
    its last byte. A note beside the file (`part.json`) records which
    parts it holds, so a newer pack at other addresses starts again rather
    than splicing two packs together. The file is left in place on failure
    or cancel; the caller discards it once it is installed.

    `extra` is the disk space the caller needs beyond the download itself
    (unpacking it, say); both are checked before a byte is fetched.
    """
    meta = {'urls': [u for u, _s in parts], 'sizes': [s for _u, s in parts]}
    have = 0
    try:
        with open(_meta_path(part), encoding='utf-8') as fh:
            if json.load(fh) == meta:
                have = os.path.getsize(part)
    except (OSError, ValueError):
        pass
    if not have:
        discard(part)
        os.makedirs(os.path.dirname(part) or '.', exist_ok=True)
        with open(_meta_path(part), 'w', encoding='utf-8') as fh:
            json.dump(meta, fh)
        open(part, 'wb').close()
    total = sum(meta['sizes'])
    ensure_space(part, max(total - have, 0) + extra)

    done = have
    offset = 0
    with open(part, 'r+b') as out:
        for url, size in parts:
            if size and have >= offset + size:
                offset += size
                continue
            start = max(have - offset, 0)
            req = urllib.request.Request(url)
            if start:
                req.add_header('Range', f'bytes={start}-')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if start and getattr(resp, 'status', None) != 206:
                    start = 0         # the server sent the whole part again
                out.seek(offset + start)
                out.truncate()
                done = offset + start
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
            offset = out.tell()
            have = offset
