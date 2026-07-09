# AutoRadiomics Agent (OneRad)

基于影像组学的端到端二分类分析 Agent。支持影像/mask 自动配对、临床表格合并、QC、特征提取、LASSO+Logistic Regression 建模，并输出 Word 报告。
UI 模式下以 **OneRad** 品牌运行，支持左侧项目侧边栏同时管理多个影像组学项目。

## 环境要求

- Python 3.10+
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

3. 安装其余依赖：

```bash
uv pip install -r requirements.txt --no-cache-dir
```

4. 激活环境：

```bash
# Git Bash
source .venv/Scripts/activate

# Windows CMD
.venv\Scripts\activate.bat

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

### 使用 pip

```bash
pip install -r requirements.txt
```

> 在 Windows 上若 `pyradiomics` 编译失败，请参考上面的「从 GitHub 源码安装」步骤。

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

### UI

```bash
python main.py --ui
```

启动后访问 http://localhost:7860。在 OneRad 界面左侧可新建、切换、删除项目；每个项目目录下会自动保存 `project.yaml`（项目配置）和 `Params_labels.yaml`（影像组学参数）。

### Docker

```bash
export DEEPSEEK_API_KEY=your_key
docker-compose up --build
```

启动后访问 http://localhost:7860。

## 测试

```bash
pytest tests/
```

## Docker 环境变量

- `DEEPSEEK_API_KEY`：DeepSeek API Key。
- `BASE_URL`：LLM API Base URL，默认 `https://api.deepseek.com/v1`。
- `MODEL`：模型名称，默认 `deepseek-v4-pro`。
