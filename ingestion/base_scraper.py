from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import httpx

from store.doc_registry import DocumentRegistry


@dataclass
class RawDocument:
    source: str
    doc_id: str
    title: str
    url: str
    published_date: datetime
    raw_bytes: bytes
    content_hash: str
    metadata: dict


class BaseScraper(ABC):
    def __init__(self, registry_path: str = "data/registry.db"):
        self.client = httpx.Client(
            headers={"User-Agent": "RegWatch/1.0 (research project)"},
            timeout=30.0,
            follow_redirects=True,
        )
        self.registry = DocumentRegistry(registry_path)

    @abstractmethod
    def fetch_index(self) -> list[dict]:
        ...

    @abstractmethod
    def fetch_document(self, entry: dict) -> RawDocument:
        ...

    def compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def fetch_all_new(self) -> list[RawDocument]:
        index = self.fetch_index()
        new_docs = []
        for entry in index:
            if not self.registry.is_registered(entry["doc_id"]):
                new_docs.append(self.fetch_document(entry))
        return new_docs
