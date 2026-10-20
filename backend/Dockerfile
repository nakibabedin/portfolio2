FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Every dependency ships a wheel (psycopg2-binary, Pillow, nh3), so no build
# toolchain. Installed before the code so the layer caches across code edits.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

EXPOSE 8000

# One worker, always: the live relay keeps its HLS segments in this process's
# memory (app/lib/live_relay.py). Proxy headers so the app sees https and the
# visitor's address through the Cloudflare Tunnel.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
