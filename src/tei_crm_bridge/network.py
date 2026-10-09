"""Korrespondenz- und Nennungsnetz (Extra ``network``) aus Edition und Graphen.

Der Import von networkx steht absichtlich nur hier: Ohne das Extra
schlägt ``import tei_crm_bridge.network`` mit ImportError fehl, und die
CLI meldet ``pip install 'tei-crm-bridge[network]'`` (Exit 2).

Wiederverwendet werden :func:`cmif.authority_uri` (GND aus dem Register),
:mod:`dates` (Briefdaten) und :class:`rdf.GraphBuilder` (``@ref``-Auflösung
wie im Graphen); keine private Funktion musste sichtbar gemacht werden.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from itertools import combinations
from pathlib import Path

import networkx as nx
from lxml import etree
from rdflib import RDF, RDFS, Graph as RdfGraph, URIRef

from . import __version__
from .cmif import authority_uri
from .dates import intersect, interval
from .projection import TEI, local_name
from .rdf import GraphBuilder

#: Auflösungskontext für @ref (erscheint nie in der Ausgabe, wie in cmif).
BASE_URI = "https://example.org/tei-crm-bridge/network/"

#: Personen-Namensraum der Edition (Filter wie Q3 in eval/sparql/q3_shared_persons.rq).
PMB_EDITIONS = "https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions"
PMB_PERSON = re.compile(re.escape(PMB_EDITIONS) + r"#pmb[0-9]+$")

#: Ehrlichkeitshinweis für jede Kennzahlen-Ausgabe.
HONESTY = "Kennzahlen beschreiben die Auszeichnung der Edition im gegebenen Korpus."

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _label(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _action_interval(action: etree._Element):
    """Geschnittenes Datumsintervall einer Handlung; None ohne/bei lesbaren Daten."""
    found = []
    for child in action:
        if isinstance(child.tag, str) and local_name(child) == "date":
            try:
                span = interval(child)
            except ValueError:
                continue
            if span is not None:
                found.append(span)
    if not found:
        return None
    try:
        return intersect(found)
    except ValueError:
        return None


def _letter_persons(builder: GraphBuilder, action: etree._Element) -> tuple[list[dict], list[dict]]:
    """Personen einer Handlung: je @ref-Token eine mit Register-URI, Label, GND."""
    persons, unresolved = [], []
    for child in action:
        if not (isinstance(child.tag, str) and local_name(child) == "persName"):
            continue
        label, gnd = _label(child), authority_uri(builder, child, None)
        for token in (child.get("ref") or "").split():
            resolved = builder.resolve(token, child)
            if resolved is None:
                unresolved.append(token)
                continue
            persons.append({"uri": resolved[0], "label": label, "gnd": gnd})
    return persons, unresolved


def build_correspondence(paths: list[Path]) -> tuple[nx.DiGraph, dict]:
    """Korrespondenznetz: Absender → Empfänger je Brief, Mehrfachkanten vereint.

    Knoten nach Register-URI (PMB-``xml:id``, aufgelöst wie in ``rdf.py``),
    dazu Label und GND (wenn im Register vorhanden). Kanten je Brief mit
    Brief-ID und Daten; vereinte Kanten tragen ``weight`` und parallele,
    ``;``-getrennte Listen (Briefe, Anfänge, Enden). Briefe ohne ``sent``
    oder ohne ``received`` entfallen und werden gezählt, nicht erfunden.
    """
    per_edge: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
    people: dict[str, dict] = {}
    without_sent, without_received, unresolved = [], [], []
    for path in sorted(paths, key=lambda item: item.stem):
        root = etree.parse(str(path)).getroot()
        doc_id = root.get(XML_ID) or path.stem
        builder = GraphBuilder(root, doc_id, BASE_URI, [])
        sent, received = [], []
        sent_dates = received_dates = None
        for desc in root.iter(TEI + "correspDesc"):
            for action in desc.findall(TEI + "correspAction"):
                kind = action.get("type")
                if kind not in ("sent", "received"):
                    continue
                persons, missed = _letter_persons(builder, action)
                unresolved.extend({"letter": doc_id, "token": token} for token in missed)
                if kind == "sent":
                    sent.extend(persons)
                    if sent_dates is None:
                        sent_dates = _action_interval(action)
                else:
                    received.extend(persons)
                    if received_dates is None:
                        received_dates = _action_interval(action)
        if not sent:
            without_sent.append(doc_id)
        if not received:
            without_received.append(doc_id)
        span = sent_dates or received_dates
        begin, end = (span.begin or "", span.end or "") if span else ("", "")
        for first in sent:
            people.setdefault(first["uri"], {"label": first["label"], "gnd": first["gnd"]})
            for second in received:
                people.setdefault(second["uri"], {"label": second["label"], "gnd": second["gnd"]})
                per_edge.setdefault((first["uri"], second["uri"]), {})[doc_id] = (begin, end)
    graph = nx.DiGraph()
    for uri in sorted(people):
        attrs = {"label": people[uri]["label"]}
        if people[uri]["gnd"] is not None:
            attrs["gnd"] = people[uri]["gnd"]
        graph.add_node(uri, **attrs)
    for (first, second) in sorted(per_edge):
        letters = per_edge[(first, second)]
        order = sorted(letters)
        graph.add_edge(first, second, weight=len(order), letters=";".join(order),
                       date_begin=";".join(letters[item][0] for item in order),
                       date_end=";".join(letters[item][1] for item in order))
    stats = {"letters": len(paths), "without_sent": sorted(without_sent),
             "without_received": sorted(without_received), "unresolved_refs": unresolved}
    return graph, stats


def _mention_persons(graph) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Brief-IDs je PMB-Person und Label: P67 auf E21 mit PMB-URI außerhalb der Doku (wie Q3)."""
    crm = "http://www.cidoc-crm.org/cidoc-crm/"
    documents = {str(node) for node in graph.subjects(RDF.type, URIRef(crm + "E31_Document"))}
    persons: dict[str, set[str]] = {}
    labels: dict[str, str] = {}
    for doc in sorted(documents):
        letter = doc.split("document/")[-1] if "document/" in doc else doc
        for entity in graph.objects(URIRef(doc), URIRef(crm + "P67_refers_to")):
            uri = str(entity)
            if not PMB_PERSON.match(uri):
                continue
            if (entity, RDF.type, URIRef(crm + "E21_Person")) not in graph:
                continue
            if any(uri.startswith(prefix) for prefix in documents):
                continue
            persons.setdefault(uri, set()).add(letter)
            if uri not in labels:
                labels[uri] = str(graph.value(entity, RDFS.label) or uri)
    return persons, labels


