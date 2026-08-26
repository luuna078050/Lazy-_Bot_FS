from __future__ import annotations

import threading
import time

from . import profit_first_engine_v4 as engine
from . import profit_first_engine_v3 as base


def install():
    if getattr(engine, '_paper_stability_installed', False):
        return
    original_start = engine.start_paper
    lock = threading.RLock()
    generation = {'id': 0}

    def stable_start(config, gateway_unused=None):
        with lock:
            # A second click must not create a competing PAPER engine.
            if bool(base.STATE.get('running')) and engine.base.THREAD and engine.base.THREAD.is_alive():
                return engine.snapshot()
            generation['id'] += 1
            gid = generation['id']
            result = original_start(config, gateway_unused)
            # Keep the session alive if the worker has a transient failure.
            def watchdog():
                while not base.STOP.is_set() and generation['id'] == gid:
                    time.sleep(0.75)
                    if base.STOP.is_set() or generation['id'] != gid:
                        break
                    thread = engine.base.THREAD
                    if thread is not None and not thread.is_alive():
                        with base.LOCK:
                            base.STATE['error'] = base.STATE.get('error') or 'PAPER worker stopped unexpectedly; restarting test worker.'
                        try:
                            base.STOP.clear()
                            base.STATE['running'] = True
                            engine.base.THREAD = threading.Thread(target=engine.base.loop, daemon=True, name='fast-scalper-paper-recovery')
                            engine.base.THREAD.start()
                        except Exception as exc:
                            with base.LOCK:
                                base.STATE['running'] = False
                                base.STATE['error'] = str(exc)[:300]
                            break
                    else:
                        with base.LOCK:
                            base.STATE['running'] = True
            threading.Thread(target=watchdog, daemon=True, name='fast-scalper-paper-watchdog').start()
            return result

    engine.start_paper = stable_start
    engine._paper_stability_installed = True
