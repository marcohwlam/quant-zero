"""
QUA-169: H60b IC re-estimation from 2022-2024 OOS trade data.

Steps:
  1. Load 352 OOS trades
  2. Compute per-session ORB% from minute_bars.db
  3. Segment trades: filtered (ORB > 1.5%) vs non-filtered
  4. Compute IC at T+5, T+15, T+30 for non-filtered trades
  5. Compare to Kissell 2014 baseline; estimate annualized IR
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
import statistics
import math

# ── Config ────────────────────────────────────────────────────────────────────
TRADES_FILE = "/repos/quant-zero/backtests/h60_intraday_vwap_mean_reversion_2026-06-09_oos_trades.json"
DB_FILE     = "/repos/quant-zero/pipelines/data/minute_bars.db"
ORB_THRESHOLD = 0.015   # 1.5%
ORB_BARS      = 30      # first 30 min bars (9:30–10:00 ET)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_ts(ts_str):
    """Parse timestamp string to UTC-aware datetime."""
    ts_str = ts_str.replace("+00:00", "").replace("Z", "")
    return datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)


def db_ts_fmt(dt):
    """Format datetime as DB key (ISO 8601 with Z)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def session_open_utc(session_date_str):
    """
    Return 9:30 AM ET in UTC for a given session date string ('YYYY-MM-DD').
    Handles EDT (UTC-4, Mar–Nov) vs EST (UTC-5, Nov–Mar) via dst offset check.
    Uses pandas-free approach: approximate DST via month.
    DST approx: March 8 – November 1 → EDT (UTC-4); else EST (UTC-5).
    """
    y, m, d = map(int, session_date_str.split("-"))
    # Approximate EDT months: April–October always EDT; March/Nov depend on exact date
    # Use simpler rule: month 4-10 = EDT, 11-3 = EST, March/Nov use exact DST dates
    # For accuracy, just check a few boundary cases
    date = datetime(y, m, d)
    # DST: second Sunday of March → first Sunday of November
    # For 2022-2024, good enough approximation:
    if m > 3 and m < 11:
        utc_offset = 4  # EDT
    elif m == 3:
        # March: DST starts second Sunday
        # March 13 2022, March 12 2023, March 10 2024
        dst_starts = {2022: 13, 2023: 12, 2024: 10}
        utc_offset = 4 if d >= dst_starts.get(y, 12) else 5
    elif m == 11:
        # November: DST ends first Sunday
        # Nov 6 2022, Nov 5 2023, Nov 3 2024
        dst_ends = {2022: 6, 2023: 5, 2024: 3}
        utc_offset = 4 if d < dst_ends.get(y, 6) else 5
    else:
        utc_offset = 5  # EST
    # 9:30 AM ET → UTC
    open_et = datetime(y, m, d, 9, 30, 0, tzinfo=timezone.utc)
    open_utc = open_et + timedelta(hours=utc_offset)
    return open_utc


# ── Load trades ────────────────────────────────────────────────────────────────
with open(TRADES_FILE) as f:
    trades_raw = json.load(f)

trades = []
for t in trades_raw:
    trades.append({
        "entry_ts": parse_ts(t["entry_ts"]),
        "session": t["session"],
        "direction": t["direction"],
        "entry_raw_price": t["entry_raw_price"],
        "entry_z_score": t["entry_z_score"],
        "signal": -t["entry_z_score"],  # negative z → long → expect +return
    })

print(f"Loaded {len(trades)} trades")

# ── Compute ORB per session ────────────────────────────────────────────────────
conn = sqlite3.connect(DB_FILE)

def compute_session_orb(session_str):
    """Compute ORB% for a given session date. Returns (orb_pct, n_bars_found)."""
    open_utc = session_open_utc(session_str)
    end_utc  = open_utc + timedelta(minutes=ORB_BARS)
    ts_start = db_ts_fmt(open_utc)
    ts_end   = db_ts_fmt(end_utc)  # exclusive upper bound (30 bars = 0..29 min)

    rows = conn.execute(
        """
        SELECT open, high, low, close, ts
        FROM minute_bars
        WHERE symbol = 'SPY'
          AND ts >= ?
          AND ts < ?
        ORDER BY ts
        """,
        (ts_start, ts_end),
    ).fetchall()

    if not rows:
        return None, 0

    session_open_price = rows[0][0]  # open of first bar
    orb_high = max(r[1] for r in rows)
    orb_low  = min(r[2] for r in rows)
    if session_open_price == 0:
        return None, len(rows)
    orb_pct = (orb_high - orb_low) / session_open_price
    return orb_pct, len(rows)


sessions = sorted(set(t["session"] for t in trades))
print(f"Unique sessions: {len(sessions)}")

session_orb = {}
missing_sessions = []
for sess in sessions:
    pct, n = compute_session_orb(sess)
    session_orb[sess] = pct
    if n < 20:
        missing_sessions.append((sess, n, pct))

