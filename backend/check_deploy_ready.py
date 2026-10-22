"""Pre-deploy guard: fails if requirements.txt carries packages that break the production build."""
import re
import sys
from pathlib import Path

BANNED = {"torch", "torchaudio", "transformers", "soundfile", "accelerate", "safetensors"}
REQ = Path(__file__).with_name("requirements.txt")


def main() -> int:
    problems = []
    for line in REQ.read_text().splitlines():
        spec = line.strip()
        if not spec or spec.startswith("#"):
            continue
        name = re.split(r"[=<>!~\[ ]", spec, 1)[0].lower()
        if name in BANNED:
            problems.append(f"ML package not allowed in production: {spec}")
        elif "+cpu" in spec or "+cu" in spec:
            problems.append(f"local-version wheel not installable in deploy: {spec}")
    for p in problems:
        print("BLOCKED:", p)
    print("deploy check:", "FAILED" if problems else "OK", f"({REQ})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
