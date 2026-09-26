"""Command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import enrich
from .ner import GlossaryRecognizer, HuggingFaceRecognizer
from .preview import write_preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich TEI P5 and export CIDOC CRM Turtle")
    parser.add_argument("input", type=Path, help="TEI P5 XML file")
    parser.add_argument("--out-dir", type=Path, default=Path("build"))
    parser.add_argument("--engine", choices=["glossary", "hf"], default="glossary")
    parser.add_argument("--glossary", type=Path, default=Path("examples/glossary.json"))
    parser.add_argument("--base-uri", default="https://example.org/tei-crm-demo/")
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--model", help="Optional local Transformers model directory or model ID")
    parser.add_argument("--local-files-only", action="store_true", help="Require already cached model files")
    args = parser.parse_args()
    recognizer = (
        GlossaryRecognizer(args.glossary) if args.engine == "glossary"
        else HuggingFaceRecognizer(model=args.model, local_files_only=args.local_files_only)
    )
    stem = args.input.stem
    result = enrich(
        args.input, args.out_dir / f"{stem}.enriched.xml",
        args.out_dir / f"{stem}.ttl", recognizer, args.base_uri, args.threshold,
    )
    write_preview(
        args.out_dir / f"{stem}.enriched.xml", args.out_dir / f"{stem}.ttl",
        args.out_dir / f"{stem}.html",
        result, args.engine,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
