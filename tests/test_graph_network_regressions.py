"""Grenzfälle aus dem Graph-Review, unabhängig vom 40-Brief-Korpus."""

import argparse
import json
from pathlib import Path

import pytest

nx = pytest.importorskip("networkx")

from tei_crm_bridge import network
from tei_crm_bridge.cli import run_network


def letter(tmp_path, dates='<date when="1900-01-01"/>', received_date=""):
    path = tmp_path / "probe.xml"
    path.write_text(f'''<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="probe"
        xml:base="https://example.org/edition/">
      <teiHeader><profileDesc><correspDesc>
        <correspAction type="sent"><persName ref="#p1 #p2">A und B</persName>{dates}</correspAction>
        <correspAction type="received"><persName ref="#p3">C</persName>{received_date}</correspAction>
      </correspDesc></profileDesc></teiHeader>
      <text><body><p>Probe.</p></body><back><listPerson>
        <person xml:id="p1"><persName>A</persName><idno subtype="gnd">https://d-nb.info/gnd/111</idno></person>
        <person xml:id="p2"><persName>B</persName><idno subtype="gnd">https://d-nb.info/gnd/222</idno></person>
        <person xml:id="p3"><persName>C</persName></person>
      </listPerson></back></text></TEI>''', encoding="utf-8")
    return path


def test_gnd_belongs_to_each_ref_token(tmp_path):
    graph, _ = network.build_correspondence([letter(tmp_path)])
    assert graph.nodes["https://example.org/edition/#p1"]["gnd"] == "https://d-nb.info/gnd/111"
    assert graph.nodes["https://example.org/edition/#p2"]["gnd"] == "https://d-nb.info/gnd/222"


@pytest.mark.parametrize("dates", [
    '<date when="unbekannt"/>',
    '<date when="1900-01-01"/><date when="1902-01-01"/>',
    '<date when="1900-01-01"/><date when="1900-01-01T12:00Z"/>',
])
def test_invalid_sent_dates_are_collected_without_received_fallback(tmp_path, dates):
    path = letter(tmp_path, dates, '<date when="1901-01-01"/>')
    graph, stats = network.build_correspondence([path])
    assert graph.number_of_edges() == 2
    assert stats["date_fallbacks"] == []
    assert len(stats["date_errors"]) == 1
    error = stats["date_errors"][0]
    assert (error["file"], error["letter"], error["action"]) == (str(path), "probe", "sent")
    assert error["message"]
    for _, _, edge in graph.edges(data=True):
        assert (edge["date_begin"], edge["date_end"], edge["date_source"]) == ("", "", "none")


def test_date_errors_keep_other_letters_and_cli_metrics(tmp_path, capsys):
    broken = letter(tmp_path, received_date='<date when="unbekannt"/>')
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    clean = letter(clean_dir)
    clean.write_text(clean.read_text().replace('xml:id="probe"', 'xml:id="clean"'))
    out = tmp_path / "out"
    run_network(argparse.Namespace(inputs=[clean, broken], out_dir=out, graphs=None),
                argparse.ArgumentParser())
    summary = json.loads(capsys.readouterr().out)
    errors = summary["date_errors"]
    assert [(error["letter"], error["action"]) for error in errors] == [("probe", "received")]
    body = json.loads((out / "metrics.json").read_text())
    assert body["correspondence"]["date_errors"] == errors
    graph = nx.read_graphml(out / "correspondence.graphml")
    assert graph.number_of_edges() == 2
    for _, _, edge in graph.edges(data=True):
        assert edge["weight"] == 2
        assert edge["letters"] == "clean;probe"
        assert edge["date_source"] == "sent;none"
        assert edge["date_begin"] == "1900-01-01T00:00:00;"
        assert edge["date_end"] == "1900-01-01T23:59:59;"


def test_dates_conflicting_across_actions_are_collected(tmp_path):
    path = letter(tmp_path)
    path.write_text(path.read_text().replace('</correspDesc>',
        '<correspAction type="sent"><date when="1902-01-01"/></correspAction></correspDesc>'))
    graph, stats = network.build_correspondence([path])
    assert [(error["letter"], error["action"]) for error in stats["date_errors"]] == [("probe", "sent")]
    assert {edge["date_source"] for _, _, edge in graph.edges(data=True)} == {"none"}


