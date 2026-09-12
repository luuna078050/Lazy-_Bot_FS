from . import fast_scalper_beta_001_legacy as legacy

# Single runtime entrypoint. Core logic and approved UI are loaded once.
app = legacy.app
S = legacy.S
B = legacy.B
START = legacy.START

from . import fast_scalper_runtime  # noqa: F401,E402
from . import fast_scalper_approved_ui  # noqa: F401,E402
