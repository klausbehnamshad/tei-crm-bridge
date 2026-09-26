"""Select the evaluation corpus from a pinned commit of schnitzler-briefe-data.

Selection rule (deterministic, no manual choice):

1. Candidate pool: every 25th letter file of ``data/editions`` in file-name
   order (L00001, L00026, ...).
2. Eligible: at least one reference PER/LOC/ORG span (see ``goldlib``) and at
   least 150 characters of projected reading text.
3. Four length bins by quartiles of projected text length; from each bin ten
   letters at evenly spaced positions in file-name order.

The selected files are copied unchanged to ``eval/corpus`` and described in
``eval/manifest.tsv`` (source, commit, checksums, licence, counts, features).

    python eval/select_corpus.py --commit 76870800b474b0ab829c65ef1ad84c3ba5f81c4e
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goldlib import KINDS, PARSER, features, gold_spans  # noqa: E402

REPO = "arthur-schnitzler/schnitzler-briefe-data"
EVAL = Path(__file__).resolve().parent
STEP, PER_BIN, BINS, MIN_CHARS = 25, 10, 4, 150
TEI = "{http://www.tei-c.org/ns/1.0}"


def _get(url: str) -> bytes:
    try:  # python.org builds on macOS ship without CA certificates
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = None
    with urllib.request.urlopen(url, timeout=60, context=context) as response:
        return response.read()


def _editions(commit: str) -> list[dict]:
    api = f"https://api.github.com/repos/{REPO}/git/trees/"
    tree = json.loads(_get(api + commit))
    data = next(item for item in tree["tree"] if item["path"] == "data")
    editions = next(item for item in json.loads(_get(api + data["sha"]))["tree"] if item["path"] == "editions")
    listing = json.loads(_get(api + editions["sha"]))
    if listing.get("truncated"):
        raise RuntimeError("GitHub tree listing truncated")
    return sorted((item for item in listing["tree"] if item["path"].endswith(".xml")), key=lambda item: item["path"])


def _git_blob_sha(content: bytes) -> str:
    """SHA-1 of a file as git stores it; must equal the SHA in the tree listing."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _raw_url(commit: str, name: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{commit}/data/editions/{name}"


def _describe(name: str, path: Path) -> dict:
    root = etree.parse(str(path), PARSER).getroot()
    spans, excluded, texts = gold_spans(name.removesuffix(".xml"), root)
    licence = root.find(f".//{TEI}publicationStmt/{TEI}availability/{TEI}licence")
    handle = root.find(f".//{TEI}publicationStmt/{TEI}idno[@type='handle']")
    title = root.find(f".//{TEI}titleStmt/{TEI}title[@level='a']")
    return {
        "chars": sum(len(text) for text in texts),
        "blocks": len(texts),
        **{f"gold_{kind}": sum(1 for span in spans if span.kind == kind) for kind in KINDS},
        "implied_excluded": excluded["implied"],
        "nested_excluded": excluded["nested"],
        "features": ",".join(features(root)),
        "licence": licence.get("target", "") if licence is not None else "",
        "handle": (handle.text or "").strip() if handle is not None else "",
        "title": " ".join("".join(title.itertext()).split()) if title is not None else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--commit", required=True, help="full commit SHA of schnitzler-briefe-data")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must be a full 40-character commit SHA")
    cache = EVAL / ".cache" / args.commit
    cache.mkdir(parents=True, exist_ok=True)

    files = _editions(args.commit)
    pool = files[::STEP]
    print(f"{len(files)} letters at {args.commit[:12]}, pool of {len(pool)}", file=sys.stderr)

    def fetch(item: dict) -> None:
        target = cache / item["path"]
        if not target.exists():
            target.write_bytes(_get(_raw_url(args.commit, item["path"])))

    with ThreadPoolExecutor(8) as executor:
        list(executor.map(fetch, pool))
    for item in pool:  # cached or downloaded, every file must be the blob of the pinned tree
        if _git_blob_sha((cache / item["path"]).read_bytes()) != item["sha"]:
            raise SystemExit(f"{item['path']}: content does not match git blob {item['sha']}")

    described = []
    for item in pool:
        info = _describe(item["path"], cache / item["path"])
        if info["chars"] >= MIN_CHARS and sum(info[f"gold_{kind}"] for kind in KINDS) > 0:
            described.append({"item": item, **info})
    lengths = sorted(entry["chars"] for entry in described)
    cuts = [lengths[len(lengths) * quarter // BINS] for quarter in range(1, BINS)]
    selected = []
    for number in range(BINS):
        low = cuts[number - 1] if number else -1
        high = cuts[number] if number < BINS - 1 else float("inf")
        members = [entry for entry in described if low < entry["chars"] <= high]
        if len(members) < PER_BIN:
            raise RuntimeError(f"bin {number + 1} has only {len(members)} letters")
        picks = [round(position * (len(members) - 1) / (PER_BIN - 1)) for position in range(PER_BIN)]
        selected += [{**members[position], "length_bin": number + 1} for position in picks]
    print(f"{len(described)} eligible, bin limits {cuts}, selected {len(selected)}", file=sys.stderr)

    corpus = EVAL / "corpus"
    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir()
    columns = [
        "letter", "title", "length_bin", "chars", "blocks", "gold_PER", "gold_LOC", "gold_ORG",
        "implied_excluded", "nested_excluded", "features", "source_url", "commit", "git_blob_sha",
        "sha256", "licence", "handle",
    ]
    with (EVAL / "manifest.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in sorted(selected, key=lambda entry: entry["item"]["path"]):
            name = entry["item"]["path"]
            shutil.copyfile(cache / name, corpus / name)
            writer.writerow({
                **{column: entry.get(column, "") for column in columns},
                "letter": name.removesuffix(".xml"),
                "source_url": _raw_url(args.commit, name),
                "commit": args.commit,
                "git_blob_sha": entry["item"]["sha"],
                "sha256": hashlib.sha256((corpus / name).read_bytes()).hexdigest(),
            })


if __name__ == "__main__":
    main()
