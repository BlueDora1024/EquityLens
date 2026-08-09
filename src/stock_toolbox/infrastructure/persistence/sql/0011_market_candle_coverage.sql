CREATE TABLE market_candle_coverage (
    provider_id TEXT NOT NULL CHECK(length(trim(provider_id)) > 0),
    symbol TEXT NOT NULL CHECK(length(trim(symbol)) > 0),
    interval TEXT NOT NULL CHECK(interval IN ('30m','60m','120m','240m','1d','1w')),
    adjustment TEXT NOT NULL CHECK(adjustment = 'forward'),
    regular_session INTEGER NOT NULL CHECK(regular_session = 1),
    covered_through_utc TEXT NOT NULL,
    cached_at_utc TEXT NOT NULL,
    PRIMARY KEY (
        provider_id,
        symbol,
        interval,
        adjustment,
        regular_session
    )
);
