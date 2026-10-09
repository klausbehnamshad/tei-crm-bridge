"""Command line interface."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from lxml import etree

from .cmif import CmifOptions, export_cmif
from .core import enrich
from .ner import GlossaryRecognizer, HuggingFaceRecognizer
from .preview import write_preview
from .reconcile import (
    Failure,
    PmbResolver,
    UpdateResult,
    collect_entities,
    load_cache,
    new_cache,
    save_cache,
    summarize,
    update_cache,
)


def _enrich_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", type=Path, metavar="input", help="TEI P5 XML file(s)")
    parser.add_argument("--out-dir", type=Path, default=Path("build"))
    parser.add_argument("--engine", choices=["glossary", "hf"], default="glossary")
    parser.add_argument("--glossary", type=Path, default=Path("examples/glossary.json"))
    parser.add_argument("--base-uri", default="https://example.org/tei-crm-demo/")
    parser.add_argument("--tei-base-url", help="URL prefix where the enriched TEI files will be published; "
                        "annotations then point to <prefix><stem>.enriched.xml")
    parser.add_argument("--source-url", help="URL of the input file (only with a single input)")
    parser.add_argument("--threshold", type=float, default=0.85, help="minimum model score (hf engine)")
    parser.add_argument("--reading", choices=["edited", "diplomatic"], default="edited",
                        help="branch of <choice> given to the recognizer")
    parser.add_argument("--model", help="Optional local Transformers model directory or model ID")
    parser.add_argument("--revision", help="model revision to load (default: the pinned one for the default model)")
    parser.add_argument("--stride", type=int, default=128, help="token overlap between model windows (hf engine)")
    parser.add_argument("--aggregation", choices=HuggingFaceRecognizer.AGGREGATIONS, default="first",
                        help="how subword predictions become spans; word-level strategies never cut a word (hf engine)")
    parser.add_argument("--local-files-only", action="store_true", help="Require already cached model files")
    parser.add_argument("--reconciliation", type=Path,
                        help="reconciliation cache (JSON); resolved norm data becomes rdfs:seeAlso")


def _cmif_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", type=Path, metavar="input",
                        help="original TEI P5 letters (no NER needed)")
    parser.add_argument("--out", type=Path, required=True, help="the single CMIF TEI file to write")
    parser.add_argument("--url-pattern",
                        help="public letter URL with {id} for the letter's xml:id, "
                        "e.g. 'https://edition.example.org/briefe/{id}.html'; "
                        "without it correspDesc carries key=<xml:id> instead of ref=<URL>")
    parser.add_argument("--cmif-url", required=True,
                        help="stable public URL of this CMIF file (publicationStmt/idno)")
    parser.add_argument("--title", help="title of the letter index (default: series title of the letters)")
    parser.add_argument("--publisher", help="originator of the metadata (default: publisher of the letters)")
    parser.add_argument("--licence", help="licence URL (default: licence of the letters, else CC BY 4.0)")
    parser.add_argument("--licence-text", help="licence statement (default: standard text for CC BY 4.0/CC0)")
    parser.add_argument("--editor", default="TEI CRM Bridge", help="contact person for the index")
    parser.add_argument("--editor-email", help="contact e-mail for the index")
    parser.add_argument("--source-id", help="bibl id the correspDesc/@source points to (default: stable UUID)")
    parser.add_argument("--source-type", choices=["print", "online"], default="online")
    parser.add_argument("--source-label", help="bibliographic text about the source edition")
    parser.add_argument("--reconciliation", type=Path,
                        help="reconciliation cache (JSON) from 'tei-crm reconcile'; "
                        "fills persName/placeName @ref where the letters lack norm data")


def _reconcile_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", type=Path, metavar="input", help="original TEI P5 letters")
    parser.add_argument("--cache", type=Path, required=True, help="reconciliation cache file (JSON) to build/update")
    parser.add_argument("--offline", action="store_true",
                        help="only use the cache, never touch the network")
    parser.add_argument("--resolver", choices=["pmb"], default="pmb", help="authority backend")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between server requests")


def _load_reconciliation(path: Path | None, parser: argparse.ArgumentParser) -> dict | None:
    if path is None:
        return None
    try:
        return load_cache(path)
    except ValueError as error:
        parser.error(str(error))


def _store_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", type=Path, metavar="GRAPH.ttl",
                        help="Turtle-Dateien zum Laden in den Store")
    parser.add_argument("--db", type=Path, required=True,
                        help="Verzeichnis des persistenten Stores (wird angelegt oder ergänzt)")


def _query_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", type=Path, metavar="QUERY.rq", help="SPARQL-Datei")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path,
                        help="Verzeichnis eines mit 'tei-crm store' angelegten Stores")
    source.add_argument("--graph", nargs="+", type=Path, metavar="GRAPH.ttl",
                        help="Turtle-Dateien für einen Speicher-Store")
    parser.add_argument("--bind", action="append", default=[], metavar="name=WERT",
                        help="Variablenbindung, mehrfach möglich; "
                        "ein als IRI gültiger Wert wird IRI, sonst Literal")
    parser.add_argument("--format", choices=["csv", "json", "table"], default="table",
                        help="Ausgabeformat (Standard: table)")


def _load_store_module(command: str, parser: argparse.ArgumentParser):
    """Das Store-Modul oder Exit 2 mit Installationshinweis (pyoxigraph nur dort)."""
    try:
        from . import store as store_module
    except ImportError:
        parser.exit(2, f"tei-crm {command}: Dafür wird das Extra 'store' benötigt: "
                       "pip install 'tei-crm-bridge[store]'.\n")
    return store_module


def run_store(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    missing = [str(path) for path in args.inputs if not path.is_file()]
    if missing:
        parser.error(f"input not found: {', '.join(missing)}")
    store_module = _load_store_module("store", parser)
    store = store_module.load([], args.db)
    before = store_module.triple_count(store)
    del store
    store = store_module.load(args.inputs, args.db)
    after = store_module.triple_count(store)
    print(json.dumps({"db": str(args.db), "files": len(args.inputs),
                      "triples_before": before, "triples_after": after},
                     ensure_ascii=False, indent=2))


def _parse_bindings(pairs: list[str], parser: argparse.ArgumentParser) -> dict[str, str]:
    bindings = {}
    for pair in pairs:
        name, separator, value = pair.partition("=")
        if not separator or not name:
            parser.error(f"--bind braucht die Form name=WERT, erhalten: {pair!r}")
        bindings[name.lstrip("?")] = value
    return bindings


def _cell(store_module, term: object) -> str:
    """Anzeigeform: ungebundene Variable (None) wird eine leere Zelle."""
    return "" if term is None else store_module.term_string(term)


def _print_table(rows: list[dict], store_module) -> None:
    if not rows:
        print("(keine Zeilen)")
        return
    names = list(rows[0])
    table = [[_cell(store_module, row[name]) for name in names] for row in rows]
    widths = [max([len(names[i])] + [len(line[i]) for line in table]) for i in range(len(names))]
    print(" | ".join(name.ljust(widths[i]) for i, name in enumerate(names)))
    print("-+-".join("-" * width for width in widths))
    for line in table:
        print(" | ".join(value.ljust(widths[i]) for i, value in enumerate(line)))


def _print_csv(rows: list[dict], store_module) -> None:
    if not rows:
        return
    names = list(rows[0])
    writer = csv.writer(sys.stdout)
    writer.writerow(names)
    for row in rows:
        writer.writerow([_cell(store_module, row[name]) for name in names])


def _print_json(rows: list[dict], store_module) -> None:
    if not rows:
        print("[]")
        return
    names = list(rows[0])
    print(json.dumps([{name: _cell(store_module, row[name]) for name in names}
                      for row in rows], ensure_ascii=False, indent=2))


def run_query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.query is None or not args.query.is_file():
        parser.error(f"query not found: {args.query}")
    if args.db is not None and not args.db.exists():
        parser.error(f"store not found: {args.db} (mit 'tei-crm store' anlegen)")
    if args.graph:
        missing = [str(path) for path in args.graph if not path.is_file()]
        if missing:
            parser.error(f"input not found: {', '.join(missing)}")
    bindings = _parse_bindings(args.bind, parser)
    store_module = _load_store_module("query", parser)
    text = args.query.read_text(encoding="utf-8")
    if args.db is not None:
        store = store_module.load([], args.db)
    else:
        store = store_module.load(args.graph, None)
    try:
        rows = store_module.query(store, text, bindings)
    except Exception as error:
        parser.exit(1, f"tei-crm query: Abfragefehler: {error}\n")
    {"csv": _print_csv, "json": _print_json, "table": _print_table}[args.format](rows, store_module)


def _validate_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("graph", type=Path, metavar="GRAPH.ttl", help="zu prüfende Turtle-Datei")
    parser.add_argument("--profile", choices=["source", "reviewed"], default="source",
                        help="SHACL-Profil (Standard: source)")


def _load_validate_module(parser: argparse.ArgumentParser):
    """Das Validate-Modul oder Exit 2 mit Installationshinweis (pyshacl nur dort)."""
    try:
        from . import validate as validate_module
    except ImportError:
        parser.exit(2, "tei-crm validate: Dafür wird das Extra 'validate' benötigt: "
                       "pip install 'tei-crm-bridge[validate]'.\n")
    return validate_module


def run_validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.graph.is_file():
        parser.error(f"graph not found: {args.graph}")
    validate_module = _load_validate_module(parser)
    try:
        report = validate_module.validate(args.graph, args.profile)
    except Exception as error:
        parser.exit(1, f"tei-crm validate: Prüffehler: {error}\n")
    print(json.dumps({"graph": str(args.graph), "profile": args.profile,
                      "conforms": report.conforms,
                      "violations": [{"focus": item.focus, "shape": item.shape,
                                      "message": item.message}
                                     for item in report.violations]},
                     ensure_ascii=False, indent=2))
    if not report.conforms:
        parser.exit(1, f"tei-crm validate: {len(report.violations)} Regelverstöße "
                       f"({args.profile}).\n")


def _network_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", type=Path, metavar="LETTER.xml",
                        help="Original-TEI-Briefe für das Korrespondenznetz")
    parser.add_argument("--out-dir", type=Path, required=True, help="Ausgabeverzeichnis")
    parser.add_argument("--graphs", nargs="+", type=Path, metavar="GRAPH.ttl",
                        help="Briefgraphen für das Nennungsnetz")


def _load_network_module(parser: argparse.ArgumentParser):
    """Das Network-Modul oder Exit 2 mit Installationshinweis (networkx nur dort)."""
    try:
        from . import network as network_module
    except ImportError:
        parser.exit(2, "tei-crm network: Dafür wird das Extra 'network' benötigt: "
                       "pip install 'tei-crm-bridge[network]'.\n")
    return network_module


def run_network(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    missing = [str(path) for path in list(args.inputs) + list(args.graphs or [])
               if not path.is_file()]
    if missing:
        parser.error(f"input not found: {', '.join(missing)}")
    network_module = _load_network_module(parser)
    try:
        correspondence, corr_stats = network_module.build_correspondence(args.inputs)
        mentions = mentions_stats = None
        if args.graphs:
            mentions, mentions_stats = network_module.build_mentions(args.graphs)
        body = network_module.write_outputs(args.out_dir, correspondence, corr_stats,
                                            mentions, mentions_stats, args.inputs, args.graphs)
    except Exception as error:
        parser.exit(1, f"tei-crm network: Netzfehler: {error}\n")
    summary = {"out_dir": str(args.out_dir),
               "correspondence": {"nodes": body["correspondence"]["nodes"],
                                  "edges": body["correspondence"]["edges"]},
               "mentions": ({"nodes": body["mentions"]["nodes"],
                             "edges": body["mentions"]["edges"]}
                            if body["mentions"] is not None else None),
               "without_sent": body["correspondence"]["without_sent"],
               "without_received": body["correspondence"]["without_received"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    # Separate parsers: an optional positional on the enrich parser would swallow
    # a subcommand name, so dispatch on argv[1] first.
    if len(sys.argv) > 1 and sys.argv[1] == "network":
        parser = argparse.ArgumentParser(
            prog="tei-crm network",
            description="Korrespondenz- und Nennungsnetz aus Edition und Graphen "
            "(Kennzahlen beschreiben die Auszeichnung, keine Bedeutung).")
        _network_parser(parser)
        run_network(parser.parse_args(sys.argv[2:]), parser)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        parser = argparse.ArgumentParser(
            prog="tei-crm validate",
            description="Prüft einen Graphen gegen das TCB-SHACL-Profil "
            "(formkonform, keine fachliche Prüfung).")
        _validate_parser(parser)
        run_validate(parser.parse_args(sys.argv[2:]), parser)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "store":
        parser = argparse.ArgumentParser(
            prog="tei-crm store",
            description="Lädt Turtle-Dateien in einen persistenten Store "
            "(legt ihn an oder ergänzt ihn).")
        _store_parser(parser)
        run_store(parser.parse_args(sys.argv[2:]), parser)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        parser = argparse.ArgumentParser(
            prog="tei-crm query",
            description="Führt eine SPARQL-Datei gegen einen Store oder "
            "Turtle-Dateien aus, mit Variablenbindung.")
        _query_parser(parser)
        run_query(parser.parse_args(sys.argv[2:]), parser)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "reconcile":
        parser = argparse.ArgumentParser(
            prog="tei-crm reconcile",
            description="Resolve local register IDs against norm data into a JSON cache; "
            "offline-reproducible, one polite request per unknown entity.")
        _reconcile_parser(parser)
        run_reconcile(parser.parse_args(sys.argv[2:]), parser)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "cmif":
        parser = argparse.ArgumentParser(
            prog="tei-crm cmif",
            description="Collect correspDesc/correspAction of many letters into one "
            "CMIF file for correspSearch; reads the original TEI letters, no NER needed.")
        _cmif_parser(parser)
        run_cmif(parser.parse_args(sys.argv[2:]), parser)
        return
    parser = argparse.ArgumentParser(description="Enrich TEI P5 and export CIDOC CRM Turtle")
    _enrich_parser(parser)
    args = parser.parse_args()
    stems = Counter(path.stem for path in args.inputs)
    if duplicates := sorted(stem for stem, count in stems.items() if count > 1):
        parser.error(f"inputs share a file name and would overwrite each other's output: {', '.join(duplicates)}")
    if args.source_url and len(args.inputs) > 1:
        parser.error("--source-url needs a single input")
    if args.engine == "glossary" and not args.glossary.is_file():
        parser.error(f"glossary not found: {args.glossary} (pass --glossary)")
    recognizer = (
        GlossaryRecognizer(args.glossary) if args.engine == "glossary"
        else HuggingFaceRecognizer(
            model=args.model, local_files_only=args.local_files_only, stride=args.stride,
            aggregation=args.aggregation, revision=args.revision,
        )
    )
    reconciliation = _load_reconciliation(args.reconciliation, parser)
    for path in args.inputs:
        stem = path.stem
        outputs = {suffix: args.out_dir / f"{stem}{suffix}" for suffix in (".enriched.xml", ".ttl", ".mentions.json", ".html")}
        tei_url = f"{args.tei_base_url}{stem}.enriched.xml" if args.tei_base_url else None
        result = enrich(
            path, outputs[".enriched.xml"], outputs[".ttl"], recognizer, args.base_uri, args.threshold,
            reading=args.reading, output_json=outputs[".mentions.json"], tei_url=tei_url, source_url=args.source_url,
            reconciliation=reconciliation,
        )
        write_preview(outputs[".enriched.xml"], outputs[".ttl"], outputs[".mentions.json"], outputs[".html"], result)
        print(json.dumps({"input": str(path), **asdict(result)}, ensure_ascii=False, indent=2))


def run_cmif(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    missing = [str(path) for path in args.inputs if not path.is_file()]
    if missing:
        parser.error(f"input not found: {', '.join(missing)}")
    if args.url_pattern and "{id}" not in args.url_pattern:
        parser.error("--url-pattern needs the placeholder {id} for the letter's xml:id")
    options = CmifOptions(
        cmif_url=args.cmif_url, url_pattern=args.url_pattern, title=args.title, publisher=args.publisher,
        licence=args.licence, licence_text=args.licence_text, editor=args.editor,
        editor_email=args.editor_email, source_id=args.source_id, source_type=args.source_type,
        source_label=args.source_label, reconciliation=_load_reconciliation(args.reconciliation, parser),
    )
    result = export_cmif(args.inputs, args.out, options)
    print(json.dumps({"output": str(args.out), **asdict(result)}, ensure_ascii=False, indent=2))


def _check_cache_path(path: Path, parser: argparse.ArgumentParser) -> None:
    """Fail fast when the cache cannot be written; missing parents are fine."""
    if path.is_dir():
        parser.error(f"--cache {path} ist ein Verzeichnis; bitte einen Dateipfad angeben")
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if parent == parent.parent or not parent.is_dir() or not os.access(parent, os.W_OK):
        parser.error(f"--cache {path} kann nicht geschrieben werden "
                     f"(Verzeichnis {parent} fehlt oder ist schreibgeschützt)")


def run_reconcile(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    missing = [str(path) for path in args.inputs if not path.is_file()]
    if missing:
        parser.error(f"input not found: {', '.join(missing)}")
    _check_cache_path(args.cache, parser)
    roots = [etree.parse(str(path)).getroot() for path in args.inputs]
    entities = collect_entities(roots)
    try:
        cache = load_cache(args.cache) if args.cache.is_file() else new_cache(PmbResolver.name)
    except ValueError as error:
        parser.error(f"{error}; Datei aus git wiederherstellen oder löschen")
    resolvers = {"pmb": PmbResolver}
    resolver = resolvers[args.resolver](delay=args.delay)
    cache["resolver"] = resolver.name
    known = set(cache["entries"])
    try:
        result: UpdateResult | None = update_cache(cache, entities, resolver, offline=args.offline,
                                                   checkpoint=lambda: save_cache(args.cache, cache))
    except KeyboardInterrupt:
        result = None
    interrupted = result is None
    outcome = result or UpdateResult(
        fetched=len(set(cache["entries"]) - known),
        skipped=sum(1 for local_id, info in entities.items()
                    if local_id not in cache["entries"] and not resolver.supports(info["kind"], local_id)))
    fetched, failed = outcome.fetched, outcome.failed
    systemic = [failure for failure in outcome.failures if failure.systemic]
    if interrupted:
        status = "interrupted"
    elif outcome.stop == "drift":
        status = "drift"
    elif outcome.stop == "consecutive":
        status = "aborted"
    elif fetched == 0 and systemic:
        status = "no_progress"
    else:
        status = "partial" if failed else "ok"
    changed = False
    # A first run ending ok/partial always leaves a valid (possibly empty) cache,
    # so a following ``cmif``/``enrich --reconciliation`` finds the file.
    if fetched > 0 or (status in ("ok", "partial") and not args.cache.is_file()):
        try:
            save_cache(args.cache, cache)
        except OSError as error:
            parser.exit(1, f"tei-crm reconcile: Cache {args.cache} konnte nicht geschrieben werden "
                           f"({error}); {_count(fetched, 'Abruf', 'Abrufe')} verworfen.\n")
        changed = True
    report = {"cache": str(args.cache), "offline": args.offline, "entities": len(entities),
              "fetched": fetched, "failed": failed, "skipped": outcome.skipped, "written": changed,
              "status": status,
              "failures": [{"id": failure.local_id, "systemic": failure.systemic, "detail": failure.detail}
                           for failure in outcome.failures],
              "summary": summarize(entities, cache), "warnings": outcome.warnings}
    if interrupted:
        report["interrupted"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    prefix = "tei-crm reconcile: "
    if interrupted:
        parser.exit(130, f"{prefix}Abgebrochen (Strg-C); bisherige Einträge gespeichert.\n")
    if status == "drift":
        parser.exit(1, f"{prefix}Unerwartete PMB-Antwort ({outcome.drift_url}) – API geändert? "
                       "Bisherige Einträge gespeichert, Lauf abgebrochen.\n")
    # Exit 1 is a runtime error; exit 2 stays reserved for argparse usage errors.
    if status == "no_progress":
        what = (f"Die ersten {outcome.attempted} von {outcome.attempted + outcome.untried} Abrufen sind "
                f"gescheitert, {outcome.untried} nicht versucht" if outcome.stop == "leading"
                else f"{_count(failed, 'Abruf ist', 'Abrufe sind')} gescheitert, keiner erfolgreich")
        parser.exit(1, f"{prefix}{what} ({_cause_text(systemic[0])}). {_advice(systemic[0])} "
                       "Cache nicht geschrieben.\n")
    if status == "aborted":
        parser.exit(1, f"{prefix}Lauf nach {_count(outcome.streak, 'systematischen Fehler', 'systematischen Fehlern')} "
                       "in Folge abgebrochen "
                       f"({_cause_text(systemic[-1])}); {_count(fetched, 'Eintrag', 'Einträge')} gespeichert, "
                       f"{outcome.untried} nicht versucht. {_advice(systemic[-1])} "
                       "Erneut ausführen, um den Rest zu holen.\n")
    if failed:
        listed = ", ".join(f"{failure.local_id} ({_cause_text(failure)})" for failure in outcome.failures[:10])
        more = f" und {len(outcome.failures) - 10} weitere" if len(outcome.failures) > 10 else ""
        print(f"Hinweis: {_count(failed, 'Abruf', 'Abrufe')} gescheitert: {listed}{more}. "
              "Ein erneuter Lauf versucht es noch einmal.", file=sys.stderr)


def _count(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"


def _cause_text(failure: Failure) -> str:
    """Short German cause: the HTTP status where there is one, else the cause class."""
    status = re.search(r"HTTP (\d{3})", failure.detail)
    if status:
        return f"HTTP {status.group(1)}"
    return {"transport": "Netzfehler", "tls": "Zertifikatsfehler", "throttle": "Server überlastet",
            "drift": "API geändert", "http": "HTTP-Fehler"}[failure.cause]


def _advice(failure: Failure) -> str:
    """What to do next, matching the cause (network/TLS advice only for those)."""
    if failure.cause == "tls":
        return f"Zertifikate prüfen: {_tls_hint()}"
    if failure.cause == "transport":
        return "Netzwerk/Proxy prüfen."
    if failure.cause == "throttle":
        return "Die PMB drosselt oder ist überlastet; später erneut versuchen oder --delay erhöhen."
    return "Die PMB meldet Fehler; später erneut versuchen."


def _tls_hint() -> str:
    """The certificate fix that applies here: certifi missing, its bundle unusable, or neither."""
    try:
        import certifi
    except ImportError:
        return "certifi installieren oder SSL_CERT_FILE auf ein CA-Bundle setzen."
    bundle = Path(certifi.where())
    if not bundle.is_file() or bundle.stat().st_size == 0:
        return f"das certifi-Bundle {bundle} fehlt oder ist leer: certifi neu installieren oder SSL_CERT_FILE setzen."
    return "SSL_CERT_FILE auf das CA-Bundle der Einrichtung setzen (Proxy mit eigener CA?)."


if __name__ == "__main__":
    main()
