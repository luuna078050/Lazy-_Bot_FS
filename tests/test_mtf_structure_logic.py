from app.strategy_intelligence import evaluate, timeframe_signal


def _series(start=100.0, step=0.5, n=120):
    c=[start+i*step for i in range(n)]
    return {"close":c,"high":[x+0.1 for x in c],"low":[x-0.1 for x in c]}


def test_timeframe_signal_reports_smooth_uptrend():
    s=timeframe_signal(_series())
    assert s["direction"] == "bullish"
    assert s["trend_smoothness"] > 0.5
    assert s["structure"]["score"] >= 0


def test_evaluate_accepts_30s_and_orderbook_flow():
    tfs={tf:_series() for tf in ("4h","2h","1h","30m","15m","5m","3m","1m")}
    result=evaluate(tfs,{"score":0.6,"spoof_risk":0.0,"pressure_velocity":0.2},{"score":0.7},0.5)
    assert result["direction"] == "bullish"
    assert result["micro_30s_score"] == 0.7
    assert result["volume_flow"] == 0.5
