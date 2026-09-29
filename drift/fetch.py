"""Constrained HTTP fetcher.

Rules (README, "How a claim is checked" and "Security posture"):
- HTTPS only.
- Only URLs that appear in the registry may be fetched; the caller passes the allowlist and this
  module refuses anything else. That includes every redirect hop: a hop is followed only when its
  target is the claim's one approved `redirect_to` destination AND is in the allowlist. At most
  MAX_REDIRECTS hops.
- One end-to-end deadline for the whole fetch, measured on a monotonic clock. The body is read with
  read1(), which returns after at most one underlying receive, and the socket timeout is shrunk to
  what is left of the deadline before every receive, so a server that trickles bytes cannot stretch
  a read past the deadline. The whole fetch (DNS, connect, TLS, headers, redirects, body) runs in a
  worker thread that the caller waits for only until the deadline: whatever blocks, control returns
  to the caller on time with FetchTimeout. (A lookup stuck inside the OS resolver cannot be
  cancelled; the abandoned worker ends when its own socket timeout or the resolver gives up.)
- A hard size cap enforced while reading in chunks. No JavaScript, no cookies, no retry storm.
- Polite, identifiable user agent.
- Fetched bytes are DATA. Nothing here interprets them as instructions.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "ai-security-architecture-map-drift/0.2 (+https://github.com/Double00kevin/ai-security-architecture-map)"
TIMEOUT_S = 20  # end-to-end deadline for one fetch, redirects and reads included
MAX_BYTES = 8_000_000  # PyPI JSON for large projects is ~2 MB; npm full docs can be larger, we use /latest
MAX_REDIRECTS = 3
CHUNK = 65_536
GRACE_S = 0.5  # extra wall time the caller waits beyond the deadline for the worker to report its own timeout

_now = time.monotonic  # seam for tests


class FetchRefused(Exception):
    """Raised before any network I/O (or before following a hop) when a URL violates the fetch rules."""


class FetchTooLarge(Exception):
    """Raised when a response exceeds MAX_BYTES."""


class FetchTimeout(Exception):
    """Raised when the end-to-end deadline passes."""


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    hops: tuple[str, ...] = ()


def _check_url(url: str, allowlist: frozenset[str]) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise FetchRefused(f"refused (not https): {url}")
    if not parts.netloc or parts.username or parts.password:
        raise FetchRefused(f"refused (bad host): {url}")
    if url not in allowlist:
        raise FetchRefused(f"refused (not in registry): {url}")


class _Deadline:
    def __init__(self, seconds: float):
        self.end = _now() + seconds
        self.seconds = seconds

    def remaining(self) -> float:
        left = self.end - _now()
        if left <= 0:
            raise FetchTimeout(f"fetch exceeded the {self.seconds:g} s end-to-end deadline")
        return left


class GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Check every hop BEFORE it is followed: https, in the allowlist, equal to the approved
    `redirect_to` destination, and no more than MAX_REDIRECTS hops. Follows 308 like 307."""

    def __init__(self, allowlist: frozenset[str], redirect_to: str | None, deadline: _Deadline):
        self.allowlist, self.redirect_to, self.deadline = allowlist, redirect_to, deadline
        self.hops: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        if len(self.hops) >= MAX_REDIRECTS:
            raise FetchRefused(f"refused (more than {MAX_REDIRECTS} redirects): {newurl}")
        if not newurl.startswith("https://"):
            raise FetchRefused(f"refused (redirected off https): {newurl}")
        if newurl != self.redirect_to:
            raise FetchRefused(f"refused (redirect target is not this claim's approved redirect_to): {newurl}")
        _check_url(newurl, self.allowlist)
        req.timeout = self.deadline.remaining()  # the next hop gets only what is left of the deadline
        self.hops.append(newurl)
        if code == 308:
            code = 307
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_307


def transport_handlers() -> list:
    """Seam for tests: extra handlers (e.g. an in-memory HTTPS handler) placed in the real opener."""
    return []


def build_opener(allowlist: frozenset[str], redirect_to: str | None, deadline: _Deadline):
    guard = GuardedRedirect(allowlist, redirect_to, deadline)
    return urllib.request.build_opener(guard, *transport_handlers()), guard


def _urlopen(opener, req, timeout):  # seam for tests that serve canned responses without an opener
    return opener.open(req, timeout=timeout)


def _set_socket_timeout(resp, seconds: float) -> None:
    """Best effort: shrink the per-operation socket timeout to what is left of the deadline."""
    fp = getattr(resp, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        try:
            sock.settimeout(max(seconds, 0.001))
        except OSError:
            pass


def _read_capped(resp, deadline: _Deadline, max_bytes: int, url: str) -> bytes:
    # read1: at most one underlying receive per call (read(n) on a buffered socket keeps receiving
    # until it has n bytes, however long a trickling server makes that take).
    read = getattr(resp, "read1", None) or resp.read
    chunks, total = [], 0
    while True:
        _set_socket_timeout(resp, deadline.remaining())
        try:
            chunk = read(min(CHUNK, max_bytes + 1 - total))
        except TimeoutError:  # the socket timeout was the rest of the deadline
            raise FetchTimeout(f"fetch exceeded the {deadline.seconds:g} s end-to-end deadline: {url}") from None
        deadline.remaining()
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise FetchTooLarge(f"response over {max_bytes} bytes: {url}")
    return b"".join(chunks)


def _fetch(url: str, allowlist: frozenset[str], accept: str, max_bytes: int, redirect_to: str | None,
           deadline: _Deadline) -> Fetched:
    opener, guard = build_opener(allowlist, redirect_to, deadline)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with _urlopen(opener, req, timeout=deadline.remaining()) as resp:  # noqa: S310 (scheme enforced above)
        final_url = resp.geturl()
        if final_url != url:  # belt and braces: whatever opened the URL, the end point must be approved
            if not final_url.startswith("https://"):
                raise FetchRefused(f"refused (redirected off https): {final_url}")
            if final_url != redirect_to:
                raise FetchRefused(f"refused (redirect target is not this claim's approved redirect_to): {final_url}")
            _check_url(final_url, allowlist)
        body = _read_capped(resp, deadline, max_bytes, url)
        return Fetched(url=url, final_url=final_url, status=resp.status,
                       content_type=resp.headers.get("content-type", ""), body=body, hops=tuple(guard.hops))


def fetch(url: str, allowlist: frozenset[str], *, accept: str = "*/*", timeout: float = TIMEOUT_S,
          max_bytes: int = MAX_BYTES, redirect_to: str | None = None) -> Fetched:
    """GET a registry URL under the fetch rules. Returns raw bytes; never decodes as instructions."""
    _check_url(url, allowlist)
    if redirect_to is not None:
        _check_url(redirect_to, allowlist)
    deadline = _Deadline(timeout)
    started = time.monotonic()  # real time for the caller's wait, whatever _now is patched to
    outcome: list = []

    def work() -> None:
        try:
            outcome.append((True, _fetch(url, allowlist, accept, max_bytes, redirect_to, deadline)))
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread below
            outcome.append((False, e))

    worker = threading.Thread(target=work, name="drift-fetch", daemon=True)
    worker.start()
    worker.join(max(0.0, timeout - (time.monotonic() - started)) + GRACE_S)
    if not outcome:
        raise FetchTimeout(f"fetch exceeded the {timeout:g} s end-to-end deadline (connect, headers or a "
                           f"redirect did not finish): {url}")
    ok, value = outcome[0]
    if not ok:
        raise value
    return value
