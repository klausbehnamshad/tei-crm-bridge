"""CMIF export for correspSearch (BBAW).

Collects the ``correspDesc``/``correspAction`` metadata of many original TEI
letters into one CMIF file (a restricted TEI subset, see the `CMIF
documentation`_ of the TEI Correspondence SIG). Reference resolution reuses
:class:`tei_crm_bridge.rdf.GraphBuilder` (``@ref``, ``prefixDef``,
``xml:base``) and date validation reuses :mod:`tei_crm_bridge.dates`; only
the authority-URI mapping (GND for persons/organisations, GeoNames for
places) is CMIF-specific.

.. _CMIF documentation: https://github.com/TEI-Correspondence-SIG/CMIF
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from lxml import etree

from .dates import interval
from .projection import TEI, local_name
from .rdf import GraphBuilder, valid_iri
from .reconcile import links_for

#: Where the official CMIF RelaxNG schema lives; referenced as ``xml-model``.
CMIF_SCHEMA = ("https://raw.githubusercontent.com/TEI-Correspondence-SIG/CMIF"
               "/main/schema/cmi-customization.rng")

#: Only correspondence actions CMIF accepts; anything else is skipped.
CMIF_ACTIONS = ("sent", "received")

#: Register ``idno`` subtypes holding a GND identifier.
GND_SUBTYPES = frozenset({"gnd", "d-nb"})

#: Register ``idno`` subtypes holding a GeoNames identifier.
GEONAMES_SUBTYPES = frozenset({"geonames"})

#: ``date`` attributes CMIF supports (a subset of TEI datable).
DATE_ATTRS = ("when", "from", "to", "notBefore", "notAfter")

#: CMIF date granularity (the schema also accepts ``xsd:dateTime``).
_CMIF_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

#: GND identifiers, normalized to the ``https`` form CMIF examples use.
_GND = re.compile(r"^https?://d-nb\.info/gnd/\S+$")

#: Standard licence statements for the two licence URLs CMIF mandates.
LICENCE_TEXTS = {
    "https://creativecommons.org/licenses/by/4.0/": (
        "This file is licensed under the terms of the Creative Commons Licence CC BY 4.0"),
    "https://creativecommons.org/publicdomain/zero/1.0/": (
        "This file is dedicated to the public domain under the terms of the "
        "Creative Commons Public Domain Dedication CC0 1.0"),
}


def _text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _normalize_gnd(uri: str) -> str:
    return re.sub(r"^http://d-nb\.info/gnd/", "https://d-nb.info/gnd/", uri)


def _register_uri(record: etree._Element, subtypes: frozenset[str]) -> str | None:
    """First valid authority URI of the register entry's OWN ``idno`` elements.

    Direct ``idno`` children plus ``idno`` under a ``location`` child count;
    ``location[@type="located_in_place"]`` names the SUPERORDINATE place, so its
    ``idno`` belongs to someone else and is ignored (consistent with
    :meth:`rdf.GraphBuilder.entities_for`, which reads direct children only).
    """
    candidates = list(record.findall(TEI + "idno"))
    for location in record.findall(TEI + "location"):
        if location.get("type") != "located_in_place":
            candidates.extend(location.findall(TEI + "idno"))
    for idno in candidates:
        subtype = (idno.get("subtype") or idno.get("type") or "").lower()
        value = (idno.text or "").strip()
        if subtype in subtypes and valid_iri(value):
            return value
    return None


def _cache_uri(reconciliation: Mapping | None, token: str, kind: str | None) -> str | None:
    """Reconciled URI for a ``#local-id`` token: GND for persons/organisations, GeoNames for places."""
    if not token.startswith("#"):
        return None
    entry = links_for(reconciliation, token[1:])
    if entry is None:
        return None
    value = entry.get("gnd") if kind in {"persName", "orgName"} else entry.get("geonames")
    return value if isinstance(value, str) and valid_iri(value) else None


