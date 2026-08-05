import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import WaveSurfer from "wavesurfer.js";

interface WaveformProps {
  url: string;
  height?: number;
  color?: string;
  progressColor?: string;
  onReady?: (duration: number) => void;
}

export interface WaveformHandle {
  togglePlayback: () => void;
}

export const Waveform = forwardRef<WaveformHandle, WaveformProps>(function Waveform({
  url,
  height = 72,
  color = "#9ca3af",
  progressColor = "#3b82f6",
  onReady,
}, forwardedRef) {
  const ref = useRef<HTMLDivElement>(null);
  const waveformRef = useRef<WaveSurfer | null>(null);

  useImperativeHandle(forwardedRef, () => ({
    togglePlayback() {
      if (waveformRef.current) void waveformRef.current.playPause();
    },
  }), []);

  useEffect(() => {
    if (!ref.current) return;
    const waveform = WaveSurfer.create({
      container: ref.current,
      height,
      waveColor: color,
      progressColor,
      cursorColor: "#111827",
      cursorWidth: 1,
      barWidth: 2,
      barGap: 2,
      barRadius: 1,
      normalize: true,
      url,
    });
    waveformRef.current = waveform;
    waveform.on("ready", () => onReady?.(waveform.getDuration()));
    const node = ref.current;
    const toggle = () => waveform.playPause();
    node.addEventListener("dblclick", toggle);
    return () => {
      node.removeEventListener("dblclick", toggle);
      waveformRef.current = null;
      waveform.destroy();
    };
  }, [color, height, onReady, progressColor, url]);

  return <div className="waveform" ref={ref} aria-label="音频波形，双击播放或暂停" />;
});
