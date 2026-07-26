CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  username TEXT NOT NULL UNIQUE,
  full_name TEXT,
  external_id TEXT UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE cases (
  id UUID PRIMARY KEY,
  case_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  issue_description TEXT,
  product TEXT,
  service TEXT,
  environment TEXT,
  incident_start TIMESTAMPTZ,
  incident_end TIMESTAMPTZ,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  status TEXT NOT NULL DEFAULT 'created',
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE raw_files (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  original_filename TEXT NOT NULL,
  object_uri TEXT NOT NULL,
  content_type TEXT,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT,
  upload_completed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analysis_runs (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  run_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_reasoning_effort TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  result_json JSONB,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  error_message TEXT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (case_id, run_number)
);

CREATE TABLE job_events (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  step_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  idempotency_key TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (analysis_run_id, idempotency_key, event_type)
);

CREATE INDEX idx_cases_created_by ON cases(created_by);
CREATE INDEX idx_raw_files_case_id ON raw_files(case_id);
CREATE INDEX idx_analysis_runs_case_id ON analysis_runs(case_id);
CREATE INDEX idx_job_events_analysis_run_id ON job_events(analysis_run_id);