def authority_uri(builder: GraphBuilder, node: etree._Element,
                  reconciliation: Mapping | None = None) -> str | None:
    """GND URI (persons/organisations) or GeoNames URI (places) for a name, or None.

    Sources in order: the register entry's ``idno`` (subtypes ``gnd``/``d-nb``
    for persons, ``geonames`` for places), the reconciliation cache via the
    local ID of ``@ref`` (``#pmb2121`` → ``pmb2121``), and finally the letter's
    own ``@ref`` when it already is a GND URI.
    """
    kind = local_name(node)
    subtypes = GND_SUBTYPES if kind in {"persName", "orgName"} else GEONAMES_SUBTYPES
    cached = direct = None
    for token in (node.get("ref") or "").split():
        resolved = builder.resolve(token, node)
        if resolved is None:
            continue
        uri, record = resolved
        if record is not None:
            found = _register_uri(record, subtypes)
            if found:
                return _normalize_gnd(found) if kind in {"persName", "orgName"} else found
            if cached is None:
                cached = _cache_uri(reconciliation, token, kind)
        elif kind in {"persName", "orgName"} and _GND.match(uri) and direct is None:
            direct = _normalize_gnd(uri)
    return cached if cached is not None else direct


def _carry_qualifiers(source: etree._Element, target: etree._Element, warnings: list[str], where: str) -> None:
    """Keep ``evidence``/``cert`` only where CMIF allows them (``conjecture``/``low``)."""
    evidence, cert = source.get("evidence"), source.get("cert")
    if evidence == "conjecture":
        target.set("evidence", evidence)
    elif evidence is not None:
        warnings.append(f"{where}: evidence={evidence!r} ist kein CMIF-Wert und entfällt")
    if cert == "low":
        target.set("cert", cert)
    elif cert is not None:
        warnings.append(f"{where}: cert={cert!r} ist kein CMIF-Wert und entfällt")


def _cmif_name(builder: GraphBuilder, node: etree._Element, warnings: list[str], where: str,
                reconciliation: Mapping | None = None) -> etree._Element:
    """A ``persName``/``orgName``/``placeName`` with an authority URI or without ``@ref``."""
    label = _text(node) or (node.get("ref") or "").strip()
    out = etree.Element(TEI + (local_name(node) or "persName"))
    out.text = label
    uri = authority_uri(builder, node, reconciliation)
    if uri is not None:
        out.set("ref", uri)
    else:
        warnings.append(f"{where}: {label!r} hat keine GND-/GeoNames-Identität und steht ohne @ref")
    _carry_qualifiers(node, out, warnings, where)
    return out


def _cmif_date(node: etree._Element, warnings: list[str], where: str) -> etree._Element:
    """A ``date`` with the CMIF machine attributes; invalid bounds keep only the text."""
    out = etree.Element(TEI + "date")
    out.text = _text(node) or None
    kept = {name: node.get(name) for name in DATE_ATTRS if node.get(name)}
    try:
        interval(node)
    except ValueError as error:
        warnings.append(f"{where}: Datum ungültig ({error}) und nur als Text übernommen")
        kept = {}
    for name, value in kept.items():
        if not _CMIF_DATE.match(value):
            warnings.append(f"{where}: {name}={value!r} ist feiner als die CMIF-Granularität (JJJJ-MM-TT)")
        out.set(name, value)
    _carry_qualifiers(node, out, warnings, where)
    return out


@dataclass(frozen=True)
class CmifOptions:
    """Export settings; ``url_pattern`` formats the letter URL with ``{id}`` (the letter's ``xml:id``)."""

    cmif_url: str
    url_pattern: str | None = None
    title: str | None = None
    publisher: str | None = None
    licence: str | None = None
    licence_text: str | None = None
    editor: str = "TEI CRM Bridge"
    editor_email: str | None = None
    source_id: str | None = None
    source_type: str = "online"
    source_label: str | None = None
    reconciliation: Mapping | None = None


@dataclass(frozen=True)
class CmifResult:
    letters: int
    descriptions: int
    actions: int
    names_with_ref: int
    names_without_ref: int
    warnings: tuple[str, ...]


