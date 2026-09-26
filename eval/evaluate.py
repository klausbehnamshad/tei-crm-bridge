"""Measure name recognition against the editorial annotation of the corpus.

    python eval/evaluate.py prepare
    python eval/evaluate.py run --label v0.2-hf --src src -- --engine hf --local-files-only
    python eval/evaluate.py score --label v0.2-hf
    python eval/evaluate.py compare v0.1-hf v0.2-hf
    python eval/evaluate.py run --label v0.2-hf-original --input original -- --engine hf --local-files-only
    python eval/evaluate.py integrity --label v0.2-hf-original

``prepare`` checks every corpus file against ``manifest.tsv`` and writes copies
without PER/LOC/ORG references (``work/input``). ``run`` passes them through the
command line tool of any checkout (``--src``), so older versions can be
measured with the same inputs. ``score`` compares the tool output with the
editorial references, both projected with ``tei_crm_bridge.projection``.
``integrity`` inspects a run on the unchanged letters. ``score`` and
``integrity`` exit with status 1 if they find a problem.

Matching rule, fixed before the first measurement:

* strict: same letter, block, start, end and type;
* overlap: same letter, block and type, at least one shared character;
  one-to-one, largest overlap first;
* predictions are new PER/LOC/ORG elements in the output body plus stand-off
  mentions from ``<stem>.mentions.json`` (if the tool writes one).

Values are stored unrounded and rounded once, for display.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter
from importlib import metadata
from pathlib import Path

from lxml import etree

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(ROOT / "src"))
from goldlib import KINDS, PARSER, Span, gold_spans, strip_references, trim  # noqa: E402

from tei_crm_bridge.projection import find_blocks, local_name, name_kind, project  # noqa: E402
from tei_crm_bridge.writeback import canonical, strip_enrichment  # noqa: E402

WORK, RUNS, RESULTS = EVAL / "work", EVAL / "runs", EVAL / "results"
CATEGORIES = ("missed", "spurious", "boundary", "type")
CATEGORY_LABELS = {
    "missed": "nicht erkannt",
    "spurious": "falscher Treffer",
    "boundary": "Grenze abweichend",
    "type": "Typ abweichend",
}
#: Prefix of the @ref that v0.1 (which set no @resp) gave to every new name.
V01_REF = "https://example.org/tei-crm-demo/"
DRIVER = """
import sys
src, out, *rest = sys.argv[1:]
split = rest.index("--")
inputs, options = rest[:split], rest[split + 1:]
sys.path.insert(0, src)
from tei_crm_bridge import cli
for path in inputs:
    sys.argv = ["tei-crm", path, "--out-dir", out, *options]
    cli.main()
"""


def manifest() -> list[dict]:
    with (EVAL / "manifest.tsv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _corpus_root(row: dict) -> etree._Element:
    path = EVAL / "corpus" / f"{row['letter']}.xml"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != row["sha256"]:
        raise SystemExit(f"{path}: checksum {digest} does not match manifest")
    return etree.parse(str(path), PARSER).getroot()


def prepare(_args: argparse.Namespace) -> None:
    target = WORK / "input"
    target.mkdir(parents=True, exist_ok=True)
    stale = []
    for row in manifest():
        root = _corpus_root(row)
        gold, _, texts = gold_spans(row["letter"], root)
        counts = {"chars": sum(map(len, texts)), "blocks": len(texts), **{f"gold_{k}": sum(s.kind == k for s in gold) for k in KINDS}}
        stale += [f"{row['letter']} {key}: manifest {row[key]}, now {value}" for key, value in counts.items() if str(value) != row[key]]
        etree.ElementTree(strip_references(root)).write(str(target / f"{row['letter']}.xml"), encoding="utf-8", xml_declaration=True)
    if stale:
        raise SystemExit("manifest.tsv is out of date with the projection; rerun select_corpus.py:\n  " + "\n  ".join(stale))
    print(f"{len(manifest())} letters checked and prepared in {target}")


def package_tree(folder: Path) -> str:
    """Git tree hash of the package's .py files; equals ``git rev-parse <commit>:src/tei_crm_bridge``."""
    entries = b""
    for path in sorted(folder.glob("*.py"), key=lambda p: p.name.encode()):
        content = path.read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(content) + content).digest()
        entries += b"100644 " + path.name.encode() + b"\0" + blob
    return hashlib.sha1(b"tree %d\0" % len(entries) + entries).hexdigest()


