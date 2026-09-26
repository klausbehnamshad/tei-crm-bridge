"""Standalone, dependency-free HTML preview of enriched TEI."""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

from lxml import etree

from . import __version__
from .core import PARSER, Result
from .dates import interval
from .projection import EXCLUDED, TEI, choose_alternative, find_blocks, is_line, local_name, name_kind, xpath_of
from .rdf import document_title
from .review import review_source
from .review_ui import SCRIPT

KIND_LABELS = {"PER": "Person", "LOC": "Ort", "ORG": "Organisation"}
EVENT_LABELS = {"sent": "Versand", "received": "Empfang"}


def _text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def safe_href(url: str | None) -> str | None:
    """``url`` if it is an http(s) link, else None (no javascript: or data: links from TEI data)."""
    if not url:
        return None
    try:
        return url.strip() if urlsplit(url.strip()).scheme.lower() in {"http", "https"} else None
    except ValueError:
        return None


def _link(url: str) -> str:
    href = safe_href(url)
    return f'<a href="{escape(href, quote=True)}">{escape(url)}</a>' if href else escape(url)


class _Renderer:
    def __init__(self, mentions: dict[str, dict], reading: str):
        self.mentions = mentions
        self.reading = reading

    def content(self, node: etree._Element) -> str:
        pieces = [escape(node.text or "")]
        for child in node:
            if isinstance(child.tag, str):
                pieces.append(self.element(child, local_name(node)))
            pieces.append(escape(child.tail or ""))
        return "".join(pieces)

    def element(self, node: etree._Element, parent: str | None) -> str:
        name = local_name(node)
        if name == "note":
            return f'<sup class="note" tabindex="0" title="Kommentar (nicht ausgewertet): {escape(_text(node), quote=True)}">K</sup>'
        if name in EXCLUDED:
            return f'<span class="excluded" title="{escape(name or "", quote=True)} – nicht Teil des Lesetexts">{self.content(node)}</span>'
        if name in {"choice", "app"}:
            chosen = choose_alternative(node, self.reading)
            others = " / ".join(_text(c) for c in node if isinstance(c.tag, str) and c is not chosen and local_name(c) != "note")
            inner = self.element(chosen, name) if chosen is not None else ""
            return f'<span class="choice" title="Alternative: {escape(others, quote=True)}">{inner}</span>'
        if name == "lb":
            return "" if node.get("break") == "no" else "<br>"
        if name in {"space", "pb", "cb"}:
            return "" if node.get("break") == "no" else " "
        if name == "gap":
            return '<span class="excluded" title="Lücke in der Überlieferung">[…]</span>'
        inner = self.content(node)
        kind = name_kind(node)
        if kind:
            info = self.mentions.get(xpath_of(node), {})
            origin = info.get("origin", "editorial")
            attributes = {
                "class": f"entity {kind.lower()} {origin}",
                "data-kind": kind,
                "data-origin": origin,
                "data-source": info.get("source") or "TEI-Edition",
                "data-entity": " ".join(info.get("entities") or []) or node.get("ref") or "",
                "data-score": "" if info.get("score") is None else f"{info['score']:.3f}",
                "data-text": info.get("text") or _text(node),
                "tabindex": "0",
            }
            if origin == "automatic" and "id" in info:
                attributes["data-mention-id"] = info["id"]
            rendered = " ".join(f'{key}="{escape(str(value), quote=True)}"' for key, value in attributes.items())
            return f"<mark {rendered}>{inner}</mark>"
        if name == "rs" or name == "name":
            return f'<span class="other-ref" title="{escape(node.get("type") or name, quote=True)}">{inner}</span>'
        if name == "hi":
            return f"<em>{inner}</em>"
        if is_line(node):
            return f'<span class="line">{inner}</span>'
        return inner


