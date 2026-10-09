"""SHACL-Validierung (Extra ``validate``) gegen das TCB-Profil.

Der Import von pyshacl steht absichtlich nur hier: Ohne das Extra
schlägt ``import tei_crm_bridge.validate`` mit ImportError fehl, und die
CLI meldet ``pip install 'tei-crm-bridge[validate]'`` (Exit 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph, RDF, URIRef
from rdflib.namespace import SH

PROFILE_MARKER = "https://klausbehnamshad.github.io/tei-crm-bridge/shapes#forProfile"
PROFILE_BASE = "https://klausbehnamshad.github.io/tei-crm-bridge/shapes#"


@dataclass
class Violation:
    """Ein Verstoß: Fokusknoten, verletzte Shape und Meldung."""

    focus: str
    shape: str
    message: str


@dataclass
class Report:
    """Ergebnis: formkonform ja/nein plus Verstoßliste."""

    conforms: bool
    violations: list[Violation] = field(default_factory=list)


def shapes_path() -> Path:
    """Paketdatei der Shapes (über Package Data ausgeliefert)."""
    return resources.files("tei_crm_bridge") / "shapes" / "tcb-shapes.ttl"


def profile_shapes(profile: Literal["source", "reviewed"]) -> Graph:
    """Shapes-Graph für ein Profil: die fremde forProfile-Gruppe entfällt.

    Entfernte Shapes nehmen ihre Blank-Node-Hülle mit (jede Shape nutzt
    eigene anonyme Knoten); benannte Shapes ohne Marker gelten für beide.
    """
    shapes = Graph().parse(shapes_path(), format="turtle")
    other = "reviewed" if profile == "source" else "source"
    drop = list(shapes.subjects(URIRef(PROFILE_MARKER), URIRef(PROFILE_BASE + other)))
    remove: set = set()
    stack = list(drop)
    while stack:
        node = stack.pop()
        if node in remove:
            continue
        remove.add(node)
        for obj in shapes.objects(node, None):
            if isinstance(obj, BNode):
                stack.append(obj)
    for node in remove:
        for triple in list(shapes.triples((node, None, None))):
            shapes.remove(triple)
    return shapes


def _named_shape(shapes: Graph, shape) -> str:
    """Nächste benannte Shape über einer anonymen (Deterministisch, aufsteigend)."""
    seen = set()
    while isinstance(shape, BNode) and shape not in seen:
        seen.add(shape)
        parents = sorted({str(s) for s, _, _ in shapes.triples((None, None, shape))} -
                         {str(shape)})
        if not parents:
            break
        shape = URIRef(next(iter(parents)))
    return str(shape)


def validate(graph: Path, profile: Literal["source", "reviewed"] = "source") -> Report:
    """Prüft ``graph`` gegen das Profil; SHACL-Konformität heißt formkonform."""
    data = Graph().parse(graph, format="turtle")
    shapes = profile_shapes(profile)
    conforms, results, _ = shacl_validate(data, shacl_graph=shapes)
    violations = []
    for report in results.subjects(RDF.type, SH.ValidationReport):
        for result in results.objects(report, SH.result):
            focus = results.value(result, SH.focusNode)
            shape = results.value(result, SH.sourceShape)
            messages = sorted({str(text) for text in results.objects(result, SH.resultMessage)})
            violations.append(Violation(focus=str(focus), shape=_named_shape(shapes, shape),
                                        message=" / ".join(messages)))
    violations.sort(key=lambda item: (item.shape, item.focus, item.message))
    return Report(conforms=bool(conforms), violations=violations)
