from core.models import ChangeSeverity, ChangeType, SemanticChange
from core.version_graph import VersionGraph


def test_version_graph_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(VersionGraph, "GRAPH_PATH", tmp_path / "version_graph.json")
    vg = VersionGraph()
    vg.add_document("DOC1", "gst", "Test Document")
    vg.add_version("DOC1", "DOC1_v2026-01-01", "2026-01-01", "hash1")
    vg.add_chunk("DOC1_v2026-01-01", "chunk1", "1. Scope", 0, 100)
    vg.record_change(
        SemanticChange(
            change_id="c1",
            doc_id="DOC1",
            old_version="old",
            new_version="new",
            change_type=ChangeType.NEW_REQUIREMENT,
            severity=ChangeSeverity.MAJOR,
            old_text_summary="old",
            new_text_summary="new",
            affected_clauses=["1. Scope"],
            confidence=0.9,
            raw_diff_context="ctx",
        )
    )
    vg.save()

    vg2 = VersionGraph()
    assert vg2.get_active_version("DOC1") == "DOC1_v2026-01-01"
