CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK(version > 0),
    name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) > 0),
    checksum_sha256 TEXT NOT NULL CHECK(length(checksum_sha256) = 64),
    applied_at_utc TEXT NOT NULL CHECK(length(applied_at_utc) = 27 AND substr(applied_at_utc,11,1) = 'T' AND substr(applied_at_utc,20,1) = '.' AND substr(applied_at_utc,27,1) = 'Z'),
    app_version TEXT NOT NULL CHECK(length(trim(app_version)) > 0)
);

CREATE TABLE global_securities (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    canonical_symbol TEXT NOT NULL CHECK(length(canonical_symbol) BETWEEN 4 AND 64),
    market TEXT NOT NULL CHECK(market = 'US'),
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 240),
    asset_type TEXT NOT NULL CHECK(asset_type IN ('COMMON_STOCK','ADR')),
    eligibility_source TEXT NOT NULL CHECK(eligibility_source IN ('PROVIDER','AI')),
    profile_provider_id TEXT NOT NULL CHECK(length(trim(profile_provider_id)) > 0),
    exchange TEXT,
    currency TEXT CHECK(currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))),
    listing_country TEXT,
    description TEXT,
    business_profile_json TEXT NOT NULL DEFAULT '{}',
    source_updated_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    UNIQUE(canonical_symbol, market)
);
CREATE INDEX idx_global_securities_display_name ON global_securities(display_name COLLATE NOCASE);
CREATE INDEX idx_global_securities_asset_type ON global_securities(asset_type);

CREATE TABLE classifications (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 40),
    normalized_name TEXT NOT NULL UNIQUE CHECK(length(trim(normalized_name)) > 0),
    aliases_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL CHECK(origin IN ('HUMAN','AI')),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
);
CREATE INDEX idx_classifications_display_name ON classifications(display_name COLLATE NOCASE);

CREATE TABLE ai_application_receipts (
    receipt_id TEXT PRIMARY KEY CHECK(length(receipt_id) = 36 AND substr(receipt_id,15,1) = '4'),
    task TEXT NOT NULL CHECK(task = 'business_classification'),
    canonical_symbol TEXT NOT NULL,
    security_id TEXT NOT NULL REFERENCES global_securities(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    input_fingerprint TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    model_config_id TEXT NOT NULL,
    result_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('APPLIED','PARTIALLY_APPLIED','NO_CHANGE')),
    outcome_summary_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(task,canonical_symbol,input_fingerprint,prompt_version,schema_version,model_config_id)
);
CREATE INDEX idx_ai_receipts_security_created ON ai_application_receipts(security_id,created_at_utc);

