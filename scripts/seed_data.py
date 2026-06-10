from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph.pipeline import ingest_document
from ingestion.base_scraper import RawDocument


@dataclass(frozen=True)
class SeedEntry:
    source: str
    doc_id: str
    title: str
    url: str
    published_date: str


SEED_ENTRIES = [
    SeedEntry(
        source="gst",
        doc_id="GST_CIRCULAR_173_05_2022",
        title="Circular No. 173/05/2022-GST",
        url="https://cbic-gst.gov.in/pdf/Circular-173-05-2022-GST.pdf",
        published_date="2022-07-06",
    ),
    SeedEntry(
        source="fssai",
        doc_id="FSSAI_LABELLING_2026",
        title="Food Safety and Standards (Labelling and Display) First Amendment Regulations, 2026",
        url="https://fssai.gov.in/upload/notifications/2026/04/69cca2b3f3ce9Notification%20dt%2024.03.2026_NRC.pdf",
        published_date="2026-03-24",
    ),
    SeedEntry(
        source="fssai",
        doc_id="FSSAI_VEGAN_2026",
        title="Food Safety and Standards (Vegan Foods) Amendment Regulations, 2026",
        url="https://fssai.gov.in/upload/notifications/2026/06/6a1fd4f01f0e0vegan_final.pdf",
        published_date="2026-05-21",
    ),
    SeedEntry(
        source="mca",
        doc_id="MCA_GENERAL_CIRCULAR_02_2024",
        title="MCA General Circular No. 02/2024",
        url="https://www.mca.gov.in/content/dam/mca/pdf/document-82-new-20240219.pdf",
        published_date="2024-02-19",
    ),
]


def build_raw_document(
    *,
    source: str,
    doc_id: str,
    title: str,
    url: str,
    published_date: datetime,
    raw_bytes: bytes,
) -> RawDocument:
    import hashlib

    return RawDocument(
        source=source,
        doc_id=doc_id,
        title=title,
        url=url,
        published_date=published_date,
        raw_bytes=raw_bytes,
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        metadata={"source_url": url},
    )


def ingest_remote_seed(entry: SeedEntry, client: httpx.Client) -> tuple[str, bool]:
    response = client.get(entry.url)
    response.raise_for_status()
    doc = build_raw_document(
        source=entry.source,
        doc_id=entry.doc_id,
        title=entry.title,
        url=entry.url,
        published_date=datetime.fromisoformat(entry.published_date),
        raw_bytes=response.content,
    )
    return ingest_document(doc)


def ingest_local_version(
    *,
    source: str,
    doc_id: str,
    title: str,
    file_path: Path,
    published_date: str,
) -> tuple[str, bool]:
    doc = build_raw_document(
        source=source,
        doc_id=doc_id,
        title=title,
        url=file_path.resolve().as_uri(),
        published_date=datetime.fromisoformat(published_date),
        raw_bytes=file_path.read_bytes(),
    )
    return ingest_document(doc)


def run_remote_seeds() -> None:
    with httpx.Client(
        headers={"User-Agent": "RegWatch/1.0 (research project)"},
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        for entry in SEED_ENTRIES:
            try:
                doc_id, diff_triggered = ingest_remote_seed(entry, client)
                print(
                    json.dumps(
                        {
                            "mode": "remote",
                            "doc_id": doc_id or entry.doc_id,
                            "source": entry.source,
                            "url": entry.url,
                            "diff_triggered": diff_triggered,
                            "status": "ok",
                        }
                    )
                )
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "mode": "remote",
                            "doc_id": entry.doc_id,
                            "source": entry.source,
                            "url": entry.url,
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                )


def run_local_versions(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest:
        try:
            doc_id, diff_triggered = ingest_local_version(
                source=item["source"],
                doc_id=item["doc_id"],
                title=item["title"],
                file_path=Path(item["file"]),
                published_date=item["published_date"],
            )
            print(
                json.dumps(
                    {
                        "mode": "local",
                        "doc_id": doc_id or item["doc_id"],
                        "file": item["file"],
                        "diff_triggered": diff_triggered,
                        "status": "ok",
                    }
                )
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "mode": "local",
                        "doc_id": item.get("doc_id", ""),
                        "file": item.get("file", ""),
                        "status": "error",
                        "error": str(exc),
                    }
                )
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed RegWatch with remote and local documents.")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to a JSON manifest for controlled local version ingestion.",
    )
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="Skip the default remote seed URLs.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clear runtime data before seeding.",
    )
    return parser.parse_args()


def clean_runtime_data() -> None:
    targets = [
        Path("data/chromadb"),
        Path("data/registry.db"),
        Path("data/version_graph.json"),
        Path("data/checkpoints.db"),
    ]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def main() -> None:
    args = parse_args()
    if args.clean:
        clean_runtime_data()
    if not args.skip_remote:
        run_remote_seeds()
    if args.manifest:
        run_local_versions(args.manifest)


if __name__ == "__main__":
    main()
