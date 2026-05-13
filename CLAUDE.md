# GAAI — Claude Code Integration

> This file is deployed to your project root as `CLAUDE.md` by the installer.
> It activates GAAI governance when working in Claude Code.

---

## Environment
- Primary OS is Windows (PowerShell); WSL is available but daemons/scripts don't persist across WSL sessions reliably
- Use Python fallbacks instead of WebFetch for FRED (returns 403)
- Avoid Unicode characters in print() statements (Windows console crashes on them)
- `flock` and `gh` CLI are not available — use direct git operations and GitHub API via PowerShell as fallback
- Watch for paths containing brackets — quote them properly in PowerShell

---

## Git Workflow Rules
- NEVER run `git checkout <branch> --` against files with uncommitted changes; stash or commit first
- Confirm the target branch (main vs staging) before pushing automated commits
- When updating dashboard data, update BOTH the source file AND any generated/cached JSON (e.g., regime.json) that the UI actually reads from
- After code fixes that change displayed values, verify the data block in index.html was regenerated

---

## Data Sources
- For GDP growth use FRED series A191RL1Q225SBEA (real GDP, compounded annual rate, pre-computed)
- Do NOT compute YoY/QoQ from nominal series via units transformation
- For GDPNow, use the official Atlanta Fed CSV endpoint, not generic web scraping
- Verify FRED series units (e.g., WRESBAL) before applying scaling

---

## Deployment Checklist
- Check .gitignore is not blocking the file you just generated (HTML dashboards were blocked at least once)
- After deploy, verify the live URL renders the new values, not just that the push succeeded

---

## You Are Operating Under GAAI Governance

This project uses the **GAAI framework** (`.gaai/` folder). Read `.gaai/core/GAAI.md` first.

### Your Identity

You operate as one of three agents depending on context:
- **Discovery Agent** — when clarifying intent, creating artefacts, defining what to build (runs in current session)
- **Delivery Agent** — when implementing validated Stories from the backlog (always runs as an isolated `claude -p` process via the daemon — see `orchestration.rules.md` § Context Isolation)
- **Bootstrap Agent** — when initializing or refreshing project context on a new codebase (runs in current session)

Read the active agent definition before acting:
- `.gaai/core/agents/discovery.agent.md`
- `.gaai/core/agents/delivery.agent.md`
- `.gaai/core/agents/bootstrap.agent.md`

### Rules (Always Active)

@.gaai/core/contexts/rules/base.rules.md

### Canonical Files

| Purpose | File |
|---|---|
| Rules | `.gaai/core/contexts/rules/orchestration.rules.md` |
| Skills index | `.gaai/core/skills/README.skills.md` |
| Active backlog | `.gaai/project/contexts/backlog/active.backlog.yaml` |
| Project memory | `.gaai/project/contexts/memory/project/context.md` |

---

## Slash Commands

After install, these commands are available in Claude Code:

- `/gaai-bootstrap` — Run Bootstrap Agent to initialize project context
- `/gaai-discover` — Activate Discovery Agent for a new feature or problem
- `/gaai-deliver` — Start the Delivery Daemon (alias of `/gaai-daemon`)
- `/gaai-status` — Show current backlog and memory state
- `/gaai-update` — Update framework core or switch AI tool adapter
- `/gaai-switch cloud` — Connect to GAAI Cloud: migrate local contexts to a cloud workspace
