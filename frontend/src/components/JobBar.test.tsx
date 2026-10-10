import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { JobEvent } from "../types";
import { JobBar } from "./JobBar";

describe("JobBar failures", () => {
  it("exposes the actual failure reason and stage from a persisted task", () => {
    const job: JobEvent = { id: "failed-music", kind: "music_generation", status: "failed", stage: "失败", progress: 0.735, message: "", speed_bytes_per_second: null, payload: { project_path: "E:/测试.woosh" }, result: null, error: { code: "INVALID_REQUEST", message: "Error opening mix.wav: System error", detail: "失败阶段：解码完成\nFileNotFoundError" }, created_at: "2026-09-11T10:22:08Z", updated_at: "2026-09-11T10:22:08Z" };
    render(<JobBar jobs={[job]} onCancel={vi.fn()} />);
    expect(screen.getByText(job.error!.message)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle(job.error!.message));
    expect(screen.getByRole("dialog", { name: "任务详情与历史" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("System error");
    fireEvent.click(screen.getByText("失败阶段与原始错误"));
    expect(screen.getByText(/失败阶段：解码完成/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制诊断信息" })).toBeEnabled();
  });
});
