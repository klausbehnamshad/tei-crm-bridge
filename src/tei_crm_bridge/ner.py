"""Interchangeable named entity recognizers with character offsets."""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KINDS = ("PER", "LOC", "ORG")
#: Model label names (prefix removed, lower case) and the kind they stand for.
LABEL_ALIASES = {
    "pers": "PER", "per": "PER", "person": "PER",
    "loc": "LOC", "location": "LOC", "gpe": "LOC",
    "org": "ORG", "organisation": "ORG", "organization": "ORG",
}
#: Labels that are known and deliberately ignored.
IGNORED_LABELS = frozenset({"o", "misc", "prod", "product", "time", "date", "event", "work", "work_of_art"})


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str
    score: float | None  # model confidence; None for deterministic sources such as a glossary
    source: str


class Recognizer(Protocol):
    def find(self, text: str) -> list[Entity]: ...

    def describe(self) -> dict[str, str | int]:
        """Parameters that identify the recognizer for provenance records."""
        ...


class IncompleteCoverage(RuntimeError):
    """The model windows do not reach every character of the input."""


def _rank(entity: Entity) -> tuple:
    score = 1.0 if entity.score is None else entity.score
    return (-score, -(entity.end - entity.start), entity.start, entity.kind)


def resolve_overlaps(items: list[Entity], text: str, threshold: float) -> list[Entity]:
    """Keep valid, non-overlapping spans: higher score first, then longer, then earlier.

    Entities without a score (deterministic sources) are not subject to the threshold.
    """
    valid = [
        item for item in items
        if item.kind in KINDS
        and 0 <= item.start < item.end <= len(text)
        and (item.score is None or item.score >= threshold)
    ]
    chosen: list[Entity] = []
    for candidate in sorted(valid, key=_rank):
        if not any(candidate.start < other.end and other.start < candidate.end for other in chosen):
            chosen.append(candidate)
    return sorted(chosen, key=lambda e: (e.start, e.end))


def check_coverage(text: str, windows: list[tuple[int, int]], content: tuple[int, int] | None = None) -> None:
    """Raise if overlapping model windows leave a gap in the content of ``text``.

    ``windows`` are the character spans of the tokens each model window sees;
    ``content`` is the span the tokenizer reads at all (default: first to last
    non-space character).
    """
    if content is None:
        characters = [index for index, char in enumerate(text) if not char.isspace()]
        if not characters:
            return
        content = (characters[0], characters[-1] + 1)
    first, last = content
    if not windows:
        raise IncompleteCoverage("the tokenizer produced no window")
    reached = None
    for start, end in sorted(windows):
        if reached is None:
            if start > first:
                raise IncompleteCoverage(f"characters 0–{start} are outside every window")
        elif start > reached:
            raise IncompleteCoverage(f"characters {reached}–{start} are outside every window")
        reached = end if reached is None else max(reached, end)
    if reached < last:
        raise IncompleteCoverage(f"characters {reached}–{len(text)} are outside every window")


class GlossaryRecognizer:
    """Small deterministic demonstration backend; not a trained NER model."""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Glossary must be a JSON object")
        self.name = path.name
        self.digest = hashlib.sha256(raw).hexdigest()
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
            Entity(match.start(), match.end(), kind, None, "glossary")
            for pattern, kind in self.patterns
            for match in pattern.finditer(text)
        ]
        return resolve_overlaps(items, text, 0.0)

    def describe(self) -> dict[str, str | int]:
        return {"engine": "glossary", "glossary": self.name, "glossarySha256": self.digest}


def label_mapping(labels: list[str]) -> dict[str, str]:
    """Map a model's labels to PER/LOC/ORG; raise if none matches, warn about unknown ones."""
    names = {re.sub(r"^[BIESLU]-", "", label).lower() for label in labels}
    mapping = {name: LABEL_ALIASES[name] for name in names if name in LABEL_ALIASES}
    if not mapping:
        raise ValueError(f"the model has no person, place or organisation labels: {sorted(names)}")
    unknown = sorted(names - set(mapping) - IGNORED_LABELS)
    missing = sorted(set(KINDS) - set(mapping.values()))
    if unknown or missing:
        warnings.warn(f"model labels ignored: {unknown}; kinds without a label: {missing}", stacklevel=2)
    return mapping


def drop_window_fragments(entities: list[Entity], windows: list[tuple[int, int]]) -> list[Entity]:
    """Remove spans cut off at an inner window edge when another window saw the name whole."""
    if len(windows) < 2:
        return entities
    inner_starts = {start for start, _ in windows[1:]}
    inner_ends = {end for _, end in windows[:-1]}
    kept = []
    for entity in entities:
        at_edge = entity.start in inner_starts or entity.end in inner_ends
        rival = any(
            other is not entity and other.kind == entity.kind and other.start < entity.end and entity.start < other.end
            and (other.end - other.start) > (entity.end - entity.start)
            for other in entities
        )
        if not (at_edge and rival):
            kept.append(entity)
    return kept


