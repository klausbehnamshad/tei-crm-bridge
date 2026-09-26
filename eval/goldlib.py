"""Shared helpers for the evaluation: reference spans, stripping and features.

Reference annotation ("gold"): editorial ``persName``/``placeName``/``orgName``
and ``rs``/``name`` with ``@type`` person, place or org inside the projected
reading text (see ``tei_crm_bridge.projection``). Excluded, and counted:

* ``@subtype="implied"``: implicit references such as "er" or "der Onkel",
  which are not proper names and not an NER target;
* references nested in another PER/LOC/ORG reference (the model output is flat,
  the outermost reference is kept).

Spans are trimmed of whitespace on both sides, for gold and predictions alike.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass

from lxml import etree

from tei_crm_bridge.projection import TEI, find_blocks, local_name, name_kind, project

KINDS = ("PER", "LOC", "ORG")
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


@dataclass(frozen=True, order=True)
class Span:
    letter: str
    block: int
    start: int
    end: int
    kind: str
    text: str

    def overlaps(self, other: "Span") -> bool:
        return (self.letter, self.block) == (other.letter, other.block) and self.start < other.end and other.start < self.end

    def as_dict(self) -> dict:
        return asdict(self)


def trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def gold_spans(letter: str, root: etree._Element) -> tuple[list[Span], dict[str, int], list[str]]:
    """Outermost, non-implied PER/LOC/ORG references per block plus exclusion counts."""
    spans: list[Span] = []
    excluded = {"implied": 0, "nested": 0}
    texts = []
    for index, block in enumerate(find_blocks(root)):
        projection = project(block)
        texts.append(projection.text)
        typed = [item for item in projection.annotations if item.kind in KINDS]
        for item in typed:
            if item.element.get("subtype") == "implied":
                excluded["implied"] += 1
                continue
            if any(item.element in set(outer.element.iterdescendants()) for outer in typed if outer is not item):
                excluded["nested"] += 1
                continue
            start, end = trim(projection.text, item.start, item.end)
            if start < end:
                spans.append(Span(letter, index, start, end, item.kind, projection.text[start:end]))
    return sorted(spans), excluded, texts


def _unwrap(node: etree._Element) -> None:
    """Replace ``node`` by its content, keeping every character in place."""
    parent = node.getparent()
    index = parent.index(node)
    previous = node.getprevious()
    leading = node.text or ""
    if previous is not None:
        previous.tail = (previous.tail or "") + leading
    else:
        parent.text = (parent.text or "") + leading
    children = list(node)
    for offset, child in enumerate(children):
        parent.insert(index + offset, child)
    tail = node.tail or ""
    if children:
        children[-1].tail = (children[-1].tail or "") + tail
    elif previous is not None:
        previous.tail = (previous.tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail
    parent.remove(node)


def strip_references(root: etree._Element) -> etree._Element:
    """Copy of ``root`` without PER/LOC/ORG references in ``body``; everything else stays."""
    stripped = copy.deepcopy(root)
    for body in stripped.iter(TEI + "body"):
        targets = [node for node in body.iter() if isinstance(node.tag, str) and name_kind(node) in KINDS]
        for node in reversed(targets):  # innermost first
            _unwrap(node)
    return stripped


def features(root: etree._Element) -> list[str]:
    """TEI features present in the body, for the corpus manifest."""
    found = set()
    for body in root.iter(TEI + "body"):
        for node in body.iter():
            name = local_name(node)
            if name in {"c", "note", "choice", "hi", "lb", "pb", "space", "del", "add", "address", "opener", "closer", "postscript", "unclear", "gap"}:
                found.add(name)
            if name == "rs" and node.get("subtype") == "implied":
                found.add("rs-implied")
            if name_kind(node) and any(name_kind(ancestor) for ancestor in node.iterancestors()):
                found.add("nested-reference")
    for action in root.iter(TEI + "correspAction"):
        found.add(f"corresp-{action.get('type')}")
        for date in action.iter(TEI + "date"):
            if date.get("notBefore") or date.get("notAfter"):
                found.add("date-interval")
    return sorted(found)
