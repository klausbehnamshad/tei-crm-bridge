"""Authority reconciliation against external norm data (PMB API).

Reconciliation is a separate, cache-backed step: ``tei-crm reconcile`` fills
a committable JSON cache over the network, while consumers (``cmif``,
``enrich``) only read that cache and stay offline. Every link carries its
source, the PMB entity URI and the retrieval date; unresolved entries keep
null values. Nothing is invented.
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Protocol

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


class ResolverError(RuntimeError):
    """Transport or parse failure; the caller skips caching and retries later."""


class Resolver(Protocol):
    """Pluggable authority lookup, mirroring ``ner.Recognizer``."""

    name: str

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
    context.load_verify_locations(cafile=certifi.where())
    return context


class PmbResolver:
    """Resolve ``pmb<N>`` register IDs via the PMB entities API."""

    name = "pmb-apis"
    ENDPOINTS = {"person": "person", "place": "place", "org": "institution"}

    def __init__(self, delay: float = 0.5, timeout: float = 20,
                 user_agent: str = f"tei-crm-bridge/{__version__} (+https://github.com/klausbehnamshad/tei-crm-bridge)"):
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self.context = tls_context()

    def resolve(self, kind: str, local_id: str, label: str) -> AuthorityLinks:
        endpoint, match = self.ENDPOINTS.get(kind), _PMB_ID.match(local_id)
        if endpoint is None or match is None:
            return AuthorityLinks()
        url = f"{PMB_API}/{endpoint}/{match.group(1)}/?format=json"
        return pick_links(self._fetch(url))

    def _fetch(self, url: str) -> list[str]:
        """The ``sameAs`` URI list of one entity; 404 and empty mean unresolved."""
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return []
                raise ResolverError(f"{url}: HTTP {error.code}") from None
            # Only h.request() errors arrive wrapped in URLError; getresponse()
            # and json.load() failures (drops, resets, bad status, raw SSL
            # errors) reach us unwrapped, hence the broad OSError branch below
            # (never plain Exception: KeyboardInterrupt/SystemExit propagate).
            except (OSError, http.client.HTTPException, ValueError) as error:
                reason = error.reason if isinstance(error, urllib.error.URLError) else error
                if isinstance(reason, ssl.SSLCertVerificationError):
                    raise ResolverError(f"{url}: {reason}") from None  # not transient: no retry
                if attempt == 2:
                    raise ResolverError(f"{url}: {error}") from None
                time.sleep(self.delay)
        same = payload.get("sameAs") if isinstance(payload, dict) else None
        if not isinstance(same, list):
            return []
        return [item for item in same if isinstance(item, str)]


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
    # file and no directory is left behind.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def links_for(cache: Mapping | None, local_id: str) -> Mapping | None:
    """Cache entry for a local ID, or ``None`` without a recorded resolution."""
    if not isinstance(cache, Mapping):
        return None
    entries = cache.get("entries")
    entry = entries.get(local_id) if isinstance(entries, Mapping) else None
    return entry if isinstance(entry, Mapping) else None


def update_cache(cache: dict, entities: dict[str, dict[str, str]], resolver: Resolver,
                 offline: bool = False, max_leading_failures: int = 3) -> tuple[int, int, list[str]]:
    """Fetch missing entities (one request per ID); returns (fetched, failed, warnings).

    ``max_leading_failures`` aborts the loop once that many fetches fail before
    the first success, so a systematic outage (no network, broken TLS) does not
    burn hundreds of doomed requests on a large corpus.
    """
    fetched, failed, warnings = 0, 0, []
    missing = [local_id for local_id in entities if local_id not in cache["entries"]]
    for position, local_id in enumerate(missing):
        if offline:
            continue
        info = entities[local_id]
        try:
            links = resolver.resolve(info["kind"], local_id, info["label"])
        except ResolverError as error:
            failed += 1
            warnings.append(f"{local_id}: Abruf gescheitert ({error}), kein Eintrag gespeichert")
            if fetched == 0 and failed >= max_leading_failures:
                remaining = len(missing) - position - 1
                warnings.append(f"Abbruch nach {failed} gescheiterten Abrufen ohne Erfolg; "
                                f"{remaining} Entities nicht versucht")
                break
            continue
        entry = {"kind": info["kind"], "label": info["label"],
                 "pmb": pmb_url(local_id) if resolver.name == PmbResolver.name else None,
                 "gnd": links.gnd, "geonames": links.geonames, "wikidata": links.wikidata,
                 "source": resolver.name, "retrieved": date.today().isoformat()}
        if not links.any():
            warnings.append(f"{local_id} ({info['label']!r}): keine Normdaten, als unaufgelöst gespeichert")
        cache["entries"][local_id] = entry
        fetched += 1
        if position < len(missing) - 1 and isinstance(resolver, PmbResolver):
            time.sleep(resolver.delay)
    return fetched, failed, warnings


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
