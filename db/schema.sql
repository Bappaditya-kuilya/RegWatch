-- ============================================================================
-- RegWatch — Supabase / PostgreSQL schema (v2, production)
--
-- Divergences from the v2.0 architecture doc (see docs/BUILD_PLAN.md):
--   1. The version graph is NORMALIZED into rows (regulatory_documents,
--      document_versions, version_edges, document_chunks, detected_changes) instead
--      of one JSONB blob rewritten per mutation. This removes the lost-update bug
--      under concurrent pipeline runs and lets us reconstruct every VersionGraph
--      query in SQL. NetworkX, if needed, is a read-time projection of these rows.
--   2. Regulatory data (documents/versions/chunks/changes) is GLOBAL — it is public
--      and identical for every tenant. Only the *lens* (impacts, tasks, profile,
--      runs) is per-tenant. This matches the GLOBAL Qdrant collections.
--   3. RLS is real, not decorative. Policies key off current_setting('app.tenant_id').
--      The FastAPI repository sets that per transaction on an RLS-bound connection;
--      it does NOT lean on the service-role key to silently bypass isolation. The
--      app-layer repository ALSO filters by tenant_id (defense in depth + testable).
--
-- Apply: Supabase dashboard -> SQL Editor -> paste -> Run. Idempotent.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- GLOBAL regulatory corpus (shared public data — NOT tenant scoped)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS regulatory_documents (
    doc_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,                 -- 'gst' | 'mca' | 'fssai' | ...
    title               TEXT NOT NULL,
    url                 TEXT,
    current_version_id  TEXT,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_versions (
    version_id          TEXT PRIMARY KEY,              -- "{doc_id}_v{version_date}"
    doc_id              TEXT NOT NULL REFERENCES regulatory_documents(doc_id) ON DELETE CASCADE,
    version_date        TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active', -- 'active' | 'superseded'
    chunks_count        INTEGER DEFAULT 0,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doc_id, content_hash)
);

-- SUPERSEDES edges: new_version_id supersedes old_version_id (one row per supersession).
CREATE TABLE IF NOT EXISTS version_edges (
    new_version_id      TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    old_version_id      TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    PRIMARY KEY (new_version_id, old_version_id)
);

-- Chunk registry (chunk TEXT + vector live in Qdrant; this is the structural index
-- that replaces the graph's CONTAINS edges, used by the diff engine + change trail).
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id            TEXT PRIMARY KEY,
    version_id          TEXT NOT NULL REFERENCES document_versions(version_id) ON DELETE CASCADE,
    doc_id              TEXT NOT NULL REFERENCES regulatory_documents(doc_id) ON DELETE CASCADE,
    section_title       TEXT,
    char_start          INTEGER DEFAULT 0,
    char_end            INTEGER DEFAULT 0
);

