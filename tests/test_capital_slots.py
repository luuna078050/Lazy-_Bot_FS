from app.capital_slots import CapitalAllocator


def test_slot_keeps_percentage_when_symbol_changes():
    a=CapitalAllocator(100,[10,8,15],mode='auto')
    a.assign(1,'OLDUSDC',.7)
    out=a.rebalance([{'symbol':'OLDUSDC','score':.2},{'symbol':'NEWUSDT','score':.9}])
    assert out[0]['action']=='REPLACE'
    assert out[0]['allocation_pct']==10
    assert out[0]['amount']==10
    assert out[0]['new_symbol']=='NEWUSDT'


def test_manual_lock_prevents_replacement():
    a=CapitalAllocator(100,[10],mode='manual'); a.assign(1,'OLDUSDC',.8); a.slots[0].locked=True
    assert a.rebalance([{'symbol':'OLDUSDC','score':.1},{'symbol':'NEWUSDT','score':.9}])==[]
