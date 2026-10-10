from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .projects import ProjectService, safe_name
from .schemas import GeneratedAsset

API_ROOT = "https://freesound.org/apiv2"
PREVIEW_HOSTS = {"freesound.org", "www.freesound.org", "cdn.freesound.org"}


class FreesoundService:
    def __init__(self, projects: ProjectService, database):
        self.projects = projects
        self.database = database

    def _token(self) -> str:
        import os

        token = os.environ.get("FREESOUND_API_KEY", "").strip()
        if token:
            return token
        settings = self.database.get_settings()
        return (settings.freesound_api_key or "").strip()

    def status(self) -> dict:
        return {"configured": bool(self._token()), "website": "https://freesound.org"}

    def search(
        self, query: str, page: int, page_size: int, filter_value: str | None
    ) -> dict:
        token = self._token()
        if not token:
            raise PermissionError(
                "Freesound API 尚未配置。请在设置中填写 API key，或点击“在网站打开”手动浏览。"
            )
        params = {
            "query": query.strip(),
            "page": page,
            "page_size": page_size,
            "token": token,
            "fields": "id,name,description,tags,username,license,duration,previews,download,url,filesize,samplerate,channels",
        }
        if filter_value:
            params["filter"] = filter_value.strip()
        try:
            response = httpx.get(
                f"{API_ROOT}/search/text/",
                params=params,
                timeout=20,
                follow_redirects=True,
            )
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "Freesound request failed",
                    request=response.request,
                    response=response,
                )
            data = response.json()
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403}:
                raise PermissionError(
                    "Freesound API key 无效或已被拒绝，请在设置中更新。"
                ) from error
            raise RuntimeError(
                f"Freesound 搜索失败（HTTP {error.response.status_code}）"
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError(f"无法连接 Freesound：{error}") from error
        results = []
        for item in data.get("results", []):
            previews = item.get("previews") or {}
            preview = (
                previews.get("preview-hq-mp3")
                or previews.get("preview-lq-mp3")
                or previews.get("preview-hq-ogg")
            )
            if not preview:
                continue
            results.append(
                {
                    "id": int(item["id"]),
                    "name": str(item.get("name", "")),
                    "description": re.sub(
                        r"\s+",
                        " ",
                        re.sub(r"<[^>]+>", " ", str(item.get("description", ""))),
                    ).strip(),
                    "tags": item.get("tags", []),
                    "username": str(item.get("username", "")),
                    "license": str(item.get("license", "")),
                    "duration": float(item.get("duration") or 0),
                    "preview_url": preview,
                    "sound_url": str(
                        item.get("url") or f"https://freesound.org/s/{item['id']}/"
                    ),
                    "filesize": int(item.get("filesize") or 0),
                    "samplerate": int(item.get("samplerate") or 0),
                    "channels": int(item.get("channels") or 0),
                }
            )
        return {
            "count": int(data.get("count", 0)),
            "page": page,
            "page_size": page_size,
            "results": results,
            "next": bool(data.get("next")),
            "previous": bool(data.get("previous")),
        }

    def import_preview(self, request, root: Path) -> dict:
        token = self._token()
        parsed = urlparse(request.preview_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in PREVIEW_HOSTS or not parsed.path:
            raise ValueError("只能导入 Freesound 官方 HTTPS preview 或 download 地址")
        if request.sound_id < 1:
            raise ValueError("Freesound sound ID 无效")
        headers = {"Authorization": f"Token {token}"} if token else {}
        try:
            response = httpx.get(
                request.preview_url, headers=headers, timeout=60, follow_redirects=True
            )
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "Freesound preview failed",
                    request=response.request,
                    response=response,
                )
        except httpx.HTTPError as error:
            raise RuntimeError(f"Freesound 预览下载失败：{error}") from error
        content_type = response.headers.get("content-type", "").lower()
        if len(response.content) > 200 * 1024 * 1024:
            raise ValueError("Freesound 预览文件超过 200 MB")
        suffix = (
            ".ogg"
            if "ogg" in content_type or request.preview_url.lower().endswith(".ogg")
            else ".mp3"
        )
        safe = safe_name(request.name)[:120]
        destination = (
            root / "Sources" / "Freesound" / f"{request.sound_id}_{safe}{suffix}"
        )
        destination = self.projects._unique_path(destination.parent, destination.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        sample_rate, channels, duration = 48_000, 2, request.duration
        try:
            import soundfile as sf

            info = sf.info(destination)
            if info.frames <= 0:
                raise ValueError("Freesound 预览没有音频帧")
            sample_rate, channels, duration = (
                info.samplerate,
                info.channels,
                info.duration,
            )
        except (RuntimeError, OSError):
            # MP3 preview decoding depends on the platform's libsndfile build. Keep the
            # downloaded preview usable in the browser even when metadata probing fails.
            if duration <= 0:
                duration = 0
        relative = destination.relative_to(root).as_posix()
        asset = GeneratedAsset(
            name=safe,
            relative_path=relative,
            source="imported",
            kind="imported",
            sample_rate=sample_rate,
            channel_count=channels,
            duration_seconds=duration,
            tags=["freesound"],
            music_metadata={
                "provider": "freesound",
                "sound_id": request.sound_id,
                "sound_url": request.sound_url,
                "username": request.username,
                "license": request.license,
                "preview_url": request.preview_url,
                "attribution": f"{request.name} by {request.username} ({request.license})".strip(),
            },
        )
        manifest = self.projects.mutate(
            root, lambda latest: latest.assets.append(asset)
        )
        return {"manifest": manifest, "asset": asset}
