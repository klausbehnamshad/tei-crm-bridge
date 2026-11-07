"""Target- und Profilregeln ohne Abhängigkeit vom origin-Marker."""

import pytest

pytest.importorskip("pyshacl")

from rdflib import BNode, Graph, Namespace, RDF, URIRef
from tei_crm_bridge import validate

OA = Namespace("http://www.w3.org/ns/oa#")
SHP = "https://klausbehnamshad.github.io/tei-crm-bridge/shapes#"


@pytest.mark.parametrize("missing", ["target", "source", "selector"])
def test_annotation_without_origin_still_requires_evidence_target(tmp_path, missing):
    graph = Graph()
    ann, target = URIRef("urn:probe:annotation"), BNode()
    graph.add((ann, RDF.type, OA.Annotation))
    if missing != "target":
        graph.add((ann, OA.hasTarget, target))
    if missing != "source":
        graph.add((target, OA.hasSource, URIRef("urn:probe:tei")))
    if missing != "selector":
        graph.add((target, OA.hasSelector, BNode()))
    path = tmp_path / "incomplete.ttl"
    graph.serialize(path, format="turtle")
    report = validate.validate(path)
    assert not report.conforms
    assert SHP + "MentionTargetShape" in {item.shape for item in report.violations}


def test_assessment_target_must_be_an_annotation(tmp_path):
    graph = Graph()
    assessment = URIRef("urn:probe:assessment")
    graph.add((assessment, RDF.type, OA.Annotation))
    graph.add((assessment, OA.motivatedBy, OA.assessing))
    graph.add((assessment, OA.hasTarget, URIRef("urn:probe:untyped")))
    path = tmp_path / "assessment.ttl"
    graph.serialize(path, format="turtle")
    report = validate.validate(path, "source")
    assert not report.conforms
    assert SHP + "MentionTargetShape" in {item.shape for item in report.violations}
