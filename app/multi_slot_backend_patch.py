from __future__ import annotations

from fastapi import HTTPException
from . import fixed_app


def install(app):
    def _pairs_alloc_10(payload):
        capital = float(payload.get('capital', 0))
        pairs = [fixed_app._clean_pair(x) for x in payload.get('pairs', []) if fixed_app._clean_pair(x)]
        alloc = [float(x) for x in payload.get('allocations', [])]
        if not 1 <= len(pairs) <= 10:
            raise HTTPException(status_code=400, detail='Можно выбрать от 1 до 10 торговых позиций')
        if len(alloc) != len(pairs) or any(x <= 0 for x in alloc) or abs(sum(alloc) - 100) > .01:
            raise HTTPException(status_code=400, detail='Доли выбранных позиций должны дать ровно 100%')
        if capital <= 0:
            raise HTTPException(status_code=400, detail='Бюджет должен быть больше 0')
        return capital, pairs, alloc

    fixed_app._pairs_alloc = _pairs_alloc_10
