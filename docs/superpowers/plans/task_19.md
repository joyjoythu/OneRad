# Task 19: 实现 Docker 部署

### Task 19: 实现 Docker 部署

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
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

EXPOSE 7860

CMD ["python", "main.py", "--ui"]
```

- [ ] **Step 2: 创建 docker-compose.yml**

```yaml
version: '3.8'
services:
  autoradiomics:
    build: .
    ports:
      - "7860:7860"
    volumes:
      - ./data:/app/data
      - ./output:/app/output
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
```

- [ ] **Step 3: 创建 README.md 使用说明**

`README.md`:
```markdown
# AutoRadiomics Agent

## 安装

```bash
pip install -r requirements.txt
```

## 运行

### CLI
```bash
python main.py --image-dir ./data/images --clinical ./data/clinical.csv --output-dir ./output
```

### UI
```bash
python main.py --ui
```

### Docker
```bash
docker-compose up --build
```
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "feat: add Docker deployment and README"
```

---

## Phase 5: 优化与收尾
