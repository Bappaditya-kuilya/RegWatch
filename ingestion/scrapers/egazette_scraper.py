from __future__ import annotations

from ingestion.base_scraper import BaseScraper, RawDocument


class EGazetteScraper(BaseScraper):
    def fetch_index(self) -> list[dict]:
        return []

    def fetch_document(self, entry: dict) -> RawDocument:
        raise NotImplementedError
