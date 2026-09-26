"""Build the GitHub Pages site in docs/ and the README results from pinned inputs.

    python scripts/build_docs.py               # example, vocabulary, landing page, README results
    python scripts/build_docs.py --with-model  # also the Schnitzler letter (needs the cached model)
    python scripts/build_docs.py --check       # exit 1 if a generated file is out of date (CI)

Every number on the landing page and in the README comes from eval/results;
the three error cases in docs/cases.json are checked against them. Without the
model, ``--check`` still proves for the Schnitzler demo that it was made from
the manifest's letter with the pinned model revision and this software
version, that removing the additions restores the letter exactly, and that
every annotation can be found again in the published TEI file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lxml import etree  # noqa: E402
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef  # noqa: E402

from tei_crm_bridge import __version__  # noqa: E402
from tei_crm_bridge.core import PARSER, enrich  # noqa: E402
from tei_crm_bridge.ner import GlossaryRecognizer, HuggingFaceRecognizer  # noqa: E402
from tei_crm_bridge.preview import write_preview  # noqa: E402
from tei_crm_bridge.projection import string_value  # noqa: E402
from tei_crm_bridge.rdf import OA  # noqa: E402
from tei_crm_bridge.vocabulary import NAMESPACE, TERMS  # noqa: E402
from tei_crm_bridge.writeback import canonical, strip_enrichment  # noqa: E402

DOCS, RESULTS = ROOT / "docs", ROOT / "eval" / "results"
REAL_LETTER = "L02051"
REPO_URL = "https://github.com/klausbehnamshad/tei-crm-bridge"
PAGES_URL = "https://klausbehnamshad.github.io/tei-crm-bridge/"
XSI = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"
README_START, README_END = "<!-- results:start -->", "<!-- results:end -->"
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")


def de(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def load(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


# Demos ----------------------------------------------------------------------

def manifest_row(letter: str) -> dict:
    with (ROOT / "eval" / "manifest.tsv").open(encoding="utf-8") as handle:
        return next(row for row in csv.DictReader(handle, delimiter="\t") if row["letter"] == letter)


def build_demo(source: Path, target: str, recognizer, source_url: str | None = None, rewrite=None) -> dict[str, bytes]:
    """Enrich ``source`` into docs/<target>/; annotations point to the published TEI file."""
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        stem = source.stem
        paths = [out / f"{stem}{suffix}" for suffix in (".enriched.xml", ".ttl", ".mentions.json", ".html")]
        # core.enrich adds a slash to the base; after the hash, all graph IRIs
        # still resolve to this published HTML page rather than example.org.
        graph_base = f"{PAGES_URL}{target}/{paths[3].name}#"
        result = enrich(source, paths[0], paths[1], recognizer, graph_base, output_json=paths[2],
                        tei_url=f"{PAGES_URL}{target}/{paths[0].name}", source_url=source_url)
        if rewrite:
            paths[0].write_bytes(rewrite(paths[0].read_bytes()))
        write_preview(*paths, result)
        return {str(DOCS / target / path.name): path.read_bytes() for path in paths}


def _schema_base(row: dict) -> str:
    return row["source_url"].rsplit("/editions/", 1)[0] + "/meta/"


def absolute_schemas(content: bytes, row: dict) -> bytes:
    """Point the edition's relative schema references (../meta/…) to the pinned upstream files."""
    tree = etree.ElementTree(etree.fromstring(content, PARSER))
    root = tree.getroot()
    for node in root.itersiblings(preceding=True):
        if isinstance(node, etree._ProcessingInstruction) and node.text:
            node.text = node.text.replace('"../meta/', f'"{_schema_base(row)}')
    if root.get(XSI):
        root.set(XSI, root.get(XSI).replace("../meta/", _schema_base(row)))
    return etree.tostring(tree, encoding="utf-8", xml_declaration=True)


def relative_schemas(root: etree._Element, row: dict) -> etree._Element:
    if root.get(XSI):
        root.set(XSI, root.get(XSI).replace(_schema_base(row), "../meta/"))
    return root


