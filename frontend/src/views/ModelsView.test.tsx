import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { JobEvent, ModelDescriptor } from "../types";
import { ModelsView } from "./ModelsView";

const musicModel: ModelDescriptor = {
  id: "HeartMuLa-3B",
  name: "HeartMuLa 3B",
  family: "music",
  description: "Music model",
  release: "2026-02-13",
  license: "Apache 2.0",
  license_url: "",
  installed: false,
  custom: false,
  path: null,
  dependencies: [],
  controls: [],
  supported: true,
  engine: "heartmula",
  model_source: "modelscope",
  memory_mode: "auto_low_vram",
};

const downloadJob: JobEvent = {
  id: "download-1",
  kind: "model_download",
  status: "running",
  progress: 0.25,
  stage: "下载 HeartMuLa",
  message: "",
  speed_bytes_per_second: 1024,
  payload: { model_id: musicModel.id, paused: false },
  result: null,
  error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ModelsView", () => {
  it("pauses an active model download", async () => {
    const pause = vi.spyOn(api, "pauseJob").mockResolvedValue({
      ...downloadJob,
      payload: { ...downloadJob.payload, paused: true },
      stage: "已暂停",
    });
    const refresh = vi.fn();
    render(<ModelsView models={[musicModel]} jobs={[downloadJob]} modelRoot="E:\\AIModels\\WooshStudio" onRefresh={refresh} onError={vi.fn()} />);

    fireEvent.click(screen.getByTitle("暂停下载"));

    await waitFor(() => expect(pause).toHaveBeenCalledWith(downloadJob.id));
    expect(refresh).toHaveBeenCalled();
    pause.mockRestore();
  });
  it("presents bundled translation as ready with no manual download or removal action", () => {
    const builtin: ModelDescriptor = { ...musicModel, id: "m2m100-418M-int8", family: "translation", name: "多语种对白翻译", installed: true, bundled: true, path: "E:/models/m2m100-418M-int8", engine: "ctranslate2", model_source: "local", dependencies: [] };
    render(<ModelsView models={[builtin]} jobs={[]} modelRoot="E:/models" onRefresh={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByText("内置 · 就绪")).toBeInTheDocument();
    expect(screen.getByText("随应用安装 · 无需下载")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("移除模型")).not.toBeInTheDocument();
  });

});
