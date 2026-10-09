"""Netzwerk-Extra: Korrespondenz- und Nennungsnetz mit unabhängigen Gegenwegen."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path

import pytest

networkx = pytest.importorskip("networkx")

from lxml import etree
from rdflib import Graph, RDF, URIRef

from tei_crm_bridge import network as network_module
from tei_crm_bridge.cli import run_network
from tei_crm_bridge.projection import TEI_URI
from tei_crm_bridge.rdf import GraphBuilder

ROOT = Path(__file__).resolve().parents[1]
SPARQL_DIR = ROOT / "eval" / "sparql"
sys.path.insert(0, str(SPARQL_DIR))
import build_graph  # noqa: E402

NS = {"tei": TEI_URI}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE_URI = "https://example.org/tei-crm-bridge/network/"


@pytest.fixture(scope="module")
def letters():
    """Die 40 Korpusbriefe (committet, keine Modellläufe nötig)."""
    found = sorted((ROOT / "eval" / "corpus").glob("L*.xml"))
    assert len(found) == 40
    return found


@pytest.fixture(scope="module")
def graphs(tmp_path_factory):
    """Die 40 Briefgraphen frisch gebaut, Hash gegen das Manifest geprüft."""
    out = tmp_path_factory.mktemp("network")
    (out / "letters").mkdir()
    built = build_graph.build_letters(out)
    assert build_graph.files_hash(built) == build_graph.load_manifest()["graph_sha256"]
    return built


def xpath_pairs(paths: list[Path]) -> dict[tuple[str, str], set[str]]:
    """Kanten-Gegenweg ohne network.py: XPath-Paare, @ref über rdf.py aufgelöst."""
    pairs: dict[tuple[str, str], set[str]] = {}
    for path in paths:
        root = etree.parse(str(path)).getroot()
        doc = root.get(XML_ID) or path.stem
        builder = GraphBuilder(root, doc, BASE_URI, [])
        found: dict[str, list[str]] = {}
        for kind in ("sent", "received"):
            uris = []
            for action in root.xpath(f"//tei:correspDesc/tei:correspAction[@type='{kind}']",
                                     namespaces=NS):
                for name in action.xpath("tei:persName", namespaces=NS):
                    for token in (name.get("ref") or "").split():
                        resolved = builder.resolve(token, name)
                        if resolved is not None:
                            uris.append(resolved[0])
            found[kind] = uris
        for first in found["sent"]:
            for second in found["received"]:
                pairs.setdefault((first, second), set()).add(doc)
    return pairs


def test_correspondence_matches_xpath(letters):
    """Kantenzahl und Gewichte gleich den XPath-Paaren (unabhängig von network.py)."""
    graph, stats = network_module.build_correspondence(letters)
    assert stats["without_sent"] == [] and stats["without_received"] == []
    want = xpath_pairs(letters)
    assert graph.number_of_edges() == len(want)
    for first, second, data in graph.edges(data=True):
        assert data["weight"] == len(want[(first, second)])
        assert set(data["letters"].split(";")) == want[(first, second)]


PMB_PERSON = re.compile(r"https://id\.acdh\.oeaw\.ac\.at/schnitzler/"
                         r"schnitzler-briefe/editions#pmb[0-9]+$")
E21 = "http://www.cidoc-crm.org/cidoc-crm/E21_Person"
E31 = "http://www.cidoc-crm.org/cidoc-crm/E31_Document"
P67 = "http://www.cidoc-crm.org/cidoc-crm/P67_refers_to"


def letter_persons(path: Path) -> set[str]:
    """P67-Personen einer Briefdatei per rdflib (ohne network.py)."""
    graph = Graph()
    graph.parse(path, format="turtle")
    documents = [str(node) for node in graph.subjects(RDF.type, URIRef(E31))]
    persons = set()
    for doc in documents:
        for entity in graph.objects(URIRef(doc), URIRef(P67)):
            uri = str(entity)
            if (PMB_PERSON.match(uri) and (entity, RDF.type, URIRef(E21)) in graph
                    and not any(uri.startswith(prefix) for prefix in documents)):
                persons.add(uri)
    return persons


def sparql_body(name: str) -> str:
    text = (SPARQL_DIR / f"{name}.rq").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


def test_projection_matches_rdflib_per_letter(graphs):
    """(1) Kanten und Gewichte gleich den Paaren je Briefdatei (rdflib-Gegenweg)."""
    want: dict[frozenset, set[str]] = {}
    for target in graphs:
        for first, second in combinations(sorted(letter_persons(target)), 2):
            want.setdefault(frozenset((first, second)), set()).add(target.stem)
    graph, _ = network_module.build_mentions(graphs)
    got = {frozenset((first, second)): (data["weight"], set(data["letters"].split(";")))
           for first, second, data in graph.edges(data=True)}
    assert set(got) == set(want)
    for pair, (weight, letters) in got.items():
        assert weight == len(want[pair]) and letters == want[pair]


def test_q3_pairs_are_subset(graphs):
    """(2) Die aus Q3 folgenden Paare sind in der Projektion enthalten."""
    union = build_graph.build_union(graphs)
    by_letter: dict[str, set[str]] = {}
    for entity, _, doc in union.query(sparql_body("q3_shared_persons")):
        by_letter.setdefault(str(doc).split("document/")[-1], set()).add(str(entity))
    subset = {}
    for letter, persons in by_letter.items():
        for first, second in combinations(sorted(persons), 2):
            subset.setdefault(frozenset((first, second)), set()).add(letter)
    graph, _ = network_module.build_mentions(graphs)
    got = {frozenset((first, second)): (data["weight"], set(data["letters"].split(";")))
           for first, second, data in graph.edges(data=True)}
    assert set(subset) <= set(got)
    for pair, letters in subset.items():
        assert got[pair] == (len(letters), letters)


def test_nodes_match_q1_persons(graphs):
    """(3) Knoten gleich den Q1-Personen (E21) des Vereinigungsgraphen."""
    union = build_graph.build_union(graphs)
    persons = {str(entity) for _doc, entity, _class, _label
               in union.query(sparql_body("q1_persons_places"))
               if str(_class).endswith("E21_Person")}
    graph, _ = network_module.build_mentions(graphs)
    assert set(graph.nodes) == persons


def test_outputs_deterministic(letters, graphs, tmp_path):
    """Zwei Läufe liefern byte-gleiche Dateien; GraphML lässt sich rücklesen."""
    first, second = tmp_path / "a", tmp_path / "b"
    built = None
    for out in (first, second):
        correspondence, corr_stats = network_module.build_correspondence(letters)
        mentions, mentions_stats = network_module.build_mentions(graphs)
        network_module.write_outputs(out, correspondence, corr_stats, mentions,
                                     mentions_stats, letters, graphs)
        built = correspondence
    names = ["correspondence.graphml", "correspondence_edges.csv",
             "mentions.graphml", "mentions_edges.csv", "metrics.json"]
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    reread = networkx.read_graphml(first / "correspondence.graphml")
    assert (reread.number_of_nodes(), reread.number_of_edges()) == (
        built.number_of_nodes(), built.number_of_edges())
    payload = json.loads((first / "metrics.json").read_text(encoding="utf-8"))
    assert payload["note"] == network_module.HONESTY
    assert set(payload["correspondence"]) >= {"nodes", "edges", "components",
                                              "top_degree", "top_betweenness"}
    assert len(payload["correspondence"]["top_degree"]) <= 10


def test_letter_without_received_is_counted(letters, tmp_path):
    """Brief ohne received entfällt aus den Kanten und steht in der Zählung."""
    target = tmp_path / "ohne.xml"
    root = etree.parse(str(letters[0])).getroot()
    root.set("{http://www.w3.org/XML/1998/namespace}id", "ohne")
    for action in root.xpath("//tei:correspDesc/tei:correspAction[@type='received']",
                             namespaces=NS):
        action.getparent().remove(action)
    etree.ElementTree(root).write(str(target), encoding="utf-8", xml_declaration=True)
    graph, stats = network_module.build_correspondence([letters[0], target])
    assert stats["without_received"] == ["ohne"]
    assert stats["without_sent"] == []
    assert graph.number_of_edges() == len(xpath_pairs([letters[0]]))


def test_example_letter_runs(letters, tmp_path):
    """Rauchtest: examples/letter.xml läuft ohne --graphs fehlerfrei."""
    del letters
    parser = argparse.ArgumentParser(prog="tei-crm network")
    out = tmp_path / "rauch"
    run_network(argparse.Namespace(inputs=[ROOT / "examples" / "letter.xml"],
                                   out_dir=out, graphs=None), parser)
    assert (out / "correspondence.graphml").is_file()
    assert (out / "metrics.json").is_file()
    assert not (out / "mentions.graphml").exists()


def test_cli_return_values(letters, tmp_path):
    """Exit 2 bei fehlender Datei und bei fehlendem Extra."""
    parser = argparse.ArgumentParser(prog="tei-crm network")
    with pytest.raises(SystemExit) as missing:
        run_network(argparse.Namespace(inputs=[tmp_path / "fehlt.xml"],
                                       out_dir=tmp_path / "x", graphs=None), parser)
    assert missing.value.code == 2


def test_cli_missing_extra(monkeypatch, letters, tmp_path):
    """Ohne installiertes Extra endet die CLI mit Exit 2 und Installationshinweis."""
    monkeypatch.setitem(sys.modules, "networkx", None)
    monkeypatch.delitem(sys.modules, "tei_crm_bridge.network")
    monkeypatch.delattr("tei_crm_bridge.network")
    parser = argparse.ArgumentParser(prog="tei-crm network")
    with pytest.raises(SystemExit) as absent:
        run_network(argparse.Namespace(inputs=[letters[0]], out_dir=tmp_path / "x",
                                       graphs=None), parser)
    assert absent.value.code == 2