def _events(root: etree._Element) -> str:
    cards = []
    for action in root.iter(TEI + "correspAction"):
        kind = action.get("type") or ""
        rows = []
        for node in action:
            if not isinstance(node.tag, str):
                continue
            entity_kind = name_kind(node)
            if entity_kind:
                rows.append((KIND_LABELS[entity_kind], _text(node), node.get("ref")))
            elif local_name(node) == "date":
                try:
                    span = interval(node)
                except ValueError:
                    span = None
                bounds = f"{(span.begin or '…')[:10]} – {(span.end or '…')[:10]}" if span else "ohne maschinenlesbares Datum"
                rows.append(("Datum", f"{_text(node)} ({bounds})", None))
        mapped = kind in EVENT_LABELS
        body = "".join(
            f"<div><dt>{escape(label)}</dt><dd>{escape(value)}"
            + (f' <code>{escape(ref)}</code>' if ref else "") + "</dd></div>"
            for label, value, ref in rows
        )
        heading = EVENT_LABELS.get(kind, kind or "ohne Typ")
        note = "" if mapped else '<p class="muted">Typ nicht auf CIDOC CRM abgebildet.</p>'
        cards.append(f'<article class="event"><h3>{escape(heading)}</h3><dl>{body}</dl>{note}</article>')
    return "\n".join(cards) or '<p class="muted">Keine Korrespondenzmetadaten im teiHeader.</p>'


def _source(root: etree._Element) -> str:
    rows = []
    availability = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt/{TEI}availability")
    licence = availability.find(f"{TEI}licence") if availability is not None else None
    if licence is not None and licence.get("target"):
        rows.append(("Lizenz", _link(licence.get("target"))))
    publisher = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt/{TEI}publisher")
    if publisher is not None:
        rows.append(("Herausgabe", escape(_text(publisher))))
    series = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title[@level='s']")
    if series is not None:
        rows.append(("Edition", escape(_text(series))))
    for idno in root.iterfind(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt/{TEI}idno"):
        rows.append((idno.get("type") or "Kennung", _link(_text(idno))))
    if not rows:
        statement = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt")
        rows.append(("Quelle", escape(_text(statement)) if statement is not None else "–"))
    if licence is not None:  # e.g. CC BY 4.0 requires indicating changes
        changes = ("Diese Fassung ist maschinell bearbeitet: ergänzte Namenselemente mit "
                   "<code>@resp</code> und Verarbeitungsvermerk in <code>appInfo</code>. "
                   "Der Lesetext ist unverändert; die ursprüngliche Auszeichnung im "
                   "<code>body</code> ist nach Entfernen der Ergänzungen wiederherstellbar.")
        schema_location = root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation") or ""
        if "raw.githubusercontent.com/arthur-schnitzler/schnitzler-briefe-data/" in schema_location:
            changes += " Für die veröffentlichte Schnitzler-Fassung wurden die Schema-Verweise absolut gesetzt."
        rows.append(("Änderungen", changes))
    return "".join(f"<div><dt>{escape(label)}</dt><dd>{value}</dd></div>" for label, value in rows)


#: The page runs only its own script; links and data from TEI cannot inject code.
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
       f"script-src 'sha256-{base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()}'")


