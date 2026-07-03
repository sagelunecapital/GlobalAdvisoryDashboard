# My Momentum Framework (v1)

**Owner:** Lance · **Drafted:** 2026-06-16
**Patterned off:** Prime Trading (TradersLab) · Julian Komar · Matt Caruso
**Companion doc:** `momentum-systems-synthesis.md` (the source study + citations)

> Every decision below is mine; the **Precedent** column shows how the three reference systems handle the same dimension, so each rule is anchored to real practice. ✅ = the precedent is primary-source-verified.

---

## Decision Table

| # | Dimension | My rule | Precedent (Prime / Komar / Caruso) |
|---|---|---|---|
| 1 | **Universe** | **US core** as the primary book; **selective HK/CN** names that clear the same RS + liquidity bar. | Komar: US growth only ✅. Caruso: US-centric ✅. Prime: "liquid leaders showing RS," market-agnostic ✅. → I take Komar's US core + Prime's RS/liquidity-agnostic logic for Asian adds. |
| 2 | **Fundamentals** | **Soft preference** — a conviction booster / tiebreaker, not a hard exclusion. Strong growth raises conviction; won't reject a name on weak/early earnings if RS + structure are excellent. | Komar + Caruso: **hard gate** (Caruso screens growth FIRST ~10,000→150, then RS; Komar bars negative EPS) ✅. Prime: no fundamental gate ✅. → I sit between: closer to Prime on gating, but I use fundamentals like Komar/Caruso to size conviction. |
| 3 | **Screening / leadership bar** | RS measured **relative to each name's own market** (US vs S&P; HK/CN vs HSI/CSI), but a candidate must clear **top-decile RS AND the full Minervini trend template** (price > 50 > 150 > 200 DMA, 200 rising). | Komar: RS > 90 + new RS high ✅. Minervini: trend template ⚪. Caruso: RS strong vs market ✅. → I localize the RS comparison (my cross-market adaptation) but keep the strict top-decile + trend-template gate. |
| 4 | **Entry bias** | **Both breakouts and pullbacks**, chosen by setup (Komar's 4 types: pullback, breakout, cheater breakout, gap-up). | Komar: all four, co-equal ✅. Prime + Caruso: contraction/pullback only, **avoid chasing breakouts** ✅. → I'm on Komar's flexible side. |
| 5 | **Entry execution** | **Full size at the trigger** — no scale-in. | Komar: scale 50/30/20, then pyramid ✅. Prime: de-risk fast, add ✅. → I diverge: single full commit. *Implication: trigger precision + the structural stop carry more weight since there's no averaging cushion.* |
| 6 | **Risk per trade** | **Fixed ~1% of capital.** Position size = 1% ÷ stop distance. | Komar: exactly this ✅. Prime: tiered 0.25 / 0.5 / 1% by conviction ✅. Caruso: per-invalidation-level ✅. → I take Komar's flat 1%. |
| 7 | **Stop / invalidation** | **Structural** — below the setup (below the 25-day EMA structure / coil low / base low). R varies with setup tightness; tighter setups → tighter stops → larger size. | Prime: below 21-DMA structure ✅. Caruso: "invalidation level" / low of final coil bar ✅. → Same structural logic, on the **25-day EMA**. |
| 8 | **Profit-taking / exits** | **Governing rule: pocket ~67% of open profit by trade maturity.** Mechanic: sell **⅓ at +2 ATR** (first de-risk); hold **⅔ runner** until the **25-day EMA breaks on a daily close**. ~⅓ of the runner is **flexible** — trimmed discretionarily to manage volatility. | Prime: sell ⅓ at **2R**, hold ⅔ runner to **21-DMA** break on daily close ✅. → I keep Prime's trim-and-runner shape but: ATR-based first target (not R), **25-EMA** (not 21-DMA), the **67%-banked north star** as primary, plus a discretionary volatility trim. |
| 9 | **Earnings handling** | **Hold through earnings: at least ⅓, at most ⅔.** Carry MORE (toward ⅔) when **all four** align: large open profit cushion · healthy market regime · high conviction/strong setup · cheap/effective put hedge. Protect the held runner with **name puts as an event hedge** around the print. | Komar: **reduces** before earnings (opposite) ✅. Prime/Caruso: silent on options. → **My distinct layer:** deliberate earnings exposure + targeted put hedge. No reference system hedges with options. |
| 10 | **Portfolio heat** | **[TO CALIBRATE]** Starting default: **5% total open-risk cap** (≈5 full-risk names at 1% each), build up slowly; recalibrate from live experience. | Komar: limit portfolio risk to 5%, "build up slowly" ✅. Minervini: progressive exposure ⚪. → Adopted as a provisional default; no live overexposure experienced yet. |
| 11 | **Timing governor** | **Market-regime filter** — gate new buys on index/breadth health (dashboard's MMTH / NCFD / NHNL + index above key MAs). Press exposure only when the broad tape confirms. | Prime: stock-level extension governor (21-DMA cycle counter + Z-score, caution at +3σ) ✅. → I chose the market-level filter; *optional later layer:* add Prime's stock-level extension governor on top (top-down + bottom-up). |

---

## My Framework in One Paragraph

Trade top-decile RS leaders (RS scored vs each name's own market) that pass the full trend template — US as the core book, selective HK/CN adds on the same bar. Fundamentals raise conviction but don't gate. Take whatever entry the chart offers (pullback, breakout, cheater, gap-up), committing **full size at the trigger** with **1% risk** sized off a **structural stop below the setup**. Manage the winner to **bank ~67% of profit**: trim **⅓ at +2 ATR**, run the **⅔ to a 25-EMA break**, with a flexible volatility trim on part of the runner. **Hold ⅓–⅔ through earnings**, sizing the carry up when cushion + regime + conviction + a cheap hedge all line up, and **hedge that runner with name puts**. Only press new exposure when the **market-regime filter** (breadth + index trend) is green.

---

## Where I Diverge From All Three (my edges to validate)

1. **Cross-market localized RS** — none of the three trade a US+Asia book; I localize the RS benchmark per market. *Validate: does a HK/CN local-RS leader perform like a US S&P-RS leader?*
2. **Full size at trigger** — all three scale in. *Validate: does single-shot entry cost me on slightly-early triggers vs. the simplicity gain?*
3. **Hold through earnings + put hedge** — Komar reduces before earnings; the others ignore options. *Validate: does the post-earnings continuation edge net of put cost beat sidestepping the event?*
4. **25-EMA runner vs 21-DMA** — slightly later/smoother trend-break exit than Prime. *Validate: backtest 25-EMA vs 21-DMA exit on my names.*

## Open Items / To Calibrate
- **Portfolio heat cap** (#10): provisional 5%; set from live data.
- **The "flexible ⅓ of runner"** (#8): define the discretionary trim trigger more precisely once there's a track record.
- **Optional:** layer Prime's stock-level extension governor (+3σ) on top of the market-regime filter.
- **Entry-trigger specs:** document exact breakout vs. pullback trigger rules per Komar's 4 entry types.
