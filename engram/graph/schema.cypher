// Engram Knowledge Graph Schema — Memgraph DDL
// Run via: loader.ensure_schema() or manually with mgconsole

// ── Uniqueness Constraints ──────────────────────────────────────────
CREATE CONSTRAINT ON (f:File) ASSERT f.path IS UNIQUE;
CREATE CONSTRAINT ON (s:Session) ASSERT s.id IS UNIQUE;
CREATE CONSTRAINT ON (e:Error) ASSERT e.pattern IS UNIQUE;
CREATE CONSTRAINT ON (st:Strategy) ASSERT st.name IS UNIQUE;
CREATE CONSTRAINT ON (c:Concept) ASSERT c.name IS UNIQUE;
CREATE CONSTRAINT ON (fl:Flow) ASSERT fl.name IS UNIQUE;

// ── Indexes ─────────────────────────────────────────────────────────
CREATE INDEX ON :File(project);
CREATE INDEX ON :Session(project);
CREATE INDEX ON :Session(created_at);
