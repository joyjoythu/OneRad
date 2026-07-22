# syntax=docker/dockerfile:1

# Stage 1: Build Vue frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Stage 2: Python runtime
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for SimpleITK / PyRadiomics / h5py
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
# Use requirements.lock (uv pip compile output) for reproducible builds.
# pyradiomics 3.1.0 has broken PyPI metadata (declares version 3.0.1a1);
# we drop that pin, install the rest of the locked set, then install
# pyradiomics 3.0.1 without build isolation so its setup.py can see numpy.
# See: https://github.com/AIM-Harvard/pyradiomics/issues/933
COPY requirements.lock .
RUN pip install --no-cache-dir setuptools wheel numpy && \
    sed -i '/^pyradiomics==/d' requirements.lock && \
    pip install --no-cache-dir -r requirements.lock && \
    pip install --no-cache-dir --no-build-isolation pyradiomics==3.0.1

# Copy backend source code
COPY main.py .
COPY app/ ./app/
COPY config/ ./config/
COPY skills/ ./skills/

# Copy built frontend artifacts from the build stage
COPY --from=frontend-builder /app/dist ./frontend/dist

# Create non-root user with fixed UID/GID 1000:1000 so host bind-mounts are
# predictable on Linux. Ensure host ./data and ./output are owned by UID 1000,
# or adjust these IDs to match the host user.
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser && \
    mkdir -p /app/data /app/output && \
    chown -R appuser:appuser /app/data /app/output /app/frontend/dist

# Persist SQLite databases and settings in the mounted /app/data directory
ENV ONERAD_DATA_DIR=/app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["sh", "-c", "exec python main.py --host 0.0.0.0 --port 8000 --base-url ${BASE_URL:-https://api.deepseek.com/v1}"]
