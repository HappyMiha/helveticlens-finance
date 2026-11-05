-- Financial Lens schema v1 (PostgreSQL 15+).
-- Five things are kept apart (§5): originals (files on disk, referenced by
-- sha256), processed data (extractions), operations (append-only revisions),
-- links, and metadata with history (audit_log).

CREATE TABLE IF NOT EXISTS schema_version (version int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS organizations (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('personal','business','cooperative')),
  base_currency char(3) NOT NULL DEFAULT 'CHF',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL CHECK (role IN ('owner','admin','editor','viewer','member')),
  PRIMARY KEY (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS accounts (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  iban text,
  currency char(3) NOT NULL DEFAULT 'CHF',
  kind text NOT NULL DEFAULT 'bank' CHECK (kind IN ('bank','cash','card','other')),
  UNIQUE (organization_id, iban)
);

CREATE TABLE IF NOT EXISTS documents (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  sha256 char(64) NOT NULL,
  filename text NOT NULL,
  media_type text NOT NULL,
  size_bytes bigint NOT NULL,
  storage_key text NOT NULL,
  privacy text NOT NULL CHECK (privacy IN ('cloud_ai','swiss_hosted','local_only')),
  doc_type text NOT NULL DEFAULT 'unknown',
  doc_type_confidence numeric(4,3),
  processing_status text NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received','processing','processed','needs_review','failed')),
  folder text,                         -- proposed storage path (§5), virtual
  received_at timestamptz NOT NULL DEFAULT now(),
  received_by text NOT NULL,
  UNIQUE (organization_id, sha256)
);

CREATE TABLE IF NOT EXISTS extractions (
  id uuid PRIMARY KEY,
  document_id uuid NOT NULL REFERENCES documents(id),
  engine text NOT NULL,                -- tesseract-5.3, pdftotext, qr-zbar, camt-parser, llm:<model>
  text text,
  fields jsonb NOT NULL DEFAULT '{}',  -- {field: {value, location, quote, confidence, method}}
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS categories (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  parent_id uuid REFERENCES categories(id),
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('expense','income','transfer','unclassified')),
  archived boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS categories_unique_name
  ON categories (organization_id, coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name));

CREATE TABLE IF NOT EXISTS projects (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  UNIQUE (organization_id, name)
);

-- An operation is an identity; its content lives in append-only revisions.
CREATE TABLE IF NOT EXISTS operations (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  kind text NOT NULL CHECK (kind IN ('invoice','receipt','expense','income','payment','transfer','refund','payslip','contribution')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operation_revisions (
  id uuid PRIMARY KEY,
  operation_id uuid NOT NULL REFERENCES operations(id),
  revision int NOT NULL,
  amount numeric(20,4) NOT NULL,       -- signed: negative = money out (payments only)
  currency char(3) NOT NULL,
  fx_rate numeric(20,10),
  fx_source text,
  op_date date NOT NULL,
  due_date date,
  counterparty text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  category_id uuid REFERENCES categories(id),
  project_id uuid REFERENCES projects(id),
  account_id uuid REFERENCES accounts(id),
  reference text,                      -- QR / SCOR reference
  bank_reference text,                 -- AcctSvcrRef, for duplicate detection
  period text,                         -- e.g. 2026-10
  verification text NOT NULL CHECK (verification IN ('confirmed','needs_review','unconfirmed')),
  verification_reason text NOT NULL DEFAULT '',
  source_document_id uuid REFERENCES documents(id),
  method text NOT NULL,                -- manual, ocr, structured_import, ai_extraction, rule
  agent text NOT NULL,                 -- who/what produced this revision
  confidence numeric(4,3),
  provenance jsonb NOT NULL DEFAULT '{}',  -- per-field provenance
  change_reason text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (operation_id, revision)
);
CREATE INDEX IF NOT EXISTS opr_by_op ON operation_revisions (operation_id, revision DESC);

CREATE OR REPLACE VIEW operations_current AS
SELECT DISTINCT ON (r.operation_id)
  o.organization_id, o.kind, o.created_at AS operation_created_at, r.*
FROM operation_revisions r JOIN operations o ON o.id = r.operation_id
ORDER BY r.operation_id, r.revision DESC;

CREATE TABLE IF NOT EXISTS tags (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  UNIQUE (organization_id, name)
);
CREATE TABLE IF NOT EXISTS operation_tags (
  operation_id uuid NOT NULL REFERENCES operations(id),
  tag_id uuid NOT NULL REFERENCES tags(id),
  PRIMARY KEY (operation_id, tag_id)
);

CREATE TABLE IF NOT EXISTS document_operations (
  document_id uuid NOT NULL REFERENCES documents(id),
  operation_id uuid NOT NULL REFERENCES operations(id),
  role text NOT NULL,                  -- source, attachment, statement
  PRIMARY KEY (document_id, operation_id, role)
);

-- Many-to-many links between operations (§4.5).
CREATE TABLE IF NOT EXISTS links (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  from_operation_id uuid NOT NULL REFERENCES operations(id),  -- e.g. the invoice
  to_operation_id uuid NOT NULL REFERENCES operations(id),    -- e.g. the payment
  link_type text NOT NULL CHECK (link_type IN ('payment','receipt','refund','settlement','duplicate','transfer','contribution')),
  amount numeric(20,4),                -- portion covered, for partial payments
  currency char(3),
  rule text NOT NULL,
  reasons jsonb NOT NULL DEFAULT '[]',
  status text NOT NULL CHECK (status IN ('proposed','confirmed','rejected')),
  created_by text NOT NULL,
  decided_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz,
  UNIQUE (from_operation_id, to_operation_id, link_type)
);

CREATE TABLE IF NOT EXISTS classification_rules (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  field text NOT NULL CHECK (field IN ('counterparty','description','iban')),
  pattern text NOT NULL,               -- case-insensitive substring
  category_id uuid REFERENCES categories(id),
  project_id uuid REFERENCES projects(id),
  origin text NOT NULL CHECK (origin IN ('user','learned','builtin')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, field, pattern)
);

-- What AI or automation did (§13 "AI Activity").
CREATE TABLE IF NOT EXISTS ai_activity (
  id bigserial PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  at timestamptz NOT NULL DEFAULT now(),
  task text NOT NULL,                  -- ocr, recognise, extract, classify, match, ask
  provider text NOT NULL,
  locality text NOT NULL CHECK (locality IN ('local','swiss','external','none')),
  document_id uuid REFERENCES documents(id),
  operation_id uuid REFERENCES operations(id),
  summary text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  organization_id uuid,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  entity text NOT NULL,
  entity_id text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'
);

-- History is append-only: revisions, extractions and the audit log cannot be
-- changed or deleted through the application role.
CREATE OR REPLACE FUNCTION fl_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Financial Lens: % on % is not allowed (append-only history)', TG_OP, TG_TABLE_NAME;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['operation_revisions','extractions','audit_log','ai_activity'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_append_only') THEN
      EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION fl_forbid_change()',
                     t || '_append_only', t);
    END IF;
  END LOOP;
END $$;


-- v2: Phase 2 — exchange rates and recurring rules.
CREATE TABLE IF NOT EXISTS fx_rates (
  currency char(3) NOT NULL,
  rate_date date NOT NULL,
  rate_to_base numeric(20,10) NOT NULL CHECK (rate_to_base > 0),  -- 1 unit of currency in base currency
  base char(3) NOT NULL DEFAULT 'CHF',
  source text NOT NULL,                -- e.g. "SNB monthly average", "bank statement", "user"
  recorded_by text NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (currency, rate_date, base, source)
);

CREATE TABLE IF NOT EXISTS recurring_rules (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  counterparty text NOT NULL,
  cadence text NOT NULL CHECK (cadence IN ('weekly','monthly','quarterly','yearly')),
  typical_amount numeric(20,4) NOT NULL,
  currency char(3) NOT NULL,
  category_id uuid REFERENCES categories(id),
  last_date date NOT NULL,
  next_expected date NOT NULL,
  occurrences int NOT NULL,
  status text NOT NULL CHECK (status IN ('proposed','confirmed','dismissed')),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, counterparty, cadence)
);


-- v3: Phase 3 — multi-profile, cooperatives, projects, budgets, permissions.
CREATE TABLE IF NOT EXISTS objects (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  kind text NOT NULL DEFAULT 'property' CHECK (kind IN ('property','unit','vehicle','equipment','other')),
  parent_id uuid REFERENCES objects(id),
  UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS members (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  member_no text NOT NULL,
  name text NOT NULL,
  object_id uuid REFERENCES objects(id),
  share_capital numeric(20,4) NOT NULL DEFAULT 0,
  joined_on date NOT NULL,
  left_on date,
  user_id uuid REFERENCES users(id),
  UNIQUE (organization_id, member_no)
);

CREATE TABLE IF NOT EXISTS member_dues (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  member_id uuid NOT NULL REFERENCES members(id),
  period text NOT NULL,
  amount numeric(20,4) NOT NULL CHECK (amount > 0),
  currency char(3) NOT NULL DEFAULT 'CHF',
  due_date date NOT NULL,
  purpose text NOT NULL DEFAULT 'contribution',
  fund_id uuid,
  UNIQUE (member_id, period, purpose)
);

CREATE TABLE IF NOT EXISTS funds (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  purpose text NOT NULL DEFAULT '',
  earmarked boolean NOT NULL DEFAULT true,
  UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS budgets (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  category_id uuid REFERENCES categories(id),
  project_id uuid REFERENCES projects(id),
  period_start date NOT NULL,
  period_end date NOT NULL,
  amount numeric(20,4) NOT NULL CHECK (amount >= 0),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS allocations (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  operation_id uuid NOT NULL REFERENCES operations(id),
  object_id uuid REFERENCES objects(id),
  member_id uuid REFERENCES members(id),
  amount numeric(20,4) NOT NULL,
  basis text NOT NULL,                 -- e.g. "area m²", "equal", "share"
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Classification beyond category (§4.4, §2): object, member, fund, scope and expense class.
ALTER TABLE operation_revisions ADD COLUMN IF NOT EXISTS object_id uuid REFERENCES objects(id);
ALTER TABLE operation_revisions ADD COLUMN IF NOT EXISTS member_id uuid REFERENCES members(id);
ALTER TABLE operation_revisions ADD COLUMN IF NOT EXISTS fund_id uuid REFERENCES funds(id);
ALTER TABLE operation_revisions ADD COLUMN IF NOT EXISTS scope text CHECK (scope IN ('personal','business'));
ALTER TABLE operation_revisions ADD COLUMN IF NOT EXISTS expense_class text CHECK (expense_class IN ('opex','capex'));

CREATE OR REPLACE VIEW operations_current AS
SELECT DISTINCT ON (r.operation_id)
  o.organization_id, o.kind, o.created_at AS operation_created_at, r.*
FROM operation_revisions r JOIN operations o ON o.id = r.operation_id
ORDER BY r.operation_id, r.revision DESC;


-- v4: Phase 4 — settings (privacy level) and a tamper-evident audit chain.
CREATE TABLE IF NOT EXISTS settings (
  organization_id uuid NOT NULL REFERENCES organizations(id),
  key text NOT NULL,
  value jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, key)
);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain char(64);


-- v5: more ways in — e-mail import and paired phones.
CREATE TABLE IF NOT EXISTS mail_messages (
  organization_id uuid NOT NULL REFERENCES organizations(id),
  mailbox text NOT NULL,
  message_id text NOT NULL,
  sender text NOT NULL DEFAULT '',
  subject text NOT NULL DEFAULT '',
  received_at timestamptz,
  documents int NOT NULL DEFAULT 0,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, mailbox, message_id)
);

CREATE TABLE IF NOT EXISTS device_tokens (
  id uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  token_sha256 char(64) NOT NULL UNIQUE,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);

INSERT INTO schema_version (version) VALUES (1), (2), (3), (4), (5) ON CONFLICT DO NOTHING;
