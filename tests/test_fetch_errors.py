"""A failed download says one plain sentence, in the reader's language —
not `<urlopen error [Errno -3] Temporary failure in name resolution>`."""
import errno
import socket
import urllib.error
import zipfile

import pytest

import ebible_bridge
import fetch_errors
import sword_bridge


def _http(code):
    return urllib.error.HTTPError('https://x/y.zip', code, 'msg', {}, None)


@pytest.mark.parametrize('exc,words', [
    (urllib.error.URLError(socket.gaierror(-3, 'x')), 'reach the internet'),
    (urllib.error.URLError(ConnectionRefusedError(111, 'x')), 'isn’t answering'),
    (urllib.error.URLError('ftp error: 421'), 'isn’t answering'),
    (TimeoutError('timed out'), 'isn’t answering'),
    (_http(404), 'isn’t on the server'),
    (_http(503), 'error 503'),
    (OSError(errno.ENOSPC, 'No space left on device'), 'disk space'),
    (zipfile.BadZipFile('bad'), 'damaged'),
    (EOFError('Compressed file ended'), 'damaged'),
    (sword_bridge.NotMirrored('x'), 'only CrossWire'),
    (sword_bridge.NotInCatalogue('x'), 'saved catalogue'),
    (sword_bridge.BadModule('x'), 'SWORD module'),
    (ebible_bridge.TooFewVerses('eng', 0, 31102), 'copy you have was kept'),
    (LookupError('odd'), 'Something went wrong: odd'),
])
def test_each_failure_has_its_sentence(exc, words):
    assert words in fetch_errors.describe(exc)


def test_offline_beats_the_licence_explanation():
    """A licence-only module fetched with the Wi-Fi off: the lookup failed
    underneath, and that, not the licence, is what the reader can act on."""
    try:
        try:
            raise urllib.error.URLError(socket.gaierror(-3, 'x'))
        except urllib.error.URLError as inner:
            raise sword_bridge.NotMirrored('x') from inner
    except sword_bridge.NotMirrored as exc:
        assert 'reach the internet' in fetch_errors.describe(exc)
