"""Human review must stay tied to one source run and one automatic text span."""

import hashlib
import json

import pytest
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import DCTERMS, PROV

from tei_crm_bridge.core import enrich
from tei_crm_bridge.ner import GlossaryRecognizer
from tei_crm_bridge.preview import write_preview
from tei_crm_bridge.rdf import CLASSES, CRM, OA, VOCAB
from tei_crm_bridge.review import apply_review, review_source


def prepared(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = root / "examples/letter.xml"
    xml, ttl, mentions, preview, reviewed = (tmp_path / name for name in
                                           ("letter.enriched.xml", "letter.ttl", "letter.mentions.json",
                                            "letter.html", "letter.reviewed.ttl"))
    result = enrich(source, xml, ttl, GlossaryRecognizer(root / "examples/glossary.json"),
                    "https://example.org/review/", output_json=mentions)
    write_preview(xml, ttl, mentions, preview, result)
    record = json.loads(mentions.read_text(encoding="utf-8"))
    automatic = [m for m in record["mentions"] if m["origin"] == "automatic"]
    return xml, ttl, mentions, preview, reviewed, record, automatic


def decision(mention, value):
    return {key: mention[key] for key in ("id", "block", "start", "end", "text", "kind")} | {
        "decision": value, "note": "Redaktionell geprüft", "decidedAt": "2026-09-26T12:00:00Z",
    }


def exported(tmp_path, record, mentions, ttl, choices):
    review = tmp_path / "letter.review.json"
    review.write_text(json.dumps({
        "format": "tei-crm-bridge-review", "version": 1,
        "source": review_source(record, mentions, ttl), "reviewer": "KB",
        "exportedAt": "2026-09-26T12:05:00Z", "decisions": choices,
    }), encoding="utf-8")
    return review


def test_review_adds_only_accepted_statements_to_separate_graph(tmp_path):
    xml, ttl, mentions, preview, reviewed, record, automatic = prepared(tmp_path)
    original_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (xml, ttl, mentions)}
    accepted, rejected = automatic[0], next(m for m in automatic[1:] if m["entities"] != automatic[0]["entities"])
    review = exported(tmp_path, record, mentions, ttl, [decision(accepted, "accepted"), decision(rejected, "rejected")])

    assert apply_review(mentions, ttl, review, reviewed) == (1, 1)
    base, graph = Graph().parse(ttl, format="turtle"), Graph().parse(reviewed, format="turtle")
    document = next(base.subjects(RDF.type, CRM.E31_Document))
    yes, no = URIRef(accepted["entities"][0]), URIRef(rejected["entities"][0])
    assert (yes, RDF.type, CLASSES[accepted["kind"]]) in graph
    assert (document, CRM.P67_refers_to, yes) in graph
    assert (no, RDF.type, CLASSES[rejected["kind"]]) not in graph
    assert (document, CRM.P67_refers_to, no) not in graph
    assert (yes, RDF.type, CLASSES[accepted["kind"]]) not in base
    assessments = list(graph.subjects(OA.motivatedBy, OA.assessing))
    assert len(assessments) == 2
    assert {graph.value(a, OA.hasBody) for a in assessments} == {VOCAB.accepted, VOCAB.rejected}
    assert all(graph.value(a, DCTERMS.created) and graph.value(a, DCTERMS.creator) for a in assessments)
    assert list(graph.subjects(RDF.type, PROV.Agent))
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in original_hashes.items())
    assert 'id="review-export"' in preview.read_text(encoding="utf-8")
    assert 'data-mention-id="' in preview.read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["checksum", "position", "editorial", "duplicate", "graph"])
def test_review_rejects_stale_or_changed_decisions_without_output(tmp_path, change):
    _, ttl, mentions, _, reviewed, record, automatic = prepared(tmp_path)
    choice = decision(automatic[0], "accepted")
    review = exported(tmp_path, record, mentions, ttl, [choice])
    data = json.loads(review.read_text(encoding="utf-8"))
    if change == "checksum":
        data["source"]["mentionsSha256"] = "0" * 64
    elif change == "position":
        data["decisions"][0]["start"] += 1
    elif change == "editorial":
        data["decisions"][0] = decision(next(m for m in record["mentions"] if m["origin"] == "editorial"), "accepted")
    elif change == "duplicate":
        data["decisions"].append(choice)
    elif change == "graph":
        data["source"]["graphSha256"] = "0" * 64
    review.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        apply_review(mentions, ttl, review, reviewed)
    assert not reviewed.exists()


def test_review_will_not_overwrite_source_file(tmp_path):
    _, ttl, mentions, _, _, record, automatic = prepared(tmp_path)
    review = exported(tmp_path, record, mentions, ttl, [decision(automatic[0], "accepted")])
    with pytest.raises(ValueError, match="output must differ"):
        apply_review(mentions, ttl, review, ttl)


def test_opposite_assessments_of_shared_candidate_stay_per_mention(tmp_path):
    _, ttl, mentions, _, reviewed, record, automatic = prepared(tmp_path)
    first = automatic[0]
    second = next(m for m in automatic[1:] if m["entities"] == first["entities"])
    review = exported(tmp_path, record, mentions, ttl, [decision(first, "accepted"), decision(second, "rejected")])
    assert apply_review(mentions, ttl, review, reviewed) == (1, 1)
    graph = Graph().parse(reviewed, format="turtle")
    candidate = URIRef(first["entities"][0])
    assert (candidate, RDF.type, CLASSES[first["kind"]]) in graph
    targets = {str(graph.value(a, OA.hasTarget)): graph.value(a, OA.hasBody)
               for a in graph.subjects(OA.motivatedBy, OA.assessing)}
    assert targets[next(uri for uri in targets if uri.endswith(f"/{first['id']}"))] == VOCAB.accepted
    assert targets[next(uri for uri in targets if uri.endswith(f"/{second['id']}"))] == VOCAB.rejected


def test_preview_escapes_script_delimiter_in_mention_text(tmp_path):
    xml, ttl, mentions, preview, _, record, automatic = prepared(tmp_path)
    record["mentions"][record["mentions"].index(automatic[0])]["text"] = "</script><script>alert(1)</script>"
    mentions.write_text(json.dumps(record), encoding="utf-8")
    from tei_crm_bridge.core import Result

    write_preview(xml, ttl, mentions, preview, Result(0, 0, 0, 0, 0, 0, 0, ()))
    html = preview.read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script>" in html
