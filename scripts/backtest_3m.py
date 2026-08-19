import argparse
import csv
import itertools
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BINANCE = "https://fapi.binance.com/fapi/v1/klines"

@dataclass
class Bar:
    ts: int
    close: float


def fetch_klines(symbol: str, interval: str, days: int) -> list[Bar]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[Bar] = []
    while start_ms < end_ms:
        qs = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": 1000, "startTime": start_ms, "endTime": end_ms})
        with urllib.request.urlopen(BINANCE + "?" + qs, timeout=30) as r:
            batch = __import__("json").load(r)
        if not batch:
            break
        for x in batch:
            rows.append(Bar(int(x[0]), float(x[4])))
        nxt = int(batch[-1][0]) + 1
        if nxt <= start_ms:
            break
        start_ms = nxt
        time.sleep(0.15)
    # deduplicate by timestamp
    return list({b.ts: b for b in rows}.values())


def ema(values: list[float], period: int) -> float:
    k = 2 / (period + 1)
    v = values[0]
    for x in values[1:]:
        v = x * k + v * (1 - k)
    return v


def signals(bars: list[Bar], fast: int, slow: int, mom_n: int, threshold: float):
    out = []
    for i in range(max(slow, mom_n), len(bars) - 1):
        closes = [b.close for b in bars[i-slow+1:i+1]]
        f = ema(closes, fast)
        s = ema(closes, slow)
        mom = bars[i].close / bars[i-mom_n].close - 1
        if f > s and mom >= threshold:
            out.append((i, 1))
        elif f < s and mom <= -threshold:
            out.append((i, -1))
    return out


def score(bars: list[Bar], fast: int, slow: int, mom_n: int, threshold: float, horizon: int):
    sigs = signals(bars, fast, slow, mom_n, threshold)
    if not sigs:
        return None
    wins = 0
    pnl = 0.0
    for i, side in sigs:
        j = min(i + horizon, len(bars) - 1)
        ret = (bars[j].close / bars[i].close - 1) * side
        pnl += ret
        wins += ret > 0
    return {"signals": len(sigs), "accuracy": wins / len(sigs), "avg_return": pnl / len(sigs), "total_return": pnl}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--horizon", type=int, default=3)
    args = ap.parse_args()
    bars = fetch_klines(args.symbol, args.interval, args.days)
    if len(bars) < 300:
        raise SystemExit(f"Not enough data: {len(bars)} bars")
    split = int(len(bars) * 0.70)
    train, test = bars[:split], bars[split:]
    candidates = []
    for fast, slow, threshold in itertools.product([5,7,9,12,15], [18,21,26,30,34], [0.001,0.0015,0.002,0.0025,0.003]):
        if fast >= slow:
            continue
        r = score(train, fast, slow, 3, threshold, args.horizon)
        if r and r["signals"] >= 20:
            candidates.append((r["accuracy"], r["avg_return"], fast, slow, threshold, r["signals"]))
    candidates.sort(reverse=True)
    best = candidates[0]
    _, _, fast, slow, threshold, train_signals = best
    test_r = score(test, fast, slow, 3, threshold, args.horizon)
    result = {
        "symbol": args.symbol,
        "interval": args.interval,
        "days": args.days,
        "bars": len(bars),
        "split": "70/30 chronological",
        "selected": {"fast": fast, "slow": slow, "momentum_threshold": threshold, "train_signals": train_signals},
        "train_accuracy": best[0],
        "train_avg_return": best[1],
        "test": test_r,
        "warning": "Accuracy is directional hit-rate for the defined horizon, not a guarantee of profitable trading or future performance. Parameters are selected on the training window only."
    }
    print(__import__("json").dumps(result, indent=2))
    with open("backtest_result.json", "w", encoding="utf-8") as f:
        __import__("json").dump(result, f, indent=2)

if __name__ == "__main__":
    main()
