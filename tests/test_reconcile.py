"""Authority reconciliation: cache fill and cache consumption, fully offline."""

import email.message
import http.client
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request

import pytest
from lxml import etree
from rdflib import OWL, RDFS

import tei_crm_bridge.reconcile as reconcile_module
from tei_crm_bridge.cli import main
from tei_crm_bridge.cmif import CmifOptions, build_cmif
from tei_crm_bridge.rdf import GraphBuilder, reconciled_uris
from tei_crm_bridge.reconcile import (
    ApiDriftError,
    AuthorityLinks,
    PmbResolver,
    ResolverError,
    collect_entities,
    links_for,
    load_cache,
    new_cache,
    pick_links,
    save_cache,
    summarize,
    tls_context,
    update_cache,
)

TEI_URI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_URI}


class FakeResolver:
    name = "fake"

    def __init__(self, links, fail=()):
        self.links = links
        self.fail = set(fail)
        self.calls = []

    def supports(self, kind, local_id):
        return True

    def resolve(self, kind, local_id, label):
        self.calls.append((kind, local_id))
        if local_id in self.fail:
            raise ResolverError("boom")
        return self.links.get(local_id, AuthorityLinks())


def letter(xml_id, actions, register=""):
    return (
        f'<TEI xmlns="{TEI_URI}" xml:id="{xml_id}">'
        "<teiHeader><fileDesc><titleStmt><title level=\"s\">Edition</title></titleStmt>"
        "<publicationStmt><publisher>Pub</publisher><availability>"
        "<licence target=\"https://creativecommons.org/licenses/by/4.0/\">L</licence>"
        "</availability></publicationStmt><sourceDesc><p>Q</p></sourceDesc></fileDesc>"
        f"<profileDesc><correspDesc>{actions}</correspDesc></profileDesc></teiHeader>"
        f"<text><body><back>{register}</back></body></text></TEI>")


def cache(entries):
    return {"resolver": "fake", "version": 1, "entries": entries}


def entry(kind, label, gnd=None, geonames=None, wikidata=None):
    return {"kind": kind, "label": label, "pmb": None, "gnd": gnd, "geonames": geonames,
            "wikidata": wikidata, "source": "fake", "retrieved": "2026-09-26"}


REGISTER = (
    '<listPerson><person xml:id="p1"><persName>Autor</persName></person></listPerson>'
    '<listPlace><place xml:id="pl1"><placeName>Dorf</placeName></place></listPlace>')

RECON = cache({
    "p1": entry("person", "Autor", gnd="https://d-nb.info/gnd/111"),
    "pl1": entry("place", "Dorf", geonames="https://sws.geonames.org/222/"),
})


def build(actions, register="", reconciliation=None):
    root = etree.fromstring(letter("L1", actions, register).encode())
    options = CmifOptions(cmif_url="https://example.org/cmif.xml", url_pattern="https://edition.example.org/{id}",
                          reconciliation=reconciliation)
    return build_cmif([("L1", root)], options)


def test_cmif_uses_cache_for_ref():
    actions = ('<correspAction type="sent"><persName ref="#p1">Autor</persName>'
               '<placeName ref="#pl1">Dorf</placeName></correspAction>')
    tree, result = build(actions, REGISTER, RECON)
    assert result.warnings == ()
    assert (result.names_with_ref, result.names_without_ref) == (2, 0)
    sent = tree.getroot().find(".//tei:correspAction", NS)
    assert sent.find("tei:persName", NS).get("ref") == "https://d-nb.info/gnd/111"
    assert sent.find("tei:placeName", NS).get("ref") == "https://sws.geonames.org/222/"


def test_register_idno_wins_over_cache():
    register = ('<listPerson><person xml:id="p1"><persName>Autor</persName>'
                '<idno subtype="gnd">https://d-nb.info/gnd/999</idno></person></listPerson>')
    actions = '<correspAction type="sent"><persName ref="#p1">Autor</persName></correspAction>'
    tree, result = build(actions, register, RECON)
    assert result.warnings == ()
    assert tree.getroot().find(".//tei:persName", NS).get("ref") == "https://d-nb.info/gnd/999"


def test_unresolved_id_has_no_ref():
    actions = '<correspAction type="sent"><persName ref="#p1">Autor</persName></correspAction>'
    tree, result = build(actions, REGISTER, cache({"p1": entry("person", "Autor")}))
    name = tree.getroot().find(".//tei:persName", NS)
    assert name.get("ref") is None
    assert result.names_without_ref == 1 and len(result.warnings) == 1


