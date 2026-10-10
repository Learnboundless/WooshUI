import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AssetHealth, ProjectManifest } from "../types";

export function useAssetHealth(projectPath: string, project: ProjectManifest) {
  const [health, setHealth] = useState<AssetHealth>({ assets: [], files: [] });
  const [error, setError] = useState("");
  const signature = project.assets.map((asset) => `${asset.id}:${asset.relative_path}`).join("|") + project.timeline.tracks.flatMap((track) => track.clips.map((clip) => clip.source_path)).join("|");
  const refresh = useCallback(async () => {
    try { setHealth(await api.assetHealth(projectPath)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }, [projectPath]);
  useEffect(() => {
    let active = true;
    const check = async () => {
      try { const result = await api.assetHealth(projectPath); if (active) { setHealth(result); setError(""); } }
      catch (reason) { if (active) setError(reason instanceof Error ? reason.message : String(reason)); }
    };
    void check();
    const timer = window.setInterval(() => { if (!document.hidden) void check(); }, 15000);
    window.addEventListener("focus", check);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", check); };
  }, [projectPath, signature]);
  const missingIds = new Set(health.assets.filter((item) => !item.exists).map((item) => item.asset_id!));
  const missingPaths = new Set(health.files.filter((item) => !item.exists).map((item) => item.path));
  return { health, error, refresh, missingIds, missingPaths };
}