if missing_sessions:
    print(f"\nWARNING: {len(missing_sessions)} sessions with < 20 ORB bars:")
    for s, n, p in missing_sessions[:10]:
        print(f"  {s}: {n} bars, ORB={p}")

orb_vals = [v for v in session_orb.values() if v is not None]
print(f"\nORB stats across {len(orb_vals)} sessions:")
print(f"  Mean ORB%:   {100*sum(orb_vals)/len(orb_vals):.3f}%")
print(f"  Median ORB%: {100*sorted(orb_vals)[len(orb_vals)//2]:.3f}%")
above_thresh = sum(1 for v in orb_vals if v > ORB_THRESHOLD)
print(f"  Sessions > 1.5% ORB: {above_thresh}/{len(orb_vals)} = {100*above_thresh/len(orb_vals):.1f}%")

# ── Segment trades ─────────────────────────────────────────────────────────────
filtered   = []
unfiltered = []
no_orb     = []

for t in trades:
    orb = session_orb.get(t["session"])
    if orb is None:
        no_orb.append(t)
    elif orb > ORB_THRESHOLD:
        filtered.append(t)
    else:
        unfiltered.append(t)

print(f"\nTrade segmentation (ORB threshold = {ORB_THRESHOLD*100:.1f}%):")
print(f"  Filtered (ORB > 1.5%):   {len(filtered):3d}  ({100*len(filtered)/len(trades):.1f}%)")
print(f"  Unfiltered (ORB ≤ 1.5%): {len(unfiltered):3d}  ({100*len(unfiltered)/len(trades):.1f}%)")
print(f"  No ORB data:              {len(no_orb):3d}  ({100*len(no_orb)/len(trades):.1f}%)")

# ── Fetch forward prices ───────────────────────────────────────────────────────
def get_close_at(ts_utc):
    """Get SPY close price at a given UTC timestamp."""
    ts_str = db_ts_fmt(ts_utc)
    row = conn.execute(
        "SELECT close FROM minute_bars WHERE symbol='SPY' AND ts=?",
        (ts_str,),
    ).fetchone()
    return row[0] if row else None


def compute_ic(trade_list, lag_minutes, label):
    """Compute IC = corr(signal, forward_return) at lag_minutes."""
    signals = []
    fwd_returns = []
    skipped = 0

    for t in trade_list:
        entry_ts  = t["entry_ts"]
        entry_close = get_close_at(entry_ts)
        if entry_close is None:
            skipped += 1
            continue

        fwd_ts    = entry_ts + timedelta(minutes=lag_minutes)
        fwd_close = get_close_at(fwd_ts)
        if fwd_close is None:
            # Try ±1 min window (market close / data gap)
            fwd_close = get_close_at(fwd_ts + timedelta(minutes=1))
            if fwd_close is None:
                fwd_close = get_close_at(fwd_ts - timedelta(minutes=1))
            if fwd_close is None:
                skipped += 1
                continue

        fwd_ret = (fwd_close - entry_close) / entry_close
        signals.append(t["signal"])
        fwd_returns.append(fwd_ret)

    n = len(signals)
    if n < 5:
        print(f"  {label}: insufficient data (n={n}, skipped={skipped})")
        return None, n, skipped

    # Pearson correlation
    mean_s  = sum(signals)    / n
    mean_r  = sum(fwd_returns) / n
    cov     = sum((s - mean_s) * (r - mean_r) for s, r in zip(signals, fwd_returns)) / n
    std_s   = math.sqrt(sum((s - mean_s)**2 for s in signals) / n)
    std_r   = math.sqrt(sum((r - mean_r)**2 for r in fwd_returns) / n)
    if std_s == 0 or std_r == 0:
        return None, n, skipped
    ic = cov / (std_s * std_r)
    t_stat = ic * math.sqrt(n - 2) / math.sqrt(max(1 - ic**2, 1e-10))
    print(f"  {label}: IC={ic:+.4f}  n={n}  t={t_stat:.2f}  skipped={skipped}")
    return ic, n, skipped


# ── IC computations ────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("IC RESULTS — FULL SAMPLE (unfiltered + filtered, n=352)")
print("="*60)
ic_full_5,  n_full_5,  _ = compute_ic(trades, 5,  "Full T+5 ")
ic_full_15, n_full_15, _ = compute_ic(trades, 15, "Full T+15")
ic_full_30, n_full_30, _ = compute_ic(trades, 30, "Full T+30")

print(f"\n{'='*60}")
print(f"IC RESULTS — ORB-FILTERED SESSIONS ONLY (n={len(filtered)})")
print("="*60)
if filtered:
    ic_filt_5,  _, _ = compute_ic(filtered, 5,  "Filt T+5 ")
    ic_filt_15, _, _ = compute_ic(filtered, 15, "Filt T+15")
    ic_filt_30, _, _ = compute_ic(filtered, 30, "Filt T+30")