def _header_text(root: etree._Element, xpath: str) -> str | None:
    found = root.find(xpath, namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
    if found is None:
        return None
    return _text(found) or None


def _series_title(root: etree._Element) -> str | None:
    titles = root.findall(
        "{http://www.tei-c.org/ns/1.0}teiHeader/{http://www.tei-c.org/ns/1.0}fileDesc/"
        "{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    for title in titles:
        if title.get("level") == "s" and _text(title):
            return _text(title)
    return None


def _canonical_licence(target: str | None) -> str | None:
    """Map CC licence URL variants (e.g. ``.../by/4.0/deed.de``) to the canonical CMIF URL."""
    if not target:
        return None
    for canonical in LICENCE_TEXTS:
        if target.startswith(canonical) or target.replace("http://", "https://").startswith(canonical):
            return canonical
    return target if valid_iri(target) else None


def _source_id(options: CmifOptions) -> str:
    """Stable ``bibl`` id (``xs:ID`` must start with a letter, a bare UUID may not)."""
    raw = options.source_id or str(uuid.uuid5(uuid.NAMESPACE_URL, options.cmif_url))
    return raw if re.match(r"^[A-Za-z_]", raw) else f"b{raw}"


def _build_header(roots: list[etree._Element], options: CmifOptions, warnings: list[str]) -> etree._Element:
    ns = "http://www.tei-c.org/ns/1.0"

    def element(name: str, text: str | None = None, **attrs: str) -> etree._Element:
        node = etree.Element(f"{{{ns}}}{name}", **attrs)
        node.text = text
        return node

    series = [_series_title(root) for root in roots]
    names = sorted({title for title in series if title})
    title = options.title
    if title is None:
        title = f"{names[0]} (CMIF)" if len(names) == 1 else "Korrespondenzmetadaten (CMIF)"
        if len(names) > 1:
            warnings.append("Briefe haben verschiedene Reihentitel; --title setzt den CMIF-Titel")
    publisher = options.publisher or next(
        (_header_text(root, ".//tei:publicationStmt/tei:publisher") for root in roots if _header_text(root, ".//tei:publicationStmt/tei:publisher")),
        "TEI CRM Bridge",
    )
    licence_target = _canonical_licence(options.licence) if options.licence else next(
        (_canonical_licence(found.get("target"))
         for root in roots
         for found in root.findall(".//{http://www.tei-c.org/ns/1.0}availability/{http://www.tei-c.org/ns/1.0}licence")
         if _canonical_licence(found.get("target"))),
        "https://creativecommons.org/licenses/by/4.0/",
    )
    if options.licence is None and licence_target not in LICENCE_TEXTS:
        warnings.append(f"Lizenz {licence_target!r} ist keine kanonische CMIF-Lizenz (CC BY 4.0/CC0); --licence setzt sie")
    licence_text = options.licence_text or LICENCE_TEXTS.get(
        licence_target, f"Lizenz der Ausgangsedition: {licence_target}")

    header = element("teiHeader")
    file_desc = etree.SubElement(header, f"{{{ns}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{ns}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{ns}}}title").text = title
    editor = etree.SubElement(title_stmt, f"{{{ns}}}editor")
    editor.text = options.editor + (" " if options.editor_email else "")
    if options.editor_email:
        etree.SubElement(editor, f"{{{ns}}}email").text = options.editor_email
    publication_stmt = etree.SubElement(file_desc, f"{{{ns}}}publicationStmt")
    etree.SubElement(publication_stmt, f"{{{ns}}}publisher").text = publisher
    etree.SubElement(publication_stmt, f"{{{ns}}}idno", type="url").text = options.cmif_url
    etree.SubElement(publication_stmt, f"{{{ns}}}date",
                     when=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    availability = etree.SubElement(publication_stmt, f"{{{ns}}}availability")
    etree.SubElement(availability, f"{{{ns}}}licence", target=licence_target).text = licence_text
    source_desc = etree.SubElement(file_desc, f"{{{ns}}}sourceDesc")
    label = options.source_label
    if label is None:
        label = f"{names[0]} ({publisher})" if names else publisher
    etree.SubElement(source_desc, f"{{{ns}}}bibl",
                     attrib={"{http://www.w3.org/XML/1998/namespace}id": _source_id(options),
                             "type": options.source_type}).text = label
    return header


def _letter_url(doc_id: str, options: CmifOptions) -> tuple[str | None, str | None]:
    """``(ref, key)`` for a ``correspDesc``: the public letter URL or, without a pattern, the ``xml:id``."""
    if options.url_pattern:
        return options.url_pattern.format(id=doc_id), None
    return None, doc_id


def build_cmif(letters: list[tuple[str, etree._Element]], options: CmifOptions) -> tuple[etree._ElementTree, CmifResult]:
    """One CMIF ``TEI`` tree for parsed letters ``(doc_id, root)`` plus statistics."""
    ns = "http://www.tei-c.org/ns/1.0"
    warnings: list[str] = []
    names_with_ref, names_without_ref, actions = 0, 0, 0
    profile = etree.Element(f"{{{ns}}}profileDesc")
    descriptions = 0
    seen: set[str] = set()
    for doc_id, root in letters:
        where = f"Brief {doc_id}"
        if doc_id in seen:
            warnings.append(f"{where}: xml:id ist doppelt; beide Einträge stehen in der CMIF-Datei")
        seen.add(doc_id)
        # An https base keeps urljoin() resolution of "#id" working; the base
        # itself never appears in the CMIF output.
        builder = GraphBuilder(root, doc_id, "https://example.org/tei-crm-bridge/cmif/", [])
        kept: list[etree._Element] = []
        for desc in root.iter(TEI + "correspDesc"):
            for action in desc.findall(TEI + "correspAction"):
                kind = action.get("type")
                if kind not in CMIF_ACTIONS:
                    warnings.append(f"{where}: correspAction type={kind!r} ist kein CMIF-Typ und entfällt")
                    continue
                out_action = etree.Element(f"{{{ns}}}correspAction", type=kind)
                for child in action:
                    name = local_name(child) if isinstance(child.tag, str) else ""
                    spot = f"{where}/{kind}/{name}"
                    if name in {"persName", "orgName", "placeName"}:
                        out_name = _cmif_name(builder, child, warnings, spot, options.reconciliation)
                        if out_name.get("ref") is not None:
                            names_with_ref += 1
                        else:
                            names_without_ref += 1
                        out_action.append(out_name)
                    elif name == "date":
                        out_action.append(_cmif_date(child, warnings, spot))
                    # correspContext and anything else have no CMIF counterpart.
                if len(out_action) == 0:
                    warnings.append(f"{where}: Handlung {kind!r} ist leer und entfällt")
                    continue
                kept.append(out_action)
                actions += 1
        if not kept:
            warnings.append(f"{where}: kein sent/received und entfällt")
            continue
        ref, key = _letter_url(doc_id, options)
        attrs = {"source": f"#{_source_id(options)}"}
        if ref is not None:
            attrs["ref"] = ref
        if key is not None:
            attrs["key"] = key
        out_desc = etree.Element(f"{{{ns}}}correspDesc", **attrs)
        out_desc.extend(kept)
        profile.append(out_desc)
        descriptions += 1
    roots = [root for _, root in letters]
    tei = etree.Element(f"{{{ns}}}TEI", nsmap={None: ns})
    header = _build_header(roots, options, warnings)
    header.append(profile)
    tei.append(header)
    text = etree.SubElement(tei, f"{{{ns}}}text")
    etree.SubElement(etree.SubElement(text, f"{{{ns}}}body"), f"{{{ns}}}p")
    result = CmifResult(len(letters), descriptions, actions, names_with_ref, names_without_ref, tuple(warnings))
    return etree.ElementTree(tei), result


def export_cmif(inputs: list[Path], out: Path, options: CmifOptions) -> CmifResult:
    """Read original TEI letters and write one CMIF file; no NER is involved."""
    letters: list[tuple[str, etree._Element]] = []
    for path in inputs:
        root = etree.parse(str(path)).getroot()
        doc_id = root.get("{http://www.w3.org/XML/1998/namespace}id") or path.stem
        letters.append((doc_id, root))
    tree, result = build_cmif(letters, options)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out), encoding="utf-8", xml_declaration=True, pretty_print=True)
    with open(out, "rb+") as handle:
        content = handle.read()
        model = (f'<?xml-model href="{CMIF_SCHEMA}" type="application/xml" '
                 'schematypens="http://relaxng.org/ns/structure/1.0"?>\n').encode()
        first, _, rest = content.partition(b"\n")
        handle.seek(0)
        handle.write(first + b"\n" + model + rest)
    return result
