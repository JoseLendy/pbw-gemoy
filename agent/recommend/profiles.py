"""
Store voice profile (plan §6.1): auto landmark / voice / nickname + the store's own edits.
Voice is chosen by md5(store_id) among the voices allowed for the dominant segment; an override
voice not allowed for that segment is rejected (never silently accepted).
"""
from __future__ import annotations

from typing import Optional

from agent.recommend.common import stable_hash


def voices_by_id(angles: dict) -> dict[str, dict]:
    return {v["id"]: v for v in angles["voices"]}


def voice_allowed(voice_id: str, segment: str, angles: dict) -> bool:
    v = voices_by_id(angles).get(voice_id)
    return bool(v) and segment in v["allowed_segments"]


def check_voice(voice_id: Optional[str], segment: str, angles: dict, who: str = "") -> None:
    """Raise ValueError if `voice_id` is unknown or not allowed for `segment`."""
    if voice_id is None:
        return
    if voice_id not in voices_by_id(angles):
        raise ValueError(f"{who + ': ' if who else ''}unknown voice {voice_id!r}")
    if not voice_allowed(voice_id, segment, angles):
        raise ValueError(f"{who + ': ' if who else ''}voice {voice_id} not allowed for segment {segment}")


def build_profiles(stores: list[dict], signals: dict, angles: dict, overrides: dict) -> dict:
    voices = voices_by_id(angles)
    profiles = {}
    for st in stores:
        dom = signals[st["store_id"]]["dominant"]
        allowed = [v for v in angles["voices"] if dom in v["allowed_segments"]]
        voice = allowed[stable_hash(st["store_id"], "voice") % len(allowed)]
        profiles[st["store_id"]] = {
            "store_id": st["store_id"], "store_name": st["store_name"],
            "landmark": f"{st['anchor_poi']}附近", "landmark_source": "auto_from_poi",
            "voice": voice["id"], "voice_label": voice["label"],
            "nickname": angles["nicknames"][stable_hash(st["store_id"], "nick") % len(angles["nicknames"])],
            "editable_by_store": True, "is_demo": True,
        }
        ov = overrides.get(st["store_id"], {})
        if "voice" in ov:
            check_voice(ov["voice"], dom, angles, who=st["store_id"])
            profiles[st["store_id"]].update(voice=ov["voice"], voice_label=voices[ov["voice"]]["label"])
        if "landmark" in ov:
            profiles[st["store_id"]].update(landmark=ov["landmark"], landmark_source="edited_by_store")
        if "nickname" in ov:
            profiles[st["store_id"]]["nickname"] = ov["nickname"]
    return profiles
