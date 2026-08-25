-- L1 definition/protocol registry. This is independent from L2/L3 fact tables.
CREATE TABLE IF NOT EXISTS l1_contract_definition (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contract_type VARCHAR(40) NOT NULL,
    contract_code VARCHAR(120) NOT NULL,
    payload JSONB NOT NULL,
    version VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contract_type, contract_code, version),
    CHECK (status IN ('draft', 'active', 'deprecated'))
);

CREATE TABLE IF NOT EXISTS l1_change_proposal (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    proposal_id VARCHAR(120) NOT NULL UNIQUE,
    proposal_type VARCHAR(60) NOT NULL,
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    proposed_by VARCHAR(200),
    reviewed_by VARCHAR(200),
    rollback_plan TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('draft', 'validated', 'benchmarked', 'approved', 'published', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_l1_contract_type_code
    ON l1_contract_definition(contract_type, contract_code);
CREATE INDEX IF NOT EXISTS idx_l1_change_status
    ON l1_change_proposal(status);
