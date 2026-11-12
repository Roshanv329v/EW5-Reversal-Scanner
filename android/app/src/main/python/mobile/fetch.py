"""
Yahoo download without yfinance.

Recent yfinance versions need a native HTTP library that is not built for Android, so
this calls the same Yahoo chart endpoint with the standard library. `yahoo_fetch` has the
data_store.FetchFn contract: (tickers, interval, period, start) -> {ticker: OHLCV frame},
so core/data_store.update_data does the merging, 4hr, 1W and indicators as on the desktop.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pandas as pd

USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36"
CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
WORKERS = 6                 # parallel requests; Yahoo starts refusing (HTTP 429) well above this
ATTEMPTS = 3


def _get(url: str) -> dict:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            if attempt == ATTEMPTS:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == ATTEMPTS:
                raise
        time.sleep(2.0 * attempt)
    return {}


def one(symbol: str, interval: str, period: Optional[str], start: Optional[str]) -> Optional[pd.DataFrame]:
    """Bars of one symbol: tz-aware UTC index for intraday, exchange calendar days for daily."""
    query = {"interval": interval, "includePrePost": "false", "events": "split"}
    if start is not None:
        query["period1"] = str(int(pd.Timestamp(start).tz_localize("UTC").timestamp()))
        query["period2"] = str(int(time.time()))
    else:
        query["range"] = period
    payload = _get(CHART_URL.format(symbol=urllib.parse.quote(symbol), query=urllib.parse.urlencode(query)))
    result = (payload.get("chart") or {}).get("result") or []
    if not result or not result[0].get("timestamp"):
        return None
    r = result[0]
    q = r["indicators"]["quote"][0]
    index = pd.to_datetime(r["timestamp"], unit="s", utc=True)
    frame = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                          "Close": q["close"], "Volume": q["volume"]}, index=index)
    if interval == "1d":
        tz = r.get("meta", {}).get("exchangeTimezoneName") or "UTC"
        frame.index = frame.index.tz_convert(tz).tz_localize(None).normalize()
    return frame.dropna(how="all")


def yahoo_fetch(tickers, interval, period, start) -> dict[str, pd.DataFrame]:
    def safe(t: str):
        try:
            return t, one(t, interval, period, start)
        except Exception:          # one bad symbol must not stop the batch; data_store reports it
            return t, None

    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, frame in pool.map(safe, list(tickers)):
            if frame is not None and not frame.empty:
                out[t] = frame
    return out
