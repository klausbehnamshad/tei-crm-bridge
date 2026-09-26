"""Project TEI text blocks to plain text with traceable offsets.

A recognizer needs running text, TEI stores it as mixed content. ``project``
turns one block (``p``, ``opener``, ``closer``, ...) into a single string and
records, for every character, where it came from:

* Characters from the XML are covered by a :class:`Segment` that names the
  owning element, the slot (``element.text`` or ``element.tail``) and the
  offset in the block's XPath string value.
* *Virtual* separators (a space for ``<lb/>`` or ``<space/>``, a line break
  between lines of an ``opener``) belong to no segment. A name that spans one
  can therefore not be written back inline.

Projection rules (the "reading text"):

* ``<c>``, ``<hi>``, ``<g>``, ``<add>``, ``<unclear>``, ``<supplied>`` and all
  other inline elements contribute their text without separators, so
  ``Ro<c>s</c>a`` stays one word.
* ``<lb/>``, ``<pb/>``, ``<cb/>`` and ``<space/>`` become one space. With
  ``@break="no"`` the word continues and whitespace on both sides is dropped
  (TEI att.breaking). No separator is added after existing whitespace.
* Excluded subtrees (editorial ``<note>``, ``<del>``, ``<fw>``, ``<index>`` and
  other non-transcriptional content) contribute nothing; their tails do. The
  descriptions inside ``<gap>`` and ``<space>`` are not read.
* In ``<choice>`` exactly one child is read: ``corr``/``reg``/``expan`` for the
  ``edited`` reading (default), ``sic``/``orig``/``abbr`` for ``diplomatic``.
  In ``<app>`` the ``lem`` is read (also inside ``rdgGrp``), otherwise the first ``rdg``.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from typing import Literal

from lxml import etree

TEI_URI = "http://www.tei-c.org/ns/1.0"
TEI = "{" + TEI_URI + "}"

Reading = Literal["edited", "diplomatic"]

#: Elements projected as one recognizer input. Only the outermost is used.
BLOCKS = frozenset({
    "p", "ab", "head", "opener", "closer", "postscript", "salute", "signed",
    "dateline", "address", "addrLine", "lg", "l", "item", "byline",
})
#: Elements that start a new line inside a block.
LINES = BLOCKS | {"list", "table", "row", "cell"}
#: A ``seg`` directly inside these elements is a line (e.g. a letterhead in ``opener``),
#: and so is a ``seg`` inside such a line ``seg`` (left/right columns of a letterhead).
LINE_CONTAINERS = frozenset({"opener", "closer", "postscript", "address", "dateline"})
#: Empty elements read as a space unless ``@break="no"``.
BREAKS = frozenset({"lb", "pb", "cb", "space"})
#: Subtrees outside the reading text.
EXCLUDED = frozenset({
    "note", "del", "fw", "figDesc", "metamark", "surplus",
    "index", "interp", "interpGrp", "certainty", "precision", "respons",
    "span", "spanGrp", "link", "linkGrp", "join", "joinGrp", "alt", "altGrp", "witDetail",
})
#: Elements whose content (a description) is not text of the source.
DESCRIBED = frozenset({"gap", "space"})
CHOICES = {
    "edited": ("corr", "reg", "expan", "ex", "seg"),
    "diplomatic": ("sic", "orig", "abbr", "am", "seg"),
}
#: Existing references, recorded as annotations. New names are never created
#: inside those of kind PER/LOC/ORG; inside other references (e.g. ``rs[@type='work']``) they may.
_PLACE_PARTS = ("settlement", "country", "region", "district", "bloc")
PROTECTED = frozenset({"persName", "placeName", "orgName", "geogName", "name", "rs", *_PLACE_PARTS})
_NAME_KINDS = {"persName": "PER", "placeName": "LOC", "geogName": "LOC", "orgName": "ORG", **dict.fromkeys(_PLACE_PARTS, "LOC")}
_TYPE_KINDS = {"person": "PER", "place": "LOC", "org": "ORG"}


def local_name(node: etree._Element) -> str | None:
    """Local name of a TEI element, ``None`` for other namespaces and non-elements."""
    if not isinstance(node.tag, str):
        return None
    qname = etree.QName(node)
    return qname.localname if qname.namespace == TEI_URI else None


def name_kind(node: etree._Element) -> str | None:
    """PER/LOC/ORG for a TEI name or ``rs``/``name`` with a person, place or org ``@type``."""
    name = local_name(node)
    if name in _NAME_KINDS:
        return _NAME_KINDS[name]
    if name in {"rs", "name"}:
        return _TYPE_KINDS.get(node.get("type", ""))
    return None


def is_line(node: etree._Element) -> bool:
    """True if ``node`` starts a new line inside a block."""
    name = local_name(node)
    if name in LINES:
        return True
    if name != "seg":
        return False
    parent = node.getparent()
    parent_name = local_name(parent) if parent is not None else None
    return parent_name in LINE_CONTAINERS or (parent_name == "seg" and is_line(parent))


def string_value(node: etree._Element) -> str:
    """XPath string value: all descendant text, without comment or PI content."""
    parts = [node.text or ""]
    for child in node:
        if isinstance(child.tag, str):
            parts.append(string_value(child))
        parts.append(child.tail or "")
    return "".join(parts)


def xpath_of(node: etree._Element) -> str:
    """Readable, position-based XPath with a ``tei:`` prefix, e.g. ``/tei:TEI/tei:text[1]``."""
    steps = []
    while node is not None:
        parent = node.getparent()
        qname = etree.QName(node)
        step = f"tei:{qname.localname}" if qname.namespace == TEI_URI else f"*[local-name()='{qname.localname}']"
        if parent is not None:
            siblings = [sibling for sibling in parent if sibling.tag == node.tag]
            step += f"[{siblings.index(node) + 1}]"
        steps.append(step)
        node = parent
    return "/" + "/".join(reversed(steps))


def xpath_selector(node: etree._Element) -> str:
    """XPath 1.0 that needs no namespace binding (W3C XPathSelector): ``xml:id`` or ``local-name()`` steps."""
    ident = node.get("{http://www.w3.org/XML/1998/namespace}id")
    if ident:
        return f"//*[@xml:id='{ident}']"
    steps = []
    while node is not None:
        parent = node.getparent()
        name = etree.QName(node).localname
        step = f"*[local-name()='{name}']"
        if parent is not None:
            same = [sibling for sibling in parent if isinstance(sibling.tag, str) and etree.QName(sibling).localname == name]
            step += f"[{same.index(node) + 1}]"
        steps.append(step)
        node = parent
    return "/" + "/".join(reversed(steps))


@dataclass(frozen=True)
class Segment:
    """Projected characters ``start:end`` are ``getattr(owner, slot)[offset:offset + end - start]``."""

    start: int
    end: int
    owner: etree._Element
    slot: Literal["text", "tail"]
    offset: int  # index of ``start`` inside the text slot
    raw: int  # offset of ``start`` in the block's XPath string value


@dataclass(frozen=True)
class Annotation:
    """An existing reference element and its projected span."""

    element: etree._Element
    kind: str | None  # None for references such as rs[@type='work']
    start: int
    end: int


@dataclass
class Projection:
    block: etree._Element
    text: str
    segments: list[Segment] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)

    def segment_at(self, position: int) -> Segment | None:
        """Segment containing projected character ``position``."""
        index = bisect_right([segment.start for segment in self.segments], position) - 1
        if index >= 0 and self.segments[index].start <= position < self.segments[index].end:
            return self.segments[index]
        return None

    def single_segment(self, start: int, end: int) -> Segment | None:
        """The segment holding all of ``start:end``, if one does."""
        segment = self.segment_at(start)
        return segment if segment is not None and end <= segment.end else None

    def raw_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Offsets of ``start:end`` in the block's string value (W3C TextPositionSelector)."""
        first, last = self.segment_at(start), self.segment_at(end - 1)
        if first is None or last is None:
            return None
        return first.raw + start - first.start, last.raw + end - last.start

    def protected(self, start: int, end: int) -> bool:
        """True if ``start:end`` overlaps an existing person, place or organisation reference."""
        return any(item.kind and item.start < end and start < item.end for item in self.annotations)


