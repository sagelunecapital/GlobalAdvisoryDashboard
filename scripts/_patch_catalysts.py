import json
from pathlib import Path

p = Path("prototypes/screener_movers.json")
data = json.loads(p.read_text(encoding="utf-8"))

DATE = "2026-05-22"
CONT = {"DXYZ", "GFS", "INFQ", "QBTS", "RGTI", "SPOT", "VSH"}

QUANTUM_GID = "quantum-chips-act"
QUANTUM_TICKERS = {"RGTI", "QBTS", "INFQ", "GFS", "QUBT"}
QUANTUM_SUMMARY = (
    "The Trump administration unveiled a $2B CHIPS Act quantum computing initiative on May 22, "
    "with RGTI, QBTS, and INFQ each signing letters of intent for $100M in federal funding to "
    "accelerate domestic quantum R&D - the U.S. government receiving equity stakes in each. "
    "GFS was awarded a proposed $375M to establish a Quantum Technology Solutions foundry business. "
    "QUBT's earnings-driven move was amplified by the sector tailwind, as the funding announcement "
    "reinforced the domestic quantum computing buildout thesis."
)

ENRICHMENT = {
    "AEVA": {
        "catalyst": (
            "AEVA surged on continued post-earnings momentum from Q1 results reported May 6, "
            "where revenue grew 90% YoY to $6.3M alongside an exclusive LiDAR supplier agreement "
            "with a major European OEM. Multiple analysts reiterated Buy ratings with PTs averaging "
            "$26.50 (Canaccord, Roth MKM). The move reflects a lagging re-rating as the market "
            "digested the OEM win and FY2026 revenue guidance of $30-36M."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
    "ATKR": {
        "catalyst": (
            "ATKR extended its post-earnings re-rating after Q2 FY2026 results showed net sales "
            "of $731M - up 11% QoQ and the first quarterly revenue increase since Q4 2022 - with "
            "adj. EPS of $1.23 beating consensus by 16%. Citi raised its PT to $86 on May 22 as "
            "the stock hit a 52-week high of $80.29, affirming that strategic divestitures and "
            "electrical conduit pricing recovery are gaining traction."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
    "DXYZ": {
        "catalyst": (
            "DXYZ surged on reports that SpaceX - its largest holding at ~16% of NAV - is planning "
            "a Nasdaq IPO filing as soon as next week, targeting a valuation of ~$1.75 trillion. "
            "Elon Musk simultaneously announced a merger of xAI into SpaceX, creating a combined "
            "entity markets are calling SpaceXAI. DXYZ trades at a steep premium to NAV, and the "
            "IPO filing news re-opened the SpaceX exposure narrative."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "GFS": {
        "catalyst": (
            "GFS was awarded a proposed $375M CHIPS Act grant to launch a Quantum Technology "
            "Solutions business as a U.S. quantum foundry, part of the Trump administration's "
            "$2B quantum initiative announced May 22 - with the U.S. Commerce Department "
            "receiving an equity stake. Evercore ISI raised its PT to $85 from $58 and "
            "Susquehanna lifted to $125 from $100 following the announcement."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "HPQ": {
        "catalyst": (
            "HPQ surged on pre-earnings positioning ahead of Q2 FY2026 results due May 27, "
            "with JPMorgan raising its PT to $22 from $19 and Morgan Stanley to $17 from $16 "
            "on May 21 - both citing AI PC momentum as AI PCs have exceeded 35% of Personal "
            "Systems shipments. The upgrades triggered short covering, with consensus at "
            "$14.05B revenue and $0.70-0.76 EPS heading into the print."
        ),
        "catalyst_type": "analyst",
        "source": "Claude | Web",
    },
    "IMAX": {
        "catalyst": (
            "IMAX soared after the Wall Street Journal reported the company is exploring a "
            "potential sale and has begun gauging acquirer interest, with Wedbush identifying "
            "Apple, Sony, and Netflix as the most likely buyers. IMAX reaffirmed FY2026 guidance "
            "targeting a record $1.4B in global box office, providing a fundamental floor to "
            "the takeover speculation."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "INFQ": {
        "catalyst": (
            "INFQ jumped on a signed letter of intent for a $100M CHIPS Act award to scale "
            "neutral-atom quantum hardware and expand U.S. manufacturing, part of the Trump "
            "administration's $2B quantum initiative - the U.S. government receiving an equity "
            "stake. The funding directly accelerates INFQ's domestic quantum hardware roadmap."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "LNTH": {
        "catalyst": (
            "LNTH rallied on FDA approval of PYLARIFY TruVu - an upgraded formulation of its "
            "lead radiopharmaceutical - formalizing a key commercial milestone analysts had been "
            "anticipating. Concurrent ASCO 2026 presentations on pipeline candidate LNTH-2403 "
            "added clinical visibility. The move builds on Q1 earnings reported May 7 where "
            "EPS of $1.46 beat consensus of $1.23, with Truist and Citizens both at $115 PTs."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "LPTH": {
        "catalyst": (
            "LPTH continued surging on post-earnings momentum from Q3 FY2026 results reported "
            "May 7 - revenue of $19.1M grew 109% YoY on defense and industrial infrared optics "
            "demand, with gross margin improving to 36% and adj. EBITDA turning positive at $1.1M. "
            "Backlog grew 196% to $110.6M, and insider buying activity on May 20 reinforced "
            "conviction in the recovery trajectory."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
    "NTAP": {
        "catalyst": (
            "NTAP rallied on an expanded strategic partnership with Google Cloud featuring "
            "NetApp Volumes Flex Unified and the NetApp Data Migrator, positioning NTAP as a "
            "key storage layer for enterprise AI workloads on Google Cloud. The announcement "
            "comes ahead of Q4 FY2026 earnings scheduled May 28 (consensus $2.27 EPS, $1.86B "
            "revenue), adding pre-earnings conviction to the partnership catalyst."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "QBTS": {
        "catalyst": (
            "QBTS signed a letter of intent for a $100M CHIPS Act award to accelerate domestic "
            "quantum system fabrication, with the U.S. government receiving an equity stake - "
            "part of the Trump administration's $2B quantum initiative. TD Cowen named QBTS one "
            "of the top three beneficiaries alongside RGTI and GFS, contributing to a ~47% "
            "weekly gain as the funding validates D-Wave's annealing architecture for near-term "
            "commercial deployment."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "QUBT": {
        "catalyst": (
            "QUBT beat Q1 2026 expectations - EPS of -$0.02 vs. -$0.05 consensus and revenue "
            "of $3.7M vs. near-zero prior year, driven by the Luminar Semiconductor and NuCrypt "
            "acquisitions - with management guiding $20-25M in incremental 2026 revenue from "
            "acquired businesses. The earnings beat was amplified by the sector-wide rally on "
            "the Trump administration's $2B CHIPS Act quantum funding announcement."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
    "RDW": {
        "catalyst": (
            "RDW jumped on stacked defense and space contract wins - a multi-year, high "
            "eight-figure NATO Penguin Mk3 UAS award, a $15M U.S. Army Stalker UAS follow-on "
            "(third in eight months, bringing recent Stalker value to $24.8M), and a DARPA "
            "prime designation for the Otter VLEO spacecraft. These extend RDW's record backlog "
            "of $498.1M, with Q1 revenue already up 57.9% YoY to $97M."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "RGTI": {
        "catalyst": (
            "RGTI signed a letter of intent with the U.S. Commerce Department for up to $100M "
            "in CHIPS Act funding over three years to accelerate superconducting quantum computing "
            "R&D, with the federal government receiving an equity stake. TD Cowen named RGTI one "
            "of the top three CHIPS quantum beneficiaries, with the stock up ~47% for the week "
            "as government validation reinforced RGTI's position in the domestic quantum buildout."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "SHAZ": {
        "catalyst": (
            "SHAZ surged after announcing the closing of an Oaktree Capital-led $350M convertible "
            "senior notes offering, with proceeds earmarked for GPU procurement and network "
            "build-out supporting a $950M five-year AI cloud deployment deal. The institutional "
            "debt raise signals external validation of SHAZ's AI neocloud strategy, with the "
            "2031 notes aligned to the company's infrastructure deployment timeline."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "SMTC": {
        "catalyst": (
            "SMTC gained on pre-earnings positioning ahead of Q1 FY2027 results due May 26, "
            "with Oppenheimer raising its PT to $150 from $110 - the most aggressive in a cluster "
            "of upgrades from Robert W. Baird and CFRA. The market is pricing a ~22% earnings "
            "reaction, underpinned by SMTC's LoRa IoT and AI data center semiconductor momentum "
            "with prior quarter net sales of $251M up 22% YoY."
        ),
        "catalyst_type": "analyst",
        "source": "Claude | Web",
    },
    "SPOT": {
        "catalyst": (
            "SPOT rallied after its May 21 Investor Day unveiled 2030 targets of $100B revenue, "
            "1 billion subscribers, 35-40% gross margin, and >20% operating margin - materially "
            "above prior consensus. SPOT simultaneously announced a landmark generative AI "
            "licensing deal with Universal Music Group enabling Premium subscribers to create "
            "AI-powered covers and remixes. Canaccord raised its PT to $720 following the event."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "UTI": {
        "catalyst": (
            "UTI surged after S&P Dow Jones Indices announced the stock will join the S&P "
            "SmallCap 600 effective May 27, triggering forced buying from passive index trackers. "
            "Multiple analysts raised PTs in response with the highest target reaching $49. "
            "Q2 FY2026 revenue of $221.4M slightly beat expectations, validating UTI's "
            "institutional quality threshold for index inclusion."
        ),
        "catalyst_type": "other",
        "source": "Claude | Web",
    },
    "VSH": {
        "catalyst": (
            "VSH jumped after Q1 2026 earnings beat on all fronts - revenue of $839.2M vs. "
            "$822.8M consensus and EPS of $0.05 vs. $0.03 est. - alongside Q2 guidance of "
            "$875-905M exceeding Street estimates of ~$858M. A book-to-bill of 1.34 and 5.7 "
            "months of backlog signal a meaningful passive component upcycle. BofA raised its "
            "PT to $28 from $18 following the results."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
    "ZM": {
        "catalyst": (
            "ZM surged after Q1 FY2027 earnings beat across the board - revenue of $1.239B "
            "grew 5.5% YoY, the strongest recent growth rate, beating consensus by ~$20M, "
            "with adj. EPS of $1.55 vs. $1.42 and a non-GAAP operating margin of 41.1%. "
            "The board added $1B to the buyback authorization on top of $625M remaining, "
            "with Citi, Benchmark, and Baird all raising PTs after the print."
        ),
        "catalyst_type": "earnings",
        "source": "Claude | Web",
    },
}

movers = data["by_date"].get(DATE, [])
for m in movers:
    t = m["ticker"]
    if t in ENRICHMENT:
        m.update(ENRICHMENT[t])
    m["continuation"] = t in CONT
    if t in QUANTUM_TICKERS:
        m["group_id"] = QUANTUM_GID
        m["group_summary"] = QUANTUM_SUMMARY

data["by_date"][DATE] = movers
p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print("Done.")
for m in movers:
    g = "[GRP]" if m.get("group_id") else "     "
    c = "[C]" if m.get("continuation") else "   "
    print(f"  {c} {g} {m['ticker']:6}  {m.get('catalyst_type','?'):10}  {m.get('change_pct', 0):+.2f}%")