CREATE TABLE security_classifications (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    security_id TEXT NOT NULL REFERENCES global_securities(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    classification_id TEXT NOT NULL REFERENCES classifications(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source TEXT NOT NULL CHECK(source IN ('HUMAN','AI')),
    ai_receipt_id TEXT REFERENCES ai_application_receipts(receipt_id) ON DELETE NO ACTION ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    confidence_text TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    source_request_id TEXT,
    human_protected INTEGER NOT NULL DEFAULT 0 CHECK(human_protected IN (0,1)),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK (
        (source='HUMAN' AND confidence_text IS NULL AND ai_receipt_id IS NULL AND source_request_id IS NULL AND human_protected=1)
        OR
        (source='AI' AND confidence_text IS NOT NULL AND ai_receipt_id IS NOT NULL AND source_request_id IS NOT NULL)
    ),
    UNIQUE(security_id,classification_id),
    UNIQUE(id,security_id)
);
CREATE INDEX idx_security_classifications_security ON security_classifications(security_id);
CREATE INDEX idx_security_classifications_classification ON security_classifications(classification_id);
CREATE INDEX idx_security_classifications_ai_receipt ON security_classifications(ai_receipt_id);

CREATE TABLE calculation_watchlists (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
    normalized_name TEXT NOT NULL UNIQUE CHECK(length(trim(normalized_name)) > 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
);
CREATE INDEX idx_watchlists_display_name ON calculation_watchlists(display_name COLLATE NOCASE);

CREATE TABLE watchlist_memberships (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    watchlist_id TEXT NOT NULL REFERENCES calculation_watchlists(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    security_id TEXT NOT NULL REFERENCES global_securities(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    participating_binding_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(watchlist_id,security_id),
    UNIQUE(id,watchlist_id),
    FOREIGN KEY(participating_binding_id,security_id) REFERENCES security_classifications(id,security_id) ON DELETE NO ACTION ON UPDATE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX idx_memberships_watchlist ON watchlist_memberships(watchlist_id);
CREATE INDEX idx_memberships_security ON watchlist_memberships(security_id);
CREATE INDEX idx_memberships_binding ON watchlist_memberships(participating_binding_id,security_id);

CREATE TABLE settings (
    key TEXT PRIMARY KEY CHECK(length(trim(key)) > 0),
    value_type TEXT NOT NULL CHECK(value_type IN ('JSON','TEXT','INTEGER','BOOLEAN')),
    value_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version > 0),
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE credential_artifacts (
    credential_reference TEXT PRIMARY KEY CHECK(length(trim(credential_reference)) > 0),
    purpose TEXT NOT NULL CHECK(purpose IN ('provider_api_key','oauth_access_token','oauth_refresh_token','ai_api_key')),
    owner_setting_key TEXT REFERENCES settings(key) ON DELETE SET NULL ON UPDATE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('STAGED','ACTIVE','PENDING_DELETE','RETAINED')),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    last_error TEXT,
    UNIQUE(credential_reference,purpose)
);
CREATE INDEX idx_credential_artifacts_status_updated ON credential_artifacts(status,updated_at_utc);
CREATE INDEX idx_credential_artifacts_owner ON credential_artifacts(owner_setting_key,purpose);

CREATE TABLE setting_credentials (
    setting_key TEXT NOT NULL REFERENCES settings(key) ON DELETE CASCADE ON UPDATE RESTRICT,
    purpose TEXT NOT NULL CHECK(purpose IN ('provider_api_key','oauth_access_token','oauth_refresh_token','ai_api_key')),
    credential_reference TEXT NOT NULL UNIQUE,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(setting_key,purpose),
    FOREIGN KEY(credential_reference,purpose) REFERENCES credential_artifacts(credential_reference,purpose) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE TABLE run_snapshots (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) = 36 AND substr(run_id,15,1) = '4'),
    run_identifier TEXT NOT NULL UNIQUE,
    operation_id TEXT UNIQUE,
    source TEXT NOT NULL CHECK(source IN ('AUTO','IMPORTED')),
    status TEXT NOT NULL CHECK(status IN ('READY','PARTIAL')),
    pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
    display_name TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    original_run_name TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    imported_at_utc TEXT,
    provider_id TEXT NOT NULL,
    provider_display_name TEXT NOT NULL,
    provider_contract_version TEXT NOT NULL,
    benchmark_symbol TEXT NOT NULL CHECK(benchmark_symbol IN ('SPY.US','QQQ.US')),
    watchlist_source_id TEXT,
    watchlist_name TEXT NOT NULL,
    watchlist_revision INTEGER,
    requested_end_date TEXT NOT NULL,
    actual_end_date TEXT NOT NULL,
    member_count INTEGER NOT NULL CHECK(member_count BETWEEN 1 AND 600),
    valid_member_count INTEGER NOT NULL CHECK(valid_member_count >= 0),
    failed_member_count INTEGER NOT NULL CHECK(failed_member_count >= 0),
    failed_member_range_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_member_range_count >= 0),
    algorithm_version TEXT NOT NULL,
    snapshot_format_version TEXT NOT NULL,
    snapshot_extensions_json TEXT NOT NULL DEFAULT '{}',
    CHECK(valid_member_count + failed_member_count = member_count),
    CHECK((source='AUTO' AND imported_at_utc IS NULL AND operation_id IS NOT NULL) OR (source='IMPORTED' AND imported_at_utc IS NOT NULL AND operation_id IS NULL)),
    CHECK((status='READY' AND failed_member_count=0 AND failed_member_range_count=0) OR (status='PARTIAL' AND failed_member_count>0))
);
CREATE INDEX idx_run_snapshots_created ON run_snapshots(created_at_utc DESC,run_id);
CREATE INDEX idx_run_snapshots_retention ON run_snapshots(source,pinned,created_at_utc,run_id);
CREATE INDEX idx_run_snapshots_watchlist ON run_snapshots(watchlist_source_id,completed_at_utc DESC);
CREATE INDEX idx_run_snapshots_status ON run_snapshots(status);
CREATE INDEX idx_run_snapshots_actual_end ON run_snapshots(actual_end_date DESC);

CREATE TABLE run_ranges (
    run_range_id TEXT PRIMARY KEY CHECK(length(run_range_id) = 36 AND substr(run_range_id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    range_key TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('PRESET_3M','PRESET_6M','PRESET_1Y','CUSTOM')),
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
CREATE INDEX idx_run_ranges_run ON run_ranges(run_id,ordinal);

CREATE TABLE run_members (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    source_membership_id TEXT,
    source_security_id TEXT,
    source_binding_id TEXT,
    canonical_symbol TEXT NOT NULL,
    market TEXT NOT NULL CHECK(market='US'),
    company_name TEXT NOT NULL,
    classification_snapshot_key TEXT NOT NULL,
    source_classification_id TEXT,
    participating_classification_name TEXT NOT NULL,
    participating_classification_normalized_name TEXT NOT NULL,
    UNIQUE(run_id,ordinal),
    UNIQUE(run_id,canonical_symbol,market),
    UNIQUE(id,run_id)
);
CREATE INDEX idx_run_members_run_symbol ON run_members(run_id,canonical_symbol);
CREATE INDEX idx_run_members_run_classification ON run_members(run_id,classification_snapshot_key);

CREATE TABLE run_stock_results (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    run_member_id TEXT NOT NULL,
    run_range_id TEXT NOT NULL,
    stock_start_close_text TEXT NOT NULL,
    stock_end_close_text TEXT NOT NULL,
    benchmark_start_close_text TEXT NOT NULL,
    benchmark_end_close_text TEXT NOT NULL,
    stock_return_text TEXT NOT NULL,
    benchmark_return_text TEXT NOT NULL,
    rs_percentage_points_text TEXT NOT NULL,
    UNIQUE(run_id,run_member_id,run_range_id),
    FOREIGN KEY(run_member_id,run_id) REFERENCES run_members(id,run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    FOREIGN KEY(run_range_id,run_id) REFERENCES run_ranges(run_range_id,run_id) ON DELETE CASCADE ON UPDATE RESTRICT
);
CREATE INDEX idx_stock_results_run_range_rs ON run_stock_results(run_id,run_range_id,rs_percentage_points_text);

CREATE TABLE run_classification_period_results (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    run_range_id TEXT NOT NULL,
    classification_snapshot_key TEXT NOT NULL,
    classification_name TEXT NOT NULL,
    total_member_count INTEGER NOT NULL CHECK(total_member_count > 0),
    valid_member_count INTEGER NOT NULL CHECK(valid_member_count BETWEEN 0 AND total_member_count),
    coverage_text TEXT NOT NULL,
    mean_rs_pp_text TEXT,
    median_rs_pp_text TEXT,
    positive_member_count INTEGER NOT NULL DEFAULT 0 CHECK(positive_member_count BETWEEN 0 AND valid_member_count),
    strong_breadth_text TEXT,
    top_members_json TEXT NOT NULL DEFAULT '[]',
    bottom_members_json TEXT NOT NULL DEFAULT '[]',
    eligibility TEXT NOT NULL CHECK(eligibility IN ('ELIGIBLE','INSUFFICIENT_SAMPLE','INSUFFICIENT_COVERAGE')),
    eligibility_reason TEXT,
    median_percentile_text TEXT,
    breadth_percentile_text TEXT,
    period_score_text TEXT,
    score_unavailable_reason TEXT,
    UNIQUE(run_id,run_range_id,classification_snapshot_key),
    FOREIGN KEY(run_range_id,run_id) REFERENCES run_ranges(run_range_id,run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CHECK(
        (eligibility!='ELIGIBLE' AND eligibility_reason IS NOT NULL AND score_unavailable_reason IS NULL AND period_score_text IS NULL)
        OR
        (eligibility='ELIGIBLE' AND period_score_text IS NULL AND eligibility_reason IS NULL AND score_unavailable_reason IS NOT NULL)
        OR
        (eligibility='ELIGIBLE' AND period_score_text IS NOT NULL AND eligibility_reason IS NULL AND score_unavailable_reason IS NULL AND median_percentile_text IS NOT NULL AND breadth_percentile_text IS NOT NULL)
    )
);
CREATE INDEX idx_class_period_run_range ON run_classification_period_results(run_id,run_range_id);
CREATE INDEX idx_class_period_run_class ON run_classification_period_results(run_id,classification_snapshot_key);

CREATE TABLE run_classification_results (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    classification_snapshot_key TEXT NOT NULL,
    classification_name TEXT NOT NULL,
    composite_score_text TEXT,
    multi_period_status TEXT NOT NULL CHECK(multi_period_status IN ('SUSTAINED_STRONG','SUSTAINED_WEAK','RECENTLY_STRENGTHENING','RECENTLY_WEAKENING','DIVERGENT','DIVERGENT_TIED_SPAN','INSUFFICIENT_DATA','NOT_APPLICABLE')),
    reason TEXT,
    UNIQUE(run_id,classification_snapshot_key),
    UNIQUE(id,run_id)
);
CREATE INDEX idx_class_results_run ON run_classification_results(run_id);

CREATE TABLE run_failures (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND substr(id,15,1) = '4'),
    run_id TEXT NOT NULL REFERENCES run_snapshots(run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    run_member_id TEXT,
    run_range_id TEXT,
    scope TEXT NOT NULL CHECK(scope IN ('MEMBER_RANGE','MEMBER','BENCHMARK','AGGREGATION','PERSISTENCE')),
    canonical_symbol TEXT,
    stage TEXT NOT NULL,
    error_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    fatal INTEGER NOT NULL DEFAULT 0 CHECK(fatal=0),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    UNIQUE(run_id,ordinal),
    FOREIGN KEY(run_member_id,run_id) REFERENCES run_members(id,run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    FOREIGN KEY(run_range_id,run_id) REFERENCES run_ranges(run_range_id,run_id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CHECK(
        (scope='MEMBER_RANGE' AND run_member_id IS NOT NULL AND run_range_id IS NOT NULL)
        OR (scope='MEMBER' AND run_member_id IS NOT NULL AND run_range_id IS NULL)
        OR (scope IN ('BENCHMARK','AGGREGATION','PERSISTENCE') AND run_member_id IS NULL AND run_range_id IS NULL)
    )
);
CREATE INDEX idx_run_failures_run_member ON run_failures(run_id,run_member_id);
CREATE INDEX idx_run_failures_run_range ON run_failures(run_id,run_range_id);
