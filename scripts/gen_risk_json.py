# Generates prototypes/risk.json for the dashboard Risk tab.
# All figures measured against a fixed $300,000 notional NAV - never account equity.
import json, io, os

NAV = 300000.0
THEME = 0.02 * NAV      # 2% max loss per theme  = $6,000
PORT = 0.06 * NAV       # 6% max loss portfolio  = $18,000
OUT = os.path.join(r"C:\Users\LANCE\Documents\OneDrive\[03] Cowork", "prototypes", "risk.json")

pos = [
    dict(sym="UNG", name="US Natural Gas Fund", theme="Energy", sub="Natural gas futures",
         qty=2000, px=10.39000035, avg=10.361528, stop=9.35,
         daily=120.0007, unreal=56.9447,
         vol_d=0.019322, vol_a=0.30673, atr=0.299, p5=0.01, p21=0.23, p63=0.49, var_share=0.880),
    dict(sym="XOP", name="SPDR S&P Oil & Gas E&P", theme="Energy", sub="Oil & gas E&P equities",
         qty=23, px=195.19999695, avg=169.50395217, stop=185.00,
         daily=39.78992985, unreal=591.00902985,
         vol_d=0.016300, vol_a=0.25875, atr=4.359, p5=0.14, p21=0.47, p63=0.68, var_share=0.029),
]

for p in pos:
    p["mv"] = p["qty"] * p["px"]
    p["pct_nav"] = p["mv"] / NAV
    p["stop_dist"] = (p["px"] - p["stop"]) / p["px"]
    p["stop_risk"] = p["qty"] * (p["px"] - p["stop"])       # loss from today's mark
    p["stop_vs_cost"] = p["qty"] * (p["stop"] - p["avg"])   # realised P&L if filled
    p["atr_mult"] = (p["px"] - p["stop"]) / p["atr"]
    p["theme_used"] = p["stop_risk"] / THEME
    p["max_shares_theme"] = THEME / (p["px"] - p["stop"])
    p["headroom"] = p["max_shares_theme"] / p["qty"]

gross = sum(p["mv"] for p in pos)
for p in pos:
    p["pct_book"] = p["mv"] / gross

stop_total = sum(p["stop_risk"] for p in pos)
gap_total = 4371.0          # UNG full -20% with no stop protection + XOP at measured beta 0.24
var95, var99 = 704.20, 995.73

