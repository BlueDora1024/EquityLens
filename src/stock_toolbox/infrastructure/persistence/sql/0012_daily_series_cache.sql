CREATE TABLE market_daily_series_cache (
    provider_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    points_json TEXT NOT NULL,
    cached_at_utc TEXT NOT NULL,
    PRIMARY KEY (provider_id, symbol, start_date, end_date)
);

CREATE INDEX idx_market_daily_series_cache_lookup
ON market_daily_series_cache(provider_id, start_date, end_date, symbol);