def build_real_letter() -> dict[str, bytes]:
    row = manifest_row(REAL_LETTER)
    return build_demo(ROOT / "eval" / "corpus" / f"{REAL_LETTER}.xml", "schnitzler", HuggingFaceRecognizer(local_files_only=True),
                      source_url=row["source_url"], rewrite=lambda content: absolute_schemas(content, row))


def check_annotations(ttl: Path, tei: Path, tei_url: str) -> list[str]:
    """Every annotation targets ``tei_url`` and its selectors find the same text in ``tei``."""
    graph, root, problems = Graph().parse(ttl, format="turtle"), etree.parse(str(tei), PARSER).getroot(), []
    for annotation in graph.subjects(RDF.type, OA.Annotation):
        target = graph.value(annotation, OA.hasTarget)
        if str(graph.value(target, OA.hasSource)) != tei_url:
            problems.append(f"{annotation}: source is not {tei_url}")
            continue
        found = set()
        for selector in graph.objects(target, OA.hasSelector):
            nodes = root.xpath(str(graph.value(selector, RDF.value)))
            if len(nodes) != 1:
                problems.append(f"{annotation}: XPath selects {len(nodes)} nodes")
                continue
            text, refined = string_value(nodes[0]), graph.value(selector, OA.refinedBy)
            if refined is None:
                found.add(text)
            elif graph.value(refined, OA.start) is not None:
                found.add(text[int(graph.value(refined, OA.start)):int(graph.value(refined, OA.end))])
            else:
                exact = str(graph.value(refined, OA.exact))
                context = str(graph.value(refined, OA.prefix) or "") + exact + str(graph.value(refined, OA.suffix) or "")
                found.add(exact if context in text else "\0missing")
        if len(found) != 1:
            problems.append(f"{annotation}: selectors disagree {sorted(found)}")
    return problems


def check_real_letter() -> list[str]:
    """Provenance and integrity of the committed model demo, checked without the model."""
    row = manifest_row(REAL_LETTER)
    folder = DOCS / "schnitzler"
    record = json.loads((folder / f"{REAL_LETTER}.mentions.json").read_text(encoding="utf-8"))
    corpus = ROOT / "eval" / "corpus" / f"{REAL_LETTER}.xml"
    expected = {
        "input": record["input"]["sha256"] == row["sha256"] == hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "model": record["settings"].get("model") == HuggingFaceRecognizer.MODEL,
        "revision": record["settings"].get("modelRevision") == HuggingFaceRecognizer.REVISION,
        "software": record["software"]["version"] == __version__,
        "source": record["input"]["url"] == row["source_url"],
    }
    problems = [f"schnitzler demo: {key} does not match" for key, ok in expected.items() if not ok]
    enriched = etree.parse(str(folder / f"{REAL_LETTER}.enriched.xml"), PARSER).getroot()
    if canonical(relative_schemas(strip_enrichment(enriched), row)) != canonical(etree.parse(str(corpus), PARSER).getroot()):
        problems.append("schnitzler demo: removing the additions does not restore the letter")
    problems += check_annotations(folder / f"{REAL_LETTER}.ttl", folder / f"{REAL_LETTER}.enriched.xml",
                                  f"{PAGES_URL}schnitzler/{REAL_LETTER}.enriched.xml")
    return problems


# Vocabulary -----------------------------------------------------------------

