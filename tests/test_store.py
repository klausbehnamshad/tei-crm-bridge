"""Store-Extra: pyoxigraph liefert dieselben Zeilen wie rdflib (R1).

Q1 und Q3 laufen auf dem Vereinigungsgraphen, Q2 läuft in rdflib je
Briefdatei (empfohlener Weg) und im Store auf der Vereinigung; verglichen
wird als Multimenge von String-Tupeln (Variablenreihenfolge = SELECT-Reihenfolge).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

pyoxigraph = pytest.importorskip("pyoxigraph")

from rdflib import Graph, Literal, URIRef

from tei_crm_bridge import store as store_module
from tei_crm_bridge.cli import main, run_query, run_store

ROOT = Path(__file__).resolve().parents[1]
SPARQL_DIR = ROOT / "eval" / "sparql"
sys.path.insert(0, str(SPARQL_DIR))
import build_graph  # noqa: E402


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    """Die 40 Briefgraphen frisch gebaut, Hash gegen das Manifest geprüft."""
    out = tmp_path_factory.mktemp("store")
    (out / "letters").mkdir()
    built = build_graph.build_letters(out)
    assert build_graph.files_hash(built) == build_graph.load_manifest()["graph_sha256"]
    return built


@pytest.fixture(scope="module")
def union(files):
    """rdflib-Vereinigungsgraph (nur für Abfragen, wie in build_graph)."""
    return build_graph.build_union(files)


@pytest.fixture(scope="module")
def memory_store(files):
    """Speicher-Store mit allen 40 Briefen (jede Datei einzeln geladen)."""
    return store_module.load(files, None)


def sparql(name: str) -> str:
    return (SPARQL_DIR / f"{name}.rq").read_text(encoding="utf-8")


def rdflib_query(graph: Graph, name: str, **bindings):
    """Eine .rq-Datei in rdflib ausführen (#-Kommentarzeilen gestrippt)."""
    text = sparql(name)
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return list(graph.query(body, initBindings=bindings))


def key_rdflib(row) -> tuple:
    """String-Tupel; ungebundene Variable (None, aus OPTIONAL) bleibt None."""
    return tuple(None if value is None else str(value) for value in row)


def key_store(row: dict) -> tuple:
    return tuple(None if value is None else store_module.term_string(value)
                 for value in row.values())


def letter_graphs(files):
    """Jede Briefdatei einzeln als rdflib-Graph (Q2-Weg je Briefdatei)."""
    graphs = []
    for target in files:
        single = Graph()
        single.parse(target, format="turtle")
        graphs.append(single)
    return graphs


def test_q1_matches_rdflib(memory_store, union):
    assert Counter(map(key_store, store_module.query(memory_store, sparql("q1_persons_places"), {}))) == \
        Counter(map(key_rdflib, rdflib_query(union, "q1_persons_places")))
    doc = "https://example.org/tei-crm-demo/document/L03501"
    assert Counter(map(key_store, store_module.query(memory_store, sparql("q1_persons_places"), {"doc": doc}))) == \
        Counter(map(key_rdflib, rdflib_query(union, "q1_persons_places", doc=URIRef(doc))))


def test_q2_unbound_matches_per_letter_rdflib(memory_store, files):
    rows = store_module.query(memory_store, sparql("q2_evidence"), {})
    assert rows, "Store-Q2 darf keine Zeilen verlieren"
    for row in rows:
        for value in row.values():
            assert not isinstance(value, pyoxigraph.BlankNode), row
    want = [row for single in letter_graphs(files) for row in rdflib_query(single, "q2_evidence")]
    assert Counter(map(key_store, rows)) == Counter(map(key_rdflib, want))


def test_q2_bound_entity_matches(memory_store, files):
    first = Graph()
    first.parse(files[0], format="turtle")
    entity = str(rdflib_query(first, "q2_evidence")[0][0])
    assert entity.startswith("http"), entity
    rows = store_module.query(memory_store, sparql("q2_evidence"), {"entity": entity})
    assert rows, "gebundene Entität muss Zeilen liefern"
    want = [row for single in letter_graphs(files)
            for row in rdflib_query(single, "q2_evidence", entity=URIRef(entity))]
    assert Counter(map(key_store, rows)) == Counter(map(key_rdflib, want))


def test_q3_matches_rdflib(memory_store, union):
    assert Counter(map(key_store, store_module.query(memory_store, sparql("q3_shared_persons"), {}))) == \
        Counter(map(key_rdflib, rdflib_query(union, "q3_shared_persons")))


def test_bind_literal(memory_store, union):
    """Literal-Bindung filtert (keine IRI, also kein NamedNode)."""
    label = str(rdflib_query(union, "q1_persons_places")[0][3])
    rows = store_module.query(memory_store, sparql("q1_persons_places"), {"label": label})
    assert rows
    assert {store_module.term_string(row["label"]) for row in rows} == {label}
    assert Counter(map(key_store, rows)) == Counter(map(
        key_rdflib, rdflib_query(union, "q1_persons_places", label=Literal(label))))


def test_persistent_store_reopen(files, tmp_path):
    """Anlegen, schließen, neu öffnen: Tripelzahl gleich, Abfrage gleich."""
    db = tmp_path / "db"
    store = store_module.load(files[:2], db)
    count = store_module.triple_count(store)
    assert count > 0
    rows = store_module.query(store, sparql("q1_persons_places"), {})
    del store
    reopened = store_module.load([], db)
    assert store_module.triple_count(reopened) == count
    assert Counter(map(key_store, store_module.query(reopened, sparql("q1_persons_places"), {}))) == \
        Counter(map(key_store, rows))


def test_cli_store_supplements(files, tmp_path, capsys):
    """tei-crm store legt an und ergänzt (vorher/nachher als JSON)."""
    parser = argparse.ArgumentParser()
    db = tmp_path / "db"
    run_store(argparse.Namespace(inputs=[files[0]], db=db), parser)
    first = json.loads(capsys.readouterr().out)
    assert (first["triples_before"], first["files"]) == (0, 1)
    run_store(argparse.Namespace(inputs=[files[1]], db=db), parser)
    second = json.loads(capsys.readouterr().out)
    assert second["triples_before"] == first["triples_after"]
    assert second["triples_after"] == store_module.triple_count(
        store_module.load(files[:2], None))


def test_cli_query_formats(files, union, capsys):
    """tei-crm query: table/csv/json liefern dieselben Zeilen wie rdflib."""
    want = Counter(map(key_rdflib, rdflib_query(union, "q3_shared_persons")))
    parser = argparse.ArgumentParser()
    query = SPARQL_DIR / "q3_shared_persons.rq"
    run_query(argparse.Namespace(query=query, db=None, graph=files, bind=[], format="table"), parser)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) - 2 == len(want)
    run_query(argparse.Namespace(query=query, db=None, graph=files, bind=[], format="csv"), parser)
    csv_lines = capsys.readouterr().out.splitlines()
    assert csv_lines[0] == "entity,label,doc" and len(csv_lines) - 1 == len(want)
    run_query(argparse.Namespace(query=query, db=None, graph=files, bind=[], format="json"), parser)
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == len(want) and set(payload[0]) == {"entity", "label", "doc"}