def test_update_fetches_only_missing_and_skips_failures(tmp_path):
    roots = [etree.fromstring(letter("L1", "", REGISTER).encode())]
    entities = collect_entities(roots)
    assert set(entities) == {"p1", "pl1"}
    stored = new_cache("fake")
    stored["entries"]["p1"] = entry("person", "Autor", gnd="https://d-nb.info/gnd/111")
    resolver = FakeResolver({"pl1": AuthorityLinks(geonames="https://sws.geonames.org/222/")}, fail={"p1"})
    result = update_cache(stored, entities, resolver, offline=True)
    assert (result.fetched, result.failed) == (0, 0) and resolver.calls == []
    result = update_cache(stored, entities, resolver)
    assert (result.fetched, result.failed) == (1, 0)
    assert [call[1] for call in resolver.calls] == ["pl1"]  # p1 was cached, never refetched
    assert stored["entries"]["pl1"]["geonames"] == "https://sws.geonames.org/222/"
    assert stored["entries"]["pl1"]["source"] == "fake"
    summary = summarize(entities, stored)
    assert summary["person"]["gnd"] == 1 and summary["place"]["geonames"] == 1


def test_failed_fetch_is_not_cached():
    stored, entities = new_cache("fake"), {"p1": {"kind": "person", "label": "Autor"}}
    result = update_cache(stored, entities, FakeResolver({}, fail={"p1"}))
    assert (result.fetched, result.failed) == (0, 1) and "p1" not in stored["entries"] and result.warnings


def test_invalid_uri_is_dropped():
    assert pick_links(["not a uri", "https://d-nb.info/gnd/111"]).gnd == "https://d-nb.info/gnd/111"
    assert pick_links(["http://d-nb.info/gnd/111"]).gnd == "https://d-nb.info/gnd/111"
    assert pick_links(["not a uri"]) == AuthorityLinks()
    assert reconciled_uris(cache({"p1": entry("person", "A", gnd="bogus")}), "p1") == []
    assert links_for(None, "p1") is None and links_for(cache({}), "p9") is None


def test_enrich_adds_reconciled_seealso_but_no_class():
    actions = '<correspAction type="sent"><persName ref="#p1">Autor</persName></correspAction>'
    root = etree.fromstring(letter("L1", actions, REGISTER).encode())
    node = root.find(".//{http://www.tei-c.org/ns/1.0}persName")
    builder = GraphBuilder(root, "L1", "https://example.org/", [], reconciliation=RECON)
    entities, _, _ = builder.entities_for(node, "PER", "Autor")
    assert len(entities) == 1
    seealso = set(builder.graph.objects(entities[0], RDFS.seeAlso))
    assert any(str(uri) == "https://d-nb.info/gnd/111" for uri in seealso)
    assert not list(builder.graph.triples((entities[0], OWL.sameAs, None)))


def test_cache_roundtrip_and_corrupt(tmp_path):
    path = tmp_path / "recon.json"
    path.write_text(json.dumps(RECON), encoding="utf-8")
    assert load_cache(path)["entries"]["p1"]["gnd"] == "https://d-nb.info/gnd/111"
    path.write_text("{broken", encoding="utf-8")
    try:
        load_cache(path)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupt cache must raise ValueError")