def build_vocabulary() -> dict[str, bytes]:
    vocab = Namespace(NAMESPACE)
    graph = Graph()
    graph.bind("tcb", vocab)
    graph.bind("crm", CRM)
    ontology = URIRef(NAMESPACE.rstrip("#"))
    graph.add((ontology, RDFS.label, Literal("TEI CRM Bridge vocabulary", lang="en")))
    types = {"class": RDFS.Class, "property": RDF.Property, "type": CRM.E55_Type, "origin": vocab.Origin,
             "decision": vocab.ReviewDecision}
    for name, kind, label_de, label_en, definition in TERMS:
        term = vocab[name]
        graph.add((term, RDF.type, types[kind]))
        graph.add((term, RDFS.label, Literal(label_de, lang="de")))
        graph.add((term, RDFS.label, Literal(label_en, lang="en")))
        graph.add((term, RDFS.comment, Literal(definition, lang="de")))
        graph.add((term, RDFS.isDefinedBy, ontology))
    turtle = graph.serialize(format="turtle").encode("utf-8")
    rows = "\n".join(
        f'<tr id="{name}"><td><code>tcb:{name}</code></td><td>{escape(kind)}</td><td>{escape(label_de)}</td><td>{escape(definition)}</td></tr>'
        for name, kind, label_de, _, definition in TERMS
    )
    body = f"""<section class="panel"><p>Namensraum <code>{escape(NAMESPACE)}</code>. Das Projekt nutzt CIDOC CRM, W3C Web Annotation, PROV-O und Dublin Core;
<code>tcb:</code> benennt nur, was diese offenlassen. <a href="vocab.ttl">Als Turtle</a>.</p>
<div class="table"><table><thead><tr><th>Term</th><th>Art</th><th>Bezeichnung</th><th>Definition</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""
    html = page("Vokabular", "tcb: – das kleine Projektvokabular", body, depth=1)
    return {str(DOCS / "vocab" / "vocab.ttl"): turtle, str(DOCS / "vocab" / "index.html"): html.encode("utf-8")}


# Landing page -------------------------------------------------------------------

STYLE = """
:root{--ink:#172a2d;--muted:#52696c;--paper:#f6f4ed;--panel:#fff;--line:#d8ddd7;--accent:#0c615c;--head:#173b3b;--good:#1d6b43;--bad:#9b3b2f}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ink:#e4ece9;--muted:#9fb3af;--paper:#111a1b;--panel:#182324;--line:#2c3b3c;--accent:#6fc7bd;--head:#0c2020;--good:#7fd1a1;--bad:#f2a293}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif}
header{background:var(--head);color:#fff;padding:2.4rem max(1rem,calc((100vw - 1040px)/2)) 2rem}
header .eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;color:#b5d4ce}
header h1{font:normal clamp(1.9rem,4.4vw,3rem)/1.1 Georgia,serif;margin:.5rem 0}header p{color:#d5e6e1;max-width:68ch;margin:.4rem 0}
header nav{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1.2rem}header nav a{color:#fff;border:1px solid #6f9b95;border-radius:999px;padding:.4rem .9rem;text-decoration:none;font-size:.92rem}
header nav a.primary{background:#e8f4f1;color:#173b3b;border-color:#e8f4f1}
main{max-width:1040px;margin:auto;padding:1.6rem 1rem 3rem}
h2{font:normal 1.55rem Georgia,serif;margin:2.2rem 0 .8rem}h3{font-size:1.02rem;margin:1.2rem 0 .4rem}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:1.2rem 1.3rem;margin:0 0 1rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.8rem;margin-top:1.2rem}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:.9rem 1rem}.tile strong{display:block;font:normal 1.7rem Georgia,serif}.tile span{color:var(--muted);font-size:.9rem}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.6rem;counter-reset:step}
.steps div{border:1px solid var(--line);border-radius:12px;padding:.8rem;background:var(--panel)}.steps div::before{counter-increment:step;content:counter(step);display:inline-block;font:600 .8rem system-ui;background:var(--accent);color:var(--paper);border-radius:999px;width:1.5rem;height:1.5rem;text-align:center;line-height:1.5rem;margin-bottom:.3rem}
.steps b{display:block}.steps span{color:var(--muted);font-size:.9rem}
.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.93rem}th,td{border-bottom:1px solid var(--line);padding:.45rem .5rem;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.up{color:var(--good)}.down{color:var(--bad)}
.muted{color:var(--muted)}code{font-size:.86em;overflow-wrap:anywhere}a{color:var(--accent)}
.case{border-left:4px solid var(--accent);padding-left:1rem;margin:1rem 0}.case .ctx{font-family:Georgia,serif;background:var(--paper);border-radius:8px;padding:.5rem .7rem;margin:.4rem 0}
.case mark{background:transparent;border-bottom:2px solid var(--accent);color:inherit;font-weight:600}
pre{background:var(--head);color:#e8f4f1;border-radius:10px;padding:.9rem 1rem;overflow-x:auto;font-size:.86rem}
footer{max-width:1040px;margin:auto;padding:0 1rem 2.5rem;color:var(--muted);font-size:.86rem}
"""


def page(title: str, subtitle: str, body: str, depth: int = 0, nav: str = "") -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · TEI CRM Bridge</title><style>{STYLE}</style></head><body>
<header><div class="eyebrow"><a href="{up}index.html" style="color:inherit;text-decoration:none">TEI CRM Bridge {escape(__version__)}</a></div>
<h1>{escape(title)}</h1><p>{subtitle}</p>{nav}</header>
<main>{body}</main>
<footer>Code: MIT · <a href="{REPO_URL}">GitHub</a>. Briefe: Arthur Schnitzler: Briefwechsel mit Autorinnen und Autoren, hg. v. Martin Anton Müller und Gerd-Hermann Susen,
Austrian Centre for Digital Humanities, <a href="https://creativecommons.org/licenses/by/4.0/deed.de">CC BY 4.0</a>. Die Dateien in <code>eval/corpus</code> sind unverändert;
die Demo-TEI ist maschinell bearbeitet (ergänzte Namen mit <code>@resp</code>, Verarbeitungsvermerk, absolute Schemaverweise).
Modell: <a href="https://huggingface.co/impresso-project/ner-hipe2020-hist-base">impresso-project/ner-hipe2020-hist-base</a> (CC BY-NC-SA 4.0, nicht mitgeliefert).</footer>
</body></html>
"""


def metric_rows(before: dict, after: dict, scope: str) -> str:
    rows = []
    labels = {"strict": "strikt", "overlap": "überlappend"}
    for mode in ("strict", "overlap"):
        for measure, name in (("precision", "Präzision"), ("recall", "Recall"), ("f1", "F1")):
            a, b = round(before[scope][mode]["all"][measure], 3), round(after[scope][mode]["all"][measure], 3)
            css = "up" if b > a else "down" if b < a else ""
            rows.append(f'<tr><td>{labels[mode]}</td><td>{name}</td><td class="num">{de(a)}</td><td class="num">{de(b)}</td><td class="num {css}">{"+" if b >= a else "−"}{de(abs(b - a))}</td></tr>')
    return "".join(rows)


def type_rows(result: dict) -> str:
    rows = []
    for kind, label in (("PER", "Personen"), ("LOC", "Orte"), ("ORG", "Organisationen"), ("all", "gesamt")):
        s, o = result["metrics"]["strict"][kind], result["metrics"]["overlap"][kind]
        rows.append(
            f'<tr><td>{label}</td><td class="num">{s["gold"]}</td><td class="num">{s["predicted"]}</td><td class="num">{de(s["f1"])}</td>'
            f'<td class="num">{de(o["precision"])}</td><td class="num">{de(o["recall"])}</td><td class="num">{de(o["f1"])}</td></tr>'
        )
    return "".join(rows)


def cases_html(result: dict) -> str:
    cases = json.loads((DOCS / "cases.json").read_text(encoding="utf-8"))
    labels = {"missed": "nicht erkannt", "spurious": "falscher Treffer", "boundary": "Grenze abweichend", "type": "Typ abweichend"}
    blocks = []
    for case in cases:
        match = [
            e for e in result["errors"]
            if e["category"] == case["category"]
            and (e["predicted"] or e["gold"])["letter"] == case["letter"]
            and (e["predicted"] or e["gold"])["text"] == case["text"]
        ]
        if not match:
            raise SystemExit(f"case {case} is not among the errors of {result['label']}")
        error = match[0]
        left, _, rest = error["context"].partition(" [")
        inner, _, right = rest.partition("] ")
        spans = []
        for role, span in (("Vorhersage", error["predicted"]), ("Referenz", error["gold"])):
            if span:
                spans.append(f"{role}: {span['kind']} „{escape(' '.join(span['text'].split()))}“")
        blocks.append(
            f'<div class="case"><h3>{escape(case["title"])}</h3><p class="muted">{labels[error["category"]]} · Brief {escape(case["letter"])} · '
            f'{" · ".join(spans)}</p><div class="ctx">{escape(left)} <mark>{escape(inner)}</mark> {escape(right)}</div><p>{escape(case["comment"])}</p></div>'
        )
    return "".join(blocks)


def build_index() -> dict[str, bytes]:
    before, after, simple = load("v0.1-hf"), load("v0.2-hf"), load("ablation-simple")
    old, new = load("integrity_v0.1-hf-original"), load("integrity_v0.2-hf-original")
    sc = after["spotcheck"]
    fp = after["errors_by_block_type"]["spurious"]
    fp_frame = sum(count for name, count in fp.items() if name != "p")
    corpus, v01, v02 = after["corpus"], before["metrics_v01_scope"], after["metrics_v01_scope"]
    tool = after["run"]["tool"]
    tiles = [
        (f"{old['in_existing_name_reference']} → {new['in_existing_name_reference']}", "neue Namen innerhalb bestehender Namensreferenzen der Edition (40 Originalbriefe)"),
        (f"{old['in_note']} → {new['in_note']}", "neue Namen in Kommentaren <code>&lt;note&gt;</code>"),
        (f"{de(v01['strict']['all']['f1'])} → {de(v02['strict']['all']['f1'])}", "F1 strikt, nur Text in <code>&lt;p&gt;</code> – der Umfang, den v0.1 las"),
        (f"{de(before['metrics']['overlap']['all']['recall'])} → {de(after['metrics']['overlap']['all']['recall'])}", "Recall überlappend, alle Textblöcke"),
    ]
    nav = (f'<nav><a class="primary" href="schnitzler/{REAL_LETTER}.html">Echter Brief ansehen</a><a href="example/letter.html">Fiktives Beispiel</a>'
           f'<a href="{REPO_URL}/tree/main/eval">Evaluation</a><a href="{REPO_URL}">Code</a></nav>')
    body = f"""
<div class="tiles">{"".join(f'<div class="tile"><strong>{value}</strong><span>{label}</span></div>' for value, label in tiles)}</div>

<h2>Was das Werkzeug tut</h2>
<div class="steps">
<div><b>Lesetext bilden</b><span>Pro Absatz, Briefkopf, Adresse oder Grußformel ein zusammenhängender Text; <code>&lt;c&gt;</code> bleibt im Wort, Kommentare zählen nicht.</span></div>
<div><b>Namen erkennen</b><span>Historisches NER-Modell mit überlappenden Fenstern; unvollständig gelesene Texte brechen ab statt still zu kürzen.</span></div>
<div><b>Behutsam zurückschreiben</b><span>Inline nur innerhalb eines Textknotens; sonst Stand-off. Die ursprüngliche Textauszeichnung im <code>body</code> ist nach Entfernen der Ergänzungen wiederherstellbar.</span></div>
<div><b>Vorschläge als Vorschläge</b><span>Automatische Treffer werden Kandidaten mit vorgeschlagener CRM-Klasse und Herkunft; Aussagen der Edition bleiben CIDOC CRM.</span></div>
<div><b>Redaktionell prüfen</b><span>Version 0.3: einzelne Inline- und Stand-off-Treffer annehmen oder ablehnen, Entscheidungen mit Begründung exportieren und daraus einen getrennten geprüften Graphen erzeugen.</span></div>
<div><b>Messen</b><span>Gegen die redaktionelle Auszeichnung von {corpus['letters']} Briefen der Schnitzler-Edition, reproduzierbar ab festem Commit.</span></div>
</div>
<p class="muted">Die untenstehenden Kennzahlen stammen aus Version 0.2. Die neue Prüffunktion verändert weder die Erkennung noch diese Messwerte; sie ergänzt einen nachvollziehbaren menschlichen Entscheidungsschritt.</p>

<h2>Gemessen: v0.1 gegen v0.2</h2>
<p>{corpus['letters']} Briefe aus <a href="https://github.com/arthur-schnitzler/schnitzler-briefe-data">schnitzler-briefe-data</a> @ <code>{corpus['commit'][:12]}</code>,
{corpus['gold']} redaktionelle Personen-, Orts- und Organisationsreferenzen als Referenz. Die Auszeichnungen wurden vor dem Lauf entfernt; beide Versionen erhielten dieselben Eingaben
mit demselben Modell (<code>impresso-project/ner-hipe2020-hist-base</code>, Schwelle 0,85). Gemessen mit TEI CRM Bridge {escape(tool['version'])},
Paketbaum <code>{escape(tool['package_tree'][:12])}</code> (<code>git rev-parse &lt;commit&gt;:src/tei_crm_bridge</code>).</p>
<p><b>Beide Blickwinkel gehören zusammen:</b> Im Text, den v0.1 überhaupt las, steigen Präzision und F1. Über alle Textblöcke steigt der Recall deutlich,
die strikte Präzision sinkt aber, weil v0.2 auch Adressen, Briefköpfe und Grußformeln liest und dort Namen vorschlägt, die die Referenz nicht enthält.</p>
<div class="panel table"><table><thead><tr><th>Nur Text in <code>&lt;p&gt;</code></th><th></th><th class="num">v0.1</th><th class="num">v0.2</th><th class="num">Δ</th></tr></thead>
<tbody>{metric_rows(before, after, "metrics_v01_scope")}</tbody></table></div>
<div class="panel table"><table><thead><tr><th>Alle Textblöcke</th><th></th><th class="num">v0.1</th><th class="num">v0.2</th><th class="num">Δ</th></tr></thead>
<tbody>{metric_rows(before, after, "metrics")}</tbody></table></div>
<p class="muted">Strikt: gleiche Grenzen und gleicher Typ. Überlappend: gleicher Typ, mindestens ein gemeinsames Zeichen, eins zu eins. Die Regeln wurden vor der ersten Messung festgelegt.</p>

<h3>v0.2 nach Typ (alle Blöcke)</h3>
<div class="panel table"><table><thead><tr><th>Typ</th><th class="num">Referenz</th><th class="num">vorhergesagt</th><th class="num">F1 strikt</th><th class="num">P überl.</th><th class="num">R überl.</th><th class="num">F1 überl.</th></tr></thead>
<tbody>{type_rows(after)}</tbody></table></div>
<p class="muted">Organisationen: nur {after['metrics']['strict']['ORG']['gold']} Referenzen – dafür ist die Stichprobe zu klein für eine Aussage.
Aggregation <code>first</code> (wortgenau) statt <code>simple</code>: F1 strikt {de(after['metrics']['strict']['all']['f1'])} gegenüber {de(simple['metrics']['strict']['all']['f1'])},
aber kein Treffer endet mitten im Wort – Voraussetzung für TEI-Markup.</p>

<h3>Integrität auf den unveränderten Briefen</h3>
<div class="panel table"><table><thead><tr><th>Prüfung (40 Originalbriefe)</th><th class="num">v0.1</th><th class="num">v0.2</th></tr></thead><tbody>
<tr><td>neue Namen gesamt (inline)</td><td class="num">{old['new_inline']}</td><td class="num">{new['new_inline']}</td></tr>
<tr><td>… davon an unzulässiger Stelle (Referenz der Edition, Kommentar, Streichung oder <code>&lt;c&gt;</code>)</td><td class="num">{old['affected']}</td><td class="num">{new['affected']}</td></tr>
<tr><td>… … in bestehender Personen-/Orts-/Organisationsreferenz</td><td class="num">{old['in_existing_name_reference']}</td><td class="num">{new['in_existing_name_reference']}</td></tr>
<tr><td>… … in Kommentar <code>&lt;note&gt;</code></td><td class="num">{old['in_note']}</td><td class="num">{new['in_note']}</td></tr>
<tr><td>… … in beidem zugleich</td><td class="num">{old['in_reference_and_note']}</td><td class="num">{new['in_reference_and_note']}</td></tr>
<tr><td>Briefe mit verändertem Lesetext</td><td class="num">{old['reading_text_changed']}</td><td class="num">{new['reading_text_changed']}</td></tr>
<tr><td>Briefe mit verändertem vorhandenem Markup</td><td class="num">{old['markup_changed']}</td><td class="num">{new['markup_changed']}</td></tr>
</tbody></table></div>

<h2>Wie die Zahlen zu lesen sind</h2>
<div class="panel">
<p><b>Wo die falschen Treffer liegen.</b> Im ganzen Korpus liegen {fp_frame} der {sum(fp.values())} falschen Treffer von v0.2 außerhalb von Absätzen –
in Adressen, Grußformeln, Unterschriften und Briefköpfen.</p>
<p><b>Was eine Stichprobe dazu zeigt.</b> In {sc['letters']} Briefen wurde nach Namen gesucht, die die Edition nicht auszeichnet. Gefunden wurden {sc['unannotated_names_listed']},
fast alle Korrespondenzpartner in Adressen, Anreden und Unterschriften; die Edition verzeichnet sie in den Metadaten (<code>correspDesc</code>).
Von den {sc['unmatched']} Vorhersagen dieser Briefe, die nicht exakt der Referenz entsprechen, sind {sc['unmatched_equal_to_listed_name']} genau ein solcher Name
und {sc['unmatched_overlapping_listed_name']} überlappen einen. Das gilt für diese zehn Briefe; die Hauptzahlen bleiben unbereinigt.</p>
<p><b>Grenzen folgen anderen Richtlinien.</b> Das Modell ist nach den <a href="https://doi.org/10.5281/zenodo.3604227">Impresso-Annotationsrichtlinien</a> trainiert,
die Titel und Funktionen zur Personennennung zählen („Dr Hoffmann“); die Edition zeichnet nur den Namen aus. Umgekehrt fasst die Edition
Adressen als einen Ort („Wien, IX. Frankg. 1.“), das Modell trennt. Deshalb werden strikte und überlappende Werte getrennt berichtet.</p>
<p class="muted">Stichprobe: Vorprüfung durch zwei unabhängige, KI-gestützte Lesedurchgänge je Brief, Abweichungen durch eine dritte Prüfung entschieden;
eine menschliche Bestätigung steht aus. Liste: <a href="{REPO_URL}/blob/main/eval/spotcheck.tsv">eval/spotcheck.tsv</a>.</p>
</div>

<h2>Drei belegte Fehlerfälle</h2>
<div class="panel">{cases_html(after)}</div>

<h2>Reproduzieren</h2>
<pre>pip install -e . -r eval/requirements.txt
git worktree add ../tcb-v0.1 e09fa38     # Ausgangsstand für den Vergleich
sh eval/reproduce.sh                      # alle Zahlen dieser Seite
python scripts/build_docs.py              # diese Seite</pre>
<p class="muted">Methode, Auswahlregel, Lizenz und alle Kennzahlen: <a href="{REPO_URL}/blob/main/eval/README.md">eval/README.md</a>.
Vokabular der wenigen eigenen Terme: <a href="vocab/">tcb:</a>.</p>
"""
    html = page("Namen in TEI-Briefen nachvollziehbar anreichern",
                "Ein Werkzeug, das historische Briefeditionen um Personen, Orte und Organisationen ergänzt, Lesetext und vorhandene Textauszeichnung bewahrt, "
                "Aussagen und Vorschläge mit Herkunft ablegt und sich an einer echten Edition messen lässt.", body, nav=nav)
    redirect = ('<!doctype html><meta charset="utf-8"><title>TEI CRM Bridge</title>'
                '<meta http-equiv="refresh" content="0; url=example/letter.html"><a href="example/letter.html">Beispielbrief</a>\n')
    return {str(DOCS / "index.html"): html.encode("utf-8"), str(DOCS / "letter.html"): redirect.encode("utf-8")}


# README -----------------------------------------------------------------------

def readme_section() -> str:
    before, after = load("v0.1-hf"), load("v0.2-hf")
    old, new = load("integrity_v0.1-hf-original"), load("integrity_v0.2-hf-original")
    fp = after["errors_by_block_type"]["spurious"]
    lines = [
        README_START,
        f"Gemessen an {after['corpus']['letters']} Briefen der Schnitzler-Edition ({after['corpus']['gold']} redaktionelle Referenzen), "
        "gleiche Eingaben und gleiches Modell für beide Versionen:",
        "",
        "| | v0.1 | v0.2 |",
        "| --- | ---: | ---: |",
    ]
    for scope, name in (("metrics_v01_scope", "nur Text in `<p>`"), ("metrics", "alle Blöcke")):
        for mode, label in (("strict", "strikt"), ("overlap", "überlappend")):
            a, b = before[scope][mode]["all"], after[scope][mode]["all"]
            lines.append(f"| {name}, {label}: F1 (P / R) | {de(a['f1'])} ({de(a['precision'])} / {de(a['recall'])}) | {de(b['f1'])} ({de(b['precision'])} / {de(b['recall'])}) |")
    lines += [
        f"| neue Namen an unzulässiger Stelle (Originalbriefe) | {old['affected']} von {old['new_inline']} | {new['affected']} von {new['new_inline']} |",
        f"| Briefe mit verändertem Lesetext / Markup | {old['reading_text_changed']} / {old['markup_changed']} | {new['reading_text_changed']} / {new['markup_changed']} |",
        "",
        "Im Text, den v0.1 las (`<p>`), steigen Präzision und F1. Über alle Blöcke steigt der Recall, die strikte Präzision sinkt: "
        f"v0.2 liest auch Adressen, Briefköpfe und Grußformeln, und {sum(c for n, c in fp.items() if n != 'p')} seiner {sum(fp.values())} falschen Treffer liegen dort. "
        "Wie viele davon nicht annotierte Namen sind, zeigt eine Stichprobe von zehn Briefen ([eval/README.md](eval/README.md)).",
        README_END,
    ]
    return "\n".join(lines)


def build_readme() -> dict[str, bytes]:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    start, end = text.index(README_START), text.index(README_END) + len(README_END)
    return {str(path): (text[:start] + readme_section() + text[end:]).encode("utf-8")}


def _differs(path: Path, content: bytes) -> bool:
    """Byte comparison; Turtle is compared as a graph because serializers differ between rdflib versions."""
    if not path.exists():
        return True
    if path.read_bytes() == content:
        return False
    if path.suffix == ".ttl":
        from rdflib.compare import isomorphic

        return not isomorphic(Graph().parse(data=content, format="turtle"), Graph().parse(path, format="turtle"))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--with-model", action="store_true", help="also rebuild the Schnitzler letter with the NER model")
    parser.add_argument("--check", action="store_true", help="exit 1 if a generated file is out of date")
    args = parser.parse_args()
    files: dict[str, bytes] = {}
    files.update(build_demo(ROOT / "examples" / "letter.xml", "example", GlossaryRecognizer(ROOT / "examples" / "glossary.json")))
    if args.with_model:
        files.update(build_real_letter())
    files.update(build_vocabulary())
    files.update(build_index())
    files.update(build_readme())
    stale = [path for path, content in files.items() if _differs(Path(path), content)]
    if args.check:
        problems = [f"out of date: {Path(p).relative_to(ROOT)}" for p in stale]
        problems += check_real_letter()
        problems += check_annotations(DOCS / "example" / "letter.ttl", DOCS / "example" / "letter.enriched.xml",
                                      f"{PAGES_URL}example/letter.enriched.xml")
        if problems:
            print("\n".join(problems))
            sys.exit(1)
        print("docs are up to date; demo provenance, integrity and annotation targets verified")
        return
    for path, content in files.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(content)
    for obsolete in (DOCS / "letter.enriched.xml", DOCS / "letter.ttl"):
        obsolete.unlink(missing_ok=True)
    print(f"{len(stale)} of {len(files)} files updated")


if __name__ == "__main__":
    main()
