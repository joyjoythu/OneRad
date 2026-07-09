# AutoRadiomics Agent (OneRad)

基于影像组学的端到端二分类分析 Agent。后端采用 **FastAPI + LangGraph**（使用 `AsyncSqliteSaver` 持久化检查点），前端采用 **Vue 3 + Element Plus + Pinia**，支持影像/mask 自动配对、临床表格合并、QC、特征提取、LASSO+Logistic Regression 建模，并输出 Word 报告。

UI 以 **OneRad** 品牌运行，提供两个主要视图：

- `/` — 分析视图：配置并运行影像组学流水线、查看实时日志、下载报告。
- `/agent` — Agent 聊天视图：与 AI Agent 对话、审阅/编辑文件计划、执行系统命令与 Python 脚本。

## 技术栈

- 后端：Python 3.10+、FastAPI、LangGraph、`AsyncSqliteSaver`
- 前端：Vue 3、Element Plus、Pinia、Vue Router、Vite
- 部署：Docker 多阶段构建（Node 构建前端，Python 提供后端服务）

## 环境要求

- Python 3.10+
- Node.js 20+（前端开发/构建需要）
- Docker & Docker Compose（可选）

## 安装

### 使用 uv（推荐）

1. 创建虚拟环境：

```bash
uv venv --python 3.11
```

2. 安装 pyradiomics：

> 注意：PyPI 上的 `pyradiomics==3.1.0` 在 Windows 下从源码编译时会因缺少 C 头文件而失败。需要从 GitHub 源码安装。
>
> 下载 [AIM-Harvard/pyradiomics](https://github.com/AIM-Harvard/pyradiomics) 源码并解压到项目根目录，例如 `pyradiomics-master/pyradiomics-master/`，然后执行：

```bash
uv pip install ./pyradiomics-master/pyradiomics-master --no-cache-dir
```

3. 激活环境（`uv pip install` 会自动安装到当前项目虚拟环境，无需手动激活即可使用；如需在 shell 中使用已安装的命令，可激活环境）：

```bash
# Git Bash
source .venv/Scripts/activate

# Windows CMD
.venv\Scripts\activate.bat

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

4. 安装其余依赖：

```bash
uv pip install -r requirements.txt --no-cache-dir
```

### 使用 pip

```bash
pip install -r requirements.txt
```

> 在 Windows 上若 `pyradiomics` 编译失败，请参考上面的「从 GitHub 源码安装」步骤。

### 前端依赖

前端代码位于 `frontend/` 目录。开发前请先安装 Node 依赖：

```bash
cd frontend
npm install
```

常用命令：

```bash
npm run dev        # 启动 Vite 开发服务器（默认 http://localhost:5173）
npm run build      # 构建生产包到 frontend/dist/
npm run test:unit  # 运行前端单元测试
```

## 数据准备

- `--image-dir`：包含成对的影像和 mask 文件（NIfTI 格式）。mask 文件名需包含 `mask`、`seg`、`label` 等关键字。
- `--clinical`：CSV 或 Excel 表格，至少包含患者 ID 列和二分类 Label 列（值为 0/1）。

## 运行

### 设置 API Key（可选，用于 LLM 列名识别与报告润色）

```bash
export DEEPSEEK_API_KEY=your_key
```

### CLI

```bash
python main.py --image-dir ./data/images --clinical ./data/clinical.csv --output-dir ./output
```

### UI（FastAPI + Vue）

`python main.py` 会启动 FastAPI 并同时提供 API 与已构建的 Vue SPA。运行前需要确保 `frontend/dist/` 已存在，可通过以下命令构建：

```bash
cd frontend
npm run build
cd ..
python main.py
```

启动后访问 http://localhost:8000。

> 注意：若未执行 `npm run build`，`frontend/dist/` 不存在时访问根路径会返回 404。

常用启动参数：

- `--host`：服务器绑定地址，默认 `0.0.0.0`。
- `--port`：服务器端口，默认 `8000`。
- `--base-url`：LLM API Base URL，默认 `https://api.deepseek.com/v1`。
- `--model`：模型名称，默认 `deepseek-v4-pro`。
- `--api-key`：LLM API Key；也可通过 `DEEPSEEK_API_KEY` 环境变量设置。
- `--feature-csv`：已提取好的影像组学特征 CSV 路径，提供后直接进入 LASSO + Logistic Regression 分析。

### 前端独立开发

如需热重载开发前端，可在另一个终端执行：

```bash
cd frontend
npm run dev
```

默认访问 http://localhost:5173；若 Vite 配置中已代理 API 请求，则会转发到 http://localhost:8000。

### Docker

```bash
export DEEPSEEK_API_KEY=your_key
docker compose up --build
```

或在使用 Compose V1 的环境：

```bash
docker-compose up --build
```

启动后访问 http://localhost:8000。

## 测试

后端测试：

```bash
pytest tests/
```

前端测试：

```bash
cd frontend
npm run test:unit
```

## Docker 环境变量

- `DEEPSEEK_API_KEY`：DeepSeek API Key。
- `BASE_URL`：LLM API Base URL，默认 `https://api.deepseek.com/v1`。
- `MODEL`：模型名称，默认 `deepseek-v4-pro`。
