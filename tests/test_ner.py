import pytest

from tei_crm_bridge.ner import (
    Entity, GlossaryRecognizer, HuggingFaceRecognizer, IncompleteCoverage, check_coverage, drop_window_fragments,
    label_mapping, resolve_overlaps,
)


def test_overlaps_prefer_score_then_length_and_ignore_threshold_for_unscored():
    text = "Universität Jena"
    items = [
        Entity(12, 16, "LOC", 0.99, "m"),
        Entity(0, 16, "ORG", 0.90, "m"),
        Entity(0, 11, "ORG", 0.50, "m"),
    ]
    assert resolve_overlaps(items, text, 0.85) == [Entity(12, 16, "LOC", 0.99, "m")]
    unscored = [Entity(12, 16, "LOC", None, "g"), Entity(0, 16, "ORG", None, "g")]
    assert resolve_overlaps(unscored, text, 0.99) == [Entity(0, 16, "ORG", None, "g")]


def test_invalid_offsets_and_kinds_are_dropped():
    assert resolve_overlaps([Entity(3, 99, "PER", 1.0, "m"), Entity(0, 2, "TIME", 1.0, "m")], "abcdef", 0) == []


def test_glossary_has_no_confidence_and_describes_itself(tmp_path):
    path = tmp_path / "g.json"
    path.write_text('{"PER": ["Goethe"], "LOC": ["Jena"]}', encoding="utf-8")
    recognizer = GlossaryRecognizer(path)
    assert [(e.kind, e.score) for e in recognizer.find("Goethe in Jena, nicht Goethes")] == [("PER", None), ("LOC", None)]
    description = recognizer.describe()
    assert description["engine"] == "glossary" and len(description["glossarySha256"]) == 64


@pytest.mark.parametrize("content", ['["Goethe"]', '{"NAME": ["Goethe"]}', '{"PER": [""]}'])
def test_glossary_validation(tmp_path, content):
    path = tmp_path / "g.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        GlossaryRecognizer(path)


def test_coverage_accepts_overlapping_windows_and_rejects_gaps():
    text = "a" * 100
    check_coverage(text, [(0, 60), (40, 100)])
    check_coverage("  \n ", [])
    check_coverage("\u00adabc\u200b", [(1, 4)], content=(1, 4))  # characters the tokenizer drops need no window
    with pytest.raises(IncompleteCoverage, match="60–70"):
        check_coverage(text, [(0, 60), (70, 100)])
    with pytest.raises(IncompleteCoverage, match="80–100"):
        check_coverage(text, [(0, 80)])  # silent truncation of the tail


class _FakePipeline:
    def __init__(self, items):
        self.items = items

    def __call__(self, text):
        return self.items


def _recognizer(items, windows):
    recognizer = object.__new__(HuggingFaceRecognizer)
    recognizer.model_id, recognizer.revision, recognizer.resolved_revision = "fake/model", "abc", "abc"
    recognizer.stride, recognizer.aggregation = 128, "first"
    recognizer.labels = label_mapping(["O", "B-pers", "I-pers", "B-loc", "B-org", "B-time"])
    recognizer.pipeline = _FakePipeline(items)
    recognizer.windows = lambda text: windows
    recognizer.content = lambda text: (len(text) - len(text.lstrip()), len(text.rstrip())) if text.strip() else None
    return recognizer


def test_huggingface_mapping_merges_duplicate_window_hits():
    text = "Goethe in Weimar"
    items = [
        {"entity_group": "pers", "score": 0.91, "start": 0, "end": 6},
        {"entity_group": "pers", "score": 0.97, "start": 0, "end": 6},  # same span from the next window
        {"entity_group": "loc", "score": 0.88, "start": 10, "end": 16},
        {"entity_group": "time", "score": 0.99, "start": 7, "end": 9},
    ]
    found = _recognizer(items, [(0, 16)]).find(text)
    assert [(e.start, e.end, e.kind, e.score) for e in found] == [(0, 6, "PER", 0.97), (10, 16, "LOC", 0.88)]


def test_huggingface_refuses_incomplete_windows():
    with pytest.raises(IncompleteCoverage):
        _recognizer([], [(0, 5)]).find("Goethe in Weimar")
    assert _recognizer([], []).find("   ") == []


def test_label_sets_of_other_models_are_mapped_or_rejected():
    assert label_mapping(["O", "B-PER", "I-PER", "B-LOC", "B-ORG", "B-MISC"]) == {"per": "PER", "loc": "LOC", "org": "ORG"}
    with pytest.warns(UserWarning, match="colour"):
        label_mapping(["B-PER", "B-COLOUR"])
    with pytest.raises(ValueError):
        label_mapping(["O", "B-MISC"])


def test_window_edge_fragments_yield_to_the_whole_name():
    whole, fragment = Entity(95, 112, "PER", 0.90, "m"), Entity(95, 100, "PER", 0.99, "m")
    assert drop_window_fragments([whole, fragment], [(0, 100), (60, 160)]) == [whole]
    alone = Entity(40, 100, "LOC", 0.9, "m")  # ends at the edge, but no rival: kept
    assert drop_window_fragments([alone], [(0, 100), (60, 160)]) == [alone]
    assert drop_window_fragments([fragment], [(0, 200)]) == [fragment]


def test_huggingface_describe_records_the_revision():
    description = _recognizer([], []).describe()
    assert description["modelRevision"] == "abc" and description["engine"] == "hf"