class _Builder:
    def __init__(self, reading: Reading):
        if reading not in CHOICES:
            raise ValueError(f"reading must be one of {sorted(CHOICES)}")
        self.reading = reading
        self.parts: list[str] = []
        self.virtual_parts: list[bool] = []
        self.segments: list[Segment] = []
        self.annotations: list[Annotation] = []
        self.position = 0
        self.raw = 0
        self.joining = False  # after <lb break="no"/>: skip leading whitespace

    def emit(self, owner: etree._Element, slot: Literal["text", "tail"], text: str | None) -> None:
        if not text:
            return
        offset = 0
        if self.joining:
            offset = len(text) - len(text.lstrip())
            self.raw += offset
            if offset == len(text):
                return
            self.joining = False
        piece = text[offset:]
        self.segments.append(Segment(self.position, self.position + len(piece), owner, slot, offset, self.raw))
        self.parts.append(piece)
        self.virtual_parts.append(False)
        self.position += len(piece)
        self.raw += len(piece)

    def virtual(self, separator: str) -> None:
        if self.parts and not self.joining and not self.parts[-1][-1].isspace():
            self.parts.append(separator)
            self.virtual_parts.append(True)
            self.position += len(separator)

    def unbreak(self) -> None:
        """``break="no"``: the token continues, so whitespace before and after is dropped."""
        while self.parts:
            part = self.parts[-1]
            kept = part.rstrip()
            removed = len(part) - len(kept)
            if not removed:
                break
            self.position -= removed
            if not self.virtual_parts[-1]:
                segment = self.segments.pop()
                if kept:
                    self.segments.append(replace(segment, end=segment.end - removed))
            if kept:
                self.parts[-1] = kept
                break
            self.parts.pop()
            self.virtual_parts.pop()
        self.joining = True

    def skip(self, node: etree._Element) -> None:
        self.raw += len(string_value(node))

    def content(self, node: etree._Element) -> None:
        """Project the content of ``node`` (text and children, not its tail)."""
        name = local_name(node)
        if name in {"choice", "app"}:
            chosen = self._choose(node, name)
            self.raw += len(node.text or "")
            self._alternatives(node, chosen)
            return
        self.emit(node, "text", node.text)
        for child in node:
            self.child(child)

    def child(self, child: etree._Element) -> None:
        name = local_name(child)
        if not isinstance(child.tag, str):
            pass  # comment or processing instruction: content is not text
        elif name in EXCLUDED:
            self.skip(child)
        elif name in BREAKS and child.get("break") == "no":
            self.unbreak()
            self.skip(child)
        else:
            line = is_line(child)
            if line:
                self.virtual("\n")
            if name in BREAKS:
                self.virtual(" ")
            start = self.position
            if name in DESCRIBED:
                self.skip(child)
            else:
                self.content(child)
            self._annotate(child, start)
            if line:
                self.virtual("\n")
        self.emit(child, "tail", child.tail)

    def _annotate(self, node: etree._Element, start: int) -> None:
        if local_name(node) in PROTECTED and self.position > start:
            self.annotations.append(Annotation(node, name_kind(node), start, self.position))

    def _choose(self, node: etree._Element, name: str) -> etree._Element | None:
        return choose_alternative(node, self.reading)

    def _alternatives(self, node: etree._Element, chosen: etree._Element | None) -> None:
        """Read ``chosen`` only; other alternatives and the layout whitespace between them are skipped."""
        for child in node:
            if child is chosen:
                start = self.position
                self.content(child)
                self._annotate(child, start)
            elif isinstance(child.tag, str) and chosen is not None and any(d is chosen for d in child.iterdescendants()):
                self.raw += len(child.text or "")
                self._alternatives(child, chosen)  # rdgGrp holding the chosen reading
            elif isinstance(child.tag, str):
                self.skip(child)
            self.raw += len(child.tail or "")


