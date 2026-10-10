"""CLI-Fehler und SELECT-Metadaten an kleinen synthetischen Graphen."""

import argparse
import pytest

ox = pytest.importorskip("pyoxigraph")

from tei_crm_bridge import store
from tei_crm_bridge.cli import run_query, run_store


@pytest.mark.parametrize("binding", [{"s": "urn:probe:a"}, {"o": "alpha"}])
def test_unprojected_bindings_explain_engine_restriction(binding):
    graph = ox.Store()
    graph.load(input='<urn:probe:a> <urn:probe:p> "alpha" .', format=ox.RdfFormat.TURTLE)
    with pytest.raises(ValueError, match="SELECT.*--bind"):
        store.query(graph, "SELECT ?p WHERE { ?s ?p ?o }", binding)


def test_empty_csv_keeps_select_header(tmp_path, capsys):
    graph, query = tmp_path / "empty.ttl", tmp_path / "empty.rq"
    graph.write_text("")
    query.write_text("SELECT ?s ?o WHERE { ?s ?p ?o }")
    run_query(argparse.Namespace(query=query, graph=[graph], db=None, bind=[], format="csv"),
              argparse.ArgumentParser())
    assert capsys.readouterr().out.strip() == "s,o"


@pytest.mark.parametrize("command", ["query", "store"])
def test_turtle_parse_errors_use_cli_exit_one(tmp_path, capsys, command):
    graph, query = tmp_path / "bad.ttl", tmp_path / "ok.rq"
    graph.write_text("this is not Turtle")
    query.write_text("SELECT * WHERE { ?s ?p ?o }")
    with pytest.raises(SystemExit) as error:
        if command == "query":
            run_query(argparse.Namespace(query=query, graph=[graph], db=None, bind=[], format="csv"),
                      argparse.ArgumentParser())
        else:
            run_store(argparse.Namespace(inputs=[graph], db=tmp_path / "db"),
                      argparse.ArgumentParser())
    assert error.value.code == 1
    assert "bad.ttl" in capsys.readouterr().err
