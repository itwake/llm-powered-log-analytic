DROP TABLE IF EXISTS analytics_sink_writes;

ALTER TABLE raw_files
  DROP COLUMN IF EXISTS upload_metadata;
