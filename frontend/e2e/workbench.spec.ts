import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const backend = "http://127.0.0.1:8765/api/v1";
const artifacts = path.resolve("../.artifacts/workbench-ui");

test("imports an AI script, copies templates, binds folder audio and exports the portable skill", async ({ page, request, context }) => {
  await fs.mkdir(artifacts, { recursive: true });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const createdResponse = await request.post(`${backend}/projects`, { data: { parent_directory: artifacts, name: `体验验收-${Date.now()}` } });
  expect(createdResponse.ok()).toBeTruthy();
  const created = await createdResponse.json();
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/");
  await page.getByRole("button", { name: created.manifest.name, exact: true }).click();
  await page.getByRole("button", { name: "剧本配音", exact: true }).click();
  await expect(page.getByRole("heading", { name: "剧本工作台", exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(artifacts, "01-empty.png") });
  await page.getByRole("button", { name: "剧本提示词", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('"type": "woosh.script"');

  const catalog = await (await request.get(`${backend}/agent/templates`)).json();
  const template = catalog.find((item: { id: string }) => item.id === "script").template;
  await page.getByRole("button", { name: "粘贴 JSON", exact: true }).click();
  await page.getByLabel("导入 JSON 内容").fill("{bad json}");
  await page.getByRole("button", { name: "检查并预览", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("JSON 格式错误");
  await expect(page.getByRole("button", { name: "确认导入" })).toBeDisabled();
  await page.getByLabel("导入 JSON 内容").fill(template);
  await page.getByRole("button", { name: "检查并预览", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeEnabled();
  await page.screenshot({ path: path.join(artifacts, "02-import-preview.png") });
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByLabel("第 1 句台词")).toHaveValue("雨停之前，他终于等到了那封信。");
  await expect.poll(async () => (await (await request.post(`${backend}/projects/open`, { data: { path: created.path } })).json()).script.lines.length).toBe(3);
  await page.screenshot({ path: path.join(artifacts, "03-script.png") });

  // A real browser folder upload preserves nested references and previews the imported role file.
  const folder = path.join(artifacts, "角色素材");
  await fs.mkdir(path.join(folder, "voices"), { recursive: true });
  const wave = Buffer.alloc(44 + 16000);
  wave.write("RIFF", 0); wave.writeUInt32LE(wave.length - 8, 4); wave.write("WAVEfmt ", 8); wave.writeUInt32LE(16, 16); wave.writeUInt16LE(1, 20); wave.writeUInt16LE(1, 22); wave.writeUInt32LE(16000, 24); wave.writeUInt32LE(32000, 28); wave.writeUInt16LE(2, 32); wave.writeUInt16LE(16, 34); wave.write("data", 36); wave.writeUInt32LE(16000, 40);
  await fs.writeFile(path.join(folder, "voices", "narrator.wav"), wave);
  const role = JSON.parse(template).voices[0];
  await fs.writeFile(path.join(folder, "voices.json"), JSON.stringify({ type: "woosh.voices", version: 1, voices: [{ ...role, mode: "clone", reference_audio: "voices/narrator.wav", reference_text: "欢迎来到我们的故事。" }] }));
  await page.getByLabel("选择导入文件夹").setInputFiles(folder);
  await expect(page.getByRole("dialog", { name: "导入剧本 / 角色" })).toBeVisible();
  await page.getByRole("button", { name: "检查并预览", exact: true }).click();
  await expect(page.getByRole("button", { name: "确认导入" })).toBeEnabled();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByLabel("从项目选择参考音频")).toHaveValue(/Sources\/Imports\/.+\/角色素材\/voices\/narrator.wav/);
  await page.getByTitle("复制参考音频路径", { exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain("narrator.wav");
  await page.screenshot({ path: path.join(artifacts, "04-reference.png") });

  await page.getByRole("button", { name: "生成音效", exact: true }).click();
  await page.getByRole("button", { name: "剧本配音", exact: true }).click();
  await expect(page.getByLabel("第 1 句台词")).toHaveValue("雨停之前，他终于等到了那封信。");
  await page.evaluate((contents: string) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([contents], "dropped-script.json", { type: "application/json" }));
    document.querySelector(".speech-view")!.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
  }, template);
  await expect(page.getByRole("dialog", { name: "导入剧本 / 角色" })).toBeVisible();
  await expect(page.getByLabel("导入 JSON 内容")).toHaveValue(template);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "模板中心", exact: true }).click();
  await page.getByRole("button", { name: "角色与音色", exact: true }).click();
  await page.getByRole("button", { name: "输出模板", exact: true }).click();
  await expect(page.getByLabel("AI 输出模板")).toHaveValue(/woosh.voices/);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 Skill 包", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("woosh-studio-skill.zip");
  await download.saveAs(path.join(artifacts, "woosh-studio-skill.zip"));
  await page.screenshot({ path: path.join(artifacts, "05-templates.png") });
  await page.getByRole("button", { name: "关闭弹窗" }).click();
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.screenshot({ path: path.join(artifacts, "06-narrow.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(artifacts, "07-dark.png") });
});
