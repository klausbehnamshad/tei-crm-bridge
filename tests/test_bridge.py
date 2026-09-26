from pathlib import Path

import pytest
from lxml import etree
from rdflib import Graph, RDF, RDFS, Literal

from tei_crm_bridge.core import CRM, EX, TEI_URI, enrich
from tei_crm_bridge.ner import GlossaryRecognizer
from tei_crm_bridge.preview import write_preview


ROOT = Path(__file__).resolve().parents[1]
NS = {"tei": TEI_URI}


def test_end_to_end_preserves_markup_and_maps_explicit_event(tmp_path):
    source = ROOT / "examples/letter.xml"
    output_xml = tmp_path / "enriched.xml"
    output_ttl = tmp_path / "graph.ttl"
    original = etree.parse(str(source))
    recognizer = GlossaryRecognizer(ROOT / "examples/glossary.json")

    result = enrich(source, output_xml, output_ttl, recognizer, "https://example.org/test/")

    tree = etree.parse(str(output_xml))
    graph = Graph().parse(str(output_ttl), format="turtle")
    assert result.paragraphs == 2
    assert result.new_annotations == 4  # Schiller, Goethe, Jena in <hi>, Universität Jena
    assert result.existing_annotations == 1  # Weimar
    assert result.events == 1
    assert result.triples == len(graph)
    assert tree.xpath("count(.//tei:body//tei:hi/tei:placeName)", namespaces=NS) == 1
    assert tree.xpath("count(.//tei:body//tei:placeName[text()='Weimar'])", namespaces=NS) == 1
    before = ["".join(p.itertext()) for p in original.xpath(".//tei:body//tei:p", namespaces=NS)]
    after = ["".join(p.itertext()) for p in tree.xpath(".//tei:body//tei:p", namespaces=NS)]
    assert before == after
    assert len(list(graph.subjects(RDF.type, CRM.E7_Activity))) == 1
    assert any(graph.triples((None, CRM["P4_has_time-span"], None)))
    assert any(graph.triples((None, CRM.P14_carried_out_by, None)))
    assert len(list(graph.triples((None, EX.teiXPath, None)))) == 5
    preview = tmp_path / "preview.html"
    write_preview(output_xml, output_ttl, preview, result, "glossary")
    rendered = preview.read_text(encoding="utf-8")
    assert 'data-kind="PER"' in rendered
    assert 'href="enriched.xml"' in rendered
    assert 'href="graph.ttl"' in rendered


def test_no_invented_event_and_escaped_text(tmp_path):
    source = tmp_path / "input.xml"
    source.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="x">'
        '<text><body><p>Goethe &amp; Schiller in Jena.</p></body></text></TEI>',
        encoding="utf-8",
    )
    recognizer = GlossaryRecognizer(ROOT / "examples/glossary.json")
    output_xml = tmp_path / "out.xml"
    output_ttl = tmp_path / "out.ttl"
    result = enrich(source, output_xml, output_ttl, recognizer, "https://example.org/test/")
    tree = etree.parse(str(output_xml))
    graph = Graph().parse(str(output_ttl), format="turtle")
    assert result.events == 0
    assert not list(graph.subjects(RDF.type, CRM.E7_Activity))
    assert "Goethe & Schiller in Jena." == "".join(tree.xpath(".//tei:p", namespaces=NS)[0].itertext())


def test_rejects_non_tei_namespace(tmp_path):
    source = tmp_path / "wrong.xml"
    source.write_text('<TEI xmlns="http://tei-c.org"><text/></TEI>', encoding="utf-8")
    with pytest.raises(ValueError, match="official namespace"):
        enrich(
            source, tmp_path / "out.xml", tmp_path / "out.ttl",
            GlossaryRecognizer(ROOT / "examples/glossary.json"), "https://example.org/test/",
        )


def test_same_surface_in_different_documents_has_separate_uri(tmp_path):
    recognizer = GlossaryRecognizer(ROOT / "examples/glossary.json")
    uris = []
    for doc_id in ("a", "b"):
        source = tmp_path / f"{doc_id}.xml"
        source.write_text(
            f'<TEI xmlns="{TEI_URI}" xml:id="{doc_id}"><text><body><p>Goethe.</p></body></text></TEI>',
            encoding="utf-8",
        )
        ttl = tmp_path / f"{doc_id}.ttl"
        enrich(source, tmp_path / f"{doc_id}.out.xml", ttl, recognizer, "https://example.org/test/")
        graph = Graph().parse(str(ttl), format="turtle")
        uris.append(next(graph.subjects(RDFS.label, Literal("Goethe"))))
    assert uris[0] != uris[1]
