import { useEffect, useState } from "react";
import { api } from "../api";
import type { ModelRuntime } from "../types";

export function ModelRuntimePanel({onError}: {onError: (value:string) => void}) {
  const [state,setState] = useState<ModelRuntime | null>(null);
  useEffect(() => {
    let active = true;
    const refresh = () => { void Promise.resolve().then(() => api.modelRuntime()).then(result => {if(active) setState(result)}).catch(() => undefined); };
    refresh(); const timer = setInterval(refresh, 2000);
    return () => {active=false; clearInterval(timer)};
  }, []);
  if (!state) return null;
  const names = {unloaded:"未加载",loading:"正在加载",ready:"已就绪 · 可复用",running:"正在使用",failed:"加载或运行失败"};
  return <section className="runtime-panel"><div><strong>模型运行状态</strong><span>{state.model_id || "当前没有常驻模型"} · {names[state.state]}</span><small>本次启动加载 {state.load_count} 次 · 复用 {state.cache_hits} 次{state.load_seconds > 0 ? " · 最近加载 " + state.load_seconds.toFixed(1) + " 秒" : ""}</small></div><button className="secondary-button" disabled={!state.model_id || state.state === "running" || state.state === "loading"} onClick={() => void api.releaseModels().then(setState).catch(error => onError(error instanceof Error ? error.message : String(error)))}>释放模型</button></section>;
}
