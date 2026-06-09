from core.diff_engine import SemanticDiffEngine
from core.version_graph import VersionGraph
from ingestion.processor import ProcessedChunk


class DummyLLM:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                class Msg:
                    content = (
                        '{"change_type":"deadline_change","severity":"major",'
                        '"old_text_summary":"Old deadline was 10th.","new_text_summary":"New deadline is 15th.",'
                        '"affected_clauses":["1. Filing"],"confidence":0.95,"key_phrase_changed":"10th to 15th"}'
                    )

                class Choice:
                    message = Msg()

                class Response:
                    choices = [Choice()]

                return Response()


def test_compute_diff_returns_semantic_changes():
    engine = SemanticDiffEngine(DummyLLM(), VersionGraph())
    old_chunk = ProcessedChunk(
        "a",
        "DOC1",
        "v1",
        "Manufacturers must file Form GSTR-FOOD by the 10th day of the following month through the state portal. A late filing penalty of Rs. 5,000 applies and the declaration must include batch-wise snack inventory details.",
        "1. Filing",
        0,
        0,
        10,
    )
    new_chunk = ProcessedChunk(
        "b",
        "DOC1",
        "v2",
        "Manufacturers must file Form GSTR-FOOD by the 15th day of the following month through the central portal. A late filing penalty of Rs. 25,000 applies and the declaration must include HSN-wise branded namkeen turnover details.",
        "1. Filing",
        0,
        0,
        10,
    )
    changes = engine.compute_diff([old_chunk], [new_chunk], "DOC1")
    assert len(changes) == 1
    assert changes[0].doc_id == "DOC1"
