---
type: memory_index
id: MEMORY-INDEX
updated_at: 2026-04-27
---

# Memory Map

> Always keep this index current. Agents use it to know what exists before calling `memory-retrieve`.
> Update when files are added, archived, or compacted.

---

## Active Files

| File | Category | ID | Last updated |
|---|---|---|---|
| `project/context.md` | project | PROJECT-001 | 2026-04-27 |
| `project/data-sources.md` | project | PROJECT-002 | 2026-04-18 |
| `decisions/_log.md` | decisions | DECISIONS-LOG | 2026-04-27 |
| `patterns/conventions.md` | patterns | PATTERNS-001 | 2026-04-27 |

---

## Decision Registry (Quick Reference)

| Decision ID | Domain | Summary |
|---|---|---|
| DEC-2026-04-18-01 | architecture | SPX price = daily high (not close) in all calculations |
| DEC-2026-04-18-02 | architecture | Divergence anchor = prior period swing high/low; same-run rule |
| DEC-2026-04-18-03 | architecture | Report date = last trading session date (not viewer's calendar date) |
| DEC-2026-04-22-01 | architecture | Tech stack: Python + SQLite + yfinance + pandas |
| DEC-2026-04-22-02 | architecture | MMTH source: EODData (yfinance ^MMTH unavailable) |
| DEC-2026-04-25-01 | architecture | detect_divergence() signature and DivergenceResult enum contract |
| DEC-2026-04-27-01 | architecture | Dashboard: HTML data injection via update_dashboard.py (current production) |
| DEC-2026-04-27-02 | infrastructure | GH Actions + Vercel static hosting pattern |
| DEC-2026-04-27-03 | infrastructure | E06: Vercel Python serverless functions, stateless, no SQLite |
| DEC-2026-04-27-04 | architecture | src/ library and update_dashboard.py are parallel implementations (accepted) |

---

## Memory Principles

- **Retrieve selectively** — never load entire folders
- **Prefer summaries** over raw session notes
- **Archive aggressively** — move compacted content to `archive/`
- **Sessions are temporary** — always summarize before closing
- **Memory is distilled knowledge — not history**
