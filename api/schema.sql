-- D1 schema for openbook telemetry
CREATE TABLE IF NOT EXISTS telemetry (
  id TEXT PRIMARY KEY,
  version TEXT NOT NULL DEFAULT '0.0.0',
  os TEXT NOT NULL DEFAULT '',
  py TEXT NOT NULL DEFAULT '',
  tz_offset INTEGER NOT NULL DEFAULT 0,
  tools TEXT NOT NULL DEFAULT '[]',
  prompts INTEGER NOT NULL DEFAULT 0,
  days INTEGER NOT NULL DEFAULT 0,
  daily_avg REAL NOT NULL DEFAULT 0,
  streak INTEGER NOT NULL DEFAULT 0,
  peak_hour INTEGER NOT NULL DEFAULT 0,
  peak_day TEXT NOT NULL DEFAULT '',
  late_pct REAL NOT NULL DEFAULT 0,
  weekend_pct REAL NOT NULL DEFAULT 0,
  fix_rate REAL NOT NULL DEFAULT 0,
  polite_rate REAL NOT NULL DEFAULT 0,
  swear_rate REAL NOT NULL DEFAULT 0,
  bro_rate REAL NOT NULL DEFAULT 0,
  question_pct REAL NOT NULL DEFAULT 0,
  short_pct REAL NOT NULL DEFAULT 0,
  avg_prompt_len INTEGER NOT NULL DEFAULT 0,
  est_cost REAL NOT NULL DEFAULT 0,
  archetype TEXT NOT NULL DEFAULT '',
  has_config INTEGER NOT NULL DEFAULT 0,
  sessions INTEGER NOT NULL DEFAULT 0,
  avg_session_min INTEGER NOT NULL DEFAULT 0,
  prompts_per_session REAL NOT NULL DEFAULT 0,
  followup_rate REAL NOT NULL DEFAULT 0,
  categories TEXT NOT NULL DEFAULT '{}',
  vocab_diversity REAL NOT NULL DEFAULT 0,
  claude_count INTEGER NOT NULL DEFAULT 0,
  codex_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prompts ON telemetry(prompts DESC);
CREATE INDEX IF NOT EXISTS idx_streak ON telemetry(streak DESC);
CREATE INDEX IF NOT EXISTS idx_archetype ON telemetry(archetype);
CREATE INDEX IF NOT EXISTS idx_os ON telemetry(os);
CREATE INDEX IF NOT EXISTS idx_updated ON telemetry(updated_at DESC);
