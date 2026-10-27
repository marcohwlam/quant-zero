# Sell-Side Free Research Sources

Source: QUA-837 (LeoPTrudel, 2026-10-27). Banks publish free research irregularly. Some reports are deep or contain usable investment ideas.

## Source List

| Tier | Bank | URL |
|---|---|---|
| Bulge bracket | Goldman Sachs | https://goldmansachs.com/insights/reports |
| Bulge bracket | JPMorgan | https://jpmorgan.com/insights/global-research |
| Bulge bracket | Morgan Stanley | https://morganstanley.com/insights |
| Bulge bracket | BofA | https://business.bofa.com/en-us/content/market-strategies-insights.html |
| Bulge bracket | Citi | https://citigroup.com/global/insights/tags/citi-research |
| Rest of street | Jefferies | https://jefferies.com/insights/ |
| Rest of street | Nomura | https://nomuraholdings.com/en/services/global_research.html |
| Rest of street | Societe Generale | https://insight-public.sgmarkets.com |
| Rest of street | RBC Capital Markets | https://rbccm.com/en/insights.page |
| Rest of street | Wells Fargo | https://wellsfargoadvisors.com/research-analysis.htm |
| Rest of street | BNP Paribas Markets 360 | https://globalmarkets.cib.bnpparibas/markets-360/ |

## Daily Scan Protocol (proposed)

1. Alpha Research Agent fetches each URL once per day and diffs titles against `research/sell-side-log.md`.
2. New items are triaged by relevance: regime views, factor or momentum studies, cross-asset relative value, event-driven or calendar effects, drawdown and risk commentary.
3. Relevant items get a one-line entry in the log (bank, title, date, link, tag). Items with a testable idea become a hypothesis candidate and must pass Pre-Flight Gates PF-1 to PF-4 and the diversification mandate.
4. Market Regime Agent reads regime-tagged items weekly.
5. Research Director summarizes the week in the Monday heartbeat.

## Caveats

- Some pages may block automated fetches or require login. Record such sources as `manual` in the log.
- Sell-side views are opinions, not validated signals. Treat as idea source only; no direct trading use.
- Respect each site's terms of use. Store titles, links, and short notes only, not full report text.
