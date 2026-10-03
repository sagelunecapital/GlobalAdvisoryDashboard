# Converts an IBKR MCP connector read into data/ibkr_live.json for gen_risk_json.py.
#
# The MCP connector is session-bound: only a Claude session can call it, never the
# unattended pipeline. So this is an in-session step. Save the raw tool output as
#   {"read_at": "<UTC ISO>", "positions": [...get_account_positions...],
#    "orders": [...get_account_orders...]}
# and run:  python scripts/ibkr_mcp_import.py <raw.json>
#
# What it adds over the Flex feed:
#   - same-day book (Flex statements lag ~2 calendar days)
#   - working GTC stops, which no Activity Flex Query section reports
#
# gen_risk_json.py uses whichever of ibkr_live.json / ibkr_flex.json covers the
# LATER session (report_date; a tie goes to this file) and is under 36h old. Flex
# statements lag about a business day, so a session read keeps winning over the
# Flex fetches that follow it until Flex catches up or the read ages out. While it
# is the book, its stops are the only stops: a held symbol with no working stop
# here is refused, never back-filled from risk_manual.json.
#
# Marks never come from market_price - it includes extended hours. gen_risk_json.py
# prices a live book from yfinance closes, unless yfinance has no usable close for the
# book's session yet (its NaN-close bug); then it uses the optional "rth_bars" in the
# raw file - IBKR regular-hours daily bars from get_price_history (outside_rth=false).
#
# Order status: the connector returns NEW for untouched orders and REPLACED for
# orders that were amended and are still working (the amended price is what it
# reports - verified 23 Sep 2026 against the tightened MSFT 491 / SNOW 328 stops).
#
# Every SELL order on a held symbol must be classified, never skipped: a stop the
# importer cannot read would otherwise publish that position as unprotected, or
# (worse) let an older stop from risk_manual.json stand in for it.
import json, io, os, re, sys, datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ibkr_live.json")
NY = ZoneInfo("America/New_York")
WORKING = {"NEW", "REPLACED", "SUBMITTED", "PRESUBMITTED", "PENDING_SUBMIT",
           "PENDING_NEW", "PENDING_REPLACE", "PARTIALLY_FILLED"}
TERMINAL = {"FILLED", "CANCELLED", "CANCELED", "EXPIRED", "REJECTED", "INACTIVE",
            "PENDING_CANCEL"}
MAX_CLOCK_SKEW = datetime.timedelta(minutes=5)


def fail(msg):
    print("FATAL: " + msg)
    sys.exit(1)


