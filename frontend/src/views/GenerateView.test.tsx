import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ModelDescriptor, ProjectManifest } from "../types";
import { GenerateView } from "./GenerateView";

const project: ProjectManifest = {
  schema_version: 2,
  id: "project-1",
  name: "SFX Test",
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
    category: "SFX",
  },
};

const dflow: ModelDescriptor = {
  id: "Woosh-DFlow",
  name: "Woosh-DFlow",
  family: "text",
  description: "",
  release: "test",
  license: "CC BY-NC 4.0",
  license_url: "",
  installed: true,
  custom: false,
  path: null,
  dependencies: [],
  controls: [],
  supported: true,
  engine: "woosh",
  model_source: "github",
  memory_mode: "auto_low_vram",
};

const translationModel: ModelDescriptor = {
  ...dflow,
  id: "opus-mt-zh-en",
  name: "轻量中文转英文",
  family: "translation",
  installed: false,
  engine: "ctranslate2",
  memory_mode: "cpu",
};

describe("GenerateView", () => {
  it("automatically prepares the local translation model on first use", async () => {
    const queuedJob = {
      id: "translation-job",
      kind: "model_download" as const,
      status: "queued" as const,
      progress: 0,
      stage: "等待中",
      message: "",
      speed_bytes_per_second: null,
      payload: { model_id: "opus-mt-zh-en" },
      result: null,
      error: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const downloadModel = vi.spyOn(api, "downloadModel").mockResolvedValue(queuedJob);
    const getJob = vi.spyOn(api, "job").mockResolvedValue({
      ...queuedJob,
      status: "completed",
      progress: 1,
    });
    const translate = vi.spyOn(api, "translate").mockResolvedValue({
      original: "重型机甲落地，金属冲击与短促液压声",
      translated: "a heavy mech landing with a metallic impact",
      translation: { source_text: "重型机甲落地，金属冲击与短促液压声", source_language: "Chinese", target_language: "English", text: "a heavy mech landing with a metallic impact", model_id: "opus-mt-zh-en" },
    });
    const onQueued = vi.fn();
    render(
      <GenerateView
        projectPath="E:\\test.woosh"
        project={project}
        models={[dflow, translationModel]}
        activeModel="Woosh-DFlow"
        onModelChange={vi.fn()}
        onProjectChange={vi.fn()}
        onQueued={onQueued}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "转为英文" }));

    await waitFor(() =>
      expect(screen.getByLabelText("英文模型提示词")).toHaveValue(
        "a heavy mech landing with a metallic impact",
      ),
    );
    expect(downloadModel).toHaveBeenCalledWith("opus-mt-zh-en");
    expect(getJob).toHaveBeenCalledWith("translation-job");
    expect(translate).toHaveBeenCalled();
    expect(onQueued).toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("uses bundled multilingual translation on a fresh machine without downloading OPUS", async () => {
    const download = vi.spyOn(api, "downloadModel");
    vi.spyOn(api, "translate").mockResolvedValue({ original: "重型机甲落地", translated: "A heavy mech lands.", translation: { source_text: "重型机甲落地", source_language: "Chinese", target_language: "English", text: "A heavy mech lands.", model_id: "m2m100-418M-int8" } });
    const builtin = { ...translationModel, id: "m2m100-418M-int8", installed: true, bundled: true };
    render(<GenerateView projectPath="E:/fresh.woosh" project={project} models={[dflow, builtin]} activeModel="Woosh-DFlow" onModelChange={vi.fn()} onProjectChange={vi.fn()} onQueued={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "转为英文" }));
    await waitFor(() => expect(screen.getByLabelText("英文模型提示词")).toHaveValue("A heavy mech lands."));
    expect(download).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("submits the user-defined SFX name before generation", async () => {
    const generate = vi.spyOn(api, "generate").mockResolvedValue({
      id: "job-1",
      kind: "generation",
      status: "queued",
      progress: 0,
      stage: "等待中",
      message: "",
      speed_bytes_per_second: null,
      payload: {},
      result: null,
      error: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    render(
      <GenerateView
        projectPath="E:\\test.woosh"
        project={project}
        models={[dflow]}
        activeModel="Woosh-DFlow"
        onModelChange={vi.fn()}
        onProjectChange={vi.fn()}
        onQueued={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("音效名称"), {
      target: { value: "玩家激光枪" },
    });
    fireEvent.click(screen.getByRole("button", { name: /生成 4 个变体/ }));

    await waitFor(() => expect(generate).toHaveBeenCalled());
    expect(generate).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "SFX",
        name: "玩家激光枪",
        postprocess_mode: "trim_silence",
      }),
    );
    generate.mockRestore();
  });

  it("disables generation when the SFX name is empty", () => {
    render(
      <GenerateView
        projectPath="E:\\test.woosh"
        project={project}
        models={[dflow]}
        activeModel="Woosh-DFlow"
        onModelChange={vi.fn()}
        onProjectChange={vi.fn()}
        onQueued={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("音效名称"), {
      target: { value: "   " },
    });

    expect(screen.getByRole("button", { name: /生成 4 个变体/ })).toBeDisabled();
  });

  it("creates a manual non-destructive trim version", async () => {
    const sourceAsset = {
      id: "asset-1",
      name: "impact",
      relative_path: "Generated/impact.wav",
      source: "generated" as const,
      kind: "sfx" as const,
      prompt_original: "impact",
      prompt_conditioned: "impact",
      model_id: "Woosh-DFlow",
      seed: 42,
      sample_rate: 48000,
      channel_count: 1,
      duration_seconds: 5,
      generation_group_id: null,
      parent_asset_id: null,
      stem_role: null,
      music_metadata: null,
      favorite: false,
      tags: [],
      created_at: "2026-01-01T00:00:00Z",
    };
    const derivedAsset = {
      ...sourceAsset,
      id: "asset-2",
      name: "impact_裁剪",
      relative_path: "Generated/Processed/impact_裁剪.wav",
      source: "rendered" as const,
      kind: "render" as const,
      duration_seconds: 2,
      parent_asset_id: sourceAsset.id,
    };
    const trimmedProject = { ...project, assets: [sourceAsset, derivedAsset] };
    const trimAsset = vi.spyOn(api, "trimAsset").mockResolvedValue({
      manifest: trimmedProject,
      asset: derivedAsset,
      details: {
        mode: "manual",
        start_seconds: 1,
        end_seconds: 3,
        removed_seconds: 3,
      },
    });
    const onProjectChange = vi.fn();
    render(
      <GenerateView
        projectPath="E:\\test.woosh"
        project={{ ...project, assets: [sourceAsset] }}
        models={[dflow]}
        activeModel="Woosh-DFlow"
        onModelChange={vi.fn()}
        onProjectChange={onProjectChange}
        onQueued={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "手动范围" }));
    fireEvent.change(screen.getByLabelText("裁剪起点"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("裁剪终点"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /创建裁剪版本/ }));

    await waitFor(() =>
      expect(trimAsset).toHaveBeenCalledWith(
        sourceAsset.id,
        expect.objectContaining({
          mode: "manual",
          start_seconds: 1,
          end_seconds: 3,
        }),
      ),
    );
    expect(onProjectChange).toHaveBeenCalledWith(trimmedProject);
    trimAsset.mockRestore();
  });

  it("offers automatic trimming from an asset context menu", async () => {
    const sourceAsset = {
      id: "asset-context",
      name: "context impact",
      relative_path: "Generated/context-impact.wav",
      source: "generated" as const,
      kind: "sfx" as const,
      prompt_original: "impact",
      prompt_conditioned: "impact",
      model_id: "Woosh-DFlow",
      seed: 7,
      sample_rate: 48000,
      channel_count: 1,
      duration_seconds: 5,
      generation_group_id: null,
      parent_asset_id: null,
      stem_role: null,
      music_metadata: null,
      favorite: false,
      tags: [],
      created_at: "2026-01-01T00:00:00Z",
    };
    const derivedAsset = {
      ...sourceAsset,
      id: "asset-context-trimmed",
      name: "context impact_裁剪",
      source: "rendered" as const,
      kind: "render" as const,
      parent_asset_id: sourceAsset.id,
    };
    const trimAsset = vi.spyOn(api, "trimAsset").mockResolvedValue({
      manifest: { ...project, assets: [sourceAsset, derivedAsset] },
      asset: derivedAsset,
      details: {
        mode: "trim_silence",
        start_seconds: 0.4,
        end_seconds: 4.6,
        removed_seconds: 0.8,
      },
    });

    render(
      <GenerateView
        projectPath="E:\\test.woosh"
        project={{ ...project, assets: [sourceAsset] }}
        models={[dflow]}
        activeModel="Woosh-DFlow"
        onModelChange={vi.fn()}
        onProjectChange={vi.fn()}
        onQueued={vi.fn()}
        onError={vi.fn()}
      />,
    );

    fireEvent.contextMenu(screen.getByRole("article", { name: "context impact 音效卡片" }), {
      clientX: 120,
      clientY: 160,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "自动去首尾空白" }));

    await waitFor(() =>
      expect(trimAsset).toHaveBeenCalledWith(
        sourceAsset.id,
        expect.objectContaining({ mode: "trim_silence" }),
      ),
    );
    trimAsset.mockRestore();
  });
});
