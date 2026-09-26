"""Validate human decisions and make a separate, attributable reviewed graph."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, RDF, RDFS, URIRef, XSD
from rdflib.namespace import DCTERMS, PROV

from .rdf import CLASSES, CRM, OA, VOCAB


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_source(record: dict, mentions_path: Path, graph_path: Path) -> dict:
    return {
        "document": record["document"],
        "inputSha256": record["input"]["sha256"],
        "mentionsSha256": sha256(mentions_path),
        "graphSha256": sha256(graph_path),
    }


def _timestamp(value: object) -> Literal:
    if not isinstance(value, str):
        raise ValueError("decidedAt must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("decidedAt must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("decidedAt must include a timezone")
    return Literal(value, datatype=XSD.dateTime)


def validate_review(review: dict, record: dict, mentions_path: Path, graph_path: Path) -> list[dict]:
    """Return validated decisions; reject stale exports and changed mention identities."""
    if not isinstance(review, dict) or review.get("format") != "tei-crm-bridge-review" or review.get("version") != 1:
        raise ValueError("unsupported review format/version")
    if review.get("source") != review_source(record, mentions_path, graph_path):
        raise ValueError("review source checksums do not match these mentions and RDF files")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
        raise ValueError("reviewer must be a nonempty name (at most 200 characters)")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("decisions must be a list")
    mentions = {m["id"]: m for m in record["mentions"]}
    seen = set()
    for decision in decisions:
        if not isinstance(decision, dict) or type(decision.get("id")) is not int:
            raise ValueError("every decision needs an integer mention id")
        number = decision["id"]
        if number in seen:
            raise ValueError(f"duplicate decision for mention {number}")
        seen.add(number)
        mention = mentions.get(number)
        if mention is None or mention["origin"] != "automatic":
            raise ValueError(f"mention {number} is absent or not automatic")
        for key in ("block", "start", "end", "text", "kind"):
            if decision.get(key) != mention[key]:
                raise ValueError(f"mention {number} has a mismatched {key}")
        if decision.get("decision") not in ("accepted", "rejected"):
            raise ValueError(f"mention {number} needs accepted or rejected")
        note = decision.get("note")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError(f"mention {number} note must be text of at most 2000 characters")
        _timestamp(decision.get("decidedAt"))
    return decisions


def apply_review(mentions_path: Path, graph_path: Path, review_path: Path, output_path: Path) -> tuple[int, int]:
    """Write a reviewed Turtle graph without modifying the original TEI, mentions or RDF."""
    inputs = (mentions_path, graph_path, review_path)
    if output_path.resolve() in {path.resolve() for path in inputs}:
        raise ValueError("output must differ from every input file")
    record = json.loads(mentions_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    decisions = validate_review(review, record, mentions_path, graph_path)
    graph = Graph().parse(graph_path, format="turtle")
    graph.bind("oa", OA)
    graph.bind("crm", CRM)
    graph.bind("tcb", VOCAB)
    graph.bind("prov", PROV)
    graph.bind("dcterms", DCTERMS)
    doc_suffix = "/document/" + quote(record["document"], safe="")
    documents = [node for node in graph.subjects(RDF.type, CRM.E31_Document) if str(node).endswith(doc_suffix)]
    if len(documents) != 1:
        raise ValueError("RDF does not contain exactly one matching document")
    document = documents[0]
    reviewer = BNode("reviewer-" + hashlib.sha256(review["reviewer"].strip().encode()).hexdigest()[:16])
    accepted = rejected = 0
    for decision in decisions:
        number = decision["id"]
        suffix = "/mention/" + quote(record["document"], safe="") + f"/{number}"
        annotations = [node for node in graph.subjects(RDF.type, OA.Annotation) if str(node).endswith(suffix)]
        if len(annotations) != 1:
            raise ValueError(f"RDF annotation for mention {number} is missing or ambiguous")
        annotation = annotations[0]
        if (annotation, VOCAB.origin, VOCAB.automatic) not in graph:
            raise ValueError(f"RDF mention {number} is not automatic")
        bodies = list(graph.objects(annotation, OA.hasBody))
        mention = next(m for m in record["mentions"] if m["id"] == number)
        if len(bodies) != 1 or str(bodies[0]) not in mention["entities"]:
            raise ValueError(f"RDF body for mention {number} does not match the mentions file")
        body = bodies[0]
        if (body, RDF.type, VOCAB.Candidate) not in graph or (body, VOCAB.suggestedClass, CLASSES[mention["kind"]]) not in graph:
            raise ValueError(f"RDF candidate for mention {number} has the wrong suggested class")
        assessment = URIRef(str(annotation) + "/assessment")
        graph.add((assessment, RDF.type, OA.Annotation))
        graph.add((assessment, OA.motivatedBy, OA.assessing))
        graph.add((assessment, OA.hasTarget, annotation))
        graph.add((assessment, OA.hasBody, VOCAB[decision["decision"]]))
        graph.add((assessment, DCTERMS.creator, reviewer))
        graph.add((assessment, DCTERMS.created, _timestamp(decision["decidedAt"])))
        if decision["note"]:
            graph.add((assessment, RDFS.comment, Literal(decision["note"])))
        if decision["decision"] == "accepted":
            graph.add((body, RDF.type, CLASSES[mention["kind"]]))
            graph.add((document, CRM.P67_refers_to, body))
            accepted += 1
        else:
            rejected += 1
    if decisions:
        graph.add((reviewer, RDF.type, PROV.Agent))
        graph.add((reviewer, RDFS.label, Literal(review["reviewer"].strip())))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    return accepted, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply human review decisions to a separate RDF graph")
    parser.add_argument("mentions", type=Path, help="original .mentions.json")
    parser.add_argument("graph", type=Path, help="original .ttl")
    parser.add_argument("review", type=Path, help="exported .review.json")
    parser.add_argument("output", type=Path, help="new .reviewed.ttl")
    args = parser.parse_args()
    try:
        accepted, rejected = apply_review(args.mentions, args.graph, args.review, args.output)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"{accepted} accepted, {rejected} rejected → {args.output}")


if __name__ == "__main__":
    main()
