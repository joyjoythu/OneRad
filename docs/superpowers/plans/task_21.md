# Task 21: 异常处理与日志增强

### Task 21: 异常处理与日志增强

**Files:**
- Modify: 各 Agent 文件
- Modify: `main.py`

- [ ] **Step 1: 统一日志格式**

在各 Agent 中添加：
```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: main.py 配置日志**

```python
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
```

- [ ] **Step 3: 测试并提交**

```bash
git add app/*.py main.py
git commit -m "chore: unify logging across agents"
```

---
