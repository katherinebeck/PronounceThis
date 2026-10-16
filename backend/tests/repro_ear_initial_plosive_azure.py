import asyncio, subprocess, sys
sys.path.insert(0, "/app/backend")
import practice, phoneme_ear as ear
ear._load()
async def main():
    for f in ["/tmp/hannah_party_trim70.wav", "/tmp/hannah_party_trim250.wav"]:
        subprocess.run(["ffmpeg","-y","-v","error","-i",f,"-ac","1","-ar","16000","-c:a","pcm_s16le","/tmp/az.wav"],check=True)
        wav = open("/tmp/az.wav","rb").read()
        out = practice._interpret("party", await practice._call_azure(wav, "party"))
        win = [{"expected":p.expected,"start_s":p.start_s or 0,"end_s":p.end_s or 0} for p in out.phonemes]
        h = ear.listen(wav, win)
        print(f, [(w["expected"], round(w["start_s"],3), round(w["end_s"],3)) for w in win])
        print("  heard", h["heard"], [(c["expected"], c["verdict"], c["p_expected"], c["heard"]) for c in h["checks"]])
asyncio.run(main())
