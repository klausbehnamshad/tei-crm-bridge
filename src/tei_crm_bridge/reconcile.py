"""Authority reconciliation against external norm data (PMB API).

Reconciliation is a separate, cache-backed step: ``tei-crm reconcile`` fills
a committable JSON cache over the network, while consumers (``cmif``,
``enrich``) only read that cache and stay offline. Every link carries its
source, the PMB entity URI and the retrieval date; unresolved entries keep
null values. Nothing is invented.
"""

from __future__ import annotations

import email.utils
import http.client
import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, Protocol

from lxml import etree

from . import __version__
from .projection import TEI, local_name
from .rdf import valid_iri

#: Cache layout version for forward-compatible readers.
CACHE_VERSION = 1

#: PMB API root for person/place/institution entities.
PMB_API = "https://pmb.acdh.oeaw.ac.at/apis/api/entities"

_GND = re.compile(r"^https?://d-nb\.info/gnd/\S+$")
_GEONAMES = re.compile(r"^https?://(?:sws\.|www\.)?geonames\.org/\S+$")
_WIKIDATA = re.compile(r"^https?://www\.wikidata\.org/entity/Q\d+$")
_PMB_ID = re.compile(r"^pmb(\d+)$")


def normalize_gnd(uri: str) -> str:
    """GND identifiers in the ``https`` form the CMIF examples use."""
    return re.sub(r"^http://d-nb\.info/gnd/", "https://d-nb.info/gnd/", uri)


@dataclass(frozen=True)
class AuthorityLinks:
    """Resolved norm-data URIs; ``None`` where the authority has nothing."""

    gnd: str | None = None
    geonames: str | None = None
    wikidata: str | None = None

    def any(self) -> bool:
        return self.gnd is not None or self.geonames is not None or self.wikidata is not None


#: Why a lookup failed. Everything but ``http`` points at a systematic problem
#: (network, TLS, rate limiting, API change) rather than at one entity.
Cause = Literal["transport", "tls", "throttle", "http", "drift"]

#: Statuses that mean "the server is busy", retried with backoff.
THROTTLE_STATUS = frozenset({429, 502, 503, 504})

#: Bounds for one backoff wait: at least this long even with ``--delay 0``,
#: at most this long whatever ``Retry-After`` asks for.
MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0


class ResolverError(RuntimeError):
    """Lookup failure; the caller skips caching and retries on a later run."""

    def __init__(self, message: str, cause: Cause = "transport"):
        super().__init__(message)
        self.cause: Cause = cause

    @property
    def systemic(self) -> bool:
        """True unless the failure is specific to one entity (a plain HTTP error)."""
        return self.cause != "http"


class ApiDriftError(ResolverError):
    """The API answered outside its known shape; abort instead of caching empties."""

    def __init__(self, url: str, detail: str):
        super().__init__(f"{url}: {detail}", cause="drift")
        self.url = url


class Resolver(Protocol):
    """Pluggable authority lookup, mirroring ``ner.Recognizer``."""

    name: str

    def supports(self, kind: str, local_id: str) -> bool:
        """Whether this backend can resolve the ID at all (no network). ..."""
        ...

    def resolve(self, kind: str, local_id: str, label: str) -> AuthorityLinks:
        """Norm data for one register entity (``kind``: person/place/org). ..."""
        ...


def pmb_url(local_id: str) -> str:
    """Public PMB entity page for a local ID (``pmb2121`` → ``…/entity/2121/``)."""
    match = _PMB_ID.match(local_id)
    return f"https://pmb.acdh.oeaw.ac.at/entity/{match.group(1) if match else local_id}/"


def tls_context() -> ssl.SSLContext:
    """TLS context with certifi added on top of the platform store.

    python.org builds on macOS ship without a CA store; loading certifi
    additively (instead of replacing the context) keeps ``SSL_CERT_FILE``,
    ``SSL_CERT_DIR`` and the platform store working, e.g. behind
    institutional proxies with their own CA.
    """
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return context
    try:
        context.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError):
        pass  # broken or missing bundle: keep the platform store, like a missing certifi
    return context


