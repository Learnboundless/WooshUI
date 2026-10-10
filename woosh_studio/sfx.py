from __future__ import annotations
import re
from .projects import safe_name


def automatic_sound_name(prompt: str) -> str:
    text = re.sub(
        r"^(?:请)?(?:帮我)?(?:生成|制作|创建)(?:一个|一段)?", "", prompt.strip()
    )
    text = re.split(r"[，,。.!！?？;；\n]|\bwith\b", text, maxsplit=1, flags=re.I)[
        0
    ].strip()
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I)
    text = safe_name(text).strip()[:36].rstrip(" ._-，")
    return text or "新音效"


def is_sfx_asset(asset, assets):
    seen = set()
    while asset and asset.id not in seen:
        seen.add(asset.id)
        if (
            asset.kind == "sfx"
            or asset.kind == "render"
            and (asset.music_metadata or {}).get("sfx_family")
        ):
            return True
        if asset.kind != "render":
            return False
        asset = assets.get(asset.parent_asset_id)
    return False
