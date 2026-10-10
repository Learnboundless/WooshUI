import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ModelDescriptor, ProjectManifest } from "../types";
import { SpeechView } from "./SpeechView";
import { blankVoice } from "../workbench";

const nativeDrop = vi.hoisted(() => ({ handler: null as ((event: { payload: { type: string; paths: string[]; position: { x: number; y: number } } }) => void) | null, off: vi.fn() }));
vi.mock("@tauri-apps/api/webviewWindow", () => ({ getCurrentWebviewWindow: () => ({ onDragDropEvent: async (handler: typeof nativeDrop.handler) => { nativeDrop.handler = handler; return nativeDrop.off; } }) }));

const project: ProjectManifest = {
  schema_version: 2, id: "project", name: "场景", description: "", sample_rate: 48000, created_at: "", updated_at: "", assets: [],
  timeline: { sample_rate: 48000, duration_seconds: 8, loop_start_seconds: null, loop_end_seconds: null, tracks: [], master_effects: [] },
  export_preset: { format: "wav24", package: "files", naming_template: "{name}", category: "Voice" },
  script: { title: "剧本", voices: [{ ...blankVoice("罗伦斯"), id: "hero" }], lines: [{ id: "line-1", character: "罗伦斯", voice_id: "hero", text: "我们出发吧。", enabled: true, language: "Chinese", instruct: "", asset_id: null }] },
};
const model = { id: "Qwen3-TTS-CustomVoice-1.7B", family: "speech", installed: true } as ModelDescriptor;
const props = { projectPath: "E:/test.woosh", project, models: [model], onProjectChange: vi.fn(), onQueued: vi.fn(), onError: vi.fn() };

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(api, "saveScript").mockImplementation(async (_path, script) => ({ ...project, script }));
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
afterEach(async () => { cleanup(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; nativeDrop.handler = null; await act(async () => { await Promise.resolve(); }); vi.restoreAllMocks(); });

describe("SpeechView", () => {
  it("stops generation when saving the edited script fails", async () => {
    vi.spyOn(api, "saveScript").mockRejectedValue(new Error("磁盘写入失败"));
    const generate = vi.spyOn(api, "generateSpeech");
    render(<SpeechView {...props} />);
    fireEvent.change(screen.getByLabelText("第 1 句台词"), { target: { value: "更改后的台词" } });
    fireEvent.click(screen.getByRole("button", { name: "生成 1 句配音" }));
    await waitFor(() => expect(props.onError).toHaveBeenCalledWith("磁盘写入失败"));
    expect(generate).not.toHaveBeenCalled();
  });
  it("copies the role prompt with current role data for another model", async () => {
    vi.spyOn(api, "agentTemplates").mockResolvedValue([{ id: "voices", title: "角色", description: "", prompt: "角色提示词", template: "{}" }]);
    render(<SpeechView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "角色提示词" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('"id": "hero"')));
    expect(screen.getByRole("status")).toHaveTextContent("已复制角色提示词");
  });
  it("unbinds deleted roles and allows undo without losing dialogue", async () => {
    render(<SpeechView {...props} />);
    fireEvent.click(screen.getByTitle("删除选中角色"));
    expect((screen.getByLabelText("第 1 句角色") as HTMLSelectElement).value).toBe("");
    expect(screen.getByLabelText("第 1 句台词")).toHaveValue("我们出发吧。");
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(screen.getByLabelText("第 1 句角色")).toHaveValue("hero");
  });
  it("previews JSON before applying and persists the imported script", async () => {
    vi.spyOn(api, "previewScript").mockResolvedValue({ kind: "woosh.script", warnings: [], script: { ...project.script!, title: "导入故事" } });
    render(<SpeechView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "粘贴 JSON" }));
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("导入 JSON 内容"), { target: { value: '{"title":"导入故事"}' } });
    fireEvent.click(screen.getByRole("button", { name: "检查并预览" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled());
    expect(screen.getByLabelText("剧本标题")).toHaveValue("剧本");
    fireEvent.click(screen.getByLabelText("替换当前剧本"));
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
    expect(screen.getByLabelText("剧本标题")).toHaveValue("导入故事");
    fireEvent.click(screen.getByTitle("保存剧本 · Ctrl+S"));
    await waitFor(() => expect(api.saveScript).toHaveBeenCalledWith("E:/test.woosh", expect.objectContaining({ title: "导入故事" })));
  });
  it("refreshes completed line audio without losing an unsaved text edit", async () => {
    const { rerender } = render(<SpeechView {...props} />);
    fireEvent.change(screen.getByLabelText("第 1 句台词"), { target: { value: "用户正在编辑" } });
    const updated = { ...project, script: { ...project.script!, lines: [{ ...project.script!.lines[0], asset_id: "finished" }] } };
    rerender(<SpeechView {...props} project={updated} />);
    expect(screen.getByLabelText("第 1 句台词")).toHaveValue("用户正在编辑");
    fireEvent.click(screen.getByTitle("保存剧本 · Ctrl+S"));
    await waitFor(() => expect(api.saveScript).toHaveBeenCalledWith("E:/test.woosh", expect.objectContaining({ lines: [expect.objectContaining({ text: "用户正在编辑", asset_id: null })] })));
  });
  it("accepts native desktop file and folder drops and removes the listener on unmount", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
    Object.defineProperty(document, "elementFromPoint", { configurable: true, value: () => null });
    const importing = vi.spyOn(api, "importResources").mockResolvedValue({ manifest: project, assets: [], documents: [], mappings: [], warnings: [] });
    const { unmount } = render(<SpeechView {...props} />);
    await waitFor(() => expect(nativeDrop.handler).not.toBeNull());
    act(() => nativeDrop.handler!({ payload: { type: "drop", paths: ["E:/角色资料", "E:/台词.json"], position: { x: 30, y: 50 } } }));
    await waitFor(() => expect(importing).toHaveBeenCalledWith("E:/test.woosh", ["E:/角色资料", "E:/台词.json"]));
    await waitFor(() => expect(props.onProjectChange).toHaveBeenCalled());
    unmount();
    expect(nativeDrop.off).toHaveBeenCalled();
  });

  it("translates bound dialogue when the character language changes and keeps the original", async () => {
    const translate = vi.spyOn(api, "translate").mockResolvedValue({ original: "我们出发吧。", translated: "Let's go.", translation: { source_text: "我们出发吧。", source_language: "Chinese", target_language: "English", text: "Let's go.", model_id: "opus-mt-zh-en" } });
    render(<SpeechView {...props} />);
    fireEvent.change(screen.getByLabelText("角色语言（同步台词并自动翻译）"), { target: { value: "English" } });
    expect(screen.getByLabelText("第 1 句语言")).toHaveValue("English");
    await waitFor(() => expect(translate).toHaveBeenCalledWith("我们出发吧。", "Auto", "English"), { timeout: 2000 });
    await waitFor(() => expect(screen.getByLabelText("第 1 句译文")).toHaveValue("Let's go."));
    expect(screen.getByLabelText("第 1 句台词")).toHaveValue("我们出发吧。");
  });

  it("shows completed speech inline and retains the prior audition after editing dialogue", async () => {
    const voiceProject = { ...project, assets: [{ id: "audio", name: "主角配音", kind: "voice_line", relative_path: "Generated/Voice/line.wav", duration_seconds: 2, music_metadata: { script_line_id: "line-1" }, source: "generated", sample_rate: 24000, channel_count: 1, model_id: null, seed: null, prompt_original: null, prompt_conditioned: null, generation_group_id: null, parent_asset_id: null, stem_role: null, favorite: false, tags: [], created_at: "" } as ProjectManifest["assets"][number]], script: { ...project.script!, lines: [{ ...project.script!.lines[0], asset_id: "audio" }] } };
    render(<SpeechView {...props} project={voiceProject} />);
    expect(screen.getByLabelText("第 1 句配音试听")).toHaveAttribute("src", expect.stringContaining("line.wav"));
    fireEvent.change(screen.getByLabelText("第 1 句台词"), { target: { value: "修改的对白" } });
    expect(screen.getByText("上次配音 · 内容已修改")).toBeInTheDocument();
    expect(screen.getByLabelText("第 1 句配音试听")).toBeInTheDocument();
  });

  it("submits all selected languages and can generate only one localized line", async () => {
    const generate=vi.spyOn(api,"generateSpeech").mockResolvedValue({id:"multi"} as never);
    const multi={...project,script:{...project.script!,source_locale:"zh-CN",target_locales:["zh-CN","en","ja"]}};
    render(<SpeechView {...props} project={multi}/>);
    fireEvent.click(screen.getByRole("button",{name:"生成 1 句 × 3 语言配音"}));
    await waitFor(()=>expect(generate).toHaveBeenCalledWith(expect.objectContaining({target_locales:["zh-CN","en","ja"]})));
    fireEvent.click(screen.getByRole("tab",{name:/日语/}));
    fireEvent.change(screen.getByLabelText("第 1 句 日语 文本"),{target:{value:"出発しよう。"}});
    fireEvent.click(screen.getByRole("button",{name:"生成日语配音"}));
    await waitFor(()=>expect(generate).toHaveBeenLastCalledWith(expect.objectContaining({line_ids:["line-1"],target_locales:["ja"]})));
    expect(screen.getByLabelText("第 1 句台词")).toHaveValue("我们出发吧。");
  });

});
