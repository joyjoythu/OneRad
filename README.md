# OneRad — AutoRadiomic Agent

基于大语言模型（LLM）的端到端影像组学分析平台。通过自然语言对话完成图像/掩膜配对、参数确认、PyRadiomics 特征提取、LASSO + 逻辑回归建模、SHAP 可解释性分析及 Word 报告生成。

## 📖 使用指南

完整使用文档（安装部署、快速上手、功能详解、设计思路）请访问：

**https://joyjoythu.github.io/OneRad/**

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 / FastAPI / LangGraph |
| 前端 | Vue 3 + TypeScript + Element Plus |
| LLM | DeepSeek (兼容 OpenAI SDK) |
| 影像 | PyRadiomics / SimpleITK |

---

## Docker 运行（推荐）

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

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
BASE_URL=https://api.deepseek.com/v1
PORT=8000
```

> `BASE_URL` 使用 DeepSeek 官方 API 无需修改；如走代理/中转，改为对应地址。
> `.env` 已在 `.gitignore` 中排除，不会被提交到 GitHub。

### 3. 构建镜像

```bash
docker compose build
```

首次构建约 **5-10 分钟**（下载基础镜像 + 安装依赖 + 编译前端）。后续构建利用缓存，仅需几十秒。

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
|---|---|
| 启动 | `docker compose up -d` |
| 停止 | `docker compose down` |
| 重启 | `docker compose restart` |
| 查看日志 | `docker compose logs -f` |
| 查看状态 | `docker compose ps` |
| 进入容器 | `docker compose exec autoradiomics bash` |
| 重建镜像 | `docker compose build --no-cache` |

### 7. 数据持久化

| 容器路径 | 宿主机路径 | 用途 |
|---|---|---|
| `/app/data` | `./data` | SQLite 数据库、配置文件 |
| `/app/output` | `./output` | 分析报告、图表、特征文件 |

删除容器不会丢失数据。

### 8. 端口自定义

如 8000 端口被占用，修改 `.env` 中 `PORT` 后重启：

```
PORT=8080
```

---

## 本地开发

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

## CLI 模式

> 当前版本暂不支持 CLI 方式启动，请通过 Docker 或本地开发方式运行 Web UI 后使用。
>
> 后续版本将重新提供命令行入口。
