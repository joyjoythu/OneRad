# Task 12: 实现 metrics.py

### Task 12: 实现 metrics.py

**Files:**
- Create: `app/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_metrics.py`:
```python
import numpy as np
from app.metrics import calculate_metrics


def test_calculate_metrics():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 1.0
    assert m.accuracy == 1.0
```

- [ ] **Step 2: 复制 calculate_metrics 到 app/metrics.py**

`app/metrics.py`:
```python
from dataclasses import dataclass
from typing import Optional
import numpy as np
from sklearn import metrics


@dataclass
class MetricsResult:
    accuracy: float = 0.0
    sensitivity: float = 0.0
    specificity: float = 0.0
    auc: float = 0.0
    best_threshold: float = 0.5
    tp: int = 0
    tn: int = 0
    fn: int = 0
    fp: int = 0


def calculate_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: Optional[float] = None) -> MetricsResult:
    result = MetricsResult()

    if len(np.unique(y_true)) < 2:
        result.auc = 0.0
    else:
        result.auc = metrics.roc_auc_score(y_true, y_prob)

    fpr, tpr, thresholds = metrics.roc_curve(y_true, y_prob)
    youden_index = tpr + (1 - fpr)
    result.best_threshold = thresholds[np.argmax(youden_index)]

    if result.best_threshold > 1:
        result.best_threshold = 0.5
    if threshold is not None:
        result.best_threshold = threshold

    y_pred = (y_prob >= result.best_threshold).astype(int)

    result.tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    result.tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    result.fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    result.fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    result.sensitivity = result.tp / (result.tp + result.fn + 1e-16)
    result.specificity = result.tn / (result.tn + result.fp + 1e-16)
    result.accuracy = (result.tp + result.tn) / (result.tp + result.tn + result.fp + result.fn + 1e-16)

    return result
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/metrics.py tests/test_metrics.py
git commit -m "feat: add calculate_metrics from existing classify code"
```

---
