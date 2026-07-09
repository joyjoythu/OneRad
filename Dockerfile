FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖（SimpleITK / PyRadiomics 需要）
RUN apt-get update && apt-get install -y \
    build-essential \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建非 root 用户并保证数据目录可写
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    mkdir -p /app/data /app/output && \
    chown -R appuser:appuser /app/data /app/output
USER appuser

EXPOSE 7860

CMD ["sh", "-c", "python main.py --ui --base-url ${BASE_URL:-https://api.deepseek.com/v1} --model ${MODEL:-deepseek-v4-pro}"]
