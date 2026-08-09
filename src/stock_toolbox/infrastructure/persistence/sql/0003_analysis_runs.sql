CREATE TABLE analysis_runs (
    run_id TEXT PRIMARY KEY REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    analysis_type TEXT NOT NULL CHECK(analysis_type GLOB '[a-z]*'),
    analysis_version TEXT NOT NULL,
    operation_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('READY','PARTIAL')),
    provider_id TEXT NOT NULL,
    watchlist_snapshot_json TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT NOT NULL,
    result_schema_version INTEGER NOT NULL CHECK(result_schema_version >= 1)
);
CREATE INDEX idx_analysis_runs_type_completed
ON analysis_runs(analysis_type,completed_at_utc DESC,run_id);

INSERT INTO analysis_runs(
    run_id,
    analysis_type,
    analysis_version,
    operation_id,
    status,
    provider_id,
    watchlist_snapshot_json,
    started_at_utc,
    completed_at_utc,
    result_schema_version
)
SELECT
    run_id,
    'rs_strength',
    '1.0.0',
    operation_id,
    status,
    provider_id,
    json_object(
        'source_id',watchlist_source_id,
        'name',watchlist_name,
        'revision',watchlist_revision,
        'member_count',member_count
    ),
    started_at_utc,
    completed_at_utc,
    1
FROM run_snapshots;
