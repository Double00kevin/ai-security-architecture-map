"""The fetcher only fetches registry URLs, over HTTPS, within a timeout and a size cap."""

import socket

import pytest

from drift import fetch as F
from tests.conftest import CannedHTTPS, claim

ALLOW = frozenset({"https://pypi.org/pypi/example/json"})


def test_refuses_http_before_any_network(http):
    with pytest.raises(F.FetchRefused, match="not https"):
        F.fetch("http://pypi.org/pypi/example/json", frozenset({"http://pypi.org/pypi/example/json"}))
    assert http.calls == []


def test_refuses_url_not_in_registry_allowlist(http):
    http.add("https://evil.example/x", b"{}")
    with pytest.raises(F.FetchRefused, match="not in registry"):
        F.fetch("https://evil.example/x", ALLOW)
    assert http.calls == []


def test_refuses_userinfo_in_url(http):
    url = "https://user:pw@pypi.org/pypi/example/json"
    with pytest.raises(F.FetchRefused):
        F.fetch(url, frozenset({url}))
    assert http.calls == []


def test_refuses_redirect_off_https(http):
    http.add("https://pypi.org/pypi/example/json", b"{}", final_url="http://pypi.org/pypi/example/json")
    with pytest.raises(F.FetchRefused, match="off https"):
        F.fetch("https://pypi.org/pypi/example/json", ALLOW)


def test_refuses_final_url_off_allowlist_even_if_opener_followed_it(http):
    http.add("https://pypi.org/pypi/example/json", b"{}", final_url="https://evil.example/x")
    with pytest.raises(F.FetchRefused, match="redirect_to"):
        F.fetch("https://pypi.org/pypi/example/json", ALLOW)


def test_passes_timeout_and_user_agent(http):
    http.add("https://pypi.org/pypi/example/json", b"{}")
    F.fetch("https://pypi.org/pypi/example/json", ALLOW)
    (url, timeout), = http.calls
    assert F.TIMEOUT_S == 20 and 19 < timeout <= 20  # what is left of the 20 s end-to-end deadline


def test_timeout_propagates_as_error(http):
    http.fail("https://pypi.org/pypi/example/json", socket.timeout("timed out"))
    with pytest.raises(socket.timeout):
        F.fetch("https://pypi.org/pypi/example/json", ALLOW)


def test_size_cap_enforced(http):
    http.add("https://pypi.org/pypi/example/json", b"x" * (F.MAX_BYTES + 1))
    with pytest.raises(F.FetchTooLarge):
        F.fetch("https://pypi.org/pypi/example/json", ALLOW)


def test_size_cap_allows_exactly_max(http):
    http.add("https://pypi.org/pypi/example/json", b"x" * F.MAX_BYTES)
    assert len(F.fetch("https://pypi.org/pypi/example/json", ALLOW).body) == F.MAX_BYTES


def test_allowlist_is_derived_only_from_registry():
    from drift import registry

    claims = [claim(source_type="github_release", source_url="https://github.com/o/r"),
              claim(id="L01-b", source_type="npm", source_url="https://www.npmjs.com/package/p")]
    allow = registry.allowlist(claims)
    assert "https://api.github.com/repos/o/r/releases/latest" in allow
    assert "https://api.github.com/repos/o/r" in allow  # repo metadata, for `archived`
    assert "https://registry.npmjs.org/p/latest" in allow
    assert not any(u.startswith("http://") for u in allow)
    assert len(allow) == 2 + 4 + 1  # two source_urls + four github api urls + one npm api url


def test_redirect_to_joins_the_allowlist():
    from drift import registry

    allow = registry.allowlist([claim(source_type="page_section", locator="x", source_url=SRC, redirect_to=CANON)])
    assert {SRC, CANON} <= allow


# ---- the REAL opener and the REAL redirect handler, with only the HTTPS transport canned ----

SRC = "https://vendor.example/page"
CANON = "https://vendor.example/page/"
OTHER = "https://other.example/also-in-registry"


