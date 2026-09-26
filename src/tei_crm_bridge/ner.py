"""Interchangeable named entity recognizers with character offsets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


KINDS = {"PER", "LOC", "ORG"}


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str
    score: float
    source: str


class Recognizer(Protocol):
    def find(self, text: str) -> list[Entity]: ...


def resolve_overlaps(items: list[Entity], text: str, threshold: float) -> list[Entity]:
    """Keep high-confidence, non-overlapping spans with valid offsets."""
    valid = [
        item for item in items
        if item.kind in KINDS
        and 0 <= item.start < item.end <= len(text)
        and item.score >= threshold
    ]
    valid.sort(key=lambda e: (-e.score, -(e.end - e.start), e.start))
    chosen: list[Entity] = []
    for candidate in valid:
        if not any(candidate.start < other.end and other.start < candidate.end for other in chosen):
            chosen.append(candidate)
    return sorted(chosen, key=lambda e: e.start)


class GlossaryRecognizer:
    """Small deterministic demonstration backend; not a trained NER model."""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Glossary must be a JSON object")
        self.patterns: list[tuple[re.Pattern[str], str]] = []
        for kind, terms in data.items():
            if kind not in KINDS or not isinstance(terms, list):
                raise ValueError("Glossary keys must be PER, LOC or ORG with lists of terms")
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    raise ValueError("Glossary terms must be non-empty strings")
                pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
                self.patterns.append((pattern, kind))

    def find(self, text: str) -> list[Entity]:
        items = [
            Entity(match.start(), match.end(), kind, 1.0, "glossary")
            for pattern, kind in self.patterns
            for match in pattern.finditer(text)
        ]
        return resolve_overlaps(items, text, 0.0)


class HuggingFaceRecognizer:
    """Use Impresso's historical multilingual NER model via standard Transformers."""

    MODEL = "impresso-project/ner-hipe2020-hist-base"
    REVISION = "afd1b509233560298ae39360ad3186253c5800d3"

    def __init__(self, model: str | None = None, local_files_only: bool = False):
        try:
            from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
        except ImportError as exc:
            raise RuntimeError("Install the NER extra: pip install -e '.[ner]'") from exc
        self.model_id = model or self.MODEL
        options = {"local_files_only": local_files_only, "trust_remote_code": False}
        if model is None:
            options["revision"] = self.REVISION
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, **options)
        model_instance = AutoModelForTokenClassification.from_pretrained(
            self.model_id, use_safetensors=True, **options
        )
        self.pipeline = pipeline(
            "token-classification", model=model_instance, tokenizer=tokenizer,
            aggregation_strategy="simple", device=-1,
        )

    def find(self, text: str) -> list[Entity]:
        label_map = {"pers": "PER", "loc": "LOC", "org": "ORG"}
        return [
            Entity(
                int(item["start"]), int(item["end"]), label_map[str(item["entity_group"]).lower()],
                float(item["score"]), self.model_id,
            )
            for item in self.pipeline(text)
            if str(item["entity_group"]).lower() in label_map
        ]