def _retry_after(error: urllib.error.HTTPError) -> float:
    """Seconds requested by a ``Retry-After`` header (seconds or HTTP date), else 0."""
    value = (error.headers.get("Retry-After") if error.headers else None) or ""
    value = value.strip()
    if value.isascii() and value.isdigit():  # "²".isdigit() is True, float("²") is not
        return float(value)
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())


class PmbResolver:
    """Resolve ``pmb<N>`` register IDs via the PMB entities API.

    Requests are paced: at least ``delay`` seconds pass between the start of
    any two requests, retries included, and a server-requested pause (rate
    limiting) also holds for the next entity. The TLS context is built on the
    first request, so ``--offline`` never touches TLS.
    """

    name = "pmb-apis"
    ENDPOINTS = {"person": "person", "place": "place", "org": "institution"}
    TRANSPORT_RETRIES = 1
    THROTTLE_RETRIES = 3

    def __init__(self, delay: float = 0.5, timeout: float = 20,
                 user_agent: str = f"tei-crm-bridge/{__version__} (+https://github.com/klausbehnamshad/tei-crm-bridge)"):
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self._context: ssl.SSLContext | None = None
        self._last_request: float | None = None
        self._not_before = 0.0

    @property
    def context(self) -> ssl.SSLContext:
        if self._context is None:
            self._context = tls_context()
        return self._context

    def supports(self, kind: str, local_id: str) -> bool:
        return kind in self.ENDPOINTS and _PMB_ID.match(local_id) is not None

    def resolve(self, kind: str, local_id: str, label: str) -> AuthorityLinks:
        endpoint, match = self.ENDPOINTS.get(kind), _PMB_ID.match(local_id)
        if endpoint is None or match is None:
            return AuthorityLinks()
        url = f"{PMB_API}/{endpoint}/{match.group(1)}/?format=json"
        return pick_links(self._fetch(url))

    def _pace(self) -> None:
        now = time.monotonic()
        wait = self._not_before - now
        if self._last_request is not None:
            wait = max(wait, self.delay - (now - self._last_request))
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, url: str) -> list[str]:
        """The ``sameAs`` URI list of one entity; 404-JSON means unresolved."""
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        transport_left, throttle_left, backoff = self.TRANSPORT_RETRIES, self.THROTTLE_RETRIES, 0
        while True:
            self._pace()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    try:
                        not_found = _is_api_not_found(error)
                    except (OSError, http.client.HTTPException) as read_error:
                        raise ResolverError(f"{url}: {read_error}", cause="transport") from None
                    if not_found:
                        return []
                    raise ApiDriftError(url, "404 ohne API-Fehlerformat") from None
                if error.code not in THROTTLE_STATUS:
                    raise ResolverError(f"{url}: HTTP {error.code}", cause="http") from None
                wait = min(MAX_BACKOFF, max(MIN_BACKOFF, self.delay * 2 ** backoff, _retry_after(error)))
                self._not_before = time.monotonic() + wait  # _pace waits; also binds the next entity
                if throttle_left == 0:
                    raise ResolverError(f"{url}: HTTP {error.code}", cause="throttle") from None
                throttle_left -= 1
                backoff += 1
            # Only h.request() errors arrive wrapped in URLError; getresponse()
            # and json.load() failures (drops, resets, bad status, raw SSL
            # errors) reach us unwrapped, hence the broad OSError branch below
            # (never plain Exception: KeyboardInterrupt/SystemExit propagate).
            except (OSError, http.client.HTTPException, ValueError) as error:
                reason = error.reason if isinstance(error, urllib.error.URLError) else error
                if isinstance(reason, ssl.SSLCertVerificationError):
                    raise ResolverError(f"{url}: {reason}", cause="tls") from None  # not transient: no retry
                if transport_left == 0:
                    raise ResolverError(f"{url}: {error}", cause="transport") from None
                transport_left -= 1
        if not isinstance(payload, dict):
            raise ApiDriftError(url, "Antwort ist kein JSON-Objekt") from None
        same = payload.get("sameAs")
        if not isinstance(same, list):
            raise ApiDriftError(url, "Antwort ohne sameAs-Liste") from None
        return [item for item in same if isinstance(item, str)]


