"""What a failed download or install says to the reader.

The backends raise whatever the network, the disk or the archive raised.
Shown as it was, that read `<urlopen error [Errno -3] Temporary failure in
name resolution>`, in English in every language. This sorts an exception
into the handful of things that actually go wrong and gives each one a
translated sentence; the raw text belongs in the log.
"""

import errno
import gzip
import socket
import tarfile
import urllib.error
import zipfile
import zlib

from gi.repository import GLib

import ebible_bridge
import sword_bridge
import transfer
from i18n import _

_DAMAGED = (zipfile.BadZipFile, tarfile.TarError, gzip.BadGzipFile,
            EOFError, zlib.error)


def _cause(exc):
    """The error underneath a URLError (its `reason`), or the error itself."""
    if isinstance(exc, urllib.error.URLError) and not isinstance(
            exc, urllib.error.HTTPError) and isinstance(exc.reason,
                                                         BaseException):
        return exc.reason
    return exc


def _offline(exc):
    """Whether the machine could not look up a host name at all: no network,
    rather than a server that is down. A NotMirrored raised over a failed
    lookup is this too, and saying "only CrossWire may hand it out" to a
    reader whose Wi-Fi is off sends them the wrong way."""
    while exc is not None:
        if isinstance(_cause(exc), socket.gaierror):
            return True
        exc = exc.__cause__
    return False


def describe(exc):
    """One translated sentence for a failed download, update or import."""
    if _offline(exc):
        return _('Scriptura can’t reach the internet. Check your connection '
                 'and try again.')
    if isinstance(exc, sword_bridge.NotMirrored):
        return _('CrossWire is unreachable, and only CrossWire may hand out '
                 'this module. Try again when it is back.')
    if isinstance(exc, sword_bridge.NotInCatalogue):
        return _('This module isn’t in the saved catalogue. Refresh the '
                 'catalogue and try again.')
    if isinstance(exc, sword_bridge.BadModule):
        return _('This file isn’t a SWORD module Scriptura can install. '
                 'Nothing was changed.')
    if isinstance(exc, ebible_bridge.TooFewVerses):
        return _('The download looks incomplete, so the copy you have was '
                 'kept. Try again later.')
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return _('The file isn’t on the server any more. Refresh the '
                     'catalogue and try again.')
        return _('The server turned the download away (error {code}). '
                 'Try again later.').format(code=exc.code)
    if isinstance(exc, transfer.NoSpace):
        return _('This needs {need} of free disk space, and {free} is '
                 'free.').format(need=GLib.format_size(exc.need),
                                 free=GLib.format_size(exc.free))
    cause = _cause(exc)
    if isinstance(cause, OSError) and cause.errno == errno.ENOSPC:
        return _('There isn’t enough free disk space.')
    if isinstance(cause, (urllib.error.URLError, TimeoutError,
                          ConnectionError)):
        return _('The server isn’t answering. Try again later.')
    if isinstance(cause, _DAMAGED):
        return _('The download arrived damaged. Try again.')
    return _('Something went wrong: {detail}').format(detail=exc)
