import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const backend="http://127.0.0.1:8767/api/v1";
const artifacts=path.resolve("../.artifacts/localization-e2e");

test("records a microphone reference, transcribes it, generates three locales and exports matching game assets", async ({page,request}) => {
  await fs.mkdir(artifacts,{recursive:true});
  const created = await (await request.post(backend+"/projects",{data:{parent_directory:artifacts,name:"多语言录音验收-"+Date.now()}})).json();
  const manifest=created.manifest;
  manifest.script={title:"星港守卫",source_locale:"zh-CN",target_locales:["zh-CN","en","ja"],voices:[{id:"guard",name:"守卫",mode:"clone",language:"Chinese",speaker:"Vivian",instruct:"",reference_audio:null,reference_text:""}],lines:[{id:"greeting",key:"chapter01.guard.greeting",character:"守卫",voice_id:"guard",text:"欢迎来到星港。",source_language:"Chinese",language:"Chinese",instruct:"",enabled:true,asset_id:null}]};
  expect((await request.put(backend+"/projects",{data:{project_path:created.path,manifest}})).ok()).toBeTruthy();
  await page.goto("/");
  await page.getByRole("button",{name:manifest.name,exact:true}).click();
  await page.getByRole("button",{name:"剧本配音",exact:true}).click();
  await expect(page.getByRole("button",{name:"麦克风录制",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"麦克风录制",exact:true}).click();
  await expect(page.getByRole("button",{name:"停止录音",exact:true})).toBeVisible();
  await expect(page.getByText("录音中 2s / 120s",{exact:true})).toBeVisible({timeout:10000});
  await page.getByRole("button",{name:"停止录音",exact:true}).click();
  await expect(page.getByLabel("麦克风录音试听")).toBeVisible();
  await page.screenshot({path:path.join(artifacts,"01-microphone-preview.png")});
  await page.getByRole("button",{name:"保存为参考音频",exact:true}).click();
  await expect(page.getByLabel("参考音频中的准确台词")).toHaveValue("这是一段测试录音。",{timeout:30000});
  await expect(page.getByText("识别台词已填入，请试听并核对准确性",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"生成 1 句 × 3 语言配音",exact:true}).click();
  await expect.poll(async()=> {
    const current=await (await request.post(backend+"/projects/open",{data:{path:created.path}})).json();
    return current.assets.filter((asset:{kind:string})=>asset.kind==="voice_line").length;
  },{timeout:30000}).toBe(3);
  await expect(page.getByLabel("第 1 句 中文 配音试听")).toBeVisible({timeout:10000});
  await page.getByRole("tab",{name:/日语/}).click();
  await expect(page.getByLabel("第 1 句 日语 配音试听")).toBeVisible();
  await page.getByLabel("第 1 句 日语 文本").fill("スターポートへようこそ。");
  await page.getByRole("button",{name:"生成日语配音",exact:true}).click();
  await expect.poll(async()=> {
    const current=await (await request.post(backend+"/projects/open",{data:{path:created.path}})).json();
    return current.assets.filter((asset:{kind:string})=>asset.kind==="voice_line").length;
  },{timeout:30000}).toBe(4);
  await expect(page.getByLabel("第 1 句 日语 配音试听")).toBeVisible();
  await page.screenshot({path:path.join(artifacts,"02-localized-dialogue.png")});
  await page.getByRole("button",{name:"导出",exact:true}).click();
  await page.getByRole("button",{name:/游戏多语言包/}).click();
  await page.getByRole("button",{name:"开始导出",exact:true}).click();
  await expect.poll(async()=> (await (await request.get(backend+"/jobs")).json()).find((job:{kind:string})=>job.kind==="export")?.status,{timeout:15000}).toBe("completed");
  const jobs=await (await request.get(backend+"/jobs")).json();
  const directory=jobs.find((job:{kind:string})=>job.kind==="export").result.directory;
  const output=JSON.parse(await fs.readFile(path.join(directory,"manifest.json"),"utf8"));
  expect(output.lines).toHaveLength(3);
  for(const line of output.lines) expect((await fs.stat(path.join(directory,line.audio_path))).size).toBeGreaterThan(44);
  await page.getByRole("button",{name:"模型",exact:true}).click();
  await expect(page.getByText("模型运行状态",{exact:true})).toBeVisible();
  await page.screenshot({path:path.join(artifacts,"03-runtime-state.png")});
  await page.getByRole("button",{name:"释放模型",exact:true}).click();
  await expect(page.getByText(/当前没有常驻模型/)).toBeVisible();
});


test("leaving the script workspace releases the microphone", async ({page,request}) => {
  await page.addInitScript(()=>{
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    (window as unknown as {capturedStreams:MediaStream[]}).capturedStreams=[];
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream=await original(constraints);
      (window as unknown as {capturedStreams:MediaStream[]}).capturedStreams.push(stream);
      return stream;
    };
  });
  const created=await (await request.post(backend+"/projects",{data:{parent_directory:artifacts,name:"录音释放验收-"+Date.now()}})).json();
  const manifest=created.manifest;
  manifest.script.voices=[{id:"v",name:"测试角色",mode:"clone",reference_audio:null,reference_text:""}];
  await request.put(backend+"/projects",{data:{project_path:created.path,manifest}});
  await page.goto("/");
  await page.getByRole("button",{name:manifest.name,exact:true}).click();
  await page.getByRole("button",{name:"剧本配音",exact:true}).click();
  await page.getByRole("button",{name:"麦克风录制",exact:true}).click();
  await expect(page.getByRole("button",{name:"停止录音",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"生成音效",exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>{
    const streams=(window as unknown as {capturedStreams:MediaStream[]}).capturedStreams;
    return streams.length>0 && streams.every(stream=>stream.getTracks().every(track=>track.readyState==="ended"));
  })).toBeTruthy();
});
