# syntax=docker/dockerfile:1

# Stage 1: Build Vue frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Stage 2: Python runtime
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for SimpleITK / PyRadiomics
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY main.py .
COPY app/ ./app/
COPY config/ ./config/

# Copy built frontend artifacts from the build stage
COPY --from=frontend-builder /app/dist ./frontend/dist

# Create non-root user and ensure data/output directories are writable
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    mkdir -p /app/data /app/output && \
    chown -R appuser:appuser /app/data /app/output /app/frontend/dist

# Persist SQLite databases in the mounted /app/data directory
ENV ONERAD_DATA_DIR=/app/data

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "python main.py --host 0.0.0.0 --port 8000 --base-url ${BASE_URL:-https://api.deepseek.com/v1} --model ${MODEL:-deepseek-v4-pro}"]
