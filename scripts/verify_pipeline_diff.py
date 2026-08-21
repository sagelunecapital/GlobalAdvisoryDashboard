#!/usr/bin/env python3
"""Content-level diff of the pipeline data files: git ref vs working tree.

Run AFTER `update_and_deploy.ps1 -DryRun` and BEFORE staging/committing.
`git diff --stat` is useless on these files - every JSON is minified to a
single line, so a dropped contract and a routine value update both show as
"1 line changed". This compares the parsed structures instead.

  Usage:
    python scripts/verify_pipeline_diff.py            # vs HEAD (pre-commit)
    python scripts/verify_pipeline_diff.py HEAD~1     # vs prior commit (post-commit)

  Covers the 13 generated JSONs. prototypes/index.html is the 14th committed
  file but is HTML, not JSON - verify it by hand per the deploy-dashboard
  skill (its "updated <ts>" comment, const ND, and embedded SPX/EMA/GDPNow
  scalars must match the regenerated regime.json).

  FAIL (exit 1) - do not commit until resolved:
    * a top-level key present in the ref is MISSING from the working tree
      (export_price_json.py silently drops failed contracts and still exits 0 -
      the only other tell is "Exported 28 tickers" instead of 35)
    * price_data.json has fewer than PRICE_EXPECTED_KEYS contracts
    * cot_data.json total obs shrank AND no contract advanced its last date
      (pure rolling-window history erosion - cot_report_pull.py re-pulls a
      rolling "last 500 weeks" and never adds data mid-week; CFTC releases
      Fridays only, so revert rather than ship eroded history)
    * a file is missing or not valid JSON

  WARN (exit 0) - surfaced but expected; confirm and move on:
    * cot_data.json obs shrank BUT last dates advanced - the 500-week window
      shedding its oldest week as a new one lands. This is a real update;
      decide with the last date, never the obs delta.
    * mfra_group.json obs delta - each group's idio_tickers list is recomputed
      per window and varies in length run to run. Check as_of advanced and the
      group count held instead.
    * a file is byte-identical to the ref (its pipeline step may have failed
      silently, or there was genuinely nothing new to publish)
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# Mirrors $dataFiles in scripts/update_and_deploy.ps1. When a script starts
# emitting a new JSON, add it to BOTH lists in the same change.
DATA_FILES = [
    "carry.json",
    "cot_data.json",
    "cross_asset.json",
    "gdpnow.json",
    "leadership.json",
    "mfra_group.json",
    "price_data.json",
    "regime.json",
    "sector_rotation.json",
    "stir.json",
    "ticker_perf.json",
    "warsh.json",
    "yen.json",
]
PRICE_EXPECTED_KEYS = 35
STAMP_KEYS = ("as_of", "asof", "updated")
WARNINGS: list[str] = []


def ref_version(ref: str, name: str):
    """Parse prototypes/<name> as of a git ref, or None if absent there."""
    out = subprocess.run(
        ["git", "-C", str(BASE), "show", f"{ref}:prototypes/{name}"],
        capture_output=True,
    )
    if out.returncode != 0:
        return None
    return json.loads(out.stdout.decode("utf-8-sig"))


def work_version(name: str):
    return json.loads((BASE / "prototypes" / name).read_text(encoding="utf-8-sig"))


def obs_count(v) -> int:
    """Total leaf-list entries, recursively."""
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        return sum(obs_count(x) for x in v.values())
    return 0


def last_dates(data) -> dict[str, str]:
    """Map key -> last entry of its 'dates' list, for keys that have one."""
    out = {}
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(v.get("dates"), list) and v["dates"]:
            out[k] = v["dates"][-1]
    return out


def stamp(data) -> str | None:
    if not isinstance(data, dict):
        return None
    for k in STAMP_KEYS:
        if isinstance(data.get(k), str):
            return f"{k}={data[k]}"
    return None


def check(ref: str, name: str) -> list[str]:
    errors = []
    try:
        old = ref_version(ref, name)
    except Exception as e:
        return [f"{name}: could not parse {ref} version ({e})"]
    try:
        new = work_version(name)
    except FileNotFoundError:
        return [f"{name}: missing from working tree"]
    except Exception as e:
        return [f"{name}: not valid JSON in working tree ({e})"]

    if old is None:
        print(f"  {name:<24} NEW FILE (absent at {ref})")
        return errors

    ko = set(old.keys()) if isinstance(old, dict) else set()
    kn = set(new.keys()) if isinstance(new, dict) else set()
    oo, on = obs_count(old), obs_count(new)
    dropped = sorted(ko - kn)
    added = sorted(kn - ko)

    # --- last-date movement (drives the COT erosion-vs-update decision) ---
    do, dn = last_dates(old), last_dates(new)
    advanced = [k for k in do if k in dn and dn[k] > do[k]]
    regressed = [k for k in do if k in dn and dn[k] < do[k]]

    notes = []
    if added:
        notes.append("+keys:" + ",".join(added[:6]))
    if advanced:
        notes.append(f"{len(advanced)}/{len(do)} dates advanced")
    st_o, st_n = stamp(old), stamp(new)
    if st_o and st_n and st_o != st_n:
        notes.append(f"{st_o} -> {st_n.split('=', 1)[1]}")

    print(f"  {name:<24} keys {len(ko)}->{len(kn)}   obs {oo}->{on} ({on - oo:+d})"
          f"   {'  '.join(notes) if notes else ''}")

    # --- FAIL conditions ---
    if dropped:
        errors.append(f"{name}: {len(dropped)} top-level key(s) DROPPED vs {ref}: "
                      f"{','.join(dropped[:10])} - re-run the exporting step, "
                      f"it drops failures silently and still exits 0")
    if regressed:
        errors.append(f"{name}: last date went BACKWARDS for {','.join(regressed[:6])} "
                      f"- stale or corrupt source data")
    if name == "price_data.json" and len(kn) < PRICE_EXPECTED_KEYS:
        errors.append(f"{name}: only {len(kn)} contracts, expected "
                      f"{PRICE_EXPECTED_KEYS} - re-run scripts/export_price_json.py "
                      f"until it prints 'Exported {PRICE_EXPECTED_KEYS} tickers'")
    if name == "cot_data.json" and on < oo and not advanced:
        errors.append(f"{name}: obs shrank {on - oo:+d} and NO contract advanced its "
                      f"last date - pure history erosion, not an update. "
                      f"Revert: git checkout {ref} -- prototypes/{name}")

    # --- WARN conditions ---
    if name == "cot_data.json" and on < oo and advanced:
        WARNINGS.append(f"{name}: obs shrank {on - oo:+d} but {len(advanced)} contract(s) "
                        f"advanced their last date - benign rolling-window shed, keep it")
    if name == "mfra_group.json" and on != oo:
        WARNINGS.append(f"{name}: obs delta {on - oo:+d} is idio_tickers churn, not data "
                        f"loss - verify as_of advanced and group count held")
    if old == new:
        WARNINGS.append(f"{name}: byte-identical to {ref} - confirm its pipeline step "
                        f"actually ran and had nothing new to publish")

    return errors


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    print(f"Content-level diff of {len(DATA_FILES)} pipeline files: {ref} -> working tree")
    print()
    all_errors = []
    for name in DATA_FILES:
        all_errors.extend(check(ref, name))
    print()

    if WARNINGS:
        for w in WARNINGS:
            print("WARN", w)
        print()
    if all_errors:
        print("PIPELINE DIFF VERIFICATION FAILED:")
        for e in all_errors:
            print("  FAIL", e)
        return 1
    print("pipeline diff verification OK - safe to stage the $dataFiles list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
