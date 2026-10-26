"""QUA-823: fetch daily OHLCV (2017-06-01 to 2021-12-31, IS only) from Alpaca for the Jan-2018 universe,
including names later delisted. Output: parquet cache under backtests/h93_cache/."""
import os, sys, time, requests, pandas as pd

H = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"]}
URL = "https://data.alpaca.markets/v2/stocks/bars"
START, END = "2017-06-01", "2021-12-31"  # no OOS data (2022+) is requested

def fetch(symbols):
    rows, token = [], None
    while True:
        p = dict(symbols=",".join(symbols), timeframe="1Day", start=START, end=END,
                 limit=10000, adjustment="all", feed="sip")
        if token: p["page_token"] = token
        r = requests.get(URL, headers=H, params=p, timeout=60)
        r.raise_for_status()
        j = r.json()
        for s, bars in j["bars"].items():
            for b in bars: rows.append((s, b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]))
        token = j.get("next_page_token")
        if not token: break
    return rows

if __name__ == "__main__":
    univ = [t.replace("-", ".") for t in pd.read_csv(sys.argv[1])["ticker"]]
    out = sys.argv[2]; os.makedirs(os.path.dirname(out), exist_ok=True)
    rows, bad = [], []
    for i in range(0, len(univ), 50):
        batch = univ[i:i+50]
        try:
            rows += fetch(batch)
        except requests.HTTPError:  # one invalid symbol rejects the whole batch
            for sym in batch:
                try: rows += fetch([sym])
                except requests.HTTPError: bad.append(sym)
        time.sleep(0.3)
    df = pd.DataFrame(rows, columns=["sym","date","open","high","low","close","volume"])
    df.to_parquet(out) if out.endswith(".parquet") else df.to_csv(out, index=False)
    print("rejected symbols:", bad)
    print(len(univ), "requested;", df.sym.nunique(), "returned;", len(df), "rows")
