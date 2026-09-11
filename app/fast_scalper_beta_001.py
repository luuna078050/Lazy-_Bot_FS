from . import fast_scalper_beta_001_legacy as legacy

# Public app entrypoint. Keep all repair layers in deterministic import order.
app = legacy.app
S = legacy.S
B = legacy.B
START = legacy.START

from . import fast_scalper_patch  # noqa: F401,E402
from . import fast_scalper_live_repair  # noqa: F401,E402
from . import fast_scalper_final_patch  # noqa: F401,E402
from . import fast_scalper_final_fix2  # noqa: F401,E402
from . import fast_scalper_snapshot_fix  # noqa: F401,E402
from . import fast_scalper_user_fix  # noqa: F401,E402
