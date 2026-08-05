import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ModelDescriptor, ProjectManifest } from "../types";
import { MusicView } from "./MusicView";

const project: ProjectManifest = {
  schema_version: 2,
  id: "project-1",
  name: "Music Test",
  description: "",
  sample_rate: 48000,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  assets: [],
  timeline: {
    sample_rate: 48000,
    duration_seconds: 8,
    loop_start_seconds: null,
    loop_end_seconds: null,
    tracks: [],
    master_effects: [],
  },
  export_preset: {
    format: "wav24",
    package: "files",
    naming_template: "{category}_{name}_{variant:02}",
    category: "Music",
  },
};

function model(id: string, family: ModelDescriptor["family"], installed: boolean): ModelDescriptor {
  return {
    id,
    name: id,
    family,
    description: "",
    release: "test",
    license: "Apache 2.0",
    license_url: "",
    installed,
    custom: false,
    path: null,
    dependencies: [],
    controls: [],
    supported: true,
    engine: family === "music" ? "heartmula" : "demucs",
    model_source: "modelscope",
    memory_mode: "auto_low_vram",
  };
}

describe("MusicView", () => {
  it("switches to lyrics mode and inserts section markers", () => {
    render(<MusicView projectPath="E:\\test.woosh" project={project} models={[]} onProjectChange={vi.fn()} onQueued={vi.fn()} onError={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /带歌词歌曲/ }));
    fireEvent.click(screen.getByRole("button", { name: "[Bridge]" }));

    expect((screen.getByLabelText("歌曲歌词") as HTMLTextAreaElement).value).toContain("[Bridge]");
  });

  it("reports the missing music model before submitting", () => {
    const onError = vi.fn();
    render(<MusicView projectPath="E:\\test.woosh" project={project} models={[model("HeartMuLa-3B", "music", false), model("Demucs-htdemucs", "separation", true)]} onProjectChange={vi.fn()} onQueued={vi.fn()} onError={onError} />);

    fireEvent.click(screen.getByRole("button", { name: /生成 1 个变体/ }));

    expect(onError).toHaveBeenCalledWith(expect.stringContaining("HeartMuLa"));
  });

  it("adds one selected stem to its matching timeline track", async () => {
    const stemProject: ProjectManifest = {
      ...project,
      assets: [{
        id: "drums-1",
        name: "Battle Theme_drums",
        relative_path: "Generated/Music/group/Stems/drums.wav",
        source: "generated",
        kind: "stem",
        prompt_original: null,
        prompt_conditioned: null,
        model_id: "Demucs-htdemucs",
        seed: 42,
        sample_rate: 48000,
        channel_count: 2,
        duration_seconds: 30,
        generation_group_id: "group",
        parent_asset_id: "mix-1",
        stem_role: "drums",
        music_metadata: { native_stem: false },
        favorite: false,
        tags: [],
        created_at: "2026-01-01T00:00:00Z",
      }],
    };
    const save = vi.spyOn(api, "saveProject").mockImplementation(async (_path, manifest) => manifest);
    render(<MusicView projectPath="E:\\test.woosh" project={stemProject} models={[]} onProjectChange={vi.fn()} onQueued={vi.fn()} onError={vi.fn()} />);

    fireEvent.click(screen.getByTitle("单独加入工作台"));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const saved = save.mock.calls[0][1];
    expect(saved.timeline.tracks).toHaveLength(1);
    expect(saved.timeline.tracks[0].role).toBe("drums");
    save.mockRestore();
  });
});