def _is_api_not_found(error: urllib.error.HTTPError) -> bool:
    """True only for the API's own JSON error (missing entity, not a moved path)."""
    ctype = error.headers.get_content_type() if error.headers else ""
    if ctype != "application/json":
        return False
    try:
        body = json.loads(error.read().decode("utf-8", "replace"))
    except ValueError:
        return False
    return isinstance(body, dict) and "detail" in body


def pick_links(uris: list[str]) -> AuthorityLinks:
    """First GND/GeoNames/Wikidata URI of a ``sameAs`` list; invalid IRIs dropped."""
    found: dict[str, str] = {}
    for uri in uris:
        if "gnd" not in found and _GND.match(uri):
            found["gnd"] = normalize_gnd(uri)
        elif "geonames" not in found and _GEONAMES.match(uri):
            found["geonames"] = uri
        elif "wikidata" not in found and _WIKIDATA.match(uri):
            found["wikidata"] = uri
    return AuthorityLinks(**{key: value for key, value in found.items() if valid_iri(value)})


def collect_entities(roots: list[etree._Element]) -> dict[str, dict[str, str]]:
    """Register entities (person/place/org with ``xml:id``) with kind and label."""
    entities: dict[str, dict[str, str]] = {}
    for root in roots:
        for tag in ("person", "place", "org"):
            for record in root.iter(TEI + tag):
                local_id = record.get("{http://www.w3.org/XML/1998/namespace}id")
                if not local_id or local_id in entities:
                    continue
                label = None
                for child in record:
                    if local_name(child) in {"persName", "placeName", "orgName"}:
                        label = " ".join("".join(child.itertext()).split()) or None
                        break
                entities[local_id] = {"kind": tag, "label": label or " ".join("".join(record.itertext()).split())}
    return entities


def new_cache(resolver_name: str) -> dict:
    return {"resolver": resolver_name, "version": CACHE_VERSION, "entries": {}}


def load_cache(path: Path) -> dict:
    """Read a reconciliation cache; ``ValueError`` on corrupt content."""
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cache {path} ist ungültig: {error}") from None
    if not isinstance(cache, dict) or not isinstance(cache.get("entries"), dict):
        raise ValueError(f"Cache {path} ist ungültig: Kopf oder entries fehlen")
    return cache


def save_cache(path: Path, cache: dict) -> None:
    # Created here (not pre-checked): on total failure this never runs, so no
    # file and no directory is left behind. Atomic within the target directory
    # (same filesystem for os.replace); leftovers are removed on failure.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def links_for(cache: Mapping | None, local_id: str) -> Mapping | None:
    """Cache entry for a local ID, or ``None`` without a recorded resolution."""
    if not isinstance(cache, Mapping):
        return None
    entries = cache.get("entries")
    entry = entries.get(local_id) if isinstance(entries, Mapping) else None
    return entry if isinstance(entry, Mapping) else None


@dataclass(frozen=True)
class Failure:
    """One failed lookup: entity, cause class and message."""

    local_id: str
    cause: Cause
    detail: str

    @property
    def systemic(self) -> bool:
        return self.cause != "http"


@dataclass
class UpdateResult:
    """Outcome of :func:`update_cache`.

    ``attempted`` counts entities a lookup was started for, ``untried`` the
    supported ones left over after an abort. ``stop`` is ``None`` for a
    complete pass, ``"leading"`` (systematic failures before any success),
    ``"consecutive"`` (systematic failures in a row after a success) or
    ``"drift"`` (unexpected API answer).
    """

    fetched: int = 0
    failed: int = 0
    skipped: int = 0
    attempted: int = 0
    untried: int = 0
    streak: int = 0
    warnings: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    stop: Literal["leading", "consecutive", "drift"] | None = None
    drift_url: str | None = None


