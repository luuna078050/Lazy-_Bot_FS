from __future__ import annotations


def install():
    from . import fixed_app
    from . import paper_engine_v2
    from . import paper_engine_test_patch

    paper_engine_test_patch.install()
    # fixed_app routes resolve these names at request time. Replace the old
    # REST-polling paper engine with the WebSocket-backed v2 engine used by the
    # report layer, so start/status/report all describe the same session.
    fixed_app.start_paper = paper_engine_v2.start_paper
    fixed_app.stop_paper = paper_engine_v2.stop_paper
    fixed_app.emergency_stop_paper = paper_engine_v2.emergency_stop_paper
    fixed_app.snapshot = paper_engine_v2.snapshot
