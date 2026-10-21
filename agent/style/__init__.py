"""
Style / variation layer (plan §3, §6). Phase 2 ships the writer brief + 8D anti-AI check.

    from agent.style.profile import brief          # Task brief block for the writer prompt
    from agent.style.antiai import check_style     # 8D
"""
from __future__ import annotations

__all__ = ["profile", "antiai", "similarity"]
