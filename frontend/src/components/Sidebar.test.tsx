import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectManifest } from "../types";
import { Sidebar } from "./Sidebar";

const project: ProjectManifest = {
  schema_version: 2,
  id: "project-1",
  name: "测试项目",
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

function renderSidebar(overrides: Partial<ComponentProps<typeof Sidebar>> = {}) {
  const props: ComponentProps<typeof Sidebar> = {
    activeView: "generate",
    project,
    projectPath: "E:\\Audio\\测试项目.woosh",
    recent: [
      { path: "E:\\Audio\\测试项目.woosh", name: "测试项目" },
      { path: "E:\\Audio\\旧项目.woosh", name: "旧项目" },
    ],
    onView: vi.fn(),
    onOpenProject: vi.fn(),
    onNewProject: vi.fn(),
    onCloseProject: vi.fn(),
    onRemoveRecent: vi.fn(),
    onRevealProject: vi.fn(),
    onError: vi.fn(),
    ...overrides,
  };
  render(<Sidebar {...props} />);
  return props;
}

describe("Sidebar project context menus", () => {
  it("offers project operations for the current project", () => {
    const props = renderSidebar();
    fireEvent.contextMenu(screen.getByRole("button", { name: "测试项目 0 个素材" }), {
      clientX: 120,
      clientY: 520,
    });

    expect(screen.getByRole("menuitem", { name: "在资源管理器中显示" })).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: "关闭当前项目" }));
    expect(props.onCloseProject).toHaveBeenCalledOnce();
  });

  it("removes only the selected recent-project record", () => {
    const props = renderSidebar();
    fireEvent.contextMenu(screen.getByRole("button", { name: "旧项目" }), {
      clientX: 110,
      clientY: 620,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "从最近列表移除" }));

    expect(props.onRemoveRecent).toHaveBeenCalledWith("E:\\Audio\\旧项目.woosh");
  });
});
