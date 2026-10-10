import { Mic, Square, Trash2, Sparkles, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { audioBufferToWav } from "../recording";
import type { ProjectManifest } from "../types";

interface Props {
  active?: boolean; projectPath: string; referenceAudio: string | null; referenceText: string; asrReady: boolean;
  onReference: (path: string) => void; onText: (text: string) => void;
  onProjectChange: (manifest: ProjectManifest) => void; onError: (message: string) => void;
}
export function ReferenceAudioTools(props: Props) {
  const [recording, setRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [preview, setPreview] = useState<{url: string; blob: Blob} | null>(null);
  const [saving, setSaving] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [status, setStatus] = useState("");
  const [candidate, setCandidate] = useState<{path: string; text: string} | null>(null);
  const [automatic, setAutomatic] = useState(true);
  const mounted = useRef(true);
  const latest = useRef(props); latest.current = props;
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const context = useRef<AudioContext | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const animation = useRef<number | null>(null);
  const previewRef = useRef<string | null>(null);
  const transcriptionId = useRef<string | null>(null);
  const requestVersion = useRef(0);
  const canRecord = () => mounted.current && latest.current.active !== false;
  const stopHardware = () => {
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
    if (timer.current) clearInterval(timer.current); timer.current = null;
    if (animation.current !== null) cancelAnimationFrame(animation.current); animation.current = null;
    if (context.current) void context.current.close().catch(() => undefined); context.current = null;
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false; requestVersion.current++;
      if (recorder.current?.state === "recording") { recorder.current.onstop = null; recorder.current.stop(); }
      stopHardware();
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    };
  }, []);
  useEffect(() => { if (props.active === false && recorder.current?.state === "recording") { stop(); setStatus("已停止录音"); } }, [props.active]);
  function discard() { if (previewRef.current) URL.revokeObjectURL(previewRef.current); previewRef.current = null; setPreview(null); }
  function stop() { if (recorder.current?.state === "recording") recorder.current.stop(); stopHardware(); setRecording(false); setLevel(0); }
  async function start() {
    if (starting || recording) return;
    setStarting(true); setStatus(""); discard();
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") throw new Error("当前环境不支持麦克风录音，请在桌面应用或 localhost 页面使用");
      const input = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
      if (!canRecord()) { input.getTracks().forEach(track => track.stop()); return; }
      stream.current = input;
      const audioContext = new AudioContext(); context.current = audioContext;
      await audioContext.resume();
      if (!canRecord()) { stopHardware(); return; }
      const analyser = audioContext.createAnalyser(); analyser.fftSize = 256;
      audioContext.createMediaStreamSource(input).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      function meter() { analyser.getByteTimeDomainData(samples); const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length); setLevel(Math.min(100, rms * 400)); animation.current = requestAnimationFrame(meter); }
      animation.current = requestAnimationFrame(meter);
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(type => MediaRecorder.isTypeSupported(type));
      const capture = new MediaRecorder(input, mime ? {mimeType: mime} : undefined); recorder.current = capture;
      const chunks: BlobPart[] = [];
      capture.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      capture.onerror = () => { stop(); latest.current.onError("录音失败，请检查麦克风后重试"); };
      capture.onstop = async () => {
        stopHardware();
        if (!mounted.current) return;
        setRecording(false); setStarting(true); setLevel(0);
        const decoder = new AudioContext();
        try {
          const audio = await decoder.decodeAudioData(await new Blob(chunks, {type: capture.mimeType}).arrayBuffer());
          if (audio.duration < 0.3) throw new Error("录音太短，请至少录制一句完整台词");
          const blob = audioBufferToWav(audio);
          if (!mounted.current) return;
          const url = URL.createObjectURL(blob); previewRef.current = url;
          setPreview({url, blob}); setStatus("录音已就绪，试听后可保存为参考音频");
        } catch (error) { if (mounted.current) latest.current.onError(error instanceof Error ? error.message : "无法读取录音"); }
        finally { await decoder.close(); if (mounted.current) setStarting(false); }
      };
      capture.start(250); setRecording(true); setSeconds(0);
      let elapsed = 0;
      timer.current = setInterval(() => { elapsed++; setSeconds(elapsed); if (elapsed >= 120) stop(); }, 1000);
    } catch (error) {
      stopHardware();
      if (mounted.current) props.onError(error instanceof DOMException && error.name === "NotAllowedError" ? "麦克风权限未开启，请在系统和应用权限中允许录音" : error instanceof Error ? error.message : "无法打开麦克风");
    } finally { if (mounted.current) setStarting(false); }
  }
  async function recognize(path = props.referenceAudio, baseline = props.referenceText) {
    if (!path || transcribing) return;
    const version = ++requestVersion.current;
    setTranscribing(true); setCandidate(null); setStatus("正在提交本地识别…");
    try {
      const submitted = await api.transcribe(props.projectPath, path);
      transcriptionId.current = submitted.id;
      let job = submitted;
      while (!["completed", "failed", "cancelled", "interrupted"].includes(job.status)) {
        await new Promise(resolve => setTimeout(resolve, 500));
        if (!mounted.current || version !== requestVersion.current) return;
        job = await api.job(submitted.id); setStatus(job.stage);
      }
      if (!mounted.current || version !== requestVersion.current) return;
      if (job.status !== "completed") throw new Error(job.error?.message || "识别任务已中断");
      const text = String(job.result?.text || "").trim();
      if (!text) throw new Error("未识别到有效台词");
      if (latest.current.referenceAudio === path && latest.current.referenceText === baseline) {
        latest.current.onText(text); setStatus("识别台词已填入，请试听并核对准确性");
      } else { setCandidate({path, text}); setStatus("参考内容已修改，识别结果等待你确认"); }
    } catch (error) { if (mounted.current && version === requestVersion.current) props.onError(error instanceof Error ? error.message : "识别失败"); }
    finally { if (mounted.current && version === requestVersion.current) { setTranscribing(false); transcriptionId.current = null; } }
  }
  async function save() {
    if (!preview || saving) return;
    setSaving(true);
    try {
      const originalPath = props.referenceAudio;
      const result = await api.uploadResources(props.projectPath, [new File([preview.blob], "麦克风参考_" + Date.now() + ".wav", {type: "audio/wav"})]);
      if (!mounted.current) return;
      props.onProjectChange(result.manifest);
      const path = result.assets[0]?.relative_path;
      if (!path) throw new Error("录音导入失败，请重试");
      if (latest.current.referenceAudio !== originalPath) { setStatus("录音已保存到素材；当前参考音频已更换，可从素材重新选择"); return; }
      props.onReference(path); discard(); setStatus("录音已保存到项目");
      if (automatic && props.asrReady) void recognize(path, "");
    } catch (error) { if (mounted.current) props.onError(error instanceof Error ? error.message : "保存录音失败"); }
    finally { if (mounted.current) setSaving(false); }
  }
  return <div className="reference-recording">
    <div className="reference-tool-actions"><button className="secondary-button" onClick={() => recording ? stop() : void start()} disabled={starting || saving}>{recording ? <Square size={15}/> : <Mic size={15}/>} {recording ? "停止录音" : starting ? "准备录音…" : "麦克风录制"}</button><button className="text-button" disabled={!props.referenceAudio || !props.asrReady || transcribing || recording || saving} onClick={() => void recognize()}>{transcribing ? <Loader2 className="spin" size={14}/> : <Sparkles size={14}/>}识别台词</button></div>
    {recording && <div className="recording-meter" role="status"><span className="recording-dot"/><span>录音中 {seconds}s / 120s</span><meter aria-label="麦克风音量" min={0} max={100} value={level}/></div>}
    {preview && <div className="recording-preview"><audio controls src={preview.url} aria-label="麦克风录音试听"/><div className="reference-tool-actions"><button className="primary-button" disabled={saving} onClick={() => void save()}>{saving ? "保存中…" : "保存为参考音频"}</button><button className="icon-button" title="丢弃录音" onClick={discard} disabled={saving}><Trash2 size={15}/></button></div>{props.asrReady && <label><input type="checkbox" checked={automatic} onChange={event => setAutomatic(event.target.checked)}/>保存后自动识别台词</label>}</div>}
    {!props.asrReady && <p className="muted">可录音并手动填写台词；自动识别请先在「模型」安装 Whisper。</p>}
    {status && <p className="muted" role="status">{status}</p>}
    {transcribing && <button className="text-button" onClick={() => { requestVersion.current++; setTranscribing(false); setStatus("已取消识别"); if (transcriptionId.current) void api.cancelJob(transcriptionId.current).catch(error => props.onError(String(error))); }}>取消识别</button>}
    {candidate && <div><p>{candidate.text}</p><button className="text-button" disabled={props.referenceAudio !== candidate.path} onClick={() => { props.onText(candidate.text); setCandidate(null); setStatus("已应用识别结果，请核对台词"); }}>使用识别文本</button></div>}
  </div>;
}
