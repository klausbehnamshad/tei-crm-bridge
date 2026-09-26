"""CMIF export: authority URIs, warnings, actions, dates and header."""

import sys
from pathlib import Path

from lxml import etree

from tei_crm_bridge.cli import main
from tei_crm_bridge.cmif import CmifOptions, build_cmif, export_cmif

TEI_URI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_URI}
OPTIONS = CmifOptions(
    cmif_url="https://example.org/cmif.xml",
    url_pattern="https://edition.example.org/{id}.html",
)


def letter(xml_id, actions, register="", publisher="Edition", licence_target="https://creativecommons.org/licenses/by/4.0/"):
    return (
        f'<TEI xmlns="{TEI_URI}" xml:id="{xml_id}">'
        "<teiHeader><fileDesc><titleStmt><title level=\"s\">Edition</title></titleStmt>"
        f"<publicationStmt><publisher>{publisher}</publisher>"
        f"<availability><licence target=\"{licence_target}\">Lizenz</licence></availability>"
        "</publicationStmt><sourceDesc><p>Quelle</p></sourceDesc></fileDesc>"
        f"<profileDesc><correspDesc>{actions}</correspDesc></profileDesc></teiHeader>"
        f"<text><body><back>{register}</back></body></text></TEI>")


def write(tmp_path, name, xml):
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return path


def build(xml_id, actions, register="", **options):
    root = etree.fromstring(letter(xml_id, actions, register).encode())
    merged = {**OPTIONS.__dict__, **options}
    return build_cmif([(xml_id, root)], CmifOptions(**merged))


REGISTER = (
    '<listPerson><person xml:id="p1"><persName><surname>Weber</surname></persName>'
    '<idno type="URL" subtype="d-nb">https://d-nb.info/gnd/118629662</idno></person>'
    '<person xml:id="p2"><persName><surname>Niemand</surname></persName>'
    '<idno type="URL" subtype="pmb">https://pmb.acdh.oeaw.ac.at/entity/1/</idno></person></listPerson>'
    '<listPlace><place xml:id="pl1"><placeName>Dresden</placeName>'
    '<location><idno type="URL" subtype="geonames">https://sws.geonames.org/2935022/</idno></location>'
    "</place></listPlace>")


def test_gnd_and_geonames_actions_complete():
    actions = (
        '<correspAction type="sent"><persName ref="#p1">Weber, Carl Maria von</persName>'
        '<placeName ref="#pl1">Dresden</placeName><date when="1825-05-07">7. Mai 1825</date></correspAction>'
        '<correspAction type="received"><persName ref="#p1">Weber, Carl Maria von</persName>'
        '<placeName ref="#pl1">Dresden</placeName></correspAction>')
    tree, result = build("L1", actions, REGISTER)
    assert result.warnings == ()
    assert (result.descriptions, result.actions, result.names_with_ref, result.names_without_ref) == (1, 2, 4, 0)
    descs = tree.getroot().find("tei:teiHeader/tei:profileDesc", NS).findall("tei:correspDesc", NS)
    assert len(descs) == 1
    assert descs[0].get("ref") == "https://edition.example.org/L1.html"
    assert descs[0].get("source", "").startswith("#")
    sent, received = descs[0].findall("tei:correspAction", NS)
    assert (sent.get("type"), received.get("type")) == ("sent", "received")
    assert sent.find("tei:persName", NS).get("ref") == "https://d-nb.info/gnd/118629662"
    assert sent.find("tei:placeName", NS).get("ref") == "https://sws.geonames.org/2935022/"
    assert sent.find("tei:date", NS).get("when") == "1825-05-07"


def test_non_gnd_authority_name_without_ref_and_warning():
    actions = '<correspAction type="sent"><persName ref="#p2">Niemand, N.</persName></correspAction>'
    tree, result = build("L2", actions, REGISTER)
    name = tree.getroot().find(".//tei:persName", NS)
    assert name.text == "Niemand, N." and name.get("ref") is None
    assert result.names_without_ref == 1
    assert len(result.warnings) == 1 and "Niemand, N." in result.warnings[0]


def test_direct_gnd_ref_and_date_interval_kept():
    actions = (
        '<correspAction type="sent"><persName ref="https://d-nb.info/gnd/118629662">Weber</persName>'
        '<date notBefore="1810-07-11" notAfter="1810-07-18">11. bis 18. Juli 1810</date></correspAction>')
    tree, result = build("L3", actions)
    assert result.warnings == ()
    name = tree.getroot().find(".//tei:correspAction/tei:persName", NS)
    assert name.get("ref") == "https://d-nb.info/gnd/118629662"
    date = tree.getroot().find(".//tei:correspAction/tei:date", NS)
    assert (date.get("notBefore"), date.get("notAfter")) == ("1810-07-11", "1810-07-18")


