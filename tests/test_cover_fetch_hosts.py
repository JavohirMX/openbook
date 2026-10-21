import http.server
import threading

import pytest
import requests

from books import covers

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _Handler(http.server.BaseHTTPRequestHandler):
    redirect_to = None

    def do_GET(self):
        if self.path == "/redirect" and _Handler.redirect_to:
            self.send_response(302)
            self.send_header("Location", _Handler.redirect_to)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *args):
        pass


@pytest.fixture
def servers():
    made = []
    for _ in range(2):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
    yield [s.server_address[1] for s in made]
    for s in made:
        s.shutdown()
        s.server_close()


@pytest.fixture(autouse=True)
def fresh_session(monkeypatch):
    monkeypatch.setattr(covers, "_session", None)


def test_loopback_is_blocked_by_default(servers, settings):
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = False
    with pytest.raises(requests.ConnectionError):
        covers._get_session().get(f"http://127.0.0.1:{servers[0]}/", timeout=3)
    assert covers._fetch_cover_bytes(f"http://127.0.0.1:{servers[0]}/c.png") is None


def test_localhost_name_is_blocked_by_default(servers, settings):
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = False
    assert covers._fetch_cover_bytes(f"http://localhost:{servers[0]}/c.png") is None


def test_opt_in_setting_allows_private_hosts(servers, settings):
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = True
    got = covers._fetch_cover_bytes(f"http://127.0.0.1:{servers[0]}/c.png")
    assert got is not None and got[0] == PNG


def test_redirect_to_a_blocked_address_is_refused(servers, settings, monkeypatch):
    # Allow only the first server, as if it were a public host; it redirects to the second.
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = False
    first, second = servers
    monkeypatch.setattr(
        covers, "_peer_is_allowed", lambda sock: sock.getpeername()[1] == first
    )
    _Handler.redirect_to = f"http://127.0.0.1:{second}/c.png"
    try:
        assert covers._fetch_cover_bytes(f"http://127.0.0.1:{first}/c.png") is not None
        assert covers._fetch_cover_bytes(f"http://127.0.0.1:{first}/redirect") is None
    finally:
        _Handler.redirect_to = None


def test_environment_proxies_are_ignored(servers, settings, monkeypatch):
    # Through a proxy the peer check would vouch for the proxy's address, not the
    # cover host's, so cover fetches ignore proxy environment variables. A
    # localhost target alone could bypass an env proxy for other reasons, so
    # also assert the adapter is called with no proxies at all.
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = True
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    session = covers._get_session()
    assert session.trust_env is False
    sent = {}
    adapter = session.get_adapter("http://example.invalid/")
    real_send = adapter.send

    def spy_send(request, **kwargs):
        sent.update(kwargs)
        return real_send(request, **kwargs)

    monkeypatch.setattr(adapter, "send", spy_send)
    got = covers._fetch_cover_bytes(f"http://127.0.0.1:{servers[0]}/c.png")
    assert got is not None and got[0] == PNG
    assert sent["proxies"] == {}


@pytest.mark.parametrize(
    "ip,expected",
    [("8.8.8.8", True), ("10.1.2.3", False), ("192.168.0.5", False), ("127.0.0.1", False),
     ("169.254.169.254", False), ("100.64.0.1", False), ("::1", False), ("fe80::1", False),
     ("fd00::1", False), ("::ffff:10.0.0.1", False), ("2606:4700:4700::1111", True)],
)
def test_address_classification(ip, expected, settings):
    settings.COVER_FETCH_ALLOW_PRIVATE_HOSTS = False

    class FakeSock:
        def getpeername(self):
            return (ip, 80)

    assert covers._peer_is_allowed(FakeSock()) is expected
