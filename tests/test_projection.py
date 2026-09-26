import pytest
from lxml import etree

from tei_crm_bridge.projection import find_blocks, project, string_value, xpath_of

TEI_NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def block(xml: str):
    root = etree.fromstring(f"<TEI {TEI_NS}><text><body>{xml}</body></text></TEI>")
    return find_blocks(root)[0]


def test_inline_markup_keeps_sentence_context():
    projection = project(block("<p>Schiller schrieb aus <hi>Jena</hi> an Goethe.</p>"))
    assert projection.text == "Schiller schrieb aus Jena an Goethe."
    start = projection.text.index("Jena")
    segment = projection.single_segment(start, start + 4)
    assert etree.QName(segment.owner).localname == "hi" and segment.slot == "text"


def test_character_markup_stays_inside_the_word():
    projection = project(block('<p>Ro<c rendition="#langesS">s</c>a kam.</p>'))
    assert projection.text == "Rosa kam."
    assert projection.single_segment(0, 4) is None  # spans three text slots


@pytest.mark.parametrize("xml, expected", [
    ("<p>Frankfurter<lb/>Zeitung</p>", "Frankfurter Zeitung"),
    ("<p>Frankfurter <lb/>Zeitung</p>", "Frankfurter Zeitung"),
    ('<p>Schil<lb break="no"/>ler</p>', "Schiller"),
    ('<p>Wien<space unit="chars" quantity="3"/>Graben</p>', "Wien Graben"),
    ('<p><pb n="2"/>Anfang</p>', "Anfang"),
])
def test_breaks_and_spaces(xml, expected):
    assert project(block(xml)).text == expected


def test_notes_deletions_and_comments_are_not_reading_text():
    projection = project(block("<p>A <note>Goethe</note>B <del>Goethe</del>C<!-- Goethe -->D</p>"))
    assert projection.text == "A B CD"
    assert "Goethe" not in projection.text


def test_choice_reading_is_selectable():
    xml = "<p>an <choice>\n <sic>Göthe</sic>\n <corr>Goethe</corr>\n</choice>.</p>"
    assert project(block(xml)).text == "an Goethe."
    assert project(block(xml), "diplomatic").text == "an Göthe."
    abbreviation = "<p><choice><abbr>Hofr.</abbr><expan>Hofrath</expan></choice> Schiller</p>"
    assert project(block(abbreviation)).text == "Hofrath Schiller"
    with pytest.raises(ValueError):
        project(block(xml), "normalized")


def test_existing_references_are_annotations():
    projection = project(block(
        '<p><rs type="person" ref="#p1">Goethe</rs> las <rs type="work">Werther</rs> in <placeName>Weimar</placeName>.</p>'
    ))
    kinds = [(projection.text[a.start:a.end], a.kind) for a in projection.annotations]
    assert kinds == [("Goethe", "PER"), ("Werther", None), ("Weimar", "LOC")]
    assert projection.protected(0, 6)
    werther = projection.text.index("Werther")
    assert not projection.protected(werther, werther + 7)  # a work reference may contain names


def test_lines_of_opener_and_letterhead_columns_are_separated():
    xml = (
        '<opener><seg type="letterhead"><seg rend="left">Redaction.</seg><seg rend="right">Frankfurt a. M.</seg></seg>'
        '<dateline>Wien, 2. Mai</dateline><salute>Lieber Freund!</salute></opener>'
    )
    text = project(block(xml)).text
    assert "Redaction.\nFrankfurt a. M." in text
    assert "Mai\nLieber" in text
    closer = project(block('<closer>Herzlich<c rendition="#langesS">s</c>t Ihr <signed>Arth</signed></closer>')).text
    assert closer.startswith("Herzlichst Ihr Arth")


def test_raw_offsets_follow_the_xpath_string_value():
    node = block("<p>Er <note>(Kommentar)</note>traf <hi>Rosa</hi> in <del>X</del>Wien.</p>")
    projection = project(node)
    raw = string_value(node)
    for segment in projection.segments:
        piece = getattr(segment.owner, segment.slot)[segment.offset:segment.offset + segment.end - segment.start]
        assert raw[segment.raw:segment.raw + len(piece)] == piece
        assert projection.text[segment.start:segment.end] == piece
    start = projection.text.index("Wien")
    first, last = projection.raw_span(start, start + 4)
    assert raw[first:last] == "Wien"


def test_blocks_are_outermost_and_skip_notes():
    root = etree.fromstring(
        f"<TEI {TEI_NS}><text><body><div><opener><salute>Lieber</salute></opener>"
        "<p>Text<note><p>Kommentar</p></note></p><closer><signed>A.</signed></closer>"
        "<address><addrLine>Wien</addrLine></address></div></body></text></TEI>"
    )
    names = [etree.QName(b).localname for b in find_blocks(root)]
    assert names == ["opener", "p", "closer", "address"]
    assert xpath_of(find_blocks(root)[1]) == "/tei:TEI/tei:text[1]/tei:body[1]/tei:div[1]/tei:p[1]"


def test_break_no_joins_across_whitespace():
    node = block('<p>Schil-\n   <lb break="no"/>\n   ler kam</p>')
    projection = project(node)
    assert projection.text == "Schil-ler kam"
    raw = string_value(node)
    for segment in projection.segments:
        piece = getattr(segment.owner, segment.slot)[segment.offset:segment.offset + segment.end - segment.start]
        assert raw[segment.raw:segment.raw + len(piece)] == piece


def test_apparatus_reads_one_reading_and_never_a_note():
    assert project(block("<p><app><rdgGrp><lem>Weimar</lem><rdg>Weymar</rdg></rdgGrp><rdg>Jena</rdg></app></p>")).text == "Weimar"
    assert project(block("<p><app><note>Kommentar</note><rdg>Weymar</rdg><rdg>Weimar</rdg></app></p>")).text == "Weymar"


def test_non_transcriptional_content_is_not_read():
    text = project(block('<p>Goethe<index><term>Goethe, J. W.</term></index> kam <gap reason="illegible"><desc>zwei Wörter</desc></gap>'
                         ' an<certainty locus="value"><desc>unsicher</desc></certainty>.</p>')).text
    assert text == "Goethe kam  an."


def test_place_name_parts_are_existing_references():
    projection = project(block('<p>in <settlement ref="#w">Wien</settlement> und <country>Österreich</country></p>'))
    assert [(projection.text[a.start:a.end], a.kind) for a in projection.annotations] == [("Wien", "LOC"), ("Österreich", "LOC")]
    assert projection.protected(3, 7)