class HuggingFaceRecognizer:
    """Impresso's historical NER model via standard Transformers, over overlapping windows."""

    MODEL = "impresso-project/ner-hipe2020-hist-base"
    REVISION = "afd1b509233560298ae39360ad3186253c5800d3"
    AGGREGATIONS = ("first", "max", "average", "simple")

    def __init__(
        self, model: str | None = None, local_files_only: bool = False, stride: int = 128, aggregation: str = "first",
        revision: str | None = None,
    ):
        if aggregation not in self.AGGREGATIONS:
            raise ValueError(f"aggregation must be one of {self.AGGREGATIONS}")
        self.aggregation = aggregation
        try:
            from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
        except ImportError as exc:
            raise RuntimeError("Install the NER extra: pip install -e '.[ner]'") from exc
        self.model_id = model or self.MODEL
        self.revision = revision or (self.REVISION if model is None else None)
        options = {"local_files_only": local_files_only, "trust_remote_code": False}
        if self.revision:
            options["revision"] = self.revision
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, **options)
        if not tokenizer.is_fast:
            raise RuntimeError("Overlapping windows need a fast tokenizer with offset mapping")
        limit = tokenizer.model_max_length
        if not 0 < stride < limit - tokenizer.num_special_tokens_to_add():
            raise ValueError(f"stride must be between 1 and the window size ({limit} tokens)")
        model_instance = AutoModelForTokenClassification.from_pretrained(
            self.model_id, use_safetensors=True, **options
        )
        self.labels = label_mapping(list(model_instance.config.id2label.values()))
        # The files actually loaded: the pinned revision, or the commit a hub download resolved to.
        self.resolved_revision = self.revision or getattr(model_instance.config, "_commit_hash", None)
        if not self.revision:
            warnings.warn(f"model revision not pinned; recorded {self.resolved_revision or 'nothing'}", stacklevel=2)
        self.tokenizer = tokenizer
        self.stride = stride
        self.pipeline = pipeline(
            "token-classification", model=model_instance, tokenizer=tokenizer,
            aggregation_strategy=aggregation, stride=stride, device=-1,
        )
        # Transformers would merge window results by span length before any score threshold;
        # keep every window's candidates and decide in drop_window_fragments/resolve_overlaps.
        self.pipeline.aggregate_overlapping_entities = lambda entities: entities

    def windows(self, text: str) -> list[tuple[int, int]]:
        """Character span of every model window, tokenized exactly as the pipeline does."""
        encoded = self.tokenizer(
            text, truncation=True, stride=self.stride, return_overflowing_tokens=True,
            return_offsets_mapping=True, return_special_tokens_mask=True,
        )
        spans = []
        for offsets, special in zip(encoded["offset_mapping"], encoded["special_tokens_mask"], strict=True):
            real = [offset for offset, flag in zip(offsets, special, strict=True) if not flag and offset[1] > offset[0]]
            if real:
                spans.append((real[0][0], real[-1][1]))
        return spans

    def content(self, text: str) -> tuple[int, int] | None:
        """Span of ``text`` the tokenizer reads at all (normalization drops some characters)."""
        offsets = self.tokenizer(
            text, add_special_tokens=False, truncation=False, return_offsets_mapping=True, verbose=False,
        )["offset_mapping"]
        real = [offset for offset in offsets if offset[1] > offset[0]]
        return (real[0][0], real[-1][1]) if real else None

    def find(self, text: str) -> list[Entity]:
        content = self.content(text) if text.strip() else None
        if content is None:
            return []
        windows = self.windows(text)
        check_coverage(text, windows, content)
        found: dict[tuple[int, int, str], Entity] = {}
        for item in self.pipeline(text):
            kind = self.labels.get(re.sub(r"^[BIESLU]-", "", str(item["entity_group"])).lower())
            if kind is None or item.get("start") is None:
                continue
            entity = Entity(int(item["start"]), int(item["end"]), kind, round(float(item["score"]), 4), self.model_id)
            key = (entity.start, entity.end, entity.kind)
            if key not in found or entity.score > found[key].score:
                found[key] = entity
        entities = drop_window_fragments(list(found.values()), windows)
        return sorted(entities, key=lambda e: (e.start, e.end, e.kind))

    def describe(self) -> dict[str, str | int]:
        description: dict[str, str | int] = {
            "engine": "hf", "model": self.model_id, "stride": self.stride, "aggregation": self.aggregation,
        }
        if self.resolved_revision:
            description["modelRevision"] = self.resolved_revision
        return description
