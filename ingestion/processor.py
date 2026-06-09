from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

import pdfplumber


@dataclass
class ProcessedChunk:
    chunk_id: str
    doc_id: str
    version: str
    text: str
    section_title: Optional[str]
    page_number: int
    char_start: int
    char_end: int


class DocumentProcessor:
    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 150

    def process(self, doc: "RawDocument", version: str) -> list[ProcessedChunk]:
        full_text = self._extract_text(doc.raw_bytes)
        sections = self._split_by_section(full_text)
        chunks: list[ProcessedChunk] = []
        chunk_idx = 0
        for section_title, section_text in sections:
            for chunk_text, char_start, char_end in self._chunk(section_text):
                chunks.append(
                    ProcessedChunk(
                        chunk_id=f"{doc.doc_id}_v{version}_{chunk_idx:04d}",
                        doc_id=doc.doc_id,
                        version=version,
                        text=chunk_text,
                        section_title=section_title,
                        page_number=0,
                        char_start=char_start,
                        char_end=char_end,
                    )
                )
                chunk_idx += 1
        return chunks

    def _extract_text(self, pdf_bytes: bytes) -> str:
        text_parts = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception:
            return pdf_bytes.decode("utf-8", errors="ignore")

    def _split_by_section(self, text: str) -> list[tuple[str, str]]:
        pattern = r"(?m)^(\d+[\.\)]\s+[A-Z][^\n]{5,80})\n"
        parts = re.split(pattern, text)
        if len(parts) == 1:
            return [("Document", text)]
        sections = []
        for i in range(1, len(parts), 2):
            title = parts[i].strip()
            content = parts[i + 1] if i + 1 < len(parts) else ""
            sections.append((title, content))
        return sections

    def _chunk(self, text: str) -> list[tuple[str, int, int]]:
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.CHUNK_SIZE, len(text))
            if end < len(text):
                boundary = text.rfind(". ", start, end)
                if boundary != -1 and boundary > start + self.CHUNK_SIZE // 2:
                    end = boundary + 1
            chunks.append((text[start:end].strip(), start, end))
            next_start = end - self.CHUNK_OVERLAP
            if next_start <= start:
                break
            start = next_start
        return [(t, s, e) for t, s, e in chunks if len(t) > 100]
