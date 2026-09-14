// Cleans a raw mic take: cuts the click at each end (Record/Stop press),
// trims silence, fades edges and re-encodes to a compact mono WAV.
const OPTS = { cutMs: 120, thresholdDb: -38, padMs: 70, fadeMs: 8, targetRate: 24000 };

function rms(data, from, to) {
  let s = 0;
  for (let i = from; i < to; i++) s += data[i] * data[i];
  return Math.sqrt(s / Math.max(1, to - from));
}

function bounds(data, sr) {
  const cut = Math.floor((OPTS.cutMs / 1000) * sr);
  let lo = cut;
  let hi = data.length - cut;
  if (hi - lo < sr * 0.15) { lo = 0; hi = data.length; }
  const win = Math.floor(sr * 0.01);
  const levels = [];
  for (let i = lo; i + win <= hi; i += win) levels.push(rms(data, i, i + win));
  const sorted = [...levels].sort((a, b) => a - b);
  const floor = sorted[Math.floor(sorted.length * 0.1)] || 0;
  const thr = Math.max(10 ** (OPTS.thresholdDb / 20), floor * 4);
  let first = levels.findIndex((l) => l > thr);
  let last = levels.length - 1 - [...levels].reverse().findIndex((l) => l > thr);
  if (first < 0) return [lo, hi];
  const pad = Math.floor((OPTS.padMs / 1000) * sr);
  return [Math.max(lo, lo + first * win - pad), Math.min(hi, lo + (last + 1) * win + pad)];
}

function encodeWav(samples, sr) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

export async function trimRecording(blob) {
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  await ctx.close();
  const sr = decoded.sampleRate;
  const mono = new Float32Array(decoded.length);
  for (let c = 0; c < decoded.numberOfChannels; c++) {
    const d = decoded.getChannelData(c);
    for (let i = 0; i < d.length; i++) mono[i] += d[i] / decoded.numberOfChannels;
  }
  const [s, e] = bounds(mono, sr);
  const slice = mono.slice(s, e);
  const fade = Math.floor((OPTS.fadeMs / 1000) * sr);
  for (let i = 0; i < fade && i < slice.length; i++) {
    const g = i / fade;
    slice[i] *= g;
    slice[slice.length - 1 - i] *= g;
  }
  const outLen = Math.ceil((slice.length * OPTS.targetRate) / sr);
  const off = new OfflineAudioContext(1, outLen, OPTS.targetRate);
  const src = off.createBufferSource();
  const ab = off.createBuffer(1, slice.length, sr);
  ab.copyToChannel(slice, 0);
  src.buffer = ab;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  return encodeWav(rendered.getChannelData(0), OPTS.targetRate);
}