@pytest.fixture
def canned(monkeypatch):
    routes: dict = {}
    handler = CannedHTTPS(routes)
    monkeypatch.setattr(F, "transport_handlers", lambda: [handler])
    return routes, handler


def test_real_handler_follows_only_the_approved_redirect_to(canned):
    routes, h = canned
    routes[SRC] = (301, {"Location": CANON}, b"")
    routes[CANON] = (200, {"Content-Type": "text/html"}, b"<p>ok</p>")
    r = F.fetch(SRC, frozenset({SRC, CANON}), redirect_to=CANON)
    assert r.body == b"<p>ok</p>" and r.final_url == CANON and r.hops == (CANON,)
    assert h.seen == [SRC, CANON]


def test_real_handler_refuses_hop_to_another_registry_url_before_following_it(canned):
    """Being somewhere in the registry is not enough: the hop must be this claim's redirect_to."""
    routes, h = canned
    routes[SRC] = (302, {"Location": OTHER}, b"")
    routes[OTHER] = (200, {}, b"should never be fetched")
    with pytest.raises(F.FetchRefused, match="redirect_to"):
        F.fetch(SRC, frozenset({SRC, OTHER}))
    assert h.seen == [SRC]  # the hop was checked before it was followed


def test_real_handler_refuses_hop_off_allowlist(canned):
    routes, h = canned
    routes[SRC] = (307, {"Location": "https://evil.example/x"}, b"")
    with pytest.raises(F.FetchRefused):
        F.fetch(SRC, frozenset({SRC}), redirect_to=None)
    assert h.seen == [SRC]


def test_real_handler_refuses_relative_hop_off_https(canned):
    routes, h = canned
    routes[SRC] = (308, {"Location": "http://vendor.example/page"}, b"")
    with pytest.raises(F.FetchRefused, match="off https"):
        F.fetch(SRC, frozenset({SRC}))


def test_redirect_to_must_itself_be_in_the_allowlist(canned):
    with pytest.raises(F.FetchRefused, match="not in registry"):
        F.fetch(SRC, frozenset({SRC}), redirect_to=CANON)


def test_redirect_depth_is_capped_at_three(canned, monkeypatch):
    routes, h = canned
    chain = [f"https://vendor.example/{i}" for i in range(6)]
    for a, b in zip(chain, chain[1:]):
        routes[a] = (302, {"Location": b}, b"")
    routes[chain[-1]] = (200, {}, b"end")

    # approve every hop so only the depth cap can stop it
    class AnyApproved(F.GuardedRedirect):
        def __init__(self, allowlist, redirect_to, deadline):
            super().__init__(allowlist, redirect_to, deadline)

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.redirect_to = newurl
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    monkeypatch.setattr(F, "GuardedRedirect", AnyApproved)
    with pytest.raises(F.FetchRefused, match="more than 3 redirects"):
        F.fetch(chain[0], frozenset(chain))
    assert h.seen == chain[:4]  # the original + 3 hops, never the 4th


class FakeClock:
    def __init__(self, step: float):
        self.t, self.step = 1000.0, step

    def __call__(self):
        return self.t

    def advance(self):
        self.t += self.step


def test_end_to_end_deadline_covers_slow_chunked_reads(monkeypatch):
    """Every read is individually fast (so a per-socket-op timeout never fires), but the whole fetch is
    slow: 40 reads x 1 s > 20 s. The monotonic end-to-end deadline stops it."""
    clock = FakeClock(step=1.0)
    monkeypatch.setattr(F, "_now", clock)
    routes = {SRC: (200, {}, b"x" * 40 * 1024)}
    handler = CannedHTTPS(routes, slow={SRC: clock})
    monkeypatch.setattr(F, "transport_handlers", lambda: [handler])
    with pytest.raises(F.FetchTimeout, match="20 s"):
        F.fetch(SRC, frozenset({SRC}))


