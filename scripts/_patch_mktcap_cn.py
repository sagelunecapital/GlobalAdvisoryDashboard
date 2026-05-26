#!/usr/bin/env python3
"""
Patch screener_movers.json (US mkt cap corrections) and
screener_movers_cn.json (HK mkt cap + full catalyst enrichment).
Run once from project root: python scripts/_patch_mktcap_cn.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
US_FILE = ROOT / "prototypes" / "screener_movers.json"
CN_FILE = ROOT / "prototypes" / "screener_movers_cn.json"

# ── US 2026-05-22 corrected market caps (USD) ─────────────────────────────────
US_MKT_CAP = {
    "AEVA":  1_210_000_000,
    "ATKR":  2_570_000_000,
    "DXYZ":    962_000_000,
    "GFS":  47_640_000_000,
    "HPQ":  22_000_000_000,
    "IMAX":  2_000_000_000,
    "INFQ":  3_570_000_000,
    "LNTH":  6_800_000_000,
    "LPTH":    904_000_000,
    "NTAP": 26_180_000_000,
    "QBTS": 10_730_000_000,
    "QUBT":  2_780_000_000,
    "RDW":   3_040_000_000,
    "RGTI":  8_790_000_000,
    "SHAZ":    200_000_000,
    "SMTC": 15_230_000_000,
    "SPOT": 107_000_000_000,
    "UTI":   2_210_000_000,
    "VSH":   6_430_000_000,
    "ZM":   25_500_000_000,
}

# ── HK/CN 2026-05-22 enriched movers (HKD) ───────────────────────────────────
CN_AI_SUPPLY = "china-ai-supply-chain"
CN_AI_SUPPLY_SUM = (
    "981, 2382, and 148 all surged on China's accelerating AI infrastructure buildout - "
    "driving demand for advanced semiconductors (981), high-pixel optical modules (2382), "
    "and copper clad laminate for AI server PCBs (148). "
    "The US-China tariff truce announced May 12 - reducing tariffs from 145% to 30% - "
    "provided an additional re-export tailwind for the entire supply chain group."
)

CN_AI_AUTO = "china-ai-automation"
CN_AI_AUTO_SUM = (
    "9880 and 6651 are both pure-play Chinese AI automation names re-rating on structural growth. "
    "9880 reported 53% revenue growth in 2025 as full-size humanoid robots became its largest segment, "
    "while 6651 commands 53.5% of China's L3+ simulation market on the back of its NVIDIA Global L4 partnership. "
    "Accelerating robotaxi city approvals and industrial robot subsidies in China drove institutional accumulation in both."
)

CN_EV_INDUSTRIAL = "china-ev-industrial"
CN_EV_INDUSTRIAL_SUM = (
    "3898 and 179 both rallied on China's NEV penetration rate exceeding 50% for the first time - "
    "3898 via traction power systems for high-speed rail and EV inverters, "
    "179 via precision motors and actuators embedded across EV drivetrains and HVAC systems. "
    "Incremental 2026-2027 rail capex announcements added a second growth leg for 3898."
)

CN_ENRICHED = {
    "981": {
        "mkt_cap": 566_000_000_000,
        "catalyst": (
            "981 rallied after Q1 2026 results showed a sustained recovery, with co-CEO Zhao Haijun guiding Q2 revenue "
            "to rise 14-16% sequentially on AI chip and automotive chip demand. "
            "Orders from overseas clients are growing as tight capacity at foreign foundries redirects production to SMIC. "
            "The results validated 981 as the primary beneficiary of China's semiconductor self-sufficiency push."
        ),
        "catalyst_type": "guidance",
        "source": "Claude | Web",
        "group_id": CN_AI_SUPPLY,
        "group_summary": CN_AI_SUPPLY_SUM,
    },
    "2382": {
        "mkt_cap": 72_510_000_000,
        "catalyst": (
            "2382 surged after May 2026 monthly shipment data showed handset lens sets at 98.1M units and "
            "vehicle lens sets at 10.71M units - both above consensus. "
            "This followed FY2025 net income of RMB 4.64B, beating estimates of RMB 3.72B by 25%, "
            "alongside a dividend increase and plans to spin off the vehicle optics unit. "
            "The AI smartphone optical upgrade cycle and automotive vision sensor ramp are dual demand drivers."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
        "group_id": CN_AI_SUPPLY,
        "group_summary": CN_AI_SUPPLY_SUM,
    },
    "148": {
        "mkt_cap": 61_900_000_000,
        "catalyst": (
            "148 jumped as China's AI server buildout triggered a new order cycle for copper clad laminate - "
            "Kingboard's core product and an irreplaceable input for every server PCB. "
            "As the largest CCL producer in China, 148 is a direct beneficiary of domestic hyperscaler capex. "
            "The US-China tariff truce reducing duties from 145% to 30% added a margin recovery catalyst."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
        "group_id": CN_AI_SUPPLY,
        "group_summary": CN_AI_SUPPLY_SUM,
    },
    "179": {
        "mkt_cap": 25_050_000_000,
        "catalyst": (
            "179 rose alongside the broader auto-parts rally as China's NEV penetration rate exceeded 50% for the first time. "
            "Johnson Electric's precision motors and actuators are embedded in EV drivetrains, HVAC, and locking systems "
            "across major Chinese OEMs. "
            "Improving gross margins (23.6% in the interim period) and robust order flow from EV customers supported the re-rating."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
        "group_id": CN_EV_INDUSTRIAL,
        "group_summary": CN_EV_INDUSTRIAL_SUM,
    },
    "2643": {
        "mkt_cap": 12_950_000_000,
        "catalyst": (
            "2643 surged after reporting its first-ever adjusted quarterly profit - driven by higher vehicle utilisation rates, "
            "reduced subsidy reliance, and improved unit economics across its Geely-backed EV ride-hailing fleet. "
            "Management announced plans to scale robotaxi deployments in China and expand internationally, "
            "re-framing 2643 from an unprofitable ride-hailer to a self-sustaining mobility platform."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
        "group_id": None,
        "group_summary": None,
    },
    "3898": {
        "mkt_cap": 69_740_000_000,
        "catalyst": (
            "3898 rallied on China's accelerating high-speed rail infrastructure spending, with the Ministry of Railways "
            "confirming incremental 2026-2027 capex that directly feeds 3898's traction inverter and converter order book. "
            "NEV sector momentum added a secondary tailwind via its industrial power module segment supplying EV OEMs. "
            "The dual rail-plus-EV exposure gives 3898 visibility on both infrastructure and consumer EV cycles."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
        "group_id": CN_EV_INDUSTRIAL,
        "group_summary": CN_EV_INDUSTRIAL_SUM,
    },
    "6651": {
        "mkt_cap": 21_700_000_000,
        "catalyst": (
            "6651 surged on continued momentum from its NVIDIA Global L4 Autonomous Driving Simulation partnership "
            "- announced at GTC March 2026 - where 51WORLD's SimOne platform integrates with NVIDIA Omniverse NuRec "
            "to create closed-loop simulation from real-world fleet data. "
            "6651 commands 53.5% of China's L3+ simulation market, and accelerating city-level robotaxi approvals "
            "in Q1-Q2 2026 drove institutional accumulation to fresh post-IPO highs."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
        "group_id": CN_AI_AUTO,
        "group_summary": CN_AI_AUTO_SUM,
    },
    "9880": {
        "mkt_cap": 62_400_000_000,
        "catalyst": (
            "9880 rallied as UBTECH reported 2025 operating revenue of RMB 2.0B - up 53.3% YoY - "
            "with full-size humanoid robots now the largest revenue segment. "
            "China's industrial robot deployment subsidies and a visible order pipeline from automotive OEMs "
            "deploying Walker-series robots in factory automation drove the re-rating. "
            "The humanoid robot sector remains a high-conviction domestic AI hardware theme for institutional investors."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
        "group_id": CN_AI_AUTO,
        "group_summary": CN_AI_AUTO_SUM,
    },
}

# ── Patch US file ─────────────────────────────────────────────────────────────
us_data = json.loads(US_FILE.read_text(encoding="utf-8"))
us_by_date = us_data.get("by_date", {})

patched = 0
for mover in us_by_date.get("2026-05-22", []):
    ticker = mover.get("ticker", "")
    if ticker in US_MKT_CAP:
        mover["mkt_cap"] = US_MKT_CAP[ticker]
        patched += 1

US_FILE.write_text(json.dumps(us_data, indent=2), encoding="utf-8")
print(f"[patch] US: updated {patched} mkt_cap values for 2026-05-22")

# ── Patch CN file ─────────────────────────────────────────────────────────────
cn_data = json.loads(CN_FILE.read_text(encoding="utf-8"))
cn_by_date = cn_data.get("by_date", {})

# Remove stale 2026-05-23 duplicate (wrong date key from before safe_trading_day fix)
if "2026-05-23" in cn_by_date:
    del cn_by_date["2026-05-23"]
    print("[patch] CN: removed stale 2026-05-23 duplicate entry")

cn_patched = 0
for mover in cn_by_date.get("2026-05-22", []):
    ticker = mover.get("ticker", "")
    if ticker in CN_ENRICHED:
        patch = CN_ENRICHED[ticker]
        mover["mkt_cap"] = patch["mkt_cap"]
        mover["catalyst"] = patch["catalyst"]
        mover["catalyst_type"] = patch["catalyst_type"]
        mover["source"] = patch["source"]
        if patch.get("group_id"):
            mover["group_id"] = patch["group_id"]
            mover["group_summary"] = patch["group_summary"]
        cn_patched += 1

cn_data["by_date"] = cn_by_date
CN_FILE.write_text(
    json.dumps(cn_data, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"[patch] CN: enriched {cn_patched} movers for 2026-05-22")
print("[patch] Done.")
