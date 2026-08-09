CREATE INDEX idx_memberships_watchlist_created
ON watchlist_memberships(watchlist_id,created_at_utc,id);

CREATE INDEX idx_security_classifications_security_created
ON security_classifications(security_id,created_at_utc,id);

CREATE INDEX idx_run_snapshots_history
ON run_snapshots(pinned DESC,created_at_utc DESC,run_id DESC);