else:
    ic_filt_5 = ic_filt_15 = ic_filt_30 = None
    print("  (no filtered trades)")

print(f"\n{'='*60}")
print(f"IC RESULTS — NON-FILTERED (H60b eligible, n={len(unfiltered)})")
print("="*60)
ic_uf_5,  n_uf_5,  _ = compute_ic(unfiltered, 5,  "NF T+5  ")
ic_uf_15, n_uf_15, _ = compute_ic(unfiltered, 15, "NF T+15 ")
ic_uf_30, n_uf_30, _ = compute_ic(unfiltered, 30, "NF T+30 ")

# ── Annualized IR estimate ──────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("ANNUALIZED IR ESTIMATE (H60b non-filtered regime)")
print("="*60)

# IR ≈ IC × sqrt(N_annual) / (1) where N_annual = annual trade count
# For H60b: ~150-200 trades/year after ORB filter
# H60 had 352 OOS trades over some period — figure out the period

if trades:
    first_ts = min(t["entry_ts"] for t in trades)
    last_ts  = max(t["entry_ts"] for t in trades)
    days_span = (last_ts - first_ts).days
    years_span = days_span / 365.25
    print(f"  OOS period: {first_ts.date()} → {last_ts.date()} ({days_span} days, {years_span:.2f} years)")
    if years_span > 0:
        annualized_trades_full = len(trades) / years_span
        annualized_trades_uf   = len(unfiltered) / years_span
        print(f"  Full annual trade rate:      {annualized_trades_full:.0f} trades/year")
        print(f"  H60b annual trade rate (NF): {annualized_trades_uf:.0f} trades/year")

# Fundamental IR equation: IR = IC × sqrt(breadth) for Grinold-Kahn
# Using T+5 as primary signal holding horizon
if ic_uf_5 is not None and years_span > 0:
    n_annual = annualized_trades_uf
    # Grinold-Kahn approximation: Sharpe ≈ IC × sqrt(N)
    # But for intraday, vol-adjusted: Sharpe_annual ≈ IC × sqrt(N_annual) × (daily_vol_adjustment)
    # Simple: annualized IR = IC_T5 × sqrt(N_annual)
    ir_estimate = ic_uf_5 * math.sqrt(n_annual)
    print(f"\n  IC (T+5, NF):                {ic_uf_5:+.4f}")
    print(f"  Annual trades (NF):          {n_annual:.0f}")
    print(f"  Grinold-Kahn IR estimate:    {ir_estimate:.3f}")
    print(f"  IS Sharpe > 1.0 likely?      {'YES' if ir_estimate > 1.0 else 'NO — RETIRE' if ir_estimate < 0.3 else 'BORDERLINE'}")

# ── Kissell comparison ─────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("KISSELL 2014 COMPARISON")
print("="*60)
kissell = {5: 0.12, 15: 0.08, 30: 0.04}  # using T+5 as proxy for T+0 (closest)
print(f"{'Timepoint':<12} {'Kissell2014':>12} {'Full sample':>12} {'Filtered':>12} {'Non-filtered':>14}")
print("-" * 65)
for lag, k_ic, full_ic, filt_ic, uf_ic in [
    (5,  kissell[5],  ic_full_5,  ic_filt_5,  ic_uf_5),
    (15, kissell[15], ic_full_15, ic_filt_15, ic_uf_15),
    (30, kissell[30], ic_full_30, ic_filt_30, ic_uf_30),
]:
    full_s  = f"{full_ic:+.4f}" if full_ic is not None else "  N/A"
    filt_s  = f"{filt_ic:+.4f}" if filt_ic is not None else "  N/A"
    uf_s    = f"{uf_ic:+.4f}"   if uf_ic   is not None else "  N/A"
    print(f"T+{lag:<10} {k_ic:>+12.4f} {full_s:>12} {filt_s:>12} {uf_s:>14}")

# ── Retirement assessment ──────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("RETIREMENT ASSESSMENT")
print("="*60)
if ic_uf_5 is not None:
    if ic_uf_5 < 0.04:
        print(f"  RETIRE: IC(T+5, NF) = {ic_uf_5:.4f} < 0.04 threshold")
        print("  H60b family RETIRED. Cannot produce IS Sharpe > 1.0 at IC < 0.04.")
    elif ic_uf_5 < 0.08:
        print(f"  MARGINAL: IC(T+5, NF) = {ic_uf_5:.4f}  (0.04-0.08 range)")
        print("  Proceed to Gate 1 with caution. Sharpe > 1.0 requires favorable market regime.")
    else:
        print(f"  PROCEED: IC(T+5, NF) = {ic_uf_5:.4f} >= 0.08")
        print("  IC sufficient. Forward to Engineering Director for Gate 1 backtest.")
else:
    print("  INSUFFICIENT DATA for assessment.")

conn.close()
print("\nDone.")