class FakeHTTP:
    """urlopen stand-in recording calls; answers are (url fragment, payload|error)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, request, timeout=None, context=None):
        self.calls.append({"url": request.full_url, "timeout": timeout, "context": context})
        for fragment, answer in self.answers:
            if fragment in request.full_url:
                if isinstance(answer, Exception):
                    raise answer
                return FakeHTTP.Response(answer)
        return FakeHTTP.Response({"sameAs": []})

    class Response:
        def __init__(self, payload):
            self.io = io.BytesIO(json.dumps(payload).encode())

        def __enter__(self):
            return self.io

        def __exit__(self, *exc):
            return False


def test_tls_context_requires_verification_without_certifi(monkeypatch):
    context = tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    monkeypatch.setitem(sys.modules, "certifi", None)
    fallback = tls_context()  # must not raise without certifi
    assert fallback.verify_mode == ssl.CERT_REQUIRED and fallback.check_hostname


def test_resolver_passes_context_and_skips_retry_on_cert_error(monkeypatch):
    http = FakeHTTP([])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    resolver = PmbResolver(delay=0)
    assert resolver.resolve("person", "pmb1", "A") == AuthorityLinks()
    assert http.calls[0]["context"] is resolver.context
    cert_error = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
    http = FakeHTTP([("entities/", cert_error)])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    try:
        resolver.resolve("person", "pmb1", "A")
    except ResolverError:
        pass
    else:
        raise AssertionError("cert error must raise ResolverError")
    assert len(http.calls) == 1


def test_update_cache_aborts_after_leading_failures():
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in range(1, 6)}
    stored = new_cache("fake")
    result = update_cache(stored, entities, FakeResolver({}, fail=set(entities)))
    assert (result.fetched, result.failed) == (0, 3)
    assert stored["entries"] == {}
    assert any("Abbruch" in warning and "2 Entities nicht versucht" in warning for warning in result.warnings)
    calls: list = []
    good = FakeResolver({"pmb2": AuthorityLinks(gnd="https://d-nb.info/gnd/2")}, fail={"pmb1"})
    original = good.resolve

    def resolve(kind, local_id, label):
        calls.append(local_id)
        return original(kind, local_id, label)

    good.resolve = resolve
    stored = new_cache("fake")
    result = update_cache(stored, entities, good)
    assert (result.fetched, result.failed) == (4, 1) and calls == [f"pmb{i}" for i in range(1, 6)]
    assert stored["entries"]["pmb2"]["gnd"] == "https://d-nb.info/gnd/2"


TOTAL_REGISTER = ('<listPerson><person xml:id="pmb1"><persName>Autor</persName></person></listPerson>'
                  '<listPlace><place xml:id="pmb2"><placeName>Dorf</placeName></place></listPlace>')


def cli_reconcile(monkeypatch, capsys, tmp_path, *extra):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", TOTAL_REGISTER), encoding="utf-8")
    out = tmp_path / "recon.json"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out),
                                      "--delay", "0", *extra])
    return out, capsys


def test_cli_total_failure_exits_1_without_cache(monkeypatch, capsys, tmp_path):
    boom = urllib.error.URLError(OSError("refused"))
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("entities/", boom)]))
    out, capsys = cli_reconcile(monkeypatch, capsys, tmp_path)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "gescheitert" in captured.err
    assert not out.is_file()
    assert json.loads(captured.out)["failed"] == 2


def test_cli_partial_failure_and_offline(monkeypatch, capsys, tmp_path):
    boom = urllib.error.URLError(OSError("refused"))
    geo = {"sameAs": ["https://sws.geonames.org/222/"]}
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("person/", boom), ("place/", geo)]))
    out, capsys = cli_reconcile(monkeypatch, capsys, tmp_path)
    main()  # no SystemExit on partial failure
    captured = capsys.readouterr()
    assert "erneuter Lauf" in captured.err
    assert set(json.loads(out.read_text(encoding="utf-8"))["entries"]) == {"pmb2"}
    http = FakeHTTP([])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    out, capsys = cli_reconcile(monkeypatch, capsys, tmp_path, "--offline")
    main()
    report = json.loads(capsys.readouterr().out)
    assert (report["fetched"], report["written"], report["status"]) == (0, False, "ok")
    assert http.calls == []


class FakeSequenceHTTP(FakeHTTP):
    """urlopen stand-in consuming one answer per call (last answer repeats)."""

    def __call__(self, request, timeout=None, context=None):
        self.calls.append({"url": request.full_url, "timeout": timeout, "context": context})
        answer = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(answer, BaseException):
            raise answer
        return FakeHTTP.Response(answer)


DROPS = [
    http.client.RemoteDisconnected("x"),
    http.client.IncompleteRead(b"ab", 10),
    http.client.BadStatusLine("GARBAGE"),
    ConnectionResetError(54, "reset"),
]
GND_PAYLOAD = {"sameAs": ["https://d-nb.info/gnd/118609807"]}


@pytest.mark.parametrize("drop", DROPS)
def test_dropped_connection_retries_once_then_fails(monkeypatch, drop):
    http = FakeSequenceHTTP([drop, drop])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    with pytest.raises(ResolverError):
        PmbResolver(delay=0).resolve("person", "pmb1", "A")
    assert len(http.calls) == 2


@pytest.mark.parametrize("drop", DROPS)
def test_dropped_connection_recovers_on_retry(monkeypatch, drop):
    http = FakeSequenceHTTP([drop, GND_PAYLOAD])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    links = PmbResolver(delay=0).resolve("person", "pmb1", "A")
    assert links.gnd == "https://d-nb.info/gnd/118609807"
    assert len(http.calls) == 2


def test_unwrapped_cert_error_has_no_retry(monkeypatch):
    raw = ssl.SSLCertVerificationError(1, "certificate verify failed")
    http = FakeSequenceHTTP([raw])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    with pytest.raises(ResolverError):
        PmbResolver(delay=0).resolve("person", "pmb1", "A")
    assert len(http.calls) == 1


FLAKY_REGISTER = ('<listPerson><person xml:id="pmb1"><persName>Eins</persName></person>'
                   '<person xml:id="pmb2"><persName>Zwei</persName></person></listPerson>'
                   '<listPlace><place xml:id="pmb3"><placeName>Dorf</placeName></place></listPlace>')


def test_cli_partial_drop_keeps_going(monkeypatch, capsys, tmp_path):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "recon.json"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    drop = http.client.RemoteDisconnected("reset by peer")
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("person/2", drop)]))
    main()  # no SystemExit: 2 fetched, 1 failed
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["fetched"], report["failed"], report["written"]) == (2, 1, True)
    assert set(json.loads(out.read_text(encoding="utf-8"))["entries"]) == {"pmb1", "pmb3"}
    assert "erneuter Lauf" in captured.err


def test_cli_cache_creates_missing_parents(monkeypatch, capsys, tmp_path):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "neu" / "sub" / "recon.json"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out),
                                      "--delay", "0", "--offline"])
    main()
    assert out.is_file()


def test_cli_cache_directory_fails_before_network(monkeypatch, capsys, tmp_path):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    http = FakeHTTP([])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "Verzeichnis" in capsys.readouterr().err
    assert http.calls == []


def test_cli_total_failure_creates_no_directory(monkeypatch, capsys, tmp_path):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "neu" / "recon.json"
    boom = urllib.error.URLError(OSError("refused"))
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("entities/", boom)]))
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert not out.is_file() and not (tmp_path / "neu").exists()


def http_error(code, content_type, body):
    headers = email.message.Message()
    if content_type:
        headers["Content-Type"] = content_type
    return urllib.error.HTTPError("https://pmb.acdh.oeaw.ac.at/x", code, "reason",
                                  headers, io.BytesIO(body))


WEIMAR_REGISTER = ('<listPerson><person xml:id="pmb1"><persName>Eins</persName></person></listPerson>'
                    '<listPlace><place xml:id="weimar"><placeName>Weimar</placeName></place></listPlace>')


@pytest.mark.parametrize("order", [[0, 1], [1, 0]])
def test_unsupported_id_never_fetched(monkeypatch, capsys, tmp_path, order):
    first = tmp_path / "A.xml"
    first.write_text(letter("A", "", WEIMAR_REGISTER), encoding="utf-8")
    second = tmp_path / "B.xml"
    second.write_text(letter("B", "", WEIMAR_REGISTER), encoding="utf-8")
    inputs = [str(first), str(second)][order[0]], [str(first), str(second)][order[1]]
    out = tmp_path / "recon.json"
    boom = urllib.error.URLError(OSError("refused"))
    http = FakeHTTP([("entities/", boom)])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", *inputs, "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert not out.is_file()
    report = json.loads(capsys.readouterr().out)
    assert report["skipped"] == 1
    assert report["failed"] == 1 and report["fetched"] == 0
    assert len(http.calls) == 2  # pmb1 attempt + retry; weimar never requested
    assert all("person/1" in call["url"] for call in http.calls)


def test_json_404_stays_unresolved(monkeypatch):
    err = http_error(404, "application/json", b'{"detail": "No Person matches the given query."}')
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([err]))
    stored = new_cache("fake")
    entities = {"pmb1": {"kind": "person", "label": "Eins"}}
    result = update_cache(stored, entities, PmbResolver(delay=0))
    assert (result.fetched, result.failed) == (1, 0)
    assert stored["entries"]["pmb1"]["gnd"] is None
    assert any("keine Normdaten" in warning for warning in result.warnings)


def test_html_404_is_drift_and_aborts(monkeypatch, capsys, tmp_path):
    err = http_error(404, "text/html", b"<html>not found</html>")
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([err]))
    with pytest.raises(ApiDriftError):
        PmbResolver(delay=0).resolve("person", "pmb1", "Eins")
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "recon.json"
    http = FakeSequenceHTTP([err])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert len(http.calls) == 1
    assert "API geändert" in capsys.readouterr().err


def test_200_without_sameAs_is_drift(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([{"id": 1}]))
    with pytest.raises(ApiDriftError):
        PmbResolver(delay=0).resolve("person", "pmb1", "Eins")
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([[["x"]]]))
    with pytest.raises(ApiDriftError):
        PmbResolver(delay=0).resolve("person", "pmb1", "Eins")


def test_drift_after_successes_keeps_entries(monkeypatch, capsys, tmp_path):
    gnd = {"sameAs": ["https://d-nb.info/gnd/118609807"]}
    err = http_error(404, "text/html", b"<html>not found</html>")
    answers = [("person/1", gnd), ("person/2", gnd), ("place/3", err)]
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP(answers))
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "recon.json"
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "API geändert" in capsys.readouterr().err
    assert set(json.loads(out.read_text(encoding="utf-8"))["entries"]) == {"pmb1", "pmb2"}


def test_save_cache_is_atomic(monkeypatch, tmp_path):
    out = tmp_path / "recon.json"
    out.write_text('{"entries": {}}', encoding="utf-8")
    before = out.read_bytes()

    def volle_platte(*args, **kwargs):
        raise OSError("volle Platte")

    monkeypatch.setattr(os, "replace", volle_platte)
    with pytest.raises(OSError):
        save_cache(out, {"entries": {"pmb1": {}}})
    assert out.read_bytes() == before
    assert [child.name for child in tmp_path.iterdir()] == ["recon.json"]


def test_checkpoint_every_25():
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in range(1, 31)}
    calls = []
    result = update_cache(new_cache("fake"), entities, FakeResolver({}),
                          checkpoint=lambda: calls.append(1), checkpoint_every=25)
    assert (result.fetched, result.failed) == (30, 0) and len(calls) == 1


def test_keyboard_interrupt_reports_130(monkeypatch, capsys, tmp_path):
    register = "".join(f'<person xml:id="pmb{i}"><persName>P{i}</persName></person>' for i in range(1, 31))
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", f"<listPerson>{register}</listPerson>"), encoding="utf-8")
    out = tmp_path / "recon.json"
    answers = [{"sameAs": []}] * 25 + [KeyboardInterrupt()]
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP(answers))
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 130
    report = json.loads(capsys.readouterr().out)
    assert report["interrupted"] is True
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert len(stored["entries"]) >= 25


def test_corrupt_cache_is_usage_error(monkeypatch, capsys, tmp_path):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", FLAKY_REGISTER), encoding="utf-8")
    out = tmp_path / "recon.json"
    out.write_text("{broken", encoding="utf-8")
    http = FakeHTTP([])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out), "--delay", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and http.calls == []


# --- error classes, pacing, breaker, messages (resolver-errors) ------------------------------


class FakeClock:
    """Deterministic stand-in for time.monotonic/time.sleep inside reconcile."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(reconcile_module.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(reconcile_module.time, "sleep", fake.sleep)
    return fake