def write_preview(xml_path: Path, ttl_path: Path, mentions_path: Path, output_path: Path, result: Result) -> None:
    root = etree.parse(str(xml_path), PARSER).getroot()
    record = json.loads(mentions_path.read_text(encoding="utf-8"))
    review_data = {
        "source": review_source(record, mentions_path, ttl_path),
        "mentions": [
            {key: m[key] for key in ("id", "block", "start", "end", "text", "kind", "source", "score", "entities")}
            for m in record["mentions"] if m["origin"] == "automatic"
        ],
    }
    review_json = json.dumps(review_data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    settings = record["settings"]
    inline = {m["xpath"]: m for m in record["mentions"] if m["xpath"]}
    renderer = _Renderer(inline, settings.get("reading", "edited"))
    blocks = "\n".join(
        f'<div class="block {escape(local_name(block) or "")}">{renderer.content(block)}</div>'
        for block in find_blocks(root)
    )
    standoff_items = []
    for m in record["mentions"]:
        if m["inline"]:
            continue
        score = "" if m["score"] is None else f", Score {m['score']:.3f}"
        where = f"Block {m['block'] + 1}, Zeichen {m['start']}–{m['end']}{score}"
        surface = escape(" ".join(m["text"].split()))
        standoff_items.append(
            f'<li class="standoff-item"><button type="button" data-mention-id="{m["id"]}" '
            f'class="standoff-button"><span class="chip {m["kind"].lower()}">{m["kind"]}</span> '
            f'„{surface}“ <span class="muted">{where}</span> <span class="review-badge">Offen</span></button></li>'
        )
    standoff_html = "".join(standoff_items) or '<li class="muted">Keine – alle Treffer liegen in je einem Textknoten.</li>'
    provenance = "".join(f"<div><dt>{escape(str(key))}</dt><dd><code>{escape(str(value))}</code></dd></div>" for key, value in sorted(settings.items()))
    title = document_title(root, xml_path.stem)
    engine = "Glossar (deterministisch)" if settings.get("engine") == "glossary" else escape(str(settings.get("model", settings.get("engine"))))
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
    warnings_html = f'<h3 class="hint">Hinweise</h3><ul class="muted">{warnings}</ul>' if warnings else ""
    stats = [
        (result.blocks, "Textblöcke"), (result.editorial, "Namen der Edition"),
        (result.inline, "Vorschläge inline"), (result.standoff, "Vorschläge stand-off"), (result.events, "Korrespondenzereignisse"),
    ]
    if result.earlier:
        stats.append((result.earlier, "Vorschläge früherer Läufe"))
    stats_html = "".join(f"<div><strong>{value}</strong><span>{label}</span></div>" for value, label in stats)
    events_html, source_html = _events(root), _source(root)
    links = {"TEI XML": xml_path.name, "RDF Turtle": ttl_path.name, "Mentions JSON": mentions_path.name}
    links_html = "".join(f'<a href="{escape(quote(href), quote=True)}">{label}</a>' for label, href in links.items())
    review_command = "tei-crm-review " + " ".join(
        (mentions_path.name, ttl_path.name, f"{record['document']}.review.json", ttl_path.with_suffix(".reviewed.ttl").name)
    )
    ttl_href = escape(quote(ttl_path.name), quote=True)
    html = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<link rel="alternate" type="text/turtle" href="{ttl_href}" title="RDF Turtle">
<title>{escape(title)} · TEI CRM Bridge</title>
<style>
:root{{--ink:#172a2d;--muted:#577073;--paper:#f6f4ed;--panel:#fff;--line:#d8ddd7;--accent:#0c615c;--per:#f8dfb4;--loc:#c8e8dc;--org:#dcd5ef;--head:#173b3b}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--ink:#e4ece9;--muted:#9fb3af;--paper:#111a1b;--panel:#182324;--line:#2c3b3c;--accent:#6fc7bd;--per:#5a4521;--loc:#1f4a3d;--org:#3c3462;--head:#0c2020}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,sans-serif}}
header{{background:var(--head);color:#fff;padding:2.2rem max(1rem,calc((100vw - 1120px)/2))}}header .eyebrow{{text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;color:#b5d4ce}}
h1{{font:normal clamp(1.7rem,3.6vw,2.8rem)/1.15 Georgia,serif;margin:.5rem 0}}header p{{color:#d5e6e1;max-width:70ch;margin:.3rem 0}}header a{{color:#b5f0e6}}
main{{max-width:1120px;margin:auto;padding:1.6rem 1rem 3rem;display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:1.5rem}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:1.25rem;margin-bottom:1rem;overflow-wrap:anywhere}}
h2{{font:normal 1.35rem Georgia,serif;margin:0 0 .8rem}}h3{{margin:.1rem 0 .5rem;font-size:1rem}}
.toolbar{{display:flex;flex-wrap:wrap;gap:.45rem;margin-bottom:.8rem}}button{{cursor:pointer;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:.38rem .8rem;color:var(--ink);font:inherit;font-size:.9rem}}button[aria-pressed="true"]{{background:var(--accent);border-color:var(--accent);color:var(--paper)}}
.document{{font:1.08rem/1.85 Georgia,serif}}.block{{margin:0 0 1rem}}.block.opener,.block.closer,.block.address,.block.dateline,.block.salute,.block.signed{{color:var(--ink);font-style:normal}}.line{{display:block}}
mark{{padding:.05rem .15rem;border-radius:4px;color:inherit;cursor:pointer}}mark.per{{background:var(--per)}}mark.loc{{background:var(--loc)}}mark.org{{background:var(--org)}}
mark.automatic{{border-bottom:2px dashed var(--ink)}}mark.dimmed{{background:transparent;outline:1px dotted var(--line);border-bottom-color:transparent}}mark:focus{{outline:2px solid var(--accent)}}
mark[data-review-status="accepted"]{{box-shadow:inset 0 -3px #36835f}}mark[data-review-status="rejected"]{{box-shadow:inset 0 -3px #a35348;text-decoration:line-through}}
mark.selected,.standoff-button.selected{{outline:2px solid var(--accent);outline-offset:2px}}
.other-ref{{border-bottom:1px dotted var(--muted)}}.note{{color:var(--accent);cursor:help;font:600 .7rem system-ui;margin-left:.1rem}}.excluded{{color:var(--muted);text-decoration:line-through}}.choice{{border-bottom:1px dashed var(--muted)}}
.stats{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.5rem;margin-bottom:.8rem}}.stats div{{border:1px solid var(--line);border-radius:10px;padding:.5rem .6rem}}.stats strong{{display:block;font-size:1.3rem}}
.stats span,.muted{{color:var(--muted);font-size:.88rem}}dl{{margin:0}}dl div{{display:grid;grid-template-columns:minmax(80px,30%) 1fr;gap:.5rem;border-top:1px solid var(--line);padding:.4rem 0}}dt{{color:var(--muted)}}dd{{margin:0}}
code{{font-size:.82rem;overflow-wrap:anywhere}}a{{color:var(--accent)}}.links a{{display:inline-block;margin:.2rem .8rem .2rem 0}}ul{{padding-left:1.1rem;margin:.3rem 0}}
.chip{{display:inline-block;border-radius:6px;padding:0 .35rem;font-size:.75rem;font-weight:600}}.chip.per{{background:var(--per)}}.chip.loc{{background:var(--loc)}}.chip.org{{background:var(--org)}}
.hint{{margin-top:.8rem}}.legend{{display:flex;flex-wrap:wrap;gap:.8rem;font-size:.85rem;color:var(--muted);margin:.2rem 0 .8rem}}.legend mark{{cursor:default}}
.review-actions{{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.75rem}}.review-actions button[aria-pressed="true"]{{background:var(--accent);color:var(--paper)}}
label{{display:block;font-weight:600;font-size:.9rem;margin:.65rem 0 .2rem}}input[type="text"],textarea{{width:100%;font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:.4rem}}
textarea{{resize:vertical}}.review-tools{{display:flex;flex-wrap:wrap;gap:.5rem;margin:.7rem 0}}.file-label{{display:inline-block;margin:0;cursor:pointer;border:1px solid var(--line);border-radius:999px;padding:.38rem .8rem;font-weight:normal}}
.file-label input{{position:absolute;width:1px;height:1px;opacity:0}}.file-label:focus-within{{outline:2px solid var(--accent)}}
#review-message{{min-height:1.4em}}#review-message.error{{color:#a53b32}}.standoff-button{{display:inline;text-align:left;border:0;border-radius:4px;padding:.15rem .25rem}}.review-badge{{font-size:.78rem;color:var(--muted);margin-left:.4rem}}
.standoff-button[data-review-status="accepted"] .review-badge{{color:#26724b}}.standoff-button[data-review-status="rejected"] .review-badge{{color:#a53b32}}
footer{{max-width:1120px;margin:auto;padding:0 1rem 2rem;color:var(--muted);font-size:.85rem}}
@media(max-width:820px){{main{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div class="eyebrow">TEI → CIDOC CRM → RDF</div><h1>{escape(title)}</h1>
<p>Erkennung: {engine}. Namen der Edition bleiben unverändert; automatische Vorschläge sind gestrichelt unterstrichen und im Graphen als Annotation, nicht als Tatsache, abgelegt.</p></header>
<main><section>
<div class="toolbar" role="group" aria-label="Entitätstyp filtern">
<button aria-pressed="true" data-filter="ALL">Alle</button><button aria-pressed="false" data-filter="PER">Personen</button><button aria-pressed="false" data-filter="LOC">Orte</button><button aria-pressed="false" data-filter="ORG">Organisationen</button><button aria-pressed="false" data-filter="automatic">nur Vorschläge</button></div>
<div class="legend"><span><mark class="per">Edition</mark> redaktionell ausgezeichnet</span><span><mark class="per automatic">Vorschlag</mark> automatisch erkannt</span><span><span class="other-ref">Werk o. Ä.</span> andere Referenz</span><span><sup class="note">K</sup> Kommentar (nicht ausgewertet)</span></div>
<div class="panel document"><h2>Lesetext</h2>{blocks}</div>
<div class="panel"><h2>Stand-off-Vorschläge</h2><p class="muted">Treffer über Elementgrenzen werden nicht als Inline-Element eingefügt, sondern nur im Graphen (TextPositionSelector) und in der Mentions-Datei geführt. Zum Prüfen eine Fundstelle auswählen.</p><ul>{standoff_html}</ul></div>
</section>
<aside>
<div class="panel"><h2>Redaktionelle Prüfung</h2><p class="muted">Jeder automatische Vorschlag kann angenommen, abgelehnt oder offen gelassen werden. Diese Entscheidung ändert die TEI-Datei nicht.</p>
<p id="review-count" aria-live="polite">Lade Fundstellen …</p>
<label for="reviewer">Name oder Kürzel der prüfenden Person</label><input id="reviewer" type="text" maxlength="200" autocomplete="name">
<div class="review-tools"><button id="review-export" type="button">Review-Datei exportieren</button>
<label class="file-label">Review-Datei importieren<input id="review-import" type="file" accept=".json,application/json"></label></div>
<p id="review-message" class="muted" role="status" aria-live="polite"></p>
<p class="muted">Entscheidungen bleiben im Browser gespeichert. Für die Weitergabe bitte die JSON-Datei exportieren; sie enthält Name, Zeitpunkt und Prüfsummen.</p>
<p class="muted">Geprüften Graphen lokal erzeugen:<br><code>{escape(review_command)}</code></p></div>
<div class="panel" id="detail" aria-live="polite"><h2>Fundstelle</h2><p class="muted">Einen automatisch erkannten Namen oder Stand-off-Vorschlag auswählen.</p></div>
<div class="panel"><h2>Überblick</h2><div class="stats">{stats_html}</div>
<div class="links">{links_html}</div></div>
<div class="panel"><h2>Korrespondenz</h2>{events_html}</div>
<div class="panel"><h2>Quelle</h2><dl>{source_html}</dl></div>
<div class="panel"><h2>Verarbeitung</h2><dl>{provenance}</dl>{warnings_html}</div>
</aside></main>
<footer>TEI CRM Bridge {escape(__version__)} · Ausgangsgraph mit ungeprüften Vorschlägen · Geprüften Graphen lokal mit <code>tei-crm-review</code> erzeugen</footer>
<script id="review-data" type="application/json">{review_json}</script>
<script>{SCRIPT}</script>
</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
