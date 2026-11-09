"""Generate ear test clips (American control + Australian/British variants) into /tmp/pt_rhotic.

Run: cd /app/backend && python3 tests/make_ear_clips.py
"""
import os
import subprocess
import sys

from elevenlabs.client import ElevenLabs

OUT = "/tmp/pt_rhotic"
VOICES = {
    "hannah": "ZSNL4hPqCnqoMPaI4jGX",   # American
    "tanya": "DusxpIechtn2D8hID1Jy",    # Australian
    "charlie": "IKne3meq5aSn9XLyUdCD",  # Australian
    "gemma": "jQQiXyFE3PBHLF8znAIb",    # Australian
    "george": "JBFqnCBsd6RMkjVDRZzb",   # British
    "lily": "pFZP5JQG7iQjIQuC4Bku",     # British
}
WORDS = {
    "hannah": ["mother", "aluminum", "home", "party", "water", "toast", "father", "brother", "who", "food", "internet"],
    "tanya": ["aluminum", "aluminium", "home", "mother", "who", "food", "party", "water"],
    "charlie": ["aluminum", "aluminium", "home", "mother", "who", "food"],
    "gemma": ["aluminum", "home", "mother", "who"],
    "george": ["aluminum", "aluminium", "home", "mother"],
    "lily": ["aluminum", "home", "mother"],
}


def main():
    os.makedirs(OUT, exist_ok=True)
    c = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    only = sys.argv[1:] or list(WORDS)
    for voice in only:
        for word in WORDS[voice]:
            path = f"{OUT}/{voice}_{word}.mp3"
            if os.path.exists(path):
                continue
            kw = {}
            if voice == "hannah":
                kw = dict(previous_text="You're an American English coach from the Midwest speaking in your natural General American accent. Listen and repeat after me. The word is",
                          next_text="That's how we say it in American English. Now you try.")
            else:
                kw = dict(previous_text="Say the word in your own natural accent. The word is", next_text="Now you try.")
            stream = c.text_to_speech.convert(text=word, voice_id=VOICES[voice], model_id="eleven_v4", language_code="en",
                                              output_format="mp3_44100_128", **kw)
            with open(path, "wb") as f:
                f.write(b"".join(ch for ch in stream if ch))
            print("wrote", path)
    # Synthetic overdone -er: stretch the last 45% of Hannah's "mother" and "father" to 2x length.
    for word in ("mother", "father", "brother"):
        src, dst = f"{OUT}/hannah_{word}.mp3", f"{OUT}/heldr_{word}.mp3"
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]).decode().strip())
        cut = dur * 0.55
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex",
                        f"[0:a]atrim=0:{cut:.3f},asetpts=PTS-STARTPTS[a];[0:a]atrim={cut:.3f},asetpts=PTS-STARTPTS,atempo=0.5[b];[a][b]concat=n=2:v=0:a=1",
                        dst], check=True)
        print("wrote", dst)


main()
