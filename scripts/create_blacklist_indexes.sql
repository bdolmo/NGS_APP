-- Indexes to speed up /api/blacklisted_variants filters (blacklist + optional lab_id/run_id).
CREATE INDEX IF NOT EXISTS idx_therapeutic_blacklist_lab_run
  ON THERAPEUTIC_VARIANTS (blacklist, lab_id, run_id);

CREATE INDEX IF NOT EXISTS idx_other_blacklist_lab_run
  ON OTHER_VARIANTS (blacklist, lab_id, run_id);

CREATE INDEX IF NOT EXISTS idx_rare_blacklist_lab_run
  ON RARE_VARIANTS (blacklist, lab_id, run_id);
