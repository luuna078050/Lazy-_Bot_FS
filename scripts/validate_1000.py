"""Historical 1000-trade validation for Lazy Bot FS.

Uses real Binance spot OHLCV and derives 1m/3m/5m/15m/30m/1h/2h/4h bars.
No order-book history is fabricated. The test compares the regime-aware
engine across two execution profiles and exercises position reassessment on
1000 deterministic decision cases per profile.
"""
from __future__ import annotations
import bisect, json, time, urllib.parse, urllib.request
from statistics import mean
from app.strategy_intelligence import evaluate, reassess_position

BINANCE = 'https://api.binance.com/api/v3/klines'


def fetch(symbol='TUTUSDC', days=30):
    end = int(time.time() * 1000); start = end - days * 86400000; out = []
    while start < end:
        q = urllib.parse.urlencode({'symbol': symbol, 'interval': '1m', 'limit': 1000, 'startTime': start, 'endTime': end})
        with urllib.request.urlopen(BINANCE + '?' + q, timeout=30) as r:
            batch = json.load(r)
        if not batch: break
        out += batch
        nxt = int(batch[-1][0]) + 60000
        if nxt <= start: break
        start = nxt
        time.sleep(.05)
    return list({int(x[0]): x for x in out}.values())


def aggregate(rows, minutes):
    step = minutes * 60_000; buckets = {}
    for x in rows:
        ts = int(x[0]); key = ts - ts % step
        buckets.setdefault(key, []).append(x)
    out = []
    for ts in sorted(buckets):
        b = buckets[ts]
        out.append({'open_time': ts, 'open': float(b[0][1]), 'high': max(float(x[2]) for x in b), 'low': min(float(x[3]) for x in b), 'close': float(b[-1][4])})
    return out


def build_frames(rows):
    return {name: aggregate(rows, minutes) for name, minutes in [('1m',1),('3m',3),('5m',5),('15m',15),('30m',30),('1h',60),('2h',120),('4h',240)]}


def make_timeframes(frames, now_ts):
    result = {}
    for name, bars in frames.items():
        times = [x['open_time'] for x in bars]
        end = bisect.bisect_right(times, now_ts)
        f = bars[max(0, end - 110):end]
        if f:
            result[name] = {k: [x[k] for x in f] for k in ('open','high','low','close')}
    return result


def run(profile, max_trades=1000):
    rows = fetch(); frames = build_frames(rows)
    start_i = 4 * 60 * 99
    step = 3 if profile == 'scalper' else 5
    threshold = .18 if profile == 'scalper' else .20
    fee = .003
    trades = []; regimes = {}; decisions = {}
    i = start_i
    while i + step < len(rows) and len(trades) < max_trades:
        tfs = make_timeframes(frames, int(rows[i][0]))
        analysis = evaluate(tfs)
        regime = analysis['regime']['regime']; regimes[regime] = regimes.get(regime, 0) + 1
        score = analysis['score']
        enter = abs(score) >= threshold
        if regime == 'flat':
            enter = enter and abs(analysis['micro_score']) >= threshold * .8
        if not enter:
            i += 1; continue
        side = 1 if score > 0 else -1
        entry = float(rows[i][4]); exitp = float(rows[i + step][4])
        trades.append((exitp / entry - 1.0) * side - fee)
        i += step

    wins = sum(x > 0 for x in trades); eq = peak = 1.0; dd = 0.0
    for x in trades:
        eq *= 1.0 + x; peak = max(peak, eq); dd = min(dd, eq / peak - 1.0)

    for n in range(1000):
        entry = 0.060 + (n % 7) * .001; current = entry * (0.90 + (n % 13) * .01)
        analysis = {
            'score': ((n % 21) - 10) / 20.0,
            'direction': 'bullish' if n % 3 == 0 else 'bearish' if n % 3 == 1 else 'neutral',
            'regime': {'regime': ('flat' if n % 4 == 0 else 'bull' if n % 4 == 1 else 'bear' if n % 4 == 2 else 'transition')},
            'timeframes': {'1h': {'rsi14': 25 + (n % 60)}},
        }
        d = reassess_position(entry, current, n % 120, analysis, alternative_edge=(n % 9) / 100.0)
        decisions[d['action']] = decisions.get(d['action'], 0) + 1

    return {
        'profile': profile, 'symbol': 'TUTUSDC', 'bars': len(rows), 'trades': len(trades),
        'target_trades': max_trades, 'target_reached': len(trades) >= max_trades,
        'horizon_min': step, 'threshold': threshold, 'fees_plus_slippage_roundtrip_pct': fee * 100,
        'win_rate_pct': wins / len(trades) * 100 if trades else 0,
        'avg_net_return_pct': mean(trades) * 100 if trades else 0,
        'total_simple_net_return_pct': sum(trades) * 100,
        'compounded_return_pct': (eq - 1) * 100, 'max_drawdown_pct': dd * 100,
        'regimes_observed': regimes, 'position_reassessment_1000_cases': decisions,
        'orderbook_backtest': 'not fabricated; live depth module validated separately',
    }


if __name__ == '__main__':
    out = [run('scalper', 1000), run('income', 1000)]
    print(json.dumps(out, indent=2))
    with open('validation_1000_result.json', 'w') as f: json.dump(out, f, indent=2)
