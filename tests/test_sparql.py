"""SPARQL-Abfragen auf dem eingefrorenen Graphen, an der TEI geprüft (R2).

Q1 und Q2 verbindlich, Q3 optional. Der Graph enthält nur die Auszeichnung
der Edition (Glossarmodus mit leerem Glossar, kein Modell). Regel für alle
Abfragen: alle redaktionellen Namen einschließlich impliziter Verweise
(``@subtype="implied"``); Begründung und Abgrenzung zur Evaluation
(295 Referenzen) in ``eval/sparql/README.md``.

Der unabhängige Weg liest direkt aus den Originalbriefen (``eval/corpus``):
Q1 löst ``@ref`` per XPath selbst auf (Entitätsmengen je Brief); Q2 prüft
Fundstellen über die Leseregel des Werkzeugs wie in der Evaluation, dazu
Wortlaut, Position und die Entität aus den ``@ref``-Tokens der Fundstelle;
Q3 vergleicht ``@ref``-Mengen je Brief. Geteilte Definitionen mit
Werkzeug und Evaluation sind zitiert: Lesetext aus
``tei_crm_bridge.projection`` (wie ``eval/README.md``), IRI-Gültigkeit aus
``tei_crm_bridge.rdf``. Die ``@ref``-Auflösung (xml:base-Kette; keine
prefixDefs im Korpus) ist eigene Implementierung und folgt
``GraphBuilder.resolve``/``_base_of`` (``src/tei_crm_bridge/rdf.py``).
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

import pytest
from lxml import etree
from rdflib import BNode, Graph, Literal, Namespace, URIRef

OA = Namespace("http://www.w3.org/ns/oa#")

from tei_crm_bridge.core import PARSER
from tei_crm_bridge.projection import TEI, TEI_URI, find_blocks, local_name, name_kind, project
from tei_crm_bridge.rdf import EVENTS, valid_iri
from tei_crm_bridge.writeback import XML_ID

ROOT = Path(__file__).resolve().parents[1]
SPARQL_DIR = ROOT / "eval" / "sparql"
sys.path.insert(0, str(SPARQL_DIR))
import build_graph  # noqa: E402

CORPUS = ROOT / "eval" / "corpus"
PMB = "https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions"
CRM = "http://www.cidoc-crm.org/cidoc-crm/"
CLASSES = {"PER": CRM + "E21_Person", "LOC": CRM + "E53_Place"}
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):(.*)$")
PMB_URI = re.compile(re.escape(PMB) + r"#pmb[0-9]+$")  # echte PMB-URI, wie der Q3-FILTER


def run(graph: Graph, name: str, **bindings):
    """Eine .rq-Datei aus eval/sparql auf dem Graphen ausführen."""
    text = (SPARQL_DIR / f"{name}.rq").read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return list(graph.query(body, initBindings=bindings))


def manifest() -> dict:
    return build_graph.load_manifest()


def manifest_gold() -> dict[str, tuple[int, int]]:
    """Je Brief (redaktionelle Referenzen ohne implied, implied-Anzahl)."""
    gold = {}
    with (ROOT / "eval" / "manifest.tsv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            gold[row["letter"]] = (int(row["gold_PER"]) + int(row["gold_LOC"]) + int(row["gold_ORG"]),
                                   int(row["implied_excluded"]))
    return gold


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    """Alles einmal: Graphen frisch aus den 40 Briefen, Hash, TEI, Annotationen, Abfragen.

    Q1 und Q3 laufen einmal auf dem Vereinigungsgraphen. Q2 läuft je Brief:
    Der Selektor-Join braucht in rdflib auf dem Vereinigungsgraphen Minuten
    (gemessen 485–562 s), je Briefdatei Millisekunden; die Datei ist dieselbe,
    die Zeilen enthalten keine Blank Nodes und sind daher identisch. Tests
    gruppieren und vergleichen in Python.
    """
    out = tmp_path_factory.mktemp("sparql")
    (out / "letters").mkdir()
    files = build_graph.build_letters(out)
    pinned = manifest()
    assert build_graph.files_hash(files) == pinned["graph_sha256"]
    graph = build_graph.build_union(files)
    letters = {}
    for target in files:
        single = Graph()
        single.parse(target, format="turtle")
        letters[target.stem] = single
    roots = {path.stem: etree.parse(str(path), PARSER).getroot()
             for path in sorted(CORPUS.glob("L*.xml"))}
    anns = {letter: annotations(letter, root, {"PER", "LOC", "ORG"})
            for letter, root in roots.items()}
    q2 = [row for single in letters.values() for row in run(single, "q2_evidence")]
    return {"graph": graph, "pinned": pinned, "roots": roots, "anns": anns,
            "letters": letters,
            "q1": run(graph, "q1_persons_places"), "q2": q2,
            "q3": run(graph, "q3_shared_persons")}


def letter_of_source(source: str, pinned: dict) -> str:
    """Briefkürzel aus der Spartendatei (Konvention des eingefrorenen Laufs)."""
    prefix = pinned["base_uri"] + "document/"
    assert source.startswith(prefix) and source.endswith("/tei"), source
    return source[len(prefix):-len("/tei")]


def letter_of_doc(doc: str, pinned: dict) -> str:
    """Briefkürzel aus der Dokument-URI (ohne /tei-Anhang)."""
    prefix = pinned["base_uri"] + "document/"
    assert doc.startswith(prefix), doc
    return doc[len(prefix):]


def base_of(node: etree._Element, default: str) -> tuple[str, bool]:
    """Effektive Basis-URI über die xml:base-Kette; folgt GraphBuilder._base_of."""
    chain = []
    while node is not None:
        value = node.get(XML_BASE)
        if value:
            chain.append(value)
        node = node.getparent()
    base, explicit = default, False
    for value in reversed(chain):
        base = urljoin(base, value)
        explicit = explicit or bool(_SCHEME.match(value))
    return base, explicit


def resolve(token: str, node: etree._Element, ids: dict, default: str):
    """(URI, Record-Element oder None) oder (None, None); folgt GraphBuilder.resolve.

    Ein ``#id`` ohne Registereintrag im Brief ist unaufgelöst (keine externe
    URI); schemalose Verweise gelten nur mit absolutem xml:base.
    """
    scheme = _SCHEME.match(token)
    if token.startswith("#"):
        record = ids.get(token[1:])
        if record is None:
            return None, None
        uri = urljoin(base_of(node, default)[0], token)
        return (uri, record) if valid_iri(uri) else (None, None)
    if scheme and scheme.group(1).lower() in ("http", "https"):
        return (token, None) if valid_iri(token) else (None, None)
    if not scheme:
        base, explicit = base_of(node, default)
        uri = urljoin(base, token) if explicit else None
        return (uri, None) if uri and valid_iri(uri) else (None, None)
    return None, None


def record_label(record: etree._Element) -> str | None:
    """Vorname + Nachname aus dem Registereintrag, sonst dessen Text."""
    for child in record:
        if local_name(child) in ("persName", "placeName", "orgName"):
            fores = [" ".join("".join(n.itertext()).split()) for n in child.iter(TEI + "forename")]
            surs = [" ".join("".join(n.itertext()).split()) for n in child.iter(TEI + "surname")]
            if fores or surs:
                return " ".join(fores + surs)
            return " ".join("".join(child.itertext()).split()) or None
    return None


def annotations(letter: str, root: etree._Element, kinds: set[str]) -> list[tuple]:
    """(Element, Art, Anzeigetext, @ref-Tokens) aller redaktionellen Namen im Lesetext."""
    found = []
    for block in find_blocks(root):
        projection = project(block)
        for item in projection.annotations:
            if item.kind in kinds:
                label = " ".join(projection.text[item.start:item.end].split())
                if label:  # Leerraum-Namen überspringt auch das Werkzeug (core._strip)
                    found.append((item.element, item.kind, label, (item.element.get("ref") or "").split()))
    return found


def slug(value: str) -> str:
    """Kurzform für lokale Entities; folgt rdf._slug (reine Zeichenfunktion)."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    short = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")[:48] or "entity"
    digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:10]
    return f"{short}-{digest}"


