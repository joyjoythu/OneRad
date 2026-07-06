# Task 1: 创建项目基础结构与 requirements.txt

### Task 1: 创建项目基础结构与 requirements.txt

**Files:**
- Create: `requirements.txt`
- Create: `main.py`
- Create: `app/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
# Core
numpy>=1.24.0
pandas>=2.0.0
scikit-learn>=1.3.0
scipy>=1.10.0

# Medical imaging
SimpleITK>=2.3.0
pyradiomics>=3.0.1

# LLM
openai>=1.0.0
langchain>=0.2.0
langchain-openai>=0.1.0

# Report & UI
python-docx>=1.1.0
gradio>=4.0.0

# Utils
openpyxl>=3.1.0
h5py>=3.8.0
```

- [ ] **Step 2: 创建 main.py CLI 入口骨架**

```python
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--clinical", required=True)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="", help="逗号分隔的协变量列名")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    args = parser.parse_args()

    # Task 18 将在此处实例化 Orchestrator 并运行


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 创建 app/__init__.py 和 tests/conftest.py**

`app/__init__.py` 可为空。

`tests/conftest.py`：
```python
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)
```

- [ ] **Step 4: 运行基础导入测试**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt main.py app/__init__.py tests/conftest.py
git commit -m "chore: project scaffold and requirements"
```

---
