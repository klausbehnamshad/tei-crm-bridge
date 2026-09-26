"""Command line interface."""

from __future__ import annotations

import argparse
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
from .reconcile import PmbResolver, collect_entities, load_cache, new_cache, save_cache, summarize, update_cache


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


def main() -> None:
    # Separate parsers: an optional positional on the enrich parser would swallow
    # a subcommand name, so dispatch on argv[1] first.
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
    interrupted = False
    try:
        fetched, failed, warnings = update_cache(cache, entities, resolver, offline=args.offline,
                                                 checkpoint=lambda: save_cache(args.cache, cache))
    except KeyboardInterrupt:
        interrupted = True
        fetched = len(set(cache["entries"]) - known)
        failed, warnings = 0, []
    skipped = sum(1 for local_id, info in entities.items()
                  if local_id not in cache["entries"] and not resolver.supports(info["kind"], local_id))
    changed = False
    if fetched > 0 or (failed == 0 and not interrupted and not args.cache.is_file()):
        try:
            save_cache(args.cache, cache)
        except OSError as error:
            parser.exit(1, f"tei-crm reconcile: Cache {args.cache} konnte nicht geschrieben werden "
                           f"({error}); {fetched} Abrufe verworfen.\n")
        changed = True
    report = {"cache": str(args.cache), "offline": args.offline, "entities": len(entities),
              "fetched": fetched, "failed": failed, "skipped": skipped, "written": changed,
              "summary": summarize(entities, cache), "warnings": warnings}
    if interrupted:
        report["interrupted"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if interrupted:
        parser.exit(130, "tei-crm reconcile: Abgebrochen (Strg-C); bisherige Einträge gespeichert.\n")
    drift = next((match.group(1) for warning in warnings
                  if (match := re.search(r"PMB-API geändert\? (\S+): ", warning)) is not None), None)
    if drift is not None:
        parser.exit(1, f"tei-crm reconcile: Unerwartete PMB-Antwort ({drift}) – API geändert? "
                       "Bisherige Einträge gespeichert, Lauf abgebrochen.\n")
    if fetched == 0 and failed > 0:
        # Total failure: no new cache file, existing cache untouched; exit 1 is
        # a runtime error while exit 2 stays reserved for argparse usage errors.
        parser.exit(1, f"tei-crm reconcile: Alle {failed} PMB-Abrufe gescheitert ({warnings[0]}). "
                       "Netzwerk/Proxy prüfen; bei Zertifikatsfehlern certifi installieren oder "
                       "SSL_CERT_FILE auf ein CA-Bundle setzen. Cache nicht geschrieben.\n")
    if failed:
        print(f"Hinweis: {failed} Abrufe gescheitert; ein erneuter Lauf holt sie nach.", file=sys.stderr)


if __name__ == "__main__":
    main()
