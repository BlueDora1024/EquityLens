CREATE TABLE quant_result_cache (
    provider_id TEXT NOT NULL CHECK(length(trim(provider_id)) > 0),
    symbol TEXT NOT NULL CHECK(length(trim(symbol)) > 0),
    interval TEXT NOT NULL CHECK(interval IN ('30m','60m','120m','240m','1d','1w')),
    start_at_utc TEXT NOT NULL,
    end_at_utc TEXT NOT NULL,
    script_version TEXT NOT NULL CHECK(length(trim(script_version)) > 0),
    result_json TEXT NOT NULL,
    cached_at_utc TEXT NOT NULL,
    PRIMARY KEY (
        provider_id,
        symbol,
        interval,
        start_at_utc,
        end_at_utc,
        script_version
    )
);
