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

CRM = "http://www.cidoc-crm.org/cidoc-crm/"
ENTITY_CLASSES = {CRM + name for name in ("E21_Person", "E53_Place", "E74_Group")}

#: Ehrlichkeitshinweis für jede Kennzahlen-Ausgabe.
HONESTY = "Kennzahlen beschreiben die Auszeichnung der Edition im gegebenen Korpus."

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _label(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _action_interval(action: etree._Element):
    """Schnitt aller lesbaren Daten; ungültige Werte und Widersprüche sind Fehler."""
    found = []
    for child in action:
        if isinstance(child.tag, str) and local_name(child) == "date":
            span = interval(child)
            if span is not None:
                found.append(span)
    if not found:
        return None
    return intersect(found)


def _token_authority(builder: GraphBuilder, child: etree._Element, token: str):
    """CMIF-Auflösung für genau einen Token im unveränderten XML-Basiskontext."""
    original = child.get("ref")
    child.set("ref", token)
    try:
        return authority_uri(builder, child, None)
    finally:
        child.set("ref", original)


def _letter_persons(builder: GraphBuilder, action: etree._Element) -> tuple[list[dict], list[dict]]:
    """Personen einer Handlung: je @ref-Token eine mit Register-URI, Label, GND."""
    persons, unresolved = [], []
    for child in action:
        if not (isinstance(child.tag, str) and local_name(child) == "persName"):
            continue
        label = _label(child)
        for token in (child.get("ref") or "").split():
            resolved = builder.resolve(token, child)
            if resolved is None:
                unresolved.append(token)
                continue
            persons.append({"uri": resolved[0], "label": label,
                            "gnd": _token_authority(builder, child, token)})
    return persons, unresolved


def build_correspondence(paths: list[Path]) -> tuple[nx.DiGraph, dict]:
    """Korrespondenznetz: Absender → Empfänger je Brief, Mehrfachkanten vereint.

    Knoten nach Register-URI (PMB-``xml:id``, aufgelöst wie in ``rdf.py``),
    dazu Label und GND (wenn im Register vorhanden). Kanten je Brief mit
    Brief-ID und Daten; vereinte Kanten tragen ``weight`` und parallele,
    ``;``-getrennte Listen (Briefe, Anfänge, Enden). Briefe ohne ``sent``
    oder ohne ``received`` entfallen und werden gezählt, nicht erfunden.
    """
    per_edge: dict[tuple[str, str], dict[str, tuple[str, str, str]]] = {}
    people: dict[str, dict] = {}
    without_sent, without_received, unresolved, date_fallbacks, date_errors = [], [], [], [], []
    for path in sorted(paths):
        root = etree.parse(str(path)).getroot()
        doc_id = root.get(XML_ID) or path.stem
        builder = GraphBuilder(root, doc_id, BASE_URI, [])
        sent, received = [], []
        dates = {"sent": [], "received": []}
        invalid_dates = set()

        def report_date_error(kind, error):
            invalid_dates.add(kind)
            date_errors.append({"file": str(path), "letter": doc_id,
                                "action": kind, "message": str(error)})

        for desc in root.iter(TEI + "correspDesc"):
            for action in desc.findall(TEI + "correspAction"):
                kind = action.get("type")
                if kind not in ("sent", "received"):
                    continue
                persons, missed = _letter_persons(builder, action)
                unresolved.extend({"letter": doc_id, "token": token} for token in missed)
                try:
                    span = _action_interval(action)
                except ValueError as error:
                    report_date_error(kind, error)
                    span = None
                if span is not None:
                    dates[kind].append(span)
                if kind == "sent":
                    sent.extend(persons)
                else:
                    received.extend(persons)
        spans = {}
        for kind, values in dates.items():
            try:
                spans[kind] = intersect(values) if values and kind not in invalid_dates else None
            except ValueError as error:
                report_date_error(kind, error)
                spans[kind] = None
        if not sent:
            without_sent.append(doc_id)
        if not received:
            without_received.append(doc_id)
        span = None if invalid_dates else spans["sent"] or spans["received"]
        date_source = ("none" if invalid_dates else "sent" if spans["sent"] else
                       "received" if spans["received"] else "none")
        if date_source == "received":
            date_fallbacks.append(doc_id)
        begin, end = (span.begin or "", span.end or "") if span else ("", "")
        for first in sent:
            people.setdefault(first["uri"], {"label": first["label"], "gnd": first["gnd"]})
            for second in received:
                people.setdefault(second["uri"], {"label": second["label"], "gnd": second["gnd"]})
                per_edge.setdefault((first["uri"], second["uri"]), {})[doc_id] = (begin, end, date_source)
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
                       date_end=";".join(letters[item][1] for item in order),
                       date_source=";".join(letters[item][2] for item in order))
    stats = {"letters": len(paths), "without_sent": sorted(without_sent),
             "without_received": sorted(without_received), "unresolved_refs": unresolved,
             "date_fallbacks": sorted(date_fallbacks), "date_errors": date_errors}
    return graph, stats


