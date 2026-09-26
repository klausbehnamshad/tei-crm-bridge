import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree
from rdflib import RDF, RDFS, Graph, Literal, URIRef, XSD

from tei_crm_bridge.core import _pieces, enrich
from tei_crm_bridge import __version__
from tei_crm_bridge.dates import bounds, intersect, interval
from tei_crm_bridge.ner import Entity, GlossaryRecognizer
from tei_crm_bridge.preview import write_preview
from tei_crm_bridge.projection import find_blocks, project, string_value
from tei_crm_bridge.rdf import CRM, OA, VOCAB
from tei_crm_bridge.writeback import unwrap

ROOT = Path(__file__).resolve().parents[1]
TEI_URI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_URI}
BASE = "https://example.org/test/"
PROV = "http://www.w3.org/ns/prov#"


def run(tmp_path, source, glossary=ROOT / "examples/glossary.json", **options):
    outputs = tmp_path / "out.xml", tmp_path / "out.ttl", tmp_path / "out.mentions.json"
    result = enrich(source, *outputs[:2], GlossaryRecognizer(glossary), BASE, output_json=outputs[2], **options)
    tree = etree.parse(str(outputs[0]))
    graph = Graph().parse(str(outputs[1]), format="turtle")
    return result, tree, graph, json.loads(outputs[2].read_text(encoding="utf-8"))


def write(tmp_path, xml, name="input.xml"):
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return path


def tei(body, header="", back=""):
    return (f'<TEI xmlns="{TEI_URI}" xml:id="x"><teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc>{header}</teiHeader>'
            f"<text><body>{body}</body>{back}</text></TEI>")


def test_example_end_to_end(tmp_path):
    source = ROOT / "examples/letter.xml"
    result, tree, graph, record = run(tmp_path, source)
    assert (result.blocks, result.editorial, result.earlier, result.inline, result.standoff, result.events) == (4, 1, 0, 5, 1, 2)
    assert result.triples == len(graph) and result.warnings == ()
    before = [project(b).text for b in find_blocks(etree.parse(str(source)).getroot())]
    assert before == [project(b).text for b in find_blocks(tree.getroot())]
    assert tree.xpath("count(//tei:hi/tei:placeName)", namespaces=NS) == 1
    assert tree.xpath("count(//tei:corr/tei:persName)", namespaces=NS) == 1
    assert tree.xpath("count(//tei:note//tei:persName)", namespaces=NS) == 0
    assert tree.xpath("//tei:body//tei:placeName[not(@resp)]/@ref", namespaces=NS) == ["#weimar"]
    new = tree.xpath("//tei:body//*[@resp='#tcb-run']", namespaces=NS)
    assert len(new) == 5 and all(n.get("{http://www.w3.org/XML/1998/namespace}id") for n in new)
    assert all(n.get("cert") is None for n in new)  # a glossary has no confidence
    [standoff] = [m for m in record["mentions"] if not m["inline"]]
    assert standoff["text"] == "Schiller" and standoff["xpath"] is None
    assert record["input"]["sha256"] and record["input"]["file"] == "letter.xml"