def update_cache(cache: dict, entities: dict[str, dict[str, str]], resolver: Resolver,
                 offline: bool = False, max_leading_failures: int = 3,
                 max_consecutive_failures: int = 5,
                 checkpoint: Callable[[], None] | None = None,
                 checkpoint_every: int = 25) -> UpdateResult:
    """Fetch missing entities (one lookup per ID) into ``cache``.

    Only systematic failures (network, TLS, rate limiting, API drift) count
    towards the circuit breaker: ``max_leading_failures`` of them before the
    first success, or ``max_consecutive_failures`` in a row after one, stop the
    loop, so an outage does not burn hundreds of doomed requests. A failure
    specific to one entity (a plain HTTP error) neither counts nor resets the
    streak. IDs the resolver does not support are skipped with a warning (no
    entry, no fetch). An ``ApiDriftError`` stops immediately. ``checkpoint``
    runs after every ``checkpoint_every`` newly stored entries.
    """
    result = UpdateResult()
    missing = [local_id for local_id in entities if local_id not in cache["entries"]]
    todo = []
    for local_id in missing:
        if resolver.supports(entities[local_id]["kind"], local_id):
            todo.append(local_id)
        else:
            result.skipped += 1
            if not offline:
                result.warnings.append(f"{local_id}: übersprungen, keine PMB-ID")
    if offline:
        return result
    streak = 0
    for position, local_id in enumerate(todo):
        info = entities[local_id]
        result.attempted += 1
        try:
            links = resolver.resolve(info["kind"], local_id, info["label"])
        except ResolverError as error:
            result.failed += 1
            result.failures.append(Failure(local_id, error.cause, str(error)))
            if isinstance(error, ApiDriftError):
                result.warnings.append(f"PMB-API geändert? {error}")
                result.stop, result.drift_url = "drift", error.url
            else:
                result.warnings.append(f"{local_id}: Abruf gescheitert ({error}), kein Eintrag gespeichert")
                if error.systemic and position < len(todo) - 1:  # last one: the pass is complete anyway
                    streak += 1
                    if result.fetched == 0 and streak >= max_leading_failures:
                        result.stop = "leading"
                    elif result.fetched > 0 and streak >= max_consecutive_failures:
                        result.stop = "consecutive"
            if result.stop is not None:
                result.untried, result.streak = len(todo) - position - 1, streak
                if result.stop == "leading":
                    result.warnings.append(f"Abbruch nach {streak} gescheiterten Abrufen ohne Erfolg; "
                                           f"{result.untried} Entities nicht versucht")
                elif result.stop == "consecutive":
                    result.warnings.append(f"Abbruch nach {streak} systematischen Fehlern in Folge; "
                                           f"{result.untried} Entities nicht versucht")
                break
            continue
        streak = 0
        entry = {"kind": info["kind"], "label": info["label"],
                 "pmb": pmb_url(local_id) if resolver.name == PmbResolver.name else None,
                 "gnd": links.gnd, "geonames": links.geonames, "wikidata": links.wikidata,
                 "source": resolver.name, "retrieved": date.today().isoformat()}
        if not links.any():
            result.warnings.append(f"{local_id} ({info['label']!r}): keine Normdaten, als unaufgelöst gespeichert")
        cache["entries"][local_id] = entry
        result.fetched += 1
        if checkpoint is not None and checkpoint_every > 0 and result.fetched % checkpoint_every == 0:
            checkpoint()
    return result


def summarize(entities: dict[str, dict[str, str]], cache: Mapping | None) -> dict[str, dict[str, int]]:
    """Resolved/unresolved counts per kind over the collected entities."""
    summary: dict[str, dict[str, int]] = {}
    for local_id, info in entities.items():
        row = summary.setdefault(info["kind"], {"total": 0, "gnd": 0, "geonames": 0, "wikidata": 0, "resolved": 0, "unresolved": 0})
        row["total"] += 1
        entry = links_for(cache, local_id)
        hits = [entry.get(key) for key in ("gnd", "geonames", "wikidata")] if entry else []
        if entry and any(hits):
            row["resolved"] += 1
            for key in ("gnd", "geonames", "wikidata"):
                if entry.get(key):
                    row[key] += 1
        else:
            row["unresolved"] += 1
    return summary
