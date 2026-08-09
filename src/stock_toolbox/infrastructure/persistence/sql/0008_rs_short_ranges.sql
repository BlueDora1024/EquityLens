PRAGMA legacy_alter_table = ON;

ALTER TABLE run_ranges RENAME TO run_ranges_before_short_presets;

CREATE TABLE run_ranges (
    run_range_id TEXT PRIMARY KEY CHECK(length(run_range_id) = 36 AND substr(run_range_id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    range_key TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('PRESET_1W','PRESET_2W','PRESET_1M','PRESET_3M','PRESET_6M','PRESET_1Y','CUSTOM')),
    requested_start_date TEXT NOT NULL,
    requested_end_date TEXT NOT NULL,
    actual_start_date TEXT NOT NULL,
    actual_end_date TEXT NOT NULL,
    benchmark_start_close_text TEXT NOT NULL,
    benchmark_end_close_text TEXT NOT NULL,
    base_weight_text TEXT NOT NULL,
    normalized_weight_text TEXT NOT NULL,
    UNIQUE(run_id,ordinal),
    UNIQUE(run_id,range_key),
    UNIQUE(run_range_id,run_id)
);

INSERT INTO run_ranges(
    run_range_id,run_id,ordinal,range_key,label,kind,
    requested_start_date,requested_end_date,actual_start_date,actual_end_date,
    benchmark_start_close_text,benchmark_end_close_text,
    base_weight_text,normalized_weight_text
)
SELECT
    run_range_id,run_id,ordinal,range_key,label,kind,
    requested_start_date,requested_end_date,actual_start_date,actual_end_date,
    benchmark_start_close_text,benchmark_end_close_text,
    base_weight_text,normalized_weight_text
FROM run_ranges_before_short_presets;

DROP TABLE run_ranges_before_short_presets;

CREATE INDEX idx_run_ranges_run ON run_ranges(run_id,ordinal);

PRAGMA legacy_alter_table = OFF;
