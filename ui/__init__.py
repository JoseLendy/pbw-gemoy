"""UI package (Phase 3 → Vue rewrite). Display helpers live in ui.components; ui.state holds the 门店端
session rules; ui.compare_view / ui.hq_view / ui.baseline_view hold the other three tabs' view functions.
server.py (FastAPI) exposes them as JSON to the Vue frontend; every backend call goes through agent.ui_data.
"""
