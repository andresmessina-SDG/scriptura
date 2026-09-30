"""Every request names Scriptura, and nothing about the reader.

urllib's own `Python-urllib/3.x` tells a host nothing and eBible refuses it
with a 403, so the eBible fetches used to claim to be a browser. The app now
sends one honest User-Agent: explicitly where a fetch also runs from tools/,
and through an opener installed at launch for everything else.
"""

import http.server
import pathlib
import threading
import urllib.request

import _version
import main

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_user_agent_names_the_app_and_no_one_else():
    ua = _version.USER_AGENT
    assert ua.startswith(f'Scriptura/{_version.__version__} ')
    assert '@' not in ua


def test_a_request_with_no_header_of_its_own_sends_ours():
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers['User-Agent'])
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    main._name_ourselves_to_hosts()
    try:
        urllib.request.urlopen(
            f'http://127.0.0.1:{server.server_port}/', timeout=5).close()
    finally:
        urllib.request.install_opener(None)
        server.server_close()
    assert seen == [_version.USER_AGENT]


def test_nothing_poses_as_a_browser():
    offenders = [str(p.relative_to(ROOT))
                 for d in (ROOT, ROOT / 'tools')
                 for p in d.glob('*.py')
                 if 'Mozilla/5.0' in p.read_text(encoding='utf-8')]
    assert offenders == []