def test_other_action_types_skipped_and_empty_action_dropped():
    actions = (
        '<correspAction type="sent"><placeName>Dresden</placeName></correspAction>'
        '<correspAction type="sent"><correspContext><ref target="x">y</ref></correspContext></correspAction>'
        '<correspAction type="transmitted"><persName ref="#p1">Weber</persName></correspAction>')
    tree, result = build("L4", actions, REGISTER)
    kept = tree.getroot().findall(".//tei:correspAction", NS)
    assert [action.get("type") for action in kept] == ["sent"]
    assert kept[0].find("tei:placeName", NS).text == "Dresden"
    assert kept[0].find("tei:persName", NS) is None
    assert any("transmitted" in warning for warning in result.warnings)
    assert any("leer" in warning for warning in result.warnings)


def test_header_links_and_key_fallback(tmp_path):
    path = write(tmp_path, "L5.xml", letter("L5", '<correspAction type="sent"><persName>Weber</persName></correspAction>'))
    out = tmp_path / "cmif.xml"
    options = CmifOptions(cmif_url="https://example.org/cmif.xml", title="Index", publisher="Verlag",
                          editor="Kontakt", editor_email="k@example.org", source_type="print",
                          source_label="Gedruckte Edition")
    result = export_cmif([path], out, options)
    assert result.descriptions == 1
    root = etree.parse(str(out)).getroot()
    assert root.find(".//tei:titleStmt/tei:title", NS).text == "Index"
    assert root.find(".//tei:publicationStmt/tei:publisher", NS).text == "Verlag"
    idno = root.find(".//tei:publicationStmt/tei:idno", NS)
    assert idno.text == "https://example.org/cmif.xml" and idno.get("type") == "url"
    bibl = root.find(".//tei:sourceDesc/tei:bibl", NS)
    assert bibl.get("type") == "print" and bibl.text == "Gedruckte Edition"
    desc = root.find(".//tei:correspDesc", NS)
    assert desc.get("key") == "L5" and desc.get("ref") is None
    assert desc.get("source") == "#" + bibl.get("{http://www.w3.org/XML/1998/namespace}id")


def test_cli_cmif_subcommand(tmp_path, monkeypatch, capsys):
    write(tmp_path, "L6.xml", letter("L6", '<correspAction type="sent"><persName>Weber</persName></correspAction>'))
    out = tmp_path / "cmif.xml"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "cmif", str(tmp_path / "L6.xml"), "--out", str(out),
                                      "--url-pattern", "https://edition.example.org/{id}.html",
                                      "--cmif-url", "https://example.org/cmif.xml"])
    main()
    assert out.is_file()
    assert Path(str(out)).read_text(encoding="utf-8").count("<correspDesc") == 1
    assert "descriptions" in capsys.readouterr().out


def test_cli_cmif_creates_missing_out_parents(tmp_path, monkeypatch, capsys):
    write(tmp_path, "L7.xml", letter("L7", '<correspAction type="sent"><persName>Weber</persName></correspAction>'))
    out = tmp_path / "a" / "b" / "cmif.xml"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "cmif", str(tmp_path / "L7.xml"), "--out", str(out),
                                      "--url-pattern", "https://edition.example.org/{id}.html",
                                      "--cmif-url", "https://example.org/cmif.xml"])
    main()
    assert out.is_file()
    assert etree.parse(str(out)).getroot() is not None


ORG_REGISTER = ('<listOrg><org xml:id="o1"><orgName>Verein</orgName>'
                '<location type="located_in_place">'
                '<idno type="URL" subtype="d-nb">https://d-nb.info/gnd/4066009-6</idno>'
                "</location></org></listOrg>"
                '<listPlace><place xml:id="pl1"><placeName>Dorf</placeName>'
                '<location><idno type="URL" subtype="geonames">https://sws.geonames.org/222/</idno></location>'
                "</place></listPlace>")


def test_located_in_place_idno_is_not_the_orgs_own():
    actions = ('<correspAction type="sent"><orgName ref="#o1">Verein</orgName>'
               '<placeName ref="#pl1">Dorf</placeName></correspAction>')
    tree, result = build("L8", actions, ORG_REGISTER)
    sent = tree.getroot().find(".//tei:correspAction", NS)
    assert sent.find("tei:orgName", NS).get("ref") is None  # superordinate place, not the org
    assert sent.find("tei:placeName", NS).get("ref") == "https://sws.geonames.org/222/"
    cache = {"entries": {"o1": {"gnd": "https://d-nb.info/gnd/118514326"}}}
    tree, result = build("L8", actions, ORG_REGISTER, reconciliation=cache)
    sent = tree.getroot().find(".//tei:correspAction", NS)
    assert sent.find("tei:orgName", NS).get("ref") == "https://d-nb.info/gnd/118514326"