def persons(n):
    return "<listPerson>" + "".join(
        f'<person xml:id="pmb{i}"><persName>P{i}</persName></person>' for i in range(1, n + 1)) + "</listPerson>"


def run_cli(monkeypatch, tmp_path, register, *extra, cache_name="recon.json"):
    letter_path = tmp_path / "L1.xml"
    letter_path.write_text(letter("L1", "", register), encoding="utf-8")
    out = tmp_path / cache_name
    monkeypatch.setattr(sys, "argv", ["tei-crm", "reconcile", str(letter_path), "--cache", str(out),
                                      "--delay", "0", *extra])
    return out


def http_500():
    return http_error(500, "text/html", b"<html>boom</html>")


def test_single_http_500_is_local_and_rerun_exits_0(monkeypatch, capsys, tmp_path):
    ok = {"sameAs": ["https://d-nb.info/gnd/1"]}
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("person/2/", http_500()), ("person/", ok)]))
    out = run_cli(monkeypatch, tmp_path, persons(3))
    main()  # exit 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["status"], report["fetched"], report["failed"]) == ("partial", 2, 1)
    assert report["failures"] == [{"id": "pmb2", "systemic": False, "detail": report["failures"][0]["detail"]}]
    assert "pmb2" in captured.err and "HTTP 500" in captured.err
    assert "certifi" not in captured.err and "Netzwerk" not in captured.err
    main()  # rerun: only pmb2 missing, still local -> still exit 0 (was exit 1 before)
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["fetched"], report["failed"]) == ("partial", 0, 1)
    assert set(json.loads(out.read_text(encoding="utf-8"))["entries"]) == {"pmb1", "pmb3"}


