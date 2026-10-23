# Syntax: docker/dockerfile:1
# Builder: resolve and install the pinned dependency set.
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
# --prefix puts site-packages and console scripts under /install, which the
# runtime stage copies wholesale into /usr/local (already on sys.path/PATH).
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime: interpreter + deps + application only. No compilers, no pip cache.
FROM python:3.11-slim
COPY --from=builder /install /usr/local

WORKDIR /app
COPY src/ src/

# Non-root: the container filesystem should not be writable by the app user's
# attacker. Secrets (DATABASE_URL, API_KEY, GROQ_API_KEY) arrive via env only —
# never baked into the image.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# /api/health is unauthenticated and unthrottled by design, so orchestrator
# probes never consume the query budget or need a key.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)"]

# Single worker by default. Scale with `uvicorn src.main:app --workers N` —
# rate-limit buckets then need REDIS_URL (shared) and the schema cache is
# per-process with <=60s staleness, which is documented in README.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
