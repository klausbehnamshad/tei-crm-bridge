"""TEI enrichment and conservative CIDOC CRM export."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

from lxml import etree
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

from .ner import Entity, Recognizer, resolve_overlaps


TEI_URI = "http://www.tei-c.org/ns/1.0"
TEI = "{" + TEI_URI + "}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
OA = Namespace("http://www.w3.org/ns/oa#")
EX = Namespace("https://example.org/tei-crm/vocab/")
NS = {"tei": TEI_URI}
TAGS = {"PER": "persName", "LOC": "placeName", "ORG": "orgName"}
CLASSES = {"PER": CRM.E21_Person, "LOC": CRM.E53_Place, "ORG": CRM.E74_Group}
REVERSE_TAGS = {value: key for key, value in TAGS.items()}


@dataclass(frozen=True)
class Result:
    paragraphs: int
    new_annotations: int
    existing_annotations: int
    events: int
    triples: int


def _safe_key(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")[:48] or "entity"
    digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def _slots(element: etree._Element):
    """Yield text slots, leaving existing named entities and their contents alone."""
    if element.text:
        yield element, "text", element.text
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if etree.QName(child).localname not in REVERSE_TAGS:
            yield from _slots(child)
        if child.tail:
            yield child, "tail", child.tail


def _insert(owner: etree._Element, slot: str, text: str, entities: list[Entity]):
    """Split one lxml text or tail slot without flattening surrounding markup."""
    if not entities:
        return []
    parent = owner if slot == "text" else owner.getparent()
    index = 0 if slot == "text" else parent.index(owner) + 1
    if slot == "text":
        owner.text = text[:entities[0].start]
    else:
        owner.tail = text[:entities[0].start]
    created = []
    for position, entity in enumerate(entities):
        node = etree.Element(TEI + TAGS[entity.kind])
        node.text = text[entity.start:entity.end]
        next_start = entities[position + 1].start if position + 1 < len(entities) else len(text)
        node.tail = text[entity.end:next_start]
        parent.insert(index, node)
        index += 1
        created.append((node, entity))
    return created


def enrich(
    input_path: Path,
    output_tei: Path,
    output_ttl: Path,
    recognizer: Recognizer,
    base_uri: str,
    threshold: float = 0.85,
) -> Result:
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if not base_uri.startswith(("https://", "http://")):
        raise ValueError("base URI must be an HTTP(S) URI")
    base_uri = base_uri.rstrip("/") + "/"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    tree = etree.parse(str(input_path), parser)
    root = tree.getroot()
    if root.tag != TEI + "TEI":
        raise ValueError("Input must have a TEI P5 root in the official namespace")
    doc_id = root.get(XML_ID) or input_path.stem
    doc_uri = URIRef(base_uri + "document/" + quote(doc_id, safe=""))

    graph = Graph()
    graph.bind("crm", CRM)
    graph.bind("oa", OA)
    graph.bind("ex", EX)
    graph.bind("rdfs", RDFS)
    graph.add((doc_uri, RDF.type, CRM.E31_Document))
    title = root.find("./" + TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "title")
    graph.add((doc_uri, RDFS.label, Literal("".join(title.itertext(with_tail=False)).strip() if title is not None else doc_id)))

    def entity_uri(kind: str, label: str) -> URIRef:
        uri = URIRef(str(doc_uri) + "/entity/" + kind.lower() + "/" + _safe_key(label))
        graph.add((uri, RDF.type, CLASSES[kind]))
        graph.add((uri, RDFS.label, Literal(label)))
        return uri

    paragraphs = root.xpath(".//tei:body//tei:p", namespaces=NS)
    existing = []
    for paragraph in paragraphs:
        for node in paragraph.iterdescendants():
            if isinstance(node.tag, str):
                kind = REVERSE_TAGS.get(etree.QName(node).localname)
                if kind and etree.QName(node).namespace == TEI_URI:
                    existing.append((node, kind, None, "tei-existing"))

    generated = []
    for paragraph in paragraphs:
        for owner, slot, text in list(_slots(paragraph)):
            candidates = resolve_overlaps(recognizer.find(text), text, threshold)
            for node, entity in _insert(owner, slot, text, candidates):
                generated.append((node, entity.kind, entity.score, entity.source))

    for number, (node, kind, score, source) in enumerate(existing + generated, start=1):
        label = "".join(node.itertext(with_tail=False)).strip()
        if not label:
            continue
        target = entity_uri(kind, label)
        if source != "tei-existing":
            node.set("ref", str(target))
        mention_uri = URIRef(base_uri + "mention/" + quote(doc_id, safe="") + f"/{number}")
        graph.add((doc_uri, CRM.P67_refers_to, target))
        graph.add((mention_uri, RDF.type, OA.Annotation))
        graph.add((mention_uri, OA.hasTarget, doc_uri))
        graph.add((mention_uri, OA.hasBody, target))
        graph.add((mention_uri, EX.surface, Literal(label)))
        graph.add((mention_uri, EX.source, Literal(source)))
        graph.add((mention_uri, EX.teiXPath, Literal(tree.getpath(node))))
        if score is not None:
            graph.add((mention_uri, EX.confidence, Literal(score, datatype=XSD.decimal)))

    events = 0
    for action in root.xpath(".//tei:correspAction[@type='sent']", namespaces=NS):
        events += 1
        event_uri = URIRef(base_uri + "event/" + quote(doc_id, safe="") + f"/sent-{events}")
        graph.add((event_uri, RDF.type, CRM.E7_Activity))
        graph.add((event_uri, RDFS.label, Literal(f"Versand von {doc_id}")))
        graph.add((doc_uri, CRM.P70_documents, event_uri))
        for node in action:
            if not isinstance(node.tag, str) or etree.QName(node).namespace != TEI_URI:
                continue
            kind = REVERSE_TAGS.get(etree.QName(node).localname)
            if kind in {"PER", "ORG", "LOC"}:
                label = "".join(node.itertext(with_tail=False)).strip()
                if label:
                    target = entity_uri(kind, label)
                    predicate = CRM.P7_took_place_at if kind == "LOC" else CRM.P14_carried_out_by
                    graph.add((event_uri, predicate, target))
            elif node.tag == TEI + "date":
                when = node.get("when")
                if when:
                    try:
                        value = date.fromisoformat(when)
                    except ValueError:
                        continue
                    span_uri = URIRef(str(event_uri) + "/time")
                    graph.add((span_uri, RDF.type, CRM["E52_Time-Span"]))
                    graph.add((span_uri, CRM.P82_at_some_time_within, Literal(value.isoformat(), datatype=XSD.date)))
                    graph.add((event_uri, CRM["P4_has_time-span"], span_uri))

    output_tei.parent.mkdir(parents=True, exist_ok=True)
    output_ttl.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_tei), encoding="utf-8", xml_declaration=True, pretty_print=False)
    graph.serialize(destination=str(output_ttl), format="turtle")
    return Result(len(paragraphs), len(generated), len(existing), events, len(graph))