def test_cli_query_bind_iri(files, capsys):
    """--bind mit IRI bindet die Entität (Q2, eine gebundene Entität)."""
    first = Graph()
    first.parse(files[0], format="turtle")
    entity = str(rdflib_query(first, "q2_evidence")[0][0])
    parser = argparse.ArgumentParser()
    run_query(argparse.Namespace(query=SPARQL_DIR / "q2_evidence.rq", db=None, graph=files,
                                 bind=[f"entity={entity}"], format="csv"), parser)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) - 1 >= 1
    assert {line.split(",")[0] for line in lines[1:]} == {entity}


def test_cli_return_values(files, tmp_path):
    """Exit 2 bei fehlender Datei/fehlendem Paket, Exit 1 bei Abfragefehler."""
    parser = argparse.ArgumentParser()
    with pytest.raises(SystemExit) as missing:
        run_query(argparse.Namespace(query=tmp_path / "fehlt.rq", db=None, graph=files,
                                     bind=[], format="table"), parser)
    assert missing.value.code == 2
    bad = tmp_path / "kaputt.rq"
    bad.write_text("SELECT ??? kein SPARQL", encoding="utf-8")
    with pytest.raises(SystemExit) as broken:
        run_query(argparse.Namespace(query=bad, db=None, graph=[files[0]],
                                     bind=[], format="table"), parser)
    assert broken.value.code == 1


def test_cli_query_needs_positional_query(files):
    """Ohne Positionsargument gibt es keine stille Deutung (Exit 2)."""
    parser = argparse.ArgumentParser(prog="tei-crm query")
    with pytest.raises(SystemExit) as missing:
        run_query(argparse.Namespace(query=None, db=None, graph=files,
                                     bind=[], format="table"), parser)
    assert missing.value.code == 2


def test_cli_query_rejects_graph_first_order(monkeypatch, files):
    """`query --graph ... QUERY` scheitert laut, statt falsch zu laden (Exit 2)."""
    monkeypatch.setattr(sys, "argv", ["tei-crm", "query", "--graph", str(files[0]),
                                      str(SPARQL_DIR / "q3_shared_persons.rq")])
    with pytest.raises(SystemExit) as rejected:
        main()
    assert rejected.value.code == 2


def test_cli_missing_extra(monkeypatch, files, tmp_path, capsys):
    """Ohne installiertes Extra endet die CLI mit Exit 2 und Installationshinweis."""
    monkeypatch.setitem(sys.modules, "pyoxigraph", None)
    monkeypatch.delitem(sys.modules, "tei_crm_bridge.store")
    monkeypatch.delattr("tei_crm_bridge.store")
    parser = argparse.ArgumentParser(prog="tei-crm store")
    with pytest.raises(SystemExit) as absent:
        run_store(argparse.Namespace(inputs=[files[0]], db=tmp_path / "db"), parser)
    assert absent.value.code == 2
    assert "tei-crm-bridge[store]" in capsys.readouterr().err
