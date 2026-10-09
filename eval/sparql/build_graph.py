"""Vereinigungsgraph der 40 Originalbriefe für die SPARQL-Abfragen (Release 0.5.0).

    python eval/sparql/build_graph.py [--out-dir eval/work/sparql]

Baut aus den 40 Originalbriefen je einen Graphen nur mit der Auszeichnung der
Edition (Glossarmodus mit leerem Glossar, kein Modell, keine Reconciliation;
Befehl aus R0) und vereinigt sie. Schreibt pro Brief ``<id>.ttl`` und
``union.ttl`` unter ``--out-dir`` (Vorgabe: ``eval/work/``, git-ignoriert).
Der Graph selbst wird nie committet, nur sein Hash in
``eval/sparql/manifest.json`` (SHA-256 über die verketteten Briefdateien).
Weicht der neu berechnete Hash davon ab, bricht das Skript mit Exit 1 ab.
Eingabedateien werden gegen die SHA-256 aus ``eval/manifest.tsv`` geprüft
(eingefrorener Datenstand); genau die 40 IDs je einmal mit einem Commit,
der mit ``corpus_commit`` übereinstimmen muss, sonst Abbruch — ebenso bei
abweichender ``software_version``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rdflib import Graph  # noqa: E402

from tei_crm_bridge import __version__  # noqa: E402
from tei_crm_bridge.core import enrich  # noqa: E402
from tei_crm_bridge.ner import GlossaryRecognizer  # noqa: E402

SPARQL_DIR = Path(__file__).resolve().parent
CORPUS = ROOT / "eval" / "corpus"
BASE_URI = "https://example.org/tei-crm-demo/"
EMPTY_GLOSSARY = {"PER": [], "LOC": [], "ORG": []}


def corpus_letters() -> list[Path]:
    """Die 40 Originalbriefe in fester Reihenfolge."""
    letters = sorted(CORPUS.glob("L*.xml"))
    assert len(letters) == 40, f"erwartet 40 Briefe, gefunden {len(letters)}"
    return letters


def validate_rows(rows: list[dict]) -> str:
    """Genau 40 eindeutige TSV-Zeilen mit einem Commit; gibt den Commit zurück."""
    ids = [row["letter"] for row in rows]
    if len(rows) != 40 or len(set(ids)) != 40:
        raise SystemExit(f"eval/manifest.tsv braucht genau die 40 IDs je einmal, gefunden {len(rows)} Zeilen")
    commits = {row["commit"] for row in rows}
    if len(commits) != 1:
        raise SystemExit(f"eval/manifest.tsv nennt mehrere Commits: {sorted(commits)}")
    return rows[0]["commit"]


def check_provenance(manifest: dict, commit: str) -> None:
    """Manifest weist den tatsächlichen Daten- und Softwarestand aus, sonst Abbruch."""
    if manifest.get("software_version") != __version__:
        raise SystemExit(f"Software weicht ab: manifest nennt {manifest.get('software_version')}, "
                         f"Werkzeug ist {__version__}")
    if manifest.get("corpus_commit") != commit:
        raise SystemExit(f"Datenstand weicht ab: manifest nennt {manifest.get('corpus_commit')}, "
                         f"eval/manifest.tsv nennt {commit}")


def check_inputs(letters: list[Path]) -> str:
    """Eingaben stehen fest: SHA-256 jedes Briefs gegen eval/manifest.tsv; gibt den Commit zurück."""
    with (ROOT / "eval" / "manifest.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    commit = validate_rows(rows)
    by_id = {row["letter"]: row["sha256"] for row in rows}
    if {path.stem for path in letters} != set(by_id):
        raise SystemExit("Briefauswahl passt nicht zu den 40 IDs aus eval/manifest.tsv")
    for path in letters:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if by_id.get(path.stem) != digest:
            raise SystemExit(f"Eingabe verändert: {path.name} passt nicht zu eval/manifest.tsv")
    return commit


def letter_graph(path: Path, out_dir: Path, recognizer: GlossaryRecognizer) -> Path:
    """Graph eines Briefs nur aus der Edition; gibt die .ttl-Datei zurück."""
    target = out_dir / "letters" / f"{path.stem}.ttl"
    enriched = target.with_suffix(".enriched.xml")
    mentions = target.with_suffix(".mentions.json")
    enrich(path, enriched, target, recognizer, BASE_URI,
           output_json=mentions, tei_url=None, source_url=None, reconciliation=None)
    enriched.unlink(missing_ok=True)
    mentions.unlink(missing_ok=True)
    return target


def build_letters(out_dir: Path) -> list[Path]:
    """Baut alle 40 Briefgraphen; gibt die .ttl-Dateien in Buchstabenfolge zurück."""
    recognizer = GlossaryRecognizer(write_glossary(out_dir))
    letters = corpus_letters()
    commit = check_inputs(letters)
    check_provenance(load_manifest(), commit)
    return [letter_graph(path, out_dir, recognizer) for path in letters]


def build_union(letter_files: list[Path]) -> Graph:
    """Vereinigungsgraph aus den Briefdateien (nur für Abfragen, nicht für den Hash)."""
    union = Graph()
    for target in letter_files:
        union.parse(target, format="turtle")
    return union


def write_glossary(out_dir: Path) -> Path:
    """Leeres Glossar als Datei (GlossaryRecognizer braucht einen Pfad)."""
    path = out_dir / "empty-glossary.json"
    path.write_text(json.dumps(EMPTY_GLOSSARY), encoding="utf-8")
    return path


def files_hash(letter_files: list[Path]) -> str:
    """SHA-256 über die verketteten Briefdateien in Buchstabenfolge.

    Die Turtle-Dateien sind Byte-deterministisch (der Serializer schreibt
    unbenannte Blank Nodes als ``[...]`` in stabiler Reihenfolge); der
    geparste Vereinigungsgraph bekäme dagegen bei jedem Einlesen frische
    Blank-Node-IDs und ist deshalb keine stabile Hash-Grundlage.
    """
    digest = hashlib.sha256()
    for target in letter_files:
        digest.update(target.read_bytes())
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads((SPARQL_DIR / "manifest.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, default=ROOT / "eval" / "work" / "sparql")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "letters").mkdir(exist_ok=True)
    letter_files = build_letters(args.out_dir)
    digest = files_hash(letter_files)
    manifest = load_manifest()
    if digest != manifest.get("graph_sha256"):
        raise SystemExit(f"Hash weicht ab: berechnet {digest}, Manifest {manifest.get('graph_sha256')}")
    union = build_union(letter_files)
    (args.out_dir / "union.ttl").write_bytes(union.serialize(format="turtle").encode("utf-8"))
    print(f"union ok: 40 Briefe, {len(union)} Tripel, sha256 {digest}")


if __name__ == "__main__":
    main()
