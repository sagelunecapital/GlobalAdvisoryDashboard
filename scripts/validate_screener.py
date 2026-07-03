#!/usr/bin/env python3
"""Validate screener movers JSON against the enrichment format rules.

Run manually or via the pre-push hook (.gaai/project/hooks/pre-push.d/).
Checks every row that HAS a catalyst (un-enriched rows are allowed - a
fetch may legitimately be committed before enrichment):

  FAIL (exit 1) - format violations that should never ship:
    * em dash (U+2014) in catalyst / group_summary (renders as garbage on cp1252)
    * ticker never mentioned in its own catalyst (ticker-only naming rule:
      summaries must reference the ticker symbol, not the company name)
    * catalyst_type not in {earnings, guidance, analyst, macro, other}
    * file is not valid JSON / missing by_date

  WARN (exit 0) - surfaced but not blocking:
    * company name (first word of company field) appears in catalyst -
      fuzzy heuristic, review manually
    * top-level weekly_returns key missing (run scripts/screener_weekly.py)
"""
import re
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FILES = [
    BASE / "prototypes" / "screener_movers.json",
    BASE / "prototypes" / "screener_movers_cn.json",
]
ALLOWED_TYPES = {"earnings", "guidance", "analyst", "macro", "other"}
EM_DASH = "—"
WARNINGS: list[str] = []


def validate(path: Path) -> list[str]:
    errors = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"{path.name}: not valid JSON ({e})"]
    if "by_date" not in data:
        return [f"{path.name}: missing top-level by_date"]
    if "weekly_returns" not in data:
        WARNINGS.append(f"{path.name}: weekly_returns missing - run scripts/screener_weekly.py before deploy")
    for dt, rows in data["by_date"].items():
        for row in rows:
            cat = row.get("catalyst")
            if not cat:
                continue  # un-enriched row: allowed
            tkr = row.get("ticker", "?")
            where = f"{path.name} {dt} {tkr}"
            if EM_DASH in cat or EM_DASH in (row.get("group_summary") or ""):
                errors.append(f"{where}: em dash in catalyst/group_summary (use plain hyphen)")
            if not re.search(rf"\b{re.escape(tkr)}\b", cat):
                errors.append(f"{where}: catalyst never mentions its ticker '{tkr}' (ticker-only naming rule)")
            ct = row.get("catalyst_type")
            if ct not in ALLOWED_TYPES:
                errors.append(f"{where}: catalyst_type '{ct}' not in {sorted(ALLOWED_TYPES)}")
            first = (row.get("company") or "").split()[0].rstrip(",.") if row.get("company") else ""
            if len(first) > 3 and first.lower() != tkr.lower() and re.search(rf"\b{re.escape(first)}\b", cat):
                WARNINGS.append(f"{where}: company name word '{first}' in catalyst - use ticker only")
    return errors


def main() -> int:
    all_errors = []
    for f in FILES:
        if f.exists():
            all_errors.extend(validate(f))
    if WARNINGS:
        for w in WARNINGS[:5]:
            print("WARN", w)
        if len(WARNINGS) > 5:
            print(f"WARN ... and {len(WARNINGS) - 5} more company-name warnings "
                  f"(run scripts/validate_screener.py directly for the full list)")
    if all_errors:
        print("SCREENER VALIDATION FAILED:")
        for e in all_errors:
            print("  FAIL", e)
        return 1
    print("screener JSON validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
