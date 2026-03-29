#!/usr/bin/env python3
"""
openbook - what your AI knows about you

Usage:
    python3 openbook.py              # full analysis + browser
    python3 openbook.py --terminal   # terminal only
    python3 openbook.py -t           # terminal only (short)
"""

__version__ = "0.1.0"

import json
import os
import re
import shutil
import sys
import tempfile
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape as html_escape
from pathlib import Path

# ─── ANSI ─────────────────────────────────────────────────────────────────────

USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def _c(code, t):
    return f"\033[{code}m{t}\033[0m" if USE_COLOR else t

def orange(t):  return _c("38;2;217;119;87", t)
def tan(t):     return _c("38;2;196;168;130", t)
def cream(t):   return _c("38;2;245;230;211", t)
def dim(t):     return _c("38;2;120;110;95", t)
def bold(t):    return _c("1", t)
def red(t):     return _c("38;2;255;100;100", t)
def green(t):   return _c("38;2;100;220;100", t)
def dimbar(t):  return _c("38;2;60;50;40", t)

# ─── Stop words ───────────────────────────────────────────────────────────────

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "shall", "can", "need", "must", "it", "its", "this", "that",
    "these", "those", "i", "you", "he", "she", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "our", "their", "mine", "yours", "ours",
    "theirs", "what", "which", "who", "whom", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "if", "then", "else", "about", "up", "out", "into", "over",
    "after", "before", "between", "under", "again", "further", "once", "here",
    "there", "any", "also", "use", "used", "using", "make", "made", "like",
    "don", "doesn", "didn", "won", "wouldn", "shouldn", "couldn", "etc",
    "e", "g", "eg", "ie", "vs", "re", "de", "le", "la", "el", "en", "es",
    "example", "http", "https", "www", "com", "org", "io", "true", "false",
    "null", "none", "yes", "set", "get", "new", "see", "let", "one",
    "two", "well", "way", "even", "still", "keep", "put", "take", "give",
    "file", "code", "add", "run", "now", "look", "want", "sure", "think",
    "know", "going", "something", "thing", "things", "much", "many", "got",
    "right", "good", "first", "last", "next", "back", "work", "working",
}

# ─── Data loading ─────────────────────────────────────────────────────────────

