"""Standalone, dependency-free HTML preview of enriched TEI."""

from __future__ import annotations

from html import escape
from pathlib import Path

from lxml import etree

from .core import NS, REVERSE_TAGS, TEI, TEI_URI, Result


def _render(element: etree._Element) -> str:
    pieces = [escape(element.text or "")]
    for child in element:
        if not isinstance(child.tag, str):
            continue
        name = etree.QName(child).localname
        kind = REVERSE_TAGS.get(name) if etree.QName(child).namespace == TEI_URI else None
        if kind:
            content = _render(child)
            pieces.append(f'<mark class="entity {kind.lower()}" data-kind="{kind}" title="{kind}">{content}</mark>')
        elif child.tag == TEI + "lb":
            pieces.append("<br>")
        elif child.tag == TEI + "hi":
            pieces.append(f"<em>{_render(child)}</em>")
        else:
            pieces.append(_render(child))
        pieces.append(escape(child.tail or ""))
    return "".join(pieces)


def write_preview(xml_path: Path, ttl_path: Path, output_path: Path, result: Result, engine: str) -> None:
    tree = etree.parse(str(xml_path), etree.XMLParser(resolve_entities=False, no_network=True))
    root = tree.getroot()
    title_node = root.find("./" + TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "title")
    title = "".join(title_node.itertext(with_tail=False)).strip() if title_node is not None else xml_path.stem
    paragraphs = "\n".join(
        "<p>" + _render(node) + "</p>"
        for node in root.xpath(".//tei:body//tei:p", namespaces=NS)
    )
    event_cards = []
    for action in root.xpath(".//tei:correspAction[@type='sent']", namespaces=NS):
        fields = []
        for node in action:
            if not isinstance(node.tag, str):
                continue
            local = etree.QName(node).localname
            if local in {"persName", "orgName", "placeName", "date"}:
                label = {"persName": "Person", "orgName": "Organisation", "placeName": "Ort", "date": "Datum"}[local]
                fields.append(f"<div><dt>{label}</dt><dd>{escape(''.join(node.itertext(with_tail=False)).strip())}</dd></div>")
        event_cards.append('<article class="event"><h3>Versand</h3><dl>' + "".join(fields) + "</dl></article>")
    event_html = "\n".join(event_cards) or '<p class="muted">Keine expliziten Versandereignisse in den TEI-Metadaten.</p>'
    safe_title = escape(title)
    safe_engine = escape(engine)
    html = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} · TEI CRM Bridge</title>
<style>
:root{{--ink:#172a2d;--muted:#577073;--paper:#f6f4ed;--line:#d8ddd7;--accent:#0c615c}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,sans-serif}}
header{{background:#173b3b;color:#fff;padding:2.4rem max(1.5rem,calc((100vw - 1080px)/2))}}
header .eyebrow{{text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;color:#b5d4ce}}h1{{font:normal clamp(2rem,4vw,3.2rem)/1.12 Georgia,serif;margin:.55rem 0}}
header p{{color:#d5e6e1;max-width:62ch}}main{{max-width:1080px;margin:auto;padding:2rem 1.5rem 4rem;display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:2rem}}
section{{min-width:0}}.panel{{background:white;border:1px solid var(--line);border-radius:14px;padding:1.5rem;box-shadow:0 5px 24px #18362d0a}}
h2{{font:normal 1.5rem Georgia,serif;margin:.1rem 0 1rem}}h3{{margin:.1rem 0 .75rem;font-size:1rem}}
.toolbar{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem}}button{{cursor:pointer;background:#fff;border:1px solid var(--line);border-radius:999px;padding:.42rem .85rem;color:var(--ink)}}button.active{{background:var(--accent);border-color:var(--accent);color:white}}
.document{{font:1.1rem/1.9 Georgia,serif}}.document p{{margin:0 0 1rem}}
mark{{padding:.08rem .16rem;border-radius:4px;color:inherit}}mark.per{{background:#f8dfb4}}mark.loc{{background:#c8e8dc}}mark.org{{background:#dcd5ef}}mark.dimmed{{background:transparent;outline:1px dotted #bcc8c6}}
.stats{{display:grid;grid-template-columns:repeat(2,1fr);gap:.6rem;margin-bottom:1rem}}.stats div{{border:1px solid var(--line);border-radius:10px;padding:.6rem}}.stats strong{{display:block;font-size:1.35rem}}.stats span,.muted{{color:var(--muted);font-size:.88rem}}
dl{{margin:0}}dl div{{display:grid;grid-template-columns:90px 1fr;gap:.5rem;border-top:1px solid var(--line);padding:.5rem 0}}dt{{color:var(--muted)}}dd{{margin:0}}.links a{{display:inline-block;margin:.5rem .7rem .3rem 0;color:var(--accent)}}footer{{max-width:1080px;margin:auto;padding:0 1.5rem 2rem;color:var(--muted);font-size:.85rem}}
@media(max-width:760px){{main{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div class="eyebrow">TEI → CIDOC CRM → RDF</div><h1>{safe_title}</h1><p>Nachvollziehbare Entitäten und explizite Korrespondenzmetadaten aus einem TEI-Dokument. Erkennung: {safe_engine}.</p></header>
<main><section><div class="toolbar" aria-label="Entitätstyp filtern"><button class="active" data-filter="ALL">Alle</button><button data-filter="PER">Personen</button><button data-filter="LOC">Orte</button><button data-filter="ORG">Organisationen</button></div><div class="panel document"><h2>Text</h2>{paragraphs}</div></section>
<aside><div class="panel"><h2>Überblick</h2><div class="stats"><div><strong>{result.paragraphs}</strong><span>Absätze</span></div><div><strong>{result.new_annotations}</strong><span>Neue Markierungen</span></div><div><strong>{result.existing_annotations}</strong><span>TEI-Markierungen</span></div><div><strong>{result.events}</strong><span>Explizite Ereignisse</span></div></div><p class="muted">NER-Treffer sind Vorschläge. Gleiche Namen sind noch nicht als historische Identitäten geprüft.</p><div class="links"><a href="{escape(xml_path.name, quote=True)}">TEI XML</a><a href="{escape(ttl_path.name, quote=True)}">RDF Turtle</a></div></div><div class="panel" style="margin-top:1rem"><h2>Korrespondenz</h2>{event_html}</div></aside></main>
<footer>TEI CRM Bridge · Fiktive Demonstrationsdaten · HTML-Vorschau für die Begutachtung</footer>
<script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{{document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.entity').forEach(el=>el.classList.toggle('dimmed',button.dataset.filter!=='ALL'&&el.dataset.kind!==button.dataset.filter));}}));</script>
</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
