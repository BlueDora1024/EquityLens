CREATE TABLE market_candle_cache (
    provider_id TEXT NOT NULL CHECK(length(trim(provider_id)) > 0),
    symbol TEXT NOT NULL CHECK(length(trim(symbol)) > 0),
    interval TEXT NOT NULL CHECK(interval IN ('30m','60m','120m','240m','1d','1w')),
    timestamp_utc TEXT NOT NULL,
    adjustment TEXT NOT NULL CHECK(adjustment = 'forward'),
    regular_session INTEGER NOT NULL CHECK(regular_session = 1),
    open_text TEXT NOT NULL,
    high_text TEXT NOT NULL,
    low_text TEXT NOT NULL,
    close_text TEXT NOT NULL,
    volume INTEGER NOT NULL CHECK(volume >= 0),
    cached_at_utc TEXT NOT NULL,
    PRIMARY KEY (
        provider_id,
        symbol,
        interval,
        timestamp_utc,
        adjustment,
        regular_session
    )
);
CREATE INDEX idx_market_candle_cache_lookup
ON market_candle_cache(provider_id,symbol,interval,timestamp_utc DESC);

