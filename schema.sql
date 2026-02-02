PRAGMA foreign_keys = ON;

-- Supply chain nodes: fabs, memory makers, OSAT/packaging, materials, equipment, logistics, etc.
CREATE TABLE IF NOT EXISTS supply_chain_node (
  node_id TEXT PRIMARY KEY,
  node_name TEXT NOT NULL,
  node_type TEXT NOT NULL,      -- e.g., "memory_maker", "packaging", "material", "equipment", "fab", "logistics"
  country_code TEXT,
  parent_org TEXT,
  criticality_score REAL NOT NULL DEFAULT 0.5,  -- 0..1 (HBM relevance)
  chokepoint_flag INTEGER NOT NULL DEFAULT 0,   -- 1 if known bottleneck
  notes TEXT
);

-- Directed edges between nodes (who depends on whom)
CREATE TABLE IF NOT EXISTS supply_chain_edge (
  edge_id TEXT PRIMARY KEY,
  from_node_id TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  to_node_id TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  dependency_type TEXT NOT NULL,   -- e.g., "supplies", "packages", "fabricates_for", "ships_for"
  dependency_weight REAL NOT NULL DEFAULT 0.5, -- 0..1
  UNIQUE(from_node_id, to_node_id, dependency_type)
);

-- Sanctions / restricted entity list (can be populated from OFAC/BIS/EU/UN, etc.)
CREATE TABLE IF NOT EXISTS sanctioned_entity (
  entity_id TEXT PRIMARY KEY,
  entity_name TEXT NOT NULL,
  regime TEXT NOT NULL,         -- e.g., "US_BIS", "US_OFAC", "EU", "UN"
  program TEXT,
  listed_on_utc TEXT,
  url TEXT,
  notes TEXT
);

-- OSINT signals: news, academic, gov pressers, SNS posts (normalized JSON payload kept)
CREATE TABLE IF NOT EXISTS osint_signal (
  signal_id TEXT PRIMARY KEY,
  collected_at_utc TEXT NOT NULL,
  source_type TEXT NOT NULL,      -- "web"|"academic_db"|"sns"
  source_name TEXT,
  url TEXT,
  lang TEXT NOT NULL DEFAULT 'english',
  title TEXT,
  summary TEXT,
  raw_json TEXT NOT NULL,         -- full JSON payload as string
  sha256 TEXT NOT NULL UNIQUE
);

-- Link signals to nodes/entities
CREATE TABLE IF NOT EXISTS signal_link (
  link_id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL REFERENCES osint_signal(signal_id) ON DELETE CASCADE,
  node_id TEXT REFERENCES supply_chain_node(node_id) ON DELETE SET NULL,
  entity_id TEXT REFERENCES sanctioned_entity(entity_id) ON DELETE SET NULL,
  mention_confidence REAL NOT NULL DEFAULT 0.5,
  UNIQUE(signal_id, node_id, entity_id)
);

-- Risk assessments output (time series friendly)
CREATE TABLE IF NOT EXISTS risk_assessment (
  assessment_id TEXT PRIMARY KEY,
  assessed_at_utc TEXT NOT NULL,
  adversary_node TEXT,            -- node_id or free-text adversary actor
  chokepoint_status TEXT NOT NULL, -- "green"|"amber"|"red"
  kinetic_impact REAL NOT NULL,   -- 0..1 (operational impact proxy)
  economic_impact REAL NOT NULL,  -- 0..1
  policy_impact REAL NOT NULL,    -- 0..1
  composite_risk REAL NOT NULL,   -- 0..1
  evidence_json TEXT NOT NULL     -- pointers to signal_ids + rationale
);

CREATE INDEX IF NOT EXISTS idx_signal_collected ON osint_signal(collected_at_utc);
CREATE INDEX IF NOT EXISTS idx_link_signal ON signal_link(signal_id);
CREATE INDEX IF NOT EXISTS idx_edge_from ON supply_chain_edge(from_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_to ON supply_chain_edge(to_node_id);
