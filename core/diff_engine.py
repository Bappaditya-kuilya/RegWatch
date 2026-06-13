from __future__ import annotations

import difflib
from typing import Optional

from groq import Groq

from core.llm import complete_structured
from core.models import ChangeSeverity, ChangeType, DiffResponse, SemanticChange
from core.version_graph import VersionGraph
from ingestion.processor import ProcessedChunk

DIFF_PROMPT = """You are a regulatory compliance expert analyzing Indian government documents.

Compare these two versions of a regulatory section and identify what semantically changed.

OLD VERSION (from {old_version}):
{old_text}

NEW VERSION (from {new_version}):
{new_text}

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "change_type": "<rate_change|deadline_change|new_requirement|removed_rule|procedural_change|penalty_change|definition_change>",
  "severity": "<critical|major|minor>",
  "old_text_summary": "<one sentence: what the old version required/stated>",
  "new_text_summary": "<one sentence: what the new version requires/states>",
  "affected_clauses": ["<section numbers>"],
  "confidence": <0.0-1.0>,
  "key_phrase_changed": "<the exact phrase or number that changed, max 50 chars>"
}}
"""


class SemanticDiffEngine:
    SIMILARITY_THRESHOLD = 0.92

    def __init__(self, llm_client: Groq, version_graph: VersionGraph | None = None):
        self.llm = llm_client
        self.vg = version_graph

    def compute_diff(
        self,
        old_chunks: list[ProcessedChunk],
        new_chunks: list[ProcessedChunk],
        doc_id: str,
    ) -> list[SemanticChange]:
        aligned = self._align_chunks(old_chunks, new_chunks)
        changes: list[SemanticChange] = []
        change_counter = 0

        for old_chunk, new_chunk in aligned["modified"]:
            if self._text_similarity(old_chunk.text, new_chunk.text) >= self.SIMILARITY_THRESHOLD:
                continue
            change = self._llm_diff(old_chunk, new_chunk, doc_id, change_counter)
            if change:
                changes.append(change)
                change_counter += 1

        for new_chunk in aligned["added"]:
            changes.append(
                SemanticChange(
                    change_id=f"{doc_id}_change_{change_counter:04d}",
                    doc_id=doc_id,
                    old_version="N/A",
                    new_version=new_chunk.version,
                    change_type=ChangeType.NEW_REQUIREMENT,
                    severity=ChangeSeverity.MAJOR,
                    old_text_summary="This section did not exist in the previous version.",
                    new_text_summary=new_chunk.text[:200] + "...",
                    affected_clauses=[new_chunk.section_title or ""],
                    confidence=0.9,
                    raw_diff_context=new_chunk.text[:500],
                )
            )
            change_counter += 1

        return changes

    def _align_chunks(
        self,
        old_chunks: list[ProcessedChunk],
        new_chunks: list[ProcessedChunk],
    ) -> dict[str, list]:
        old_by_section = {f"{c.section_title}:{i}": c for i, c in enumerate(old_chunks)}
        new_by_section = {f"{c.section_title}:{i}": c for i, c in enumerate(new_chunks)}

        modified = []
        added = []
        removed = []

        old_items = list(old_by_section.values())
        matched_old: set[int] = set()

        for new_chunk in new_by_section.values():
            best_idx = None
            best_score = -1.0
            for idx, old_chunk in enumerate(old_items):
                if idx in matched_old:
                    continue
                same_title = (old_chunk.section_title or "") == (new_chunk.section_title or "")
                score = self._text_similarity(old_chunk.text[:300], new_chunk.text[:300])
                if same_title:
                    score += 0.2
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx is not None and best_score >= 0.35:
                matched_old.add(best_idx)
                modified.append((old_items[best_idx], new_chunk))
            else:
                added.append(new_chunk)

        for idx, old_chunk in enumerate(old_items):
            if idx not in matched_old:
                removed.append(old_chunk)

        return {"modified": modified, "added": added, "removed": removed}

    def _text_similarity(self, a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    def _llm_diff(
        self,
        old_chunk: ProcessedChunk,
        new_chunk: ProcessedChunk,
        doc_id: str,
        idx: int,
    ) -> Optional[SemanticChange]:
        prompt = DIFF_PROMPT.format(
            old_version=old_chunk.version,
            new_version=new_chunk.version,
            old_text=old_chunk.text[:1500],
            new_text=new_chunk.text[:1500],
        )
        resp = complete_structured(self.llm, prompt, DiffResponse, max_tokens=512)
        if resp is None:
            return None
        return SemanticChange(
            change_id=f"{doc_id}_change_{idx:04d}",
            doc_id=doc_id,
            old_version=old_chunk.version,
            new_version=new_chunk.version,
            change_type=resp.change_type,
            severity=resp.severity,
            old_text_summary=resp.old_text_summary,
            new_text_summary=resp.new_text_summary,
            affected_clauses=resp.affected_clauses,
            confidence=resp.confidence,
            raw_diff_context=old_chunk.text[:300] + "\n\n-> CHANGED TO ->\n\n" + new_chunk.text[:300],
        )
