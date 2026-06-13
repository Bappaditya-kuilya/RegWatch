from __future__ import annotations

from core.llm import get_groq_client
from store import get_vector_store
from store.metadata import get_metadata_store

ROUTER_PROMPT = """Classify this user query into exactly one category.
Query: "{query}"

Categories:
- "current_state"
- "change_history"
- "impact"
- "action"

Respond with ONLY the category name, nothing else."""


class QueryAgent:
    def __init__(self):
        self.llm = get_groq_client()
        self.vs = get_vector_store()
        self.meta = get_metadata_store()

    def answer(self, query: str, profile: dict) -> dict:
        intent = self._classify_intent(query)
        if intent == "current_state":
            return self._answer_current(query)
        if intent == "change_history":
            return self._answer_change_history(query)
        if intent in ("impact", "action"):
            return self._answer_impact(query, profile)
        return self._answer_current(query)

    def _classify_intent(self, query: str) -> str:
        resp = self.llm.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": ROUTER_PROMPT.format(query=query)}],
            temperature=0,
            max_tokens=20,
        )
        return resp.choices[0].message.content.strip().lower()

    def _answer_current(self, query: str) -> dict:
        chunks = self.vs.query_active(query, n_results=4)
        context = "\n\n---\n\n".join(c["text"] for c in chunks)
        citations = [c["metadata"].get("doc_id", "") for c in chunks]
        resp = self.llm.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": f"""Answer this question based ONLY on the provided regulatory context.
If the answer is not in the context, say so explicitly.

CONTEXT:
{context}

QUESTION: {query}

Provide a clear, direct answer. End with: "Source: [citation]" """,
                }
            ],
            temperature=0.2,
            max_tokens=600,
        )
        return {
            "answer": resp.choices[0].message.content,
            "citations": citations,
            "query_type": "current_state",
            "chunks_used": len(chunks),
        }

    def _answer_change_history(self, query: str) -> dict:
        recent_changes = self.meta.recent_changes(days=90)
        keywords = query.lower().split()
        relevant = [c for c in recent_changes if any(kw in str(c).lower() for kw in keywords)][:5]
        if not relevant:
            return {
                "answer": "No changes detected in the last 90 days for your query.",
                "citations": [],
                "query_type": "change_history",
            }
        summary = "\n".join(
            f"- [{c.get('change_type', 'change').upper()}] {c.get('new_text_summary', '')}" for c in relevant
        )
        return {
            "answer": f"Recent regulatory changes relevant to your query:\n\n{summary}",
            "citations": [c.get("doc_id", "") for c in relevant],
            "query_type": "change_history",
        }

    def _answer_impact(self, query: str, profile: dict) -> dict:
        chunks = self.vs.query_active(query, n_results=3)
        context = "\n\n".join(c["text"] for c in chunks)
        resp = self.llm.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": f"""
You are advising a compliance officer at: {profile.get('company_name', 'an MSME')}.
Business type: {profile.get('business_type')}. Products: {profile.get('product_categories')}.

Based on this regulatory context, answer the question:

CONTEXT:
{context}

QUESTION: {query}

Be specific about what actions are required and by when.
""",
                }
            ],
            temperature=0.2,
            max_tokens=700,
        )
        return {
            "answer": resp.choices[0].message.content,
            "citations": [c["metadata"].get("doc_id", "") for c in chunks],
            "query_type": "impact",
        }
