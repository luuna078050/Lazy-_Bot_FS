from app.pump_detector import analyze_3m_ohlcv

def rows(prices, vols):
    return [[i*180000, p, p, p, p, v] for i,(p,v) in enumerate(zip(prices,vols))]

def test_normal_market():
    r=analyze_3m_ohlcv(rows([1+i*0.0001 for i in range(20)],[100]*20))
    assert r['signal']=='NORMAL'
    assert r['pump_events']==0

def test_pump_now():
    prices=[1.0]*16+[1.01,1.02,1.03,1.036]; vols=[100]*19+[500]
    r=analyze_3m_ohlcv(rows(prices,vols))
    assert r['signal']=='PUMP_NOW'
    assert r['hold_seconds']==20
    assert r['pump_score']>0.55

def test_pump_history():
    prices=[1.0]*10; vols=[100]*10
    for _ in range(3):
        prices += [prices[-1]*1.01, prices[-1]*1.01]; vols += [250,100]
    r=analyze_3m_ohlcv(rows(prices,vols))
    assert r['pump_events']>=2
    assert r['signal']=='PUMP_HISTORY'

def test_one_thousand_deterministic_cases():
    for n in range(1000):
        base=1+n%17/1000; prices=[base*(1+(i%5)*0.0001) for i in range(20)]; vols=[100+(i%7) for i in range(20)]
        if n%11==0: prices[-1]*=1.01; vols[-1]=400
        result=analyze_3m_ohlcv(rows(prices,vols))
        assert 0<=result['pump_score']<=1
        assert result['hold_seconds'] in (20,180)
