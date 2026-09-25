from app.three_phase import analyze_three_phase

def series(vals):
    highs=[v*1.002 for v in vals]
    lows=[v*0.998 for v in vals]
    vols=[100.0]*len(vals)
    return vals,highs,lows,vols

def test_three_phase_has_required_fields():
    vals=[100+i*0.15 for i in range(120)]
    vals += [117.5,117.0,116.4,115.8,116.2,116.8,117.3]
    c,h,l,v=series(vals)
    x=analyze_three_phase(c,h,l,v)
    assert x.phase in {"PHASE_1_IMPULSE","PHASE_2_CORRECTION","PHASE_3_RECOVERY","NEUTRAL","UNKNOWN"}
    assert 0 <= x.rsi <= 100
    assert 0 <= x.stoch_k <= 100
    assert 0 <= x.stoch_d <= 100
    assert 0 <= x.confidence <= 100

def test_overheated_resistance_blocks_chase():
    vals=[100+i*0.10 for i in range(120)]
    vals += [112,113,114,115,116,117,118,119,120]
    c,h,l,v=series(vals)
    x=analyze_three_phase(c,h,l,v,price=c[-1],resistance=c[-1]*0.999)
    assert x.gate == "BLOCK"
    assert x.action == "NO_CHASE"