def choose_alternative(node: etree._Element, reading: Reading = "edited") -> etree._Element | None:
    """The one child of ``choice`` (by reading) or reading of ``app`` that is projected."""
    if local_name(node) == "app":
        lemma = _find_reading(node, "lem")
        return lemma if lemma is not None else _find_reading(node, "rdg")
    children = [child for child in node if isinstance(child.tag, str) and local_name(child) not in EXCLUDED]
    return next(
        (child for wanted in CHOICES[reading] for child in children if local_name(child) == wanted),
        children[0] if children else None,
    )


def _find_reading(node: etree._Element, wanted: str) -> etree._Element | None:
    for child in node:
        name = local_name(child)
        if name == wanted:
            return child
        if name == "rdgGrp":
            found = _find_reading(child, wanted)
            if found is not None:
                return found
    return None


def project(block: etree._Element, reading: Reading = "edited") -> Projection:
    """Project one block. The block's own tail is not part of it."""
    builder = _Builder(reading)
    builder.content(block)
    text = "".join(builder.parts)
    return Projection(block, text, builder.segments, builder.annotations)


def find_blocks(root: etree._Element) -> list[etree._Element]:
    """Outermost block elements in every ``text//body``, outside excluded subtrees."""
    blocks: list[etree._Element] = []

    def visit(node: etree._Element) -> None:
        for child in node:
            name = local_name(child)
            if name is None and not isinstance(child.tag, str):
                continue
            if name in EXCLUDED:
                continue
            if name in BLOCKS:
                blocks.append(child)
            else:
                visit(child)

    for body in root.iter(TEI + "body"):
        # A nested body (floatingText) is reached through the walk of the outer one.
        if not any(local_name(ancestor) in EXCLUDED | BLOCKS | {"body"} for ancestor in body.iterancestors()):
            visit(body)
    return blocks
