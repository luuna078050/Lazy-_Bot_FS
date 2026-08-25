"""Compatibility shim.

The final Fast Scalper UI owns pair selection. The former capture-phase picker
used a hard-coded five-slot limit and could overwrite the ten-slot UI, so it is
intentionally disabled here.
"""


def install(app):
    return
