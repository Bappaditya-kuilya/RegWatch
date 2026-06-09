from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from ingestion.base_scraper import BaseScraper, RawDocument


class FSSAIScraper(BaseScraper):
    INDEX_URL = "https://fssai.gov.in/cms/orders-and-circulars.php"

    def fetch_index(self) -> list[dict]:
        resp = self.client.get(self.INDEX_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = []
        for link in soup.select("a[href$='.pdf']")[:25]:
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if not href:
                continue
            url = href if href.startswith("http") else f"https://fssai.gov.in{href}"
            entries.append(
                {
                    "doc_id": f"FSSAI_{abs(hash(url))}",
                    "title": title,
                    "url": url,
                    "published_date": datetime.now(),
                }
            )
        return entries

    def fetch_document(self, entry: dict) -> RawDocument:
        pdf_bytes = self.client.get(entry["url"]).content
        return RawDocument(
            source="fssai",
            doc_id=entry["doc_id"],
            title=entry["title"],
            url=entry["url"],
            published_date=entry["published_date"],
            raw_bytes=pdf_bytes,
            content_hash=self.compute_hash(pdf_bytes),
            metadata={"source_url": entry["url"]},
        )
