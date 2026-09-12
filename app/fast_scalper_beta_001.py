from . import fast_scalper_beta_001_legacy as legacy

# Single runtime entrypoint. No stacked repair/patch imports.
app = legacy.app
S = legacy.S
B = legacy.B
START = legacy.START

from . import fast_scalper_runtime  # noqa: F401,E402
