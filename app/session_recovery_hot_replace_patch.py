from __future__ import annotations
import json, os, threading, time
from pathlib import Path


def install(engine):
    if getattr(engine, '_session_patch', False): return
    engine._session_patch = True
    path = Path(os.getenv('FAST_SCALPER_PAPER_STATE_FILE', 'fast_scalper_paper_state.json'))
    io_lock = threading.Lock()
    original_start, original_stop, original_emergency = engine.start_paper, engine.stop_paper, engine.emergency_stop_paper

    def save():
        try:
            with engine._lock:
                d = dict(engine._state); d['saved_at'] = engine._now()
                d['trades'] = list(engine._state.get('trades', [])[-100:])
                d['open_positions'] = {k: dict(v) for k,v in engine._state.get('open_positions',{}).items()}
                d['orders'] = {k: dict(v) for k,v in engine._state.get('orders',{}).items()}
            tmp=Path(str(path)+'.tmp')
            with io_lock: tmp.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8'); tmp.replace(path)
        except Exception: pass

    def restore():
        if not path.exists(): return False
        try:
            d=json.loads(path.read_text(encoding='utf-8'))
            if d.get('mode')!='paper' or not d.get('config'): return False
            with engine._lock:
                for k in ('running','mode','started_at','stopped_at','initial_balance','balance','pnl','trades','open_positions','orders','config','error','stop_type'):
                    if k in d: engine._state[k]=d[k]
                engine._state['previous_session_available']=True; engine._state['previous_session_saved_at']=d.get('saved_at')
            return True
        except Exception: return False

    def candidates():
        try:
            from .market_radar import RADAR
            return RADAR.snapshot(20) or []
        except Exception: return []

    def pick(rows,active,excluded):
        for r in rows:
            s=str(r.get('symbol') or '').upper().replace('-','/')
            if not s or s in active or s in excluded: continue
            sig=str(r.get('signal') or '').upper(); state=str(r.get('state') or '').upper(); score=float(r.get('score',r.get('pump_score',0)) or 0)
            if sig in {'PUMP','PUMP_NOW','NORMAL'} or state in {'IGNITION','EARLY_ROCKET'} or score>=25: return s
        return None

    def loop(_feed):
        while not engine._stop.is_set():
            try:
                feed=engine._feed
                with engine._lock:
                    cfg=dict(engine._state.get('config') or {}); slots=list(cfg.get('slots') or []); auto=bool(cfg.get('auto_replace_hot',False)); pref=max(1,int(cfg.get('preferred_slot',1) or 1))-1
                if not slots: slots=[{'pair':p,'allocation':cfg.get('allocations',[])[i]} for i,p in enumerate(cfg.get('pairs',[]))]
                for i,slot in enumerate(slots):
                    s=str(slot.get('pair') or '').upper().replace('-','/')
                    if not s: continue
                    alloc=float(slot.get('allocation') or 0); tfs=cfg.get('timeframes') or ['3m']*len(slots); tf=tfs[i] if i<len(tfs) else '3m'
                    engine._tick(s,alloc,cfg.get('target_usdt',.30),cfg.get('min_usdt',.20),cfg.get('sl_pct',.5),cfg.get('max_hold',180),feed)
                if auto:
                    with engine._lock:
                        active=set(engine._state.get('open_positions',{}))|set(engine._state.get('orders',{})); trades=list(engine._state.get('trades',[]))
                    for slot in list(slots):
                        old=str(slot.get('pair') or '').upper().replace('-','/')
                        if not old or old in active: continue
                        last=next((t for t in reversed(trades) if str(t.get('symbol','')).upper().replace('-','/')==old),None)
                        if str((last or {}).get('reason') or '').upper() not in {'PUMP_20S_EXIT','TIMEOUT','CRITICAL_EXIT'}: continue
                        new=pick(candidates(),active,{old})
                        if not new: continue
                        target_index=pref if pref<len(slots) and not (str(slots[pref].get('pair') or '') in active and str(slots[pref].get('pair') or '')!=old) else next((j for j,x in enumerate(slots) if str(x.get('pair') or '') not in active),None)
                        if target_index is None: continue
                        slots[target_index]['pair']=new
                        with engine._lock:
                            engine._state['config']['slots']=slots; engine._state['config']['pairs']=[str(x.get('pair')) for x in slots if x.get('pair')]
                        # Rebuild the websocket subscription so the replacement pair gets live prices immediately.
                        try: feed.stop()
                        except Exception: pass
                        engine._feed=engine.MarketFeed(engine._state['config']['pairs']); engine._feed.start(); feed=engine._feed
                        alloc=float(slots[target_index].get('allocation') or 0); tfs=cfg.get('timeframes') or ['3m']*len(slots); tf=tfs[target_index] if target_index<len(tfs) else '3m'
                        engine._tick(new,alloc,cfg.get('target_usdt',.30),cfg.get('min_usdt',.20),cfg.get('sl_pct',.5),cfg.get('max_hold',180),feed)
                        break
                save()
            except Exception as exc:
                with engine._lock: engine._state['error']=str(exc)[:300]
            time.sleep(1)
        with engine._lock: engine._state['running']=False; engine._state['stopped_at']=engine._now()
        save()

    restored=restore()

    def start(config,gateway):
        with engine._lock:
            running=bool(engine._state.get('running')); previous=bool(engine._state.get('previous_session_available')) and bool(engine._state.get('open_positions'))
        if running: return engine.snapshot()
        if previous and not bool(config.get('replace_previous_session',False)):
            cfg=dict(engine._state.get('config') or {})
        else:
            original_start(config,gateway)
            with engine._lock:
                cfg=dict(engine._state.get('config') or {}); rawp,rawa=list(cfg.get('pairs',[])),list(cfg.get('allocations',[]))
                slots=list(config.get('slots') or []) or [{'pair':rawp[i],'allocation':rawa[i] if i<len(rawa) else 0} for i in range(len(rawp))]
                cfg['slots']=slots; cfg['auto_replace_hot']=bool(config.get('auto_replace_hot',False)); cfg['preferred_slot']=max(1,int(config.get('preferred_slot',1) or 1)); engine._state['config']=cfg; engine._state['previous_session_available']=False
            engine._stop.set()
            if engine._feed: engine._feed.stop()
            engine._stop.clear()
        engine._stop.clear(); engine._feed=engine.MarketFeed(cfg.get('pairs',[])); engine._feed.start(); engine._thread=threading.Thread(target=loop,args=(engine._feed,),daemon=True,name='fast-scalper-paper-session'); engine._thread.start(); save(); return engine.snapshot()

    def stop(gateway): r=original_stop(gateway); save(); return r
    def emergency(gateway): r=original_emergency(gateway); save(); return r
    engine.start_paper,engine.stop_paper,engine.emergency_stop_paper=start,stop,emergency; engine._save_session_state=save
    if restored and bool(engine._state.get('running')):
        cfg=dict(engine._state.get('config') or {}); engine._stop.clear(); engine._feed=engine.MarketFeed(cfg.get('pairs',[])); engine._feed.start(); engine._thread=threading.Thread(target=loop,args=(engine._feed,),daemon=True,name='fast-scalper-paper-resume'); engine._thread.start()