doc = {
    "updated": "2026-09-15T11:05:00Z",
    "export_pulled": "15 Sep 2026",
    "source": "Interactive Brokers (live)",
    "vol_window": "18 Jun - 14 Sep 2026 (60 daily bars)",
    "nav": NAV,
    "unit": 0.01 * NAV,
    "limits": {
        "theme_pct": 0.02, "theme_abs": THEME,
        "portfolio_pct": 0.06, "portfolio_abs": PORT,
        "basis": "NAV fixed at the $300,000 notional mandate. Never measured against account equity.",
        "provisional": True, "set_on": "15 Sep 2026"
    },
    "positions": pos,
    "totals": {
        "gross": gross, "gross_pct": gross / NAV, "net_pct": gross / NAV,
        "daily": sum(p["daily"] for p in pos),
        "unreal": sum(p["unreal"] for p in pos),
        "stop_total": stop_total, "stop_pct": stop_total / NAV,
        "gap_total": gap_total, "gap_pct": gap_total / NAV,
        "var95": var95, "var99": var99, "correlation": 0.2840,
        "theme_used": stop_total / THEME, "portfolio_used": stop_total / PORT,
        "theme_used_gap": gap_total / THEME, "portfolio_used_gap": gap_total / PORT,
        "theme_used_var99": var99 / THEME, "portfolio_used_var99": var99 / PORT,
        "themes_live": 1, "themes_supported": PORT / THEME
    },
    "excluded": {
        "sym": "TLT", "qty": 900, "px": 80.40000155, "mv": 900 * 80.40000155,
        "unreal": -11261.722505,
        "reason": "Excluded by the account owner as outside this book. Still held in the same margin account, so account-level margin cannot be ring-fenced to these two positions."
    },
    "scenarios": [
        {"name": "Natural gas -20%", "naive": -4371, "stopped": -2295, "gap": -4371, "trigger": "UNG"},
        {"name": "Energy equities -12%", "naive": -1370, "stopped": -1066, "gap": -1370, "trigger": "XOP"},
        {"name": "Crude -10%", "naive": -1297, "stopped": -858, "gap": -1297, "trigger": "XOP"},
        {"name": "Broad market -3%", "naive": -369, "stopped": -369, "gap": -369, "trigger": None},
        {"name": "Rates +50bp", "naive": -298, "stopped": -298, "gap": -298, "trigger": None},
        {"name": "UNG realised drift, next 21d", "naive": None, "stopped": -847, "gap": None,
         "trigger": "no market move required"}
    ],
    "slippage": [
        {"label": "Clean fill at $9.35", "ung": -2080, "total": -2295},
        {"label": "2% below stop", "ung": -2454, "total": -2669},
        {"label": "5% below stop", "ung": -3015, "total": -3230},
        {"label": "10% below stop", "ung": -3950, "total": -4165},
        {"label": "Full gap - stop gives nothing", "ung": -4156, "total": -4371}
    ],
    "gross_permitted": [
        {"stop": 0.03, "gross": PORT / 0.03, "note": "tight stops, high turnover"},
        {"stop": 0.05, "gross": PORT / 0.05, "note": "levered, actively managed"},
        {"stop": 0.075, "gross": PORT / 0.075, "note": "fully invested, unlevered"},
        {"stop": 0.10, "gross": PORT / 0.10, "note": "your current UNG stop discipline"},
        {"stop": 0.15, "gross": PORT / 0.15, "note": "wide stops, low turnover"},
        {"stop": 0.20, "gross": PORT / 0.20, "note": "conviction holds, little protection"}
    ],
    "limit_rows": [
        {"name": "Portfolio - both stops fill cleanly", "budget": PORT, "cur": stop_total},
        {"name": "Portfolio - gas gap, no stop protection", "budget": PORT, "cur": gap_total},
        {"name": "Portfolio - VaR 99%, correlation-adjusted", "budget": PORT, "cur": var99},
        {"name": "Energy theme - both stops fill cleanly", "budget": THEME, "cur": stop_total},
        {"name": "Energy theme - gas gap, no stop protection", "budget": THEME, "cur": gap_total},
        {"name": "Energy theme - VaR 99%, correlation-adjusted", "budget": THEME, "cur": var99},
        {"name": "Energy theme - VaR 95%, correlation-adjusted", "budget": THEME, "cur": var95},
        {"name": "UNG - position risk at stop", "budget": THEME, "cur": 2080.0},
        {"name": "XOP - position risk at stop", "budget": THEME, "cur": 234.60}
    ],
    "not_configured": [
        "Single-commodity concentration (UNG is 82.2% of the book)",
        "Gross exposure backstop for gap risk",
        "Net exposure range"
    ],
    "regime": {
        "cls": "red", "div": "bearish", "since": "2026-09-10",
        "note": "Read live from regime.json; snapshot held here for the brief."
    },
    "news": [
        {"hot": True,
         "title": "Crude at a four-month high on Saudi pipeline shutdown",
         "body": "Brent traded around $106-110 after rallying more than 9% last week. Saudi Arabia shut its East-West pipeline - roughly 7m b/d to Yanbu, the route that bypasses Hormuz - following drone attacks. WTI near $101.",
         "src": "Bloomberg, Energy Intelligence, Fortune - 13-14 Sep 2026",
         "affects": "XOP, $4,490"},
        {"hot": False,
         "title": "Natural gas at a three-week low on a bearish storage build",
         "body": "Gas fell to about $2.80/MMBtu. The EIA reported a 40 Bcf injection for the week to 4 Sep against roughly 31 Bcf expected, lifting stocks to 3.254 Tcf - some 4.8% above the five-year average. Lower-48 output averages 112.9 Bcf/d in September.",
         "src": "EIA Short-Term Energy Outlook, Trading Economics, NGI - Sep 2026",
         "affects": "UNG, $20,780"}
    ],
    "notes": [
        "NAV is $300,000 throughout - the notional mandate assigned by the firm. Never measured against account equity, by instruction. 1% = $3,000.",
        "Limits are provisional, set 15 Sep 2026: 2% maximum loss per theme, 6% across the portfolio. Not a written company risk policy.",
        "Themes are assigned, not fed. IBKR returns no sector tags; UNG and XOP are both classified Energy as a stated assumption.",
        "Stop distances are shown as probability of being touched over a holding period, not in daily sigma - these are GTC orders with no expiry.",
        "Both stops CONFIRMED as working orders by the account owner, 15 Sep 2026. The API returned status REPLACED, which marks a prior modification, not a cancellation. Defined-risk figures therefore hold. Still unconfirmed: whether they are enabled outside regular trading hours - most gaps occur overnight, which is exactly when a stop is least likely to help.",
        "Parametric VaR understates the tail: historical 5th percentile $751 vs parametric $704; the worst day in the window was $1,449, or 1.46x the 99% VaR.",
        "Correlation of 0.284 is not a usable parameter - standard error 0.121, 95% interval [0.030, 0.503], rolling 20-day range -0.114 to +0.691. Total diversification benefit versus perfect correlation is $108.",
        "Scenario betas are assumed: UNG ~1.0 to front-month gas; XOP ~1.2 to equities, ~1.5 to crude. The XOP leg of the gas shock uses the measured beta of 0.24.",
        "Independently reviewed. The first issue was blocked and reissued: sigma framing replaced with touch probabilities, the -20% gas scenario corrected, and claims of a risk-free position and of diversification withdrawn."
    ]
}

with io.open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=1, ensure_ascii=True)

# ---- assertions: fail loudly rather than ship a wrong file ----
d = json.load(io.open(OUT, encoding="utf-8"))
assert abs(d["totals"]["gross"] - 25269.60) < 0.01, "gross mismatch"
assert abs(d["totals"]["stop_total"] - 2314.60) < 0.01, "stop total mismatch"
assert abs(d["limits"]["theme_abs"] - 6000.0) < 1e-9, "theme budget must be 2% of 300k"
assert abs(d["limits"]["portfolio_abs"] - 18000.0) < 1e-9, "portfolio budget must be 6% of 300k"
assert d["nav"] == 300000.0, "NAV must be the 300k mandate"
assert abs(d["totals"]["theme_used"] - 0.3857667) < 1e-4, "theme usage mismatch"
assert abs(d["totals"]["portfolio_used"] - 0.1285889) < 1e-4, "portfolio usage mismatch"
assert len(d["positions"]) == 2, "expected exactly two positions"
assert all(p["theme"] == "Energy" for p in d["positions"]), "theme tagging changed"
for r in d["limit_rows"]:
    assert r["cur"] <= r["budget"], "unexpected breach: " + r["name"]

print("OK  wrote %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))
print("  gross $%.2f | stop risk $%.2f" % (d["totals"]["gross"], d["totals"]["stop_total"]))
print("  theme used %.1f%% of $%.0f | portfolio used %.1f%% of $%.0f" % (
    100 * d["totals"]["theme_used"], d["limits"]["theme_abs"],
    100 * d["totals"]["portfolio_used"], d["limits"]["portfolio_abs"]))
print("  no limit breaches; %d rows checked" % len(d["limit_rows"]))
