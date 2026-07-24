# 安装部署

OneRad 支持三种运行方式：**Docker（推荐）**、本地开发、CLI 命令行模式。

## 方式一：Docker 运行（推荐）

### 1. 前置条件

确保已安装 Docker Desktop：

```bash
docker --version
docker compose version
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek API Key：

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
BASE_URL=https://api.deepseek.com/v1
PORT=8000
```

::: tip 说明
- `BASE_URL` 使用 DeepSeek 官方 API 无需修改；如走代理/中转，改为对应地址。
- `.env` 已在 `.gitignore` 中排除，不会被提交到 GitHub。
- 如果不写 `.env`，也可以启动后在 Web 界面的**设置页**中填入 API Key（二者任选其一，界面设置优先级更高）。
:::

### 3. 构建镜像

```bash
docker compose build
```

首次构建约 **5–10 分钟**（下载基础镜像 + 安装依赖 + 编译前端）。后续构建利用缓存，仅需几十秒。

### 4. 启动容器

```bash
docker compose up -d
```

查看日志确认启动成功：

```bash
docker compose logs -f
```

### 5. 访问

浏览器打开 **http://localhost:8000**

### 6. 常用命令

| 操作 | 命令 |
|------|------|
| 启动 | `docker compose up -d` |
| 停止 | `docker compose down` |
| 重启 | `docker compose restart` |
| 查看日志 | `docker compose logs -f` |
| 查看状态 | `docker compose ps` |
| 进入容器 | `docker compose exec autoradiomics bash` |
| 重建镜像 | `docker compose build --no-cache` |

### 7. 数据持久化

| 容器路径 | 宿主机路径 | 用途 |
|---------|-----------|------|
| `/app/data` | `./data` | SQLite 数据库、配置文件 |
| `/app/output` | `./output` | 分析报告、图表、特征文件 |

删除容器不会丢失数据。

### 8. 端口自定义

如 8000 端口被占用，修改 `.env` 中 `PORT` 后重启：

```ini
PORT=8080
```

---

## 方式二：本地开发

### 后端

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
pip install --no-build-isolation pyradiomics==3.0.1
python main.py  # 启动于 http://localhost:8000
```

### 前端

```bash
cd frontend
npm install
npm run dev  # 启动于 http://localhost:5173，自动代理 /api 到 :8000
```

---

## 方式三：CLI 模式

支持跳过 Web UI，直接从命令行运行分析：

```bash
python main.py --feature-csv features.csv --clinical clinical.xlsx --output-dir ./output
```

完整参数见：

```bash
python main.py --help
```

::: warning 适用场景
CLI 模式适合批量复现已有特征表的分析，不包含对话式探索、审批面板等交互能力。首次使用建议从 Web UI 开始。
:::

---

## 首次启动检查清单

1. ✅ 浏览器能打开 http://localhost:8000
2. ✅ API Key 已配置（`.env` 或设置页），状态显示「已配置」
3. ✅ 新建一个测试项目，发送一条消息能收到 Agent 回复

全部通过后，进入 [5 分钟快速上手](/guide/quickstart)。
