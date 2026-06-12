# RegWatch — Build Plan for "The Arch" (RAG & Agentic AI Hackathon, IIT KGP)

**Owner:** solo, full-time · **Deadline:** ~June 28 2026 · **Cost ceiling:** $0 · **Dev machine:** 8 GB RAM

---

## North star

RegWatch is a **Temporal / Version-Aware RAG framework** — it retrieves the *correct version* of a
regulatory document and detects what *semantically changed* between versions. The flagship vertical is
Indian regulatory compliance (GST / MCA / FSSAI) for MSMEs.

The Arch judges **"contextual fidelity under rigorous stress tests"** and **agentic AI**. Our entire
pitch is built on the fact that **naive RAG fails temporal/version-conflation stress tests by design,
and our architecture passes them.** We lead with fidelity-under-stress, not "compliance dashboard."

---

## Hard rules

1. **Strangler-fig, never big-bang.** Every phase ends with a working, deployable, demoable app.
2. **$0 cost.** Every component is on a genuinely free tier (table below). No credit card required.
3. **8 GB-friendly.** All heavy work (embed, vectors, DB, LLM) is a remote API call. Local dev runs only
   FastAPI + Streamlit dev servers (~500 MB total).
4. **Day-8 hard cutoff on multi-tenancy.** If multi-tenant isn't done by EOD Day 8, freeze it and ship
   single-tenant-clean. The P0 stress-test/agentic work (Days 9–13) is non-negotiable; it is what wins.

---

## Locked free stack

| Concern | Choice | Free tier | Notes |
|---|---|---|---|
| Embeddings | **Google Gemini `gemini-embedding-001`** | 1,500 req/day, no card | #1 multilingual MTEB (Hindi/Bengali) |
| Embeddings fallback | **Jina v4** | 1M tokens/month | auto-fallback if Gemini quota hit |
| LLM | **Groq** llama-3.3-70b | 14,400 req/day | diff / impact / action / query / verify |
| Vector DB | **Qdrant Cloud** | 1 GB RAM / 4 GB disk | **GLOBAL** collections (not per-tenant) |
| Metadata DB + Auth | **Supabase** | 500 MB + Supabase Auth | tenant rows; daily write avoids 7-day pause |
| Backend host | **Render** (free web service) | 750 instance-hrs/mo | + UptimeRobot keep-alive ping (no sleep) |
| Frontend host | **Streamlit Community Cloud** | free forever | calls FastAPI via httpx |

**Dropped from the v2.0 doc:** Cohere (trial = 1,000 calls/*month*, bans production), Railway (no longer
free always-on), per-tenant Qdrant collections, Celery, Next.js.

---

## Architecture

```
Streamlit Cloud (UI) ──httpx──► FastAPI on Render (+ APScheduler, 1 worker)
 UptimeRobot ping ────────────►        │
                                        ├─ Supabase Postgres  (tenants, profiles, docs, versions,
                                        │                       changes, impacts, tasks, runs, audit)
                                        ├─ Qdrant Cloud        (GLOBAL active + history collections)
                                        ├─ Gemini / Jina       (embeddings)
                                        └─ Groq                (all LLM agents)
```

### Three deliberate divergences from the v2.0 architecture doc (these are upgrades)

1. **Global vector collections**, not per-tenant. Regulatory text is identical for every tenant and there
   is no document-upload feature, so per-tenant collections would re-embed the same circular N times for
   zero benefit. The *tenant lens* is the impact/task **rows in Postgres**, not the vectors.
2. **Normalize the version graph into Postgres rows** (documents / versions / changes), not one JSONB blob
   rewritten per mutation (that blob has a lost-update bug under concurrent runs + O(n) write
   amplification). NetworkX becomes a read-time projection built from rows when graph ops are needed.
3. **Tenant isolation via an app-layer tenant-scoped repository** (the real, unit-testable enforcement),
   with Supabase RLS + JWT-scoped clients as *tested* defense-in-depth. The v2.0 doc's RLS is decorative —
   it connects with the service-role key, which bypasses RLS entirely.

---

## P0 — the winning artifacts (this is what beats the field)

### A. Contextual-Fidelity Stress-Test Suite
A versioned eval set of adversarial questions engineered to break naive RAG, with a scoreboard comparing
**RegWatch (version-aware path)** vs **a naive active-only RAG baseline**. Categories:
- **Temporal confusion** — "what was the GST rate in 2023 vs now?"
- **Version conflation** — answer must not mix clauses from superseded + active versions.
- **Superseded-clause trap** — question whose answer changed; naive RAG returns the stale clause.
- **Multi-hop across versions** — requires reasoning over the change history, not a single chunk.
Output: a results table (accuracy / fidelity per category) + a few qualitative side-by-sides for the deck.

### B. Agentic query + verifier
- **Router agent** — classifies intent (point-in-time lookup vs change-history vs impact) and chooses the
  retrieval strategy + which version(s) to pull.
- **Verifier agent** — confirms the drafted answer is grounded in the *cited* version and refuses /
  re-retrieves otherwise. This is "agentic" + "fidelity" in one move (The Arch's two keywords).

### C. Reliability hardening (do during migration, not after)
- Groq `response_format=json_object` + Pydantic validation + bounded retry on every LLM node.
  Replaces the current bare `except: return None` / `except: continue` that silently drops changes.
- Idempotent persistence keyed by `change_id` / `task_id` (upserts) → kills the LangGraph
  `operator.add` accumulation/dedup bug; DB rows become the source of truth.

---

## 18-day schedule

| Days | Phase | Exit criteria (demoable at each gate) |
|---|---|---|
| **1** | De-risk deploy | Empty FastAPI `/health` live on Render + keep-alive; Supabase schema applied; all 5 cloud accounts created |
| **2–5** | State migration (single tenant) behind interfaces | Pipeline runs end-to-end against Gemini + Qdrant(global) + Supabase; structured-output hardening landed; UI still works |
| **6–8** | Multi-tenant (lean) | Supabase Auth + `tenant_id` everywhere; 2 seeded tenants; pytest proves cross-tenant denial. **← hard cutoff** |
| **9–13** | **P0 winning work** | Stress-test suite + scoreboard vs naive RAG; router + verifier agents; 10–15 real GST/MCA/FSSAI docs w/ v1↔v2 pairs + deterministic fixtures |
| **14–16** | Demo + deck | Deck (problem → framework → stress-test results → business); demo script; polish |
| **17–18** | Rehearse ×2 + buffer | Two clean run-throughs; fixes only |

---

## Risk register

1. **Migration overruns and eats P0 time** → ship a clean SaaS that demos *worse* than today. Mitigation:
   Day-8 hard cutoff; the stress-test suite + smooth demo are protected.
2. **Gemini free tier tightened mid-project** → Jina v4 auto-fallback already wired.
3. **Render cold start during live demo** → UptimeRobot keep-alive + warm the service right before demo.
4. **Groq rate limit during benchmark run** → batch + cache eval results; benchmark is a one-shot artifact.
5. **Supabase 7-day inactivity pause** → daily APScheduler write keeps it alive.

## What NOT to build before June 28
Celery · Next.js · per-tenant vector collections · document upload · custom auth · WebSockets ·
eGazette scraper · >3 scraping sources · embedding perf optimization.

---
*Decision log lives in agent memory: `hackathon-scope-decision`, `regwatch-codebase-truths`.*
