# Pronounce This — ear service (phoneme recogniser)
# Build from the repo root so backend/phoneme_ear.py is in the context:
#   docker build -f ear-service/Dockerfile -t pt-ear .
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY ear-service/ear-requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

ENV PHONEME_EAR_MODEL=vitouphy/wav2vec2-xls-r-300m-timit-phoneme \
    PHONEME_EAR_DTYPE=bfloat16 \
    HF_HOME=/srv/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=2

# Bake the model into the image so cold starts don't download 1.2 GB.
RUN python -c "import os; from transformers import AutoModelForCTC, AutoProcessor; m=os.environ['PHONEME_EAR_MODEL']; AutoProcessor.from_pretrained(m); AutoModelForCTC.from_pretrained(m)"

COPY backend/phoneme_ear.py ear-service/app.py ./

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s \
  CMD python -c "import os,urllib.request as u; r=u.Request('http://127.0.0.1:8080/health', headers={'X-Ear-Secret': os.environ['EAR_SECRET']}); print(u.urlopen(r, timeout=8).read())" || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
