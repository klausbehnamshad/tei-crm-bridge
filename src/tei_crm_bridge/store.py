"""Optionaler Triplestore (Extra ``store``) auf pyoxigraph-Basis.

Der Import von pyoxigraph steht absichtlich nur hier: Ohne das Extra
schlägt ``import tei_crm_bridge.store`` mit ImportError fehl, und die
CLI meldet ``pip install 'tei-crm-bridge[store]'`` (Exit 2).
"""

from __future__ import annotations

from pathlib import Path

from pyoxigraph import Literal, NamedNode, RdfFormat, Store, Variable

from .rdf import valid_iri


def load(paths: list[Path], db: Path | None) -> Store:
    """Lädt Turtle-Dateien in einen Store (persistent unter ``db`` oder Speicher).

    Jede Datei wird einzeln über ``bulk_load`` geladen, damit Blank Nodes
    getrennt bleiben (wie ``build_union`` in ``eval/sparql/build_graph.py``).
    """
    store = Store(str(db)) if db is not None else Store()
    for path in paths:
        store.bulk_load(path=str(path), format=RdfFormat.TURTLE)
    return store


def triple_count(store: Store) -> int:
    """Zahl der Tripel im Store (für die vorher/nachher-Ausgabe der CLI)."""
    return sum(1 for _ in store.quads_for_pattern(None, None, None, None))


def query(store: Store, text: str, bindings: dict[str, str]) -> list[dict]:
    """Führt SELECT ``text`` mit ``bindings`` aus (über ``substitutions``).

    Bindungswerte, die als IRI gültig sind (``rdf.valid_iri``), werden
    ``NamedNode``, sonst ``Literal``. Ergebnis: Liste von Dicts mit
    Variablennamen (ohne ``?``) als Schlüsseln, in SELECT-Reihenfolge.
    """
    substitutions = {
        Variable(name): NamedNode(value) if valid_iri(value) else Literal(value)
        for name, value in bindings.items()
    }
    results = store.query(text, substitutions=substitutions)
    names = [variable.value for variable in results.variables]
    rows = []
    for solution in results:
        rows.append({name: solution[variable] for name, variable in zip(names, results.variables)})
    return rows


def term_string(term):
    """Vergleichsform eines Terms: URI bzw. lexikalischer Wert, None bleibt None.

    None steht für eine ungebundene Variable (OPTIONAL); die CLI zeigt
    dafür eine leere Zelle, Vergleiche behandeln es als eigenen Wert.
    """
    return None if term is None else term.value
