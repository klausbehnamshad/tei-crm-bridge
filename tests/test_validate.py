"""SHACL-Profil (Extra validate): Demos formkonform, vier rote Fälle mit Shape."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

pyshacl = pytest.importorskip("pyshacl")

from rdflib import Graph, RDF, URIRef

from tei_crm_bridge import validate as validate_module
from tei_crm_bridge.cli import run_validate
from tei_crm_bridge.review import apply_review

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_review  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LETTER = ROOT / "docs" / "example" / "letter.ttl"
SCHNITZLER = ROOT / "docs" / "schnitzler" / "L02051.ttl"
CRM = "http://www.cidoc-crm.org/cidoc-crm/"
OA = "http://www.w3.org/ns/oa#"
TCB = "https://klausbehnamshad.github.io/tei-crm-bridge/vocab/#"
SHP = "https://klausbehnamshad.github.io/tei-crm-bridge/shapes#"
P82A = URIRef(CRM + "P82a_begin_of_the_begin")
P82B = URIRef(CRM + "P82b_end_of_the_end")


def reviewed_graph(tmp_path: Path) -> Path:
    """Geprüfter Graph wie in test_review.py: eine Annahme, eine Ablehnung."""
    _, ttl, mentions, _, reviewed, record, automatic = test_review.prepared(tmp_path)
    accepted = automatic[0]
    rejected = next(m for m in automatic[1:] if m["entities"] != accepted["entities"])
    review = test_review.exported(tmp_path, record, mentions, ttl, [
        test_review.decision(accepted, "accepted"), test_review.decision(rejected, "rejected")])
    assert apply_review(mentions, ttl, review, reviewed) == (1, 1)
    return reviewed


def copy_letter(tmp_path: Path) -> Graph:
    return Graph().parse(LETTER, format="turtle")


def test_source_demos_conform():
    for demo in (LETTER, SCHNITZLER):
        report = validate_module.validate(demo, "source")
        assert report.conforms, [(item.shape, item.focus) for item in report.violations]
        assert report.violations == []


def test_reviewed_graph_conforms_reviewed(tmp_path):
    reviewed = reviewed_graph(tmp_path)
    graph = Graph().parse(reviewed, format="turtle")
    assessing = list(graph.subjects(URIRef(OA + "motivatedBy"), URIRef(OA + "assessing")))
    assert assessing, "Prüfvermerke fehlen im Fixture"
    classified = [o for o in graph.objects(None, URIRef(CRM + "P67_refers_to"))
                  if (o, RDF.type, URIRef(TCB + "Candidate")) in graph]
    assert classified, "angenommener Kandidat mit P67 fehlt im Fixture"
    report = validate_module.validate(reviewed, "reviewed")
    assert report.conforms, [(item.shape, item.focus) for item in report.violations]


def test_reviewed_graph_rejected_by_source(tmp_path):
    """Profilauswahl wirkt: P67 auf Kandidaten scheitert nur unter source."""
    reviewed = reviewed_graph(tmp_path)
    report = validate_module.validate(reviewed, "source")
    assert not report.conforms
    assert SHP + "P67SourceShape" in {item.shape for item in report.violations}


def test_candidate_with_crm_class(tmp_path):
    graph = copy_letter(tmp_path)
    candidate = next(graph.subjects(RDF.type, URIRef(TCB + "Candidate")))
    graph.add((candidate, RDF.type, URIRef(CRM + "E21_Person")))
    target = tmp_path / "neg1.ttl"
    graph.serialize(target, format="turtle")
    report = validate_module.validate(target, "source")
    assert not report.conforms
    assert SHP + "CandidateShape" in {item.shape for item in report.violations}


def test_event_without_type(tmp_path):
    graph = copy_letter(tmp_path)
    event = next(graph.subjects(RDF.type, URIRef(CRM + "E7_Activity")))
    for triple in list(graph.triples((event, URIRef(CRM + "P2_has_type"), None))):
        graph.remove(triple)
    target = tmp_path / "neg2.ttl"
    graph.serialize(target, format="turtle")
    report = validate_module.validate(target, "source")
    assert not report.conforms
    assert SHP + "EventShape" in {item.shape for item in report.violations}


def test_time_span_end_before_begin(tmp_path):
    graph = copy_letter(tmp_path)
    span = next(s for s in graph.subjects(RDF.type, URIRef(CRM + "E52_Time-Span"))
                if graph.value(s, P82A) and graph.value(s, P82B))
    begin, end = graph.value(span, P82A), graph.value(span, P82B)
    graph.remove((span, P82A, begin))
    graph.remove((span, P82B, end))
    graph.add((span, P82A, end))
    graph.add((span, P82B, begin))
    target = tmp_path / "neg3.ttl"
    graph.serialize(target, format="turtle")
    report = validate_module.validate(target, "source")
    assert not report.conforms
    assert SHP + "TimeSpanShape" in {item.shape for item in report.violations}


def test_annotation_without_target(tmp_path):
    graph = copy_letter(tmp_path)
    annotation = next(graph.subjects(URIRef(TCB + "origin"), URIRef(TCB + "editorial")))
    for triple in list(graph.triples((annotation, URIRef(OA + "hasTarget"), None))):
        graph.remove(triple)
    target = tmp_path / "neg4.ttl"
    graph.serialize(target, format="turtle")
    report = validate_module.validate(target, "source")
    assert not report.conforms
    assert SHP + "MentionTargetShape" in {item.shape for item in report.violations}


def test_cli_return_values(tmp_path, capsys):
    """Exit 0 konform, Exit 1 Verstöße, Exit 2 fehlende Datei."""
    parser = argparse.ArgumentParser(prog="tei-crm validate")
    run_validate(argparse.Namespace(graph=LETTER, profile="source"), parser)
    assert json.loads(capsys.readouterr().out)["conforms"] is True
    graph = copy_letter(tmp_path)
    candidate = next(graph.subjects(RDF.type, URIRef(TCB + "Candidate")))
    graph.add((candidate, RDF.type, URIRef(CRM + "E21_Person")))
    bad = tmp_path / "rot.ttl"
    graph.serialize(bad, format="turtle")
    with pytest.raises(SystemExit) as violations:
        run_validate(argparse.Namespace(graph=bad, profile="source"), parser)
    assert violations.value.code == 1
    with pytest.raises(SystemExit) as missing:
        run_validate(argparse.Namespace(graph=tmp_path / "fehlt.ttl", profile="source"), parser)
    assert missing.value.code == 2


def test_cli_missing_extra(monkeypatch, capsys):
    """Ohne installiertes Extra endet die CLI mit Exit 2 und Installationshinweis."""
    monkeypatch.setitem(sys.modules, "pyshacl", None)
    monkeypatch.delitem(sys.modules, "tei_crm_bridge.validate")
    monkeypatch.delattr("tei_crm_bridge.validate")
    parser = argparse.ArgumentParser(prog="tei-crm validate")
    with pytest.raises(SystemExit) as absent:
        run_validate(argparse.Namespace(graph=LETTER, profile="source"), parser)
    assert absent.value.code == 2
    assert "tei-crm-bridge[validate]" in capsys.readouterr().err
