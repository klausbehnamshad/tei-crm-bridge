"""Integration tests with the pinned Impresso model (about 400 MB, not run in CI).

    pip install -e '.[ner,test]'
    TCB_MODEL_TESTS=1 pytest -m integration
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("TCB_MODEL_TESTS") != "1", reason="set TCB_MODEL_TESTS=1 to run model tests"),
]


@pytest.fixture(scope="module")
def recognizer():
    from tei_crm_bridge.ner import HuggingFaceRecognizer

    return HuggingFaceRecognizer(local_files_only=os.environ.get("TCB_ONLINE") != "1")


def test_sentence_context_decides_the_type(recognizer):
    alone = recognizer.find("Jena")
    in_context = recognizer.find("Friedrich Schiller schrieb aus Jena an Goethe.")
    assert ("Jena", "LOC") in [("Friedrich Schiller schrieb aus Jena an Goethe."[e.start:e.end], e.kind) for e in in_context]
    assert not [e for e in alone if e.kind == "LOC" and e.score >= 0.85]


def test_long_input_is_read_to_the_end(recognizer):
    sentence = "Friedrich Schiller schrieb aus Jena an Goethe. "
    text = sentence * 120
    assert len(text) == 5640
    found = recognizer.find(text)
    assert len(found) == 360
    assert max(e.end for e in found) > len(text) - len(sentence)


def test_entities_at_start_window_boundary_and_end(recognizer):
    filler = "Es regnete den ganzen Tag, und wir blieben lange im Haus. "
    base = "Goethe kam. " + filler * 60
    sentence = " Dann reisten wir nach Weimar."
    boundary = recognizer.windows(base)[0][1]
    for cut in (i for i in range(boundary, boundary - 200, -1) if base[i] == " "):
        text = base[:cut] + sentence + base[cut:] + "Zuletzt schrieb Schiller."
        name = text.index("Weimar")
        first_window_end = recognizer.windows(text)[0][1]
        if name < first_window_end < name + len("Weimar"):
            break  # the first window ends inside the name
    else:
        pytest.fail("no insertion point straddles the first window boundary")
    found = {(text[e.start:e.end], e.kind) for e in recognizer.find(text)}
    assert {("Goethe", "PER"), ("Weimar", "LOC"), ("Schiller", "PER")} <= found