def test_leading_http_500s_do_not_trip_breaker(monkeypatch, capsys, tmp_path):
    ok = {"sameAs": []}
    answers = [(f"person/{i}/", http_500()) for i in (1, 2, 3)] + [("person/", ok)]
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP(answers))
    out = run_cli(monkeypatch, tmp_path, persons(6))
    main()
    report = json.loads(capsys.readouterr().out)
    assert (report["fetched"], report["failed"], report["status"]) == (3, 3, "partial")
    assert len(json.loads(out.read_text(encoding="utf-8"))["entries"]) == 3


def test_503_retry_after_then_success(clock, monkeypatch):
    busy = http_error(503, "text/html", b"")
    busy.headers["Retry-After"] = "2"
    http = FakeSequenceHTTP([busy, GND_PAYLOAD])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    links = PmbResolver(delay=0.5).resolve("person", "pmb1", "A")
    assert links.gnd == "https://d-nb.info/gnd/118609807"
    assert len(http.calls) == 2
    assert max(clock.sleeps) >= 2


def test_429_backoff_is_bounded_and_systemic(clock, monkeypatch):
    limited = http_error(429, "text/html", b"")
    limited.headers["Retry-After"] = "600"
    http = FakeSequenceHTTP([limited])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    with pytest.raises(ResolverError) as error:
        PmbResolver(delay=1).resolve("person", "pmb1", "A")
    assert error.value.systemic and error.value.cause == "throttle"
    assert len(http.calls) == 4  # 1 + 3 retries
    backoffs = [seconds for seconds in clock.sleeps if seconds > 1]
    assert backoffs and max(backoffs) <= 60


