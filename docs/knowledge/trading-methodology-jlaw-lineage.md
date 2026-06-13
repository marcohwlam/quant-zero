# Trading Methodology: The J Law Lineage

**Purpose:** Actionable, codifiable knowledge base for systematic quant trading — daily/weekly swing-to-position horizon (holding days to months). This is NOT minute-level or intraday methodology.

**Last updated:** 2026-06-12

---

## Table of Contents

1. [William O'Neil — CAN SLIM](#1-william-oneil--can-slim)
2. [Mark Minervini — SEPA / Trend Template / VCP](#2-mark-minervini--sepa--trend-template--vcp)
3. [Stan Weinstein — Stage Analysis](#3-stan-weinstein--stage-analysis)
4. [Nicolas Darvas — Box Theory](#4-nicolas-darvas--box-theory)
5. [Mark Douglas — Trading Psychology](#5-mark-douglas--trading-psychology)
6. [Jack Schwager — Market Wizards Synthesis](#6-jack-schwager--market-wizards-synthesis)
7. [Secondary Lineage: Zanger, Grimes, Elder, Lynch, Buffett](#7-secondary-lineage)
8. [Synthesis A: The Integrated J Law Workflow](#synthesis-a-the-integrated-j-law-workflow)
9. [Synthesis B: Systematic / Quant Translation](#synthesis-b-systematic--quant-translation)

---

## 1. William O'Neil — CAN SLIM

**Primary source:** *How to Make Money in Stocks* (William O'Neil, IBD)

### 1.1 CAN SLIM — Letter-by-Letter Thresholds

| Letter | Factor | Quantitative Threshold |
|--------|--------|----------------------|
| **C** | Current quarterly EPS | ≥ 25% growth vs. same quarter prior year; accelerating preferred; prior quarter also ≥ 25% |
| **C** | Current quarterly sales | ≥ 25% growth, OR above the trailing-twelve-month growth rate (acceleration signal) |
| **A** | Annual EPS growth | ≥ 25% per year for each of the last 3 years; ROE ≥ 17% |
| **A** | Annual projected EPS | ≥ 25% forward estimate |
| **N** | New product/service/management/price high | Price must be nearer to its 52-week high than its 52-week low; new fundamental catalyst present |
| **S** | Supply (shares outstanding / float) | Preference for smaller-float stocks (< 25M shares is cited by O'Neil screener implementations; buybacks are positive); big-volume breakout from a stock with low supply = outsized move |
| **L** | Leader (Relative Strength Rating) | RS Rating ≥ 80 (O'Neil specifies 80 as the minimum; best performers typically show 87–99); avoid laggards with RS < 70 |
| **I** | Institutional sponsorship | Increasing number of institutional owners; minimum ~20 institutions owning shares; avoid stocks that are the most widely held (top 50 most-held) — too crowded; prefer funds with strong 3-year performance records |
| **M** | Market direction | Must be in confirmed uptrend (IBD calls "Confirmed Uptrend"); reduce or eliminate exposure during "Uptrend Under Pressure" or "Market in Correction" |

**Notes on precision:**
- The 25% thresholds for C and A are O'Neil's stated minimums and are widely confirmed across IBD material.
- The ROE 17% figure appears in O'Neil's screener implementations and is consistent with his text.
- The RS Rating 80 minimum is O'Neil's stated floor; he prefers 80–99 at purchase.
- Float < 25M shares is a common implementation of O'Neil's supply principle; O'Neil does not give an exact share count in the main text but emphasizes smaller supply.

### 1.2 Relative Strength (RS) Rating

- Scale: 1–99 (percentile rank vs. all listed stocks)
- Calculation: 12-month price change, with the most recent 3-month period weighted 40% and each of the three preceding quarters weighted 20% each
- O'Neil's threshold: **RS ≥ 80** to qualify as a leader; ideally 87–99 at time of purchase
- The RS *line* (price vs. market index, plotted separately) should ideally be making new highs at or before the stock's price breaks out — a leading RS line is a confirming signal

### 1.3 Cup-with-Handle Pattern

| Parameter | Rule |
|-----------|------|
| Prior uptrend required | ≥ 30% advance before the base forms |
| Cup duration | 7 to 65 weeks (most valid cups: 3–6 months on weekly chart) |
| Cup depth | 12% to 33% in normal markets; up to ~50% in severe bear markets; ideally corrects ≤ 1/3 of prior advance |
| Cup shape | Round, U-shaped (not V-shaped); right side should rebuild on declining then increasing volume |
| Handle duration | 1 to 4 weeks (ideally); at minimum 1 week |
| Handle depth | Typically ≤ 10–15% below the cup's right rim; must form in the **upper half** of the cup's price range (i.e., above the cup's midpoint) |
| Handle volume | Volume should contract (dry up) during handle formation — signal that selling pressure is exhausted |
| Pivot/buy point | The high of the handle's consolidation + $0.10 (10 cents above the handle's intraday high) |
| Buy zone | From the pivot up to **5% above the pivot** — do not buy more than 5% past the breakout point |
| Volume on breakout | ≥ 40–50% above the stock's 50-day average daily volume on breakout day; at minimum materially above average |

**Other O'Neil bases:** Flat base (5–7 weeks, correction < 15%), double-bottom base (corrects ~20–35%, forms W shape), ascending base (3 pullbacks each ~10–20% in an uptrend).

### 1.4 Sell Rules

**Defensive sells (cutting losses):**
- **7–8% stop loss rule:** Sell any stock that falls 7–8% below your purchase price, without exception. This is O'Neil's primary risk control.
- Never average down into a losing position.

**Offensive sells (locking in gains):**
- **20–25% profit target:** Take at least partial profits when a stock gains 20–25% from a proper breakout (unless the stock gained 20% in fewer than 3 weeks — "8-week hold rule" below)
- **8-week hold rule:** If a stock gains 20%+ within 3 weeks of breakout, it may be a potential big winner — hold for at least 8 weeks before evaluating full exit
- **Climax top signals:** Wide-range day on extreme volume, largest 1-day gain since the move began, gap up on exhaustion volume — take profits into these
- **Distribution days (market-level sell signal):** When 4–5 distribution days cluster within a 4-week period on a major index (Nasdaq, S&P 500), reduce exposure or go to cash. Distribution day = index closes down ≥ 0.2% on volume **higher** than the prior session.
- **Follow-through day (re-entry signal):** After a correction, a rally attempt that produces a strong close (typically up 1.5%+) on volume higher than the prior day, occurring on **Day 4 or later** of the rally attempt, confirms a potential new uptrend.

### 1.5 Market Direction (M) — IBD Market Calls

| Market Condition | Action |
|-----------------|--------|
| Confirmed Uptrend | Full exposure; buy breakouts aggressively |
| Uptrend Under Pressure | Reduce new buys; tighten stops |
| Market in Correction | No new purchases; raise cash; hold only best positions |

The M factor is O'Neil's acknowledgment that ~75% of stocks follow the overall market direction. This is the portfolio-level risk filter — no matter how good the individual stock setup, buying against a market in correction dramatically reduces success rates.

---

## 2. Mark Minervini — SEPA / Trend Template / VCP

**Primary sources:** *Trade Like a Stock Market Wizard* (2013), *Think & Trade Like a Champion* (2017)

### 2.1 SEPA — Five Elements

SEPA = Specific Entry Point Analysis. The five elements must **all align** before a trade is taken:

| Element | Definition |
|---------|-----------|
| **Trend** | Stock must be in a Stage 2 uptrend as defined by the Trend Template (see 2.2) |
| **Fundamentals** | Accelerating earnings and revenue growth; improving margins; EPS acceleration preferred (typically ≥ 20% YoY, with recent quarters showing acceleration) |
| **Catalyst** | An identifiable fundamental trigger: new product, earnings beat, guidance raise, regulatory approval, sector tailwind — something institutions are buying in response to |
| **Entry** | Specific low-risk entry point, typically the VCP pivot breakout; entry only at the precise pivot, not chased |
| **Exit** | Pre-planned stop loss and profit-taking rules defined before entry; both defensive and offensive exits planned |

### 2.2 The 8-Point Trend Template

All 8 criteria must be satisfied simultaneously. A stock failing any single criterion is not a buy candidate.

| # | Criterion | Exact Threshold |
|---|-----------|----------------|
| 1 | Price vs. 150-day MA | Current price **above** the 150-day (30-week) MA |
| 2 | Price vs. 200-day MA | Current price **above** the 200-day (40-week) MA |
| 3 | MA stack: 150 vs. 200 | 150-day MA **above** the 200-day MA |
| 4 | 200-day slope | 200-day MA is trending upward — **higher than it was 30 days ago** (ideally rising for 4–5 months or longer) |
| 5 | 50-day dominance | 50-day MA **above** both the 150-day and the 200-day MAs |
| 6 | Price vs. 50-day MA | Current price **above** the 50-day MA |
| 7 | Distance from 52-week low | Current price **at least 30% above** its 52-week low |
| 8 | Proximity to 52-week high | Current price **within 25% of** its 52-week high (the closer to new high, the better) |
| 8+ | Relative Strength | RS Rating **≥ 70**, preferably in the 80s or 90s |

**MA convention note:** Minervini uses simple moving averages (SMA). The 150-day SMA ≈ 30-week SMA. The 200-day SMA ≈ 40-week SMA.

The template is essentially a codified Stage 2 definition (see Weinstein, Section 3), operationalized with daily MA arithmetic.

### 2.3 VCP — Volatility Contraction Pattern

The VCP is Minervini's primary entry setup. It identifies the final consolidation before a Stage 2 stock makes its next leg up.

**Structure:**
1. A stock in confirmed Stage 2 uptrend (Trend Template = pass) pauses and forms a series of progressively tighter contractions
2. Each contraction's depth is approximately **half** the prior contraction's depth (the 50% rule of thumb)
3. Volume **declines** into each successive contraction, reaching a "dry-up" at the final low

| Parameter | Specification |
|-----------|--------------|
| Number of contractions | 2–6 total; 3 is typical; minimum 2 |
| Contraction depth sequence (example) | ~18% → ~12% → ~6% (each ~50% of prior) |
| First contraction depth range | Typically 10–25%, lasting 2–6 weeks |
| Second contraction depth range | Typically 7–15%, lasting 1–4 weeks |
| Third (final) contraction depth range | Typically 3–8%, lasting 1–3 weeks |
| Total pattern duration | 4–12 weeks (first contraction through breakout) |
| Higher lows required | Each contraction's bottom must be **higher than** the previous contraction's bottom |
| Volume at contraction lows | Should be **40–50% below** average daily volume — "dry-up" indicates sellers exhausted |
| Pivot definition | The **high of the final (tightest) contraction** |
| Breakout entry | Price crosses above the pivot on rising volume |
| Breakout volume requirement | **40–50% above** average daily volume on breakout day; light-volume breakouts (≤ 10–20% above average) frequently fail |
| Stop placement | Just below the final contraction's low |

**Footprint concept:** Minervini refers to each high-low oscillation as a "contraction" or "footprint." A pattern with 3 contractions (T = 3 footprints) is described as a 3T VCP. More contractions = more refined sellers exhausted = higher-quality setup (in theory).

### 2.4 Risk Management and Position Sizing

| Rule | Parameter |
|------|-----------|
| Maximum account risk per trade | 1.25%–2.5% of total equity |
| Hard stop | 7–8% below entry (tighter on low-ATR setups; wider only in rare high-conviction situations) |
| Minimum gain-to-loss ratio | 2:1 to 3:1 before entry |
| Initial position size | Starter position (e.g., 50% of intended full size) at the pivot breakout |
| Pyramiding (adding) | Add to confirmed winners on subsequent strength; never average down |
| Partial profit-taking | At 2–3R (2× to 3× risk), take partial profits; move stop to breakeven on remainder |
| Trailing the remainder | Trail stop behind subsequent bases or MAs |
| Never average down | A core absolute — if a position moves against you, do not add; cut it |

**Win-rate math (Minervini's framework):** A trader with a 50% win rate, average win of 20%, and average loss of 7% produces a positive expectancy:
`E = (0.5 × 0.20) + (0.5 × -0.07) = 0.10 - 0.035 = +0.065 (6.5% per trade)`

Minervini's actual reported results have significantly higher win rates (60–70%+) in championship periods with tighter average losses.

---

## 3. Stan Weinstein — Stage Analysis

**Primary source:** *Secrets for Profiting in Bull and Bear Markets* (Stan Weinstein, 1988)

### 3.1 The Four Stages

Weinstein maps every stock into one of four lifecycle stages using the **30-week simple moving average (SMA)** on **weekly charts**.

| Stage | Name | 30-Week MA | Price Action | Volume Pattern | Action |
|-------|------|-----------|--------------|----------------|--------|
| **1** | Basing/Accumulation | Flattening (near-flat) | Sideways; below prior highs, above prior lows | Declining or flat | Wait; do not buy |
| **2** | Advancing/Markup | Rising | Making higher highs and higher lows; price above rising 30-week MA | Up weeks on above-avg volume; down weeks on below-avg volume | **BUY** — this is the only stage to own stocks |
| **3** | Topping/Distribution | Flattening after rising | Erratic; large swings; price starts failing the 30-week MA | High volume on down moves; weak rallies on low volume | Sell; do not buy |
| **4** | Declining/Markdown | Declining | Lower highs and lower lows; price below declining 30-week MA | Down weeks on above-avg volume | Never buy; sell short if appropriate |

### 3.2 Stage Identification Rules

**Stage 1 → Stage 2 (Breakout — buy signal):**
- Price breaks above the trading range ceiling (horizontal resistance) that defined Stage 1
- The 30-week MA turns from flat to upward-sloping
- Breakout week volume: ideally **2–3× the stock's average weekly volume** (Weinstein's stated confirmation requirement)
- Entry: buy the breakout, or on the first pullback to the breakout level (now support)

**Stage 2 continuation characteristics:**
- Price consistently holds above the rising 30-week MA
- Up weeks outnumber down weeks; up weeks generally have higher volume than down weeks
- Making new highs on expanding volume

**Stage 2 → Stage 3 (Topping signal — exit):**
- 30-week MA begins to flatten
- Price oscillates around the 30-week MA rather than holding above it cleanly
- Distribution: high-volume down weeks interspersed with low-volume up weeks

**Stage 3 → Stage 4 (Markdown — avoid/short):**
- Price breaks below the 30-week MA support convincingly
- 30-week MA turns downward
- Lower highs and lower lows established

**Relative strength context:** Weinstein also considers the stock's 30-week MA relative to its sector index. A stock breaking out while its sector is also in Stage 2 is a higher-confidence trade.

### 3.3 Key Practitioner Rules

- **Never buy in Stage 4.** Not even "cheap" — Stage 4 declines often continue far beyond where they look oversold.
- **Never buy in Stage 3** — the distribution phase; selling into rallies, not buying them.
- **Stage 1 is waiting room.** Monitoring stocks building bases in Stage 1 for a Stage 2 breakout is how Weinstein builds his watchlist.
- **Weekly chart is primary.** Daily charts are used for entry timing only; the stage call is always weekly.

---

## 4. Nicolas Darvas — Box Theory

**Primary source:** *How I Made $2,000,000 in the Stock Market* (Nicolas Darvas, 1960)

### 4.1 The Techno-Fundamentalist Filter

Darvas coined the term "techno-fundamentalist" to describe his dual-filter approach:

**Fundamental filter (qualitative, not quantitative):**
- Industries and companies he expected to grow significantly over the next 10–20 years (Darvas focused on technology and defense in the late 1950s)
- Companies showing consistently strong earnings, especially during broad market volatility
- Strong earnings growth (Darvas did not specify an exact % threshold; contemporary interpretations commonly use ≥ 25–30% EPS growth, aligning with O'Neil)
- Preference for companies with dominant market positions in growth industries

**Technical filter:**
- Stock must be making **new all-time highs** or be at multi-year highs — Darvas only bought stocks that were going up, never "bargains" or falling stocks

### 4.2 Box Construction Rules

| Rule | Definition |
|------|-----------|
| Box ceiling | The recent significant high from which price pulled back |
| Box floor | The recent significant low that held during the pullback |
| Box validity | A box is "formed" when price bounces between ceiling and floor at least twice, establishing both levels as support and resistance |
| Box breakout (buy signal) | Price closes **above the ceiling** of the box on above-average volume |
| Confirmation | Volume should increase on the breakout, confirming institutional demand |

Darvas placed his buy orders as **stop buy orders** just above the box ceiling — so the trade was triggered automatically if and only if price broke out. He monitored prices by telegram while touring as a professional dancer, relying entirely on mechanical orders.

### 4.3 Stop Loss and Trailing Stop Rules

| Action | Rule |
|--------|------|
| Initial stop | Placed **just below the floor of the current box** — a break below the box means the breakout failed |
| Trail on new boxes | As the stock forms a new higher box, raise the stop to just below the **new box floor** |
| Exit rule | Exit (stop triggered) when price closes below the current box floor |

### 4.4 Pyramiding Rules

- Darvas added to winning positions as new higher boxes formed and were broken out of
- Never added to losing positions
- As each new box formed and broke out, he bought more and simultaneously raised his trailing stop below the new box floor
- This created an asymmetric position: early shares had a wide trail (larger paper profit, well above any reasonable stop), later additions had tighter stops

### 4.5 Position Management

- Darvas concentrated into his strongest ideas — he did not run a diversified portfolio
- He exited immediately if the box floor was violated, regardless of conviction
- The "stop just below box floor" provided automatic risk definition on every position

---

## 5. Mark Douglas — Trading Psychology

**Primary sources:** *Trading in the Zone* (2000), *The Disciplined Trader* (1990)

### 5.1 The Core Problem Douglas Identifies

Most traders lose not because of bad methodology, but because they approach the market with a **deterministic mindset** (needing to know what happens next, seeking certainty, taking losses personally) rather than a **probabilistic mindset** (accepting any individual outcome as random within a statistical edge).

### 5.2 The 5 Fundamental Truths

These are Douglas's stated truths that underpin the probabilistic mindset:

1. **"Anything can happen."** — Any single trade outcome is genuinely unknowable in advance.
2. **"You don't need to know what is going to happen next in order to make money."** — A statistical edge over many trades is sufficient; certainty on any one trade is not required.
3. **"There is a random distribution between wins and losses for any given set of variables that define an edge."** — Within any valid edge, wins and losses are randomly distributed; you cannot predict the sequence.
4. **"An edge is nothing more than an indication of a higher probability of one thing happening over another."** — An edge is probabilistic, not deterministic.
5. **"Every moment in the market is unique."** — Each trade setup is a new event; past experience does not guarantee the next outcome.

### 5.3 The 7 Principles of Consistency

Douglas states that a consistently profitable trader operates by these principles:

1. "I objectively identify my edges."
2. "I predefine the risk of every trade."
3. "I completely accept the risk or I am willing to let go of the trade."
4. "I act on my edges without reservation or hesitation."
5. "I pay myself as the market makes money available to me."
6. "I continually monitor my susceptibility for making errors."
7. "I understand the absolute necessity of these principles of consistent success and, therefore, I never violate them."

### 5.4 Quant/Systematic Translation of Douglas's Framework

Douglas's psychology addresses the human errors that a rules-based system eliminates by design:

| Human Error (Douglas identifies) | Systematic Solution |
|----------------------------------|---------------------|
| Hesitating to take valid signals ("what if it fails this time?") | Automated signal execution — no human hesitation |
| Moving stops because "it will come back" | Hard-coded stop orders; no manual override |
| Overtrading (seeking certainty by acting more) | Signal-driven entry only; no discretionary adds |
| Taking profits too early from fear | Predefined exit rules (take at 2R, trail remainder) |
| Revenge trading after a loss | Position sizing rules cap loss exposure regardless of emotion |
| Treating each loss as a personal failure | Expectancy math: losses are expected components of the edge |

For a systematic trader, Douglas's framework is most valuable as **validation**: the entire purpose of a backtest-driven, rules-based system is to enforce the 7 principles by construction. The system replaces the psychological work with structural constraints.

---

## 6. Jack Schwager — Market Wizards Synthesis

**Primary sources:** *Market Wizards* (1989), *The New Market Wizards* (1992), *Hedge Fund Market Wizards* (2012), *Unknown Market Wizards* (2020)

### 6.1 Cross-Cutting Lessons from All Wizards

Schwager's books interview traders across wildly different styles (trend-following, discretionary, options, macro, equities). The common threads are more significant than the method differences:

| Theme | Core Lesson |
|-------|-------------|
| **Risk management is paramount** | Every wizard prioritizes protecting capital above capturing gains. "Know your exit before your entry." |
| **Cut losses without hesitation** | Near-universal: small losses are the cost of doing business; large losses are existential. No exception for "high conviction." |
| **Asymmetric payoff structure** | Winners must be significantly larger than losers. A trader who wins 40% of the time can be highly profitable if the average win is 3× the average loss. |
| **Define your edge precisely** | "If you don't know what your edge is, you don't have one." Vague edges ("I'm good at reading markets") are not edges. |
| **No single right method** | Trend followers, value investors, short-term traders, options players — all generate consistent profits with opposite approaches. The method matters less than discipline and edge clarity. |
| **Discipline over intelligence** | The wizards are not uniformly the smartest people in the room. They are uniformly the most disciplined. Deviation from methodology is the primary cause of losses. |
| **Stops at structurally meaningful levels** | Place stops where the trade thesis is invalidated by market structure — not at a round-number loss tolerance. If meaningful stop = too much risk, reduce size, not stop distance. |
| **Portfolio correlation awareness** | Multiple positions in correlated instruments = one large position. Risk must be evaluated at portfolio level, not position level. |
| **Journal discipline** | Multiple wizards cite detailed trading journals as the mechanism for identifying their true edge (and eliminating what only *feels* like an edge). |
| **Psychology is the last frontier** | Once methodology is sound, psychology (execution consistency) determines results. This aligns directly with Douglas. |

### 6.2 Specific Quantified Risk Rules (from Schwager interviews)

- Equity-based drawdown rule (David Dhaliwal / Unknown Market Wizards): cut position size by **50%** at **5% portfolio drawdown**, cut by 50% again at **8% drawdown**, stop trading entirely at **15% drawdown**
- Peter Brandt's "Friday Close Rule": liquidate any open losing position at end of week — never carry a loser into the weekend
- The asymmetric setup: "You can lose only the dollar amount you set as your risk cutout level, but your upside is entirely open-ended"

---

## 7. Secondary Lineage

### 7.1 Dan Zanger

**Background:** Verified world-record return, turning ~$10,775 into $18M in 18 months (1998–2000). Published in Forbes. Known as a pure chart pattern trader.

**Key methodology points:**

| Element | Rule |
|---------|------|
| Stock selection | EPS growth ≥ 40% YoY; small float; low institutional ownership (room for new buyers) |
| Pattern focus | Cup and handle, flat base, high-tight flag, bull flags, pennants, parabolic curves, wedges, channels, ascending triangles |
| **High-tight flag** | Stock gains ≥ 100% in 4–8 weeks, then consolidates in a shallow flag (≤ 25% pullback) over 3–5 weeks; buy breakout above flag high + $0.10; do not pay more than 5% above breakout |
| Volume requirement | Breakout volume: minimum 300% above the 20-day average volume ("volume is everything") |
| Position management | Hold 2–4 positions in the strongest sectors; rotate out immediately if stock goes limp or volume dries up post-breakout |
| Stop discipline | Sell immediately if the stock fails to follow through after breaking a pattern; no holding through weakness |

**Contrast vs. O'Neil/Minervini:** Zanger is even more concentrated, more pattern-driven, and uses higher momentum thresholds. The high-tight flag is rarer than a VCP or cup — it requires prior explosive gains. It is the most extreme version of the momentum-breakout philosophy.

### 7.2 Adam Grimes

**Primary source:** *The Art and Science of Technical Analysis* (2012)

**Key methodology points:**
- Grimes approaches technical analysis statistically — he empirically tests patterns for a measurable edge, rejecting those without statistical support (e.g., Fibonacci retracements, simple MA crossovers show no edge in his testing)
- Core insight: there is only a **small** statistical edge in any single pattern; consistency, discipline, and proper position sizing are what convert a small edge into profits over time
- Mean reversion and trend following are the two primary forces in markets; the skill is identifying which is dominant in a given asset/timeframe
- Challenges conventional charting religion: "not all technical analysis works; backtesting is the only honest way to know"
- Relevant for quant teams: Grimes's framework is the intellectual justification for building backtested, statistically-validated systems rather than relying on visual pattern recognition

### 7.3 Alexander Elder

**Primary sources:** *Trading for a Living* (1993), *Come Into My Trading Room* (2002)

**Triple Screen System:**

| Screen | Timeframe | Tool | Purpose |
|--------|-----------|------|---------|
| First Screen | Weekly (5× your trading timeframe) | MACD Histogram or EMA slope | Establish trading bias (trend direction) |
| Second Screen | Daily (your trading timeframe) | Oscillators (Stochastic, Force Index) | Identify pullbacks/retracements against the weekly trend |
| Third Screen | Intraday (1/5× trading timeframe) | Price action breakout | Precise entry timing |

**Key rule:** Only trade in the direction of the weekly trend. Use the daily to find retracements (buy dips in uptrends, sell rallies in downtrends). Enter on intraday breakouts in the weekly-trend direction.

**The 2% Rule:** Never risk more than **2% of account equity** on any single trade. (Risk = entry price minus stop price × position size ÷ account equity.)

**The 6% Rule:** If total open losses plus losses for the month reach **6% of account equity**, stop trading for the remainder of the month. This cap prevents a losing streak from compounding into an account-destroying drawdown.

*These two rules are Elder's stated exact figures and are widely confirmed across his books.*

### 7.4 Peter Lynch

**Primary sources:** *One Up on Wall Street* (1989), *Beating the Street* (1993)

**Six Stock Categories:**

| Category | Characteristics | Expected Return Profile |
|----------|----------------|------------------------|
| **Slow Growers** | Large, mature companies; growth ≈ GDP; high dividend payers | Steady income; minimal capital gain |
| **Stalwarts** | Large-cap with 10–12% annual growth; stable sales through recessions | Hold for 20–50% gain; don't expect multibaggers |
| **Fast Growers** | Small/mid companies growing 20–25%+ annually; Lynch's primary focus for large returns | Multibagger potential; highest risk |
| **Cyclicals** | Auto, airline, steel, chemicals; revenue rises/falls with economic cycle | Buy at cycle trough; sell at cycle peak; timing-dependent |
| **Turnarounds** | Distressed companies with recovery potential; "barely dragging into Chapter 11" and surviving | Binary: huge return or total loss |
| **Asset Plays** | Hidden balance sheet value (real estate, patents, cash) not reflected in stock price | Asymmetric when catalyst unlocks value |

**Key Lynch rules:**
- "Invest in what you know" — not sentiment, but genuine knowledge of a company's competitive position
- PEG ratio (P/E ÷ earnings growth rate) ≈ 1.0 is fairly valued; < 1.0 is undervalued, > 1.5 is stretched
- Lynch preferred fast growers; stalwarts were defensive ballast

**Philosophical contrast with this lineage:** Lynch is a long-term, fundamental-first investor (multi-year holding periods). He is not a chart reader or momentum trader. His relevance here is the *fundamental classification* framework — O'Neil and Minervini are effectively building systematic methods to find Lynch's "fast growers" at the moment they are breaking out, rather than holding through all phases.

### 7.5 Warren Buffett

**Philosophical contrast (included for completeness):**
- Buy wonderful companies at fair prices; hold for decades
- Margin of safety (price below intrinsic value)
- Moat-based investing (durable competitive advantage)
- Irrelevant to this lineage's trading horizon and methodology

**The contrast is instructive:** Buffett's edge is *valuation* and *business quality* over multi-year horizons. The J Law lineage's edge is *price momentum and technical timing* over weeks to months. Both can be rational and profitable edges — they are orthogonal strategies, not competing ones. The systematic error would be mixing the frameworks (e.g., using Buffett's "hold forever" rationale to avoid cutting a loss that triggers O'Neil's 7–8% stop).

---

## Synthesis A: The Integrated J Law Workflow

The J Law synthesis combines five frameworks into a single unified workflow. Each framework covers a distinct layer:

```
FRAMEWORK       ROLE IN WORKFLOW
─────────────────────────────────────────────────────────────────
Weinstein       Market context filter (is the stock in Stage 2?)
O'Neil CAN SLIM Fundamental quality gate (is growth sufficient?)
O'Neil M        Market timing (is the broad market in uptrend?)
Minervini SEPA  Full trade setup checklist (all 5 elements aligned?)
Minervini TT    Technical entry gate (does the stock pass Trend Template?)
Minervini VCP   Entry pattern (is there a low-risk pivot to buy?)
Darvas Box      Alternative entry pattern (stair-step box breakout)
O'Neil Cup      Alternative entry pattern (cup-with-handle pivot)
Douglas         Execution discipline (follow rules without hesitation)
Schwager        Portfolio risk overlay (asymmetric payoff, cut losses)
```

### The Unified Workflow (6 Steps)

**Step 1: UNIVERSE SCREEN**
Filter the investable universe to stocks that meet the minimum quality and trend bar:
- CAN SLIM fundamentals: C ≥ 25%, A ≥ 25% (3-year), RS ≥ 80
- Minervini Trend Template: all 8 criteria pass
- Weinstein Stage 2: price above rising 30-week MA (= 150-day SMA); confirmed by volume behavior
- Market direction: IBD condition = "Confirmed Uptrend"; M-filter = on

**Step 2: STAGE CHECK**
From the screened universe, verify Stage 2:
- Weinstein: 30-week MA rising, price above it, up-weeks on above-average volume
- Minervini: 200-day MA trending up ≥ 30 days, 50 > 150 > 200 MA stack
- O'Neil: price within 25% of 52-week high, RS line trending up

**Step 3: SETUP IDENTIFICATION**
From Stage 2 stocks, identify a specific low-risk pattern:
- VCP: 2–6 contracting pullbacks, volume dry-up (40–50% below avg), pivot = high of final contraction
- Cup-with-handle: U-shaped base (12–33% depth, 7–65 weeks), handle in upper half, volume dry-up in handle
- Darvas box: higher box forming above prior box, stop defined by box floor
- In all cases: risk-to-reward ≥ 2:1 from entry to stop

**Step 4: ENTRY**
- Enter at the pivot (VCP high, cup handle high + $0.10, box ceiling + $0.10)
- Only within 5% of pivot; no chasing extended moves
- Confirm with breakout volume ≥ 40–50% above average
- Initial position: 50–100% of target size; add on confirmation

**Step 5: RISK MANAGEMENT**
- Pre-define stop before order is placed
- Stop: 7–8% maximum below entry (tighter based on pattern low)
- Account risk: max 1.25–2.5% of equity per trade (Elder's 2% rule)
- Portfolio monthly loss cap: never let cumulative monthly loss exceed 6% of equity (Elder's 6% rule)
- Pyramiding: add only to confirmed winners on subsequent breakouts/bases

**Step 6: EXIT**
- Defensive: sell at 7–8% loss, no exceptions
- Offensive: take partial profits at 20–25% gain (or 2–3R); hold remainder with trailing stop
- 8-week hold rule: if up 20%+ in < 3 weeks, hold 8 weeks before re-evaluating
- Market-level: if distribution days accumulate (4–5 in 4 weeks), reduce or exit all positions
- Pattern failure: if breakout volume is low and stock returns to pivot, exit immediately
- Douglas discipline: execute all of the above mechanically; do not override for emotional reasons

---

## Synthesis B: Systematic / Quant Translation

> **Horizon note:** This entire lineage operates on **daily and weekly price data**, targeting holding periods of **days to months** (swing-to-position trading). It is a fundamentally different track from intraday or minute-level strategies. Backtesting should use **end-of-day (EOD) OHLCV data** with execution assumed at next-day open (to avoid look-ahead bias on the breakout day close).

### B.1 Universe Screen — Boolean Filter Stack

All filters are evaluated on the most recent complete trading day. All moving averages are simple (SMA) unless noted.

```python
# Minimum price and liquidity
price_filter        = close >= 10.0                     # avoid penny stocks
liquidity_filter    = avg_dollar_volume_20d >= 1_000_000  # $1M+ avg daily dollar volume

# CAN SLIM fundamentals (sourced from earnings data)
C_filter            = eps_growth_current_qtr >= 0.25    # vs same qtr prior year
A_filter            = (eps_growth_yr1 >= 0.25 and
                       eps_growth_yr2 >= 0.25 and
                       eps_growth_yr3 >= 0.25)
roe_filter          = roe_ttm >= 0.17
rs_rating_filter    = rs_rating >= 80                   # percentile rank, 1-99

# Minervini Trend Template (all 8 must be True)
TT1 = close > sma(close, 150)
TT2 = close > sma(close, 200)
TT3 = sma(close, 150) > sma(close, 200)
TT4 = sma(close, 200) > sma(close, 200)[30]            # 200d MA today > 30 bars ago
TT5 = sma(close, 50) > sma(close, 150)
TT6 = sma(close, 50) > sma(close, 200)
TT7 = close > sma(close, 50)
TT8 = close >= low_52w * 1.30                          # at least 30% above 52-week low
TT9 = close >= high_52w * 0.75                         # within 25% of 52-week high
trend_template      = TT1 and TT2 and TT3 and TT4 and TT5 and TT6 and TT7 and TT8 and TT9

# Weinstein Stage 2 (weekly data)
sma_30w             = sma_weekly(close, 30)
weinstein_stage2    = (close_weekly > sma_30w and
                       sma_30w > sma_30w[4])            # 30-week MA rising (vs 4 weeks ago)

# Market direction filter (evaluated on index, e.g. SPY/QQQ)
market_filter       = (index_distribution_days_4wk < 4 and
                       index_in_confirmed_uptrend == True)

# Combined universe filter
in_universe = (price_filter and liquidity_filter and
               C_filter and A_filter and roe_filter and rs_rating_filter and
               trend_template and weinstein_stage2 and market_filter)
```

**Notes:**
- Earnings data (C, A, ROE) must be sourced from a point-in-time fundamental database to avoid look-ahead bias. Use report date, not period end date.
- RS Rating replication requires ranking all stocks in the universe by 12-month return with the 40/20/20/20 quarterly weighting scheme and computing percentile ranks.
- The float filter (< 25M shares) is optional but aligns with O'Neil's S factor; include if float data is available.
- Institutional sponsorship (I) is difficult to model with pure price/fundamental data; it can be approximated by RS trend or omitted in an initial implementation.

### B.2 Entry Signals

#### B.2.1 VCP Pivot Breakout

```python
# Identify contracting pullbacks within a Stage 2 trend
# Simplified 3-contraction VCP detection:

def detect_vcp(prices, volumes, lookback=60):
    """
    Returns True + pivot level if a VCP pattern is present.
    Simplified: detects 2-3 swing highs with contracting depth
    and declining volume at each swing low.
    """
    # Find swing highs and lows over lookback window
    swings = find_swing_points(prices, lookback)
    contractions = []
    for i in range(1, len(swings)):
        depth = (swings[i].high - swings[i].low) / swings[i].high
        contractions.append(depth)

    # Check contraction sequence (each ~50% of prior)
    if len(contractions) >= 2:
        contracting = all(contractions[i] < contractions[i-1] * 0.75
                         for i in range(1, len(contractions)))
        # Volume dry-up at final low
        vol_at_final_low = volume_at_swing_low(volumes, swings[-1])
        avg_vol = mean(volumes[-20:])
        vol_dryup = vol_at_final_low < avg_vol * 0.60  # 40%+ below avg

        pivot = swings[-1].high  # high of final contraction
        return contracting and vol_dryup, pivot
    return False, None

# Entry trigger: price closes above pivot on volume
def vcp_entry(close, volume, pivot, avg_volume_20d):
    breakout = close > pivot
    vol_confirm = volume > avg_volume_20d * 1.40  # 40%+ above average
    return breakout and vol_confirm
```

#### B.2.2 Darvas Box Breakout

```python
def detect_darvas_box(highs, lows, closes, lookback=20):
    """
    Box ceiling = highest high in the lookback window that price
    has bounced below at least twice.
    Box floor = lowest low that has held at least twice.
    """
    ceiling = max(highs[-lookback:])
    floor   = min(lows[-lookback:])
    # Price oscillating between floor and ceiling (consolidation)
    consolidating = all(floor * 0.98 <= c <= ceiling * 1.02
                        for c in closes[-5:])
    return consolidating, ceiling, floor

def darvas_entry(close, volume, ceiling, avg_volume_20d):
    breakout = close > ceiling * 1.001   # penny above ceiling
    vol_confirm = volume > avg_volume_20d * 1.20  # at minimum above-avg
    return breakout and vol_confirm
```

#### B.2.3 Cup-with-Handle Pivot

```python
def detect_cup_handle(prices, volumes, min_weeks=7, max_weeks=65):
    """
    Cup: U-shaped base. Depth 12-33% from prior high. Duration 7-65 weeks.
    Handle: in upper half of cup, <15% depth, volume declining.
    Pivot: handle high + $0.10.
    """
    cup_high    = max(prices[:-handle_window])
    cup_low     = min(prices[cup_start:cup_end])
    cup_depth   = (cup_high - cup_low) / cup_high

    handle_high = max(prices[-handle_window:])
    handle_low  = min(prices[-handle_window:])
    handle_depth = (handle_high - handle_low) / handle_high

    # Handle must be in upper half of cup
    cup_midpoint = cup_low + (cup_high - cup_low) * 0.5
    handle_in_upper_half = handle_low >= cup_midpoint

    valid = (0.12 <= cup_depth <= 0.33 and
             handle_depth <= 0.15 and
             handle_in_upper_half and
             min_weeks <= cup_duration_weeks <= max_weeks)

    pivot = handle_high + 0.10
    return valid, pivot
```

### B.3 Exit and Stop Rules

```python
# Per-trade parameters (set at entry, never moved adversely)
entry_price      = filled_price
stop_price       = entry_price * (1 - 0.075)   # 7.5% stop (midpoint of 7-8% range)
target_1         = entry_price * 1.20           # first partial exit at +20%
target_2         = entry_price * 1.25           # full exit signal at +25% (or trail)
eight_week_hold  = entry_date + timedelta(weeks=8)  # if up 20% in <3 weeks

def manage_exit(current_price, current_date, position):
    # Defensive: hard stop
    if current_price <= position.stop_price:
        return "SELL_ALL", "hard_stop"

    # Check for 20% gain in < 3 weeks (8-week hold candidate)
    days_held = (current_date - position.entry_date).days
    gain = (current_price - position.entry_price) / position.entry_price

    if gain >= 0.20 and days_held <= 15:
        # Potential big winner: hold min 8 weeks
        position.eight_week_candidate = True
        return "HOLD", "eight_week_rule"

    if gain >= 0.20 and not position.eight_week_candidate:
        # Take partial profit at 20-25%
        return "SELL_PARTIAL_50", "profit_target_partial"

    if gain >= 0.25:
        # Take more or all profits
        return "SELL_PARTIAL_75", "profit_target_full"

    # Trail stop after first partial taken
    if position.partial_taken:
        new_trail = current_price * 0.92  # 8% trail from current price
        position.stop_price = max(position.stop_price, new_trail)

    return "HOLD", "trailing"
```

### B.4 Position Sizing and Portfolio Risk Rules

```python
def calculate_position_size(account_equity, entry_price, stop_price,
                             risk_per_trade_pct=0.02,
                             max_portfolio_loss_pct=0.06):
    """
    Elder 2% Rule: risk at most 2% of equity on any single trade.
    Elder 6% Rule: if cumulative monthly loss >= 6% of equity, stop trading.
    Minervini: 1.25-2.5% account risk per trade (use 2% as default).
    """
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        raise ValueError("Stop must be below entry")

    max_risk_dollars = account_equity * risk_per_trade_pct
    shares = int(max_risk_dollars / risk_per_share)
    position_value = shares * entry_price

    # Cap position at e.g. 20% of account (concentration limit)
    max_position_value = account_equity * 0.20
    shares = min(shares, int(max_position_value / entry_price))

    return shares

def portfolio_risk_check(account_equity, mtd_pnl, max_monthly_drawdown=0.06):
    """Elder 6% Rule: halt new trades if monthly drawdown >= 6%."""
    if mtd_pnl < 0 and abs(mtd_pnl) / account_equity >= max_monthly_drawdown:
        return False  # no new trades this month
    return True

# Pyramiding (Minervini / Darvas): add to winners only
def pyramid_add(position, current_price, avg_volume, account_equity):
    """
    Add when price makes new high above entry on volume.
    Size each add proportionally smaller than prior add
    (e.g. 50% of initial size on first add, 25% on second add).
    """
    if (current_price > position.last_add_price * 1.05 and
        avg_volume > position.avg_vol_20d * 1.40):
        add_size = position.initial_size * 0.50  # first pyramid
        return add_size
    return 0
```

### B.5 Market Direction Filter (M-Factor)

```python
def market_direction_filter(index_prices, index_volumes, lookback_days=25):
    """
    O'Neil M-factor: count distribution days on major index.
    Distribution day: index closes down >= 0.2% on volume > prior day.
    4-5 distribution days in 25 trading days = market in distribution.
    """
    dist_days = 0
    for i in range(1, lookback_days):
        price_change = (index_prices[-i] - index_prices[-i-1]) / index_prices[-i-1]
        vol_higher   = index_volumes[-i] > index_volumes[-i-1]
        if price_change <= -0.002 and vol_higher:
            dist_days += 1

    if dist_days >= 4:
        return "CAUTION"   # reduce exposure
    if dist_days >= 5:
        return "CORRECTION"  # no new buys; raise cash

    # Follow-through day check (new uptrend confirmation)
    # Day 4+ of rally attempt: close significantly higher on higher volume
    # Implementation: track rally attempt day count separately

    return "UPTREND"

trading_allowed = (market_direction_filter(spy_prices, spy_volumes) == "UPTREND")
```

### B.6 Complete Signal Pipeline Summary

```
[Daily EOD Data Feed]
        │
        ▼
[UNIVERSE SCREEN]
  price ≥ $10, ADV ≥ $1M
  CAN SLIM: C ≥ 25%, A ≥ 25% (3yr), ROE ≥ 17%
  RS Rating ≥ 80
  Trend Template: all 8 criteria pass
  Weinstein Stage 2: close > rising 30-week SMA
  M-Filter: distribution days < 4
        │
        ▼ (filtered list: "Stage 2 Leaders")
[SETUP SCAN]
  Detect VCP pivot (primary)
  Detect Cup-with-Handle pivot (secondary)
  Detect Darvas Box ceiling (tertiary)
        │
        ▼ (list with entry levels)
[SIGNAL GENERATION]
  Entry: close > pivot AND volume > 1.40 × avg_vol_20d
  Not extended: close ≤ pivot × 1.05
        │
        ▼
[POSITION SIZING]
  Risk per trade: 2% of equity
  Stop: 7.5% below entry
  Shares = (equity × 0.02) / (entry - stop)
  Cap: max 20% of equity per position
        │
        ▼
[EXIT MANAGEMENT]
  Hard stop: -7.5% from entry
  Partial profit: +20-25% from entry
  8-week hold if +20% in < 3 weeks
  Monthly loss cap: halt at -6% MTD
```

### B.7 Backtesting Constraints and Cautions

| Issue | Practical Guidance |
|-------|-------------------|
| **Look-ahead bias on fundamentals** | Use point-in-time earnings (report date, not fiscal period end); earnings typically reported 3–6 weeks after quarter close |
| **Look-ahead bias on RS rating** | Compute RS rating from data available as of bar date only |
| **Execution assumption** | Signal generated on close Day 0; execute at open Day 1 (realistic for daily EOD systems) |
| **Volume surge validation** | Breakout-day volume must exceed threshold at EOD; intraday volume is noisy — EOD confirmation is the standard |
| **Slippage on low-float stocks** | Small-float stocks (O'Neil's S factor) have high slippage on large orders; model slippage as a function of position size vs. average daily dollar volume |
| **Survivorship bias** | Must use a database that includes delisted stocks; failure to do so inflates backtest results significantly |
| **Market regime sensitivity** | This methodology performs best in bull markets (Stages 2 proliferate); it will naturally reduce exposure in bear markets via the M-filter and Trend Template |
| **Hold horizon** | Parameterize holding period to test 2–20 week typical holds; this is NOT a days-only or months-only strategy |

---

## Sources

- [AAII: A Tribute to William O'Neil — Revisiting the CAN SLIM Strategy](https://www.aaii.com/journal/article/68036-a-tribute-to-william-o-neil-revisiting-the-can-slim-strategy)
- [Portfolio123: A Stock-Picker's Guide to William O'Neil's CAN SLIM System](https://blog.portfolio123.com/a-stock-pickers-guide-to-william-oneils-can-slim-system/)
- [Wikipedia: CAN SLIM](https://en.wikipedia.org/wiki/CAN_SLIM)
- [LuxAlgo: O'Neil's Strategies — Trading Tactics Explained](https://www.luxalgo.com/blog/oneils-strategies-trading-tactics-explained/)
- [StockCharts ChartSchool: Cup With Handle](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns/cup-with-handle)
- [Financial Wisdom TV: How to Make Money in Stocks — William O'Neil](https://www.financialwisdomtv.com/post/how-to-make-money-in-stocks-by-william-o-neil)
- [FinancialTechWiz: Mark Minervini Trading Strategy — SEPA, VCP, Trend Template](https://www.financialtechwiz.com/post/mark-minervini-trading-strategy/)
- [FinerMarketPoints: What is a VCP Pattern — Mark Minervini's VCP Explained](https://www.finermarketpoints.com/post/what-is-a-vcp-pattern-mark-minervini-s-volatility-contraction-pattern-explained)
- [TrendSpider: Volatility Contraction Pattern (VCP)](https://trendspider.com/learning-center/volatility-contraction-pattern-vcp/)
- [Minervini Quotes (X / Twitter): SEPA Five Elements](https://x.com/MinerviniQuote/status/1761814001032339757)
- [DeepVue: Stan Weinstein Stage Analysis](https://deepvue.com/indicators/stan-weinstein-stage-analysis-when-to-buy/)
- [AronGroups: Stage Analysis Trading — Stan Weinstein's 4-Stage Method](https://arongroups.co/forex-articles/stage-analysis-trading/)
- [Due.com: Nicolas Darvas Box Theory](https://due.com/how-nicolas-darvas-used-box-theory-to-20x-his-money/)
- [TradeForexSwing: Technical Foundations of Nicolas Darvas's Strategy](https://tradethatswing.com/the-technical-foundations-of-nicolas-darvass-trading-strategy/)
- [ForexMentor: The 5 Fundamental Truths and 7 Principles of Consistency (Mark Douglas)](https://www.forexmentor.com/forex-trading-articles/trading-consistently.html)
- [WonkMonk's Notes: Jack Schwager's 46 Market Wizard Lessons](https://wonkmonksnotes.wordpress.com/2020/11/08/jack-schwager-46-market-wizard-lessons/)
- [TradingResourceHub: Dan Zanger — 3 Key Elements](https://tradingresourcehub.substack.com/p/3-key-elements-to-dan-zangers-system)
- [Financial Wisdom TV: Dan Zanger](https://www.financialwisdomtv.com/post/dan-zanger)
- [TopStep: Going Deep on Adam Grimes's Approach](https://www.topstep.com/blog/going-deep-on-adam-grimes-approach)
- [TradingStrategyGuides: Alexander Elder Triple Screen Strategy](https://tradingstrategyguides.com/alexander-elder-trading-strategy-the-triple-screen/)
- [GuroFocus: Peter Lynch's 6 Categories of Stocks](https://www.gurufocus.com/news/711216/one-up-on-wall-street-peter-lynchs-6-categories-of-stocks)
- [GrokiPedia: Distribution Day](https://grokipedia.com/page/Distribution_day)
- [TraderLion: Follow-Through Day](https://traderlion.com/trading-strategies/follow-through-day/)
- [ChartMill: High Tight Flag Pattern](https://www.chartmill.com/documentation/technical-analysis/chart-patterns/466-High-Tight-Flag-Pattern)
