# ============================================================
# Production Dockerfile — multi-stage, slim, non-root
#   Build (từ thư mục 06-lab-complete):  docker build -t agent .
#   Run:  docker run -p 8000:8000 -e AGENT_API_KEY=... -e REDIS_URL=... agent
# ============================================================

# ── Stage 1: builder — cài dependencies vào một prefix riêng ──
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy requirements TRƯỚC source để layer cài dependencies được cache
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime — chỉ chứa Python, packages đã cài và source ──
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# User non-root
RUN groupadd --system appuser && useradd --system --gid appuser --no-create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

USER appuser

EXPOSE 8000

# HEALTHCHECK gọi /health theo đúng PORT mà app đang nghe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=3)"

# `exec` để uvicorn thay thế sh và trở thành PID 1: nhận SIGTERM từ `docker stop` và tắt êm.
# Lắng nghe theo $PORT (Railway/Render cấp), mặc định 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
