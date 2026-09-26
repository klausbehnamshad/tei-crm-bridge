"""Command line interface."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .core import enrich
from .ner import GlossaryRecognizer, HuggingFaceRecognizer
from .preview import write_preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich TEI P5 and export CIDOC CRM Turtle")
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
    for path in args.inputs:
        stem = path.stem
        outputs = {suffix: args.out_dir / f"{stem}{suffix}" for suffix in (".enriched.xml", ".ttl", ".mentions.json", ".html")}
        tei_url = f"{args.tei_base_url}{stem}.enriched.xml" if args.tei_base_url else None
        result = enrich(
            path, outputs[".enriched.xml"], outputs[".ttl"], recognizer, args.base_uri, args.threshold,
            reading=args.reading, output_json=outputs[".mentions.json"], tei_url=tei_url, source_url=args.source_url,
        )
        write_preview(outputs[".enriched.xml"], outputs[".ttl"], outputs[".mentions.json"], outputs[".html"], result)
        print(json.dumps({"input": str(path), **asdict(result)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
