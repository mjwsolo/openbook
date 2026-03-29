/**
 * openbook telemetry API — Cloudflare Worker + D1
 *
 * Endpoints:
 *   POST /api/telemetry  — receive anonymous stats
 *   GET  /api/stats      — aggregate community stats
 *   GET  /api/percentile — get percentiles for a user ID
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Content-Type": "application/json",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers });
    }

    try {
      if (url.pathname === "/api/telemetry" && request.method === "POST") {
        return await handleTelemetry(request, env, headers);
      }
      if (url.pathname === "/api/stats" && request.method === "GET") {
        return await handleStats(env, headers);
      }
      if (url.pathname === "/api/percentile" && request.method === "GET") {
        return await handlePercentile(url, env, headers);
      }
      return new Response(JSON.stringify({ error: "Not found" }), { status: 404, headers });
    } catch (e) {
      return new Response(JSON.stringify({ error: "Internal error" }), { status: 500, headers });
    }
  },
};

async function handleTelemetry(request, env, headers) {
  const data = await request.json();

  // Validate
  if (!data.id || !data.prompts) {
    return new Response(JSON.stringify({ error: "Missing required fields" }), { status: 400, headers });
  }

  // Sanitize all fields
  const row = {
    id: String(data.id).slice(0, 64),
    version: String(data.v || "0.0.0").slice(0, 10),
    os: String(data.os || "").slice(0, 20),
    py: String(data.py || "").slice(0, 10),
    tz_offset: clamp(Number(data.tz_offset) || 0, -12, 14),
    tools: JSON.stringify((data.tools || []).slice(0, 5)),
    prompts: clamp(Number(data.prompts) || 0, 0, 10000000),
    days: clamp(Number(data.days) || 0, 0, 3650),
    daily_avg: clamp(Number(data.daily_avg) || 0, 0, 100000),
    streak: clamp(Number(data.streak) || 0, 0, 3650),
    peak_hour: clamp(Number(data.peak_hour) || 0, 0, 23),
    peak_day: String(data.peak_day || "").slice(0, 10),
    late_pct: clamp(Number(data.late_pct) || 0, 0, 100),
    weekend_pct: clamp(Number(data.weekend_pct) || 0, 0, 100),
    fix_rate: clamp(Number(data.fix_rate) || 0, 0, 100),
    polite_rate: clamp(Number(data.polite_rate) || 0, 0, 100),
    swear_rate: clamp(Number(data.swear_rate) || 0, 0, 100),
    bro_rate: clamp(Number(data.bro_rate) || 0, 0, 100),
    question_pct: clamp(Number(data.question_pct) || 0, 0, 100),
    short_pct: clamp(Number(data.short_pct) || 0, 0, 100),
    avg_prompt_len: clamp(Number(data.avg_prompt_len) || 0, 0, 100000),
    est_cost: clamp(Number(data.est_cost) || 0, 0, 1000000),
    archetype: String(data.archetype || "").slice(0, 100),
    has_config: data.has_config ? 1 : 0,
    sessions: clamp(Number(data.sessions) || 0, 0, 1000000),
    avg_session_min: clamp(Number(data.avg_session_min) || 0, 0, 10000),
    prompts_per_session: clamp(Number(data.prompts_per_session) || 0, 0, 10000),
    followup_rate: clamp(Number(data.followup_rate) || 0, 0, 100),
    categories: JSON.stringify(data.categories || {}),
    vocab_diversity: clamp(Number(data.vocab_diversity) || 0, 0, 100),
    claude_count: clamp(Number(data.claude_count) || 0, 0, 10000000),
    codex_count: clamp(Number(data.codex_count) || 0, 0, 10000000),
  };

  // Upsert
  await env.DB.prepare(`
    INSERT INTO telemetry (
      id, version, os, py, tz_offset, tools, prompts, days, daily_avg, streak,
      peak_hour, peak_day, late_pct, weekend_pct, fix_rate, polite_rate,
      swear_rate, bro_rate, question_pct, short_pct, avg_prompt_len, est_cost,
      archetype, has_config, sessions, avg_session_min, prompts_per_session,
      followup_rate, categories, vocab_diversity, claude_count, codex_count,
      updated_at
    ) VALUES (
      ?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,
      ?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,?31,?32, datetime('now')
    ) ON CONFLICT(id) DO UPDATE SET
      version=?2, os=?3, py=?4, tz_offset=?5, tools=?6, prompts=?7, days=?8,
      daily_avg=?9, streak=?10, peak_hour=?11, peak_day=?12, late_pct=?13,
      weekend_pct=?14, fix_rate=?15, polite_rate=?16, swear_rate=?17, bro_rate=?18,
      question_pct=?19, short_pct=?20, avg_prompt_len=?21, est_cost=?22,
      archetype=?23, has_config=?24, sessions=?25, avg_session_min=?26,
      prompts_per_session=?27, followup_rate=?28, categories=?29,
      vocab_diversity=?30, claude_count=?31, codex_count=?32,
      updated_at=datetime('now')
  `).bind(
    row.id, row.version, row.os, row.py, row.tz_offset, row.tools,
    row.prompts, row.days, row.daily_avg, row.streak, row.peak_hour,
    row.peak_day, row.late_pct, row.weekend_pct, row.fix_rate, row.polite_rate,
    row.swear_rate, row.bro_rate, row.question_pct, row.short_pct,
    row.avg_prompt_len, row.est_cost, row.archetype, row.has_config,
    row.sessions, row.avg_session_min, row.prompts_per_session,
    row.followup_rate, row.categories, row.vocab_diversity,
    row.claude_count, row.codex_count,
  ).run();

  return new Response(JSON.stringify({ ok: true }), { headers });
}

async function handleStats(env, headers) {
  const agg = await env.DB.prepare(`
    SELECT
      COUNT(*) as total_users,
      AVG(prompts) as avg_prompts,
      AVG(daily_avg) as avg_daily,
      AVG(late_pct) as avg_late_pct,
      AVG(streak) as avg_streak,
      AVG(est_cost) as avg_cost,
      AVG(polite_rate) as avg_polite,
      AVG(swear_rate) as avg_swear,
      AVG(sessions) as avg_sessions,
      AVG(avg_session_min) as avg_session_len,
      AVG(vocab_diversity) as avg_vocab,
      SUM(claude_count) as total_claude,
      SUM(codex_count) as total_codex
    FROM telemetry
  `).first();

  const archetypes = await env.DB.prepare(
    "SELECT archetype, COUNT(*) as cnt FROM telemetry GROUP BY archetype ORDER BY cnt DESC LIMIT 10"
  ).all();

  const os_dist = await env.DB.prepare(
    "SELECT os, COUNT(*) as cnt FROM telemetry GROUP BY os ORDER BY cnt DESC"
  ).all();

  return new Response(JSON.stringify({
    aggregate: agg,
    archetypes: archetypes.results,
    os_distribution: os_dist.results,
  }), { headers: { ...headers, "Cache-Control": "public, max-age=300" } });
}

async function handlePercentile(url, env, headers) {
  const id = url.searchParams.get("id");
  if (!id) {
    return new Response(JSON.stringify({ error: "Missing id" }), { status: 400, headers });
  }

  const user = await env.DB.prepare("SELECT * FROM telemetry WHERE id = ?").bind(id).first();
  if (!user) {
    return new Response(JSON.stringify({ error: "User not found" }), { status: 404, headers });
  }

  const total = (await env.DB.prepare("SELECT COUNT(*) as cnt FROM telemetry").first()).cnt;
  const metrics = ["prompts", "streak", "daily_avg", "late_pct", "polite_rate", "est_cost", "vocab_diversity"];
  const percentiles = {};

  for (const col of metrics) {
    const below = await env.DB.prepare(
      `SELECT COUNT(*) as cnt FROM telemetry WHERE ${col} < ?`
    ).bind(user[col]).first();
    percentiles[col] = total > 1 ? Math.round((below.cnt / (total - 1)) * 100) : 50;
  }

  return new Response(JSON.stringify({ percentiles, total_users: total }), { headers });
}

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}
