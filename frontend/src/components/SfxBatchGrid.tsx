import { useMemo, useState } from "react";
import { Heart,Play,Plus } from "lucide-react";
import { sfxFamilies,sfxDisplayName } from "../sfx";
import type { GeneratedAsset,ProjectManifest } from "../types";
import { AudioVisualization } from "./AudioVisualization";
import { AssetActions } from "./AssetActions";

interface Props {
  assets:GeneratedAsset[];selectedId?:string;projectPath:string;missingIds:Set<string>;revision:number;
  onSelect:(asset:GeneratedAsset)=>void;onPlay:(asset:GeneratedAsset)=>void;onFavorite:(id:string)=>void;
  onContext:(asset:GeneratedAsset,x:number,y:number)=>void;onMore:(asset:GeneratedAsset)=>void;
  onProjectChange:(project:ProjectManifest)=>void;onError:(error:string)=>void;
}
export function SfxBatchGrid(props:Props) {
  const families=useMemo(()=>sfxFamilies(props.assets),[props.assets]);
  const [chosen,setChosen]=useState<Record<string,string>>({});
  const batches=useMemo(()=>{
    const map=new Map<string,typeof families>();
    for(const family of families)map.set(family.batchId,[...(map.get(family.batchId)||[]),family]);
    return [...map.entries()].reverse();
  },[families]);
  if(!families.length)return <div className="empty-state"><strong>还没有音效</strong><span>每次生成会形成一个批次，变体保存在同一卡片中。</span></div>;
  return <div className="sfx-batches">{batches.map(([id,items],index)=><section className="sfx-batch" key={id} aria-label={"音效批次 "+(batches.length-index)}><header className="sfx-batch-header"><strong>{items[0].inferred ? "历史批次" : "批次"} {String(batches.length-index).padStart(2,'0')}</strong><span>{new Date(items[0].root.created_at).toLocaleString()} · {items[0].root.model_id || "音效"}</span><small>{items[0].inferred ? "按文件名与时间归档 · " : ""}{items.reduce((sum,item)=>sum+item.versions.length,0)} 个版本</small></header><div className="sfx-family-grid">{items.map(family=>{
    const selected=family.versions.find(asset=>asset.id===props.selectedId);
    const asset=selected || family.versions.find(asset=>asset.id===chosen[family.id]) || family.versions.at(-1)!;
    const name=sfxDisplayName(family.root);
    return <article key={family.id} className={"sfx-family-card "+(selected?'selected':'')} aria-label={name+" 音效卡片"} tabIndex={0} onClick={()=>props.onSelect(asset)} onContextMenu={event=>{event.preventDefault();props.onContext(asset,event.clientX,event.clientY)}} onKeyDown={event=>{if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();const rect=event.currentTarget.getBoundingClientRect();props.onContext(asset,rect.left+15,rect.top+15)}}}>
      <div className="sfx-family-heading"><div><h3>{name}</h3><p>{family.root.prompt_original || family.root.prompt_conditioned || "音效素材"}</p></div><button className="icon-button" title={asset.favorite?'取消收藏':'收藏'} onClick={event=>{event.stopPropagation();props.onFavorite(asset.id)}}><Heart size={17} fill={asset.favorite?'currentColor':'none'}/></button></div>
      <div className="sfx-version-row"><label>版本<select aria-label={name+" 版本"} value={asset.id} onClick={event=>event.stopPropagation()} onChange={event=>{const target=family.versions.find(item=>item.id===event.target.value)!;setChosen({...chosen,[family.id]:target.id});props.onSelect(target)}}>{family.versions.map((version,i)=><option key={version.id} value={version.id}>{version.music_metadata?.edit_operation==='trim' || version.tags.includes('已裁剪') ? '裁剪版本' : i===0 ? '原始版本' : '变体 '+(i+1)} · {version.duration_seconds.toFixed(2)}s{props.missingIds.has(version.id)?' · 文件缺失':''}</option>)}</select></label><span>{family.versions.length} 个版本</span></div>
      <AudioVisualization projectPath={props.projectPath} path={asset.relative_path} label={name} missing={props.missingIds.has(asset.id)} revision={props.revision}/>
      <div className="sfx-card-actions"><button className="secondary-button" disabled={props.missingIds.has(asset.id)} onClick={event=>{event.stopPropagation();props.onPlay(asset)}}><Play size={14}/>试听当前版本</button><button className="text-button" onClick={event=>{event.stopPropagation();props.onMore(asset)}}><Plus size={14}/>追加变体</button><AssetActions asset={asset} projectPath={props.projectPath} missing={props.missingIds.has(asset.id)} onProjectChange={props.onProjectChange} onError={props.onError}/></div>
    </article>;
  })}</div></section>)}</div>;
}
