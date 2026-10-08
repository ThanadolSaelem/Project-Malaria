# Reconstructed 2026-10-08 from `docker history` of vflat-scan:arm64 on the
# Oracle VM (the original Dockerfile was not kept). Layers, in order:
# python:3.11-slim (Debian trixie, Python 3.11.16) -> pip deps -> models -> code.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
      numpy \
      opencv-python-headless \
      fastapi \
      "uvicorn[standard]" \
      python-multipart \
      pymupdf \
      img2pdf \
 && (pip install --no-cache-dir ai-edge-litert || pip install --no-cache-dir tflite-runtime)

COPY models/ /models/
COPY vflat_scan.py run_test.py app.py pdf_utils.py ./

# VFLAT_THREADS=4 is the image default; on a 1-core host set it to 1 at run
# time (see docker-compose.snippet.yml).
ENV VFLAT_MODELS=/models VFLAT_PERM=/models/freeform_perm.json VFLAT_THREADS=4

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