def test_deadline_is_shared_across_redirect_hops(canned, monkeypatch):
    clock = FakeClock(step=0)
    monkeypatch.setattr(F, "_now", clock)
    routes, h = canned

    real = h.https_open

    def slow_open(req):
        clock.t += 15  # each hop costs 15 s; two hops blow the 20 s budget
        return real(req)

    h.https_open = slow_open
    routes[SRC] = (301, {"Location": CANON}, b"")
    routes[CANON] = (200, {}, b"ok")
    with pytest.raises(F.FetchTimeout):
        F.fetch(SRC, frozenset({SRC, CANON}), redirect_to=CANON)


def test_chunked_read_enforces_cap_on_real_opener(canned):
    routes, _ = canned
    routes[SRC] = (200, {}, b"y" * 5000)
    with pytest.raises(F.FetchTooLarge):
        F.fetch(SRC, frozenset({SRC}), max_bytes=4096)
    assert len(F.fetch(SRC, frozenset({SRC}), max_bytes=5000).body) == 5000


@pytest.mark.allow_network_attempt
def test_global_guard_blocks_real_sockets(no_network):
    import socket as S
    with pytest.raises(OSError):
        S.create_connection(("example.invalid", 443), timeout=1)
    assert no_network  # the attempt was recorded; without the marker the test would fail at teardown


# ---- R4 (PR #5 review): the deadline must hold against a real socket, not only a fake clock ----

import http.client
import socket
import threading
import time

_REAL_CONNECT = socket.socket.connect  # captured at import, before the no-network guard patches it


def _loopback_pair():
    """A connected pair of local sockets. AF_UNIX where available (no connect call at all); on Windows
    a 127.0.0.1 listener, connected with the pre-guard connect. Nothing leaves the machine."""
    if hasattr(socket, "AF_UNIX"):
        return socket.socketpair()
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    csock = socket.socket()
    _REAL_CONNECT(csock, lsock.getsockname())
    ssock, _ = lsock.accept()
    lsock.close()
    return ssock, csock


def _trickle(sock, head: bytes, pieces: int, gap: float):
    def run():
        try:
            sock.sendall(head)
            for _ in range(pieces):
                time.sleep(gap)
                sock.sendall(b"0123456789")
        except OSError:
            pass
        finally:
            sock.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_trickling_server_cannot_stretch_a_read_past_the_deadline():
    """A real http.client.HTTPResponse over a local socket: 10 bytes every 40 ms for 1.2 s. Each
    receive is fast, so a per-socket timeout never fires; the old read(65536) kept receiving until the
    body was complete. With read1 and the timeout recomputed per receive, control returns on time."""
    server, client = _loopback_pair()
    _trickle(server, b"HTTP/1.1 200 OK\r\nContent-Length: 300\r\n\r\n", pieces=30, gap=0.04)
    resp = http.client.HTTPResponse(client)
    resp.begin()
    t0 = time.monotonic()
    with pytest.raises(F.FetchTimeout):
        F._read_capped(resp, F._Deadline(0.15), 10_000, "https://example.invalid/x")
    elapsed = time.monotonic() - t0
    client.close()
    assert elapsed < 0.3, f"read returned after {elapsed:.3f}s against a 0.15s deadline"


def test_caller_gets_control_back_when_connect_or_headers_hang(monkeypatch):
    """Whatever blocks before the body (DNS, connect, TLS, headers), fetch() returns on time."""
    release = threading.Event()

    def hangs(opener, req, timeout):
        release.wait(5)
        raise OSError("released")

    monkeypatch.setattr(F, "_urlopen", hangs)
    t0 = time.monotonic()
    with pytest.raises(F.FetchTimeout, match="did not finish"):
        F.fetch(SRC, frozenset({SRC}), timeout=0.3)
    elapsed = time.monotonic() - t0
    release.set()
    assert elapsed < 0.3 + F.GRACE_S + 0.3, f"fetch returned after {elapsed:.3f}s"


def test_worker_errors_are_raised_in_the_caller(monkeypatch):
    def refuses(opener, req, timeout):
        raise F.FetchRefused("refused (test)")

    monkeypatch.setattr(F, "_urlopen", refuses)
    with pytest.raises(F.FetchRefused, match=r"refused \(test\)"):
        F.fetch(SRC, frozenset({SRC}))
