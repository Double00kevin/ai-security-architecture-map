"""Shared test plumbing. No test touches the network: urlopen is replaced by an in-memory server,
and a global guard fails any test that tries to open a real socket or resolve a name."""

from __future__ import annotations

import io
import socket
import urllib.error
import urllib.request
from email.message import Message

import pytest

import drift.fetch as fetch_mod


class NetworkBlocked(OSError):
    """Raised by the global guard; the test is also failed at teardown even if the code swallowed this."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Any real connect or DNS lookup fails the test. Code under test often catches OSError (a fetch
    error becomes an 'error' finding), so the attempt is recorded and the test is failed at teardown."""
    attempts: list[str] = []

    def refuse(what):
        def _refuse(*a, **kw):
            attempts.append(f"{what}{a[1:2] if what.startswith('socket.') else a[:1]}")
            raise NetworkBlocked(f"network access in tests is forbidden ({what})")
        return _refuse

    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    yield attempts
    if attempts and not request.node.get_closest_marker("allow_network_attempt"):
        pytest.fail(f"test attempted real network access: {attempts}")


class FakeResponse(io.BytesIO):
    def __init__(self, url: str, status: int, content_type: str, body: bytes, final_url: str | None = None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["content-type"] = content_type
        self._url = final_url or url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class FakeHTTP:
    """Serve canned responses. routes[url] = (status, content_type, body[, final_url]) or an Exception to raise."""

    def __init__(self):
        self.routes: dict[str, object] = {}
        self.calls: list[tuple[str, float | None]] = []

    def add(self, url: str, body: bytes | str, content_type: str = "application/json", status: int = 200,
            final_url: str | None = None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.routes[url] = (status, content_type, body, final_url)

    def fail(self, url: str, exc: Exception):
        self.routes[url] = exc

    def __call__(self, *args, timeout=None):  # (opener, req) now; (req) before the real-opener seam existed
        req = args[-1]
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.calls.append((url, timeout))
        r = self.routes.get(url)
        if r is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", Message(), io.BytesIO(b"{}"))
        if isinstance(r, Exception):
            raise r
        status, ct, body, final = r
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "Error", Message(), io.BytesIO(body))
        return FakeResponse(url, status, ct, body, final)


class CannedHTTPS(urllib.request.HTTPSHandler):
    """Replaces the real HTTPS transport inside a REAL opener, so redirects go through the real
    GuardedRedirect handler. routes[url] = (status, headers dict, body)."""

    def __init__(self, routes: dict, slow: dict | None = None):
        super().__init__()
        self.routes, self.slow, self.seen = routes, slow or {}, []

    def https_open(self, req):
        import urllib.response
        self.seen.append(req.full_url)
        status, headers, body = self.routes.get(req.full_url, (404, {}, b"not found"))
        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        fp = SlowBytes(body, self.slow.get(req.full_url)) if req.full_url in self.slow else io.BytesIO(body)
        resp = urllib.response.addinfourl(fp, msg, req.full_url, status)
        resp.msg = "canned"
        return resp


class SlowBytes(io.BytesIO):
    """Each read() advances a fake monotonic clock by `step` seconds."""

    def __init__(self, body: bytes, clock):
        super().__init__(body)
        self.clock = clock

    def read(self, n=-1):
        self.clock.advance()
        return super().read(min(n, 1024) if n and n > 0 else 1024)

    read1 = read  # the fetcher reads with read1 when the response has it


@pytest.fixture
def http(monkeypatch) -> FakeHTTP:
    fake = FakeHTTP()
    monkeypatch.setattr(fetch_mod, "_urlopen", fake)
    return fake


def claim(**kw) -> dict:
    """A minimal valid claim record; override any field."""
    base = {
        "id": "L01-example", "layer": 1, "layer_name": "Models & Hosting", "tool": "Example",
        "claim": "Example is active", "status": "active", "owner": None,
        "source_type": "pypi", "source_url": "https://pypi.org/project/example/",
        "locator": None, "snapshot": None, "snapshot_hash": None, "last_version": None,
        "fetched_at": None,
    }
    base.update(kw)
    return base


def reviewed(c: dict, when: str = "2026-09-28", outcome: str = "supported", by: str = "tester") -> dict:
    """Give a claim evidence that supports an availability assertion, and a valid review of it."""
    from drift import registry
    from drift.snapshot import sha256

    if not c.get("snapshot"):
        c["snapshot"] = f"pypi {c['tool']} 1.0.0"
        c["snapshot_hash"] = sha256(c["snapshot"])
    c.setdefault("assertions", ["availability"])
    if not c.get("supports"):
        c["supports"] = list(c["assertions"])
    c.update(reviewed_at=when, reviewed_by=by, review_outcome=outcome)
    c["review_hash"] = registry.review_hash(c)
    c["review_claim_hash"] = registry.claim_hash(c)
    c["review_fetched_at"] = registry.fetch_dates(c)
    for k in registry.APPROVAL_KEYS:
        c.pop(k, None)
    c["review_event_hash"] = registry.review_event_hash(c)
    return c