def build_mentions(graph_files: list[Path]) -> tuple[nx.Graph, dict]:
    """Nennungsnetz: Person–Person-Projektion gemeinsamer Briefe (ungerichtet).

    Kanten-``weight`` ist die Zahl gemeinsamer Briefe über alle Briefe,
    ``letters`` ihre ``;``-getrennte Liste. Knoten sind alle P67-Personen
    mit PMB-URI (Q1-Menge: E21, PMB-URI, außerhalb der Dokument-URI);
    Labels aus ``rdfs:label``.
    """
    persons: dict[str, set[str]] = {}
    labels: dict[str, str] = {}
    for path in sorted(graph_files):
        file_persons, file_labels = _mention_persons(RdfGraph().parse(path, format="turtle"))
        for uri, letters in file_persons.items():
            persons.setdefault(uri, set()).update(letters)
            labels.setdefault(uri, file_labels[uri])
    per_pair: dict[frozenset, set[str]] = {}
    by_letter: dict[str, set[str]] = {}
    for uri, letters in persons.items():
        for letter in letters:
            by_letter.setdefault(letter, set()).add(uri)
    for letter in sorted(by_letter):
        for first, second in combinations(sorted(by_letter[letter]), 2):
            per_pair.setdefault(frozenset((first, second)), set()).add(letter)
    graph = nx.Graph()
    for uri in sorted(persons):
        graph.add_node(uri, label=labels[uri])
    for pair in sorted(per_pair, key=lambda item: sorted(item)):
        first, second = sorted(pair)
        order = sorted(per_pair[pair])
        graph.add_edge(first, second, weight=len(order), letters=";".join(order))
    stats = {"graphs": len(graph_files), "persons": len(persons), "pairs": len(per_pair)}
    return graph, stats


