"""Bounded official-source discovery and immutable Bank of Canada reference data.

Retrieved documents are untrusted data: JavaScript is inspected, never executed.
Only the approved Bank of Canada HTTPS origin is reachable by this connector.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import time
import queue
import threading
from datetime import date
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .core import SafetyError, canonical_json, digest, utcnow

ORIGIN = "https://www.bankofcanada.ca"
DOCS = ORIGIN + "/valet/docs"
TERMS = ORIGIN + "/terms/"
ROBOTS = ORIGIN + "/robots.txt"
SERIES = "FXUSDCAD"
START, END = "2023-01-01", "2025-12-31"
USER_AGENT = "SIQEQuestResearch/1.0"
LIMITATIONS = [
    "Bank of Canada indicative daily average reference rates; not executable prices or an FX execution benchmark.",
    "No OHLC, volume, bid/ask, financing or carry data; no missing-day filling.",
    "Publication time and first historical availability are unknown; current retrieval is not point-in-time as-reported history.",
    "Attribution: Bank of Canada. Normalization converts decimal strings to floats; underlying data sourced from LSEG (formerly Refinitiv).",
    "Third-party rights are not licensed by the Bank's general reproduction permission; redistribution/commercial use needs separate rights review.",
]


class SourceError(SafetyError):
    """An explicit, bounded retrieval, permission, or data-quality failure."""


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        target = (
            values.get("href")
            if tag in {"a", "link"}
            else values.get("src")
            if tag == "script"
            else None
        )
        if target:
            relation = (
                "feed"
                if values.get("type", "")
                in {"application/rss+xml", "application/atom+xml"}
                else values.get("rel", "document")
            )
            if "citation" in values.get("rel", ""):
                relation = "citation"
            self.links.append((target, relation))
        if tag == "meta" and values.get("name", "").lower() in {
            "citation_pdf_url",
            "citation_fulltext_html_url",
            "citation_reference",
        }:
            self.links.append((values.get("content", ""), "citation"))


class _PolicyContent(HTMLParser):
    """Read complete legal content without rendering or executing remote HTML."""

    _ignored = {"script", "style", "noscript"}
    _chrome = {"head", "nav", "header", "footer", "aside"}
    _blocks = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_seen = False
        self.in_main = False
        self.main_closed = False
        self.ignored = []
        self.chrome = []
        self.chrome_invalid = False
        self.main_text, self.full_text = [], []
        self.main_links, self.full_links = [], []
        self.base = TERMS
        self.base_seen = False

    def _text(self, value):
        if self.in_main:
            self.main_text.append(value)
        elif not self.chrome:
            self.full_text.append(value)

    def handle_starttag(self, tag, attrs):
        if tag in self._ignored:
            self.ignored.append(tag)
            return
        if self.ignored:
            return
        values = dict(attrs)
        for name in ("href", "alt"):
            if sum(key == name for key, _ in attrs) > 1:
                raise SourceError("ambiguous terms content attribute")
        if tag == "base" and values.get("href") is not None:
            if self.base_seen:
                raise SourceError("ambiguous terms document base URL")
            self.base_seen = True
            self.base = urljoin(TERMS, values["href"].strip())
        if tag == "main":
            if self.main_seen:
                raise SourceError("terms must have one complete main content scope")
            if self.chrome:
                raise SourceError("terms main content nested inside site chrome")
            self.main_seen = self.in_main = True
        if not self.in_main and tag in self._chrome:
            self.chrome.append(tag)
        if tag in self._blocks:
            self._text(" ")
        if self.in_main or not self.chrome:
            links = self.main_links if self.in_main else self.full_links
            if tag in {"a", "area"} and values.get("href") is not None:
                # Keep order and duplicates: a changed legal cross-reference matters.
                links.append(values["href"].strip())
            if tag in {"img", "area"} and values.get("alt"):
                self._text(values["alt"])

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag in self._blocks:
            self._text(" ")
        if tag == "main":
            if not self.in_main:
                raise SourceError("unmatched terms main content boundary")
            self.in_main = False
            self.main_closed = True
        elif not self.in_main and tag in self._chrome:
            if not self.chrome or self.chrome[-1] != tag:
                self.chrome_invalid = True
            else:
                self.chrome.pop()

    def handle_startendtag(self, tag, attrs):
        if tag in self._ignored or tag in self._chrome or tag == "main":
            raise SourceError("ambiguous self-closing terms content boundary")
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not self.ignored:
            self._text(data)

    def content(self):
        if self.ignored or self.rawdata.strip():
            raise SourceError("incomplete terms content markup; manual review required")
        if self.main_seen:
            if not self.main_closed or self.in_main:
                raise SourceError(
                    "incomplete terms main content; manual review required"
                )
            parts, links, scope = self.main_text, self.main_links, "main"
        else:
            if self.chrome or self.chrome_invalid:
                raise SourceError("ambiguous terms content; manual review required")
            parts, links, scope = self.full_text, self.full_links, "full_visible"
        text = " ".join("".join(parts).split())
        if len(text) < 80 or len(text.split()) < 12:
            raise SourceError("meaningful complete terms content missing")
        content = {
            "text": text,
            "hrefs": [urljoin(self.base, target) for target in links],
        }
        return text, {
            "policy_content_sha256": digest(content),
            "policy_content_method": "htmlparser-visible-text-hrefs-v1",
            "policy_content_source": scope,
        }


def _policy_content(body):
    parser = _PolicyContent()
    try:
        parser.feed(body.decode("utf-8", errors="strict"))
        parser.close()
        return parser.content()
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SourceError("terms content cannot be extracted safely") from exc


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connect to an already validated IP while authenticating the original host."""

    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _network_transport(url, headers, timeout, max_bytes):
    """No proxy, automatic redirect, cookies, credentials or DNS rebinding window."""
    parsed = urlsplit(url)
    deadline = time.monotonic() + timeout
    resolved = queue.Queue(maxsize=1)

    def resolve():
        try:
            resolved.put(
                (
                    True,
                    socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM),
                )
            )
        except OSError as exc:
            resolved.put((False, exc))

    threading.Thread(target=resolve, daemon=True).start()
    try:
        success, addresses = resolved.get(timeout=timeout)
    except queue.Empty as exc:
        raise SourceError("DNS lookup timeout") from exc
    if not success:
        raise SourceError("DNS lookup failed")
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise SourceError("DNS resolved to a non-public endpoint")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError("network deadline exhausted")
    conn = _PinnedHTTPS(parsed.hostname, addresses[0][4][0], remaining)
    try:
        conn.request(
            "GET",
            urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
            headers=headers,
        )
        response = conn.getresponse()
        metadata = {key.lower(): value for key, value in response.getheaders()}
        length = metadata.get("content-length")
        if length is not None and int(length) > max_bytes:
            raise SourceError("response exceeds byte cap")
        chunks = []
        size = 0
        while size <= max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceError("response deadline exhausted")
            if conn.sock is not None:
                conn.sock.settimeout(remaining)
            block = response.read1(min(65536, max_bytes + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        body = b"".join(chunks)
        if len(body) > max_bytes:
            raise SourceError("response exceeds byte cap")
        return {
            "status": response.status,
            "headers": metadata,
            "body": body,
            "url": url,
        }
    finally:
        conn.close()


class SourceHunter:
    """Discover from official metadata; retrieve only public, research-only content.

    Optional transport(url, headers, timeout, max_bytes) returns a dict with status,
    headers, body bytes and url. A transport MUST NOT follow redirects internally.
    Tests use this seam; ordinary callers use the pinned, certificate-checked path.
    """

    def __init__(self, store, transport=None, clock=utcnow, sleeper=time.sleep):
        self.store = store
        self.transport = transport or _network_transport
        self.clock = clock
        self.sleeper = sleeper
        self._policy = None
        self._last_request = 0.0
        self.request_count = 0

    def _begin(self, limit=4, seconds=24):
        self.store.authorize("research.sources")
        self.request_count = 0
        self._limit = (
            min(
                limit,
                max(0, int(self.store.config.get("max_network_requests_per_cycle", 4))),
            )
            if limit <= 4
            else limit
        )
        self._deadline = time.monotonic() + seconds
        self._bytes = 0
        self._policy = None
        self._evidence = []
        self._phase_size = min(
            4, int(self.store.config.get("max_network_requests_per_cycle", 4))
        )
        if self._phase_size < 1:
            raise SourceError("network requests disabled by configuration")
        self._phases = []
        if limit > 4:
            self._limit = min(limit, 4 * self._phase_size)

    def _phase_accounting(self):
        return [
            {
                "phase": index + 1,
                "request_count": count,
                "request_limit": self._phase_size,
            }
            for index, count in enumerate(self._phases)
        ]

    def _safe_url(self, url):
        if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
            raise SourceError("unsafe URL")
        parsed = urlsplit(url)
        allowed = self.store.config.get("allowed_domains", [])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.bankofcanada.ca"
            or parsed.hostname not in allowed
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise SourceError(
                "only the approved Bank of Canada HTTPS origin is allowed"
            )
        return urlunsplit(
            ("https", "www.bankofcanada.ca", parsed.path or "/", parsed.query, "")
        )

    def _request(self, url, conditional=None, bootstrap=False):
        url = self._safe_url(url)
        original = url
        for _ in range(3):
            if not bootstrap:
                if self._policy is None or not self._policy.can_fetch(USER_AGENT, url):
                    raise SourceError("robots permission missing or denied")
            remaining = self._deadline - time.monotonic()
            if self.request_count >= self._limit or remaining <= 0:
                raise SourceError("request/time budget exhausted")
            interval = (
                max(1.0, float(self._policy.crawl_delay(USER_AGENT) or 0))
                if self._policy
                else 1.0
            )
            if self._policy:
                rate = self._policy.request_rate(USER_AGENT)
                if rate:
                    interval = max(interval, rate.seconds / rate.requests)
            delay = max(0.0, interval - (time.monotonic() - self._last_request))
            if delay >= remaining:
                raise SourceError("robots delay exceeds operation time budget")
            if delay:
                self.sleeper(delay)
            self.request_count += 1
            phase_index = (self.request_count - 1) // self._phase_size
            if phase_index == len(self._phases):
                self._phases.append(0)
            self._phases[phase_index] += 1
            self._last_request = time.monotonic()
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html,text/plain,*/*",
                "Accept-Encoding": "identity",
            }
            headers.update(conditional or {})
            cap = min(2_000_000, 8_000_000 - self._bytes)
            if cap <= 0:
                raise SourceError("operation byte budget exhausted")
            try:
                response = self.transport(
                    url,
                    headers,
                    min(5.0, max(0.1, self._deadline - time.monotonic())),
                    cap,
                )
                status = int(response["status"])
                body = response["body"]
                meta = {
                    str(k).lower(): str(v)
                    for k, v in response.get("headers", {}).items()
                }
                if not isinstance(body, bytes) or len(body) > cap:
                    raise SourceError("invalid or oversized transport response")
                if self._safe_url(response.get("url", url)) != url:
                    raise SourceError("transport followed an unvalidated redirect")
                self._bytes += len(body)
                blob = self.store.put_blob(
                    body, meta.get("content-type", "application/octet-stream")
                )
                evidence = {
                    "method": "GET",
                    "request_url": url,
                    "original_url": original,
                    "status": status,
                    "retrieved_at": self.clock(),
                    "phase": phase_index + 1,
                    "phase_request_number": self._phases[phase_index],
                    "headers": {
                        k: meta[k]
                        for k in ("etag", "last-modified", "content-type", "date")
                        if k in meta
                    },
                    "raw": blob,
                }
                self._evidence.append(evidence)
                self.store.record("source_retrieval", digest(evidence), evidence)
                if status in {301, 302, 303, 307, 308}:
                    url = self._safe_url(urljoin(url, meta.get("location", "")))
                    if not meta.get("location"):
                        raise SourceError("redirect without Location")
                    continue
                if status not in {200, 304}:
                    raise SourceError(
                        "HTTP status "
                        + str(status)
                        + "; no retry or restriction bypass"
                    )
                return body, evidence
            except SourceError:
                raise
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                http.client.HTTPException,
            ) as exc:
                raise SourceError("retrieval failed: " + type(exc).__name__) from exc
        raise SourceError("redirect cap exceeded")

    def _permissions(self):
        body, robot_evidence = self._request(ROBOTS, bootstrap=True)
        text = body.decode("utf-8", errors="strict")
        if not re.search(r"(?im)^\s*user-agent\s*:", text) or "<html" in text.lower():
            raise SourceError("robots response is not a usable policy")
        policy = RobotFileParser()
        policy.parse(text.splitlines())
        self._policy = policy
        terms_body, terms_evidence = self._request(TERMS)
        terms_text, fingerprint = _policy_content(terms_body)
        terms_text = terms_text.lower()
        requirements = (
            "bank of canada",
            "attribution",
            "third-party",
            "indicative",
            "lseg",
            "circumvent",
        )
        if not all(word in terms_text for word in requirements):
            raise SourceError(
                "terms changed or restrictions cannot be established; manual review required"
            )
        previous = self.store.records("source_policy")
        if previous:
            # Parse the accepted raw snapshot with the same method, including legacy
            # records without fingerprints. Never rewrite immutable policy history.
            prior_terms = previous[-1]["value"]["terms"]
            _, prior_fingerprint = _policy_content(
                self.store.read_blob(prior_terms["raw"])
            )
            if (
                prior_fingerprint["policy_content_sha256"]
                != fingerprint["policy_content_sha256"]
            ):
                raise SourceError(
                    "terms content changed; explicit policy review required before retrieval"
                )
        terms_evidence = dict(terms_evidence, **fingerprint)
        policy_record = {
            "robots": robot_evidence,
            "terms": terms_evidence,
            "status": "research_only_restricted",
            "redistribution": "NOT_AUTHORIZED",
            "attribution": "Bank of Canada",
            "third_party": "LSEG; rights unknown",
        }
        self.store.record("source_policy", digest(policy_record), policy_record)
        return policy_record

    def _json(self, body):
        try:
            result = json.loads(
                body,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except (ValueError, UnicodeError) as exc:
            raise SourceError("invalid JSON payload") from exc
        if not isinstance(result, dict):
            raise SourceError("JSON object required")
        return result

    def _metadata(self, url, body):
        """Extract JSON-native [URL, relation] pairs without running remote content."""
        text = body.decode("utf-8", errors="replace")
        parser = _Links()
        parser.feed(text)
        links = list(parser.links)
        for match in re.finditer(r"https://[^\s<>\"']+", text):
            links.append((match.group(0).rstrip(").,"), "reference"))
        if text.lstrip().startswith("{"):

            def walk(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in {
                            "link",
                            "url",
                            "href",
                            "citation",
                            "@id",
                        } and isinstance(child, str):
                            links.append(
                                (child, "dataset" if "/valet/" in child else "citation")
                            )
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)

            walk(self._json(body))
        if "<rss" in text or "<feed" in text:
            for link in re.findall(
                r"<link[^>]*>([^<]+)</link>|<link[^>]*href=[\"']([^\"']+)", text
            ):
                links.append((link[0] or link[1], "feed_entry"))
        safe = []
        for target, relation in links:
            try:
                resolved = self._safe_url(urljoin(url, unescape(target)))
            except (SourceError, ValueError):
                continue
            link = [resolved, relation]
            if resolved != url and link not in safe:
                safe.append(link)
        return safe[:128]

    def _source(self, url, evidence, relation, parent=None, detail=None):
        identity = "boc:" + hashlib.sha256(url.encode()).hexdigest()
        history = [
            r["value"]
            for r in self.store.records("source")
            if r["value"].get("source_id") == identity
        ]
        version = evidence["raw"]["sha256"]
        existing = self.store.get("source", identity + ":" + version)
        if existing:
            return existing["value"]
        value = {
            "source_id": identity,
            "url": url,
            "legal_publisher": "Bank of Canada",
            "jurisdiction": "Canada",
            "source_type": relation,
            "authoritative_claim_categories": [
                "published reference exchange rates",
                "own API documentation",
            ],
            "discovered_at": history[0]["discovered_at"]
            if history
            else evidence["retrieved_at"],
            "last_validated_at": None,
            "original_publication_time": None,
            "data_coverage": detail,
            "version": version,
            "license_access_status": "public_research_restricted; third-party rights unknown",
            "retrieval_method": "HTTPS GET",
            "authentication_required": False,
            "authentication_evidence": "public unauthenticated HTTP 200 observed"
            if evidence["status"] == 200
            else "not established",
            "citation_references": [parent] if parent else [],
            "data_freshness": "retrieved snapshot; publication freshness unknown",
            "reliability_history": [
                {
                    "status": evidence["status"],
                    "at": evidence["retrieved_at"],
                    "evidence": evidence["raw"],
                }
            ],
            "known_discrepancies": [],
            "verification_outcome": "DISCOVERED_NOT_VALIDATED",
            "version_history": list(
                dict.fromkeys([item["version"] for item in history] + [version])
            ),
            "evidence": evidence["raw"],
        }
        self.store.record("source", identity + ":" + version, value)
        return value

    def discover(self, gap):
        if not isinstance(gap, str) or not gap.strip() or len(gap) > 2000:
            raise SourceError(
                "knowledge gap must be nonempty and at most 2000 characters"
            )
        self._begin(16, 90)
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,39}", gap)
        fx = any(
            word.lower()
            in {
                "usd",
                "cad",
                "usdcad",
                "fxusdcad",
                "fx",
                "exchange",
                "currency",
                "dollar",
            }
            for word in words
        )
        topics = (
            ["exchange rates", "daily average", "reference rate"]
            if fx
            else list(dict.fromkeys(word.lower() for word in words))[:6]
        )
        entities = ["Bank of Canada"] + (["USD", "CAD", "FXUSDCAD"] if fx else [])
        query = SERIES if fx else " ".join(topics[:3])
        plan = {
            "gap": gap,
            "topics": topics,
            "entities": entities,
            "queries": [query, " ".join(entities + topics[:1])],
            "seed": DOCS,
            "scope": "Bank of Canada official metadata only",
            "created_at": self.clock(),
        }
        self.store.record("discovery_plan", digest(plan), plan)
        candidates = []
        try:
            self._permissions()
            body, evidence = self._request(DOCS)
            candidates.append(self._source(DOCS, evidence, "api_documentation"))
            links = self._metadata(DOCS, body)
            for document, relation in links:
                if relation in {"citation", "feed"} or "/valet-api-how-to" in document:
                    content, doc_ev = self._request(document)
                    candidates.append(self._source(document, doc_ev, relation, DOCS))
                    self.store.record(
                        "discovery_links",
                        digest({"url": document, "raw": doc_ev["raw"]}),
                        {
                            "url": document,
                            "links": self._metadata(document, content),
                            "raw": doc_ev["raw"],
                        },
                    )
                    break
            initializer = next(
                (url for url, _ in links if url.endswith("swagger-initializer.js")),
                None,
            )
            catalog_url = next(
                (url for url, _ in links if url.endswith((".yml", ".yaml", ".json"))),
                None,
            )
            if initializer:
                script, ev = self._request(initializer)
                candidates.append(
                    self._source(initializer, ev, "api_documentation", DOCS)
                )
                # Resolve the published template only. No evaluation of JavaScript.
                match = re.search(
                    r"[\"'`]([^\"'`]*api-\$\{lang\}\.ya?ml)[\"'`]",
                    script.decode("utf-8"),
                )
                if match:
                    catalog_url = urljoin(
                        DOCS.rsplit("/", 1)[0] + "/",
                        match.group(1).replace("${lang}", "en"),
                    )
                else:
                    catalog_url = next(
                        (
                            u
                            for u, _ in self._metadata(initializer, script)
                            if u.endswith((".yml", ".yaml", ".json"))
                        ),
                        catalog_url,
                    )
            if not catalog_url:
                raise SourceError("official API catalog not discoverable from docs")
            catalog, ev = self._request(catalog_url)
            candidates.append(
                self._source(catalog_url, ev, "api_catalog", initializer or DOCS)
            )
            text = catalog.decode("utf-8")
            routes = set(re.findall(r"(?m)^  (/[^\s:]+):\s*$", text))
            if text.lstrip().startswith("{"):
                routes.update(self._json(catalog).get("paths", {}))
            base_match = re.search(r"(?m)^\s*- url:\s*(https://\S+)", text)
            base = (
                self._safe_url(base_match.group(1)) if base_match else ORIGIN + "/valet"
            )
            if "/search/series" in routes:
                search_url = (
                    base.rstrip("/") + "/search/series?" + urlencode({"search": query})
                )
            elif "/lists/{type}/{format}" in routes:
                search_url = base.rstrip("/") + "/lists/series/json"
            else:
                raise SourceError(
                    "official catalog has no supported series discovery route"
                )
            catalog_body, ev = self._request(search_url)
            candidates.append(
                self._source(search_url, ev, "dataset_catalog", catalog_url)
            )
            payload = self._json(catalog_body)
            series = payload.get("series", {})
            if not isinstance(series, dict):
                raise SourceError("unsupported series catalog structure")
            matching = []
            for name, metadata in series.items():
                if not isinstance(metadata, dict):
                    continue
                haystack = (name + " " + str(metadata)).lower()
                score = sum(
                    term.lower() in haystack for term in entities[1:] + topics + words
                )
                if score and re.fullmatch(r"[A-Za-z0-9_-]+", name):
                    matching.append((fx and name == SERIES, score, name, metadata))
            # Catalog identifiers establish identity; descriptive mentions do not.
            matching.sort(key=lambda row: (-row[0], -row[1], row[2]))
            for _, _, name, metadata in matching[:2]:
                if "/series/{seriesName}/{format}" not in routes:
                    continue
                target = base.rstrip("/") + "/series/" + name + "/json"
                content, ev = self._request(target)
                detail = self._json(content)
                candidates.append(
                    self._source(target, ev, "dataset", search_url, detail)
                )
                # Follow citation/feed/dataset metadata actually present, bounded to two.
                discovered_links = self._metadata(target, content)
                preferred = [
                    (u, r)
                    for u, r in discovered_links
                    if r in {"citation", "feed", "dataset", "feed_entry"}
                    and "/observations/" not in u
                    and u != TERMS
                ]
                for linked, relation in preferred[:2]:
                    if self.request_count >= self._limit - 1:
                        break
                    linked_body, linked_ev = self._request(linked)
                    candidates.append(self._source(linked, linked_ev, relation, target))
                    self.store.record(
                        "discovery_links",
                        digest({"url": linked, "raw": linked_ev["raw"]}),
                        {
                            "url": linked,
                            "links": self._metadata(linked, linked_body),
                            "raw": linked_ev["raw"],
                        },
                    )
            # API-declared feed is a discovered channel, not a preloaded URL.
            if (
                fx
                and isinstance(series.get(SERIES), dict)
                and "/fx_rss/{seriesNames}" in routes
                and self.request_count < self._limit
            ):
                feed_url = base.rstrip("/") + "/fx_rss/" + SERIES
                feed, ev = self._request(feed_url)
                candidates.append(self._source(feed_url, ev, "feed", catalog_url))
                self.store.record(
                    "discovery_links",
                    digest({"url": feed_url, "raw": ev["raw"]}),
                    {
                        "url": feed_url,
                        "links": self._metadata(feed_url, feed),
                        "raw": ev["raw"],
                    },
                )
                for entry_url, relation in self._metadata(feed_url, feed)[:2]:
                    if (
                        relation not in {"feed_entry", "citation", "dataset"}
                        or entry_url == TERMS
                        or self.request_count >= self._limit
                    ):
                        continue
                    entry, entry_ev = self._request(entry_url)
                    candidates.append(
                        self._source(entry_url, entry_ev, relation, feed_url)
                    )
                    self.store.record(
                        "discovery_links",
                        digest({"url": entry_url, "raw": entry_ev["raw"]}),
                        {
                            "url": entry_url,
                            "links": self._metadata(entry_url, entry),
                            "raw": entry_ev["raw"],
                        },
                    )
            self.store.record(
                "discovery_result",
                digest({"plan": plan, "sources": candidates}),
                {
                    "plan": plan,
                    "sources": candidates,
                    # Source versions are immutable, even when rediscovered unchanged.
                    "retrievals": list(self._evidence),
                    "request_count": self.request_count,
                    "phases": self._phase_accounting(),
                    "status": "COMPLETE_BOUNDED_SCOPE",
                },
            )
            return candidates
        except (SourceError, UnicodeError) as exc:
            self.store.audit(
                "source.discovery_failed",
                {"error": str(exc), "request_count": self.request_count, "plan": plan},
            )
            raise SourceError(str(exc)) from exc

    def registry(self):
        return [row["value"] for row in self.store.records("source")]

    def validate(self, source):
        self._begin()
        url = self._safe_url(source.get("url", ""))
        registered = self.store.get(
            "source", str(source.get("source_id")) + ":" + str(source.get("version"))
        )
        if (
            registered is None
            or registered["value"].get("url") != url
            or source.get("legal_publisher") != "Bank of Canada"
        ):
            raise SourceError(
                "source identity is not registered to official publisher evidence"
            )
        self.store.read_blob(registered["value"]["evidence"])
        policy = self._permissions()
        is_alpha = urlsplit(url).path.rstrip("/") in {
            "/valet/series/FXUSDCAD",
            "/valet/series/FXUSDCAD/json",
        }
        target = (
            ORIGIN + "/valet/observations/FXUSDCAD/json?recent=1" if is_alpha else url
        )
        body, evidence = self._request(target)
        if is_alpha:
            self._normalize(self._json(body), evidence, enforce_coverage=False)
        result = dict(registered["value"])
        result.update(
            last_validated_at=evidence["retrieved_at"],
            verification_outcome="VALIDATED_RESEARCH_ONLY",
            validation_evidence=evidence,
            policy=policy,
            license_status="restricted_research; redistribution rights unknown",
        )
        result["reliability_history"] = result.get("reliability_history", []) + [
            {
                "status": evidence["status"],
                "at": evidence["retrieved_at"],
                "evidence": evidence["raw"],
            }
        ]
        self.store.record("source_validation", digest(result), result)
        return result

    @staticmethod
    def _has_alpha_units(detail):
        """Require USD/CAD identity and evidence of CAD-per-USD direction."""
        if not isinstance(detail, dict):
            return False
        label = str(detail.get("label", "")).replace(" ", "").upper()
        description = str(detail.get("description", "")).lower()
        metadata = detail.get("metadata", {})
        unit = (
            str(metadata.get("unit", "")).strip().lower()
            if isinstance(metadata, dict)
            else ""
        )
        expected_unit = bool(
            re.fullmatch(r"canadian dollars? per (?:us|u\.s\.) dollar", unit)
        )
        expected_description = bool(
            re.search(
                r"(?:us|u\.s\.) dollar\s+(?:to\s+(?:the\s+)?canadian dollar|in\s+canadian dollars)",
                description,
            )
        )
        return (
            label == "USD/CAD"
            and (not unit or expected_unit)
            and (expected_unit or expected_description)
        )

    def _normalize(self, payload, evidence, enforce_coverage=True):
        detail = payload.get("seriesDetail", {}).get(SERIES)
        if not isinstance(detail, dict):
            raise SourceError("seriesDetail missing FXUSDCAD")
        if not self._has_alpha_units(detail):
            raise SourceError("seriesDetail does not establish CAD per USD units")
        rows = payload.get("observations")
        if not isinstance(rows, list) or not rows:
            raise SourceError("no actual observations")
        observations = []
        last = ""
        revision = evidence["raw"]["sha256"]
        years = set()
        for row in rows:
            try:
                day = row["d"]
                parsed = date.fromisoformat(day)
                if parsed.isoformat() != day or day <= last or parsed.weekday() >= 5:
                    raise SourceError("duplicate, nonascending or weekend observation")
                if enforce_coverage and not START <= day <= END:
                    raise SourceError("observation outside requested coverage")
                original = row[SERIES]["v"]
                if not isinstance(original, str):
                    raise SourceError("original decimal string required")
                number = float(original)
                if not math.isfinite(number) or number <= 0:
                    raise SourceError("nonfinite or nonpositive reference rate")
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError("invalid observation: " + str(exc)) from exc
            observations.append(
                {
                    "date": day,
                    "value": number,
                    "event_time": day,
                    "event_time_precision": "date",
                    "publication_time": None,
                    "available_at": None,
                    "ingested_at": evidence["retrieved_at"],
                    "timezone": "America/Toronto",
                    "source_revision": revision,
                    "original_value": original,
                    "normalized_value": number,
                    "vintage": revision,
                    "complete": True,
                    "adjustment_history": [],
                    "data_status": "current_retrieved_reference_vintage",
                }
            )
            last = day
            years.add(parsed.year)
        if enforce_coverage and (
            years != {2023, 2024, 2025}
            or any(
                sum(o["date"].startswith(str(y)) for o in observations) < 200
                for y in years
            )
        ):
            raise SourceError(
                "insufficient genuine observations for three-year research slice"
            )
        return observations

    @staticmethod
    def _is_alpha_source(source):
        """Match the series endpoint's singular seriesDetails entity, not observations."""
        detail = source.get("data_coverage")
        series_detail = (
            detail.get("seriesDetails") if isinstance(detail, dict) else None
        )
        return (
            source.get("source_type") == "dataset"
            and urlsplit(source.get("url", "")).path.rstrip("/")
            in {"/valet/series/FXUSDCAD", "/valet/series/FXUSDCAD/json"}
            and isinstance(series_detail, dict)
            and series_detail.get("name") == SERIES
            and SourceHunter._has_alpha_units(series_detail)
        )

    def acquire_alpha(self):
        sources = self.registry()
        source = next(
            (item for item in reversed(sources) if self._is_alpha_source(item)),
            None,
        )
        if source is None:
            sources = self.discover(
                "USD CAD FXUSDCAD daily average exchange rate 2023 2024 2025"
            )
            source = next(
                (item for item in reversed(sources) if self._is_alpha_source(item)),
                None,
            )
        if source is None:
            raise SourceError(
                "FXUSDCAD not found in official catalog; no fabricated fallback"
            )
        source = self.validate(source)
        # Validation established robots + terms in this operation; one request left.
        request_url = (
            ORIGIN
            + "/valet/observations/FXUSDCAD/json?"
            + urlencode({"start_date": START, "end_date": END})
        )
        body, evidence = self._request(request_url)
        observations = self._normalize(self._json(body), evidence)
        normalized = self.store.put_blob(
            canonical_json(observations).encode("utf-8"), "application/json"
        )
        dataset_id = digest(
            {
                "series": SERIES,
                "raw": evidence["raw"]["sha256"],
                "normalized": normalized["sha256"],
            }
        )
        manifest = {
            "dataset_id": dataset_id,
            "schema_version": 1,
            "source_id": source["source_id"],
            "source_version": source["version"],
            "source": source,
            "series": SERIES,
            "instrument": "USD/CAD",
            "publisher": "Bank of Canada",
            "method": "GET",
            "request_url": request_url,
            "request": evidence,
            "retrieved_at": evidence["retrieved_at"],
            "publication_time": None,
            "available_at": None,
            "raw": evidence["raw"],
            "normalized": normalized,
            "coverage": {
                "start": observations[0]["date"],
                "end": observations[-1]["date"],
                "requested_start": START,
                "requested_end": END,
                "observation_count": len(observations),
            },
            "units": "CAD per USD",
            "timezone": "America/Toronto",
            "vintage": evidence["raw"]["sha256"],
            "data_class": "daily_average_reference_exchange_rate",
            "historical_availability": "UNKNOWN",
            "policy": source["policy"],
            "limitations": LIMITATIONS,
        }
        manifest["manifest_id"] = digest(manifest)
        self.store.record("source_snapshot", manifest["manifest_id"], manifest)
        dataset = {
            "dataset_id": dataset_id,
            "observations": observations,
            "manifest": manifest,
        }
        self.store.record("dataset", dataset_id, dataset)
        self.store.audit(
            "source.acquired",
            {
                "dataset_id": dataset_id,
                "manifest_id": manifest["manifest_id"],
                "request_count": self.request_count,
            },
        )
        return dataset

    def check_updates(self):
        self._begin(
            min(4, int(self.store.config.get("max_network_requests_per_cycle", 4)))
        )
        snapshots = self.store.records("source_snapshot")
        if not snapshots:
            return {
                "status": "NO_SNAPSHOT",
                "request_count": 0,
                "changed": None,
                "evidence": [],
                "stale_dependencies": [],
            }
        snapshot = snapshots[-1]["value"]
        try:
            self._permissions()
            previous = snapshot["request"]
            conditional = {}
            if previous["headers"].get("etag"):
                conditional["If-None-Match"] = previous["headers"]["etag"]
            elif previous["headers"].get("last-modified"):
                conditional["If-Modified-Since"] = previous["headers"]["last-modified"]
            body, evidence = self._request(snapshot["request_url"], conditional)
            changed = (
                evidence["status"] != 304
                and evidence["raw"]["sha256"] != snapshot["raw"]["sha256"]
            )
            notices = []
            if changed:
                notices.append(
                    {
                        "dataset_id": snapshot["dataset_id"],
                        "reason": "upstream raw content changed; revalidation and downstream rerun required",
                        "dependent_kinds": [
                            "experiment",
                            "strategy",
                            "lesson",
                            "report",
                        ],
                        "automatic_promotion": False,
                    }
                )
            result = {
                "status": "CHANGED_REVALIDATION_REQUIRED" if changed else "UNCHANGED",
                "changed": changed,
                "request_count": self.request_count,
                "checked_at": self.clock(),
                "evidence": evidence,
                "stale_dependencies": notices,
                "dataset_id": snapshot["dataset_id"],
            }
        except (SourceError, UnicodeError, ValueError, KeyError) as exc:
            result = {
                "status": "CHECK_FAILED",
                "changed": None,
                "request_count": self.request_count,
                "checked_at": self.clock(),
                "error": str(exc),
                "evidence": self._evidence,
                "stale_dependencies": [
                    {
                        "dataset_id": snapshot.get("dataset_id"),
                        "reason": "freshness unverified after failed check",
                    }
                ],
            }
        self.store.record("source_update", digest(result), result)
        return result
