"""RSS 2.0 / Atom feeds: newest entry title and date.

A syndication feed has no business carrying a DTD. The document is first run through an expat parser
whose DOCTYPE and ENTITY declaration handlers raise, so a declaration is refused wherever it sits
(after any amount of whitespace, in any encoding expat reads: UTF-8, UTF-16 LE/BE with a BOM, Latin-1).
Only a document that passes that scan is handed to ElementTree.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.parsers import expat

from ..fetch import fetch

ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


class _Declaration(Exception):
    pass


def refuse_declarations(body: bytes) -> None:
    """Parse the whole document with expat; raise SourceError on any DOCTYPE or ENTITY declaration."""
    from . import SourceError

    p = expat.ParserCreate()
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def doctype(*_a):
        raise _Declaration("DOCTYPE")

    def entity(*_a):
        raise _Declaration("ENTITY")

    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = entity
    p.UnparsedEntityDeclHandler = entity
    p.ExternalEntityRefHandler = lambda *_a: (_ for _ in ()).throw(_Declaration("external entity"))
    try:
        p.Parse(body, True)
    except _Declaration as e:
        raise SourceError(f"feed contains a {e} declaration; refused") from None
    except expat.ExpatError as e:
        raise SourceError(f"feed is not well-formed XML: {e}") from None


def check(c: dict, allow: frozenset[str]):
    from . import Evidence, SourceError

    body = fetch(c["source_url"], allow, accept=ACCEPT, redirect_to=c.get("redirect_to")).body
    refuse_declarations(body)
    root = ET.fromstring(body)  # noqa: S314 - declarations refused by the expat pass above
    item = root.find(".//item")
    if item is not None:
        title = (item.findtext("title") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
    else:
        entry = root.find(".//a:entry", ATOM)
        if entry is None:
            raise SourceError("feed has no item/entry")
        title = (entry.findtext("a:title", default="", namespaces=ATOM) or "").strip()
        date = (entry.findtext("a:updated", default="", namespaces=ATOM) or "").strip()
    return Evidence(date[:25] or None, f"latest entry: {title[:120]} ({date[:25]})")
