# DocIntel backend — FastAPI + Tesseract OCR + poppler + libmagic
# Build context = repo root:  docker build -f backend/Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Runtime native deps:
#  - tesseract-ocr + rus/fra/eng language packs  (pytesseract)
#  - poppler-utils                               (pdf2image)
#  - libmagic1                                   (python-magic)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-rus tesseract-ocr-fra tesseract-ocr-eng \
        poppler-utils libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# build-essential is only needed to compile native wheels (chroma-hnswlib);
# install it, build, then purge to keep the image lean.
COPY backend/requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install -r requirements.txt \
    && apt-get purge -y build-essential && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./

EXPOSE 8000
# LIBRARY_PATH / HF_HOME are injected by the Deployment, not baked here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
