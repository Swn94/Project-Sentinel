-- Project Sentinel Database Schema
-- Optimized for Supply Chain Tracing & OSINT Signal Storage

CREATE TABLE IF NOT EXISTS supply_nodes (
    node_id SERIAL PRIMARY KEY,
    entity_name VARCHAR(100) NOT NULL,
    role_type VARCHAR(50) CHECK (role_type IN ('IP_HOLDER', 'CHOKEPOINT', 'ASSEMBLY', 'PROXY', 'ADVERSARY')),
    country_code CHAR(2) NOT NULL,
    risk_level FLOAT DEFAULT 0.0, -- 0.0 (Safe) to 1.0 (Sanctioned)
    metadata JSONB -- Stores flexible OSINT data (e.g., known shell companies)
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origin_id INT REFERENCES supply_nodes(node_id),
    destination_id INT REFERENCES supply_nodes(node_id),
    shipment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cargo_type VARCHAR(50) DEFAULT 'HBM_MODULE',
    volume_units INT NOT NULL,
    manifest_data JSONB, -- Raw scraping data from shipping logs
    is_flagged BOOLEAN DEFAULT FALSE
);

-- 🚀 Strategic Indexing for Performance
-- Creating a GIN index allows us to search millions of shipping manifests instantly.
CREATE INDEX idx_manifest_search ON shipments USING GIN (manifest_data);
CREATE INDEX idx_risk_nodes ON supply_nodes (risk_level) WHERE risk_level > 0.7;

-- Seed Data (Initial Setup)
INSERT INTO supply_nodes (entity_name, role_type, country_code, risk_level) VALUES
('Nvidia HQ', 'IP_HOLDER', 'US', 0.0),
('SK Hynix', 'CHOKEPOINT', 'KR', 0.1), -- The Strategic Chokepoint
('Dubai Electronics LLC', 'PROXY', 'AE', 0.8), -- Suspicious Proxy
('Chengdu Research Inst', 'ADVERSARY', 'CN', 1.0);