def test_429_backoff_grows_without_retry_after(clock, monkeypatch):
    http = FakeSequenceHTTP([http_error(429, "text/html", b"")])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    with pytest.raises(ResolverError):
        PmbResolver(delay=1).resolve("person", "pmb1", "A")
    assert [seconds for seconds in clock.sleeps if seconds >= 1][:3] == [1, 2, 4]


def test_pacer_spaces_every_request(clock, monkeypatch):
    starts = []
    inner = FakeHTTP([("person/2/", http_500())])

    def urlopen(request, timeout=None, context=None):
        starts.append(clock.now)
        return inner(request, timeout=timeout, context=context)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in (1, 2, 3)}
    result = update_cache(new_cache("pmb-apis"), entities, PmbResolver(delay=0.5))
    assert (result.fetched, result.failed) == (2, 1)
    assert len(starts) == 3
    assert all(later - earlier >= 0.5 for earlier, later in zip(starts, starts[1:], strict=False))


def test_consecutive_outage_after_success_aborts(monkeypatch, capsys, tmp_path):
    boom = urllib.error.URLError(OSError("refused"))
    ok = {"sameAs": ["https://d-nb.info/gnd/1"]}
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("person/1/", ok), ("person/", boom)]))
    out = run_cli(monkeypatch, tmp_path, persons(16))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["status"], report["fetched"], report["failed"]) == ("aborted", 1, 5)
    assert "in Folge" in captured.err and "10 nicht versucht" in captured.err
    assert set(json.loads(out.read_text(encoding="utf-8"))["entries"]) == {"pmb1"}


def test_breaker_never_fires_when_failures_alternate_with_successes():
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in range(1, 12)}
    resolver = FakeResolver({}, fail={f"pmb{i}" for i in (2, 4, 6, 8, 10)})
    result = update_cache(new_cache("fake"), entities, resolver)
    assert result.stop is None and (result.fetched, result.failed) == (6, 5)
    assert len(resolver.calls) == 11


def test_leading_abort_message_and_singular(monkeypatch, capsys, tmp_path):
    boom = urllib.error.URLError(OSError("refused"))
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("entities/", boom)]))
    run_cli(monkeypatch, tmp_path, persons(7))
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "Die ersten 3 von 7 Abrufen" in err and "4 nicht versucht" in err and "Netzwerk" in err
    run_cli(monkeypatch, tmp_path, persons(1), cache_name="one.json")
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "1 Abruf ist gescheitert" in err and "1 Abrufe" not in err


def test_offline_never_builds_tls_even_with_broken_certifi(monkeypatch, capsys, tmp_path):
    certifi = pytest.importorskip("certifi")
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "missing.pem"))
    http = FakeHTTP([])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    run_cli(monkeypatch, tmp_path, persons(2), "--offline")
    main()  # no traceback, exit 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert http.calls == []
    assert tls_context().verify_mode == ssl.CERT_REQUIRED  # broken bundle falls back, no raise


