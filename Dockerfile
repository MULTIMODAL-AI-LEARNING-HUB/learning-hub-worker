# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only PyTorch first so sentence-transformers picks it up instead
# of the CUDA variant (saves ~1.5 GB from the final image).
RUN pip install --user --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# ── Stage 2: Final runner ──────────────────────────────────────────────────────
FROM python:3.10-slim

WORKDIR /app

# Runtime dependency for psycopg2-binary
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.10/site-packages
ENV PYTHONUNBUFFERED=1

CMD celery -A celery_app worker --loglevel=info