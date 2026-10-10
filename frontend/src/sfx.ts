import type { GeneratedAsset } from "./types";

export function automaticSoundName(prompt: string) {
  let name=prompt.trim().replace(/^(?:请)?(?:帮我)?(?:生成|制作|创建)(?:一个|一段)?/, "").split(/[，,。.!！?？;；\n]|\bwith\b/i)[0].trim();
  name=name.replace(/^(?:a|an|the)\s+/i,"").replace(/[<>:"/\\|?*\x00-\x1f]/g,"-").replace(/\s+/g," ").slice(0,36).replace(/[ ._-]+$/g,"");
  return name || "新音效";
}
export interface SfxFamily {id:string;batchId:string;root:GeneratedAsset;versions:GeneratedAsset[];inferred?:boolean}
export function sfxDisplayName(asset:GeneratedAsset) {
  if(asset.music_metadata?.sound_name)return String(asset.music_metadata.sound_name);
  if(/^SFX_generated_/.test(asset.name) && asset.prompt_original)return automaticSoundName(asset.prompt_original);
  return asset.name.startsWith("SFX_") ? asset.name.replace(/^SFX_/, "").replace(/_(0[1-8])(?:_\d+)?$/, "") : asset.name;
}
export function sfxFamilies(all: GeneratedAsset[]) {
  const map=new Map(all.map(asset=>[asset.id,asset]));
  const groups=new Map<string,SfxFamily>();
  for(const asset of all) {
    let current:GeneratedAsset|undefined=asset; const visited=new Set<string>(); let sound=asset.kind==="render" && asset.music_metadata?.sfx_family===true; let root=asset; let key=asset.id;
    if(!["sfx","render"].includes(asset.kind))continue;
    while(current && !visited.has(current.id)) {
      visited.add(current.id);
      if(current.kind==="sfx")sound=true;
      else if(current.kind!=="render"){sound=false;break;}
      root=current; key=current.id;
      if(!current.parent_asset_id)break;
      const parent=map.get(current.parent_asset_id);
      if(!parent) {key=current.parent_asset_id;break;}
      current=parent;
    }
    if(!sound)continue;
    const group=groups.get(key) || {id:key,batchId:root.generation_group_id || root.id,root,versions:[]};
    group.versions.push(asset);groups.set(key,group);
  }
  const output:SfxFamily[]=[];
  const legacy=new Map<string,{family:SfxFamily;started:number;numbers:Set<string>}>();
  for(const group of [...groups.values()].sort((a,b)=>a.root.created_at.localeCompare(b.root.created_at))) {
    if(group.root.generation_group_id){output.push(group);continue;}
    const match=group.root.name.match(/^(.*)_(0[1-8])(?:_(\d+))?$/);
    const time=Date.parse(group.root.created_at);
    if(!match || !Number.isFinite(time)){output.push({...group,inferred:true});continue;}
    const key=JSON.stringify([match[1],match[3] || "",group.root.model_id,group.root.prompt_original,group.root.prompt_conditioned]);
    const existing=legacy.get(key);
    if(existing && time-existing.started<=60000 && !existing.numbers.has(match[2])) {
      existing.family.versions.push(...group.versions);existing.numbers.add(match[2]);
    } else {
      const family={...group,inferred:true};output.push(family);legacy.set(key,{family,started:time,numbers:new Set([match[2]])});
    }
  }
  return output.map(group=>({...group,versions:group.versions.slice().sort((a,b)=>a.created_at.localeCompare(b.created_at))}));
}
