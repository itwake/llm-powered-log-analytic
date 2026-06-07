CREATE TABLE IF NOT EXISTS analysis_step_artifacts (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  step_name TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  object_uri TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(analysis_run_id, step_name, artifact_type)
);

CREATE INDEX IF NOT EXISTS idx_analysis_step_artifacts_case_run
  ON analysis_step_artifacts(case_id, analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_analysis_step_artifacts_step
  ON analysis_step_artifacts(step_name);