def make_ca(directory, name):
    key, cert = directory / f"{name}.key", directory / f"{name}.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", f"/CN={name}",
                    "-addext", "basicConstraints=critical,CA:TRUE"], check=True, capture_output=True)
    return cert


def test_tls_context_adds_certifi_on_top_of_ssl_cert_file(monkeypatch, tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    certifi = pytest.importorskip("certifi")
    platform_ca, bundle_ca = make_ca(tmp_path, "tcb-platform-ca"), make_ca(tmp_path, "tcb-certifi-ca")
    monkeypatch.setenv("SSL_CERT_FILE", str(platform_ca))
    monkeypatch.setattr(certifi, "where", lambda: str(bundle_ca))
    subjects = {value for cert in tls_context().get_ca_certs()
                for rdn in cert["subject"] for key, value in rdn if key == "commonName"}
    assert {"tcb-platform-ca", "tcb-certifi-ca"} <= subjects


def test_existing_cache_is_untouched_on_failure_offline_and_full_cache(monkeypatch, capsys, tmp_path):
    body = '{"resolver":"pmb-apis","version":1,"entries":{"pmb1":{"kind":"person","label":"P1","pmb":null,' \
           '"gnd":null,"geonames":null,"wikidata":null,"source":"pmb-apis","retrieved":"2026-01-01"}}}'
    boom = urllib.error.URLError(OSError("refused"))
    cases = [(persons(3), (), 1), (persons(3), ("--offline",), 0), (persons(1), (), 0)]
    for register, extra, code in cases:
        monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("entities/", boom)]))
        out = run_cli(monkeypatch, tmp_path, register, *extra)
        out.write_text(body, encoding="utf-8")
        os.utime(out, ns=(1_000_000_000, 1_000_000_000))
        if code:
            with pytest.raises(SystemExit) as error:
                main()
            assert error.value.code == code
        else:
            main()
        assert json.loads(capsys.readouterr().out)["written"] is False
        assert out.read_text(encoding="utf-8") == body
        assert out.stat().st_mtime_ns == 1_000_000_000


def test_raw_ssl_eof_is_transient(monkeypatch):
    eof = ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
    http = FakeSequenceHTTP([eof])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    with pytest.raises(ResolverError) as error:
        PmbResolver(delay=0).resolve("person", "pmb1", "A")
    assert error.value.cause == "transport" and len(http.calls) == 2


class CauseResolver(FakeResolver):
    """Fails each ID in ``causes`` with a ResolverError of that cause."""

    def __init__(self, causes):
        super().__init__({})
        self.causes = causes

    def resolve(self, kind, local_id, label):
        self.calls.append((kind, local_id))
        if local_id in self.causes:
            raise ResolverError("boom", cause=self.causes[local_id])
        return AuthorityLinks()


def test_http_failure_neither_counts_nor_resets_streak():
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in range(1, 11)}
    # leading: transport, http, transport, transport -> 3 systemic before any success -> stop
    leading = CauseResolver({"pmb1": "transport", "pmb2": "http", "pmb3": "transport", "pmb4": "transport"})
    result = update_cache(new_cache("fake"), entities, leading)
    assert result.stop == "leading" and result.attempted == 4 and result.untried == 6
    # consecutive after a success: 4 transport, 1 http, 1 transport -> 5 systemic in a row -> stop
    causes = {f"pmb{i}": "transport" for i in (2, 3, 4, 5, 7)} | {"pmb6": "http"}
    result = update_cache(new_cache("fake"), entities, CauseResolver(causes))
    assert result.stop == "consecutive" and result.streak == 5 and result.untried == 3


def test_breaker_does_not_report_abort_on_last_entity():
    entities = {f"pmb{i}": {"kind": "person", "label": f"P{i}"} for i in range(1, 4)}
    result = update_cache(new_cache("fake"), entities, CauseResolver({f"pmb{i}": "transport" for i in (1, 2, 3)}))
    assert result.stop is None and result.failed == 3 and result.untried == 0
    assert not any("Abbruch" in warning for warning in result.warnings)


def test_advice_matches_cause(clock, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([http_error(503, "text/html", b"")]))
    run_cli(monkeypatch, tmp_path, persons(3))
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "no_progress"
    assert "drosselt" in captured.err and "--delay" in captured.err
    assert "certifi" not in captured.err and "Netzwerk" not in captured.err
    cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([cert]))
    run_cli(monkeypatch, tmp_path, persons(3), cache_name="tls.json")
    with pytest.raises(SystemExit):
        main()
    err = capsys.readouterr().err
    assert "Zertifikatsfehler" in err and "SSL_CERT_FILE" in err and "Netzwerk" not in err


