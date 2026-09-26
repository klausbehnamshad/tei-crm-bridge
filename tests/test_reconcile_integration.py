"""Live PMB reconciliation (network, not run in CI).

    TCB_PMB_TESTS=1 pytest -m integration
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("TCB_PMB_TESTS") != "1", reason="set TCB_PMB_TESTS=1 to run PMB tests"),
]


def test_pmb2121_resolves_schnitzler():
    from tei_crm_bridge.reconcile import PmbResolver

    links = PmbResolver(delay=0).resolve("person", "pmb2121", "Schnitzler, Arthur")
    assert links.gnd == "https://d-nb.info/gnd/118609807"
    assert links.wikidata == "http://www.wikidata.org/entity/Q44331"


def test_pmb50_resolves_wien():
    from tei_crm_bridge.reconcile import PmbResolver

    links = PmbResolver(delay=0).resolve("place", "pmb50", "Wien")
    assert links.geonames == "https://sws.geonames.org/2761369/"
