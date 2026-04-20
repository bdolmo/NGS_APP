-- Indexes to speed up show_sample_details variant queries by lab_id/run_id.
CREATE INDEX IF NOT EXISTS idx_therapeutic_lab_run
  ON THERAPEUTIC_VARIANTS (lab_id, run_id);

CREATE INDEX IF NOT EXISTS idx_other_lab_run
  ON OTHER_VARIANTS (lab_id, run_id);

CREATE INDEX IF NOT EXISTS idx_rare_lab_run
  ON RARE_VARIANTS (lab_id, run_id);