-- Detected semantic changes (global; mirrors core.models.SemanticChange).
CREATE TABLE IF NOT EXISTS detected_changes (
    change_id           TEXT PRIMARY KEY,
    doc_id              TEXT NOT NULL REFERENCES regulatory_documents(doc_id) ON DELETE CASCADE,
    old_version         TEXT NOT NULL,
    new_version         TEXT NOT NULL,
    change_type         TEXT NOT NULL,
    severity            TEXT NOT NULL,
    old_text_summary    TEXT,
    new_text_summary    TEXT,
    affected_clauses    JSONB NOT NULL DEFAULT '[]',
    confidence          DOUBLE PRECISION,
    raw_diff_context    TEXT,
    new_chunk_id        TEXT,
    old_chunk_id        TEXT,
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- TENANTS + per-tenant data
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tenants (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT NOT NULL,
    slug                TEXT UNIQUE NOT NULL,
    subscription_tier   TEXT NOT NULL DEFAULT 'free',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One CompanyProfile (core.models.CompanyProfile) per tenant, stored as JSONB.
CREATE TABLE IF NOT EXISTS company_profiles (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    profile             JSONB NOT NULL DEFAULT '{}',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Which regulatory sources a tenant subscribes to (drives their pipeline scope).
CREATE TABLE IF NOT EXISTS tenant_sources (
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source              TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source)
);

CREATE TABLE IF NOT EXISTS impact_assessments (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    change_id           TEXT NOT NULL REFERENCES detected_changes(change_id) ON DELETE CASCADE,
    is_applicable       BOOLEAN NOT NULL,
    applicability_reason TEXT,
    affected_operations JSONB NOT NULL DEFAULT '[]',
    affected_product_categories JSONB NOT NULL DEFAULT '[]',
    risk_level          TEXT,
    requires_action     BOOLEAN NOT NULL DEFAULT FALSE,
    assessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, change_id)
);

CREATE TABLE IF NOT EXISTS compliance_tasks (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    task_id             TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    source_change_id    TEXT,
    deadline            TIMESTAMPTZ,
    deadline_source     TEXT,
    penalty_if_missed   TEXT,
    priority            INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    citation            TEXT,
    action_url          TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending|acknowledged|completed
    acknowledged_at     TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, task_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trigger             TEXT NOT NULL,                  -- scheduled|manual|onboarding
    mode                TEXT NOT NULL DEFAULT 'seeded', -- seeded|live
    status              TEXT NOT NULL DEFAULT 'running',-- running|completed|failed
    changes_detected    INTEGER DEFAULT 0,
    tasks_generated     INTEGER DEFAULT 0,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    error_message       TEXT,
    run_metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID REFERENCES tenants(id) ON DELETE CASCADE,
    actor               TEXT,
    action              TEXT NOT NULL,
    resource_type       TEXT,
    resource_id         TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_versions_doc        ON document_versions(doc_id, status);
CREATE INDEX IF NOT EXISTS idx_chunks_version      ON document_chunks(version_id);
CREATE INDEX IF NOT EXISTS idx_changes_doc         ON detected_changes(doc_id, new_version);
CREATE INDEX IF NOT EXISTS idx_changes_detected_at ON detected_changes(detected_at);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant_status ON compliance_tasks(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority      ON compliance_tasks(tenant_id, priority);
CREATE INDEX IF NOT EXISTS idx_impacts_tenant      ON impact_assessments(tenant_id, change_id);
CREATE INDEX IF NOT EXISTS idx_runs_tenant_status  ON pipeline_runs(tenant_id, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Row Level Security (real isolation; see header note 3)
--
-- The FastAPI repository runs, per request/transaction:
--     SET LOCAL app.tenant_id = '<uuid-from-jwt>';
-- on an RLS-bound connection (a role for which RLS is enforced — NOT the service
-- role, which bypasses RLS). These policies then make cross-tenant rows invisible
-- even if application code forgets a filter. A pytest asserts cross-tenant denial.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE company_profiles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_sources     ENABLE ROW LEVEL SECURITY;
ALTER TABLE impact_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_tasks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log          ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'company_profiles','tenant_sources','impact_assessments',
        'compliance_tasks','pipeline_runs','audit_log'
    ] LOOP
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I;', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid);',
            t
        );
    END LOOP;
END $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Application role for REAL RLS enforcement.
--
-- Supabase's 'postgres' connecting role has BYPASSRLS (verified empirically), so RLS
-- policies do NOTHING on that connection. The FastAPI repository therefore drops to this
-- owner-less, non-BYPASSRLS role for every tenant transaction:
--     SET LOCAL ROLE regwatch_app;  SET LOCAL app.tenant_id = '<uuid>';
-- Only then do the tenant_isolation policies actually constrain queries.
-- Proven by tests/test_tenant_isolation.py.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'regwatch_app') THEN
        CREATE ROLE regwatch_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO regwatch_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO regwatch_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO regwatch_app;

-- Let the connecting admin role SET ROLE to regwatch_app.
DO $$ BEGIN
    EXECUTE format('GRANT regwatch_app TO %I', current_user);
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
