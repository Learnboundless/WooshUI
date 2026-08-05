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
});