def test_offline_never_calls_tls_context(monkeypatch, capsys, tmp_path):
    def forbidden():
        raise AssertionError("tls_context must not run offline or at construction")

    monkeypatch.setattr(reconcile_module, "tls_context", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([]))
    run_cli(monkeypatch, tmp_path, persons(2), "--offline")
    main()
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    PmbResolver(delay=0)  # construction must stay TLS-free as well


def test_tls_context_additive_without_openssl(monkeypatch, tmp_path):
    certifi = pytest.importorskip("certifi")
    with open(certifi.where(), encoding="ascii") as handle:
        pems = re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", handle.read(), re.S)
    platform_pem, bundle_pem = tmp_path / "platform.pem", tmp_path / "bundle.pem"
    platform_pem.write_text(pems[0] + "\n", encoding="ascii")
    bundle_pem.write_text(pems[1] + "\n", encoding="ascii")
    expected = [ssl.PEM_cert_to_DER_cert(pem) for pem in pems[:2]]
    monkeypatch.setenv("SSL_CERT_FILE", str(platform_pem))
    monkeypatch.setattr(certifi, "where", lambda: str(bundle_pem))
    loaded = tls_context().get_ca_certs(binary_form=True)
    assert all(der in loaded for der in expected)


def test_only_local_failures_still_leave_a_cache_for_cmif(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(urllib.request, "urlopen", FakeHTTP([("person/", http_500())]))
    out = run_cli(monkeypatch, tmp_path, persons(1))
    main()  # exit 0
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["fetched"], report["written"]) == ("partial", 0, True)
    assert load_cache(out)["entries"] == {}  # valid, empty: a following --reconciliation step can read it


def test_interrupt_report_counts_skipped(monkeypatch, capsys, tmp_path):
    register = persons(3).replace("</listPerson>", '<person xml:id="gnd9"><persName>X</persName></person></listPerson>')
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([{"sameAs": []}, KeyboardInterrupt()]))
    run_cli(monkeypatch, tmp_path, register)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 130
    assert json.loads(capsys.readouterr().out)["skipped"] == 1


def test_non_ascii_retry_after_does_not_crash(clock, monkeypatch):
    busy = http_error(503, "text/html", b"")
    busy.headers["Retry-After"] = "\u00b2"
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([busy, GND_PAYLOAD]))
    assert PmbResolver(delay=0).resolve("person", "pmb1", "A").gnd == "https://d-nb.info/gnd/118609807"


def test_unreadable_404_body_is_transport_not_drift(monkeypatch):
    class BrokenBody(io.BytesIO):
        def read(self, *args):
            raise http.client.IncompleteRead(b"", 10)

    headers = email.message.Message()
    headers["Content-Type"] = "application/json"
    err = urllib.error.HTTPError("https://pmb.acdh.oeaw.ac.at/x", 404, "reason", headers, BrokenBody())
    monkeypatch.setattr(urllib.request, "urlopen", FakeSequenceHTTP([err]))
    with pytest.raises(ResolverError) as error:
        PmbResolver(delay=0).resolve("person", "pmb1", "A")
    assert error.value.cause == "transport" and not isinstance(error.value, ApiDriftError)


def test_backoff_has_minimum_and_retry_after_binds_next_entity(clock, monkeypatch):
    busy = http_error(503, "text/html", b"")
    http = FakeSequenceHTTP([busy])
    monkeypatch.setattr(urllib.request, "urlopen", http)
    resolver = PmbResolver(delay=0)
    with pytest.raises(ResolverError):
        resolver.resolve("person", "pmb1", "A")
    assert [seconds for seconds in clock.sleeps if seconds > 0][:3] == [1, 1, 1]  # MIN_BACKOFF with --delay 0
    limited = http_error(429, "text/html", b"")
    limited.headers["Retry-After"] = "30"
    starts = []
    answers = iter([limited, limited, limited, limited, GND_PAYLOAD])

    def urlopen(request, timeout=None, context=None):
        starts.append(clock.now)
        answer = next(answers)
        if isinstance(answer, BaseException):
            raise answer
        return FakeHTTP.Response(answer)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    resolver = PmbResolver(delay=0)
    with pytest.raises(ResolverError):
        resolver.resolve("person", "pmb1", "A")
    resolver.resolve("person", "pmb2", "B")  # next entity still honours the server's 30 s
    assert starts[-1] - starts[-2] >= 30