def last_session(t_utc):
    """Latest COMPLETED NY session at t: today after the 16:00 close, else the
    previous weekday. Exchange holidays are not modelled - the date is only used
    to rank this book against a Flex statement, never to date a mark."""
    ny = t_utc.astimezone(NY)
    d = ny.date()
    if ny.weekday() >= 5 or ny.hour < 16:
        d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def main():
    if len(sys.argv) != 2:
        fail("usage: python scripts/ibkr_mcp_import.py <raw.json>")
    with io.open(sys.argv[1], encoding="utf-8") as f:
        raw = json.load(f)
    for k in ("read_at", "positions", "orders"):
        if k not in raw:
            fail("raw file has no '%s' key" % k)
    read_at = datetime.datetime.strptime(raw["read_at"], "%Y-%m-%dT%H:%M:%SZ") \
                       .replace(tzinfo=datetime.timezone.utc)
    if read_at - datetime.datetime.now(datetime.timezone.utc) > MAX_CLOCK_SKEW:
        fail("read_at %s is in the future - it must be UTC (Z), not local time"
             % raw["read_at"])

    positions = []
    for p in raw["positions"]:
        qty = float(p["position"])
        if qty == 0:                                    # closed today; connector keeps a zero row
            continue
        if p.get("asset_class") != "STK" or p.get("currency") != "USD":
            fail("%s is %s/%s - the Risk tab models USD stocks only"
                 % (p["contract_description"], p.get("asset_class"), p.get("currency")))
        positions.append({
            "sym": p["contract_description"],
            "conid": str(p["contract_id"]),
            "qty": qty,
            "avg": float(p["average_price"]),
            "mark_flex": float(p["market_price"]),      # key name shared with the Flex schema
            "unreal_flex": float(p["unrealized_pnl"]),
            "asset_class": p["asset_class"],
            "currency": p["currency"],
        })
    held = {p["sym"]: p["qty"] for p in positions}
    report_date = last_session(read_at).strftime("%Y-%m-%d")

    # Optional "rth_bars": {SYM: {date, open, high, low, close}} from get_price_history
    # with outside_rth=false - the official regular-hours daily bar, unlike market_price.
    # gen_risk_json.py marks the book from these only when yfinance has not yet published
    # a usable close for report_date. A bar must be for report_date and self-consistent.
    for sym, b in (raw.get("rth_bars") or {}).items():
        p = next((q for q in positions if q["sym"] == sym), None)
        if p is None:
            fail("rth_bars has %s, which is not held" % sym)
        if b.get("date") != report_date:
            fail("%s RTH bar is for %s, not the book's session %s" % (sym, b.get("date"), report_date))
        lo, hi = float(b["low"]), float(b["high"])
        o, c = float(b["open"]), float(b["close"])
        if not (0 < lo <= min(o, c) and max(o, c) <= hi):
            fail("%s RTH bar is inconsistent: open %.4f / close %.4f outside [%.4f, %.4f]"
                 % (sym, o, c, lo, hi))
        p["mark_rth"], p["mark_rth_date"] = c, b["date"]

    stops = {}
    for o in raw["orders"]:
        if o.get("side") != "SELL":
            continue
        oid, otype = o.get("order_id"), (o.get("order_type") or "").upper()
        status = (o.get("order_status") or "").upper()
        m = re.match(r"Sell\s+([\d,.]+)\s+(\S+)$", (o.get("primary_description") or "").strip())
        if not m:
            fail("cannot parse SELL order %s: %r" % (oid, o.get("primary_description")))
        sym = m.group(2)
        if sym not in held:
            continue                                    # reported below as an orphan if a stop
        if status in TERMINAL:
            continue
        if status not in WORKING:
            fail("%s SELL order %s has status %r - classify it in WORKING or TERMINAL "
                 "before publishing" % (sym, oid, o.get("order_status")))
        if otype == "LIMIT":
            continue                                    # take-profit; gives no downside cover
        if otype in ("TRAIL", "TRAILING_STOP", "TRAIL_LIMIT", "TRAILING_STOP_LIMIT"):
            fail("%s has a trailing stop (order %s). Its trigger moves with the price and "
                 "the connector does not report the current level - record it by hand."
                 % (sym, oid))
        if otype not in ("STOP", "STOP_LIMIT"):
            fail("%s SELL order %s has type %r, which the Risk tab cannot model"
                 % (sym, oid, o.get("order_type")))
        px = re.search(r"STP(?:\s+LMT)?\s+([\d,.]+)", o.get("secondary_description") or "")
        if not px:
            fail("cannot read the stop price of %s order %s: %r"
                 % (sym, oid, o.get("secondary_description")))
        qty = float(o["remaining_shares_qty"])
        if qty <= 0:
            continue
        stops.setdefault(sym, []).append({
            "qty": qty, "stop": float(px.group(1).replace(",", "")),
            "type": otype, "order_id": str(oid), "status": status,
        })

    for sym, tr in stops.items():
        tr.sort(key=lambda t: -t["stop"])               # nearest (highest) stop first
        if sym not in held:
            print("  WARNING working stop for %s but no position - orphan order?" % sym)
            continue
        covered = sum(t["qty"] for t in tr)
        if abs(covered - held[sym]) > 1e-9:
            print("  WARNING %s stops cover %.0f of %.0f shares" % (sym, covered, held[sym]))
    for sym in held:
        if sym not in stops:
            print("  note: %s has no working stop" % sym)

    doc = {
        "fetched_at": raw["read_at"],
        "source": "IBKR MCP connector (live positions + working orders)",
        "report_date": report_date,
        "positions": positions,
        "stops": stops,
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print("OK  wrote %s" % OUT)
    print("  %d positions: %s" % (len(positions),
          ", ".join("%s %.0f" % (p["sym"], p["qty"]) for p in positions)))
    for sym, tr in sorted(stops.items()):
        print("  stops %-5s %s" % (sym, " + ".join("%.0f @ %.2f" % (t["qty"], t["stop"]) for t in tr)))
    rth = [p for p in positions if "mark_rth" in p]
    if rth:
        print("  RTH closes %s: %s" % (report_date,
              ", ".join("%s %.2f" % (p["sym"], p["mark_rth"]) for p in rth)))


if __name__ == "__main__":
    main()
