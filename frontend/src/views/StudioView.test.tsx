import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { GeneratedAsset, ProjectManifest } from "../types";
import { StudioView } from "./StudioView";

const sourceAsset: GeneratedAsset = {
  id: "asset-1",
  name: "music",
  relative_path: "Generated/Music/music.wav",
  source: "generated",
  kind: "music_mix",
  prompt_original: null,
  prompt_conditioned: null,
  model_id: "HeartMuLa-3B",
  seed: 42,
  sample_rate: 48000,
  channel_count: 2,
  duration_seconds: 30,
  generation_group_id: "group-1",
  parent_asset_id: null,
  stem_role: null,
  music_metadata: null,
  favorite: false,
  tags: [],
  created_at: "2026-01-01T00:00:00Z",
};

const project: ProjectManifest = {
  schema_version: 2,
  id: "project-1",
  name: "Studio Test",
  description: "",
  sample_rate: 48000,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  assets: [sourceAsset],
  timeline: {
    sample_rate: 48000,
    duration_seconds: 30,
    loop_start_seconds: null,
    loop_end_seconds: null,
    tracks: [
      {
        id: "track-1",
        name: "Music",
        muted: false,
        solo: false,
        gain_db: 0,
        pan: 0,
        role: "music",
        clips: [
          {
            id: "clip-1",
            asset_id: sourceAsset.id,
            name: sourceAsset.name,
            source_path: sourceAsset.relative_path,
            start_seconds: 0,
            trim_start_seconds: 0,
            trim_end_seconds: null,
            fade_in_seconds: 0,
            fade_out_seconds: 0,
            gain_db: 0,
            pan: 0,
            loop_enabled: false,
            loop_start_seconds: null,
            loop_end_seconds: null,
            effects: [],
          },
        ],
      },
    ],
    master_effects: [],
  },
  export_preset: {
    format: "wav24",
    package: "files",
    naming_template: "{category}_{name}_{variant:02}",
    category: "SFX",
  },
};

describe("StudioView", () => {
  it("auto trims any selected timeline asset and switches the clip", async () => {
    const derivedAsset: GeneratedAsset = {
      ...sourceAsset,
      id: "asset-2",
      name: "music_裁剪",
      relative_path: "Generated/Processed/music_裁剪.wav",
      source: "rendered",
      kind: "render",
      parent_asset_id: sourceAsset.id,
      duration_seconds: 28,
    };
    const manifest = { ...project, assets: [sourceAsset, derivedAsset] };
    vi.spyOn(api, "trimAsset").mockResolvedValue({
      manifest,
      asset: derivedAsset,
      details: {
        mode: "trim_silence",
        start_seconds: 1,
        end_seconds: 29,
        removed_seconds: 2,
      },
    });
    const saveProject = vi.spyOn(api, "saveProject").mockImplementation(
      async (_path, next) => next,
    );
    const onProjectChange = vi.fn();
    render(
      <StudioView
        projectPath="E:\\studio.woosh"
        project={project}
        onProjectChange={onProjectChange}
        onError={vi.fn()}
      />,
    );

    fireEvent.contextMenu(screen.getByRole("button", { name: "music" }), {
      clientX: 180,
      clientY: 240,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "自动去首尾空白" }));

    await waitFor(() => expect(saveProject).toHaveBeenCalled());
    const savedManifest = saveProject.mock.calls[0][1];
    const clip = savedManifest.timeline.tracks[0].clips[0];
    expect(clip.asset_id).toBe(derivedAsset.id);
    expect(clip.source_path).toBe(derivedAsset.relative_path);
    expect(onProjectChange).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