def _rdf_label(graph, node) -> str:
    """Lexikalisch erstes Label; RDF-Iterationsreihenfolge bestimmt keine Ausgabe."""
    return min((str(value) for value in graph.objects(node, RDFS.label)), default=str(node))


def build_bipartite_mentions(graph_files: list[Path]) -> tuple[nx.DiGraph, dict]:
    """Gerichtet Brief-URI → externe E21/E53/E74-URI; Dokumentidentität bleibt vollständig."""
    data = RdfGraph()
    for path in sorted(graph_files):
        data.parse(path, format="turtle")
    documents = sorted(str(node) for node in data.subjects(RDF.type, URIRef(CRM + "E31_Document"))
                       if isinstance(node, URIRef))
    document_uris = set(documents)
    prefix_lengths = sorted({len(uri) for uri in document_uris})
    entities, pairs = {}, set()
    for doc in documents:
        for entity in data.objects(URIRef(doc), URIRef(CRM + "P67_refers_to")):
            if not isinstance(entity, URIRef):
                continue
            uri = str(entity)
            if any(uri[:length] in document_uris for length in prefix_lengths if length <= len(uri)):
                continue
            classes = {str(value) for value in data.objects(entity, RDF.type)} & ENTITY_CLASSES
            if classes:
                entities[str(entity)] = {"label": _rdf_label(data, entity), "kind": "entity",
                                         "bipartite": 1, "crm_classes": ";".join(sorted(classes))}
                pairs.add((doc, str(entity)))
    graph = nx.DiGraph()
    for doc in documents:
        graph.add_node(doc, label=_rdf_label(data, URIRef(doc)), kind="document", bipartite=0)
    for uri in sorted(entities):
        graph.add_node(uri, **entities[uri])
    graph.add_edges_from(sorted(pairs))
    return graph, {"graphs": len(graph_files), "documents": len(documents), "entities": len(entities)}


