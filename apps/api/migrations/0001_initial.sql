CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  username TEXT UNIQUE NOT NULL,
  full_name TEXT,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'engineer',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE copilot_credentials (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  credential_type TEXT NOT NULL,
  encrypted_token BYTEA NOT NULL,
  token_hint TEXT,
  github_base_url TEXT NOT NULL DEFAULT 'https://github.com',
  runtime_type TEXT NOT NULL DEFAULT 'github_copilot',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);

CREATE TABLE copilot_device_auth (
  auth_id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  device_code TEXT NOT NULL,
  user_code TEXT NOT NULL,
  verification_uri TEXT NOT NULL,
  verification_uri_complete TEXT NOT NULL,
  expires_in INT NOT NULL,
  interval INT NOT NULL,
  poll_count INT NOT NULL DEFAULT 0,
  github_base_url TEXT NOT NULL DEFAULT 'https://github.com',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cases (
  id UUID PRIMARY KEY,
  case_key TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  issue_description TEXT,
  product TEXT,
  service TEXT,
  environment TEXT,
  incident_start TIMESTAMPTZ,
  incident_end TIMESTAMPTZ,
  timezone TEXT DEFAULT 'UTC',
  status TEXT NOT NULL DEFAULT 'created',
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE analysis_runs (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  run_number INT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  config_json JSONB NOT NULL DEFAULT '{}',
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_reasoning_effort TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  drain_config_json JSONB NOT NULL DEFAULT '{}',
  causal_config_json JSONB NOT NULL DEFAULT '{}',
  progress_json JSONB NOT NULL DEFAULT '{}',
  result_json JSONB,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  error_message TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, run_number)
);

CREATE TABLE job_events (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  step_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INT NOT NULL DEFAULT 1,
  idempotency_key TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(analysis_run_id, idempotency_key, event_type)
);

CREATE INDEX idx_job_events_case_run ON job_events(case_id, analysis_run_id);
CREATE INDEX idx_job_events_step ON job_events(step_name);

CREATE TABLE analytics_sink_writes (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  sink_name TEXT NOT NULL,
  destination TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  row_count BIGINT NOT NULL DEFAULT 0,
  last_error TEXT,
  last_attempt_at TIMESTAMPTZ,
  next_retry_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_analytics_sink_writes_case_run ON analytics_sink_writes(case_id, analysis_run_id);
CREATE INDEX idx_analytics_sink_writes_status_retry ON analytics_sink_writes(status, next_retry_at);

CREATE TABLE raw_files (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID REFERENCES analysis_runs(id),
  original_filename TEXT NOT NULL,
  object_uri TEXT NOT NULL,
  content_type TEXT,
  size_bytes BIGINT NOT NULL,
  sha256 TEXT,
  upload_completed BOOLEAN NOT NULL DEFAULT FALSE,
  upload_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  detected_format TEXT,
  file_role TEXT DEFAULT 'log',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE raw_log_lines (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  file_id UUID NOT NULL REFERENCES raw_files(id),
  line_number BIGINT NOT NULL,
  raw_text TEXT NOT NULL,
  raw_text_redacted TEXT,
  sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_raw_log_lines_case_run ON raw_log_lines(case_id, analysis_run_id);
CREATE INDEX idx_raw_log_lines_file_line ON raw_log_lines(file_id, line_number);

CREATE TABLE log_templates (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  template_key TEXT NOT NULL,
  template_text TEXT NOT NULL,
  normalized_template_text TEXT NOT NULL,
  representative_log_id UUID,
  occurrence_count BIGINT NOT NULL DEFAULT 0,
  first_seen TIMESTAMPTZ,
  last_seen TIMESTAMPTZ,
  services JSONB NOT NULL DEFAULT '[]',
  files JSONB NOT NULL DEFAULT '[]',
  sample_values JSONB NOT NULL DEFAULT '{}',
  drain_cluster_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(analysis_run_id, template_key)
);

CREATE TABLE normalized_log_lines (
  id UUID PRIMARY KEY,
  raw_log_id UUID NOT NULL REFERENCES raw_log_lines(id),
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  timestamp TIMESTAMPTZ,
  timestamp_quality TEXT NOT NULL DEFAULT 'parsed',
  level TEXT,
  service TEXT,
  message TEXT NOT NULL,
  normalized_message TEXT NOT NULL,
  redacted_message TEXT NOT NULL,
  parsed_fields JSONB NOT NULL DEFAULT '{}',
  parser_name TEXT,
  parser_confidence FLOAT NOT NULL DEFAULT 0.0,
  template_id UUID REFERENCES log_templates(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE representative_samples (
  id UUID PRIMARY KEY,
  template_id UUID NOT NULL REFERENCES log_templates(id),
  log_id UUID NOT NULL REFERENCES normalized_log_lines(id),
  sample_reason TEXT NOT NULL,
  sample_rank INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE template_annotations (
  id UUID PRIMARY KEY,
  template_id UUID NOT NULL REFERENCES log_templates(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  golden_signal TEXT NOT NULL,
  fault_categories JSONB NOT NULL DEFAULT '[]',
  entities JSONB NOT NULL DEFAULT '{}',
  severity_score FLOAT NOT NULL DEFAULT 0.0,
  confidence FLOAT NOT NULL DEFAULT 0.0,
  rationale TEXT,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  raw_model_response JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(template_id, prompt_version, model_name)
);

CREATE TABLE time_window_signals (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  window_size_seconds INT NOT NULL,
  template_id UUID REFERENCES log_templates(id),
  service TEXT,
  golden_signal TEXT NOT NULL,
  fault_category TEXT,
  count BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE causal_nodes (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  template_id UUID NOT NULL REFERENCES log_templates(id),
  node_type TEXT NOT NULL DEFAULT 'template',
  rank_score FLOAT NOT NULL DEFAULT 0.0,
  pagerank_score FLOAT NOT NULL DEFAULT 0.0,
  golden_signal TEXT,
  fault_categories JSONB NOT NULL DEFAULT '[]',
  first_seen TIMESTAMPTZ,
  last_seen TIMESTAMPTZ,
  occurrence_count BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(analysis_run_id, template_id)
);

CREATE TABLE causal_edges (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  source_template_id UUID NOT NULL REFERENCES log_templates(id),
  target_template_id UUID NOT NULL REFERENCES log_templates(id),
  edge_type TEXT NOT NULL DEFAULT 'candidate_cause',
  method TEXT NOT NULL,
  lag_seconds INT,
  support_windows INT NOT NULL DEFAULT 0,
  confidence FLOAT NOT NULL DEFAULT 0.0,
  p_value FLOAT,
  p_value_adj FLOAT,
  lift FLOAT,
  temporal_precedence_score FLOAT,
  correlation_score FLOAT,
  evidence JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE causal_summaries (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  summary_markdown TEXT NOT NULL,
  customer_update_markdown TEXT NOT NULL,
  next_actions_json JSONB NOT NULL DEFAULT '[]',
  evidence_refs_json JSONB NOT NULL DEFAULT '[]',
  confidence FLOAT NOT NULL DEFAULT 0.0,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  raw_model_response JSONB,
  edited_by UUID REFERENCES users(id),
  edited_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feedback (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID REFERENCES analysis_runs(id),
  user_id UUID NOT NULL REFERENCES users(id),
  target_type TEXT NOT NULL,
  target_id TEXT,
  feedback_type TEXT NOT NULL,
  rating INT,
  comment TEXT,
  corrected_value JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exports (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id),
  export_type TEXT NOT NULL,
  object_uri TEXT NOT NULL,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  case_id UUID REFERENCES cases(id),
  ip_address TEXT,
  user_agent TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
