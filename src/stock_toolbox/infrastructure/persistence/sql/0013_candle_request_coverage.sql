ALTER TABLE market_candle_coverage
ADD COLUMN requested_count INTEGER NOT NULL DEFAULT 0 CHECK(requested_count >= 0);

ALTER TABLE market_candle_coverage
ADD COLUMN returned_count INTEGER NOT NULL DEFAULT 0 CHECK(returned_count >= 0);
