from app.market_radar import MarketRadar


def test_radar_returns_empty_without_tickers():
    r = MarketRadar(20)
    assert r.snapshot(20) == []


def test_radar_scores_and_ranks_tickers():
    r = MarketRadar(20)
    with r.lock:
        for i in range(25):
            s = f'T{i}USDT'
            r.tickers[s] = {'s': s, 'c': str(1 + i / 1000), 'o': '1', 'q': str(1000000 - i * 1000)}
        r._ready.set()
    rows = r.snapshot(20)
    assert len(rows) == 20
    assert rows[0]['symbol'].endswith('/USDT')
    assert all(0 <= x['score'] <= 100 for x in rows)


def test_radar_excludes_stable_bases():
    r = MarketRadar(20)
    with r.lock:
        r.tickers = {
            'USDCUSDT': {'s': 'USDCUSDT', 'c': '1', 'o': '1', 'q': '99999999'},
            'BTCUSDT': {'s': 'BTCUSDT', 'c': '100', 'o': '99', 'q': '100000'},
        }
        r._ready.set()
    rows = r.snapshot(20)
    assert [x['symbol'] for x in rows] == ['BTC/USDT']


def test_websocket_uses_render_compatible_443_and_no_rest_polling():
    r = MarketRadar(20)
    url = r._build_url()
    assert url.startswith('wss://stream.binance.com:443/stream?streams=')
    assert '!miniTicker@arr' in url
    assert '@kline_3m' in url
    assert '@aggTrade' in url


def test_three_min_metrics_are_based_on_kline_not_pulse():
    r = MarketRadar(20)
    with r.lock:
        r.bars['BTCUSDT'].extend([
            {'ts': 1, 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'quote_volume': 1000, 'closed': True},
            {'ts': 2, 'open': 100.5, 'high': 101.5, 'low': 100, 'close': 101.0, 'quote_volume': 1200, 'closed': True},
            {'ts': 3, 'open': 101, 'high': 102, 'low': 100.8, 'close': 101.5, 'quote_volume': 1500, 'closed': True},
        ])
    metrics = r._three_min_metrics('BTCUSDT', 102.0)
    assert round(metrics['change_3m_pct'], 3) == round((102 / 101 - 1) * 100, 3)
    assert metrics['volume_ratio'] > 1
