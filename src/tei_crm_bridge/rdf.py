"""Conservative CIDOC CRM and W3C Web Annotation graph for one TEI document.

* Editorial names (already in the TEI) are statements of the edition: the
  document ``P67_refers_to`` the entity. Existing ``@ref`` values are kept.
* Automatic names are suggestions: an ``oa:Annotation`` with provenance whose
  body is a ``tcb:Candidate`` with a suggested CRM class. Neither a CRM type
  nor a ``P67`` statement is asserted until someone confirms it.
* ``correspAction`` of type ``sent`` and ``received`` become separate
  ``E7_Activity`` events with controlled types; dates become bounded time-spans.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Mapping
from urllib.parse import quote, urljoin

from lxml import etree
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
from rdflib.namespace import DCTERMS, PROV

from . import __version__
from .dates import intersect, interval
from .projection import TEI, local_name, name_kind, string_value, xpath_of, xpath_selector
from .writeback import XML_ID, Mention

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
OA = Namespace("http://www.w3.org/ns/oa#")
VOCAB = Namespace("https://klausbehnamshad.github.io/tei-crm-bridge/vocab/#")
SOFTWARE = URIRef("https://github.com/klausbehnamshad/tei-crm-bridge")
CLASSES = {"PER": CRM.E21_Person, "LOC": CRM.E53_Place, "ORG": CRM.E74_Group}
EVENTS = {
    "sent": (VOCAB.sending, "Versand", "sending"),
    "received": (VOCAB.receiving, "Empfang", "receiving"),
}
#: ``idno`` subtypes in the edition's registers that name an authority record.
AUTHORITIES = frozenset({"gnd", "d-nb", "wikidata", "geonames", "viaf", "pmb"})
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$")
_IRI = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>"{}|\\^`]+$')


def valid_iri(value: str) -> bool:
    """True for an absolute IRI that Turtle can serialize."""
    return bool(_IRI.match(value))


def reconciled_uris(cache: Mapping | None, local_id: str | None) -> list[str]:
    """Validated GND/GeoNames/Wikidata URIs of a reconciliation cache entry."""
    if not isinstance(cache, Mapping) or not local_id:
        return []
    entries = cache.get("entries")
    entry = entries.get(local_id) if isinstance(entries, Mapping) else None
    if not isinstance(entry, Mapping):
        return []
    return [value for value in (entry.get("gnd"), entry.get("geonames"), entry.get("wikidata"))
            if isinstance(value, str) and valid_iri(value)]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")[:48] or "entity"
    digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def document_title(root: etree._Element, fallback: str) -> str:
    titles = root.findall(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    preferred = [title for title in titles if title.get("level") == "a"] or titles
    for title in preferred:
        text = _normalize("".join(title.itertext()))
        if text:
            return text
    return fallback


def _record_label(record: etree._Element) -> str | None:
    """Preferred name of a ``person``/``place``/``org`` register entry."""
    for child in record:
        name = local_name(child)
        if name in {"persName", "placeName", "orgName"}:
            forenames = [_normalize("".join(n.itertext())) for n in child.iter(TEI + "forename")]
            surnames = [_normalize("".join(n.itertext())) for n in child.iter(TEI + "surname")]
            if forenames or surnames:
                return " ".join(forenames + surnames)
            return _normalize("".join(child.itertext())) or None
    return None


class GraphBuilder:
    def __init__(
        self, root: etree._Element, doc_id: str, base_uri: str, warnings: list[str],
        tei_url: str | None = None, source_url: str | None = None,
        reconciliation: Mapping | None = None,
    ):
        self.root = root
        self.base = base_uri
        self.doc_id = doc_id
        self.warnings = warnings
        #: Reconciled norm data (``{"entries": {local_id: {...}}}``), added as
        #: ``rdfs:seeAlso`` next to the register ``idno`` identifiers. Never a
        #: CRM class and never ``owl:sameAs``: reconciliation is a suggestion.
        self.reconciliation = reconciliation
        self.doc = URIRef(base_uri + "document/" + quote(doc_id, safe=""))
        # The enriched TEI file that the selectors of every annotation point into.
        self.tei = URIRef(tei_url or str(self.doc) + "/tei")
        self.title = document_title(root, doc_id)
        self.ids = {node.get(XML_ID): node for node in root.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
        self.prefixes = self._prefix_defs()
        self.labels: dict[URIRef, str] = {}
        self.graph = Graph()
        for prefix, namespace in (("crm", CRM), ("oa", OA), ("prov", PROV), ("dcterms", DCTERMS), ("tcb", VOCAB), ("rdfs", RDFS)):
            self.graph.bind(prefix, namespace)
        self.graph.add((self.doc, RDF.type, CRM.E31_Document))
        self.graph.add((self.doc, RDFS.label, Literal(self.title)))
        self.graph.add((self.tei, DCTERMS.isFormatOf, self.doc))
        self.graph.add((self.tei, DCTERMS["format"], Literal("application/tei+xml")))
        if source_url:
            self.graph.add((self.tei, PROV.wasDerivedFrom, URIRef(source_url)))

    # Entities ------------------------------------------------------------

    def _prefix_defs(self) -> dict[str, tuple[re.Pattern[str], str]]:
        """TEI prefixDef rules. Patterns are Python regular expressions; only use trusted TEI."""
        found = {}
        for node in self.root.iter(TEI + "prefixDef"):
            ident, match, replacement = node.get("ident"), node.get("matchPattern"), node.get("replacementPattern")
            if not (ident and match and replacement):
                continue
            try:
                pattern = re.compile(match)
            except re.error as error:
                self.warnings.append(f"prefixDef {ident!r}: invalid matchPattern ({error})")
                continue
            groups = [int(number) for number in re.findall(r"\$(\d)", replacement)]
            if any(number > pattern.groups for number in groups):
                self.warnings.append(f"prefixDef {ident!r}: replacementPattern refers to a missing group")
                continue
            found[ident] = (pattern, re.sub(r"\$(\d)", r"\\\1", replacement))
        return found

    def _base_of(self, node: etree._Element) -> tuple[str, bool]:
        """Effective base URI and whether an ``xml:base`` made it absolute."""
        bases = [ancestor.get("{http://www.w3.org/XML/1998/namespace}base") for ancestor in [node, *node.iterancestors()]]
        # A bare #id names an xml:id in the enriched TEI file, not a fragment
        # of the HTML page used for the document's conceptual IRIs.
        base, explicit = str(self.tei), False
        for value in reversed([value for value in bases if value]):
            base = urljoin(base, value)
            explicit = explicit or bool(_SCHEME.match(value))
        return base, explicit

    def resolve(self, token: str, node: etree._Element, depth: int = 0) -> tuple[str, etree._Element | None] | None:
        """Absolute IRI for one ``@ref`` token and the register record it names, or None."""
        uri, record = None, None
        scheme = _SCHEME.match(token)
        if token.startswith("#"):
            record = self.ids.get(token[1:])
            uri = urljoin(self._base_of(node)[0], token) if record is not None else None
        elif scheme and scheme.group(1) in self.prefixes and depth == 0:
            pattern, replacement = self.prefixes[scheme.group(1)]
            match = pattern.fullmatch(scheme.group(2))
            return self.resolve(match.expand(replacement), node, depth + 1) if match else None
        elif scheme and scheme.group(1).lower() in {"http", "https"}:
            uri = token
        elif not scheme:  # relative reference such as register.xml#p1: only with an explicit xml:base
            base, explicit = self._base_of(node)
            uri = urljoin(base, token) if explicit else None
        if uri is None or not valid_iri(uri):
            return None
        return uri, record

    def _entity(self, uri: URIRef, kind: str, label: str) -> URIRef:
        self.graph.add((uri, RDF.type, CLASSES[kind]))
        if uri not in self.labels:
            self.labels[uri] = label
            self.graph.add((uri, RDFS.label, Literal(label)))
        return uri

    def local_entity(self, kind: str, label: str, key: str | None = None) -> URIRef:
        """Document-local entity for an editorial name without a resolvable ``@ref``.

        Names with the same unresolved ``@ref`` (``key``) share it, otherwise the
        same kind and surface form do.
        """
        slug = f"ref-{_slug(key)}" if key else _slug(label)
        uri = URIRef(f"{self.doc}/entity/{kind.lower()}/{slug}")
        return self._entity(uri, kind, label)

    def candidate(self, kind: str, label: str, existing_uri: str | None = None) -> URIRef:
        """Unconfirmed entity for an automatic name, retaining an earlier run's URI."""
        uri = URIRef(existing_uri) if existing_uri else URIRef(f"{self.doc}/candidate/{kind.lower()}/{_slug(label)}")
        self.graph.add((uri, RDF.type, VOCAB.Candidate))
        self.graph.add((uri, VOCAB.suggestedClass, CLASSES[kind]))
        if uri not in self.labels:
            self.labels[uri] = label
            self.graph.add((uri, RDFS.label, Literal(label)))
        return uri

    def entities_for(self, node: etree._Element, kind: str, label: str) -> tuple[list[URIRef], list[str], list[str]]:
        """Entities of an existing TEI name, the raw ``@ref`` tokens and the unresolved ones.

        Several register records in one ``@ref`` are several referents (``Saltens``:
        Felix and Ottilie Salten). An external URI next to a single register record
        names the same referent and is linked with ``rdfs:seeAlso``.
        """
        tokens = (node.get("ref") or "").split()
        resolved = [(token, self.resolve(token, node)) for token in tokens]
        unresolved = [token for token, result in resolved if result is None]
        for token in unresolved:
            self.warnings.append(f"unresolved @ref {token!r} on {xpath_of(node)}")
        records = [(URIRef(uri), record) for _, result in resolved if result for uri, record in [result] if record is not None]
        external = [URIRef(uri) for _, result in resolved if result for uri, record in [result] if record is None]
        if not records and not external:
            return [self.local_entity(kind, label, unresolved[0] if unresolved else None)], tokens, unresolved
        entities = []
        for uri, record in records:
            entities.append(self._entity(uri, kind, _record_label(record) or label))
            for idno in record.findall(TEI + "idno"):  # the record's own identifiers only
                value = _normalize(idno.text or "")
                if (idno.get("subtype") or idno.get("type") or "").lower() in AUTHORITIES and valid_iri(value):
                    self.graph.add((uri, RDFS.seeAlso, URIRef(value)))
            for value in reconciled_uris(self.reconciliation, record.get(XML_ID)):
                self.graph.add((uri, RDFS.seeAlso, URIRef(value)))
        if len(records) == 1:
            for uri in external:
                self.graph.add((records[0][0], RDFS.seeAlso, uri))
        elif not records:
            entities.append(self._entity(external[0], kind, label))
            for uri in external[1:]:
                self.graph.add((external[0], RDFS.seeAlso, uri))
        else:
            entities += [self._entity(uri, kind, label) for uri in external]
        for entity in entities:
            for token in unresolved:
                self.graph.add((entity, VOCAB.unresolvedRef, Literal(token)))
        return entities, tokens, unresolved

    # Provenance and mentions ----------------------------------------------

    def add_run(self, settings: dict) -> URIRef:
        """Processing run with every setting that influences the automatic mentions."""
        settings = {**settings, "softwareVersion": __version__}
        digest = hashlib.sha256(repr(sorted(settings.items())).encode()).hexdigest()[:12]
        run = URIRef(f"{self.base}run/{quote(self.doc_id, safe='')}/{digest}")
        self.graph.add((run, RDF.type, PROV.Activity))
        self.graph.add((run, PROV.wasAssociatedWith, SOFTWARE))
        self.graph.add((SOFTWARE, RDF.type, PROV.SoftwareAgent))
        self.graph.add((SOFTWARE, RDFS.label, Literal("TEI CRM Bridge")))
        for key, value in sorted(settings.items()):
            datatype = XSD.decimal if isinstance(value, float) else XSD.integer if isinstance(value, int) else None
            self.graph.add((run, VOCAB[key], Literal(value, datatype=datatype)))
        if settings.get("engine") == "hf" and settings.get("modelRevision"):
            self.graph.add((run, PROV.used, URIRef(f"https://huggingface.co/{settings['model']}")))
        return run

    def add_mention(self, number: int, mention: Mention, run: URIRef | None) -> URIRef:
        uri = URIRef(f"{self.base}mention/{quote(self.doc_id, safe='')}/{number}")
        g = self.graph
        entities = [URIRef(entity) for entity in mention.entities]
        g.add((uri, RDF.type, OA.Annotation))
        g.add((uri, OA.motivatedBy, OA.identifying))
        for entity in entities:
            g.add((uri, OA.hasBody, entity))
        # Named blank nodes keep the Turtle serialization byte-for-byte reproducible.
        target = BNode(f"m{number}target")
        g.add((uri, OA.hasTarget, target))
        g.add((target, RDF.type, OA.SpecificResource))
        g.add((target, OA.hasSource, self.tei))
        # Alternative selectors for the same text, all resolvable in the enriched TEI file.
        # Positions and quotes use the XPath string value of the block: tags removed,
        # characters as in the file (W3C Web Annotation, 4.2.4 and 4.2.5).
        span = mention.projection.raw_span(mention.start, mention.end)
        raw = string_value(mention.projection.block) if span else None
        # An editorial element can contain whitespace outside the recorded name span.
        # Its unrefined XPath would then identify different text from the refined
        # block selectors, so omit that alternative.
        if mention.element is not None and (span is None or string_value(mention.element) == raw[span[0]:span[1]]):
            element = BNode(f"m{number}element")
            g.add((target, OA.hasSelector, element))
            g.add((element, RDF.type, OA.XPathSelector))
            g.add((element, RDF.value, Literal(xpath_selector(mention.element))))
        if span:
            block = xpath_selector(mention.projection.block)
            start, end = span
            for part, refinement in (("position", OA.TextPositionSelector), ("quote", OA.TextQuoteSelector)):
                selector, refined = BNode(f"m{number}{part}"), BNode(f"m{number}{part}text")
                g.add((target, OA.hasSelector, selector))
                g.add((selector, RDF.type, OA.XPathSelector))
                g.add((selector, RDF.value, Literal(block)))
                g.add((selector, OA.refinedBy, refined))
                g.add((refined, RDF.type, refinement))
                if refinement == OA.TextPositionSelector:
                    g.add((refined, OA.start, Literal(start, datatype=XSD.nonNegativeInteger)))
                    g.add((refined, OA.end, Literal(end, datatype=XSD.nonNegativeInteger)))
                else:
                    g.add((refined, OA.exact, Literal(raw[start:end])))
                    if start:
                        g.add((refined, OA.prefix, Literal(raw[max(0, start - 32):start])))
                    if end < len(raw):
                        g.add((refined, OA.suffix, Literal(raw[end:end + 32])))
        if mention.origin == "editorial":
            g.add((uri, VOCAB.origin, VOCAB.editorial))
            for entity in entities:
                g.add((self.doc, CRM.P67_refers_to, entity))
            for token in mention.unresolved:
                g.add((uri, VOCAB.unresolvedRef, Literal(token)))
        else:
            g.add((uri, VOCAB.origin, VOCAB.automatic))
            if run is not None:
                g.add((uri, PROV.wasGeneratedBy, run))
            elif mention.element is not None:
                # Reprocessing an enriched TEI keeps the original @resp. It
                # identifies the earlier software application in that source,
                # even though its processing activity cannot be reconstructed.
                resp = mention.element.get("resp") or ""
                if resp.startswith("#") and resp[1:] in self.ids:
                    application = URIRef(str(self.tei) + resp)
                    g.add((uri, PROV.wasAttributedTo, application))
                    g.add((application, RDF.type, PROV.SoftwareAgent))
            if mention.score is not None:
                g.add((uri, VOCAB.confidence, Literal(round(mention.score, 4), datatype=XSD.decimal)))
        return uri

    # Correspondence ---------------------------------------------------------

    def add_correspondence(self) -> int:
        counters: dict[str, int] = {}
        for action in self.root.iter(TEI + "correspAction"):
            kind = action.get("type")
            if kind not in EVENTS:
                self.warnings.append(f"correspAction type {kind!r} is not mapped")
                continue
            counters[kind] = counters.get(kind, 0) + 1
            event_type, label_de, label_en = EVENTS[kind]
            event = URIRef(f"{self.base}event/{quote(self.doc_id, safe='')}/{kind}-{counters[kind]}")
            g = self.graph
            g.add((event, RDF.type, CRM.E7_Activity))
            g.add((event, CRM.P2_has_type, event_type))
            g.add((event_type, RDF.type, CRM.E55_Type))
            g.add((event_type, RDFS.label, Literal(label_de, lang="de")))
            g.add((event_type, RDFS.label, Literal(label_en, lang="en")))
            g.add((event, RDFS.label, Literal(f"{label_de}: {self.title}")))
            g.add((self.doc, CRM.P70_documents, event))
            dates = []
            for node in action:
                entity_kind = name_kind(node) if isinstance(node.tag, str) else None
                if entity_kind:
                    label = _normalize("".join(node.itertext()))
                    if label or node.get("ref"):
                        entities, _, _ = self.entities_for(node, entity_kind, label or node.get("ref"))
                        predicate = CRM.P7_took_place_at if entity_kind == "LOC" else CRM.P14_carried_out_by
                        for entity in entities:
                            g.add((event, predicate, entity))
                elif local_name(node) == "date":
                    dates.append(node)
            if dates:
                self._time_span(event, dates)
        return sum(counters.values())

    def _time_span(self, event: URIRef, nodes: list[etree._Element]) -> None:
        """One time-span per event (P4 is many-to-one): the interval all dates agree on."""
        found = []
        for node in nodes:
            try:
                span = interval(node)
            except ValueError as error:
                self.warnings.append(f"date on {xpath_of(node)}: {error}")
                continue
            if span is not None:
                found.append((node, span))
        if not found:
            return
        try:
            span = intersect([item for _, item in found])
        except ValueError as error:
            self.warnings.append(f"{xpath_of(nodes[0].getparent())}: {error}")
            return
        uri = URIRef(f"{event}/time")
        g = self.graph
        g.add((uri, RDF.type, CRM["E52_Time-Span"]))
        g.add((event, CRM["P4_has_time-span"], uri))
        if span.begin:
            g.add((uri, CRM.P82a_begin_of_the_begin, Literal(span.begin, datatype=XSD.dateTime)))
        if span.end:
            g.add((uri, CRM.P82b_end_of_the_end, Literal(span.end, datatype=XSD.dateTime)))
        text = " / ".join(t for t in (_normalize("".join(node.itertext())) for node, _ in found) if t)
        if text:
            g.add((uri, RDFS.label, Literal(text)))
        qualifiers = "".join(f"; {name}={node.get(name)}" for node, _ in found for name in ("evidence", "cert") if node.get(name))
        g.add((uri, CRM.P3_has_note, Literal(f"TEI {span.source}{qualifiers}")))
