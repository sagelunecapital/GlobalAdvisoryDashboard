# Enrich & Deploy Screener Movers

Enrich the screener movers with catalysts, then deploy.

**How deploy works (do NOT confuse with the macro dashboard):** the screener UI
fetches `prototypes/screener_movers.json` (US), `screener_movers_cn.json` (HK/CN),
and `screener_ipos.json` directly. There is **NO inline data block** in index.html
for the screener — deploying is just committing the JSON and pushing to main.

**Enrichment is done by Claude directly** using built-in web search / research tools.
NEVER call `screener_enrich.py` or the Anthropic API — those are forbidden for this work.

## Steps

1. **Guard the existing data before any fetch.** Run `git log -p` / `git diff` on the
   target JSON first. Fetching before the HK close mislabels the *prior* session under
   *today's* key — diff the new date key against the previous batch and, if a fetch would
   clobber an already-enriched batch, recover it from git before re-keying. A re-fetch must
   never silently wipe enriched catalysts.

2. **Fetch, then spot-check mkt_cap immediately.** If USD/HKD suffix matching breaks, the
   volume column gets picked up instead of market cap. Verify before enriching.

3. **Enrich per the rules** (see `screener_enrichment_rules` memory): one real, dated,
   price-moving catalyst per ticker; classify `catalyst_type`; set thematic grouping and the
   continuation flag; ticker-only naming; **no em dashes**. For HK/CN, reuse the existing US
   enrichment logic — do not duplicate with a separate code path.

   **Research process (mover dates are after the model's cutoff — always search, never recall):**
   - Spawn one research subagent per ticker, all in parallel. Each prompt must require:
     the ticker + % move + exact date; a source name, URL, and date for every claim;
     an explicit `CATALYST_FOUND: yes|no` (finding nothing is a valid answer — do NOT
     invent events; classify those as `macro` and say no specific trigger was found);
     a confidence rating; ticker-only naming (numeric for HK) and plain hyphens in the draft;
     a one-phrase `SECTOR_THEME` so the main agent can detect same-day thematic groups.
   - The MAIN agent (not the subagents) does synthesis: grouping needs the cross-ticker
     view — group only tickers sharing the same specific same-day catalyst/trigger
     (stricter for HK: same broad sector is NOT enough).
   - `continuation` is set programmatically by comparing against the previous trading
     day's tickers in `by_date` — never authored by judgment.
   - Sanity-check suspicious movers: a big % on a thinly-traded ADR with a flat underlying
     listing is a pricing artifact — say so in the catalyst rather than forcing a story.

   **Write the enriched rows via a patch script, never by hand-editing the JSON.** The script
   must preserve fetched fields, only touch the new date key, and assert format rules
   (no em dashes, ticker mentioned, valid catalyst_type). Then run
   `python scripts/validate_screener.py` — it must exit 0 before you commit (it also runs
   as a pre-push hook and will block the push otherwise).

4. **Refresh weekly returns.** After enrichment, run `python scripts/screener_weekly.py`. It
   recomputes the Fri-to-Fri weekly return per ticker (via yfinance) and rewrites
   `weekly_returns` inside `screener_movers.json` and `screener_movers_cn.json` — the weekly
   movers view reads these to show each ticker once with its true weekly move. Idempotent; any
   ticker that doesn't resolve is listed and falls back to the daily change in the UI.

5. **Commit the JSON and push to MAIN.** Vercel deploys from `main`, not `staging`. Commit the
   affected file(s): `screener_movers.json`, `screener_movers_cn.json`, and/or `screener_ipos.json`
   (the weekly-returns step above also modifies the two movers files — include those changes).

6. **Verify live before reporting done.** Curl the live Vercel URL for the JSON
   (e.g. `https://global-advisory-dashboard.vercel.app/screener_movers.json`) and confirm the new
   enriched values are actually served. Do not declare success on push alone.
