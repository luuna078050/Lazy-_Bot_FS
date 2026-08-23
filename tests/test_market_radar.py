from app.market_radar import MarketRadar

def test_radar_returns_empty_without_tickers():
    r=MarketRadar(20)
    assert r.snapshot(20)==[]

def test_radar_scores_and_ranks_tickers():
    r=MarketRadar(20)
    with r.lock:
        for i in range(25):
            s=f'T{i}USDT'
            r.tickers[s]={'s':s,'c':str(1+i/1000),'o':'1','q':str(1000000-i*1000)}
    rows=r.snapshot(20)
    assert len(rows)==20
    assert rows[0]['symbol'].endswith('/USDT')
    assert all(0<=x['score']<=100 for x in rows)

def test_radar_excludes_stable_bases():
    r=MarketRadar(20)
    with r.lock:
        r.tickers={'USDCUSDT':{'s':'USDCUSDT','c':'1','o':'1','q':'99999999'},'BTCUSDT':{'s':'BTCUSDT','c':'100','o':'99','q':'100000'}}
    rows=r.snapshot(20)
    assert [x['symbol'] for x in rows]==['BTC/USDT']
