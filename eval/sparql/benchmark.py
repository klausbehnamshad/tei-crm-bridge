"""Vergleich von rdflib und pyoxigraph am hashgeprüften 40-Brief-Graphen.

python eval/sparql/benchmark.py --graph-dir eval/work/sparql --out RESULT.json

Kein Modelllauf. Alle Zeitwerte enthalten Ergebnis-Materialisierung; Parsen,
Store-Laden und Zählen stehen separat. Q2 unter rdflib läuft nur je Brief.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rdflib import Graph, URIRef  # noqa: E402
from tei_crm_bridge import store  # noqa: E402
from build_graph import (check_inputs, check_provenance, corpus_letters,  # noqa: E402
                         files_hash, load_manifest)

QUERY_FILES = {"Q1": "q1_persons_places.rq", "Q2": "q2_evidence.rq",
               "Q3": "q3_shared_persons.rq"}
KAINZ = "https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb11851"


def timed(function):
    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def multiset(rows, oxigraph=False):
    return Counter(tuple(store.term_string(value) if oxigraph else
                         None if value is None else str(value)
                         for value in (row.values() if oxigraph else row)) for row in rows)


def result_hash(values):
    encoded = sorted((json.dumps(key, ensure_ascii=False), count)
                     for key, count in values.items())
    return hashlib.sha256(json.dumps(encoded, ensure_ascii=False).encode()).hexdigest()


def source_hashes():
    paths = list((ROOT / "src" / "tei_crm_bridge").glob("*.py"))
    paths.extend(ROOT / "eval" / "sparql" / name for name in QUERY_FILES.values())
    paths.extend([Path(__file__), ROOT / "eval" / "sparql" / "build_graph.py",
                  ROOT / "eval" / "sparql" / "manifest.json", ROOT / "eval" / "manifest.tsv",
                  ROOT / "pyproject.toml"])
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--base-commit", help="Bezugscommit; kein Nachweis eines unveränderten Baums")
    args = parser.parse_args()
    manifest = load_manifest()
    letters = corpus_letters()
    check_provenance(manifest, check_inputs(letters))
    files = sorted((args.graph_dir / "letters").glob("*.ttl"))
    if [path.stem for path in files] != [path.stem for path in letters]:
        raise SystemExit("Briefgraphen stimmen nicht mit den 40 Korpus-IDs überein.")
    digest = files_hash(files)
    if digest != manifest["graph_sha256"]:
        raise SystemExit("Graph-Hash weicht vom Manifest ab.")
    queries = {key: (ROOT / "eval" / "sparql" / name).read_text(encoding="utf-8")
               for key, name in QUERY_FILES.items()}

    def parse_files():
        return [Graph().parse(path, format="turtle") for path in files]

    def parse_union():
        graph = Graph()
        for path in files:
            graph.parse(path, format="turtle")
        return graph

    singles, singles_seconds = timed(parse_files)
    union, union_seconds = timed(parse_union)
    loads = []
    counts = []
    for _ in range(args.repeats):
        database, seconds = timed(lambda: store.load(files, None))
        loads.append(seconds)
        count, seconds = timed(lambda: store.triple_count(database))
        counts.append(seconds)
        if count != len(union):
            raise SystemExit("Tripelzahlen der Engines unterscheiden sich.")
    runs = []
    comparisons = {}
    for query_name, binding in (("Q1", {}), ("Q2", {}), ("Q3", {}), ("Q2", {"entity": KAINZ})):
        key = query_name + ("_Kainz" if binding else "")
        reference = None
        for engine in ("rdflib", "pyoxigraph"):
            samples = []
            for _ in range(args.repeats):
                if engine == "pyoxigraph":
                    rows, seconds = timed(lambda: store.query(database, queries[query_name], binding))
                else:
                    init = {name: URIRef(value) for name, value in binding.items()}
                    graphs = singles if query_name == "Q2" else [union]
                    rows, seconds = timed(lambda: [row for graph in graphs for row in
                                                   graph.query(queries[query_name], initBindings=init)])
                values = multiset(rows, oxigraph=engine == "pyoxigraph")
                if reference is None:
                    reference = values
                if values != reference:
                    raise SystemExit(f"{key}: Ergebnisse zwischen Läufen oder Engines verschieden.")
                samples.append(seconds)
            runs.append({"engine": engine, "query": key, "binding": binding,
                         "scope": "per_letter" if engine == "rdflib" and query_name == "Q2" else "union",
                         "rows": len(rows), "result_multiset_sha256": result_hash(values),
                         "seconds": samples, "median_seconds": statistics.median(samples),
                         "min_seconds": min(samples), "max_seconds": max(samples)})
        comparisons[key] = True
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "command": "python " + " ".join(sys.argv),
              "python": platform.python_version(), "platform": platform.platform(),
              "machine": platform.machine(), "processor": platform.processor(),
              "versions": {name: importlib.metadata.version(name)
                           for name in ("rdflib", "pyoxigraph")},
              "base_commit": args.base_commit,
              "source_state": "Quellbaum über source_sha256 identifiziert; base_commit ist nur Bezug.",
              "source_sha256": source_hashes(), "graph_sha256": digest,
              "corpus_commit": manifest["corpus_commit"], "letters": len(files), "triples": count,
              "method": ("perf_counter, ohne Warmup; alle Wiederholungen gespeichert; "
                         "Queryzeit einschließlich Materialisierung, ohne Laden/Parsen/Zählen; "
                         "Q2 rdflib je Brief, pyoxigraph Union; Speicher-Store; "
                         "lexikalische Ergebnis-Multimengen jeder Wiederholung verglichen."),
              "parse_seconds": {"rdflib_union": union_seconds, "rdflib_per_letter": singles_seconds},
              "pyoxigraph_load_seconds": loads, "pyoxigraph_count_seconds": counts,
              "engines_equal": comparisons, "runs": runs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(args.out), "triples": count, "engines_equal": comparisons}))


if __name__ == "__main__":
    main()
