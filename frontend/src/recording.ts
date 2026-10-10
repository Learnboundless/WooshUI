export function audioBufferToWav(audio: AudioBuffer): Blob {
  const size = audio.length * 2;
  const buffer = new ArrayBuffer(44 + size);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, 36 + size, true); text(8, "WAVE"); text(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, audio.sampleRate, true); view.setUint32(28, audio.sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, size, true);
  const channels = Array.from({length: audio.numberOfChannels}, (_, index) => audio.getChannelData(index));
  for (let frame = 0; frame < audio.length; frame++) {
    let sample = channels.reduce((sum, channel) => sum + channel[frame], 0) / channels.length;
    sample = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + frame * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([buffer], {type: "audio/wav"});
}
