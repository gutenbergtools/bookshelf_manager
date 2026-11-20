-- Job queue for cross-host triggers (replaces SCP trigger files).
-- Lives in the Postgres catalog database, next to the rest of the data.

CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(200) NOT NULL UNIQUE,
    job_type        VARCHAR(40) NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    claimed_at      TIMESTAMPTZ,
    claimed_by      VARCHAR(80) NOT NULL DEFAULT '',
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON jobs (status, created_at);
