CREATE TYPE hypothesis_source AS ENUM ('sectors', 'screener', 'markov', 'coach', 'manual');
CREATE TYPE hypothesis_status AS ENUM ('open', 'generated', 'archived');
CREATE TYPE deployment_status AS ENUM ('active', 'paused', 'retired', 'failed');

CREATE TABLE hypotheses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source hypothesis_source NOT NULL,
  ticker TEXT,
  sector TEXT,
  regime TEXT,
  conviction TEXT,
  why TEXT NOT NULL,
  context JSONB,
  status hypothesis_status NOT NULL DEFAULT 'open',
  source_meta JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  generated_strategy_id UUID
);

CREATE INDEX idx_hypotheses_status ON hypotheses(status, created_at DESC);
CREATE INDEX idx_hypotheses_source ON hypotheses(source);

CREATE TABLE deployments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_path TEXT NOT NULL,
  deployed_at TIMESTAMP NOT NULL DEFAULT NOW(),
  status deployment_status NOT NULL DEFAULT 'active',
  parent_id UUID REFERENCES deployments(id),
  params_json JSONB,
  metrics_snapshot JSONB
);

CREATE INDEX idx_deployments_strategy ON deployments(strategy_path, deployed_at DESC);
CREATE INDEX idx_deployments_status ON deployments(status);
