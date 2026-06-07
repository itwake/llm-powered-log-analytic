CREATE TABLE IF NOT EXISTS organizations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO organizations (id, name, slug, is_default)
VALUES ('default', 'Default Organization', 'default', TRUE)
ON CONFLICT (id) DO UPDATE
SET
  name = EXCLUDED.name,
  slug = EXCLUDED.slug,
  is_default = TRUE;

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS organization_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS external_id TEXT;

ALTER TABLE cases
  ADD COLUMN IF NOT EXISTS organization_id TEXT NOT NULL DEFAULT 'default';

ALTER TABLE copilot_credentials
  ADD COLUMN IF NOT EXISTS key_id TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint constraint_record
    JOIN pg_class source_table
      ON source_table.oid = constraint_record.conrelid
    JOIN pg_class target_table
      ON target_table.oid = constraint_record.confrelid
    JOIN pg_attribute source_column
      ON source_column.attrelid = source_table.oid
     AND source_column.attnum = ANY(constraint_record.conkey)
    WHERE constraint_record.contype = 'f'
      AND source_table.relname = 'users'
      AND source_column.attname = 'organization_id'
      AND target_table.relname = 'organizations'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT fk_users_organization
      FOREIGN KEY (organization_id) REFERENCES organizations(id);
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint constraint_record
    JOIN pg_class source_table
      ON source_table.oid = constraint_record.conrelid
    JOIN pg_class target_table
      ON target_table.oid = constraint_record.confrelid
    JOIN pg_attribute source_column
      ON source_column.attrelid = source_table.oid
     AND source_column.attnum = ANY(constraint_record.conkey)
    WHERE constraint_record.contype = 'f'
      AND source_table.relname = 'cases'
      AND source_column.attname = 'organization_id'
      AND target_table.relname = 'organizations'
  ) THEN
    ALTER TABLE cases
      ADD CONSTRAINT fk_cases_organization
      FOREIGN KEY (organization_id) REFERENCES organizations(id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS policy_groups (
  id UUID PRIMARY KEY,
  organization_id TEXT NOT NULL DEFAULT 'default' REFERENCES organizations(id),
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  description TEXT,
  external_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(organization_id, slug)
);

CREATE TABLE IF NOT EXISTS policy_group_members (
  id UUID PRIMARY KEY,
  group_id UUID NOT NULL REFERENCES policy_groups(id),
  user_id UUID NOT NULL REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'viewer',
  added_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS case_group_access (
  id UUID PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES cases(id),
  group_id UUID NOT NULL REFERENCES policy_groups(id),
  role TEXT NOT NULL,
  granted_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_users_organization
  ON users(organization_id);

CREATE INDEX IF NOT EXISTS idx_cases_organization
  ON cases(organization_id);

CREATE INDEX IF NOT EXISTS idx_policy_groups_organization
  ON policy_groups(organization_id);

CREATE INDEX IF NOT EXISTS idx_policy_group_members_user
  ON policy_group_members(user_id);

CREATE INDEX IF NOT EXISTS idx_case_group_access_group
  ON case_group_access(group_id);