def test_published_demo_iris_resolve_to_its_html_page():
    spec = importlib.util.spec_from_file_location("tei_crm_build_docs", ROOT / "scripts/build_docs.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    files = module.build_demo(ROOT / "examples/letter.xml", "example", GlossaryRecognizer(ROOT / "examples/glossary.json"))
    graph = Graph().parse(data=files[str(ROOT / "docs/example/letter.ttl")].decode(), format="turtle")
    page_base = f"{module.PAGES_URL}example/letter.html#/"
    document = next(graph.subjects(RDF.type, CRM.E31_Document))
    assert str(document).startswith(page_base)
    assert all(str(candidate).startswith(page_base) for candidate in graph.subjects(RDF.type, VOCAB.Candidate))
    tei_url = URIRef(f"{module.PAGES_URL}example/letter.enriched.xml")
    assert all(graph.value(graph.value(annotation, OA.hasTarget), OA.hasSource) == tei_url
               for annotation in graph.subjects(RDF.type, OA.Annotation))
    weimar = URIRef(f"{tei_url}#weimar")
    assert (weimar, RDF.type, CRM.E53_Place) in graph
    assert (document, CRM.P67_refers_to, weimar) in graph


def test_every_annotation_is_found_again_in_its_source_file(tmp_path):
    """W3C selectors resolve in the enriched TEI named by oa:hasSource."""
    source = write(tmp_path, tei('<p>Ro<c rendition="#s">s</c>a fuhr nach New<lb/>York zu <hi>Goethe</hi>.<note>Goethe?</note></p>'
                                  '<p>Schil <lb break="no"/>\n  ler</p>'), "letter.xml")
    glossary = write(tmp_path, '{"PER": ["Rosa", "Goethe", "Schiller"], "LOC": ["New York"]}', "g.json")
    tei_url = "https://example.org/pub/letter.enriched.xml"
    _, tree, graph, _ = run(tmp_path, source, glossary, tei_url=tei_url, source_url="https://example.org/src/letter.xml")
    root = tree.getroot()
    assert (URIRef(tei_url), URIRef(PROV + "wasDerivedFrom"), URIRef("https://example.org/src/letter.xml")) in graph
    annotations = list(graph.subjects(RDF.type, OA.Annotation))
    assert len(annotations) == 4
    for annotation in annotations:
        target = graph.value(annotation, OA.hasTarget)
        assert graph.value(target, OA.hasSource) == URIRef(tei_url)
        found = {}
        for selector in graph.objects(target, OA.hasSelector):
            [node] = root.xpath(str(graph.value(selector, RDF.value)))  # no namespace binding needed
            refined = graph.value(selector, OA.refinedBy)
            if refined is None:
                found["element"] = string_value(node)
            elif (refined, RDF.type, OA.TextPositionSelector) in graph:
                found["position"] = string_value(node)[int(graph.value(refined, OA.start)):int(graph.value(refined, OA.end))]
            else:
                text = string_value(node)
                exact, prefix, suffix = (str(graph.value(refined, p) or "") for p in (OA.exact, OA.prefix, OA.suffix))
                assert prefix + exact + suffix in text
                found["quote"] = exact
        assert found["position"] == found["quote"]
        if "element" in found:
            assert found["element"] == found["quote"]
    quotes = {str(o) for o in graph.objects(None, OA.exact)}
    assert "NewYork" in quotes and "Schil \n  ler" in quotes  # the file's characters, not the reading text


def test_trimmed_editorial_name_has_consistent_selectors(tmp_path):
    source = write(tmp_path, tei("<p><persName> Goethe </persName> ging.</p>"))
    _, tree, graph, _ = run(tmp_path, source)
    [annotation] = graph.subjects(RDF.type, OA.Annotation)
    target = graph.value(annotation, OA.hasTarget)
    selected = set()
    for selector in graph.objects(target, OA.hasSelector):
        [node] = tree.getroot().xpath(str(graph.value(selector, RDF.value)))
        refined = graph.value(selector, OA.refinedBy)
        assert refined is not None  # the whole element includes spaces outside the name
        if (refined, RDF.type, OA.TextPositionSelector) in graph:
            text = string_value(node)
            selected.add(text[int(graph.value(refined, OA.start)):int(graph.value(refined, OA.end))])
        else:
            selected.add(str(graph.value(refined, OA.exact)))
    assert selected == {"Goethe"}


def test_suggestions_are_candidates_not_statements(tmp_path):
    _, _, graph, _ = run(tmp_path, ROOT / "examples/letter.xml")
    document = URIRef(BASE + "document/letter-001")
    assert set(graph.objects(document, CRM.P67_refers_to)) == {URIRef(BASE + "document/letter-001/tei#weimar")}
    automatic = list(graph.subjects(VOCAB.origin, VOCAB.automatic))
    assert len(automatic) == 6
    for annotation in automatic:
        body = graph.value(annotation, OA.hasBody)
        assert (body, RDF.type, VOCAB.Candidate) in graph
        assert not [t for t in graph.objects(body, RDF.type) if str(t).startswith(str(CRM))]
        assert (annotation, URIRef(PROV + "wasGeneratedBy"), None) in graph
    jena = URIRef(BASE + "document/letter-001/candidate/loc/jena-0dd8aa7e1e")
    assert (jena, VOCAB.suggestedClass, CRM.E53_Place) in graph
    assert not list(graph.triples((None, VOCAB.confidence, None)))
    [run_uri] = set(graph.objects(None, URIRef(PROV + "wasGeneratedBy")))
    assert (run_uri, VOCAB.softwareVersion, Literal(__version__)) in graph
    assert not list(graph.triples((run_uri, VOCAB.threshold, None)))


def test_correspondence_events_refs_and_dates(tmp_path):
    _, _, graph, _ = run(tmp_path, ROOT / "examples/letter.xml")
    sent, received = URIRef(BASE + "event/letter-001/sent-1"), URIRef(BASE + "event/letter-001/received-1")
    goethe, schiller = URIRef("https://d-nb.info/gnd/118540238"), URIRef("https://d-nb.info/gnd/118607626")
    assert (sent, CRM.P2_has_type, VOCAB.sending) in graph and (received, CRM.P2_has_type, VOCAB.receiving) in graph
    assert (sent, CRM.P14_carried_out_by, schiller) in graph and (received, CRM.P14_carried_out_by, goethe) in graph
    assert (goethe, RDFS.label, Literal("Johann Wolfgang von Goethe")) in graph  # correspDesc name, not a body form
    span = URIRef(str(received) + "/time")
    assert (span, CRM.P82a_begin_of_the_begin, Literal("1797-08-02T00:00:00", datatype=XSD.dateTime)) in graph
    assert (span, CRM.P82b_end_of_the_end, Literal("1797-08-05T23:59:59", datatype=XSD.dateTime)) in graph


def test_dates_keep_their_precision():
    assert bounds("1889") == ("1889-01-01T00:00:00", "1889-12-31T23:59:59")
    assert bounds("1900-02") == ("1900-02-01T00:00:00", "1900-02-28T23:59:59")
    assert bounds("1904-02") == ("1904-02-01T00:00:00", "1904-02-29T23:59:59")
    assert bounds("1889-08-02") == ("1889-08-02T00:00:00", "1889-08-02T23:59:59")
    assert bounds("1889-08-02T14:30") == ("1889-08-02T14:30:00", "1889-08-02T14:30:59")
    assert bounds("1889-08-02T14:30:05+01:00") == ("1889-08-02T14:30:05+01:00", "1889-08-02T14:30:05+01:00")
    assert bounds("1889-08-02T14:30:12.345Z") == ("1889-08-02T14:30:12.345Z", "1889-08-02T14:30:12.345Z")
    assert bounds("1889-08-02T14:30:12.123456+14:00") == (
        "1889-08-02T14:30:12.123456+14:00", "1889-08-02T14:30:12.123456+14:00",
    )
    date = etree.fromstring(f'<date xmlns="{TEI_URI}" notBefore="1889-08" evidence="conjecture"/>')
    assert interval(date).begin == "1889-08-01T00:00:00" and interval(date).end is None
    for value in (
        "1889-13", "1889-02-30", "1889-08-02T99:99:99", "1889-08-02T24:00", "--08-02", "um 1890",
        "1889-08-02T14:30+99:99", "1889-08-02T14:30+14:01", "1889-08-02T14:30:12.1234567Z",
    ):
        with pytest.raises(ValueError):
            bounds(value)
    with pytest.raises(ValueError, match="after"):
        interval(etree.fromstring(f'<date xmlns="{TEI_URI}" notBefore="1890" notAfter="1889"/>'))
    assert interval(etree.fromstring(f'<date xmlns="{TEI_URI}">Sonntag</date>')) is None


def test_dates_with_offsets_compare_as_instants_and_floating_dates_are_not_assumed_utc():
    earlier = interval(etree.fromstring('<date notBefore="2020-01-01T00:30+02:00"/>'))
    later_limit = interval(etree.fromstring('<date notAfter="2019-12-31T23:45+00:00"/>'))
    combined = intersect([earlier, later_limit])
    assert combined.begin == "2020-01-01T00:30:00+02:00"
    assert combined.end == "2019-12-31T23:45:59+00:00"
    with pytest.raises(ValueError, match="without a timezone"):
        interval(etree.fromstring('<date notBefore="2020-01-01T00:30Z" notAfter="2020-01-01"/>'))
    with pytest.raises(ValueError, match="without a timezone"):
        intersect([earlier, interval(etree.fromstring('<date when="2020-01-01"/>'))])


def test_several_dates_of_one_action_are_intersected_or_reported(tmp_path):
    header = ('<profileDesc><correspDesc><correspAction type="sent"><date when="1889-08"/><date notBefore="1889-08-10"/></correspAction>'
              '<correspAction type="received"><date when="1889"/><date when="1890"/></correspAction></correspDesc></profileDesc>')
    result, _, graph, _ = run(tmp_path, write(tmp_path, tei("<p>x</p>", header)))
    span = URIRef(BASE + "event/x/sent-1/time")
    assert set(graph.objects(span, CRM.P82a_begin_of_the_begin)) == {Literal("1889-08-10T00:00:00", datatype=XSD.dateTime)}
    assert set(graph.objects(span, CRM.P82b_end_of_the_end)) == {Literal("1889-08-31T23:59:59", datatype=XSD.dateTime)}
    assert not list(graph.triples((URIRef(BASE + "event/x/received-1/time"), None, None)))
    assert any("exclude each other" in w for w in result.warnings)


def test_invalid_dates_and_unmapped_actions_are_reported(tmp_path):
    header = ('<profileDesc><correspDesc><correspAction type="sent"><date when="1889-02-30"/></correspAction>'
              '<correspAction type="transmitted"><persName>Bote</persName></correspAction></correspDesc></profileDesc>')
    result, _, graph, _ = run(tmp_path, write(tmp_path, tei("<p>x</p>", header)))
    assert result.events == 1
    assert any("1889-02-30" in w for w in result.warnings) and any("transmitted" in w for w in result.warnings)
    assert not list(graph.triples((None, CRM["P4_has_time-span"], None)))


def test_existing_references_are_protected_and_resolved(tmp_path):
    source = write(tmp_path, f"""<TEI xmlns="{TEI_URI}" xml:id="brief" xml:base="https://edition.example/letters">
      <teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>
      <text><body><p><rs type="person" ref="#p1">Goethe</rs> las ein <rs type="work" ref="#w1">Buch über Schiller</rs>
      in <persName ref="https://d-nb.info/gnd/118540238 #p1">Goethe</persName>, bei <rs type="person" ref="#p1 #p2">Goethes</rs>
      und <rs type="place" ref="#missing">Jena</rs>, <rs type="org" ref="#o1">Verein</rs>, <persName ref="register.xml#p9">Knebel</persName>.</p></body>
      <back><listPerson><person xml:id="p1"><persName><forename>Johann Wolfgang</forename> <surname>Goethe</surname></persName>
      <idno type="URL" subtype="wikidata">http://www.wikidata.org/entity/Q5879</idno><idno type="URL" subtype="www">https://example.org</idno></person>
      <person xml:id="p2"><persName>Christiane Vulpius</persName></person></listPerson>
      <listOrg><org xml:id="o1"><orgName>Verein</orgName><location><placeName ref="#w"/><idno subtype="wikidata">http://www.wikidata.org/entity/Q1741</idno></location></org></listOrg>
      <listBibl><bibl xml:id="w1"><title>Buch</title></bibl></listBibl></back></text></TEI>""")
    result, tree, graph, _ = run(tmp_path, source)
    assert tree.xpath("count(//tei:rs[@type='person']//tei:persName)", namespaces=NS) == 0
    assert tree.xpath("count(//tei:rs[@type='work']/tei:persName)", namespaces=NS) == 1  # names may sit in work references
    goethe, vulpius = URIRef("https://edition.example/letters#p1"), URIRef("https://edition.example/letters#p2")
    assert (goethe, RDFS.label, Literal("Johann Wolfgang Goethe")) in graph
    assert (goethe, RDFS.seeAlso, URIRef("http://www.wikidata.org/entity/Q5879")) in graph
    assert not list(graph.triples((goethe, RDFS.seeAlso, URIRef("https://example.org"))))
    assert (goethe, RDFS.seeAlso, URIRef("https://d-nb.info/gnd/118540238")) in graph
    document = URIRef(BASE + "document/brief")
    assert {(document, CRM.P67_refers_to, goethe), (document, CRM.P67_refers_to, vulpius)} <= set(graph)  # plural reference
    assert not list(graph.triples((goethe, RDFS.seeAlso, vulpius)))
    assert not list(graph.triples((URIRef("https://edition.example/letters#o1"), RDFS.seeAlso, None)))  # Vienna's idno is the place's
    assert (document, CRM.P67_refers_to, URIRef("https://edition.example/register.xml#p9")) in graph  # relative, via xml:base
    assert any("#missing" in warning for warning in result.warnings)
    assert list(graph.triples((None, VOCAB.unresolvedRef, Literal("#missing"))))


def test_prefix_definitions_expand_once_and_bad_ones_warn(tmp_path):
    header = ('<encodingDesc><listPrefixDef><prefixDef ident="gnd" matchPattern="(.*)" replacementPattern="https://d-nb.info/gnd/$1"/>'
              '<prefixDef ident="reg" matchPattern="([a-z0-9]+)" replacementPattern="#$1"/>'
              '<prefixDef ident="bad" matchPattern="(\\p{L}+)" replacementPattern="x$1"/></listPrefixDef></encodingDesc>')
    body = '<p><persName ref="gnd:118540238">Goethe</persName> und <persName ref="reg:p1">Schiller</persName></p>'
    back = '<back><listPerson><person xml:id="p1"><persName>Friedrich Schiller</persName></person></listPerson></back>'
    result, _, graph, _ = run(tmp_path, write(tmp_path, tei(body, header, back)))
    assert (URIRef("https://d-nb.info/gnd/118540238"), RDF.type, CRM.E21_Person) in graph
    assert (URIRef(BASE + "document/x/tei#p1"), RDFS.label, Literal("Friedrich Schiller")) in graph
    assert any("bad" in w for w in result.warnings)


def test_invalid_uris_become_unresolved_instead_of_breaking_turtle(tmp_path):
    body = '<p><persName ref="https://d-nb.info/gnd/118607626 (GND)">Schiller</persName></p>'
    _, _, graph, _ = run(tmp_path, write(tmp_path, tei(body)))
    assert list(graph.triples((None, VOCAB.unresolvedRef, Literal("(GND)"))))
    assert (URIRef("https://d-nb.info/gnd/118607626"), RDF.type, CRM.E21_Person) in graph


def test_reprocessing_keeps_suggestions_as_suggestions(tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    run(first, ROOT / "examples/letter.xml")
    result, tree, graph, _ = run(tmp_path, first / "out.xml")
    assert (result.editorial, result.earlier, result.inline) == (1, 5, 0)
    assert set(graph.objects(URIRef(BASE + "document/letter-001"), CRM.P67_refers_to)) == {URIRef(BASE + "document/letter-001/tei#weimar")}
    earlier_annotations = 0
    for annotation in graph.subjects(VOCAB.origin, VOCAB.automatic):
        [candidate] = graph.objects(annotation, OA.hasBody)
        assert (candidate, RDF.type, VOCAB.Candidate) in graph
        assert graph.value(candidate, VOCAB.suggestedClass) in {CRM.E21_Person, CRM.E53_Place, CRM.E74_Group}
        if graph.value(annotation, URIRef(PROV + "wasGeneratedBy")) is None:
            earlier_annotations += 1
            assert (annotation, URIRef(PROV + "wasAttributedTo"), URIRef(BASE + "document/letter-001/tei#tcb-run")) in graph
    assert earlier_annotations == result.earlier
    assert tree.xpath("count(//tei:persName//tei:persName | //tei:placeName//tei:placeName)", namespaces=NS) == 0


def test_floating_text_is_read_once(tmp_path):
    body = ('<div><p>Ich lege den Brief bei.</p><floatingText><body><div><p>Schiller wohnt in Jena.</p></div></body></floatingText></div>'
            '<p>Er schrieb: <floatingText><body><p>Goethe in Weimar.</p></body></floatingText> Ende</p>')
    result, _, graph, _ = run(tmp_path, write(tmp_path, tei(body)))
    assert (result.blocks, result.editorial, result.inline) == (3, 0, 4)
    assert not list(graph.triples((None, CRM.P67_refers_to, None)))


def test_undeclared_entities_are_an_error_not_silent_text_loss(tmp_path):
    declared = write(tmp_path, f'<!DOCTYPE TEI [<!ENTITY uuml "&#252;">]><TEI xmlns="{TEI_URI}"><text><body><p>M&uuml;nchen und Jena</p></body></text></TEI>')
    result, tree, _, _ = run(tmp_path, declared)
    assert "München" in "".join(tree.getroot().itertext()) and result.inline == 1
    undeclared = write(tmp_path, f'<!DOCTYPE TEI SYSTEM "tei_all.dtd"><TEI xmlns="{TEI_URI}"><text><body><p>Wien&mdash;Jena</p></body></text></TEI>', "u.xml")
    with pytest.raises((ValueError, etree.XMLSyntaxError)):
        run(tmp_path, undeclared)


def test_names_are_split_at_tei_line_boundaries():
    root = etree.fromstring(f'<TEI xmlns="{TEI_URI}"><text><body><address><addrLine>Hrn</addrLine><addrLine>Felix Braun</addrLine>'
                            '<addrLine>Wien XIX</addrLine></address></body></text></TEI>')
    projection = project(find_blocks(root)[0])
    assert projection.text.startswith("Hrn\nFelix Braun\nWien XIX")
    pieces = _pieces(Entity(0, 15, "PER", 0.9, "m"), projection)
    assert [projection.text[p.start:p.end] for p in pieces] == ["Felix Braun"]  # the honorific alone is no name
    root = etree.fromstring(f'<TEI xmlns="{TEI_URI}"><text><body><p>M Brandes\nDem Hotel</p></body></text></TEI>')
    projection = project(find_blocks(root)[0])
    assert _pieces(Entity(0, 13, "PER", 0.9, "m"), projection) == [Entity(0, 13, "PER", 0.9, "m")]  # a source newline is text


def test_turtle_output_is_reproducible(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    for folder in (first, second):
        folder.mkdir()
        enrich(ROOT / "examples/letter.xml", folder / "o.xml", folder / "o.ttl", GlossaryRecognizer(ROOT / "examples/glossary.json"), BASE)
    assert (first / "o.ttl").read_bytes() == (second / "o.ttl").read_bytes()


def test_no_invented_event_and_escaped_text(tmp_path):
    source = write(tmp_path, f'<TEI xmlns="{TEI_URI}" xml:id="x"><text><body><p>Goethe &amp; Schiller in Jena.</p></body></text></TEI>')
    result, tree, graph, _ = run(tmp_path, source)
    assert result.events == 0
    assert not list(graph.subjects(RDF.type, CRM.E7_Activity))
    assert "Goethe & Schiller in Jena." == "".join(tree.xpath(".//tei:p", namespaces=NS)[0].itertext())


def test_rejects_non_tei_namespace(tmp_path):
    with pytest.raises(ValueError, match="official namespace"):
        run(tmp_path, write(tmp_path, '<TEI xmlns="http://tei-c.org"><text/></TEI>'))


def test_same_surface_in_different_documents_has_separate_uri(tmp_path):
    uris = []
    for doc_id in ("a", "b"):
        source = write(tmp_path, f'<TEI xmlns="{TEI_URI}" xml:id="{doc_id}"><text><body><p>Goethe.</p></body></text></TEI>', f"{doc_id}.xml")
        _, _, graph, _ = run(tmp_path, source)
        uris.append(next(graph.subjects(RDFS.label, Literal("Goethe"))))
    assert uris[0] != uris[1]


def test_preview_shows_origin_standoff_and_change_notice(tmp_path):
    header = '<publicationStmt><availability><licence target="javascript:alert(1)">x</licence></availability></publicationStmt>'
    source = write(tmp_path, tei('<p><persName>Goethe</persName> in Jena</p>').replace("</titleStmt>", "</titleStmt>" + header, 1))
    outputs = [tmp_path / name for name in ("e#1.xml", "e.ttl", "e.mentions.json", "e.html")]
    result = enrich(source, outputs[0], outputs[1], GlossaryRecognizer(ROOT / "examples/glossary.json"), BASE, output_json=outputs[2])
    write_preview(*outputs, result)
    html = outputs[3].read_text(encoding="utf-8")
    assert 'data-origin="automatic"' in html and 'data-origin="editorial"' in html
    assert 'href="e%231.xml"' in html and 'href="e.ttl"' in html
    assert '<link rel="alternate" type="text/turtle" href="e.ttl"' in html
    assert 'href="javascript' not in html and "Content-Security-Policy" in html
    assert "maschinell bearbeitet" in html and "ursprüngliche Auszeichnung" in html


def test_unwrap_is_inverse_of_insertion(tmp_path):
    source = ROOT / "examples/letter.xml"
    _, tree, _, _ = run(tmp_path, source)
    root = tree.getroot()
    for node in root.xpath("//tei:body//*[@resp='#tcb-run']", namespaces=NS):
        unwrap(node)
    body = etree.tostring(root.find(f"{{{TEI_URI}}}text"))
    assert body == etree.tostring(etree.parse(str(source)).getroot().find(f"{{{TEI_URI}}}text"))