def _top(items: list[tuple[str, float]], labels: dict[str, str], count: int = 10) -> list[dict]:
    ordered = sorted(items, key=lambda item: (-item[1], item[0]))[:count]
    return [{"uri": uri, "label": labels.get(uri, uri), "value": value} for uri, value in ordered]


def graph_metrics(graph, labels: dict[str, str], directed: bool) -> dict:
    """Knoten, Kanten, Komponenten, je zehn höchste Grade und Betweenness."""
    components = (nx.number_weakly_connected_components(graph) if directed
                  else nx.number_connected_components(graph))
    betweenness = nx.betweenness_centrality(graph)
    return {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "components": components,
            "top_degree": _top([(node, graph.degree(node)) for node in graph], labels),
            "top_betweenness": _top(list(betweenness.items()), labels)}


def metrics(letter_files: list[Path], graph_files: list[Path] | None,
            correspondence: dict, mentions: dict | None) -> dict:
    """Kennzahlen-JSON: Methode, Version, Korpus (Dateien + SHA-256), Datum, Hinweis."""
    def finger(paths):
        names, digests = [], []
        for path in sorted(paths):
            names.append(path.name)
            digests.append(hashlib.sha256(path.read_bytes()).hexdigest())
        return names, digests

    letter_names, letter_digests = finger(letter_files)
    body = {"method": ("Korrespondenz aus correspAction sent/received persName/@ref "
                       "(GraphBuilder.resolve, GND aus cmif.authority_uri, Daten aus dates); "
                       "Nennungen aus P67 auf E21 mit PMB-URI außerhalb der Dokument-URI (wie Q3), "
                       "Projektion Person-Person mit weight = Zahl gemeinsamer Briefe; "
                       "Grade und Betweenness aus networkx (normalisiert)."),
            "software_version": __version__,
            "corpus": {"letters": letter_names, "letter_sha256": letter_digests},
            "date": date.today().isoformat(), "note": HONESTY,
            "correspondence": correspondence, "mentions": mentions}
    if graph_files is not None:
        graph_names, graph_digests = finger(graph_files)
        body["corpus"]["graphs"] = graph_names
        body["corpus"]["graph_sha256"] = graph_digests
    return body


def write_outputs(out_dir: Path, correspondence: nx.DiGraph, corr_stats: dict,
                  mentions: nx.Graph | None = None, mentions_stats: dict | None = None,
                  letter_files: list[Path] | None = None,
                  graph_files: list[Path] | None = None) -> dict:
    """Schreibt GraphML, Kanten-CSV und metrics.json (deterministisch sortiert)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(correspondence, out_dir / "correspondence.graphml")
    with (out_dir / "correspondence_edges.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "target", "weight", "letters", "date_begin", "date_end"])
        for first, second, data in sorted(correspondence.edges(data=True)):
            writer.writerow([first, second, data["weight"], data["letters"],
                             data["date_begin"], data["date_end"]])
    corr_labels = {node: data.get("label", node) for node, data in correspondence.nodes(data=True)}
    corr_metrics = graph_metrics(correspondence, corr_labels, directed=True)
    corr_metrics.update(corr_stats)
    mentions_metrics = None
    if mentions is not None:
        nx.write_graphml(mentions, out_dir / "mentions.graphml")
        with (out_dir / "mentions_edges.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "target", "weight", "letters"])
            for first, second, data in sorted(mentions.edges(data=True)):
                writer.writerow([first, second, data["weight"], data["letters"]])
        mention_labels = {node: data.get("label", node) for node, data in mentions.nodes(data=True)}
        mentions_metrics = graph_metrics(mentions, mention_labels, directed=False)
        mentions_metrics.update(mentions_stats or {})
    body = metrics(letter_files or [], graph_files, corr_metrics, mentions_metrics)
    (out_dir / "metrics.json").write_text(json.dumps(body, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return body

