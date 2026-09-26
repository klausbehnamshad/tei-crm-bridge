"""TEI enrichment and conservative CIDOC CRM export."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from . import __version__
from .ner import Entity, Recognizer, resolve_overlaps
from .projection import TEI, TEI_URI, Projection, Reading, find_blocks, project, xpath_of
from .rdf import GraphBuilder, valid_iri
from .writeback import IdMinter, Mention, add_application, earlier_run_ids, place, verify

#: Internal DTD entities are expanded; external ones are never loaded (no XXE, no network).
PARSER = etree.XMLParser(resolve_entities="internal", no_network=True, load_dtd=False)
#: Words that are no name on their own (a model span often starts with them in addresses).
HONORIFICS = frozenset({
    "an", "a", "à", "herr", "herrn", "hrn", "hr", "frau", "fr", "frl", "fräulein", "dr", "prof", "doctor",
    "monsieur", "madame", "mme", "mlle", "m", "mr", "mrs", "ms", "sehr", "geehrter", "geehrte", "hochgeehrter",
    "wohlgeboren", "hochwohlgeboren", "baron", "graf", "gräfin", "hofrat", "hofrath",
})
_ROMAN = re.compile(r"^[ivxlcdm]+$")


@dataclass(frozen=True)
class Result:
    blocks: int
    editorial: int
    earlier: int  # suggestions from an earlier run found in the input
    inline: int
    standoff: int
    events: int
    triples: int
    warnings: tuple[str, ...]


def _strip(entity: Entity, text: str) -> Entity | None:
    start, end = entity.start, entity.end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Entity(start, end, entity.kind, entity.score, entity.source) if start < end else None


def _is_name(surface: str) -> bool:
    words = [word for word in re.split(r"[\s.,;:()]+", surface.casefold()) if word]
    return any(len(word) > 1 and word not in HONORIFICS and not _ROMAN.match(word) for word in words)


def _pieces(entity: Entity, projection: Projection) -> list[Entity]:
    """Split a span at line boundaries between TEI lines; keep only pieces that look like names."""
    text, cuts = projection.text, [entity.start]
    for position in range(entity.start, entity.end):
        if text[position] == "\n" and projection.segment_at(position) is None:
            cuts += [position, position + 1]
    cuts.append(entity.end)
    pieces = []
    for start, end in zip(cuts[::2], cuts[1::2], strict=True):
        piece = _strip(Entity(start, end, entity.kind, entity.score, entity.source), text)
        if piece and (len(cuts) == 2 or _is_name(text[piece.start:piece.end])):
            pieces.append(piece)
    return pieces


def _parse(input_path: Path) -> etree._ElementTree:
    tree = etree.parse(str(input_path), PARSER)
    if tree.getroot().tag != TEI + "TEI":
        raise ValueError("Input must have a TEI P5 root in the official namespace")
    for node in tree.getroot().iter():
        if isinstance(node, etree._Entity):
            raise ValueError(f"{input_path}: entity {node.text} is not declared in the document; expand it before processing")
    return tree


def enrich(
    input_path: Path,
    output_tei: Path,
    output_ttl: Path,
    recognizer: Recognizer,
    base_uri: str,
    threshold: float = 0.85,
    *,
    reading: Reading = "edited",
    output_json: Path | None = None,
    tei_url: str | None = None,
    source_url: str | None = None,
) -> Result:
    """Enrich one TEI file. ``tei_url`` is where the enriched TEI will be published
    (the source of every annotation target); ``source_url`` identifies the input."""
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if not base_uri.startswith(("https://", "http://")):
        raise ValueError("base URI must be an HTTP(S) URI")
    for url in (tei_url, source_url):
        if url is not None and not valid_iri(url):
            raise ValueError(f"not an absolute IRI: {url!r}")
    base_uri = base_uri.rstrip("/") + "/"
    raw_input = input_path.read_bytes()
    tree = _parse(input_path)
    root = tree.getroot()
    doc_id = root.get("{http://www.w3.org/XML/1998/namespace}id") or input_path.stem
    original = copy.deepcopy(root)
    warnings: list[str] = []
    builder = GraphBuilder(root, doc_id, base_uri, warnings, tei_url=tei_url, source_url=source_url)
    events = builder.add_correspondence()  # first, so correspondents keep their full names as labels
    ids = IdMinter(root)
    application_id = ids.reserve("tcb-run") if root.find(TEI + "teiHeader") is not None else None
    earlier = {f"#{ident}" for ident in earlier_run_ids(root)}

    blocks = find_blocks(root)
    projections = [project(block, reading) for block in blocks]  # all before any writeback
    mentions: list[Mention] = []
    for index, projection in enumerate(projections):
        for item in projection.annotations:
            span = _strip(Entity(item.start, item.end, item.kind or "", None, "tei"), projection.text) if item.kind else None
            if span is None:
                continue
            label = " ".join(projection.text[span.start:span.end].split())
            if item.element.get("resp") in earlier:  # a suggestion of an earlier run stays a suggestion
                mention = Mention(index, projection, span.start, span.end, item.kind, "automatic", "tei-crm-bridge (earlier run)",
                                  _score(item.element.get("cert")), element=item.element, this_run=False)
                reference = item.element.get("ref") or ""
                mention.entities = [str(builder.candidate(item.kind, label, reference if valid_iri(reference) else None))]
            else:
                mention = Mention(index, projection, span.start, span.end, item.kind, "editorial", "tei", element=item.element)
                entities, mention.refs, mention.unresolved = builder.entities_for(item.element, item.kind, label)
                mention.entities = [str(entity) for entity in entities]
            mentions.append(mention)
    for index, projection in enumerate(projections):
        found = recognizer.find(projection.text) if projection.text.strip() else []
        pieces = [piece for item in found for piece in _pieces(item, projection)]
        free = [entity for entity in pieces if not projection.protected(entity.start, entity.end)]
        for mention in place(projection, index, resolve_overlaps(free, projection.text, threshold), ids):
            mention.entities = [str(builder.candidate(mention.kind, " ".join(mention.text.split())))]
            if mention.element is not None:
                mention.element.set("ref", mention.entities[0])
                if application_id:
                    mention.element.set("resp", "#" + application_id)
                if mention.score is not None:
                    mention.element.set("cert", f"{mention.score:.4f}".rstrip("0").rstrip("."))
            mentions.append(mention)

    new = [m for m in mentions if m.origin == "automatic" and m.this_run]
    verify(original, root, [m.element for m in new if m.element is not None], reading)
    settings = settings_of(recognizer, threshold, reading)
    if application_id:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(settings.items()))
        add_application(root, application_id, __version__, f"Automatische Namenserkennung ({summary}). Vorschläge, nicht geprüft.")
    run = builder.add_run(settings)
    mentions.sort(key=lambda m: (m.block, m.start, m.end))
    for number, mention in enumerate(mentions, start=1):
        builder.add_mention(number, mention, run if mention.this_run else None)

    # Serialize everything first, so a failure leaves no half-written output behind.
    record = _mentions_record(doc_id, input_path, raw_input, tei_url, source_url, settings, blocks, mentions, warnings)
    outputs = {
        output_tei: etree.tostring(tree, encoding="utf-8", xml_declaration=True),
        output_ttl: builder.graph.serialize(format="turtle").encode("utf-8"),
    }
    if output_json is not None:
        outputs[output_json] = (json.dumps(record, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return Result(
        blocks=len(blocks),
        editorial=sum(1 for m in mentions if m.origin == "editorial"),
        earlier=sum(1 for m in mentions if not m.this_run),
        inline=sum(1 for m in new if m.element is not None),
        standoff=sum(1 for m in new if m.element is None),
        events=events,
        triples=len(builder.graph),
        warnings=tuple(warnings),
    )


def _score(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def settings_of(recognizer: Recognizer, threshold: float, reading: str) -> dict:
    """Recognizer description plus pipeline settings; a score threshold only for scoring engines."""
    settings = {**recognizer.describe(), "reading": reading}
    if settings.get("engine") != "glossary":
        settings["threshold"] = threshold
    return settings


def _mentions_record(doc_id, input_path, raw_input, tei_url, source_url, settings, blocks, mentions, warnings) -> dict:
    return {
        "document": doc_id,
        "software": {"name": "tei-crm-bridge", "version": __version__},
        "input": {"file": input_path.name, "sha256": hashlib.sha256(raw_input).hexdigest(), "url": source_url},
        "tei_url": tei_url,
        "settings": settings,
        "blocks": [xpath_of(block) for block in blocks],
        "mentions": [
            {
                "id": number,
                "block": m.block,
                "start": m.start,
                "end": m.end,
                "text": m.text,
                "kind": m.kind,
                "origin": m.origin,
                "source": m.source,
                "score": m.score,
                "inline": m.element is not None,
                "xpath": xpath_of(m.element) if m.element is not None else None,
                "entities": m.entities,
                "refs": m.refs,
                "unresolved": m.unresolved,
            }
            for number, m in enumerate(mentions, start=1)
        ],
        "warnings": warnings,
    }


__all__ = ["Result", "enrich", "TEI", "TEI_URI"]
