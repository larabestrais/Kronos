FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    TZ=Europe/Brussels

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better caching)
COPY requirements.txt requirements-bot.txt ./
RUN pip install --upgrade pip && \
    case "$(uname -m)" in \
        x86_64) pip install --index-url https://download.pytorch.org/whl/cpu torch ;; \
        aarch64|arm64) pip install torch ;; \
        *) pip install torch ;; \
    esac && \
    pip install -r requirements-bot.txt

# Copy code (excludes via .dockerignore)
COPY . .

# Persist runtime data outside the image
RUN mkdir -p /app/data /app/.cache/huggingface

EXPOSE 5050

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -fsS -u "${DASHBOARD_USER:-kronos}:${DASHBOARD_PASSWORD:-_}" http://localhost:5050/api/state || exit 1

CMD ["python", "run_dashboard.py", "--remote", "--host", "0.0.0.0", "--port", "5050"]
