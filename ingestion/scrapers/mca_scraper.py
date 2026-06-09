from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup

from ingestion.base_scraper import BaseScraper, RawDocument


class MCAScraper(BaseScraper):
    BASE_URL = "https://www.mca.gov.in"
    INDEX_URL = (
        "https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/general-circulars.html"
    )

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
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            entries.append(
                {
                    "doc_id": f"MCA_{abs(hash(url))}",
                    "title": title,
                    "url": url,
                    "published_date": datetime.now(),
                }
            )
        return entries

    def fetch_document(self, entry: dict) -> RawDocument:
        pdf_bytes = self.client.get(entry["url"]).content
        return RawDocument(
            source="mca",
            doc_id=entry["doc_id"],
            title=entry["title"],
            url=entry["url"],
            published_date=entry["published_date"],
            raw_bytes=pdf_bytes,
            content_hash=self.compute_hash(pdf_bytes),
            metadata={"source_url": entry["url"]},
        )
