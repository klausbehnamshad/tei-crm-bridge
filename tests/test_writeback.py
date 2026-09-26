import copy

import pytest
from lxml import etree

from tei_crm_bridge.ner import Entity
from tei_crm_bridge.projection import find_blocks, project
from tei_crm_bridge.writeback import XML_ID, IdMinter, IntegrityError, add_application, place, unwrap, verify

TEI_NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def document(body: str, header: str = ""):
    return etree.fromstring(f'<TEI {TEI_NS} xml:id="d">{header}<text><body>{body}</body></text></TEI>')


def entity(projection, surface, kind="PER"):
    start = projection.text.index(surface)
    return Entity(start, start + len(surface), kind, 0.99, "test")


def test_single_slot_entities_become_inline_elements():
    root = document('<p>Schiller schrieb aus <hi>Jena</hi> an Goethe.</p>')
    original = copy.deepcopy(root)
    projection = project(find_blocks(root)[0])
    mentions = place(projection, 0, [entity(projection, "Schiller"), entity(projection, "Jena", "LOC"), entity(projection, "Goethe")], IdMinter(root))
    assert all(m.element is not None for m in mentions)
    body = etree.tostring(root.find(".//{*}p"), encoding=str)
    assert '<hi><placeName xml:id="tcb-n2">Jena</placeName></hi>' in body
    verify(original, root, [m.element for m in mentions], "edited")


def test_entities_across_element_boundaries_stay_standoff():
    root = document('<p>Ro<c rendition="#langesS">s</c>a und Schil<lb break="no"/>ler</p>')
    original = copy.deepcopy(root)
    projection = project(find_blocks(root)[0])
    mentions = place(projection, 0, [entity(projection, "Rosa"), entity(projection, "Schiller")], IdMinter(root))
    assert [m.element for m in mentions] == [None, None]
    assert etree.tostring(root) == etree.tostring(original)


def test_no_name_inside_character_markup():
    root = document('<p>Stadt <c rendition="#x">Wien</c></p>')
    projection = project(find_blocks(root)[0])
    [mention] = place(projection, 0, [entity(projection, "Wien", "LOC")], IdMinter(root))
    assert mention.element is None


def test_tail_slot_and_comment_tail():
    root = document("<p><hi>Brief</hi> an Goethe<!-- x --> und Schiller.</p>")
    original = copy.deepcopy(root)
    projection = project(find_blocks(root)[0])
    mentions = place(projection, 0, [entity(projection, "Goethe"), entity(projection, "Schiller")], IdMinter(root))
    assert [m.element.text for m in mentions] == ["Goethe", "Schiller"]
    verify(original, root, [m.element for m in mentions], "edited")


def test_ids_do_not_collide_with_existing_ones():
    root = document('<p xml:id="tcb-n1">Goethe</p>')
    ids = IdMinter(root)
    assert ids.next() == "tcb-n2"
    assert ids.reserve("tcb-run") == "tcb-run"
    assert ids.reserve("tcb-run") == "tcb-run-2"


def test_verify_detects_changed_text_and_markup():
    root = document('<p xml:id="a" rend="x">Goethe in Jena</p>')
    original = copy.deepcopy(root)
    changed = copy.deepcopy(root)
    changed.find(".//{*}p").text = "Goethe in Weimar"
    with pytest.raises(IntegrityError, match="reading text"):
        verify(original, changed, [], "edited")
    attribute = copy.deepcopy(root)
    del attribute.find(".//{*}p").attrib["rend"]
    with pytest.raises(IntegrityError, match="existing"):
        verify(original, attribute, [], "edited")


def test_unwrap_restores_text_around_children():
    root = etree.fromstring("<p>a <x>b <y>c</y> d</x> e</p>")
    unwrap(root.find("x"))
    assert etree.tostring(root, encoding=str) == "<p>a b <y>c</y> d e</p>"


def test_application_is_documented_in_the_header():
    root = document("<p>x</p>", "<teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc><profileDesc/></teiHeader>")
    assert add_application(root, "tcb-run", "0.2.0", "Test")
    header = root.find("{*}teiHeader")
    assert [etree.QName(child).localname for child in header] == ["fileDesc", "encodingDesc", "profileDesc"]
    application = header.find(".//{*}application")
    assert application.get("ident") == "tei-crm-bridge" and application.get(XML_ID) == "tcb-run"
    assert not add_application(document("<p>x</p>"), "tcb-run", "0.2.0", "Test")


def test_no_tei_names_in_foreign_namespace_content():
    root = document('<p>Formel <m:math xmlns:m="http://www.w3.org/1998/Math/MathML"><m:mi>Goethe</m:mi></m:math></p>')
    projection = project(find_blocks(root)[0])
    [mention] = place(projection, 0, [entity(projection, "Goethe")], IdMinter(root))
    assert mention.element is None


def test_insertion_after_joined_whitespace_uses_the_slot_offset():
    root = document('<p>Herr Schil<lb break="no"/>\n  ler und Goethe</p>')
    original = copy.deepcopy(root)
    projection = project(find_blocks(root)[0])
    assert projection.text == "Herr Schiller und Goethe"
    [mention] = place(projection, 0, [entity(projection, "Goethe")], IdMinter(root))
    assert mention.element.text == "Goethe" and mention.element.getprevious().tail == "\n  ler und "
    verify(original, root, [mention.element], "edited")
