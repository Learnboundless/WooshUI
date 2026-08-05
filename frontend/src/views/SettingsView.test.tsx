import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsView } from "./SettingsView";

const capabilities = {
  platform: "Windows-11",
  python_version: "3.12.11",
  cuda_available: true,
  cuda_device_name: "NVIDIA GeForce RTX 4060 Ti",
  cuda_memory_bytes: 8_000_000_000,
  effective_device: "cuda" as const,
  disk_free_bytes: 100_000_000_000,
  model_root: "E:\\AIModels\\WooshStudio",
  settings: {
    device: "auto" as const,
    active_model: "Woosh-DFlow",
    active_music_model: "HeartMuLa-3B",
    model_root: null,
    model_download_source: "auto" as const,
    music_memory_mode: "auto" as const,
    language: "zh-CN" as const,
    theme: "system" as const,
  },
};

describe("SettingsView", () => {
  it("changes the runtime device", () => {
    const onChange = vi.fn();
    render(<SettingsView capabilities={capabilities} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /CPU/ }));
    expect(onChange).toHaveBeenCalledWith({ ...capabilities.settings, device: "cpu" });
  });

  it("disables CUDA when unavailable", () => {
    render(
      <SettingsView
        capabilities={{ ...capabilities, cuda_available: false, cuda_device_name: null, effective_device: "cpu" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "CUDA 不可用" })).toBeDisabled();
  });
});
