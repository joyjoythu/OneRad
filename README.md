# OneRad — 影像组学智能分析 Agent

基于大语言模型的端到端影像组学分析平台。通过自然语言对话即可完成图像/mask 配对、参数确认、PyRadiomics 特征提取、LASSO+Logistic Regression 建模及 Word 报告生成。后端 **FastAPI + LangGraph**，前端 **Vue 3 + Element Plus**。

## 技术栈

- 后端：Python 3.10+、FastAPI、LangGraph（`AsyncSqliteSaver` 持久化检查点）
- LLM：DeepSeek V4（`deepseek-v4-flash` / `deepseek-v4-pro`），通过原生 OpenAI SDK 调用
- 前端：Vue 3、Element Plus、Pinia、Vue Router、Vite
- 部署：Docker 多阶段构建

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

> PyPI 上的 `pyradiomics==3.1.0` 在 Windows 下从源码编译时会因缺少 C 头文件而失败，需从 GitHub 源码安装。
>
> 下载 [AIM-Harvard/pyradiomics](https://github.com/AIM-Harvard/pyradiomics) 源码并解压到项目根目录，然后执行：

```bash
uv pip install ./pyradiomics-master/pyradiomics-master --no-cache-dir
```

3. 激活环境：

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

```bash
cd frontend
npm install
```

## 快速开始

### 1. 设置 API Key

在「设置 → 通用设置」页面填写 DeepSeek API Key，或通过环境变量：

```bash
export DEEPSEEK_API_KEY=your_key
```

### 2. 启动服务

```bash
cd frontend && npm run build && cd ..
python main.py
```

访问 **http://localhost:8000** 即可。

> 前端开发时可单独启动 Vite 热重载：`cd frontend && npm run dev`（默认 http://localhost:5173，API 请求代理到 8000）。

### 3. 创建项目

在侧边栏点击「新建项目」，指定名称和数据目录。项目目录建议结构：

```
my_project/
├── images/          # NIfTI 图像文件 (*.nii.gz)
├── masks/           # 分割掩膜文件 (*.nii.gz)
├── clinical.xlsx    # 临床表格（CSV 或 Excel，含患者 ID 和二分类 Label 列）
└── Params_labels.yaml  # PyRadiomics 提取参数（可选，缺失时使用默认配置）
```

### 4. 开始对话

点击项目进入 Agent 对话界面，用自然语言描述分析目标即可，例如：

- "帮我分析这个项目的影像组学数据"
- "先扫描一下项目目录结构"
- "检查这批图像的 spacing 是否一致"
- "用新的 clinical_v2.xlsx 重新跑一次分析"

Agent 会自动：探索项目文件 → 配对图像与掩膜 → 检测 spacing → 确认提取参数 → 提取特征 → 建模分析 → 生成报告。关键操作会弹出审批面板等待你确认。

## 界面功能

### Agent 对话区

- **自然语言交互**：用中文描述分析需求，Agent 自动规划并执行
- **思考过程可见**：DeepSeek 推理模型的思考链实时展示（可折叠）
- **模型切换**：支持 `deepseek-v4-flash`（默认）和 `deepseek-v4-pro`
- **自动审批模式**：开启后工具调用免确认直接执行，适合信任度高的场景

### 审批面板

Agent 在执行敏感操作前会挂起并弹出审批面板，你可选择：

- **文件操作**：查看/编辑文件整理计划（移动、复制、重命名、新建目录）
- **Python 脚本**：查看代码（高亮 + 风险等级标记）后确认执行
- **影像组学配对**：审核图像-掩膜配对结果，调整后确认
- **特征提取**：确认提取参数、病例数、输出目录
- **建模分析**：确认特征 CSV、临床表、ID 列、Label 列、协变量

### 右侧面板

- **步骤进度**（Todo List）：Agent 自动维护分析步骤清单，实时展示当前进度
- **子任务状态**：并行子 Agent 探索项目时，可看到每个子任务的进行状态

### 项目与对话管理

- **侧边栏**：按项目分组管理对话，支持重命名、删除
- **对话持久化**：所有对话历史自动保存，关闭浏览器后重新打开可继续
- **运行状态**：对话运行时侧边栏显示转圈动画，结束后显示提示点

## 路径约定

Agent 会自动在项目目录下查找和输出文件。默认路径约定：

| 产物 | 路径 |
|------|------|
| 特征 CSV | `radiomics_features/radiomics_features.csv` |
| 特征缓存 | `radiomics_features/h5/*.h5` |
| 失败记录 | `radiomics_features/failed_cases.csv` |
| 分析结果 | `radiomics_analysis/`（含 selected_features.csv、metrics.json、report.docx） |
| 统计结果 | `feature_statistics/`（含统计表格 .docx） |
| 脚本存档 | `agent_scripts/`（Agent 生成的 Python 脚本） |
| 文件备份 | `.onerad_backup/<timestamp>/` |

用户通常无需手动指定这些路径——Agent 会自动推断。断点续提基于 h5 缓存的参数哈希，参数不变则跳过已提取的病例。

## Skills 系统

Agent 的行为由 `skills/` 目录下的 Markdown 文件驱动，每次 LLM 调用时从磁盘实时读取，编辑即生效，无需重启：

| Skill | 用途 |
|-------|------|
| `agent-core` | Agent 核心行为：工具使用准则、安全边界、确认流程 |
| `radiomics-workflow` | 影像组学工作流：0–6 步标准流程与进度报告规范 |
| `file-operations` | 文件操作计划生成的 prompt 模板 |
| `clinical-columns` | 临床表列名识别 |
| `filename-id` | 文件名患者 ID 推断 |
| `report-writing` | 报告方法学润色 |
| `thread-title` | 对话标题生成 |

> 工具参数校验、沙箱、安全策略和审批流程由 Python 代码强制执行，无法通过修改 Markdown 绕过。

## 启动参数

```bash
python main.py --host 0.0.0.0 --port 8000 --base-url https://api.deepseek.com/v1
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 服务器绑定地址 |
| `--port` | `8000` | 服务器端口 |
| `--base-url` | `https://api.deepseek.com/v1` | LLM API 地址 |
| `--api-key` | — | LLM API Key（也可用环境变量） |
| `--feature-csv` | — | 已有特征 CSV 路径，跳过提取直接分析 |

## Docker

```bash
export DEEPSEEK_API_KEY=your_key
docker compose up --build
```

启动后访问 http://localhost:8000。Docker 环境变量：

- `DEEPSEEK_API_KEY`：DeepSeek API Key
- `BASE_URL`：LLM API Base URL，默认 `https://api.deepseek.com/v1`

## 测试

```bash
pytest tests/                # 后端测试
cd frontend && npm run test:unit  # 前端测试
```
