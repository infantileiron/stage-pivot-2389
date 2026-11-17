-- 002: 演出合同分成、预付款抵扣与付款回执
-- 与 ORM 模型对应；初表由 ORM create_all 创建，此文件提供等价 DDL。

CREATE TABLE contracts (
	id INTEGER NOT NULL AUTO_INCREMENT,
	code VARCHAR(60) NOT NULL,
	name VARCHAR(100) NOT NULL,
	producer VARCHAR(100) NOT NULL,
	play VARCHAR(60) NOT NULL,
	venue VARCHAR(40),
	start_day VARCHAR(10) NOT NULL,
	end_day VARCHAR(10) NOT NULL,
	ratio_bp INTEGER NOT NULL,
	advance_cents BIGINT NOT NULL,
	status VARCHAR(20),
	version INTEGER,
	needs_recalc INTEGER,
	current_run_id INTEGER,
	open_run INTEGER NOT NULL DEFAULT 0,
	earned_cents BIGINT,
	published_advance_cents BIGINT,
	paid_cents BIGINT,
	payable_cents BIGINT,
	credit_cents BIGINT,
	recovery_cents BIGINT,
	settlement_fingerprint VARCHAR(64),
	published_at VARCHAR(40),
	created VARCHAR(40),
	updated VARCHAR(40),
	PRIMARY KEY (id),
	UNIQUE (code)
);

CREATE TABLE share_runs (
	id INTEGER NOT NULL AUTO_INCREMENT,
	contract_id INTEGER NOT NULL,
	state VARCHAR(20),
	snapshot JSON,
	result JSON,
	error TEXT,
	attempts INTEGER,
	contract_version INTEGER,
	settlement_fingerprint VARCHAR(64),
	retry_of INTEGER,
	created_by VARCHAR(100),
	created VARCHAR(40),
	started VARCHAR(40),
	finished VARCHAR(40),
	published VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(contract_id) REFERENCES contracts (id)
);

CREATE INDEX ix_share_runs_contract ON share_runs (contract_id, state);

CREATE TABLE payment_receipts (
	id INTEGER NOT NULL AUTO_INCREMENT,
	contract_id INTEGER NOT NULL,
	receipt_no VARCHAR(100) NOT NULL,
	amount_cents BIGINT NOT NULL,
	paid_day VARCHAR(10) NOT NULL,
	note TEXT,
	status VARCHAR(20),
	run_id INTEGER,
	payable_before_cents BIGINT,
	payable_after_cents BIGINT,
	created_by VARCHAR(100),
	created VARCHAR(40),
	PRIMARY KEY (id),
	FOREIGN KEY(contract_id) REFERENCES contracts (id),
	UNIQUE (receipt_no)
);

CREATE INDEX ix_receipts_contract ON payment_receipts (contract_id, status);
