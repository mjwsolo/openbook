# openbook

**what your AI knows about you.**

One command. Installs, runs, opens your AI personality report.

Works with **Claude Code** and **OpenAI Codex**.

## Install

**Mac / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/mjwsolo/openbook/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
iwr -useb https://raw.githubusercontent.com/mjwsolo/openbook/main/install.ps1 | iex
```

That's it. One command. Installs and runs immediately.

After install, just type `openbook` anytime to run again.

## What you get

- **Your archetype** — a pattern-based roast of your coding habits
- **The receipts** — how many times you swore, said "fix", coded at 3am
- **Activity heatmap** — GitHub-style contribution grid for your AI usage
- **Word cloud** — what you actually talk about (privacy-filtered)
- **Cost estimate** — what your AI habit is costing you
- **Tips** — personalized recommendations with cited sources
- **Shareable card** — download as PNG, share on X

## How it works

Reads your local prompt history. No data leaves your machine unless you opt in.

| Tool | File |
|---|---|
| Claude Code | `~/.claude/history.jsonl` |
| OpenAI Codex | `~/.codex/history.jsonl` |

Zero dependencies. Just Python 3.8+.

## Privacy

- All analysis runs **locally**
- File paths, usernames, project names are **filtered** from output
- Telemetry is **opt-in** and only sends aggregate counts (never prompt text)
- You can opt out anytime: `openbook --opt-out`

## Commands

```bash
openbook              # full report + browser
openbook -t           # terminal only
openbook --opt-in     # enable anonymous stats sharing
openbook --opt-out    # disable stats sharing
openbook --version    # show version
```

## License

MIT
