import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import evaluate  # noqa: E402
from goldlib import Span, gold_spans, strip_references  # noqa: E402

TEI_NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def test_gold_excludes_implied_and_nested_and_trims():
    root = etree.fromstring(
        f'<TEI {TEI_NS}><text><body><p><rs type="person"> Goethe </rs> und <rs type="person" subtype="implied">er</rs> '
        f'in der <rs type="org">Universität <rs type="place">Jena</rs></rs>; <rs type="work">Faust</rs>.</p></body></text></TEI>'
    )
    spans, excluded, texts = gold_spans("L1", root)
    assert [(s.text, s.kind) for s in spans] == [("Goethe", "PER"), ("Universität Jena", "ORG")]
    assert excluded == {"implied": 1, "nested": 1}
    assert texts[0].startswith(" Goethe  und er")


def test_stripping_keeps_text_and_other_references():
    root = etree.fromstring(
        f'<TEI {TEI_NS}><teiHeader><profileDesc><correspDesc><correspAction><persName>A</persName></correspAction></correspDesc></profileDesc></teiHeader>'
        f'<text><body><p>Ein <rs type="work">Buch über <rs type="person">Goethe</rs></rs> aus <placeName>Jena<c>.</c></placeName></p></body></text></TEI>'
    )
    stripped = strip_references(root)
    assert "".join(stripped.find(".//{*}p").itertext()) == "".join(root.find(".//{*}p").itertext())
    assert stripped.xpath("count(//*[local-name()='rs'])") == 1  # the work reference stays
    assert stripped.xpath("count(//*[local-name()='placeName'])") == 0
    assert stripped.xpath("count(//*[local-name()='persName'])") == 1  # header untouched


def test_overlap_matching_is_one_to_one_largest_overlap_first():
    gold = [Span("L", 0, 0, 10, "PER", "x"), Span("L", 0, 12, 20, "PER", "y")]
    one = evaluate._overlap_pairs(gold, [Span("L", 0, 5, 15, "PER", "z")])
    assert [(g.start, p.start) for g, p in one] == [(0, 5)]  # a prediction counts once
    two = evaluate._overlap_pairs(gold, [Span("L", 0, 0, 4, "PER", "a"), Span("L", 0, 6, 14, "PER", "b")])
    assert [(g.start, p.start) for g, p in two] == [(0, 0), (12, 6)]
    assert evaluate._overlap_pairs(gold, [Span("L", 0, 0, 10, "LOC", "t")]) == []  # type must agree
    result = evaluate._prf(2, 4, 2)
    assert (result["precision"], result["recall"]) == (0.5, 1.0) and abs(result["f1"] - 2 / 3) < 1e-12  # unrounded


def test_strict_matching_counts_duplicate_predictions_once():
    gold = [Span("L", 0, 0, 6, "PER", "Goethe")]
    duplicate = Span("L", 0, 0, 6, "PER", "Goethe")
    assert evaluate._strict_tp(gold, [duplicate, duplicate]) == 1
    assert evaluate._strict_tp(gold + gold, [duplicate]) == 1


def test_examples_are_spread_over_categories():
    errors = [{"category": c, "n": i} for c in ("missed", "spurious") for i in range(20)]
    picked = evaluate._examples(errors)
    assert len(picked) == 10 and {e["category"] for e in picked} == {"missed", "spurious"}
    assert [e["n"] for e in picked if e["category"] == "missed"][0] == 0


def test_spot_check_rows_are_found_in_the_current_projection():
    texts = {}
    for row in evaluate.manifest():
        _, _, texts[row["letter"]] = gold_spans(row["letter"], evaluate._corpus_root(row))
    spans, problems, letters = evaluate.spotcheck_spans(texts)
    assert problems == [] and len(spans) == 28 and len(letters) == 10
    assert all(texts[s.letter][s.block][s.start:s.end] == s.text for s in spans)


def test_v01_scope_is_text_inside_p():
    root = etree.fromstring(f'<TEI {TEI_NS}><text><body><div><postscript><p>PS Wien</p></postscript>'
                            '<closer>Gruß <signed>Arth</signed></closer></div></body></text></TEI>')
    from tei_crm_bridge.projection import find_blocks, project
    postscript, closer = (project(b) for b in find_blocks(root))
    assert evaluate._v01_scope(postscript) == set(range(len("PS Wien")))
    assert evaluate._v01_scope(closer) == set()