def mention_entities(kind: str, label: str, tokens: list[str], node: etree._Element,
                     ids: dict, default: str, doc: str) -> list[tuple]:
    """(URI, Record, Anzeigetext) einer Nennung; folgt GraphBuilder.entities_for."""
    resolved = [(token, resolve(token, node, ids, default)) for token in tokens]
    unresolved = [token for token, (uri, _) in resolved if uri is None]
    records = [(uri, record) for _, (uri, record) in resolved if uri is not None and record is not None]
    external = [uri for _, (uri, record) in resolved if uri is not None and record is None]
    if not records and not external:
        key = unresolved[0] if unresolved else None
        short = "ref-" + slug(key) if key else slug(label)
        return [(f"{doc}/entity/{kind.lower()}/{short}", None, label)]
    if len(records) == 1 and external:
        picked = records
    elif not records:
        picked = [(external[0], None)]
    else:
        picked = records + [(uri, None) for uri in external]
    return [(uri, record, label) for uri, record in picked]


def correspondence_names(root: etree._Element) -> list[tuple]:
    """(Art, Anzeigetext, Tokens, Element) aus abgebildeten correspActions.

    Der Kopf läuft vor dem Fließtext und setzt die ersten Labels
    (``enrich`` ruft ``add_correspondence`` zuerst auf); P67 gibt es dafür nicht.
    """
    found = []
    for action in root.iter(TEI + "correspAction"):
        if action.get("type") not in EVENTS:
            continue
        for node in action:
            if not isinstance(node.tag, str):
                continue
            kind = name_kind(node)
            if kind not in ("PER", "LOC", "ORG"):
                continue
            label = " ".join("".join(node.itertext()).split()) or node.get("ref")
            if label:
                found.append((kind, label, (node.get("ref") or "").split(), node))
    return found


