from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx

from config.settings import DATA_DIR
from core.models import SemanticChange


class VersionGraph:
    GRAPH_PATH = DATA_DIR / "version_graph.json"

    def __init__(self) -> None:
        self.G = nx.DiGraph()
        self._load()

    def add_document(self, doc_id: str, source: str, title: str) -> None:
        if not self.G.has_node(doc_id):
            self.G.add_node(doc_id, node_type="doc", source=source, title=title)

    def add_version(
        self,
        doc_id: str,
        version_id: str,
        version_date: str,
        content_hash: str,
        status: str = "active",
    ) -> None:
        self.G.add_node(
            version_id,
            node_type="version",
            doc_id=doc_id,
            version_date=version_date,
            content_hash=content_hash,
            status=status,
        )
        self.G.add_edge(doc_id, version_id, edge_type="HAS_VERSION")

    def add_chunk(
        self,
        version_id: str,
        chunk_id: str,
        section_title: str | None,
        char_start: int,
        char_end: int,
    ) -> None:
        self.G.add_node(
            chunk_id,
            node_type="chunk",
            version_id=version_id,
            section_title=section_title,
            char_start=char_start,
            char_end=char_end,
        )
        self.G.add_edge(version_id, chunk_id, edge_type="CONTAINS")

    def supersede(self, new_version_id: str, old_version_id: str) -> None:
        self.G.add_edge(new_version_id, old_version_id, edge_type="SUPERSEDES")
        if self.G.has_node(old_version_id):
            self.G.nodes[old_version_id]["status"] = "superseded"

    def record_change(
        self,
        change: SemanticChange,
        new_chunk_id: str | None = None,
        old_chunk_id: str | None = None,
    ) -> None:
        change_node_id = f"change_{change.change_id}"
        self.G.add_node(
            change_node_id,
            node_type="change",
            created_at_ts=datetime.now(timezone.utc).timestamp(),
            **change.model_dump(mode="json"),
        )
        if new_chunk_id:
            self.G.add_edge(new_chunk_id, change_node_id, edge_type="CHANGED_FROM")
        if old_chunk_id:
            self.G.add_edge(change_node_id, old_chunk_id, edge_type="CHANGED_TO")

    def get_active_version(self, doc_id: str) -> str | None:
        for _, version_id, data in self.G.edges(doc_id, data=True):
            if data.get("edge_type") == "HAS_VERSION":
                node = self.G.nodes[version_id]
                if node.get("status") == "active":
                    return version_id
        return None

    def get_previous_version(self, version_id: str) -> str | None:
        for _, old_id, data in self.G.edges(version_id, data=True):
            if data.get("edge_type") == "SUPERSEDES":
                return old_id
        return None

    def get_chunks_for_version(self, version_id: str) -> list[str]:
        return [
            target
            for _, target, data in self.G.edges(version_id, data=True)
            if data.get("edge_type") == "CONTAINS"
        ]

    def get_recent_changes(self, days: int = 30) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        changes: list[dict] = []
        for node_id, attrs in self.G.nodes(data=True):
            if attrs.get("node_type") != "change":
                continue
            ts = attrs.get("created_at_ts", cutoff)
            if ts >= cutoff:
                changes.append({"change_id": node_id, **attrs})
        return changes

    def get_change_trail(self, doc_id: str) -> list[dict]:
        versions = sorted(
            [
                (v, self.G.nodes[v]["version_date"])
                for _, v, d in self.G.edges(doc_id, data=True)
                if d.get("edge_type") == "HAS_VERSION"
            ],
            key=lambda x: x[1],
        )
        trail = []
        for version_id, _ in versions:
            chunks = self.get_chunks_for_version(version_id)
            for chunk_id in chunks:
                for _, change_id, d in self.G.edges(chunk_id, data=True):
                    if d.get("edge_type") == "CHANGED_FROM":
                        trail.append(self.G.nodes[change_id])
        return trail

    def save(self) -> None:
        self.GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = nx.node_link_data(self.G)
        with self.GRAPH_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f)

    def _load(self) -> None:
        if self.GRAPH_PATH.exists():
            with self.GRAPH_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            self.G = nx.node_link_graph(data)
