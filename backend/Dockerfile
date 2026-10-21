# ComplianceAI - scanner API + admin console
# The OCR stack (torch + easyocr) is heavy, so the image is CPU-only torch.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

# zbar shared library for pyzbar, libGL/libglib for opencv, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch keeps the image roughly 1 GB smaller than the default wheel
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.1+cpu

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY run.py /app/run.py

# The SQLite file lives on a mounted volume so it survives redeploys
ENV DB_PATH=/data/compliance.db \
    UPLOAD_FOLDER=/data/uploads \
    REPORTS_FOLDER=/data/reports \
    PORT=5000

RUN mkdir -p /data/uploads /data/reports && \
    useradd -m -u 1000 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5000/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", \
     "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", \
     "wsgi:application", "--chdir", "backend"]
