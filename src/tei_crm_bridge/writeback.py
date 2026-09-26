"""Write recognized names back into TEI without disturbing existing markup.

A name becomes an inline ``persName``/``placeName``/``orgName`` only if it lies
in one XML text slot whose element may contain names. Everything else stays a
stand-off mention (recorded in RDF and the mentions file). ``verify`` proves
that the only change to the tree is the added wrappers.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field

from lxml import etree

from .ner import Entity
from .projection import TEI, Projection, Reading, find_blocks, local_name, project

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TAGS = {"PER": "persName", "LOC": "placeName", "ORG": "orgName"}
#: Elements whose content model does not allow names (TEI P5).
NO_NAMES_INSIDE = frozenset({"c", "g", "pc", "w", "m", "idno"})
APPLICATION = "tei-crm-bridge"


class IntegrityError(RuntimeError):
    """Enrichment changed the text or existing markup."""


@dataclass
class Mention:
    block: int
    projection: Projection
    start: int
    end: int
    kind: str
    origin: str  # "editorial" (existing TEI) or "automatic"
    source: str
    score: float | None = None
    element: etree._Element | None = None  # None: stand-off only
    entities: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    this_run: bool = True  # False for suggestions recorded by an earlier run

    @property
    def text(self) -> str:
        return self.projection.text[self.start:self.end]


class IdMinter:
    """Fresh ``xml:id`` values that do not collide with the document's own."""

    def __init__(self, root: etree._Element, prefix: str = "tcb"):
        self.taken = {node.get(XML_ID) for node in root.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
        self.prefix = prefix
        self.counter = 0

    def reserve(self, wanted: str) -> str:
        candidate, number = wanted, 1
        while candidate in self.taken:
            number += 1
            candidate = f"{wanted}-{number}"
        self.taken.add(candidate)
        return candidate

    def next(self) -> str:
        while True:
            self.counter += 1
            candidate = f"{self.prefix}-n{self.counter}"
            if candidate not in self.taken:
                self.taken.add(candidate)
                return candidate


def place(projection: Projection, block: int, entities: list[Entity], ids: IdMinter) -> list[Mention]:
    """Wrap single-slot entities in new name elements; return all as mentions."""
    mentions, slots = [], defaultdict(list)
    for entity in entities:
        mention = Mention(block, projection, entity.start, entity.end, entity.kind, "automatic", entity.source, entity.score)
        segment = projection.single_segment(entity.start, entity.end)
        parent = None
        if segment is not None:
            parent = segment.owner if segment.slot == "text" else segment.owner.getparent()
        if parent is None or local_name(parent) is None or local_name(parent) in NO_NAMES_INSIDE:
            mentions.append(mention)  # across elements, in c/g/…, or in foreign-namespace content
        else:
            slots[(segment.owner, segment.slot)].append((mention, segment))
    for (owner, slot), items in slots.items():
        _split(owner, slot, items, ids)
        mentions += [mention for mention, _ in items]
    return sorted(mentions, key=lambda m: (m.start, m.end))


def _split(owner: etree._Element, slot: str, items: list, ids: IdMinter) -> None:
    """Split one ``text`` or ``tail`` slot around the mentions it holds."""
    items.sort(key=lambda item: item[0].start)
    segment = items[0][1]
    text = getattr(owner, slot)
    parent = owner if slot == "text" else owner.getparent()
    index = 0 if slot == "text" else parent.index(owner) + 1
    shift = segment.offset - segment.start
    local = [(mention, mention.start + shift, mention.end + shift) for mention, _ in items]
    setattr(owner, slot, text[:local[0][1]] or None)
    for position, (mention, start, end) in enumerate(local):
        node = etree.Element(TEI + TAGS[mention.kind])
        node.set(XML_ID, ids.next())
        node.text = text[start:end]
        following = local[position + 1][1] if position + 1 < len(local) else len(text)
        node.tail = text[end:following] or None
        parent.insert(index, node)
        index += 1
        mention.element = node


def unwrap(node: etree._Element) -> None:
    """Replace ``node`` by its content, keeping every character in place."""
    parent = node.getparent()
    index = parent.index(node)
    previous = node.getprevious()
    leading, tail = node.text or "", node.tail or ""
    if previous is not None:
        previous.tail = (previous.tail or "") + leading or None
    else:
        parent.text = (parent.text or "") + leading or None
    children = list(node)
    for offset, child in enumerate(children):
        parent.insert(index + offset, child)
    if children:
        children[-1].tail = (children[-1].tail or "") + tail or None
    elif previous is not None:
        previous.tail = (previous.tail or "") + tail or None
    else:
        parent.text = (parent.text or "") + tail or None
    parent.remove(node)


def verify(original: etree._Element, enriched: etree._Element, added: list[etree._Element], reading: Reading) -> None:
    """Raise unless the reading text is unchanged and removing ``added`` restores ``original``."""
    before = [project(block, reading).text for block in find_blocks(original)]
    after = [project(block, reading).text for block in find_blocks(enriched)]
    if before != after:
        raise IntegrityError("the projected reading text changed")
    wanted = {node.get(XML_ID) for node in added}
    clone = copy.deepcopy(enriched)
    for node in [node for node in clone.iter() if isinstance(node.tag, str) and node.get(XML_ID) in wanted]:
        unwrap(node)
    if canonical(clone) != canonical(original):
        raise IntegrityError("existing elements, attributes or text changed")


def canonical(node: etree._Element) -> bytes:
    """C14N 2.0 serialization. (libxml2's C14N 1.0 mis-serializes namespaces under ``xml:base``.)"""
    return etree.tostring(node, method="c14n2", with_comments=True)


def add_application(root: etree._Element, xml_id: str, version: str, description: str) -> bool:
    """Document the processing run in ``encodingDesc/appInfo``; False without a ``teiHeader``."""
    header = root.find(TEI + "teiHeader")
    if header is None:
        return False
    encoding = header.find(TEI + "encodingDesc")
    if encoding is None:
        encoding = etree.Element(TEI + "encodingDesc")
        file_desc = header.find(TEI + "fileDesc")
        header.insert(header.index(file_desc) + 1 if file_desc is not None else 0, encoding)
    app_info = encoding.find(TEI + "appInfo")
    if app_info is None:
        app_info = etree.SubElement(encoding, TEI + "appInfo")
    application = etree.SubElement(app_info, TEI + "application", ident=APPLICATION, version=version)
    application.set(XML_ID, xml_id)
    etree.SubElement(application, TEI + "label").text = "TEI CRM Bridge"
    etree.SubElement(application, TEI + "desc").text = description
    etree.SubElement(application, TEI + "ptr", target="https://github.com/klausbehnamshad/tei-crm-bridge")
    return True


def earlier_run_ids(root: etree._Element) -> set[str]:
    """``xml:id`` values of applications recorded by earlier runs of this tool."""
    return {
        node.get(XML_ID) for node in root.iter(TEI + "application")
        if node.get("ident") == APPLICATION and node.get(XML_ID)
    }


def strip_enrichment(root: etree._Element, is_added=None) -> etree._Element:
    """Copy of an enriched document without this tool's additions (inverse of ``enrich`` on TEI).

    Name elements whose ``@resp`` points to a ``tei-crm-bridge`` application are
    unwrapped (or those for which ``is_added`` is true), and the applications are
    removed together with ``appInfo``/``encodingDesc`` containers left empty.
    """
    clone = copy.deepcopy(root)
    runs = {f"#{ident}" for ident in earlier_run_ids(clone)}
    added = [
        node for node in clone.iter()
        if local_name(node) in set(TAGS.values()) and (node.get("resp") in runs or (is_added is not None and is_added(node)))
    ]
    for node in reversed(added):
        unwrap(node)
    for application in [node for node in clone.iter(TEI + "application") if node.get("ident") == APPLICATION]:
        container = application.getparent()
        container.remove(application)
        while (container.getparent() is not None and len(container) == 0 and not (container.text or "").strip()
               and local_name(container) in {"appInfo", "encodingDesc"}):
            parent = container.getparent()
            parent.remove(container)
            container = parent
    return clone
