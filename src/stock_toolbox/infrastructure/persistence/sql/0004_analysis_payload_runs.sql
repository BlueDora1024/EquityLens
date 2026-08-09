CREATE TABLE analysis_payload_runs (
    run_id TEXT PRIMARY KEY,
    analysis_type TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY','PARTIAL')),
    provider_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    completed_at_utc TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
    note TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX idx_analysis_payload_runs_type_completed
ON analysis_payload_runs(analysis_type,pinned DESC,completed_at_utc DESC,run_id);

