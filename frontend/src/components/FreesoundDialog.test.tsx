import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { FreesoundDialog } from "./FreesoundDialog";

const sound = { id: 123, name: "Soft Whisper", description: "A close voice", tags: ["voice", "whisper"], username: "actor", license: "Creative Commons 0", duration: 2.5, preview_url: "https://cdn.freesound.org/previews/1/123.mp3", download_url: "https://freesound.org/apiv2/sounds/123/download/", sound_url: "https://freesound.org/s/123/", filesize: 10, samplerate: 48000, channels: 1 };

describe("FreesoundDialog", () => {
  it("searches, previews metadata and imports a selected sound into the project", async () => {
    vi.spyOn(api, "freesoundStatus").mockResolvedValue({ configured: true, website: "https://freesound.org" });
    vi.spyOn(api, "freesoundSearch").mockResolvedValue({ count: 1, page: 1, page_size: 20, results: [sound], next: false, previous: false });
    const imported = vi.spyOn(api, "freesoundImport").mockResolvedValue({ manifest: { id: "project" } as never, asset: { relative_path: "Sources/Freesound/123_Soft Whisper.mp3" } as never });
    const onImported = vi.fn();
    render(<FreesoundDialog projectPath="E:/project.woosh" onClose={vi.fn()} onImported={onImported} onError={vi.fn()} />);
    await waitFor(() => expect(api.freesoundStatus).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("搜索 Freesound"), { target: { value: "whisper" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => expect(screen.getAllByText("Soft Whisper").length).toBeGreaterThan(0));
    expect(screen.getByText("Creative Commons 0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "导入到当前项目" }));
    await waitFor(() => expect(imported).toHaveBeenCalledWith(expect.objectContaining({ project_path: "E:/project.woosh", sound_id: 123, username: "actor", preview_url: sound.preview_url })));
    expect(onImported).toHaveBeenCalledWith(expect.anything(), "Sources/Freesound/123_Soft Whisper.mp3");
  });

  it("keeps a website fallback when no API key is configured", async () => {
    vi.spyOn(api, "freesoundStatus").mockResolvedValue({ configured: false, website: "https://freesound.org" });
    render(<FreesoundDialog projectPath="E:/project.woosh" onClose={vi.fn()} onImported={vi.fn()} onError={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/尚未配置 Freesound API key/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("搜索 Freesound"), { target: { value: "voice" } });
    expect(screen.getByRole("button", { name: "搜索" })).toBeEnabled();
  });
});
