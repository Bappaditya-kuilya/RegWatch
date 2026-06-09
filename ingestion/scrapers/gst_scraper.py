from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ingestion.base_scraper import BaseScraper, RawDocument


class GSTScraper(BaseScraper):
    BASE_URL = "https://cbic-gst.gov.in"
    INDEX_URL = f"{BASE_URL}/cbic-internet/listTradeNotices.html"

    def fetch_index(self) -> list[dict]:
        resp = self.client.get(self.INDEX_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = []
        for row in soup.select("table.table tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[1].find("a")
            if not link or not link.get("href"):
                continue
            entries.append(
                {
                    "doc_id": f"GST_{self._slugify(link.text)}",
                    "title": link.text.strip(),
                    "url": self.BASE_URL + link["href"],
                    "published_date": self._parse_date(cells[0].text.strip()),
                }
            )
        return entries

    def fetch_document(self, entry: dict) -> RawDocument:
        pdf_bytes = self.client.get(entry["url"]).content
        return RawDocument(
            source="gst",
            doc_id=entry["doc_id"],
            title=entry["title"],
            url=entry["url"],
            published_date=entry["published_date"],
            raw_bytes=pdf_bytes,
            content_hash=self.compute_hash(pdf_bytes),
            metadata={"source_url": entry["url"]},
        )

    def _slugify(self, text: str) -> str:
        return re.sub(r"[^A-Z0-9]", "_", text.upper())[:64]

    def _parse_date(self, text: str) -> datetime:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return datetime.now()