def build_mentions(graph_files: list[Path], *, bipartite=None) -> tuple[nx.Graph, dict]:
    """Personprojektion: weight zählt vollständige Brief-URIs; alle externen E21 zählen.

    ``letters`` zeigt kurze Brief-IDs; ``letter_uris`` hält die parallelen
    vollständigen Identitäten. Verschiedene Editionen dürfen gleiche IDs haben.
    """
    if bipartite is None:
        bipartite, _ = build_bipartite_mentions(graph_files)
    person_set = {node for node, attrs in bipartite.nodes(data=True)
                  if CRM + "E21_Person" in attrs.get("crm_classes", "").split(";")}
    persons = sorted(person_set)
    per_pair: dict[tuple[str, str], set[str]] = {}
    for doc, attrs in sorted(bipartite.nodes(data=True)):
        if attrs["kind"] == "document":
            mentioned = sorted(node for node in bipartite.successors(doc) if node in person_set)
            for pair in combinations(mentioned, 2):
                per_pair.setdefault(pair, set()).add(doc)
    graph = nx.Graph()
    for uri in persons:
        graph.add_node(uri, label=bipartite.nodes[uri]["label"])
    for (first, second) in sorted(per_pair):
        pair = (first, second)
        order = sorted(per_pair[pair])
        graph.add_edge(first, second, weight=len(order),
                       letters=";".join(doc.rsplit("document/", 1)[-1] for doc in order),
                       letter_uris=";".join(order))
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
            correspondence: dict, mentions: dict | None, mentions_bipartite: dict | None = None) -> dict:
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
                       "bipartite Nennungen Brief-URI zu E21/E53/E74 außerhalb der Dokument-URI; "
                       "Projektion E21-Person-Person mit weight = Zahl gemeinsamer Brief-URIs; "
                       "ungewichteter Gesamtgrad (gerichtet: Eingang plus Ausgang), "
                       "normalisierte ungewichtete Betweenness aus networkx; "
                       "Komponenten schwach bei gerichteten, zusammenhängend bei ungerichteten Graphen."),
            "software_version": __version__,
            "networkx_version": nx.__version__,
            "corpus": {"letters": letter_names, "letter_sha256": letter_digests},
            "date": date.today().isoformat(), "note": HONESTY,
            "correspondence": correspondence, "mentions": mentions,
            "mentions_bipartite": mentions_bipartite}
    if graph_files is not None:
        graph_names, graph_digests = finger(graph_files)
        body["corpus"]["graphs"] = graph_names
        body["corpus"]["graph_sha256"] = graph_digests
    return body


def write_outputs(out_dir: Path, correspondence: nx.DiGraph, corr_stats: dict,
                  mentions: nx.Graph | None = None, mentions_stats: dict | None = None,
                  letter_files: list[Path] | None = None,
                  graph_files: list[Path] | None = None, *,
                  bipartite: nx.DiGraph | None = None, bipartite_stats: dict | None = None) -> dict:
    """Schreibt GraphML, Kanten-CSV und metrics.json (deterministisch sortiert)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(correspondence, out_dir / "correspondence.graphml")
    with (out_dir / "correspondence_edges.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "target", "weight", "letters", "date_begin", "date_end", "date_source"])
        for first, second, data in sorted(correspondence.edges(data=True)):
            writer.writerow([first, second, data["weight"], data["letters"],
                             data["date_begin"], data["date_end"], data["date_source"]])
    corr_labels = {node: data.get("label", node) for node, data in correspondence.nodes(data=True)}
    corr_metrics = graph_metrics(correspondence, corr_labels, directed=True)
    corr_metrics.update(corr_stats)
    mentions_metrics = None
    if mentions is not None:
        nx.write_graphml(mentions, out_dir / "mentions.graphml")
        with (out_dir / "mentions_edges.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "target", "weight", "letters", "letter_uris"])
            for first, second, data in sorted(mentions.edges(data=True)):
                writer.writerow([first, second, data["weight"], data["letters"], data["letter_uris"]])
        mention_labels = {node: data.get("label", node) for node, data in mentions.nodes(data=True)}
        mentions_metrics = graph_metrics(mentions, mention_labels, directed=False)
        mentions_metrics.update(mentions_stats or {})
    bipartite_metrics = None
    if graph_files is not None:
        if bipartite is None:
            bipartite, bipartite_stats = build_bipartite_mentions(graph_files)
        nx.write_graphml(bipartite, out_dir / "mentions_bipartite.graphml")
        with (out_dir / "mentions_bipartite_edges.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["letter_uri", "entity_uri", "entity_classes"])
            for first, second in sorted(bipartite.edges):
                writer.writerow([first, second, bipartite.nodes[second]["crm_classes"]])
        labels = {node: data["label"] for node, data in bipartite.nodes(data=True)}
        bipartite_metrics = graph_metrics(bipartite, labels, directed=True)
        bipartite_metrics.update(bipartite_stats or {})
    body = metrics(letter_files or [], graph_files, corr_metrics, mentions_metrics, bipartite_metrics)
    (out_dir / "metrics.json").write_text(json.dumps(body, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return body