def load_history():
    """Load all prompts from Claude and Codex history files."""
    prompts = []
    sources_found = []

    # ── Claude Code: ~/.claude/history.jsonl ─────────────────────────────
    claude_path = Path.home() / ".claude" / "history.jsonl"
    if claude_path.exists():
        sources_found.append("Claude Code")
        with open(claude_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    if "display" in d and "timestamp" in d:
                        prompts.append({
                            "text": d["display"],
                            "ts": d["timestamp"],
                            "project": d.get("project", ""),
                            "source": "claude",
                        })
                except (json.JSONDecodeError, KeyError):
                    pass

    # ── OpenAI Codex: ~/.codex/history.jsonl ─────────────────────────────
    codex_path = Path.home() / ".codex" / "history.jsonl"
    if codex_path.exists():
        sources_found.append("Codex")
        with open(codex_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    # Codex uses: {"session_id", "ts", "text"}
                    text = d.get("text") or d.get("display") or d.get("prompt") or d.get("content", "")
                    ts = d.get("ts") or d.get("timestamp") or d.get("created_at", 0)
                    if text and ts:
                        # Normalize to milliseconds (Codex uses seconds)
                        ts_ms = ts * 1000 if ts < 1e12 else ts
                        prompts.append({
                            "text": text,
                            "ts": ts_ms,
                            "project": d.get("project", d.get("cwd", "")),
                            "source": "codex",
                        })
                except (json.JSONDecodeError, KeyError):
                    pass

    # Also check codex session rollouts
    codex_sessions = Path.home() / ".codex" / "sessions"
    if codex_sessions.is_dir():
        for rollout in codex_sessions.glob("**/rollout-*.jsonl"):
            with open(rollout, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                        # Session rollouts have typed events
                        if d.get("type") in ("user", "human", "input"):
                            text = d.get("content") or d.get("message", {}).get("content", "") or d.get("text", "")
                            ts = d.get("timestamp") or d.get("ts", 0)
                            if text and ts:
                                prompts.append({
                                    "text": text if isinstance(text, str) else str(text),
                                    "ts": ts if isinstance(ts, (int, float)) else 0,
                                    "project": d.get("project", ""),
                                    "source": "codex",
                                })
                    except (json.JSONDecodeError, KeyError):
                        pass
        if not any(p["source"] == "codex" for p in prompts):
            pass  # no codex prompts found in sessions either
        elif "Codex" not in sources_found:
            sources_found.append("Codex")

    return prompts, sources_found



# ─── Analysis ─────────────────────────────────────────────────────────────────

def analyze_prompts(prompts):
    """The big one. Extract all the juicy stats."""
    if not prompts:
        return None

    texts = [p["text"] for p in prompts]
    timestamps = [p["ts"] for p in prompts]
    all_text = " ".join(texts).lower()

    # ── Basic stats ──────────────────────────────────────────────────────
    total_prompts = len(prompts)
    total_chars = sum(len(t) for t in texts)
    avg_length = total_chars // total_prompts if total_prompts else 0

    first_date = datetime.fromtimestamp(min(timestamps) / 1000)
    last_date = datetime.fromtimestamp(max(timestamps) / 1000)
    days_active = max(1, (last_date - first_date).days)
    prompts_per_day = round(total_prompts / days_active, 1)

    # ── Time analysis ────────────────────────────────────────────────────
    hours = [datetime.fromtimestamp(ts / 1000).hour for ts in timestamps]
    hour_counts = Counter(hours)

    late_night = sum(1 for h in hours if h >= 0 and h < 5)
    # early_morning, business_hours, evening removed — unused

    peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else 12
    peak_hour_fmt = f"{peak_hour:02d}:00"

    # Day of week
    days_of_week = [datetime.fromtimestamp(ts / 1000).strftime("%A") for ts in timestamps]
    day_counts = Counter(days_of_week)
    busiest_day = day_counts.most_common(1)[0] if day_counts else ("Monday", 0)

    # Weekend warrior
    weekend_prompts = sum(1 for d in days_of_week if d in ("Saturday", "Sunday"))
    weekend_pct = round(weekend_prompts / total_prompts * 100) if total_prompts else 0

    # ── Contribution heatmap (GitHub-style) ────────────────────────────
    daily_counts = defaultdict(int)
    for ts in timestamps:
        day_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        daily_counts[day_str] += 1

    # Build week grid: list of weeks, each week is [Mon..Sun] counts
    # Start from first_date's Monday, end at last_date's Sunday
    start = first_date - timedelta(days=first_date.weekday())  # Monday
    end = last_date + timedelta(days=6 - last_date.weekday())  # Sunday
    heatmap_weeks = []
    current = start
    while current <= end:
        week = []
        for d in range(7):
            day = current + timedelta(days=d)
            day_str = day.strftime("%Y-%m-%d")
            in_range = first_date.date() <= day.date() <= last_date.date()
            week.append({
                "date": day_str,
                "count": daily_counts.get(day_str, 0),
                "in_range": in_range,
            })
        heatmap_weeks.append(week)
        current += timedelta(days=7)

    # Streak calculation
    sorted_days = sorted(daily_counts.keys())
    current_streak = 0
    max_streak = 0
    prev = None
    for day_str in sorted_days:
        day = datetime.strptime(day_str, "%Y-%m-%d")
        if prev and (day - prev).days == 1:
            current_streak += 1
        else:
            current_streak = 1
        max_streak = max(max_streak, current_streak)
        prev = day

    # ── Session detection (gap >30min = new session) ──────────────────
    sorted_ts = sorted(timestamps)
    session_gaps = []
    sessions = 1
    session_lengths = [0]
    for i in range(1, len(sorted_ts)):
        gap_min = (sorted_ts[i] - sorted_ts[i-1]) / 60000
        if gap_min > 30:
            sessions += 1
            session_lengths.append(0)
        else:
            session_lengths[-1] += gap_min

    avg_session_min = round(sum(session_lengths) / len(session_lengths)) if session_lengths else 0
    prompts_per_session = round(total_prompts / sessions, 1) if sessions else 0

    # ── Follow-up rate (prompt within 2min of previous = follow-up) ──
    followups = 0
    for i in range(1, len(sorted_ts)):
        if (sorted_ts[i] - sorted_ts[i-1]) / 60000 < 2:
            followups += 1
    followup_rate = round(followups / total_prompts * 100, 1) if total_prompts else 0

    # ── Prompt categories ────────────────────────────────────────────
    cat_fix = len(re.findall(r"\bfix\b|\bbug\b|\berror\b|\bbroken\b|\bdoesn.?t work\b", all_text))
    cat_build = len(re.findall(r"\bbuild\b|\bcreate\b|\badd\b|\bimplement\b|\bwrite\b|\bgenerate\b", all_text))
    cat_explain = len(re.findall(r"\bexplain\b|\bwhat is\b|\bwhat does\b|\bhow does\b|\bwhy does\b", all_text))
    cat_review = len(re.findall(r"\breview\b|\bcheck\b|\blook at\b|\bany issues\b", all_text))
    cat_refactor = len(re.findall(r"\brefactor\b|\bclean\b|\bsimplify\b|\brewrite\b|\brestructure\b", all_text))
    cat_test = len(re.findall(r"\btest\b|\bspec\b|\bcoverage\b|\bassert\b", all_text))
    cat_total = cat_fix + cat_build + cat_explain + cat_review + cat_refactor + cat_test
    prompt_categories = {
        "debug": cat_fix,
        "build": cat_build,
        "explain": cat_explain,
        "review": cat_review,
        "refactor": cat_refactor,
        "test": cat_test,
    }

    # ── Vocabulary diversity ─────────────────────────────────────────
    all_words_raw = re.findall(r"[a-zA-Z]{3,}", all_text)
    vocab_diversity = round(len(set(all_words_raw)) / max(len(all_words_raw), 1) * 100, 1)

    # ── Config file detection ────────────────────────────────────────
    has_claude_md = (Path.home() / ".claude" / "CLAUDE.md").exists() or any(
        (Path(p.get("project", "")) / "CLAUDE.md").exists() for p in prompts[:10] if p.get("project"))
    has_agents_md = any(
        (Path(p.get("project", "")) / "AGENTS.md").exists() for p in prompts[:10] if p.get("project"))
    has_config = has_claude_md or has_agents_md

    # ── Tool split ───────────────────────────────────────────────────
    claude_count = sum(1 for p in prompts if p.get("source") == "claude")
    codex_count = sum(1 for p in prompts if p.get("source") == "codex")

    # ── Roast stats ──────────────────────────────────────────────────────

    # Frustration signals
    fix_count = len(re.findall(r"\bfix\b", all_text))
    bug_count = len(re.findall(r"\bbug\b", all_text))
    why_count = len(re.findall(r"\bwhy\b", all_text))
    doesnt_work = len(re.findall(r"doesn.?t work|not working|broken|wrong", all_text))
    help_count = len(re.findall(r"\bhelp\b", all_text))
    error_count = len(re.findall(r"\berror\b", all_text))

    # Politeness
    please_count = len(re.findall(r"\bplease\b", all_text))
    thanks_count = len(re.findall(r"\bthanks?\b|\bthank you\b|\bcheers\b", all_text))
    sorry_count = len(re.findall(r"\bsorry\b|\bmy bad\b|\bapologi", all_text))

    # Indecisiveness
    actually_count = len(re.findall(r"\bactually\b", all_text))
    nevermind_count = len(re.findall(r"\bnevermind\b|\bnever mind\b|\bforget it\b|\bignore that\b", all_text))
    # wait_count removed — unused
    nvm_count = len(re.findall(r"\bnvm\b", all_text))
    changed_mind = actually_count + nevermind_count + nvm_count

    # Overexplaining / context dumping
    long_prompts = sum(1 for t in texts if len(t) > 500)
    short_prompts = sum(1 for t in texts if len(t) < 20)
    one_worders = sum(1 for t in texts if len(t.strip().split()) <= 2)

    # Bro/dude energy
    bro_count = len(re.findall(r"\bbro\b|\bdude\b|\bman\b|\bmate\b|\bfam\b", all_text))

    # Excitement
    exclamation_count = sum(t.count("!") for t in texts)
    question_count = sum(1 for t in texts if "?" in t)
    caps_prompts = sum(1 for t in texts if sum(1 for c in t if c.isupper()) > len(t) * 0.5 and len(t) > 10)

    # Perfectionism
    refactor_count = len(re.findall(r"\brefactor\b|\bclean up\b|\brewrite\b|\bredo\b", all_text))
    # change_count removed — unused
    too_much = len(re.findall(r"\btoo much\b|\btoo many\b|\btoo long\b|\btoo short\b|\boverboard\b|\boverkill\b", all_text))

    # Compliments / roasts to AI
    good_job = len(re.findall(r"\bgood\b|\bgreat\b|\bperfect\b|\bnice\b|\bamazing\b|\bawesome\b|\blove it\b|\bbeautiful\b", all_text))
    bad_job = len(re.findall(r"\bwrong\b|\bbad\b|\bno\b|\bnot what\b|\bnope\b|\bterrible\b|\bawful\b|\bugly\b|\bshit\b|\bcrap\b", all_text))

    # Swearing
    swear_count = len(re.findall(r"\bshit\b|\bfuck\b|\bdamn\b|\bhell\b|\bcrap\b|\bass\b|\bwtf\b|\bwth\b|\bomg\b|\bffs\b|\blmao\b|\blol\b", all_text))

    # ── Projects ─────────────────────────────────────────────────────────
    project_counts = Counter()
    for p in prompts:
        proj = p.get("project", "")
        if proj:
            name = Path(proj).name
            project_counts[name] = project_counts.get(name, 0) + 1

    top_projects = project_counts.most_common(5)

    # ── Longest prompt ───────────────────────────────────────────────────
    longest_raw = max(texts, key=len)
    longest_words = len(longest_raw.split())
    # Sanitize: strip file paths, emails, tokens
    longest = re.sub(r"[/~][\w/\-_.]+", "[path]", longest_raw)
    longest = re.sub(r"\S+@\S+\.\S+", "[email]", longest)
    longest = re.sub(r"(sk|pk|token|key|secret|password)[\-_]?\w{10,}", "[redacted]", longest, flags=re.I)

    # ── Shortest meaningful prompt ───────────────────────────────────────
    short_ones = [t for t in texts if len(t.strip()) > 0]
    shortest = min(short_ones, key=len) if short_ones else ""

    # ── Most repeated prompts (filter slash commands and system noise) ──
    prompt_counts = Counter(
        t.strip().lower() for t in texts
        if len(t.strip()) > 5 and not t.strip().startswith("/")
    )
    most_repeated = prompt_counts.most_common(3)

    # ── Word cloud data ──────────────────────────────────────────────────
    # Build privacy filter: usernames, dir names, project names
    privacy_words = set()
    home = Path.home()
    privacy_words.add(home.name.lower())
    for part in home.parts:
        if len(part) > 2:
            privacy_words.add(part.lower().strip("/"))
    # Project folder names from history paths
    for p in prompts:
        proj = p.get("project", "")
        if proj:
            for chunk in Path(proj).parts:
                if len(chunk) > 2:
                    privacy_words.add(chunk.lower().strip("-"))
            # Also split hyphenated project dir names
            name = Path(proj).name
            for chunk in name.split("-"):
                if len(chunk) > 2:
                    privacy_words.add(chunk.lower())
    privacy_words.update({
        "users", "home", "documents", "desktop", "downloads", "github",
        "repos", "projects", "src", "lib", "bin", "var", "tmp",
        "volumes", "applications", "library", "usr", "local", "opt",
    })

    # Strip file paths from text before extracting
    cleaned_text = re.sub(r"[/~][\w/\-_.]+", " ", all_text)
    words = re.findall(r"[a-zA-Z]{3,}", cleaned_text)
    words = [w for w in words if w not in STOP_WORDS and w not in privacy_words and len(w) <= 25]
    word_counts = Counter(words)
    top_words = word_counts.most_common(50)

    cloud_words = []
    if top_words:
        max_count = top_words[0][1]
        for word, count in top_words:
            size = max(14, int((count / max_count) * 72))
            cloud_words.append({"text": word, "size": size, "count": count})

    # ── Topic extraction (what you actually talk about) ────────────────
    # Look for meaningful nouns/phrases that indicate topics
    TOPIC_WORDS = {
        # ML / Data Science
        "model", "training", "test", "dataset", "accuracy", "loss", "epoch",
        "neural", "network", "prediction", "regression", "classification",
        "embedding", "transformer", "attention", "lstm", "cnn", "bert", "gpt",
        "pytorch", "tensorflow", "sklearn", "pandas", "numpy", "gradient",
        "overfitting", "hyperparameter", "validation", "inference", "weights",
        "features", "labels", "batch", "optimizer", "learning", "finetune",
        # Web / Frontend
        "component", "button", "page", "layout", "sidebar", "navbar",
        "modal", "form", "input", "dropdown", "animation", "css", "style",
        "responsive", "frontend", "backend", "endpoint", "route", "middleware",
        # Data / DB
        "database", "query", "schema", "table", "migration", "postgres",
        "mongodb", "redis", "sql", "index", "cache", "pipeline",
        # DevOps / Infra
        "deploy", "docker", "kubernetes", "ci", "pipeline", "server",
        "cloud", "aws", "lambda", "container", "monitoring", "logs",
        # General dev
        "api", "auth", "login", "token", "webhook", "websocket",
        "config", "env", "build", "lint", "format", "dependency",
        "refactor", "debug", "performance", "memory", "thread",
        # Domain
        "graph", "ontology", "knowledge", "entity", "relationship", "node",
        "edge", "extraction", "scraping", "parsing", "nlp", "search",
        "chart", "plot", "visualization", "dashboard", "report", "metric",
        "payment", "user", "notification", "email", "upload", "download",
    }

    topic_counts = {}
    for w, cnt in word_counts.items():
        if w in TOPIC_WORDS:
            topic_counts[w] = cnt
    # Also grab high-frequency non-stopwords that seem like real topics
    TOPIC_NOISE = {
        "dude", "bro", "mate", "fam", "man", "guys", "okay", "yeah",
        "pasted", "lines", "text", "users", "stuff", "dont", "doesnt",
        "cant", "wont", "isnt", "arent", "didnt", "hasn", "also",
        "maybe", "really", "actually", "already", "basically",
        "need", "should", "would", "could", "please", "thanks",
        "looks", "seems", "gonna", "wanna", "gotta",
        "desktop", "documents", "github",
        "left", "right", "start", "stop", "open", "close",
        "show", "hide", "move", "remove", "delete", "create",
        "best", "better", "worse", "less", "more",
    }
    for w, cnt in word_counts.most_common(150):
        if (cnt >= 4 and len(w) >= 4 and w not in TOPIC_WORDS
                and w not in topic_counts and w not in TOPIC_NOISE
                and w not in STOP_WORDS):
            topic_counts[w] = cnt
    top_topics = sorted(topic_counts.items(), key=lambda x: -x[1])[:10]

    # ── Hour-by-hour heatmap data ────────────────────────────────────────
    hour_data = [hour_counts.get(h, 0) for h in range(24)]

    result = {
        "total_prompts": total_prompts,
        "total_chars": total_chars,
        "avg_length": avg_length,
        "days_active": days_active,
        "prompts_per_day": prompts_per_day,
        "first_date": first_date.strftime("%b %d, %Y"),
        "last_date": last_date.strftime("%b %d, %Y"),
        "peak_hour": peak_hour_fmt,
        "late_night": late_night,
        "weekend_pct": weekend_pct,
        "busiest_day": busiest_day[0],
        "busiest_day_count": busiest_day[1],
        "fix_count": fix_count,
        "bug_count": bug_count,
        "why_count": why_count,
        "doesnt_work": doesnt_work,
        "help_count": help_count,
        "error_count": error_count,
        "please_count": please_count,
        "thanks_count": thanks_count,
        "sorry_count": sorry_count,
        "changed_mind": changed_mind,
        "actually_count": actually_count,
        "bro_count": bro_count,
        "exclamation_count": exclamation_count,
        "question_count": question_count,
        "caps_prompts": caps_prompts,
        "refactor_count": refactor_count,
        "too_much": too_much,
        "good_job": good_job,
        "bad_job": bad_job,
        "swear_count": swear_count,
        "long_prompts": long_prompts,
        "short_prompts": short_prompts,
        "one_worders": one_worders,
        "longest_words": longest_words,
        "shortest": shortest[:80],
        "most_repeated": most_repeated,
        "top_topics": top_topics,
        "top_projects": top_projects,
        "cloud_words": cloud_words,
        "hour_data": hour_data,
        "heatmap_weeks": heatmap_weeks,
        "max_streak": max_streak,
        "day_of_week_counts": [day_counts.get(d, 0) for d in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]],
        "longest_prompt": longest[:200],
        "sessions": sessions,
        "avg_session_min": avg_session_min,
        "prompts_per_session": prompts_per_session,
        "followup_rate": followup_rate,
        "prompt_categories": prompt_categories,
        "vocab_diversity": vocab_diversity,
        "has_config": has_config,
        "claude_count": claude_count,
        "codex_count": codex_count,
    }

    # ── Token/cost estimation ──────────────────────────────────────────
    # Rough estimate: avg prompt ~30 tokens input, assume ~200 tokens output per exchange
    # Claude Sonnet: ~$3/M input, ~$15/M output. Codex: ~$2.50/M input, ~$10/M output
    est_input_tokens = total_chars // 4  # ~4 chars per token
    est_output_tokens = est_input_tokens * 6  # AI typically outputs ~6x more than user types
    est_cost_claude = (est_input_tokens * 3 + est_output_tokens * 15) / 1_000_000
    est_cost_codex = (est_input_tokens * 2.5 + est_output_tokens * 10) / 1_000_000
    est_cost = round(est_cost_claude + est_cost_codex, 2)

    result["est_input_tokens"] = est_input_tokens
    result["est_output_tokens"] = est_output_tokens
    result["est_cost"] = est_cost

    # ── Leaderboard payload (anonymous, no PII) ─────────────────────
    import hashlib
    machine_id = hashlib.sha256(
        (str(Path.home()) + os.environ.get("USER", "")).encode()
    ).hexdigest()[:16]

    result["leaderboard_payload"] = {
        "id": machine_id,
        "prompts": total_prompts,
        "days_active": days_active,
        "daily_avg": prompts_per_day,
        "streak": max_streak,
        "peak_hour": peak_hour,
        "peak_day": busiest_day[0],
        "late_night_pct": round(late_night / total_prompts * 100, 1) if total_prompts else 0,
        "fix_rate": round((fix_count + doesnt_work) / total_prompts * 100, 1) if total_prompts else 0,
        "bro_count": bro_count,
        "please_count": please_count,
        "thanks_count": thanks_count,
        "swear_count": swear_count,
        "error_count": error_count,
        "question_pct": round(question_count / total_prompts * 100, 1) if total_prompts else 0,
        "one_word_pct": round(one_worders / total_prompts * 100, 1) if total_prompts else 0,
        "archetype": "",  # filled after archetype calc
        "tools": "",      # filled in main()
    }

    result["archetype"] = determine_archetype(result)
    result["leaderboard_payload"]["archetype"] = result["archetype"]["name"]
    result["tips"] = generate_tips(result)
    return result


def determine_archetype(data):
    """Pattern-based archetype using combinations of signals, not single counts."""
    total = data["total_prompts"]
    if total == 0:
        return {"name": "the ghost", "desc": "you haven't talked to your AI yet. suspicious."}

    # Compute rates (0-1) so patterns work regardless of total volume
    late_rate = data["late_night"] / total
    fix_rate = (data["fix_count"] + data["doesnt_work"]) / total
    why_rate = data["why_count"] / total
    question_rate = data["question_count"] / total
    polite_rate = (data["please_count"] + data["thanks_count"] + data["sorry_count"]) / total
    swear_rate = data["swear_count"] / total
    bro_rate = data["bro_count"] / total
    change_rate = data["changed_mind"] / total
    short_rate = data["one_worders"] / total
    long_rate = data["long_prompts"] / total
    error_rate = data["error_count"] / total
    dow = data.get("day_of_week_counts", [0]*7)
    weekend = dow[5] + dow[6]
    weekday_total = sum(dow[:5])
    weekend_rate = weekend / total if total else 0
    evening_count = sum(1 for h, c in enumerate(data.get("hour_data", [])) for _ in range(c) if h >= 20 or h < 5)
    evening_rate = evening_count / total if total else 0

    # Each pattern: (score, title, desc)
    # Score = how strongly this pattern matches (higher = stronger match)
    patterns = []

    # No social life: codes evenings + weekends heavily
    if evening_rate > 0.15 or (weekend_rate > 0.4 and late_rate > 0.05):
        score = (evening_rate + weekend_rate + late_rate) * 100
        weekend_evening = data["late_night"] + weekend
        patterns.append((score,
            "no social life detected",
            f"you code on weekends ({weekend} prompts) and evenings ({data['late_night']} after midnight). "
            f"your github is green but your social calendar is empty."))

    # Emotionally attached: bro/dude + polite + long prompts (treats AI like a friend)
    if bro_rate > 0.05 or (bro_rate > 0.02 and polite_rate > 0.01):
        score = (bro_rate * 200) + (polite_rate * 50)
        patterns.append((score,
            "emotionally attached to an LLM",
            f"you called your AI 'bro' {data['bro_count']} times and said please {data['please_count']} times. "
            f"it's not going to invite you to its birthday."))

    # Rage debugger: swearing + fixing + errors
    if swear_rate > 0.01 or (fix_rate > 0.03 and error_rate > 0.02):
        score = (swear_rate * 300) + (fix_rate * 120) + (error_rate * 100)
        broken = data["fix_count"] + data["doesnt_work"] + data["error_count"]
        patterns.append((score,
            "losing an argument with autocomplete",
            f"{broken} prompts about things being broken, {data['swear_count']} swear words. "
            f"you're debugging the AI that was supposed to debug your code."))

    # Learning in production: high questions + high errors
    if question_rate > 0.3 and (error_rate > 0.01 or fix_rate > 0.02):
        score = (question_rate * 60) + (error_rate * 80)
        patterns.append((score,
            "learning in production",
            f"{data['question_count']} questions and {data['error_count']} errors. "
            f"you're figuring it out as you go. your AI is your stackoverflow now."))

    # The PM: changes mind + long prompts + lots of direction
    if change_rate > 0.005 or (long_rate > 0.08 and change_rate > 0.002):
        score = (change_rate * 300) + (long_rate * 30)
        patterns.append((score,
            "the PM nobody asked for",
            f"you changed direction {data['changed_mind']} times and wrote {data['long_prompts']} essay-length prompts. "
            f"even your AI doesn't know what you're building anymore."))

    # Vending machine: lots of short prompts + high volume
    if short_rate > 0.12 and data["prompts_per_day"] > 10:
        score = (short_rate * 80) + (data["prompts_per_day"] * 2)
        patterns.append((score,
            "treats AI like a vending machine",
            f"{round(short_rate*100)}% of your prompts are 2 words or less at {data['prompts_per_day']}/day. "
            f"insert prompt, receive code. no context, no small talk."))

    # Replaced google: mostly questions, few statements
    if question_rate > 0.35:
        score = question_rate * 40
        patterns.append((score,
            "replaced google with something more expensive",
            f"{data['question_count']} of your {total} prompts were questions. "
            f"you replaced your entire learning process with vibes."))

    # Polite coder: says please/thanks a lot
    if polite_rate > 0.03:
        polite_total = data["please_count"] + data["thanks_count"] + data["sorry_count"]
        score = polite_rate * 300
        patterns.append((score,
            "saying please to a for-loop",
            f"you said please/thanks/sorry {polite_total} times in {total} prompts. "
            f"it does not have feelings. you might have too many."))

    # The nicest insomniac: polite + late night/weekend
    if polite_rate > 0.02 and (late_rate > 0.05 or weekend_rate > 0.35):
        polite_total = data["please_count"] + data["thanks_count"] + data["sorry_count"]
        score = (polite_rate * 200) + (late_rate * 80) + (weekend_rate * 40)
        patterns.append((score,
            "saying please to a for-loop at 2am",
            f"you said please/thanks {polite_total} times, often late at night. "
            f"it does not have feelings. you might have too many."))

    # Perfectionist: refactors + "too much" + mind changes
    if data["refactor_count"] > 3 or (data["too_much"] > 3 and change_rate > 0.005):
        score = (data["refactor_count"] * 5) + (data["too_much"] * 4) + (change_rate * 100)
        patterns.append((score,
            "rewriting hello world for the 5th time",
            f"{data['refactor_count']} refactors{', said too much ' + str(data['too_much']) + ' times' if data['too_much'] > 0 else ''}. "
            f"the code wasn't bad. you just got bored."))

    # The therapist: very long prompts dominate
    if long_rate > 0.1:
        score = long_rate * 60
        patterns.append((score,
            "the therapist who codes",
            f"{data['long_prompts']} of your prompts were essay-length. "
            f"your AI knows more about your project than your team does."))

    # Power user: high volume + streaks + multiple tools
    streak = data.get("max_streak", 0)
    tools = data.get("tools", [])
    if data["prompts_per_day"] > 15 and streak > 4:
        score = (data["prompts_per_day"] * 1.5) + (streak * 3)
        patterns.append((score,
            "your AI has more screen time than your phone",
            f"{data['prompts_per_day']} prompts/day, {streak}-day streak"
            f"{', across ' + ' + '.join(tools) if len(tools) > 1 else ''}. "
            f"you talk to your AI more than most people talk to their coworkers."))

    if not patterns:
        return {"name": "the quiet one", "desc": f"{total} prompts but no strong patterns. you're balanced. or boring."}

    # Pick highest scoring pattern
    patterns.sort(key=lambda x: -x[0])
    _, name, desc = patterns[0]
    return {"name": name, "desc": desc}


def generate_tips(data):
    """Generate personalized, data-driven tips. Each tip has a trigger condition,
    severity score based on how far the user deviates, and a cited source."""
    tips = []
    total = data["total_prompts"]
    if total == 0:
        return tips

    avg_len = data["avg_length"]
    fix_total = data["fix_count"] + data["doesnt_work"]
    fix_rate = fix_total / total
    why_rate = data["why_count"] / total
    change_rate = data["changed_mind"] / total
    late_rate = data["late_night"] / total
    error_rate = data["error_count"] / total
    one_word_rate = data["one_worders"] / total
    polite = data["please_count"] + data["thanks_count"] + data["sorry_count"]
    polite_rate = polite / total
    question_rate = data["question_count"] / total
    streak = data.get("max_streak", 0)
    dow = data.get("day_of_week_counts", [0]*7)
    weekend = dow[5] + dow[6]
    weekday = sum(dow[:5])
    swear_rate = data["swear_count"] / total
    long_rate = data["long_prompts"] / total

    def tip(score, title, body, category, source):
        if score > 0:
            tips.append({"score": score, "title": title, "body": body,
                         "category": category, "source": source})

    # ── PROMPTING ────────────────────────────────────────────────────

    if fix_rate > 0.03:
        tip(fix_rate * 100,
            "Describe the goal, not the problem",
            f"You said \"fix\" or \"doesn't work\" {fix_total} times ({fix_rate:.0%} of prompts). "
            f"Prompts that describe desired behavior (\"this should return X when given Y\") "
            f"outperform problem descriptions (\"fix this bug\") by producing more targeted solutions.",
            "prompting",
            "Anthropic Prompt Engineering Guide — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-direct")

    if avg_len < 40:
        tip(max(0, 40 - avg_len),
            "Add more context to your prompts",
            f"Your average prompt is {avg_len} characters. Prompts with context about what you're "
            f"building, the tech stack, and expected behavior produce significantly better output. "
            f"Even 1-2 sentences of context helps the model avoid assumptions.",
            "prompting",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/give-claude-a-role")

    if avg_len > 500:
        tip((avg_len - 500) / 10,
            "Break complex prompts into steps",
            f"Your average prompt is {avg_len} characters. Long prompts can dilute the key instruction. "
            f"Try chain-of-thought: first outline the plan, then implement step by step. "
            f"This gives the model clearer focus at each stage.",
            "prompting",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/chain-prompts")

    if why_rate > 0.05:
        tip(why_rate * 80,
            "Replace 'why' with 'explain step by step'",
            f"You asked \"why\" {data['why_count']} times. \"Why doesn't this work?\" is ambiguous. "
            f"\"Explain step by step what this code does and where it diverges from the expected output\" "
            f"gives the model a concrete task. Specific instructions consistently outperform open-ended ones.",
            "prompting",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-direct")

    if error_rate > 0.02:
        tip(error_rate * 80,
            "Paste the full error, not a summary",
            f"You mentioned errors {data['error_count']} times. AI models can parse full stack traces "
            f"faster than you can describe them. Copy-paste the complete error — including file paths "
            f"and line numbers — for the most accurate fix.",
            "prompting",
            "Anthropic Claude Code Best Practices — docs.anthropic.com/en/docs/claude-code/best-practices")

    if one_word_rate > 0.15:
        pct = round(one_word_rate * 100)
        tip(one_word_rate * 40,
            "Short prompts cost more than they save",
            f"{pct}% of your prompts are 2 words or less. Vague prompts like \"fix\" or \"continue\" "
            f"often need follow-ups, wasting round-trips. One detailed prompt typically beats three vague ones. "
            f"Include what, why, and constraints upfront.",
            "prompting",
            "OpenAI Codex Prompting Guide — developers.openai.com/codex/prompting-guide")

    if question_rate > 0.4:
        tip(question_rate * 30,
            "Turn questions into tasks",
            f"{round(question_rate * 100)}% of your prompts are questions. Questions like \"Can you...?\" "
            f"or \"How do I...?\" add uncertainty. Direct instructions (\"Write a function that...\") "
            f"get more actionable output. Save questions for when you genuinely need explanation.",
            "prompting",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-direct")

    if long_rate > 0.1:
        tip(long_rate * 30,
            "Front-load the important part",
            f"{data['long_prompts']} of your prompts were 500+ characters. When writing long prompts, "
            f"put your main instruction in the first sentence. Models weight earlier text more heavily. "
            f"Context and details should follow the core ask, not bury it.",
            "prompting",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-direct")

    # ── WORKFLOW ─────────────────────────────────────────────────────

    if change_rate > 0.01:
        tip(change_rate * 200,
            "Plan before you prompt",
            f"You changed direction {data['changed_mind']} times. Each reversal wastes a full round-trip. "
            f"Spend 30 seconds writing your goal and constraints before hitting enter. "
            f"A clear brief saves more time than it takes to write.",
            "workflow",
            "Anthropic Claude Code Tips — docs.anthropic.com/en/docs/claude-code/best-practices")

    if data["refactor_count"] > 5:
        tip(data["refactor_count"] * 2,
            "Describe architecture upfront",
            f"You asked to refactor {data['refactor_count']} times. Each refactor means the first output "
            f"missed your intent. Front-loading architecture (\"module with X interface, Y pattern\") "
            f"gets closer on the first pass. Use CLAUDE.md or AGENTS.md to persist project conventions.",
            "workflow",
            "Anthropic Claude Code CLAUDE.md — docs.anthropic.com/en/docs/claude-code/memory")

    if streak < 3 and data["days_active"] > 14:
        tip(10,
            "Build a streak for better context",
            f"Your longest streak is {streak} days. Consistent daily use helps your AI build "
            f"better mental models of your project. Claude Code's memory system learns from "
            f"repeated interactions — sporadic use means it re-learns context each time.",
            "workflow",
            "Anthropic Claude Code Memory — docs.anthropic.com/en/docs/claude-code/memory")

    if total > 200 and data["top_projects"] and len(data["top_projects"]) >= 3:
        top_proj = data["top_projects"][0]
        tip(12,
            f"You're spread across {len(data['top_projects'])}+ projects",
            f"Your top project ({top_proj[0]}) has {top_proj[1]} prompts but you're active in "
            f"{len(data['top_projects'])} projects. Context-switching between projects is expensive for AI too — "
            f"it needs to rebuild mental context each switch. Consider batching work per project.",
            "workflow",
            "Cal Newport, Deep Work — context switching research")

    if total > 100 and data.get("most_repeated"):
        top_repeat = data["most_repeated"][0]
        if top_repeat[1] > 5 and not top_repeat[0].startswith("/"):
            tip(top_repeat[1] * 2,
                "Automate your repeated prompts",
                f"You've sent \"{top_repeat[0][:40]}\" {top_repeat[1]} times. Frequently repeated prompts "
                f"can be saved as slash commands (Claude Code) or shortcuts. "
                f"Put common instructions in your CLAUDE.md or AGENTS.md file instead of typing them each time.",
                "workflow",
                "Anthropic Claude Code Custom Commands — docs.anthropic.com/en/docs/claude-code/slash-commands")

    # ── TIMING ───────────────────────────────────────────────────────

    if late_rate > 0.1:
        tip(late_rate * 60,
            f"Your peak hour is {data['peak_hour']} — use it",
            f"{data['late_night']} prompts ({late_rate:.0%}) were sent between midnight and 5am. "
            f"A Microsoft study found code written late at night has significantly higher defect density. "
            f"Your most active hour is {data['peak_hour']} — schedule complex AI-assisted work then.",
            "timing",
            "Microsoft Research — 'The Influence of Time on Software Quality' (Sillitti et al.)")

    if total > 50 and weekend > weekday * 0.6:
        tip((weekend / max(weekday, 1)) * 20,
            "You're a weekend coder",
            f"You send {weekend} prompts on weekends vs {weekday} on weekdays. "
            f"If this is a work project, time-boxing AI sessions during the week protects your rest. "
            f"If it's personal projects — that's healthy, but watch for burnout.",
            "timing",
            "Research on developer burnout — IEEE Software 'Unhappiness of Software Developers'")

    if dow and total > 50:
        days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        min_day_idx = dow.index(min(dow))
        max_day_idx = dow.index(max(dow))
        ratio = max(dow) / max(min(dow), 1)
        if ratio > 3:
            tip(ratio * 3,
                f"Your {days_list[max_day_idx]}s are {round(ratio)}x busier than {days_list[min_day_idx]}s",
                f"You send {max(dow)} prompts on {days_list[max_day_idx]}s but only {min(dow)} on "
                f"{days_list[min_day_idx]}s. Highly uneven workloads correlate with lower satisfaction. "
                f"Consider spreading AI-assisted work more evenly across the week.",
                "timing",
                "Flow research — Csikszentmihalyi on consistent creative practice")

    # ── STYLE & COMMUNICATION ────────────────────────────────────────

    if polite_rate < 0.005 and total > 100:
        tip(15,
            "Politeness is a prompting technique",
            f"You said please/thanks {polite} times in {total} prompts. "
            f"Anthropic's research shows that polite, well-structured prompts produce more thoughtful responses. "
            f"It's not about manners — framing requests respectfully signals to the model that you want careful output.",
            "style",
            "Anthropic Research — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-direct")

    if polite_rate > 0.1:
        tip(polite_rate * 20,
            "You're very polite — that's effective",
            f"You said please/thanks/sorry {polite} times. This isn't wasted — "
            f"research shows polite prompts correlate with more careful, detailed responses. "
            f"Just make sure politeness doesn't replace clarity: \"Please write X\" is better than just \"Please help\".",
            "style",
            "Anthropic Prompt Engineering — docs.anthropic.com/en/docs/build-with-claude/prompt-engineering")

    if swear_rate > 0.03:
        tip(swear_rate * 60,
            "Frustration in prompts can reduce quality",
            f"You expressed frustration {data['swear_count']} times. While venting is human, "
            f"frustrated prompts tend to be vague (\"this is broken, fix it\"). "
            f"When stuck, try describing the expected vs actual behavior calmly — it gets better results.",
            "style",
            "Cognitive load theory — frustration impairs clear communication (Sweller, 1988)")

    if data["bro_count"] > 20:
        tip(8,
            "Your casual style works — keep the clarity",
            f"You've used casual language (bro/dude) {data['bro_count']} times. "
            f"Casual prompting is fine — models handle informal language well. "
            f"Just ensure the core instruction is clear. \"Bro, refactor this\" works if the scope is obvious.",
            "style",
            "Anthropic — models are robust to tone variation in prompts")

    # ── META / TOOLING ───────────────────────────────────────────────

    if total > 500:
        tip(8,
            "Create a CLAUDE.md / AGENTS.md file",
            f"With {total} prompts, you have clear patterns and preferences. "
            f"Capture them in a CLAUDE.md (Claude) or AGENTS.md (Codex) file — project conventions, "
            f"preferred patterns, tech stack — so your AI starts every session with your context.",
            "tooling",
            "Anthropic Claude Code Memory — docs.anthropic.com/en/docs/claude-code/memory")

    if total > 200 and data.get("tools") and len(data["tools"]) > 1:
        tip(10,
            "You use multiple AI tools — sync your preferences",
            f"You're active on {' and '.join(data['tools'])}. Keep your coding conventions consistent "
            f"by maintaining both CLAUDE.md and AGENTS.md in your projects. "
            f"Same rules, same patterns — regardless of which AI you're talking to.",
            "tooling",
            "Best practice for multi-tool AI workflows")

    if data["days_active"] > 30 and total > 300:
        tip(6,
            "Run this tool monthly to track your growth",
            f"You've been coding with AI for {data['days_active']} days. Your prompting style evolves. "
            f"Running this analysis monthly lets you see if your fix-rate is dropping, "
            f"your prompts are getting more specific, or new patterns are emerging.",
            "tooling",
            "Reflective practice — Schön, 'The Reflective Practitioner' (1983)")

    # Sort by score (most relevant first), return top 5
    tips.sort(key=lambda t: -t["score"])
    return tips[:5]


# ─── Terminal Render ──────────────────────────────────────────────────────────

def render_terminal(data):
    tw = min(shutil.get_terminal_size().columns, 80)
    w = tw - 4

    def line(text="", align="left"):
        plain = re.sub(r"\033\[[^m]*m", "", text)
        pad = w - len(plain)
        if pad < 0: pad = 0
        if align == "center":
            l = pad // 2
            r = pad - l
            print(f"  {orange('│')}{' ' * l}{text}{' ' * r}{orange('│')}")
        else:
            print(f"  {orange('│')} {text}{' ' * max(0, pad - 1)}{orange('│')}")

    def sep():
        print(f"  {orange('├' + '─' * w + '┤')}")

    def empty():
        line()

    print()
    print(f"  {orange('╭' + '─' * w + '╮')}")
    empty()

    # Header
    line(bold(orange("OPENBOOK")), "center")
    line(dim("what your AI knows about you"), "center")
    empty()
    sep()

    # Big stats
    empty()
    stat1 = f"{orange(str(data['total_prompts']))} prompts"
    stat2 = f"{tan(str(data['days_active']))} days"
    stat3 = f"{cream(str(data['prompts_per_day']))}/day"
    stat4 = f"peak: {cream(data['busiest_day'] + 's')}"
    stat5 = f"{orange(str(data.get('max_streak', 0)))} day streak"
    stat6 = f"~{cream('$' + str(data.get('est_cost', 0)))}"
    line(f"{stat1}   {stat2}   {stat3}   {stat4}   {stat5}", "center")
    line(f"est. cost: {stat6}   tokens: {dim(str(data.get('est_input_tokens', 0)) + ' in / ' + str(data.get('est_output_tokens', 0)) + ' out')}", "center")
    line(dim(f"{data['first_date']} → {data['last_date']}"), "center")
    empty()
    sep()

    # Archetype
    empty()
    line(f"  You are... {bold(cream(data['archetype']['name']))}", "center")
    line(dim(data['archetype']['desc']), "center")
    empty()
    sep()

    # Roast section
    empty()
    line(orange("THE RECEIPTS"))
    empty()

    roasts = []
    if data["fix_count"]:
        roasts.append(f'You said {cream("fix")} {orange(str(data["fix_count"]))} times')
    if data["doesnt_work"]:
        dw = "doesn" + "'" + "t work"
        roasts.append(f'You said {cream(dw)} {orange(str(data["doesnt_work"]))} times')
    if data["why_count"]:
        roasts.append(f'You asked {cream("why")} {orange(str(data["why_count"]))} times')
    if data["please_count"]:
        roasts.append(f'You said {cream("please")} to an AI {orange(str(data["please_count"]))} times')
    if data["sorry_count"]:
        roasts.append(f'You {cream("apologized")} to your AI {orange(str(data["sorry_count"]))} times')
    if data["thanks_count"]:
        roasts.append(f'You said {cream("thanks")} {orange(str(data["thanks_count"]))} times. It cannot feel gratitude')
    if data["bro_count"]:
        roasts.append(f'You called your AI {cream("bro/dude")} {orange(str(data["bro_count"]))} times')
    if data["swear_count"]:
        roasts.append(f'You swore at your AI {orange(str(data["swear_count"]))} times')
    if data["changed_mind"]:
        roasts.append(f'You changed your mind {orange(str(data["changed_mind"]))} times')
    if data["late_night"]:
        roasts.append(f'{orange(str(data["late_night"]))} prompts sent between {cream("midnight and 5am")}')
    if data["refactor_count"]:
        roasts.append(f'You asked to {cream("refactor/rewrite")} {orange(str(data["refactor_count"]))} times')
    if data["too_much"]:
        roasts.append(f'You said {cream("too much/too many")} {orange(str(data["too_much"]))} times')
    if data["one_worders"]:
        pct = round(data["one_worders"] / data["total_prompts"] * 100)
        roasts.append(f'{orange(str(pct))}% of your prompts were {cream("2 words or less")}')
    if data["longest_words"]:
        roasts.append(f'Your longest prompt was {orange(str(data["longest_words"]))} words. Chill.')

    for r in roasts[:12]:
        line(f"{dim('•')} {r}")

    empty()

    # Most repeated
    if data["most_repeated"]:
        sep()
        empty()
        line(orange("BROKEN RECORD AWARD"))
        empty()
        for prompt_text, count in data["most_repeated"]:
            display = prompt_text[:50] + "..." if len(prompt_text) > 50 else prompt_text
            line(f'{orange(str(count))}x  {cream(chr(34) + display + chr(34))}')
        empty()

    # Topics (what you actually talk about)
    if data.get("top_topics"):
        sep()
        empty()
        line(orange("YOUR OBSESSIONS"))
        empty()
        max_t = data["top_topics"][0][1] if data["top_topics"] else 1
        bar_max = w - 30
        for topic, count in data["top_topics"]:
            bar_len = max(1, int((count / max_t) * bar_max))
            bar = "█" * bar_len
            emp = "░" * (bar_max - bar_len)
            name = topic[:18].ljust(18)
            line(f" {tan(name)} {orange(bar)}{dimbar(emp)} {dim(str(count))}")
        empty()

    # Top projects
    if data["top_projects"]:
        sep()
        empty()
        line(orange("PROJECTS"))
        empty()
        max_p = data["top_projects"][0][1] if data["top_projects"] else 1
        bar_max = w - 30
        for proj, count in data["top_projects"]:
            bar_len = max(1, int((count / max_p) * bar_max))
            bar = "█" * bar_len
            emp = "░" * (bar_max - bar_len)
            name = proj[:18].ljust(18)
            line(f" {tan(name)} {orange(bar)}{dimbar(emp)} {dim(str(count))}")
        empty()

    # Word cloud preview
    if data["cloud_words"]:
        sep()
        empty()
        line(orange("TOP WORDS"))
        empty()
        words = data["cloud_words"][:25]
        max_s = max(w_["count"] for w_ in words)
        ln = ""
        ln_len = 0
        max_inner = w - 2
        for wd in words:
            ratio = wd["count"] / max_s
            if ratio > 0.6:
                styled = bold(cream(wd["text"].upper()))
                dlen = len(wd["text"])
            elif ratio > 0.3:
                styled = orange(wd["text"])
                dlen = len(wd["text"])
            else:
                styled = dim(wd["text"])
                dlen = len(wd["text"])

            if ln_len + dlen + 2 > max_inner:
                line(ln)
                ln = styled
                ln_len = dlen
            else:
                if ln:
                    ln += "  " + styled
                    ln_len += 2 + dlen
                else:
                    ln = styled
                    ln_len = dlen
        if ln:
            line(ln)
        empty()

    # Hour heatmap
    sep()
    empty()
    line(orange("WHEN YOU CODE"))
    empty()
    max_h = max(data["hour_data"]) if data["hour_data"] else 1
    # Show as a single-line sparkline
    blocks = " ▁▂▃▄▅▆▇█"
    spark = ""
    for h_count in data["hour_data"]:
        idx = int((h_count / max(max_h, 1)) * 8)
        spark += blocks[idx]
    line(f"  {dim('0h')}  {orange(spark)}  {dim('23h')}", "center")
    line(f"  Peak: {cream(data['peak_hour'])}   Busiest: {cream(data['busiest_day']+'s')}", "center")
    empty()

    # Tips
    tips = data.get("tips", [])
    if tips:
        sep()
        empty()
        line(orange("TIPS FOR YOU"))
        empty()
        for i, tip in enumerate(tips):
            line(f"{cream(str(i+1) + '.')} {bold(cream(tip['title']))}")
            # Word wrap the body
            body = tip["body"]
            words_line = ""
            wl = 0
            max_body = w - 6
            for word in body.split():
                if wl + len(word) + 1 > max_body:
                    line(f"   {dim(words_line)}")
                    words_line = word
                    wl = len(word)
                else:
                    words_line = (words_line + " " + word).strip()
                    wl += len(word) + 1
            if words_line:
                line(f"   {dim(words_line)}")
            empty()

    # Footer
    sep()
    empty()
    line(dim("openbook - what your AI knows about you"), "center")
    empty()
    print(f"  {orange('╰' + '─' * w + '╯')}")
    print()


# ─── HTML Template ───────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>openbook</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{--o:#D97757;--ol:#E8956F;--od:#A35A3A;--tan:#C4A882;--cr:#F5E6D3;--bg:#1a1410;--card:#231e18;--bdr:#3a3028;--t:#e8ddd0;--td:#9a8b7a;--tb:#fff8f0}
body.codex{--o:#10A37F;--ol:#74AA9C;--od:#0B7A5E;--tan:#7ECBB4;--cr:#D4F5EB;--bg:#0d1410;--card:#131e18;--bdr:#1e3028;--t:#d0e8dd;--td:#7a9a8b;--tb:#f0fff8}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--t);padding:32px 20px;display:flex;flex-direction:column;align-items:center;background-image:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(217,119,87,.12),transparent)}
.wrap{max-width:720px;width:100%}
.card{background:var(--card);border:1px solid var(--bdr);border-radius:20px;padding:36px;position:relative;overflow:hidden;margin-bottom:24px}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--o),transparent)}
.sec{font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--o);margin-bottom:14px}

/* Header */
.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px}
.hdr h1{font-size:2rem;font-weight:900;letter-spacing:-.03em;background:linear-gradient(135deg,var(--o),var(--tan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hdr .meta{font-size:.65rem;color:var(--td);font-family:'JetBrains Mono',monospace;text-align:right}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px 20px;margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid var(--bdr)}
.st{text-align:center}
.st .v{font-size:1.1rem;font-weight:800;color:var(--o);font-family:'JetBrains Mono',monospace;white-space:nowrap}
.st .l{font-size:.58rem;text-transform:uppercase;letter-spacing:.06em;color:var(--td);margin-top:2px}

/* Archetype */
.arch{text-align:center;padding:20px 0 24px;border-bottom:1px solid var(--bdr);margin-bottom:24px}
.arch-pre{font-size:.75rem;color:var(--td);margin-bottom:4px}
.arch-name{font-size:1.8rem;font-weight:900;color:var(--cr)}
.arch-desc{font-size:.82rem;color:var(--td);font-style:italic;margin-top:6px}

/* Receipts */
.receipts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:24px}
.rc{background:rgba(217,119,87,.06);border:1px solid rgba(217,119,87,.1);border-radius:10px;padding:10px 12px;text-align:center;transition:all .2s;cursor:default}
.rc:hover{background:rgba(217,119,87,.12);border-color:var(--o);transform:scale(1.03)}
.rc .n{font-size:1.3rem;font-weight:800;color:var(--o);font-family:'JetBrains Mono',monospace}
.rc .d{font-size:.68rem;color:var(--td);margin-top:2px;line-height:1.3}
.rc .d b{color:var(--cr);font-weight:600}

/* Two col */
.row{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}

/* Heatmap */
.heatmap{display:flex;gap:2px;overflow-x:auto}
.hm-col{display:flex;flex-direction:column;gap:2px}
.hm-cell{width:11px;height:11px;border-radius:2px;transition:all .15s;cursor:default}
.hm-cell:hover{transform:scale(1.5);outline:1px solid var(--o);z-index:1}
.hm-labels{display:flex;flex-direction:column;gap:2px;margin-right:4px}
.hm-labels span{height:11px;font-size:.5rem;color:var(--td);font-family:'JetBrains Mono',monospace;line-height:11px;width:24px;text-align:right}
.hm-months{display:flex;margin-left:28px;margin-top:6px}
.hm-months span{font-size:.55rem;color:var(--td);font-family:'JetBrains Mono',monospace}

/* Hour chart */
.hours{display:flex;align-items:flex-end;gap:3px;height:80px}
.hbar-wrap{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.hbar{width:100%;border-radius:3px 3px 0 0;background:linear-gradient(180deg,var(--o),var(--od));min-height:2px;transition:all .2s;cursor:default}
.hbar:hover{background:var(--ol);transform:scaleY(1.05)}
.hlabels{display:flex;gap:3px;margin-top:6px}
.hlabels span{flex:1;text-align:center;font-size:.55rem;color:var(--td);font-family:'JetBrains Mono',monospace}

/* Day of week chart */
.dow{display:flex;gap:6px;height:80px}
.dow-bar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}
.dow-fill{width:100%;border-radius:4px 4px 0 0;background:linear-gradient(180deg,var(--o),var(--od));transition:all .2s;cursor:default;min-height:3px}
.dow-fill:hover{background:var(--ol)}
.dow-label{font-size:.55rem;color:var(--td);font-family:'JetBrains Mono',monospace;margin-top:6px}

/* Word cloud */
.cloud{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:6px 14px;padding:16px;min-height:180px}
.cloud span{font-weight:600;cursor:default;transition:all .3s;white-space:nowrap;line-height:1.3}
.cloud span:hover{color:var(--tb)!important;text-shadow:0 0 20px var(--ol);transform:scale(1.15)}

/* Topics */
.topic{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.topic .name{font-size:.78rem;color:var(--t);width:80px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topic .bar-bg{flex:1;height:5px;background:rgba(196,168,130,.12);border-radius:3px;overflow:hidden}
.topic .bar-fill{height:100%;background:linear-gradient(90deg,var(--od),var(--o));border-radius:3px;transition:all .3s}
.topic:hover .bar-fill{background:var(--ol)}
.topic .cnt{font-size:.68rem;color:var(--td);font-family:'JetBrains Mono',monospace;width:28px}

/* Longest prompt */
.prompt-reveal{background:rgba(196,168,130,.05);border:1px solid var(--bdr);border-radius:12px;padding:16px;font-size:.8rem;color:var(--td);line-height:1.5;font-style:italic;position:relative}
.prompt-reveal b{color:var(--cr);font-style:normal}

/* Repeated */
.repeated{display:flex;gap:12px;align-items:center;margin-bottom:8px;padding:8px 12px;background:rgba(196,168,130,.04);border-radius:8px}
.repeated:hover{background:rgba(196,168,130,.08)}
.rp-count{font-size:1.1rem;font-weight:800;color:var(--o);font-family:'JetBrains Mono',monospace;min-width:36px}
.rp-text{font-size:.8rem;color:var(--cr);font-style:italic}

/* Projects */
.proj{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.proj .name{font-size:.78rem;color:var(--t);width:100px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.proj .bar-bg{flex:1;height:5px;background:rgba(196,168,130,.12);border-radius:3px;overflow:hidden}
.proj .bar-fill{height:100%;background:linear-gradient(90deg,var(--od),var(--o));border-radius:3px}
.proj .cnt{font-size:.68rem;color:var(--td);font-family:'JetBrains Mono',monospace;width:36px}

/* Footer / share */
.ftr{text-align:center;padding:16px;font-size:.65rem;color:var(--td)}
.share-bar{text-align:center;margin-bottom:32px}
.btn{border:none;padding:12px 28px;border-radius:12px;font-size:.85rem;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;transition:all .2s;margin:0 6px}
.btn:hover{transform:scale(1.03)}
.btn-dl{background:var(--o);color:#fff}
.btn-dl:hover{background:var(--ol)}
.btn-x{background:#000;color:#fff;border:1px solid #333}
.btn-x:hover{background:#1a1a1a}
.btn-lb{background:linear-gradient(135deg,var(--o),var(--od))}
.btn-lb:hover{background:var(--ol)}
.share-hint{font-size:.7rem;color:var(--td);margin-top:10px}

/* Tips */
.tip-item{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--bdr)}
.tip-item:last-child{border-bottom:none}
.tip-num{font-size:1.4rem;font-weight:800;color:var(--o);font-family:'JetBrains Mono',monospace;min-width:32px;line-height:1}
.tip-title{font-size:.9rem;font-weight:700;color:var(--cr);margin-bottom:6px}
.tip-text{font-size:.8rem;color:var(--td);line-height:1.6}
.tip-meta{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
.tip-cat{font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;color:var(--o);background:rgba(217,119,87,.1);padding:3px 8px;border-radius:4px}
.tip-src{font-size:.6rem;color:var(--td);font-style:italic}

/* Theme toggle */
.theme-toggle{position:fixed;top:16px;right:16px;display:flex;gap:6px;z-index:10}
.theme-btn{width:28px;height:28px;border-radius:8px;border:2px solid transparent;cursor:pointer;transition:all .2s;opacity:.5}
.theme-btn:hover{opacity:1;transform:scale(1.1)}
.theme-btn.active{opacity:1;border-color:var(--t)}
.theme-btn.claude{background:#D97757}
.theme-btn.codex{background:#10A37F}
.theme-btn.claude{background:#D97757}

/* Tooltip */
.tt{position:fixed;background:#000;color:var(--cr);padding:6px 10px;border-radius:6px;font-size:.7rem;font-family:'JetBrains Mono',monospace;pointer-events:none;z-index:99;opacity:0;transition:opacity .15s}

@media(max-width:720px){.row{grid-template-columns:1fr}.receipts{grid-template-columns:1fr 1fr}.stats{grid-template-columns:repeat(4,1fr)}}
</style>
</head>
<body>
<div class="theme-toggle">
  <button class="theme-btn claude active" onclick="setTheme('claude')" title="Claude theme"></button>
  <button class="theme-btn codex" onclick="setTheme('codex')" title="Codex theme"></button>
</div>
<div class="wrap">

<!-- ═══ TRADING CARD (screenshot target) ═══ -->
<div class="card" id="card">
  <div id="card-inner"></div>
</div>

<div class="share-bar">
  <button class="btn btn-dl" onclick="screenshot()">Download</button>
  <button class="btn btn-x" onclick="shareX()">Share on X</button>
  <button class="btn btn-lb" style="opacity:0.5;cursor:default" disabled>Leaderboard — coming soon</button>
  <div class="share-hint">Compare yourself against other devs</div>
</div>

<!-- ═══ DEEP DIVE ═══ -->
<div id="deep"></div>

<div class="ftr">openbook — what your AI knows about you</div>
</div>
<div class="tt" id="tt"></div>

<script>
const D = $$DATA$$;
const ci = document.getElementById('card-inner');
const deep = document.getElementById('deep');
const tt = document.getElementById('tt');
const palette = [[217,119,87],[232,149,111],[196,168,130],[245,230,211],[163,90,58],[200,140,100]];

// ─── HTML escape for user content ────────────────────────
function esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

// ─── Tooltip helper ──────────────────────────────────────
document.addEventListener('mousemove', e => { tt.style.left = e.pageX+12+'px'; tt.style.top = e.pageY-32+'px'; });
function showTip(el, text) {
  el.addEventListener('mouseenter', () => { tt.textContent = text; tt.style.opacity = 1; });
  el.addEventListener('mouseleave', () => { tt.style.opacity = 0; });
}

// ─── CARD ────────────────────────────────────────────────
ci.innerHTML = `
<div class="hdr">
  <h1>openbook</h1>
  <div class="meta">${D.first_date} — ${D.last_date}</div>
</div>
<div class="arch">
  <div class="arch-name">${D.archetype.name}</div>
  <div class="arch-desc">${D.archetype.desc}</div>
</div>
<div class="stats">
  <div class="st"><div class="v">${D.total_prompts.toLocaleString()}</div><div class="l">Prompts</div></div>
  <div class="st"><div class="v">${D.days_active}</div><div class="l">Days</div></div>
  <div class="st"><div class="v">${D.prompts_per_day}</div><div class="l">Daily Avg</div></div>
  <div class="st"><div class="v">${D.busiest_day}</div><div class="l">Peak Day</div></div>
  <div class="st"><div class="v">${D.peak_hour}</div><div class="l">Peak Hour</div></div>
  <div class="st"><div class="v">${D.max_streak||0}</div><div class="l">Day Streak</div></div>
  <div class="st"><div class="v">~$${D.est_cost||0}</div><div class="l">Est. Cost</div></div>
</div>`;

// Receipts (top 6 for card)
const onePct = D.one_worders ? Math.round(D.one_worders/D.total_prompts*100) : 0;
const allR = [
  [D.bro_count, 'said <b>"bro/dude"</b>'],
  [D.late_night, 'prompts at <b>3am</b>'],
  [D.why_count, 'asked <b>"why?"</b>'],
  [D.swear_count, '<b>swore</b> at AI'],
  [D.fix_count, 'said <b>"fix"</b>'],
  [D.doesnt_work, '<b>"doesn\'t work"</b>'],
  [D.error_count, 'mentioned <b>error</b>'],
  [D.please_count, 'said <b>"please"</b>'],
  [D.thanks_count, 'said <b>"thanks"</b>'],
  [D.sorry_count, '<b>apologized</b>'],
  [D.good_job, '<b>complimented</b> AI'],
  [D.changed_mind, '<b>changed mind</b>'],
  [D.refactor_count, 'asked to <b>refactor</b>'],
  [D.longest_words, 'words, <b>longest prompt</b>'],
  [onePct?onePct+'%':0, 'prompts <b>≤2 words</b>'],
].filter(([v])=>{const n=typeof v==='string'?parseInt(v):v;return n&&n>0})
 .sort((a,b)=>(typeof b[0]==='string'?parseInt(b[0]):b[0])-(typeof a[0]==='string'?parseInt(a[0]):a[0]));

if (allR.length) {
  let h = '<div class="sec">The Receipts</div><div class="receipts">';
  allR.slice(0,6).forEach(([n,t])=>{ h+=`<div class="rc"><div class="n">${n}</div><div class="d">${t}</div></div>`; });
  h += '</div>';
  ci.innerHTML += h;
}

ci.innerHTML += `<div class="ftr">openbook — what your AI knows about you</div>`;

// ─── DEEP DIVE SECTIONS ─────────────────────────────────

// 1. Activity Heatmap (full width)
if (D.heatmap_weeks && D.heatmap_weeks.length) {
  const c = document.createElement('div'); c.className='card';
  const allCounts = D.heatmap_weeks.flat().map(d=>d.count);
  const maxC = Math.max(...allCounts, 1);
  const dayLabels = ['Mon','','Wed','','Fri','',''];
  let h = '<div class="sec">Activity</div><div style="display:flex"><div class="hm-labels">';
  dayLabels.forEach(l=>{h+=`<span>${l}</span>`;});
  h+='</div><div class="heatmap">';
  const months=[];
  D.heatmap_weeks.forEach((week,wi)=>{
    h+='<div class="hm-col">';
    week.forEach(day=>{
      if (!day.in_range) {
        h+='<div class="hm-cell" style="background:transparent;visibility:hidden"></div>';
      } else {
        const r=day.count/maxC;
        let bg=day.count===0?'rgba(196,168,130,.06)':r<.25?'rgba(217,119,87,.25)':r<.5?'rgba(217,119,87,.45)':r<.75?'rgba(217,119,87,.7)':'rgba(217,119,87,1)';
        h+=`<div class="hm-cell" style="background:${bg}" data-tip="${day.date}: ${day.count} prompts"></div>`;
      }
    });
    h+='</div>';
    const hasData = week.some(d=>d.in_range);
    if (hasData) {
      const firstInRange = week.find(d=>d.in_range);
      const m = firstInRange.date.slice(5,7);
      if(months.length===0 || months[months.length-1].month!==m) months.push({idx:wi,month:m,name:new Date(firstInRange.date+'T00:00').toLocaleString('en',{month:'short'})});
    }
  });
  h+='</div></div><div class="hm-months">';
  let li=0; months.forEach(m=>{const g=(m.idx-li)*13;h+=`<span style="margin-left:${li===0?28:g-20}px">${m.name}</span>`;li=m.idx;});
  h+='</div>';
  c.innerHTML=h; deep.appendChild(c);
  c.querySelectorAll('[data-tip]').forEach(el=>showTip(el,el.dataset.tip));
}

// 2. Row: Hour chart + Day of week
{
  const row = document.createElement('div'); row.className='row';

  // Hour chart
  if (D.hour_data) {
    const c = document.createElement('div'); c.className='card';
    const maxH = Math.max(...D.hour_data);
    let h = '<div class="sec">By Hour</div><div class="hours">';
    D.hour_data.forEach((cnt,i)=>{
      const pct=maxH?(cnt/maxH*100):0;
      h+=`<div class="hbar-wrap"><div class="hbar" style="height:${Math.max(3,pct)}%" data-tip="${i}:00 — ${cnt} prompts"></div></div>`;
    });
    h+='</div><div class="hlabels">';
    for(let i=0;i<24;i++) h+=`<span>${i%6===0?i+'h':''}</span>`;
    h+='</div>';
    c.innerHTML=h; row.appendChild(c);
    c.querySelectorAll('[data-tip]').forEach(el=>showTip(el,el.dataset.tip));
  }

  // Day of week
  if (D.day_of_week_counts) {
    const c = document.createElement('div'); c.className='card';
    const maxD = Math.max(...D.day_of_week_counts);
    const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    let h = '<div class="sec">By Day</div><div class="dow">';
    D.day_of_week_counts.forEach((cnt,i)=>{
      const pct=maxD?(cnt/maxD*100):0;
      const px = Math.max(4, Math.round(pct/100*60));
      h+=`<div class="dow-bar"><div class="dow-fill" style="height:${px}px" data-tip="${days[i]}: ${cnt} prompts"></div><div class="dow-label">${days[i]}</div></div>`;
    });
    h+='</div>';
    c.innerHTML=h; row.appendChild(c);
    c.querySelectorAll('[data-tip]').forEach(el=>showTip(el,el.dataset.tip));
  }
  deep.appendChild(row);
}

// 3. Word Cloud (full width)
if (D.cloud_words && D.cloud_words.length) {
  const c = document.createElement('div'); c.className='card';
  c.innerHTML = '<div class="sec">Your Words</div>';
  const cloud = document.createElement('div'); cloud.className='cloud';
  D.cloud_words.forEach((w,i)=>{
    const span = document.createElement('span');
    span.textContent = w.text;
    const col = palette[i%palette.length];
    const op = 0.5+(w.size/72)*0.5;
    span.style.cssText=`font-size:${w.size}px;color:rgba(${col[0]},${col[1]},${col[2]},${op});animation-delay:${i*0.02}s`;
    showTip(span, `"${w.text}" — ${w.count}x`);
    cloud.appendChild(span);
  });
  c.appendChild(cloud); deep.appendChild(c);
}

// 4. Row: Obsessions + Projects
{
  const row = document.createElement('div'); row.className='row';

  if (D.top_topics && D.top_topics.length) {
    const c = document.createElement('div'); c.className='card';
    const maxT = D.top_topics[0][1];
    let h = '<div class="sec">Your Obsessions</div>';
    D.top_topics.slice(0,7).forEach(([name,count])=>{
      h+=`<div class="topic"><span class="name">${name}</span><div class="bar-bg"><div class="bar-fill" style="width:${count/maxT*100}%"></div></div><span class="cnt">${count}</span></div>`;
    });
    c.innerHTML=h; row.appendChild(c);
  }

  if (D.top_projects && D.top_projects.length) {
    const c = document.createElement('div'); c.className='card';
    const maxP = D.top_projects[0][1];
    let h = '<div class="sec">Projects</div>';
    D.top_projects.forEach(([name,count])=>{
      h+=`<div class="proj"><span class="name">${name}</span><div class="bar-bg"><div class="bar-fill" style="width:${count/maxP*100}%"></div></div><span class="cnt">${count}</span></div>`;
    });
    c.innerHTML=h; row.appendChild(c);
  }
  deep.appendChild(row);
}

// 5. Row: Longest prompt + Broken Record
{
  const row = document.createElement('div'); row.className='row';

  if (D.longest_prompt) {
    const c = document.createElement('div'); c.className='card';
    c.innerHTML = `<div class="sec">Your Longest Prompt</div><div class="prompt-reveal"><b>${D.longest_words} words</b> — "${esc(D.longest_prompt)}${D.longest_prompt.length>=200?'...':''}"</div>`;
    row.appendChild(c);
  }

  if (D.most_repeated && D.most_repeated.length) {
    const c = document.createElement('div'); c.className='card';
    let h = '<div class="sec">Broken Record</div>';
    D.most_repeated.forEach(([text,count])=>{
      const d = text.length>50?text.slice(0,50)+'...':text;
      h+=`<div class="repeated"><span class="rp-count">${count}x</span><span class="rp-text">"${esc(d)}"</span></div>`;
    });
    c.innerHTML=h; row.appendChild(c);
  }
  deep.appendChild(row);
}

// 6. All Receipts (expanded, below card)
if (allR.length > 6) {
  const c = document.createElement('div'); c.className='card';
  let h = '<div class="sec">All Receipts</div><div class="receipts">';
  allR.forEach(([n,t])=>{ h+=`<div class="rc"><div class="n">${n}</div><div class="d">${t}</div></div>`; });
  h += '</div>';
  c.innerHTML=h; deep.appendChild(c);
}

// 7. Tips
if (D.tips && D.tips.length) {
  const c = document.createElement('div'); c.className='card';
  let h = '<div class="sec">Tips For You</div>';
  D.tips.forEach((tip,i) => {
    h += `<div class="tip-item">
      <div class="tip-num">${i+1}</div>
      <div class="tip-body">
        <div class="tip-title">${tip.title}</div>
        <div class="tip-text">${tip.body}</div>
        <div class="tip-meta"><span class="tip-cat">${tip.category}</span>${tip.source ? `<span class="tip-src">${tip.source}</span>` : ''}</div>
      </div>
    </div>`;
  });
  c.innerHTML=h; deep.appendChild(c);
}

// ─── Leaderboard ─────────────────────────────────────────
function joinLeaderboard() {
  const payload = btoa(JSON.stringify(D.leaderboard_payload));
  // TODO: replace with actual domain when deployed
  const base = 'https://openbook.dev';
  window.open(`${base}/api/join?d=${payload}`, '_blank');
}

// ─── Theme ───────────────────────────────────────────────
function setTheme(theme) {
  document.body.classList.toggle('codex', theme === 'codex');
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.theme-btn.${theme}`).classList.add('active');
}

// ─── Actions ─────────────────────────────────────────────
function shareX() {
  const text = encodeURIComponent(`I'm "${D.archetype.name}" according to openbook — ${D.total_prompts} prompts analyzed\n\nRun: curl -s https://raw.githubusercontent.com/mjwsolo/openbook/main/openbook.py | python3`);
  window.open(`https://x.com/intent/tweet?text=${text}`, '_blank');
}
function screenshot() {
  const s = document.createElement('script');
  s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
  s.onload = () => {
    html2canvas(document.getElementById('card'), {backgroundColor:'#1a1410',scale:2}).then(canvas=>{
      const a=document.createElement('a');a.download='openbook.png';a.href=canvas.toDataURL('image/png');a.click();
    });
  };
  document.head.appendChild(s);
}
</script>
</body>
</html>"""


def generate_html(data):
    return HTML_TEMPLATE.replace("$$DATA$$", json.dumps(data, indent=2))


# ─── Telemetry ────────────────────────────────────────────────────────────────

TELEMETRY_ENDPOINT = "https://openbook-api.mjwsolo.workers.dev/api/telemetry"
CONFIG_DIR = Path.home() / ".openbook"
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_config():
    """Read local config (telemetry preference, user ID)."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config):
    """Write local config."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_anonymous_id():
    """Generate a stable anonymous ID from machine info. No PII."""
    import hashlib
    raw = str(Path.home()) + os.environ.get("USER", "") + os.environ.get("HOSTNAME", "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ask_telemetry_consent():
    """One-time opt-in prompt. Returns True/False."""
    print(f"  {orange('?')} {cream('Help build the openbook community?')}")
    print()
    print(f"  {dim('  openbook can share anonymous stats to power:')}")
    print(f"  {dim('  • Leaderboards — see how you rank against other devs')}")
    print(f"  {dim('  • Percentiles — \"more prolific than 87% of users\"')}")
    print(f"  {dim('  • Trends — how the community codes with AI over time')}")
    print(f"  {dim('  • Claude vs Codex — aggregate comparison across tools')}")
    print()
    print(f"  {dim('  What we send:  numbers only (prompt count, peak hour, archetype)')}")
    print(f"  {dim('  What we never send:  prompt text, project names, file paths, code')}")
    print(f"  {dim('  You can opt out anytime:  openbook --opt-out')}")
    print()
    try:
        answer = input(f"  {dim('  Share? (y/n): ')}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def build_telemetry_payload(data):
    """Build the anonymous payload from analysis data."""
    import platform
    total = data["total_prompts"]
    return {
        "id": get_anonymous_id(),
        "v": __version__,
        "os": sys.platform,
        "py": platform.python_version(),
        "tz_offset": round((datetime.now() - datetime.utcnow()).total_seconds() / 3600),
        "tools": [s.lower().replace(" ", "") for s in data.get("tools", [])],
        "prompts": total,
        "days": data["days_active"],
        "daily_avg": data["prompts_per_day"],
        "streak": data.get("max_streak", 0),
        "peak_hour": data.get("peak_hour", "00:00").replace(":00", ""),
        "peak_day": data.get("busiest_day", ""),
        "late_pct": round(data["late_night"] / total * 100, 1) if total else 0,
        "weekend_pct": data.get("weekend_pct", 0),
        "fix_rate": round((data["fix_count"] + data["doesnt_work"]) / total * 100, 1) if total else 0,
        "polite_rate": round((data["please_count"] + data["thanks_count"] + data["sorry_count"]) / total * 100, 1) if total else 0,
        "swear_rate": round(data["swear_count"] / total * 100, 1) if total else 0,
        "bro_rate": round(data["bro_count"] / total * 100, 1) if total else 0,
        "question_pct": round(data["question_count"] / total * 100, 1) if total else 0,
        "short_pct": round(data["one_worders"] / total * 100, 1) if total else 0,
        "avg_prompt_len": data["avg_length"],
        "est_cost": data.get("est_cost", 0),
        "archetype": data.get("archetype", {}).get("name", ""),
        "has_config": data.get("has_config", False),
        "sessions": data.get("sessions", 0),
        "avg_session_min": data.get("avg_session_min", 0),
        "prompts_per_session": data.get("prompts_per_session", 0),
        "followup_rate": data.get("followup_rate", 0),
        "categories": data.get("prompt_categories", {}),
        "vocab_diversity": data.get("vocab_diversity", 0),
        "claude_count": data.get("claude_count", 0),
        "codex_count": data.get("codex_count", 0),
    }


def send_telemetry(payload):
    """POST anonymous stats. Non-blocking, fails silently."""
    import urllib.request
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            TELEMETRY_ENDPOINT,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"openbook/{__version__}",
                "Accept": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def handle_telemetry(data):
    """Handle the full telemetry flow: check consent, send if opted in."""
    config = get_config()

    # First run: ask for consent
    if "telemetry" not in config:
        consented = ask_telemetry_consent()
        config["telemetry"] = consented
        config["id"] = get_anonymous_id()
        save_config(config)
        if consented:
            print(f"  {dim('  Thanks! Your anonymous stats help build community benchmarks.')}")
        else:
            print(f"  {dim('  No worries. You can enable later with: openbook --opt-in')}")
        print()

    # Send if opted in
    if config.get("telemetry"):
        payload = build_telemetry_payload(data)
        sent = send_telemetry(payload)
        if sent:
            print(f"  {dim('  Stats shared anonymously.')}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    terminal_only = "--terminal" in args or "-t" in args

    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    if "--version" in args:
        print(f"openbook {__version__}")
        sys.exit(0)

    # Handle opt-in/opt-out flags
    if "--opt-in" in args:
        config = get_config()
        config["telemetry"] = True
        config["id"] = get_anonymous_id()
        save_config(config)
        print(f"  {cream('Telemetry enabled.')} Anonymous stats will be shared.")
        sys.exit(0)

    if "--opt-out" in args:
        config = get_config()
        config["telemetry"] = False
        save_config(config)
        print(f"  {cream('Telemetry disabled.')} No data will be shared.")
        sys.exit(0)

    # Load data
    prompts, sources_found = load_history()

    if not prompts:
        print()
        print(f"  {orange('No prompt history found!')}")
        print()
        print(f"  {dim('Looked for:')}")
        print(f"    {cream('Claude Code')}  ~/.claude/history.jsonl")
        print(f"    {cream('Codex')}        ~/.codex/history.jsonl")
        print()
        sys.exit(1)

    print()
    tools = " + ".join(sources_found)
    print(f"  {orange('⣿')} {bold(cream('openbook'))} {dim('— what your AI knows about you')}")
    print(f"  {dim(f'  Found {len(prompts)} prompts from {tools}')}")
    print()

    data = analyze_prompts(prompts)
    data["tools"] = sources_found
    data["leaderboard_payload"]["tools"] = ",".join(s.lower().replace(" ", "") for s in sources_found)

    render_terminal(data)

    # Telemetry (ask on first run, then auto-send if opted in)
    handle_telemetry(data)

    if not terminal_only:
        output_path = Path(tempfile.gettempdir()) / "openbook.html"
        output_path.write_text(generate_html(data), encoding="utf-8")
        print(f"  {dim('Opening browser...')}")
        print()
        webbrowser.open(f"file://{output_path}")


if __name__ == "__main__":
    main()
