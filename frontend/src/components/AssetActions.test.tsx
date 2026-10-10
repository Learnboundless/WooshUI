import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { AssetActions } from "./AssetActions";
import type { GeneratedAsset, ProjectManifest } from "../types";

describe("AssetActions", () => {
  it("removes a missing record only after showing which project bindings will be removed", async () => {
    const asset = { id: "missing", name: "缺失对白", relative_path: "Generated/missing.wav" } as GeneratedAsset;
    const updated = { assets: [] } as unknown as ProjectManifest;
    const remove = vi.spyOn(api, "removeAssets").mockResolvedValue(updated);
    const changed = vi.fn();
    render(<AssetActions asset={asset} projectPath="E:/test.woosh" missing onProjectChange={changed} onError={vi.fn()} />);
    fireEvent.click(screen.getByTitle("删除素材 缺失对白"));
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByText(/磁盘上的音频文件保留/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认移除" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("E:/test.woosh", ["missing"]));
    expect(changed).toHaveBeenCalledWith(updated);
  });
});
