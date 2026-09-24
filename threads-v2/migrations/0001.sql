CREATE TABLE jobs (
 id TEXT PRIMARY KEY, scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
 payload TEXT NOT NULL, part INTEGER NOT NULL DEFAULT 0, container_id TEXT,
 last_post_id TEXT, root_post_id TEXT, root_published_at TEXT, error TEXT,
 updated_at TEXT NOT NULL
);
CREATE INDEX jobs_due ON jobs(status, scheduled_at);
CREATE TABLE posts (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), part INTEGER NOT NULL,
 body TEXT NOT NULL, published_at TEXT NOT NULL, slot INTEGER NOT NULL,
 hook_type TEXT NOT NULL, UNIQUE(job_id, part)
);
CREATE TABLE snapshots (
 post_id TEXT NOT NULL REFERENCES posts(id), window TEXT NOT NULL,
 collected_at TEXT NOT NULL, age_minutes REAL NOT NULL,
 views INTEGER NOT NULL, likes INTEGER NOT NULL, reposts INTEGER NOT NULL,
 PRIMARY KEY(post_id, window)
);
CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE ai_runs (
 id TEXT PRIMARY KEY, month TEXT NOT NULL, status TEXT NOT NULL,
 reserved_usd REAL NOT NULL, actual_usd REAL,
 input_tokens INTEGER, output_tokens INTEGER, result TEXT, created_at TEXT NOT NULL
);
CREATE TABLE alerts (
 id TEXT PRIMARY KEY, message TEXT NOT NULL, sent_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE leases (key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL);
