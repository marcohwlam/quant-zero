# Sell-Side Research Log

Source list: `docs/knowledge/sell-side-free-research-sources.md` (QUA-837). Scan run: 2026-10-27 (QUA-838).
Entries store title, link, and tag only. Sell-side views are opinions, not validated signals. Hypothesis candidates must pass PF-1 to PF-4 and the diversification mandate.

## Source Fetchability (2026-10-27)

| Bank | Status | Note |
|---|---|---|
| Goldman Sachs | manual | curl returns 200 but page is JS-rendered with no item list; WebFetch gets 403 |
| JPMorgan | partial | Redirects to /insights/research. Item list loads dynamically; only the featured item is visible |
| Morgan Stanley | fetchable | Static HTML lists current items. Dates not on listing page |
| BofA | partial | Landing page only; links to hub pages, no dated items |
| Citi | manual | Navigation hub only, no item list |
| Jefferies | fetchable | Static HTML, titles and links. Dates not on listing page |
| Nomura | manual | 200 only with www host and browser UA; WebFetch 403; no item list |
| Societe Generale | manual | 3 KB JS SPA shell, no content without a browser |
| RBC Capital Markets | fetchable | Needs www host and browser UA (503 on HEAD). Dated URLs, 2026/10 |
| Wells Fargo | partial | Landing page only; reports under /research-analysis/reports.htm and /strategy.htm (not yet scanned) |
| BNP Paribas Markets 360 | manual | Connection fails (no response) |

Fetchable: 3 (MS, Jefferies, RBC). Partial: 3 (JPM, BofA, Wells). Manual: 5 (GS, Citi, Nomura, SG, BNP).

## Log

Format: `date | bank | title | link | tag`. Date `2026-10` means month only.

2026-10 | RBC CM | Caveats and risks (3Q26 reporting season starts slightly soft) | https://www.rbccm.com/en/insights/2026/10/caveats-and-risks | regime
2026-10 | RBC CM | The micro reality (quarterly global analyst outlook survey) | https://www.rbccm.com/en/insights/2026/10/the-micro-reality | regime
2026-10 | RBC CM | The George Davis Report: October 2026 Edition | https://www.rbccm.com/en/insights/2026/10/the-george-davis-report-october-2026-edition | regime
2026-10 | RBC CM | Escalating Middle East tensions amplify energy supply risks | https://www.rbccm.com/en/insights/2026/10/escalating-middle-east-tensions-amplify-energy-supply-risks | risk
2026-10 | RBC CM | What's driving the municipal market's remarkable growth? | https://www.rbccm.com/en/insights/2026/10/whats-driving-the-municipal-markets-remarkable-growth | cross-asset
2026-07-01 | JPMorgan | Mid-year market outlook 2026: The tug of war continues | https://www.jpmorgan.com/insights/global-research/outlook/mid-year-outlook | regime
undated | Morgan Stanley | Market Resilience Isn't Complacency (Thoughts on the Market, Mike Wilson) | https://www.morganstanley.com/insights/podcasts/thoughts-on-the-market/bull-market-resilience-isnt-complacency-mike-wilson | regime
undated | Morgan Stanley | Software Sell-Off: Framing Concerns About Private Credit | https://www.morganstanley.com/im/en-us/individual-investor/insights/articles/the-software-sell-off.html | risk
undated | Morgan Stanley | The Undervalued Companies Benefiting from AI | https://www.morganstanley.com/insights/articles/3600-stocks-map-out-ai-investing-opportunties-across-sectors | factor
undated | Jefferies | Tariffs, Valuations, and Cautious Optimism: The Outlook for Tech M&A | https://www.jefferies.com/insights/markets/tariffs-valuations-and-cautious-optimism-the-outlook-for-tech-ma/ | event

Skipped as not relevant (corporate, sector color, lifestyle): MS healthcare and leadership videos, Jefferies carbon removal / private aviation / Perplexity / Canadian economy, RBC Canada AI, energy infrastructure, and carbon pricing items.

## Hypothesis Candidates

None this scan. Listing pages give titles only; no item has a stated, testable signal. Candidate for follow-up: RBC "The micro reality" analyst-survey series (survey-revision signal), pending read of the full piece. Any hypothesis from it must pass PF-1 to PF-4.
