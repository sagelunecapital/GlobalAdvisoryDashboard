---
type: memory_index
id: MEMORY-INDEX
updated_at: 2026-04-18
---

# Memory Map

> Always keep this index current. Agents use it to know what exists before calling `memory-retrieve`.
> Update when files are added, archived, or compacted.

---

## Active Files

| File | Category | ID | Last updated |
|---|---|---|---|
| `project/context.md` | project | PROJECT-001 | 2026-04-18 |
| `project/data-sources.md` | project | PROJECT-002 | 2026-04-18 |
| `decisions/_log.md` | decisions | DECISIONS-LOG | 2026-04-18 |
| `patterns/conventions.md` | patterns | PATTERNS-001 | — |

---

## Memory Principles

- **Retrieve selectively** — never load entire folders
- **Prefer summaries** over raw session notes
- **Archive aggressively** — move compacted content to `archive/`
- **Sessions are temporary** — always summarize before closing
- **Memory is distilled knowledge — not history**
