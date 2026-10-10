import {test,expect} from "@playwright/test";
import path from "node:path";
import fs from "node:fs/promises";
const backend="http://127.0.0.1:8767/api/v1";
const artifacts=path.resolve("../.artifacts/quality-audit/ui");

test("SFX batches contain variants and real analysis, without leaking voice and reference assets",async({page,request})=>{
 await fs.mkdir(artifacts,{recursive:true});
 const created=await(await request.post(backend+"/projects",{data:{parent_directory:artifacts,name:"音效批次验收-"+Date.now()}})).json();
 const manifest=created.manifest;
 manifest.assets=[{id:"speech",name:"不能出现在音效列表的配音",kind:"voice_line",relative_path:"Voice/missing.wav"},{id:"ref",name:"不能出现在音效列表的参考录音",kind:"imported",relative_path:"Sources/missing.wav"}];
 expect((await request.put(backend+"/projects",{data:{project_path:created.path,manifest}})).ok()).toBeTruthy();
 await page.goto("/");await page.getByRole("button",{name:manifest.name,exact:true}).click();
 await page.getByLabel("中文提示词").fill("火焰喷射，短促有力");
 await page.getByLabel("英文模型提示词").fill("a short flamethrower burst");
 await expect(page.getByLabel("音效名称")).toHaveValue("火焰喷射");
 const count=page.getByRole("slider",{name:"音效变体数量",exact:true});await count.focus();await count.press("Home");await count.press("ArrowRight");await count.press("ArrowRight");
 await page.getByRole("button",{name:"生成 3 个变体",exact:true}).click();
 const card=page.getByRole("article",{name:"火焰喷射 音效卡片",exact:true});
 await expect(card).toHaveCount(1);await expect(card.getByRole("option")).toHaveCount(3);
 await expect(card.getByRole("img",{name:"火焰喷射 的真实波形"})).toBeVisible();
 await expect(page.getByText(/个音效文件缺失/)).toHaveCount(0);
 await expect(page.getByRole("heading",{name:/不能出现在音效列表/})).toHaveCount(0);
 await card.getByRole("button",{name:"频谱图",exact:true}).click();
 await expect(card.getByRole("img",{name:"火焰喷射 的真实频谱图"})).toBeVisible();
 await expect.poll(()=>card.locator('canvas').evaluate(canvas=>{
   const ctx=canvas.getContext('2d')!;const data=ctx.getImageData(0,0,canvas.width,canvas.height).data;const colors=new Set<number>();for(let i=0;i<data.length;i+=4)colors.add(data[i]*65536+data[i+1]*256+data[i+2]);return colors.size;
 })).toBeGreaterThan(8);
 await page.getByRole("button",{name:"手动范围",exact:true}).click();
 await page.getByLabel("裁剪起点").fill("0.1");await page.getByLabel("裁剪终点").fill("0.8");
 await page.getByRole("button",{name:"创建裁剪版本",exact:true}).click();
 await expect(card.getByRole("option")).toHaveCount(4);await expect(card).toHaveCount(1);
 await card.getByRole("button",{name:"追加变体",exact:true}).click();
 await expect(card.getByRole("option")).toHaveCount(7);await expect(card).toHaveCount(1);
 await page.screenshot({path:path.join(artifacts,"sfx-batch-and-spectrum.png")});
 await page.setViewportSize({width:1024,height:768});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.screenshot({path:path.join(artifacts,"sfx-batch-narrow.png")});
});
