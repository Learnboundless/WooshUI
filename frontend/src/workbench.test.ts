import { describe, expect, it } from "vitest";
import type { ScriptDocument, ScriptPreview } from "./types";
import { bindImportedReferences, blankVoice, mergeScript } from "./workbench";

function fixture(): ScriptDocument {
  return { title: "旧剧本", voices: [{ ...blankVoice("罗伦斯"), id: "hero" }], lines: [{ id: "line-1", character: "罗伦斯", voice_id: "hero", text: "出发。", enabled: true, language: "Chinese", instruct: "", asset_id: "old-audio" }] };
}

describe("script import", () => {
  it("remaps colliding IDs when appending while preserving the original script", () => {
    const current = fixture();
    const incoming: ScriptPreview = { kind: "woosh.script", script: fixture(), warnings: [] };
    const next = mergeScript(current, incoming, false);
    expect(next.voices).toHaveLength(2);
    expect(next.voices[1].id).not.toBe("hero");
    expect(next.voices[1].name).toBe("罗伦斯 2");
    expect(next.lines[1].voice_id).toBe(next.voices[1].id);
    expect(next.lines[1].character).toBe("罗伦斯 2");
    expect(next.lines[1].id).not.toBe("line-1");
    expect(next.lines[1].asset_id).toBeNull();
    expect(current.lines[0].asset_id).toBe("old-audio");
  });
  it("updates imported roles by name without orphaning existing lines", () => {
    const current = fixture();
    const incoming: ScriptPreview = { kind: "woosh.voices", script: { title: "", voices: [{ ...blankVoice("罗伦斯"), id: "new-ai-id", instruct: "坚定" }], lines: [] }, warnings: [] };
    const next = mergeScript(current, incoming, false);
    expect(next.voices).toHaveLength(1);
    expect(next.voices[0].id).toBe("hero");
    expect(next.lines[0].voice_id).toBe("hero");
    expect(next.lines[0].asset_id).toBeNull();
  });
  it("resolves a reference next to a dropped script before matching basenames", () => {
    const preview: ScriptPreview = { kind: "woosh.script", script: fixture(), warnings: [] };
    preview.script.voices[0].reference_audio = "voices/hero.wav";
    const mappings = [
      { source: "scene/script.json", original_path: "C:/scene/script.json", relative_path: "Sources/batch/scene/script.json" },
      { source: "scene/voices/hero.wav", original_path: "C:/scene/voices/hero.wav", relative_path: "Sources/batch/scene/voices/hero.wav" },
      { source: "other/hero.wav", original_path: "C:/other/hero.wav", relative_path: "Sources/batch/other/hero.wav" },
    ];
    const next = bindImportedReferences(preview, mappings, mappings[0].relative_path);
    expect(next.script.voices[0].reference_audio).toBe(mappings[1].relative_path);
    expect(preview.script.voices[0].reference_audio).toBe("voices/hero.wav");
  });
});