def _tool(src: Path) -> dict:
    """Version and exact source of the tool that produced a run."""
    package = src / "tei_crm_bridge"
    version = re.search(r'__version__ = "([^"]+)"', (package / "__init__.py").read_text()).group(1)
    tool = {"version": version, "package_tree": package_tree(package)}
    try:
        commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        committed = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD:./tei_crm_bridge"], capture_output=True, text=True, check=True).stdout.strip()
        if committed == tool["package_tree"]:
            tool["commit"] = commit
    except (OSError, subprocess.CalledProcessError):
        pass  # an exported snapshot: the tree hash identifies the source
    return tool


def _versions() -> dict:
    found = {"python": platform.python_version()}
    for package in ("lxml", "rdflib", "transformers", "torch", "tokenizers"):
        try:
            found[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    return found


def run(args: argparse.Namespace) -> None:
    src = Path(args.src).resolve()
    out = RUNS / args.label
    shutil.rmtree(out, ignore_errors=True)  # never score leftovers of an earlier run
    out.mkdir(parents=True)
    folder = WORK / "input" if args.input == "stripped" else EVAL / "corpus"
    inputs = [str(folder / f"{row['letter']}.xml") for row in manifest()]
    if not all(Path(path).exists() for path in inputs):
        raise SystemExit("run `prepare` first")
    options = args.options[1:] if args.options[:1] == ["--"] else args.options
    completed = subprocess.run(
        [sys.executable, "-c", DRIVER, str(src), str(out), *inputs, "--", *options],
        capture_output=True, text=True,
    )
    (out / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (out / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise SystemExit(f"tool failed, see {out / 'stderr.log'}")
    (out / "run.json").write_text(json.dumps({
        "label": args.label, "input": args.input, "tool": _tool(src), "options": options, "versions": _versions(),
    }, indent=2), encoding="utf-8")
    print(f"{len(inputs)} letters processed into {out}")


def _v01_scope(projection) -> set[int]:
    """Projected positions v0.1 read: text inside a ``<p>`` (it processed ``body//p``)."""
    positions = set()
    for segment in projection.segments:
        owner = segment.owner if segment.slot == "text" else segment.owner.getparent()
        if any(local_name(node) == "p" for node in [owner, *owner.iterancestors()]):
            positions.update(range(segment.start, segment.end))
    return positions


def _predictions(letter: str, run_dir: Path, gold_texts: list[str]) -> tuple[list[Span], Counter, list[str]]:
    """New names in the tool output plus stand-off mentions, and structural findings."""
    root = etree.parse(str(run_dir / f"{letter}.enriched.xml"), PARSER).getroot()
    spans, structure, problems = [], Counter(), []
    projections = [project(block) for block in find_blocks(root)]
    texts = [projection.text for projection in projections]
    if texts != gold_texts:
        problems.append(f"{letter}: projected text differs from the input")
    for index, projection in enumerate(projections):
        for item in projection.annotations:
            if item.kind in KINDS:
                start, end = trim(projection.text, item.start, item.end)
                spans.append(Span(letter, index, start, end, item.kind, projection.text[start:end]))
                structure["inline"] += 1
    for body in root.iter("{http://www.tei-c.org/ns/1.0}body"):
        for node in body.iter():
            if local_name(node) not in {"persName", "placeName", "orgName"}:
                continue
            ancestors = {local_name(ancestor) for ancestor in node.iterancestors()}
            structure["in_note"] += "note" in ancestors
            structure["in_del"] += "del" in ancestors
            structure["in_other_reference"] += bool(ancestors & {"rs", "persName", "placeName", "orgName", "name"})
            structure["in_c_or_g"] += local_name(node.getparent()) in {"c", "g"}
    sidecar = run_dir / f"{letter}.mentions.json"
    if sidecar.exists():
        for mention in json.loads(sidecar.read_text(encoding="utf-8"))["mentions"]:
            if mention["origin"] == "automatic" and not mention["inline"]:
                text = texts[mention["block"]]
                start, end = trim(text, mention["start"], mention["end"])
                spans.append(Span(letter, mention["block"], start, end, mention["kind"], text[start:end]))
                structure["standoff"] += 1
    return sorted(spans), structure, problems


def _prf(tp: int, predicted: int, gold: int) -> dict:
    precision = tp / predicted if predicted else 0.0
    recall = tp / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "predicted": predicted, "gold": gold, "precision": precision, "recall": recall, "f1": f1}


def _overlap_pairs(gold: list[Span], predicted: list[Span]) -> list[tuple[Span, Span]]:
    candidates = sorted(
        ((min(g.end, p.end) - max(g.start, p.start), g, p) for g in gold for p in predicted if g.kind == p.kind and g.overlaps(p)),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    used_gold, used_pred, pairs = set(), set(), []
    for _, g, p in candidates:
        if g not in used_gold and p not in used_pred:
            used_gold.add(g)
            used_pred.add(p)
            pairs.append((g, p))
    return pairs


def _flat(text: str) -> str:
    return " ".join(text.split())


def _context(text: str, start: int, end: int, width: int = 45) -> str:
    return f"…{_flat(text[max(0, start - width):start])} [{_flat(text[start:end])}] {_flat(text[end:end + width])}…"


def _key(span: Span) -> tuple:
    return (span.letter, span.block, span.start, span.end, span.kind)


def _strict_tp(gold: list[Span], predicted: list[Span]) -> int:
    """Count exact matches one-to-one, including duplicate spans."""
    return sum((Counter(map(_key, gold)) & Counter(map(_key, predicted))).values())


def score(args: argparse.Namespace) -> None:
    run_dir = RUNS / args.label
    gold_all, pred_all, texts, structure, problems, excluded = [], [], {}, Counter(), [], Counter()
    block_names: dict[tuple[str, int], str] = {}
    scope: dict[tuple[str, int], set[int]] = {}
    for row in manifest():
        root = _corpus_root(row)
        for index, block in enumerate(find_blocks(root)):
            block_names[(row["letter"], index)] = local_name(block)
            scope[(row["letter"], index)] = _v01_scope(project(block))
        gold, dropped, gold_texts = gold_spans(row["letter"], root)
        predicted, found, issues = _predictions(row["letter"], run_dir, gold_texts)
        gold_all += gold
        pred_all += predicted
        texts[row["letter"]] = gold_texts
        structure.update(found)
        excluded.update(dropped)
        problems += issues

    gold_keys, pred_keys = {_key(s) for s in gold_all}, {_key(s) for s in pred_all}

    def measure(gold: list[Span], predicted: list[Span]) -> dict:
        found = {"strict": {}, "overlap": {}}
        for kind in (*KINDS, "all"):
            g = [s for s in gold if kind in (s.kind, "all")]
            p = [s for s in predicted if kind in (s.kind, "all")]
            found["strict"][kind] = _prf(_strict_tp(g, p), len(p), len(g))
            found["overlap"][kind] = _prf(len(_overlap_pairs(g, p)), len(p), len(g))
        return found

    def in_v01_scope(span: Span) -> bool:
        positions = scope[(span.letter, span.block)]
        return span.start in positions and span.end - 1 in positions

    metrics = measure(gold_all, pred_all)
    metrics_v01 = measure([s for s in gold_all if in_v01_scope(s)], [s for s in pred_all if in_v01_scope(s)])

    errors = []
    for span in pred_all:
        if _key(span) in gold_keys:
            continue
        same = [g for g in gold_all if g.overlaps(span) and g.kind == span.kind]
        other = [g for g in gold_all if g.overlaps(span) and g.kind != span.kind]
        category = "boundary" if same else "type" if other else "spurious"
        reference = (same or other or [None])[0]
        errors.append({"category": category, "predicted": span.as_dict(), "gold": reference.as_dict() if reference else None})
    for span in gold_all:
        if _key(span) not in pred_keys and not any(p.overlaps(span) for p in pred_all):
            errors.append({"category": "missed", "predicted": None, "gold": span.as_dict()})
    for error in errors:
        anchor = error["predicted"] or error["gold"]
        error["context"] = _context(texts[anchor["letter"]][anchor["block"]], anchor["start"], anchor["end"])
        error["block_type"] = block_names[(anchor["letter"], anchor["block"])]
    errors.sort(key=lambda e: (CATEGORIES.index(e["category"]), *(lambda a: (a["letter"], a["block"], a["start"]))(e["predicted"] or e["gold"])))

    spotcheck, spot_problems = _spotcheck(pred_all, gold_keys, texts)
    problems += spot_problems
    rows = manifest()
    result = {
        "label": args.label,
        "run": json.loads((run_dir / "run.json").read_text(encoding="utf-8")),
        "corpus": {"letters": len(rows), "commit": rows[0]["commit"], "gold": len(gold_all), "excluded_gold": dict(excluded)},
        "metrics": metrics,
        "metrics_v01_scope": metrics_v01,
        "error_counts": dict(Counter(e["category"] for e in errors)),
        "errors_by_block_type": {
            category: dict(sorted(Counter(e["block_type"] for e in errors if e["category"] == category).items()))
            for category in CATEGORIES
        },
        "structure": {key: structure[key] for key in ("inline", "standoff", "in_note", "in_del", "in_other_reference", "in_c_or_g")},
        "spotcheck": spotcheck,
        "problems": problems,
        "examples": _examples(errors),
        "errors": errors,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (RESULTS / f"{args.label}.md").write_text(_report(result), encoding="utf-8")
    print(_report(result))
    if problems:
        sys.exit(1)


def _examples(errors: list[dict], count: int = 10) -> list[dict]:
    """Deterministic sample: quotas filled round robin, evenly spaced within each category."""
    groups = {category: [e for e in errors if e["category"] == category] for category in CATEGORIES}
    quota = dict.fromkeys(CATEGORIES, 0)
    remaining = count
    while remaining and any(quota[c] < len(groups[c]) for c in CATEGORIES):
        for category in CATEGORIES:
            if remaining and quota[category] < len(groups[category]):
                quota[category] += 1
                remaining -= 1
    picked = []
    for category in CATEGORIES:
        items, size = groups[category], quota[category]
        picked += [items[round(i * (len(items) - 1) / max(size - 1, 1))] for i in range(size)]
    return picked


def spotcheck_spans(texts: dict[str, list[str]]) -> tuple[list[Span], list[str], set[str]]:
    """Unannotated names of the spot check, located by text and occurrence in the current projection."""
    path = EVAL / "spotcheck.tsv"
    if not path.exists():
        return [], [], set()
    spans, problems, letters = [], [], set()
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            letters.add(row["letter"])
            text = texts[row["letter"]][int(row["block"])]
            starts = [match.start() for match in re.finditer(re.escape(row["text"]), text)]
            if len(starts) < int(row["occurrence"]):
                problems.append(f"spotcheck: {row['letter']} block {row['block']}: {row['text']!r} not found")
                continue
            start = starts[int(row["occurrence"]) - 1]
            spans.append(Span(row["letter"], int(row["block"]), start, start + len(row["text"]), row["kind"], row["text"]))
    return spans, problems, letters


def _spotcheck(predicted: list[Span], gold_keys: set, texts: dict[str, list[str]]) -> tuple[dict | None, list[str]]:
    """Counts only: how many non-matching predictions in the checked letters are listed unannotated names."""
    listed, problems, letters = spotcheck_spans(texts)
    if not letters:
        return None, problems
    checked = [span for span in predicted if span.letter in letters]
    unmatched = [span for span in checked if _key(span) not in gold_keys]
    listed_keys = {_key(span) for span in listed}
    exact = [span for span in unmatched if _key(span) in listed_keys]
    overlapping = [span for span in unmatched if _key(span) not in listed_keys and any(e.overlaps(span) and e.kind == span.kind for e in listed)]
    return {
        "letters": len(letters),
        "unannotated_names_listed": len(listed),
        "predicted": len(checked),
        "strict_tp": len(checked) - len(unmatched),
        "unmatched": len(unmatched),
        "unmatched_equal_to_listed_name": len(exact),
        "unmatched_overlapping_listed_name": len(overlapping),
    }, problems


def _table(metrics: dict) -> list[str]:
    lines = [
        "| Typ | Gold | Vorhergesagt | strikt P | strikt R | strikt F1 | Überlappung P | Überlappung R | Überlappung F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind in (*KINDS, "all"):
        s, o = metrics["strict"][kind], metrics["overlap"][kind]
        lines.append(
            f"| {'gesamt' if kind == 'all' else kind} | {s['gold']} | {s['predicted']} | {s['precision']:.3f} | {s['recall']:.3f} | {s['f1']:.3f} "
            f"| {o['precision']:.3f} | {o['recall']:.3f} | {o['f1']:.3f} |"
        )
    return lines


def _report(result: dict) -> str:
    tool = result["run"]["tool"]
    commit_note = f", Commit `{tool['commit'][:12]}`" if "commit" in tool else ""
    lines = [
        f"# Evaluation `{result['label']}`",
        "",
        f"Korpus: {result['corpus']['letters']} Briefe aus schnitzler-briefe-data @ `{result['corpus']['commit'][:12]}`, "
        f"{result['corpus']['gold']} Referenzannotationen "
        f"(ausgeschlossen: {', '.join(f'{v} {k}' for k, v in sorted(result['corpus']['excluded_gold'].items()))}).",
        f"Werkzeug: Version {tool['version']}, Paketbaum `{tool['package_tree'][:12]}`"
        f"{commit_note}, "
        f"Optionen `{' '.join(result['run']['options'])}`.",
        "",
        "Alle Textblöcke:",
        "",
        *_table(result["metrics"]),
        "",
        "Nur Text in `<p>` (der Umfang, den v0.1 las):",
        "",
        *_table(result["metrics_v01_scope"]),
    ]
    counts, structure, by_block = result["error_counts"], result["structure"], result["errors_by_block_type"]
    lines += [
        "",
        "Fehler: " + ", ".join(f"{counts.get(c, 0)} {CATEGORY_LABELS[c]}" for c in CATEGORIES) + ".",
        "Nach Blocktyp: " + "; ".join(
            f"{CATEGORY_LABELS[c]}: " + ", ".join(f"{name} {count}" for name, count in by_block[c].items())
            for c in CATEGORIES if by_block[c]
        ) + ".",
        f"Struktur: {structure['inline']} Treffer inline, {structure['standoff']} stand-off; neue Namen in `<note>`: {structure['in_note']}, "
        f"in `<del>`: {structure['in_del']}, in anderer Referenz (Werk o. Ä.): {structure['in_other_reference']}, direkt in `<c>`/`<g>`: {structure['in_c_or_g']}.",
    ]
    if result["spotcheck"]:
        sc = result["spotcheck"]
        lines += [
            "",
            f"Stichprobe (Vorprüfung, {sc['letters']} Briefe, {sc['unannotated_names_listed']} dort nicht annotierte Namen): von {sc['predicted']} Vorhersagen "
            f"stimmen {sc['strict_tp']} exakt mit der Referenz überein; von den {sc['unmatched']} übrigen sind {sc['unmatched_equal_to_listed_name']} "
            f"genau ein nicht annotierter Name und {sc['unmatched_overlapping_listed_name']} überlappen einen.",
        ]
    if result["problems"]:
        lines += ["", "Probleme: " + "; ".join(result["problems"])]
    lines += ["", "## Fehlerbeispiele", "", "| Kategorie | Brief | Vorhersage | Referenz | Kontext |", "| --- | --- | --- | --- | --- |"]
    for example in result["examples"]:
        pred, gold = example["predicted"], example["gold"]
        shown = ["{} „{}“".format(span["kind"], _flat(span["text"])) if span else "–" for span in (pred, gold)]
        lines.append(f"| {CATEGORY_LABELS[example['category']]} | {(pred or gold)['letter']} | {shown[0]} | {shown[1]} | {example['context'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def integrity(args: argparse.Namespace) -> None:
    """Check a run on the original letters: text, existing markup, nesting. Exit 1 on any finding."""
    run_dir = RUNS / args.label

    def v01_name(node: etree._Element) -> bool:  # v0.1 set no @resp; its new names carry its @ref prefix
        return (node.get("ref") or "").startswith(V01_REF) and node.get("resp") is None

    totals, failures = Counter(), []
    for row in manifest():
        original = _corpus_root(row)
        output = etree.parse(str(run_dir / f"{row['letter']}.enriched.xml"), PARSER).getroot()
        totals["letters"] += 1
        runs = {node.get("{http://www.w3.org/XML/1998/namespace}id") for node in output.iter("{http://www.tei-c.org/ns/1.0}application")}
        new = [
            node for node in output.iter()
            if local_name(node) in {"persName", "placeName", "orgName"} and ((node.get("resp") or "")[1:] in runs or v01_name(node))
        ]
        totals["new_inline"] += len(new)
        for node in new:
            ancestors = list(node.iterancestors())
            in_reference = any(name_kind(a) for a in ancestors)
            in_note = any(local_name(a) == "note" for a in ancestors)
            in_del = any(local_name(a) == "del" for a in ancestors)
            in_c = local_name(node.getparent()) in {"c", "g"}
            totals["in_existing_name_reference"] += in_reference
            totals["in_note"] += in_note
            totals["in_reference_and_note"] += in_reference and in_note
            totals["in_del"] += in_del
            totals["in_c_or_g"] += in_c
            totals["affected"] += in_reference or in_note or in_del or in_c
        if [project(b).text for b in find_blocks(original)] != [project(b).text for b in find_blocks(output)]:
            totals["reading_text_changed"] += 1
            failures.append(f"{row['letter']}: reading text changed")
        if canonical(strip_enrichment(output, v01_name)) != canonical(original):
            totals["markup_changed"] += 1
            failures.append(f"{row['letter']}: existing markup changed")
    keys = ("new_inline", "affected", "in_existing_name_reference", "in_note", "in_reference_and_note", "in_del", "in_c_or_g",
            "reading_text_changed", "markup_changed")
    run_info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    report = {"label": args.label, "tool": run_info["tool"], "letters": totals["letters"], **{key: totals[key] for key in keys}, "failures": failures}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"integrity_{args.label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["affected"] or failures:
        sys.exit(1)


def compare(args: argparse.Namespace) -> None:
    before, after = (json.loads((RESULTS / f"{label}.json").read_text(encoding="utf-8")) for label in (args.before, args.after))
    lines = [f"# Vergleich `{args.before}` → `{args.after}`", "", "| Maß | Typ | vorher | nachher | Differenz |", "| --- | --- | ---: | ---: | ---: |"]
    for scope, label in (("metrics", ""), ("metrics_v01_scope", " (nur `<p>`)")):
        for mode in ("strict", "overlap"):
            for kind in (*KINDS, "all"):
                for measure in ("precision", "recall", "f1"):
                    a, b = round(before[scope][mode][kind][measure], 3), round(after[scope][mode][kind][measure], 3)
                    lines.append(f"| {mode} {measure}{label} | {kind} | {a:.3f} | {b:.3f} | {b - a:+.3f} |")
    lines += ["", "| Befund | vorher | nachher |", "| --- | ---: | ---: |"]
    for category in CATEGORIES:
        lines.append(f"| {CATEGORY_LABELS[category]} | {before['error_counts'].get(category, 0)} | {after['error_counts'].get(category, 0)} |")
    for key, value in before["structure"].items():
        lines.append(f"| Struktur: {key} | {value} | {after['structure'][key]} |")
    text = "\n".join(lines) + "\n"
    (RESULTS / f"compare_{args.before}_{args.after}.md").write_text(text, encoding="utf-8")
    print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="TEI CRM Bridge evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare").set_defaults(func=prepare)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--src", default=str(ROOT / "src"), help="src directory of the tool version to run")
    run_parser.add_argument("--input", choices=["stripped", "original"], default="stripped",
                            help="letters without PER/LOC/ORG references (evaluation) or unchanged (integrity)")
    run_parser.add_argument("options", nargs=argparse.REMAINDER, help="options for tei-crm after --")
    run_parser.set_defaults(func=run)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--label", required=True)
    score_parser.set_defaults(func=score)
    integrity_parser = commands.add_parser("integrity")
    integrity_parser.add_argument("--label", required=True)
    integrity_parser.set_defaults(func=integrity)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("before")
    compare_parser.add_argument("after")
    compare_parser.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
