# Fetches the IBKR account's Open Positions via the Flex Web Service (v3) and
# writes them to data/ibkr_flex.json for scripts/gen_risk_json.py to consume.
#
# Why Flex and not the trading API: Flex is a token-authenticated REST service, so
# it works unattended from the scheduled task. TWS/IB Gateway would have to be
# running and re-authenticated daily.
#
# WHAT FLEX CANNOT GIVE YOU: working orders. An Activity Flex Query has 47 sections
# and none of them report live, unexecuted orders - only executed trades and held
# positions. The stop levels therefore live in data/risk_manual.json as
# owner-confirmed values, NOT here. Do not try to add a "stops" section to the query.
#
# Setup (one time, in IBKR Account Management):
#   Performance & Reports > Flex Queries > Activity Flex Query > +
#   Sections: Open Positions   (Symbol, Conid, Quantity, Cost Basis Price,
#                               Mark Price, FIFO Unrealized PNL, Asset Class,
#                               Currency, Report Date)
#   Period: Last Business Day      Format: XML      Then note the Query ID.
#   Performance & Reports > Flex Queries > Flex Web Service Configuration > create token.
# Then set both of these (user env vars, so the scheduled task inherits them):
#   setx IBKR_FLEX_TOKEN <token>
#   setx IBKR_FLEX_QUERY_ID <query id>
#
# Output: data/ibkr_flex.json
import json, io, os, sys, time, datetime
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ibkr_flex.json")

BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
SEND = BASE + "/SendRequest"
GET = BASE + "/GetStatement"

# Flex v3 error codes. The service answers HTTP 200 with an error document, so the
# status must be parsed out of the XML - a non-200 check is not enough.
RETRYABLE = {
    "1001": "Statement could not be generated at this time",
    "1004": "Statement is incomplete at this time",
    "1005": "Settlement data is not ready at this time",
    "1006": "FIFO P/L data is not ready at this time",
    "1018": "Too many requests from this token (1/sec, 10/min)",
    "1019": "Statement generation in progress",
    "1021": "Statement could not be retrieved at this time",
}
# Everything else is fatal: 1003 unavailable, 1010 legacy query, 1011 inactive,
# 1012 token expired, 1013 IP restriction, 1014 invalid query, 1015 invalid token,
# 1016 invalid account, 1017 invalid reference code, 1020 invalid request.

# The service rate-limits at 1 request/second; poll well inside that.
POLL_WAIT = 5
POLL_TRIES = 12


def get(url, params):
    q = "&".join("%s=%s" % (k, v) for k, v in params.items())
    req = urllib.request.Request(url + "?" + q, headers={"User-Agent": "gaai-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def text(node, *names):
    """First matching child's text, searched anywhere in the tree."""
    for n in names:
        el = node.find(".//" + n)
        if el is not None and el.text:
            return el.text.strip()
    return None


def fail(msg):
    print("FATAL: " + msg)
    sys.exit(1)


def send_request(token, query_id):
    """Ask Flex to generate the statement; returns (reference_code, statement_url)."""
    raw = get(SEND, {"t": token, "q": query_id, "v": 3})
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        fail("SendRequest did not return XML (%s): %s" % (e, raw[:300]))
    status = text(root, "Status")
    if status != "Success":
        code = text(root, "ErrorCode") or "?"
        msg = text(root, "ErrorMessage") or raw[:300]
        fail("SendRequest %s [%s] %s" % (status, code, msg))
    ref = text(root, "ReferenceCode")
    url = text(root, "Url") or GET
    if not ref:
        fail("SendRequest succeeded but returned no ReferenceCode: " + raw[:300])
    return ref, url


def get_statement(token, ref, url):
    """Poll until the statement is ready; returns the parsed XML root."""
    for attempt in range(1, POLL_TRIES + 1):
        raw = get(url, {"t": token, "q": ref, "v": 3})
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            fail("GetStatement did not return XML (%s): %s" % (e, raw[:300]))

        # A ready statement is <FlexQueryResponse>; an error is <FlexStatementResponse>.
        code = text(root, "ErrorCode")
        if code:
            msg = text(root, "ErrorMessage") or ""
            if code in RETRYABLE:
                print("  [%d/%d] %s (%s) - waiting %ds"
                      % (attempt, POLL_TRIES, RETRYABLE[code], code, POLL_WAIT))
                time.sleep(POLL_WAIT)
                continue
            fail("GetStatement error [%s] %s" % (code, msg))
        if root.find(".//OpenPosition") is not None or root.tag == "FlexQueryResponse":
            return root
        # No error and no positions - report the document rather than guess.
        fail("GetStatement returned neither an error nor OpenPosition rows: " + raw[:400])
    fail("statement still not ready after %d polls (%ds)" % (POLL_TRIES, POLL_TRIES * POLL_WAIT))


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def main():
    token = os.environ.get("IBKR_FLEX_TOKEN")
    query_id = os.environ.get("IBKR_FLEX_QUERY_ID")
    if not token or not query_id:
        fail("IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set. "
             "See the setup block at the top of this file. "
             "risk.json will keep its previous positions until this is configured.")

    print("Flex SendRequest (query %s) ..." % query_id)
    ref, url = send_request(token, query_id)
    print("  reference code %s" % ref)
    root = get_statement(token, ref, url)

    rows = []
    for p in root.iter("OpenPosition"):
        a = p.attrib
        # levelOfDetail SUMMARY rows would double-count against LOT rows.
        if a.get("levelOfDetail") and a["levelOfDetail"].upper() not in ("SUMMARY", ""):
            continue
        sym = a.get("symbol")
        qty = num(a.get("position"))
        if not sym or qty in (None, 0.0):
            continue
        rows.append({
            "sym": sym,
            "conid": a.get("conid"),
            "qty": qty,
            "avg": num(a.get("costBasisPrice")),
            "mark_flex": num(a.get("markPrice")),
            "unreal_flex": num(a.get("fifoPnlUnrealized")),
            "asset_class": a.get("assetCategory"),
            "currency": a.get("currency"),
            "report_date": a.get("reportDate"),
        })

    if not rows:
        fail("Flex returned zero open positions. If the account really is flat, "
             "clear data/ibkr_flex.json by hand - this script refuses to publish "
             "an empty book, because an empty book is also what a misconfigured "
             "query returns.")

    rows.sort(key=lambda r: r["sym"])
    acct = None
    st = root.find(".//FlexStatement")
    if st is not None:
        acct = st.attrib.get("accountId")

    doc = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "IBKR Flex Web Service v3",
        "query_id": str(query_id),
        "account": acct,
        "report_date": rows[0].get("report_date"),
        "positions": rows,
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=True)

    print("OK  wrote %s" % OUT)
    print("  report date %s | %d positions: %s"
          % (doc["report_date"], len(rows), ", ".join(
              "%s %g" % (r["sym"], r["qty"]) for r in rows)))


if __name__ == "__main__":
    main()