def feed(kind: str, label: str, tokens: list[str], node: etree._Element, ids: dict,
         default: str, doc: str, seen: dict, classmap: dict, touched: set) -> None:
    """Entitäten einer Nennung in Labelherkunft (global, zuerst gewinnt) und Klassen."""
    for uri, record, text in mention_entities(kind, label, tokens, node, ids, default, doc):
        if uri not in seen:
            seen[uri] = (record_label(record) or text) if record is not None else text
        classmap.setdefault(uri, set()).add(CLASSES[kind])
        touched.add(uri)


def letter_model(letter: str, root: etree._Element, kinds: set[str], items: list[tuple],
                 default: str, doc: str, seen: dict, classmap: dict) -> set[tuple]:
    """Erwartete Q1-Zeilen (URI, Klasse, Label) eines Briefs aus der TEI.

    ``items`` sind vorberechnete Annotationen (Fixture); gefiltert wird hier.
    """
    ids = {node.get(XML_ID): node for node in root.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
    classes = {CLASSES[kind] for kind in kinds}
    touched: set[str] = set()
    for kind, label, tokens, node in correspondence_names(root):
        feed(kind, label, tokens, node, ids, default, doc, seen, classmap, set())
    for element, kind, label, tokens in [item for item in items if item[1] in kinds]:
        feed(kind, label, tokens, element, ids, default, doc, seen, classmap, touched)
    return {(uri, cls, seen[uri]) for uri in touched for cls in classmap[uri] if cls in classes}


def real_tsv_rows() -> list[dict]:
    """Zeilen aus eval/manifest.tsv, Header per Namen gelesen."""
    import csv as csv_module
    with (ROOT / "eval" / "manifest.tsv").open(encoding="utf-8") as handle:
        return list(csv_module.DictReader(handle, delimiter="\t"))


def test_manifest_provenance_checks():
    """Abweichungen an corpus_commit, TSV-Zeilen und Version werden abgewiesen."""
    rows = real_tsv_rows()
    commit = build_graph.validate_rows(rows)  # Kontrolle: echte Zeilen gelten
    pinned_manifest = dict(manifest())
    build_graph.check_provenance(pinned_manifest, commit)  # Kontrolle: echtes Manifest gilt
    tampered = dict(pinned_manifest, corpus_commit="0" * 40)
    with pytest.raises(SystemExit):
        build_graph.check_provenance(tampered, commit)
    doubled = rows + [dict(rows[0])]
    with pytest.raises(SystemExit):
        build_graph.validate_rows(doubled)
    old_version = dict(pinned_manifest, software_version="0.0.0")
    with pytest.raises(SystemExit):
        build_graph.check_provenance(old_version, commit)


def test_hash_and_letter_count(data):
    graph, pinned = data["graph"], data["pinned"]
    assert pinned["letters"] == 40
    docs = set(graph.subjects(URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                              URIRef(CRM + "E31_Document")))
    assert len(docs) == 40


def test_editorial_counts_match_gold_plus_implied(data):
    """335 redaktionelle Nennungen = 295 Referenzen + 40 implied, je Brief."""
    graph, pinned = data["graph"], data["pinned"]
    counts = {letter_of_source(str(row[0]), pinned): int(row[1]) for row in graph.query(
        "PREFIX tcb: <https://klausbehnamshad.github.io/tei-crm-bridge/vocab/#> "
        "PREFIX oa: <http://www.w3.org/ns/oa#> "
        "SELECT ?source (COUNT(?ann) AS ?n) WHERE { "
        "?ann tcb:origin tcb:editorial ; oa:hasTarget [ oa:hasSource ?source ] } "
        "GROUP BY ?source")}
    assert len(counts) == 40
    total_gold = total_implied = 0
    for letter, (gold, implied) in manifest_gold().items():
        assert counts.get(letter, 0) == gold + implied, letter
        total_gold += gold
        total_implied += implied
    assert (total_gold, total_implied, sum(counts.values())) == (295, 40, 335)


def test_q1_all_letters(data):
    """Q1-Zeilen je Brief = @ref-Auflösung aus der TEI (Inhalte, nicht Anzahlen)."""
    pinned, rows = data["pinned"], data["q1"]
    by_letter: dict[str, list] = {}
    for row in rows:
        by_letter.setdefault(letter_of_doc(str(row[0]), pinned), []).append(row)
    seen, classmap = {}, {}
    for letter in sorted(data["roots"]):
        root = data["roots"][letter]
        doc = pinned["base_uri"] + "document/" + letter
        want = letter_model(letter, root, {"PER", "LOC"}, data["anns"][letter],
                            doc + "/tei", doc, seen, classmap)
        got = {(str(row[1]), str(row[2]), str(row[3])) for row in by_letter.get(letter, [])}
        assert got == want, letter


def check_q2_positions(rows, roots, pinned) -> None:
    """Wortlaut und Nachbarschaft jeder Q2-Zeile an der Position im Lesetext."""
    for row in rows:
        _, _, block, exact, prefix, suffix, start, end, source = (
            str(v) if v is not None else None for v in row)
        letter = letter_of_source(source, pinned)
        nodes = roots[letter].xpath(block)
        assert len(nodes) == 1, (letter, block)
        value = nodes[0].xpath("string(.)")
        start, end = int(start), int(end)
        assert value[start:end] == exact, (letter, exact)
        if start > 0:
            assert prefix == value[max(0, start - 32):start], (letter, exact)
        else:
            assert prefix is None, (letter, exact)
        if end < len(value):
            assert suffix == value[end:end + 32], (letter, exact)
        else:
            assert suffix is None, (letter, exact)


def check_q2_entities(rows, roots, pinned) -> None:
    """?entity jeder Q2-Zeile stammt aus den @ref-Tokens ihrer Fundstelle.

    An die Fundstelle gebunden: Das Namenselement wird über Block-XPath plus
    Position (start/end, über project().raw_span) gefunden, nicht über den
    Wortlaut im Block; Art über die zitierte name_kind-Definition, Tokens
    mit resolve() selbst aufgelöst (xml:base-Kette, keine prefixDefs im
    Korpus); unaufgelöste Refs folgen der Dokument-Entity-Regel aus
    mention_entities. Ein umgebogener Body fliegt hier auf.
    """
    for row in rows:
        entity, _, block, exact = (str(v) if v is not None else None for v in row[:4])
        start, end = int(row[6]), int(row[7])
        source = str(row[8])
        letter = letter_of_source(source, pinned)
        root = roots[letter]
        doc = pinned["base_uri"] + "document/" + letter
        ids = {node.get(XML_ID): node for node in root.iter()
               if isinstance(node.tag, str) and node.get(XML_ID)}
        nodes = root.xpath(block)
        assert len(nodes) == 1, (letter, block)
        projection = project(nodes[0])
        want = " ".join(exact.split())
        uris, hit = set(), False
        for item in projection.annotations:
            if projection.raw_span(item.start, item.end) != (start, end):
                continue
            kind = name_kind(item.element)
            if kind is None:
                continue
            hit = True
            tokens = (item.element.get("ref") or "").split()
            for uri, _, _ in mention_entities(kind, want, tokens, item.element,
                                             ids, doc + "/tei", doc):
                uris.add(uri)
        assert hit, (letter, exact, start, end)
        assert entity in uris, (letter, exact, entity, sorted(uris))


def test_q2_all_annotations(data):
    """Jede Q2-Zeile: Wortlaut, Position und Entität stimmen mit der TEI überein.

    335 Annotationen ergeben 340 Zeilen: 5 Nennungen tragen mehrere Referenten
    (ein @ref mit mehreren Registereinträgen, z. B. „Saltens" für Felix und
    Ottilie Salten) und erscheinen je Referent einmal. Jede Mehrfachzeile wird
    unten an ihren mehreren Bodies erkannt, nicht vorausgesetzt.
    """
    graph, pinned, rows = data["graph"], data["pinned"], data["q2"]
    assert len(rows) == 340
    anns = Counter(str(row[1]) for row in rows)
    assert len(anns) == 335
    assert sum(count - 1 for count in anns.values()) == 5
    for ann, count in anns.items():
        if count > 1:
            assert len(set(graph.objects(URIRef(ann), OA.hasBody))) == count, ann
    check_q2_positions(rows, data["roots"], pinned)
    check_q2_entities(rows, data["roots"], pinned)


def test_q2_rewired_body_rejected(data):
    """Umgebogener Body: Wortlaut/Position bleiben grün, die Entität fliegt auf.

    Deterministische Probe (R3-Befund 1): Zwei gleichlautende Namen mit
    verschiedenem @ref im selben Block (erste Gruppe sortiert nach
    (Block, Wortlaut)); der Body der ersten Ein-Body-Annotation (sortiert
    nach (Annotation, Entität)) wird auf die Entität der anderen Fundstelle
    umgebogen, Selektoren und P67 unverändert. Nur für den Test erzeugter
    Graph (L03501-Kopie).
    """
    single = Graph()
    for triple in data["letters"]["L03501"]:
        single.add(triple)
    rows = run(single, "q2_evidence")
    assert rows, "Umbau darf keine Zeilen verlieren"
    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((str(row[2]), " ".join(str(row[3]).split())),
                          []).append((str(row[1]), str(row[0])))
    candidates = sorted(
        (key, sorted(set(pairs)))
        for key, pairs in groups.items()
        if len({ann for ann, _ in pairs}) >= 2
        and len({entity for _, entity in pairs}) >= 2
    )
    assert candidates, "keine gleichlautende Gruppe mit verschiedenen Entitäten"
    (_, _), pairs = candidates[0]
    bodies_of = {ann: sorted(str(body) for body in single.objects(URIRef(ann), OA.hasBody))
                 for ann, _ in pairs}
    ordered = sorted(set(pairs))
    target = next((ann, entity) for ann, entity in ordered
                  if len(bodies_of[ann]) == 1)
    ann, old = target
    others = sorted({entity for other_ann, entity in ordered
                     if other_ann != ann and entity != old})
    assert others, "keine Ersatz-URI in der Gruppe"
    single.remove((URIRef(ann), OA.hasBody, URIRef(old)))
    single.add((URIRef(ann), OA.hasBody, URIRef(others[0])))
    rows = run(single, "q2_evidence")
    assert rows, "Umbau darf keine Zeilen verlieren"
    check_q2_positions(rows, data["roots"], data["pinned"])  # Lücke: bleibt grün
    with pytest.raises(AssertionError):
        check_q2_entities(rows, data["roots"], data["pinned"])


TEI_NS = {"tei": TEI_URI}
NAME_XPATH = (
    "//tei:body//tei:persName | //tei:body//tei:placeName | //tei:body//tei:geogName | "
    "//tei:body//tei:settlement | //tei:body//tei:country | //tei:body//tei:region | "
    "//tei:body//tei:district | //tei:body//tei:bloc | "
    "//tei:body//tei:rs[@type='person' or @type='place'] | "
    "//tei:body//tei:name[@type='person' or @type='place']"
)


def xpath_tokens(letter: str, root: etree._Element) -> set[tuple]:
    """(Brief, @ref-Token) rein über XPath: Namen im body ohne note/del."""
    pairs = set()
    for element in root.xpath(NAME_XPATH, namespaces=TEI_NS):
        if any(isinstance(ancestor.tag, str)
               and (ancestor.tag == TEI + "note" or ancestor.tag == TEI + "del")
               for ancestor in element.iterancestors()):
            continue
        for token in (element.get("ref") or "").split():
            pairs.add((letter, token))
    return pairs


def test_xpath_token_set_matches_annotations(data):
    """Gleiche (Brief, Token)-Menge aus XPath wie aus den Fixture-Annotationen (R2b).

    Verglichen werden data["anns"] (über find_blocks/project aus der TEI) und
    der XPath-Weg ohne tei_crm_bridge.projection. Bei Abweichungen wird nichts
    repariert: Der Test listet sie auf und scheitert.
    """
    model_pairs, xpath_pairs = set(), set()
    for letter, root in data["roots"].items():
        for _, kind, _, tokens in data["anns"][letter]:
            if kind in ("PER", "LOC"):
                for token in tokens:
                    model_pairs.add((letter, token))
        xpath_pairs |= xpath_tokens(letter, root)
    only_xpath = sorted(xpath_pairs - model_pairs)
    only_model = sorted(model_pairs - xpath_pairs)
    assert not only_xpath and not only_model, (
        f"nur XPath: {only_xpath[:10]}; nur letter_model: {only_model[:10]}")


def test_q2_union_equals_per_letter_multiset(data):
    """Q2 auf der Zwei-Brief-Vereinigung = Einzelbriefe aneinander (Multimenge).

    Gilt nur unter zwei Strukturbedingungen: Die Annotation-URIs sind je
    Brief verschieden, und Blank Nodes werden je Datei getrennt geparst —
    sonst entstünden über gemeinsame URIs oder Blank Nodes
    Kreuzkombinationen. Die Q2-Zeilen selbst enthalten keine Blank Nodes;
    ihre Reihenfolge (ORDER BY) zählt nicht mit. L00026 und L02376 teilen
    zwei Entitäten (pmb30, pmb50), sodass der Join über Briefe greifen würde.
    """
    pair = ("L00026", "L02376")
    union = Graph()
    for letter in pair:
        for triple in data["letters"][letter]:
            union.add(triple)
    rows = run(union, "q2_evidence")
    want = [row for letter in pair for row in run(data["letters"][letter], "q2_evidence")]
    key = lambda row: tuple(str(value) for value in row)  # noqa: E731
    assert Counter(map(key, rows)) == Counter(map(key, want))
    assert rows, "Vereinigung darf keine Zeilen verlieren"
    for row in rows:
        for value in row:
            assert not isinstance(value, BNode), row


def test_q3_rejects_non_pmb_editions_uri():
    """editions#andere-id ist keine PMB-URI und darf nicht gruppiert werden.

    Nur für den Test gebauter Graph: zwei Briefe nennen dieselbe
    editions-URI ohne #pmb-Ziffern.
    """
    other = PMB + "#andere-id"
    graph = Graph()
    e31, e21, p67 = (URIRef(CRM + name) for name in
                     ("E31_Document", "E21_Person", "P67_refers_to"))
    rdf_type = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    for letter in ("L00001", "L00002"):
        doc = URIRef("https://example.org/tei-crm-demo/document/" + letter)
        graph.add((doc, rdf_type, e31))
        graph.add((doc, p67, URIRef(other)))
    graph.add((URIRef(other), rdf_type, e21))
    graph.add((URIRef(other),
               URIRef("http://www.w3.org/2000/01/rdf-schema#label"),
               Literal("Andere Id")))
    rows = run(graph, "q3_shared_persons")
    assert [str(row[0]) for row in rows] == [], [str(row[0]) for row in rows]


GUARD_XPATH = (
    "//tei:body//tei:persName | //tei:body//tei:placeName | //tei:body//tei:orgName | "
    "//tei:body//tei:geogName | //tei:body//tei:settlement | //tei:body//tei:country | "
    "//tei:body//tei:region | //tei:body//tei:district | //tei:body//tei:bloc | "
    "//tei:body//tei:rs[@type='person' or @type='place' or @type='org'] | "
    "//tei:body//tei:name[@type='person' or @type='place' or @type='org']"
)
UNREAD_BRANCHES = {"choice", "app", "fw", "index", "interp", "gap"}


def test_no_names_in_unread_branches(data):
    """Korpusgrenze des R2b-Vergleichs: kein Name in choice/app/fw/index/interp/gap.

    Der XPath-Weg bildet die Leseregel des Werkzeugs nicht vollständig nach
    (keine ausgeschlossenen Teilbäume, keine Alternativzweige von choice/app);
    der Token-Vergleich gilt nur, weil der eingefrorene Korpus keine
    Namenselemente an solchen Stellen enthält. Kommt eines vor, scheitert
    dieser Test statt still zu vergleichen.
    """
    hits = []
    for letter, root in data["roots"].items():
        for element in root.xpath(GUARD_XPATH, namespaces=TEI_NS):
            for ancestor in element.iterancestors():
                if isinstance(ancestor.tag, str) and local_name(ancestor) in UNREAD_BRANCHES:
                    hits.append((letter, local_name(ancestor),
                                 " ".join("".join(element.itertext()).split())[:40]))
                    break
    assert hits == [], hits[:10]


def test_q3_shared_persons(data):
    """Q3-Zeilen = (Person, Brief)-Paare gemeinsamer PMB-URIs (aus der TEI)."""
    pinned, rows = data["pinned"], data["q3"]
    persons: dict[str, set[str]] = {}
    for letter, root in data["roots"].items():
        doc = pinned["base_uri"] + "document/" + letter
        ids = {node.get(XML_ID): node for node in root.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
        letter_uris = set()
        for element, kind, label, tokens in data["anns"][letter]:
            if kind != "PER":
                continue
            for uri, _, _ in mention_entities(kind, label, tokens, element, ids, doc + "/tei", doc):
                letter_uris.add(uri)
        for uri in letter_uris:
            persons.setdefault(uri, set()).add(letter)
    want = {uri: letters for uri, letters in persons.items()
            if len(letters) > 1 and PMB_URI.match(uri)}
    others = {uri: letters for uri, letters in persons.items()
              if len(letters) > 1 and not PMB_URI.match(uri)}
    got: dict[str, set[str]] = {}
    labels: dict[str, str] = {}
    for row in rows:
        uri, label, doc = str(row[0]), str(row[1]), str(row[2])
        got.setdefault(uri, set()).add(letter_of_doc(doc, pinned))
        assert labels.setdefault(uri, label) == label, uri
    assert got == want
    assert others == {}, f"gemeinsame Nicht-PMB-URIs separat ausweisen: {others}"
