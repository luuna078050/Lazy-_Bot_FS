from __future__ import annotations

# The final UI is now supplied by app.ui_v10. This compatibility installer is
# intentionally kept as a no-op so older report patches can remain imported
# without replacing the new TOP-10 rotation renderer.
def install(app):
    return