def test_received_date_fallback_names_its_source(tmp_path):
    graph, stats = network.build_correspondence([
        letter(tmp_path, "", '<date when="1901-01-01"/>')])
    assert stats["date_fallbacks"] == ["probe"]
    assert {data["date_source"] for _, _, data in graph.edges(data=True)} == {"received"}


def mention_file(tmp_path, documents=None):
    documents = documents or ["https://example.org/document/brief"]
    path = tmp_path / "mentions.ttl"
    rows = ['@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .',
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .']
    for document in documents:
        rows.append(f'''<{document}> a crm:E31_Document;
          crm:P67_refers_to <https://d-nb.info/gnd/111>, <https://d-nb.info/gnd/222>,
            <https://example.org/place/1>, <https://example.org/group/1>,
            <{document}/candidate/1>, <https://example.org/untyped> .''')
    rows.extend([
        '<https://d-nb.info/gnd/111> a crm:E21_Person; rdfs:label "Z", "A" .',
        '<https://d-nb.info/gnd/222> a crm:E21_Person .',
        '<https://example.org/place/1> a crm:E53_Place .',
        '<https://example.org/group/1> a crm:E74_Group .',
    ])
    for document in documents:
        rows.append(f'<{document}/candidate/1> a crm:E21_Person .')
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def test_projection_accepts_external_person_uris(tmp_path):
    graph, _ = network.build_mentions([mention_file(tmp_path)])
    assert set(graph) == {"https://d-nb.info/gnd/111", "https://d-nb.info/gnd/222"}
    assert graph.number_of_edges() == 1
    assert graph.nodes["https://d-nb.info/gnd/111"]["label"] == "A"


def test_different_document_uris_keep_separate_letter_identity(tmp_path):
    documents = ["https://edition-a.example/document/X", "https://edition-b.example/document/X"]
    graph, _ = network.build_mentions([mention_file(tmp_path, documents)])
    edge = graph.edges["https://d-nb.info/gnd/111", "https://d-nb.info/gnd/222"]
    assert edge["weight"] == 2
    assert edge["letter_uris"].split(";") == documents


def test_local_entities_are_excluded_for_different_document_prefix_lengths(tmp_path):
    documents = ["urn:edition:a", "https://example.org/edition/long/document/Z"]
    graph, stats = network.build_bipartite_mentions([mention_file(tmp_path, documents)])
    assert graph.number_of_edges() == 8
    assert stats["entities"] == 4
    assert all(document + "/candidate/1" not in graph for document in documents)


def test_errors_from_both_actions_are_collected(tmp_path):
    path = letter(tmp_path, '<date when="ungültig"/>', '<date when="auch-ungültig"/>')
    _, stats = network.build_correspondence([path])
    assert [error["action"] for error in stats["date_errors"]] == ["sent", "received"]


def test_cli_exports_bipartite_graph_and_person_projection(tmp_path):
    out = tmp_path / "out"
    run_network(argparse.Namespace(inputs=[letter(tmp_path)], out_dir=out,
                                   graphs=[mention_file(tmp_path)]), argparse.ArgumentParser())
    bipartite = nx.read_graphml(out / "mentions_bipartite.graphml")
    assert bipartite.is_directed()
    assert bipartite.number_of_nodes() == 5
    assert bipartite.number_of_edges() == 4
    assert set(bipartite.successors("https://example.org/document/brief")) == {
        "https://d-nb.info/gnd/111", "https://d-nb.info/gnd/222",
        "https://example.org/place/1", "https://example.org/group/1"}
    assert (out / "mentions_bipartite_edges.csv").exists()
    assert nx.read_graphml(out / "mentions.graphml").number_of_edges() == 1
    body = json.loads((out / "metrics.json").read_text())
    assert body["mentions_bipartite"]["edges"] == 4
    assert body["networkx_version"] == nx.__version__


def test_metric_method_identifies_raw_unweighted_degree(tmp_path):
    graph = nx.DiGraph([("a", "b"), ("a", "c")])
    measured = network.graph_metrics(graph, {}, directed=True)
    body = network.metrics([], None, measured, None)
    assert body["correspondence"]["top_degree"][0]["value"] == 2
    assert "ungewichteter Gesamtgrad" in body["method"]
    assert "normalisierte ungewichtete Betweenness" in body["method"]
