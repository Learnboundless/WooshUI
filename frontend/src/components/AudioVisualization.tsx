import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AudioAnalysis } from "../types";

export function AudioVisualization({projectPath,path,label,missing=false,revision=0}:{projectPath:string;path:string;label:string;missing?:boolean;revision?:number}) {
  const [analysis,setAnalysis]=useState<AudioAnalysis|null>(null);
  const [error,setError]=useState("");const [view,setView]=useState<"wave"|"spectrum">("wave");
  const container=useRef<HTMLDivElement>(null); const canvas=useRef<HTMLCanvasElement>(null);
  useEffect(()=>{
    let cancelled=false;setAnalysis(null);setError("");
    if(missing)return;
    let started=false;
    const load=()=>{if(started)return;started=true;void api.analyzeAudio(projectPath,path).then(value=>{if(!cancelled)setAnalysis(value)}).catch(reason=>{if(!cancelled)setError(reason instanceof Error?reason.message:String(reason))})};
    if(typeof IntersectionObserver==="undefined"){load();return()=>{cancelled=true}}
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){load();observer.disconnect()}},{rootMargin:"160px"});
    if(container.current)observer.observe(container.current);
    return()=>{cancelled=true;observer.disconnect()};
  },[projectPath,path,missing,revision]);
  useEffect(()=>{
    if(!analysis || view!=="spectrum" || !canvas.current)return;
    const width=analysis.spectrogram.length,height=analysis.spectrogram[0]?.length || 0;
    if(!width||!height)return;
    canvas.current.width=width;canvas.current.height=height;
    const context=canvas.current.getContext("2d");if(!context)return;
    const image=context.createImageData(width,height);
    for(let x=0;x<width;x++)for(let y=0;y<height;y++){
      const value=Math.max(0,Math.min(1,(analysis.spectrogram[x][y]+90)/90));const p=((height-y-1)*width+x)*4;
      image.data[p]=Math.round(12+230*Math.max(0,(value-.4)/.6));image.data[p+1]=Math.round(20+170*value);image.data[p+2]=Math.round(45+160*(1-Math.abs(value-.5)*2));image.data[p+3]=255;
    }
    context.putImageData(image,0,0);
  },[analysis,view]);
  const scale=Math.max(1,analysis?.peak || 1);
  const polygon=analysis ? [...analysis.peaks.map((pair,i)=>[i/Math.max(1,analysis.peaks.length-1)*600,42-pair[1]/scale*36]),...analysis.peaks.map((pair,i)=>[i/Math.max(1,analysis.peaks.length-1)*600,42-pair[0]/scale*36]).reverse()].map(p=>p.join(',')).join(' ') : '';
  return <div className="audio-visualization" ref={container}>
    <div className="audio-visualization-controls"><div role="group" aria-label="音频图形"><button type="button" className={view==='wave'?'active':''} onClick={event=>{event.stopPropagation();setView('wave')}}>波形</button><button type="button" className={view==='spectrum'?'active':''} onClick={event=>{event.stopPropagation();setView('spectrum')}}>频谱图</button></div>{analysis && <span>{analysis.duration_seconds.toFixed(2)}s · {analysis.sample_rate/1000} kHz · {analysis.peak_dbfs.toFixed(1)} dBFS</span>}</div>
    {missing ? <div className="audio-visualization-placeholder">音频文件缺失</div> : !analysis ? <div className="audio-visualization-placeholder">{error ? "音频分析不可用" : "读取真实音频…"}</div> : view==='wave' ? <svg viewBox="0 0 600 84" preserveAspectRatio="none" role="img" aria-label={label+" 的真实波形"}><line x1="0" y1="42" x2="600" y2="42" stroke="currentColor" opacity="0.15"/><polygon points={polygon}/></svg> : <div className="spectrogram-view"><canvas ref={canvas} role="img" aria-label={label+" 的真实频谱图"}/><small>20 Hz → {Math.round(analysis.sample_rate/2000)} kHz · 亮色表示更强能量</small></div>}
    {analysis && analysis.peak>1 && <small className="line-issue">存在超满幅峰值，建议创建峰值保护版本</small>}
  </div>;
}
