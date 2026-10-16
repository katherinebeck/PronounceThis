import subprocess, sys, io
import numpy as np, soundfile as sf
sys.path.insert(0, "/app/backend")
import phoneme_ear as ear
ear._load()

def bounds(d, sr, pad_ms=70):
    cut = int(0.12 * sr); lo, hi = cut, len(d) - cut
    if hi - lo < sr * 0.15: lo, hi = 0, len(d)
    win = int(sr * 0.01)
    lv = [np.sqrt(np.mean(d[i:i+win]**2)) for i in range(lo, hi - win + 1, win)]
    srt = sorted(lv); floor = srt[int(len(srt) * 0.1)]
    thr = max(10 ** (-38 / 20), floor * 4)
    first = next(i for i, l in enumerate(lv) if l > thr)
    last = len(lv) - 1 - next(i for i, l in enumerate(reversed(lv)) if l > thr)
    pad = int(pad_ms / 1000 * sr)
    return max(lo, lo + first * win - pad), min(hi, lo + (last + 1) * win + pad)

for name in ["hannah_party", "lily_party", "hannah_story"]:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "0.4", "-i", "anullsrc=r=48000:cl=mono", "-i", f"/tmp/pt_rhotic/{name}.mp3",
                    "-filter_complex", "[1:a]aresample=48000,aformat=channel_layouts=mono[b];[0:a][b]concat=n=2:v=0:a=1,apad=pad_dur=0.5",
                    "-c:a", "pcm_s16le", f"/tmp/{name}_48.wav"], check=True)
    d, sr = sf.read(f"/tmp/{name}_48.wav", dtype="float32")
    for pad_ms in (70, 250):
        s, e = bounds(d, sr, pad_ms)
        sl = d[s:e].copy(); f = int(0.008 * sr)
        sl[:f] *= np.linspace(0, 1, f); sl[-f:] *= np.linspace(1, 0, f)
        sf.write("/tmp/t.wav", sl, sr); sf.write(f"/tmp/{name}_trim{pad_ms}.wav", sl, sr)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "/tmp/t.wav", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "/tmp/t16.wav"], check=True)
        b = open("/tmp/t16.wav", "rb").read()
        probs, id2tok, heard = ear._posteriors(b)
        pid = [i for i, t in id2tok.items() if t == "p"][0]
        print(f"{name} pad={pad_ms}ms trimmed_start={s/sr:.3f}s heard='{heard}' max p(p)={probs[:, pid].max():.3f} first5 argmax={[id2tok.get(int(x)) for x in probs.argmax(-1)[:6]]}")
