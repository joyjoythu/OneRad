# Matching Agent 实现方案

## 1. 职责定位与上下文

Matching Agent 位于流水线第三阶段，承接 Discovery Agent 产出的影像-掩膜配对列表，以及 Clinical Agent 解析出的临床表格（含 ID 列、标签列、特征列），核心职责是：**将影像文件名中提取出的患者 ID 与临床表格中的 ID 列进行对齐，生成可用于后续 QC 与特征提取的统一数据表**。

**流水线位置：**
```
Discovery → Clinical → [Matching] → QC → Feature → Merge → Analysis → Report
```

**负责人：** 同学 B（`clinical.py` 中与 Clinical Agent 同文件，但逻辑独立）

---

## 2. 输入输出契约（与上下游 Agent 的接口）

### 2.1 上游输入

#### 来自 Discovery Agent
```python
# 类型别名：影像-掩膜配对列表
ImageMaskPair = Dict[str, str]  # {"patient_id": str, "image_path": str, "mask_path": str}
DiscoveryOutput = List[ImageMaskPair]
```

示例：
```python
discovery_output = [
    {"patient_id": "P001", "image_path": "/data/P001_CT.nii.gz", "mask_path": "/data/P001_mask.nii.gz"},
    {"patient_id": "P002", "image_path": "/data/P002_CT.nii.gz", "mask_path": "/data/P002_mask.nii.gz"},
    {"patient_id": "P003", "image_path": "/data/P003_CT.nii.gz", "mask_path": "/data/P003_mask.nii.gz"},
]
```

#### 来自 Clinical Agent
```python
# 类型别名：临床表格解析结果
ClinicalOutput = Dict[str, Any]
# 内部必须包含：
#   - "df": pd.DataFrame          # 原始临床表格（已读取）
#   - "id_col": str               # ID 列的列名，如 "PatientID"
#   - "label_col": str            # Label 列的列名，如 "OS" 或 "Label"
#   - "feature_cols": List[str]   # 临床特征列名列表
#   - "has_time_event": bool      # 是否有 Time/Event 列（生存分析标志）
#   - "time_col": Optional[str]   # Time 列名（生存分析时存在）
#   - "event_col": Optional[str]  # Event 列名（生存分析时存在）
```

示例：
```python
clinical_output = {
    "df": pd.DataFrame({
        "PatientID": ["P001", "P002", "P004", "P005"],
        "Age": [55, 62, 48, 71],
        "Sex": ["F", "M", "F", "M"],
        "Label": [1, 0, 1, 0],
    }),
    "id_col": "PatientID",
    "label_col": "Label",
    "feature_cols": ["Age", "Sex"],
    "has_time_event": False,
    "time_col": None,
    "event_col": None,
}
```

### 2.2 下游输出

```python
# 类型别名：Matching Agent 输出
MatchingOutput = Dict[str, Any]
# 内部包含：
#   - "matched_df": pd.DataFrame      # 匹配成功的行（影像路径 + 掩膜路径 + 临床数据）
#   - "unmatched_image_ids": List[str]   # 有影像但无临床数据的 ID 列表
#   - "unmatched_clinical_ids": List[str] # 有临床数据但无影像的 ID 列表
#   - "match_stats": Dict[str, int]    # 匹配统计信息
#   - "match_method": str              # 匹配方式："exact" 或 "fuzzy"
```

`matched_df` 的列结构：
```python
# 必须包含以下列（顺序不重要）：
#   - "patient_id": str              # 患者 ID（标准化后的字符串）
#   - "image_path": str              # 影像文件绝对路径
#   - "mask_path": str               # 掩膜文件绝对路径
#   - 临床表格中的其他所有列（Age, Sex, Label 等）
```

示例：
```python
matching_output = {
    "matched_df": pd.DataFrame({
        "patient_id": ["P001", "P002"],
        "image_path": ["/data/P001_CT.nii.gz", "/data/P002_CT.nii.gz"],
        "mask_path": ["/data/P001_mask.nii.gz", "/data/P002_mask.nii.gz"],
        "Age": [55, 62],
        "Sex": ["F", "M"],
        "Label": [1, 0],
    }),
    "unmatched_image_ids": ["P003"],       # 有影像，但临床表里没有
    "unmatched_clinical_ids": ["P004", "P005"],  # 临床表里有，但无影像
    "match_stats": {
        "total_images": 3,
        "total_clinical": 4,
        "matched": 2,
        "unmatched_images": 1,
        "unmatched_clinical": 2,
    },
    "match_method": "exact",
}
```

### 2.3 全局状态传递

Orchestrator 维护的 `state` dict 中，Matching Agent 阶段涉及以下 key：

```python
# 进入 Matching 阶段时，state 中已有：
state = {
    "discovery": {
        "pairs": [...],           # DiscoveryOutput
        "unpaired_files": [...],
    },
    "clinical": {
        "df": pd.DataFrame,
        "id_col": str,
        "label_col": str,
        "feature_cols": List[str],
        # ... 其他 clinical 输出
    },
    # Matching 阶段将写入：
    "matching": {
        "matched_df": pd.DataFrame,
        "unmatched_image_ids": List[str],
        "unmatched_clinical_ids": List[str],
        "match_stats": Dict[str, int],
        "match_method": str,
    },
}
```

---

## 3. 核心模块设计

### 3.1 文件位置与模块结构

```
app/
└── clinical.py          # Clinical Agent + Matching Agent 同文件
```

Matching Agent 相关代码集中在 `clinical.py` 下半部分，对外暴露主入口函数 `run_matching()`。

### 3.2 类与函数定义

#### 3.2.1 异常类定义

```python
# clinical.py

class MatchingError(Exception):
    """Matching Agent 基础异常"""
    pass

class IDEmptyError(MatchingError):
    """ID 列或影像 ID 列表为空"""
    pass

class NoMatchError(MatchingError):
    """精确匹配与模糊匹配均未产生任何匹配"""
    pass

class AllMatchUnqualifiedError(MatchingError):
    """模糊匹配全部低于相似度阈值，视为无有效匹配"""
    pass
```

#### 3.2.2 核心数据类

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
import pandas as pd

@dataclass
class MatchResult:
    """Matching Agent 的完整输出数据类"""
    matched_df: pd.DataFrame                          # 匹配成功的数据框
    unmatched_image_ids: List[str] = field(default_factory=list)
    unmatched_clinical_ids: List[str] = field(default_factory=list)
    match_stats: Dict[str, int] = field(default_factory=dict)
    match_method: str = "exact"                       # "exact" 或 "fuzzy"
    fuzzy_threshold: float = 0.8                      # 模糊匹配阈值（仅 fuzzy 时有效）
    warnings: List[str] = field(default_factory=list) # 非致命警告信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为 Orchestrator state 所需的字典格式"""
        return {
            "matched_df": self.matched_df,
            "unmatched_image_ids": self.unmatched_image_ids,
            "unmatched_clinical_ids": self.unmatched_clinical_ids,
            "match_stats": self.match_stats,
            "match_method": self.match_method,
            "fuzzy_threshold": self.fuzzy_threshold,
            "warnings": self.warnings,
        }
```

#### 3.2.3 主入口函数

```python
def run_matching(
    discovery_pairs: List[Dict[str, str]],
    clinical_df: pd.DataFrame,
    id_col: str,
    fuzzy_threshold: float = 0.8,
    enable_fuzzy: bool = True,
) -> MatchResult:
    """
    Matching Agent 主入口函数。
    
    参数
    ----------
    discovery_pairs : List[Dict[str, str]]
        Discovery Agent 输出的影像-掩膜配对列表，每个 dict 必须包含 "patient_id" 键。
    clinical_df : pd.DataFrame
        Clinical Agent 输出的临床表格 DataFrame，必须包含 id_col 指定的列。
    id_col : str
        临床表格中患者 ID 列的列名。
    fuzzy_threshold : float, default=0.8
        模糊匹配相似度阈值（0.0 ~ 1.0），低于此值的匹配将被丢弃。
    enable_fuzzy : bool, default=True
        是否启用模糊匹配兜底。若为 False，仅做精确匹配。
    
    返回
    -------
    MatchResult
        包含匹配结果、未匹配 ID、统计信息和警告的完整结果对象。
    
    异常
    ------
    IDEmptyError
        影像 ID 列表或临床 ID 列存在空值/空集合。
    NoMatchError
        没有任何 ID 能够匹配（精确和模糊均失败）。
    AllMatchUnqualifiedError
        模糊匹配有候选但全部低于阈值。
    
    示例
    -------
    >>> result = run_matching(
    ...     discovery_pairs=[{"patient_id": "P001", "image_path": "...", "mask_path": "..."}],
    ...     clinical_df=df,
    ...     id_col="PatientID",
    ... )
    >>> print(result.match_stats)
    {"total_images": 1, "total_clinical": 100, "matched": 1, ...}
    """
```

#### 3.2.4 内部工具函数

```python
def _extract_image_ids(pairs: List[Dict[str, str]]) -> Set[str]:
    """
    从 Discovery 配对列表中提取所有 patient_id，去重。
    
    参数
    ----------
    pairs : List[Dict[str, str]]
        影像-掩膜配对列表。
    
    返回
    -------
    Set[str]
        去重后的患者 ID 集合。
    """


def _normalize_id(id_str: str) -> str:
    """
    ID 标准化：去除首尾空白、统一大小写、移除常见文件扩展名残留。
    
    标准化规则（按顺序执行）：
    1. strip() 去除首尾空白
    2. 统一转为小写（或保持原样，视约定；推荐保持原样但比较时忽略大小写）
    3. 移除末尾常见扩展名如 .nii, .nii.gz, .dcm, .mha（如有混入）
    
    参数
    ----------
    id_str : str
        原始 ID 字符串。
    
    返回
    -------
    str
        标准化后的 ID 字符串。
    
    示例
    -------
    >>> _normalize_id(" P001 ")
    "P001"
    >>> _normalize_id("p001.nii.gz")
    "p001"
    """


def _exact_match(
    image_ids: Set[str],
    clinical_ids: Set[str],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    精确匹配：在标准化后的 ID 集合上做交集运算。
    
    匹配策略：
    - 大小写不敏感比较（都转小写后再比较）
    - 保留原始大小写格式以 clinical_df 中的为准（或取影像中的，约定一致即可）
    
    参数
    ----------
    image_ids : Set[str]
        影像侧标准化后的 ID 集合。
    clinical_ids : Set[str]
        临床侧标准化后的 ID 集合。
    
    返回
    -------
    Tuple[Set[str], Set[str], Set[str]]
        (matched_ids, unmatched_image_ids, unmatched_clinical_ids)
        三个集合中的元素均为标准化后的 ID 字符串。
    """


def _fuzzy_match(
    unmatched_images: Set[str],
    unmatched_clinical: Set[str],
    threshold: float = 0.8,
) -> Tuple[Dict[str, str], List[str], List[str], List[str]]:
    """
    模糊匹配：对精确匹配未成功的 ID 使用 difflib.SequenceMatcher 进行相似度匹配。
    
    算法细节：
    1. 对每一个未匹配的影像 ID，与所有未匹配的临床 ID 计算 SequenceMatcher.ratio()
    2. 取 ratio 最高的临床 ID 作为候选
    3. 若 ratio >= threshold，则视为匹配成功
    4. 采用贪心策略：一旦某个临床 ID 被匹配，即从候选池中移除（避免一对多）
    
    参数
    ----------
    unmatched_images : Set[str]
        精确匹配后仍未匹配的影像 ID 集合。
    unmatched_clinical : Set[str]
        精确匹配后仍未匹配的临床 ID 集合。
    threshold : float, default=0.8
        相似度阈值，0.0 ~ 1.0。
    
    返回
    -------
    Tuple[Dict[str, str], List[str], List[str], List[str]]
        - fuzzy_map: Dict[影像ID, 临床ID] 匹配映射表
        - remaining_images: 模糊匹配后仍无匹配的影像 ID 列表
        - remaining_clinical: 模糊匹配后仍无匹配的临床 ID 列表
        - low_confidence_pairs: 低于阈值但被记录的候选（用于日志/警告）
    """


def _build_matched_dataframe(
    pairs: List[Dict[str, str]],
    clinical_df: pd.DataFrame,
    id_col: str,
    matched_ids: Set[str],
    fuzzy_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    根据匹配结果构建最终 DataFrame：将影像路径、掩膜路径与临床数据拼接。
    
    参数
    ----------
    pairs : List[Dict[str, str]]
        原始 Discovery 配对列表。
    clinical_df : pd.DataFrame
        原始临床表格。
    id_col : str
        临床表格中的 ID 列名。
    matched_ids : Set[str]
        所有匹配成功的标准化 ID 集合（精确 + 模糊）。
    fuzzy_map : Optional[Dict[str, str]], default=None
        模糊匹配映射表 {影像ID: 临床ID}，若为 None 表示无模糊匹配。
    
    返回
    -------
    pd.DataFrame
        拼接后的 DataFrame，列包含 patient_id, image_path, mask_path 及所有临床列。
    """


def _validate_id_column(clinical_df: pd.DataFrame, id_col: str) -> None:
    """
    验证临床表格的 ID 列是否合法：列存在、非全空、类型可转字符串。
    
    参数
    ----------
    clinical_df : pd.DataFrame
        临床表格。
    id_col : str
        ID 列名。
    
    异常
    ------
    ValueError
        列不存在、全为空值、或全部为空字符串。
    """
```

---

## 4. 核心算法实现（可直接照抄）

### 4.1 完整实现代码

```python
# clinical.py 中 Matching Agent 部分

import difflib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd


# ─── 异常类 ───────────────────────────────────────────

class MatchingError(Exception):
    """Matching Agent 基础异常"""
    pass


class IDEmptyError(MatchingError):
    """ID 列或影像 ID 列表为空"""
    pass


class NoMatchError(MatchingError):
    """精确匹配与模糊匹配均未产生任何匹配"""
    pass


class AllMatchUnqualifiedError(MatchingError):
    """模糊匹配全部低于相似度阈值，视为无有效匹配"""
    pass


# ─── 数据类 ───────────────────────────────────────────

from dataclasses import dataclass, field

@dataclass
class MatchResult:
    """Matching Agent 的完整输出数据类"""
    matched_df: pd.DataFrame
    unmatched_image_ids: List[str] = field(default_factory=list)
    unmatched_clinical_ids: List[str] = field(default_factory=list)
    match_stats: Dict[str, int] = field(default_factory=dict)
    match_method: str = "exact"
    fuzzy_threshold: float = 0.8
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched_df": self.matched_df,
            "unmatched_image_ids": self.unmatched_image_ids,
            "unmatched_clinical_ids": self.unmatched_clinical_ids,
            "match_stats": self.match_stats,
            "match_method": self.match_method,
            "fuzzy_threshold": self.fuzzy_threshold,
            "warnings": self.warnings,
        }


# ─── 内部工具函数 ─────────────────────────────────────

def _normalize_id(id_str: str) -> str:
    """ID 标准化：去除空白、统一小写、移除常见扩展名残留。"""
    if not isinstance(id_str, str):
        id_str = str(id_str)
    s = id_str.strip()
    # 移除末尾常见医学影像扩展名（不区分大小写）
    s = re.sub(r"\.(nii\.gz|nii|dcm|mha|mhd|raw|nrrd)$", "", s, flags=re.IGNORECASE)
    return s.lower()


def _extract_image_ids(pairs: List[Dict[str, str]]) -> Set[str]:
    """从 Discovery 配对列表中提取标准化后的 patient_id 集合。"""
    ids = set()
    for p in pairs:
        pid = p.get("patient_id")
        if pid is None:
            raise MatchingError("Discovery pair 缺少 'patient_id' 键")
        ids.add(_normalize_id(pid))
    return ids


def _validate_id_column(clinical_df: pd.DataFrame, id_col: str) -> None:
    """验证 ID 列合法性。"""
    if id_col not in clinical_df.columns:
        raise ValueError(f"ID 列 '{id_col}' 不存在于临床表格中")
    col = clinical_df[id_col]
    if col.isna().all():
        raise ValueError(f"ID 列 '{id_col}' 全部为缺失值")
    # 检查是否全部为空字符串（转字符串后）
    str_col = col.astype(str).str.strip()
    if (str_col == "").all():
        raise ValueError(f"ID 列 '{id_col}' 全部为空字符串")


def _exact_match(
    image_ids: Set[str],
    clinical_ids: Set[str],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    大小写不敏感的精确匹配。
    返回: (matched, unmatched_images, unmatched_clinical)
    """
    # 注意：入参已经是标准化（小写）后的集合
    matched = image_ids & clinical_ids
    unmatched_images = image_ids - matched
    unmatched_clinical = clinical_ids - matched
    return matched, unmatched_images, unmatched_clinical


def _fuzzy_match(
    unmatched_images: Set[str],
    unmatched_clinical: Set[str],
    threshold: float = 0.8,
) -> Tuple[Dict[str, str], List[str], List[str], List[str]]:
    """
    使用 difflib.SequenceMatcher 进行贪心模糊匹配。
    返回: (fuzzy_map, remaining_images, remaining_clinical, low_confidence)
    """
    fuzzy_map: Dict[str, str] = {}
    remaining_images = list(unmatched_images)
    remaining_clinical = list(unmatched_clinical)
    low_confidence: List[str] = []

    # 将 clinical 转为可修改列表
    available_clinical = list(unmatched_clinical)

    for img_id in sorted(unmatched_images):
        best_ratio = 0.0
        best_clinical_id = None

        for cli_id in available_clinical:
            # SequenceMatcher 要求可哈希序列，字符串直接可用
            ratio = difflib.SequenceMatcher(None, img_id, cli_id).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_clinical_id = cli_id

        if best_clinical_id is not None and best_ratio >= threshold:
            fuzzy_map[img_id] = best_clinical_id
            available_clinical.remove(best_clinical_id)
            remaining_images.remove(img_id)
            remaining_clinical.remove(best_clinical_id)
        elif best_clinical_id is not None:
            # 有最佳候选但低于阈值，记录到警告
            low_confidence.append(
                f"'{img_id}' ↔ '{best_clinical_id}' (ratio={best_ratio:.3f})"
            )

    return fuzzy_map, remaining_images, remaining_clinical, low_confidence


def _build_matched_dataframe(
    pairs: List[Dict[str, str]],
    clinical_df: pd.DataFrame,
    id_col: str,
    matched_ids: Set[str],
    fuzzy_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    构建匹配后的 DataFrame，将影像路径与临床数据合并。
    """
    # 建立 标准化ID -> 原始pair 的映射
    norm_to_pair: Dict[str, Dict[str, str]] = {}
    for p in pairs:
        norm_id = _normalize_id(p["patient_id"])
        norm_to_pair[norm_id] = p

    # 建立 标准化临床ID -> 原始临床ID 的映射（保留原始大小写/格式）
    clinical_df = clinical_df.copy()
    clinical_df["__norm_id__"] = clinical_df[id_col].astype(str).apply(_normalize_id)
    norm_to_clinical_id = dict(zip(clinical_df["__norm_id__"], clinical_df[id_col]))

    rows: List[Dict[str, Any]] = []

    for norm_id in matched_ids:
        pair = norm_to_pair.get(norm_id)
        if pair is None:
            continue  # 理论上不应发生

        # 确定对应临床行的 ID
        if fuzzy_map and norm_id in fuzzy_map:
            # 模糊匹配：用映射后的临床 ID（已标准化）反查原始 ID
            target_norm_id = _normalize_id(fuzzy_map[norm_id])
        else:
            target_norm_id = norm_id

        original_clinical_id = norm_to_clinical_id.get(target_norm_id)
        if original_clinical_id is None:
            continue

        # 筛选临床行
        clinical_row = clinical_df[clinical_df[id_col] == original_clinical_id]
        if clinical_row.empty:
            continue

        # 构造合并行
        row_dict = clinical_row.iloc[0].to_dict()
        row_dict.pop("__norm_id__", None)  # 删除辅助列
        row_dict["patient_id"] = pair["patient_id"]  # 保留影像侧原始 ID
        row_dict["image_path"] = pair["image_path"]
        row_dict["mask_path"] = pair["mask_path"]
        rows.append(row_dict)

    if not rows:
        # 返回空 DataFrame，但保留预期列结构
        cols = ["patient_id", "image_path", "mask_path"] + [
            c for c in clinical_df.columns if c != "__norm_id__"
        ]
        return pd.DataFrame(columns=cols)

    return pd.DataFrame(rows)


# ─── 主入口函数 ───────────────────────────────────────

def run_matching(
    discovery_pairs: List[Dict[str, str]],
    clinical_df: pd.DataFrame,
    id_col: str,
    fuzzy_threshold: float = 0.8,
    enable_fuzzy: bool = True,
) -> MatchResult:
    """
    Matching Agent 主入口：精确匹配 + 模糊匹配（可选），输出统一数据表。
    """
    warnings: List[str] = []

    # ── Step 1: 前置校验 ──────────────────────────────
    if not discovery_pairs:
        raise IDEmptyError("Discovery pairs 为空列表，无任何影像数据")

    if clinical_df is None or clinical_df.empty:
        raise IDEmptyError("临床表格为空")

    _validate_id_column(clinical_df, id_col)

    # ── Step 2: 提取标准化 ID ──────────────────────────
    image_ids = _extract_image_ids(discovery_pairs)
    clinical_ids = set(clinical_df[id_col].astype(str).apply(_normalize_id))

    if not image_ids:
        raise IDEmptyError("影像 ID 列表为空（所有 pair 缺少 patient_id）")
    if not clinical_ids:
        raise IDEmptyError(f"临床 ID 列 '{id_col}' 提取后为空")

    # ── Step 3: 精确匹配 ──────────────────────────────
    matched_exact, unmatched_img, unmatched_cli = _exact_match(
        image_ids, clinical_ids
    )

    match_method = "exact"
    fuzzy_map: Optional[Dict[str, str]] = None

    # ── Step 4: 模糊匹配兜底 ──────────────────────────
    if enable_fuzzy and unmatched_img and unmatched_cli:
        fuzzy_map, rem_img, rem_cli, low_conf = _fuzzy_match(
            unmatched_img, unmatched_cli, threshold=fuzzy_threshold
        )

        if fuzzy_map:
            match_method = "fuzzy"
            matched_exact = matched_exact | set(fuzzy_map.keys())
            unmatched_img = set(rem_img)
            unmatched_cli = set(rem_cli)
            warnings.append(
                f"启用模糊匹配：成功匹配 {len(fuzzy_map)} 对，"
                f"阈值={fuzzy_threshold}"
            )
        else:
            warnings.append(
                f"模糊匹配未命中：剩余 {len(unmatched_img)} 个影像 ID 与 "
                f"{len(unmatched_cli)} 个临床 ID 无法对应"
            )

        if low_conf:
            warnings.append(
                "以下配对相似度低于阈值，已忽略：\n  "
                + "\n  ".join(low_conf)
            )

    # ── Step 5: 致命异常判断 ──────────────────────────
    if not matched_exact:
        raise NoMatchError(
            f"无任何 ID 匹配成功。影像 ID 数={len(image_ids)}，"
            f"临床 ID 数={len(clinical_ids)}。请检查 ID 命名是否一致。"
        )

    # 样本量不足警告（<30 时由 Orchestrator 决定是否中断）
    if len(matched_exact) < 30:
        warnings.append(
            f"⚠️ 匹配成功样本量仅 {len(matched_exact)} 例，"
            f"低于推荐阈值 30，后续分析可能不稳定。"
        )

    # ── Step 6: 构建结果 DataFrame ────────────────────
    matched_df = _build_matched_dataframe(
        pairs=discovery_pairs,
        clinical_df=clinical_df,
        id_col=id_col,
        matched_ids=matched_exact,
        fuzzy_map=fuzzy_map,
    )

    # 去重：同一个 patient_id 可能对应多行临床记录（异常情况）
    original_len = len(matched_df)
    matched_df = matched_df.drop_duplicates(subset=["patient_id"], keep="first")
    if len(matched_df) < original_len:
        warnings.append(
            f"发现 {original_len - len(matched_df)} 个重复的 patient_id 行，"
            f"已自动去重保留第一条。"
        )

    # ── Step 7: 组装统计信息 ──────────────────────────
    stats = {
        "total_images": len(discovery_pairs),
        "total_clinical": len(clinical_df),
        "matched": len(matched_df),
        "unmatched_images": len(unmatched_img),
        "unmatched_clinical": len(unmatched_cli),
    }

    result = MatchResult(
        matched_df=matched_df,
        unmatched_image_ids=sorted(unmatched_img),
        unmatched_clinical_ids=sorted(unmatched_cli),
        match_stats=stats,
        match_method=match_method,
        fuzzy_threshold=fuzzy_threshold if match_method == "fuzzy" else 0.0,
        warnings=warnings,
    )

    return result
```

---

## 5. 异常处理逻辑

### 5.1 异常矩阵

| 异常场景 | 检测位置 | 抛出异常 | Orchestrator 处理建议 |
|----------|----------|----------|----------------------|
| Discovery pairs 为空 | Step 1 | `IDEmptyError` | 中断，提示用户检查影像文件夹 |
| 临床表格为空 | Step 1 | `IDEmptyError` | 中断，提示用户检查临床文件 |
| ID 列不存在 | Step 1 | `ValueError` | 中断，提示 Clinical Agent 输出异常 |
| ID 列全空 | Step 1 | `ValueError` | 中断，提示用户检查表格内容 |
| 影像 ID 集合为空 | Step 2 | `IDEmptyError` | 中断，提示 Discovery Agent 未提取到 ID |
| 临床 ID 集合为空 | Step 2 | `IDEmptyError` | 中断，提示 Clinical Agent 未识别 ID 列 |
| **无任何 ID 匹配** | Step 5 | `NoMatchError` | **中断**，用户可选：跳过/终止/重命名后重试 |
| 模糊匹配全部低于阈值 | Step 4 | `AllMatchUnqualifiedError` | 同 NoMatchError |
| 匹配成功但样本量 < 30 | Step 5 | 仅警告 | Orchestrator 弹窗提示，用户选继续/终止 |
| 存在重复 patient_id | Step 6 | 仅警告 + 自动去重 | 日志记录，继续执行 |

### 5.2 Orchestrator 集成示例

```python
# orchestrator.py 中 Matching 阶段调用示例

from clinical import run_matching, MatchingError, NoMatchError, IDEmptyError

def stage_matching(state: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Orchestrator 调用 Matching Agent 的包装函数。
    
    返回
    -------
    (success: bool, message: str, updated_state: dict)
    """
    try:
        discovery_pairs = state["discovery"]["pairs"]
        clinical_df = state["clinical"]["df"]
        id_col = state["clinical"]["id_col"]

        result = run_matching(
            discovery_pairs=discovery_pairs,
            clinical_df=clinical_df,
            id_col=id_col,
            fuzzy_threshold=0.8,
            enable_fuzzy=True,
        )

        # 写入 state
        state["matching"] = result.to_dict()

        # 发出 SSE 事件
        msg = (
            f"Matching 完成：{result.match_stats['matched']}/"
            f"{result.match_stats['total_images']} 例匹配成功，"
            f"方式={result.match_method}"
        )
        if result.warnings:
            msg += "\n警告：" + "\n".join(result.warnings)

        return True, msg, state

    except (IDEmptyError, NoMatchError, MatchingError) as e:
        # Orchestrator 捕获后进入中断状态，等待用户决策
        return False, f"Matching 失败：{str(e)}", state
    except Exception as e:
        # 兜底异常
        return False, f"Matching 未知错误：{str(e)}", state
```

---

## 6. difflib 模糊匹配算法详解

### 6.1 为什么用 difflib

- **零依赖**：Python 标准库，无需 pip 安装
- **适合短字符串**：患者 ID 通常为 3~20 字符，`SequenceMatcher` 在此长度表现稳定
- **直观可控**：`ratio()` 返回 0.0~1.0，阈值易调

### 6.2 贪心匹配策略

```python
# 核心逻辑（已在 _fuzzy_match 中实现）

for img_id in unmatched_images:
    best_ratio = 0.0
    best_clinical_id = None
    
    for cli_id in available_clinical:  # available 会动态减少
        ratio = difflib.SequenceMatcher(None, img_id, cli_id).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_clinical_id = cli_id
    
    if best_ratio >= threshold:
        fuzzy_map[img_id] = best_clinical_id
        available_clinical.remove(best_clinical_id)  # 贪心：已匹配的临床ID不再参与后续匹配
```

**策略说明：**
- 贪心（Greedy）策略保证每个临床 ID 最多被匹配一次，避免数据泄露
- 若两个影像 ID 都与同一个临床 ID 高相似，先遍历到的会"抢占"，后者只能匹配次优
- 此策略在医学数据场景可接受，因为 ID 命名通常有统一规范，不匹配是少数例外

### 6.3 阈值选择建议

| 阈值 | 适用场景 | 风险 |
|------|----------|------|
| 0.95 | ID 仅有微小差异（如大小写、前导零） | 严格，可能漏掉真正的不一致 |
| **0.80** | **默认推荐**：允许一定拼写差异 | 平衡 |
| 0.60 | ID 命名规范差异大（如医院 A/B 不同编码） | 容易误匹配，需人工复核 |
| 0.50 以下 | 不推荐 | 误匹配风险过高 |

---

## 7. 单元测试用例

```python
# tests/test_matching.py

import pytest
import pandas as pd
from clinical import (
    run_matching,
    _normalize_id,
    _exact_match,
    _fuzzy_match,
    MatchingError,
    NoMatchError,
    IDEmptyError,
)


def test_normalize_id():
    assert _normalize_id(" P001 ") == "p001"
    assert _normalize_id("P001.nii.gz") == "p001"
    assert _normalize_id("P001.DCM") == "p001"


def test_exact_match_basic():
    img = {"p001", "p002", "p003"}
    cli = {"p001", "p002", "p004"}
    matched, un_img, un_cli = _exact_match(img, cli)
    assert matched == {"p001", "p002"}
    assert un_img == {"p003"}
    assert un_cli == {"p004"}


def test_fuzzy_match_typo():
    img = {"patient_001"}
    cli = {"patinet_001", "patient_002"}  # typo: patinet
    fuzzy_map, rem_img, rem_cli, _ = _fuzzy_match(img, cli, threshold=0.8)
    assert "patient_001" in fuzzy_map
    assert fuzzy_map["patient_001"] == "patinet_001"


def test_run_matching_success():
    pairs = [
        {"patient_id": "P001", "image_path": "/a.nii", "mask_path": "/a_mask.nii"},
        {"patient_id": "P002", "image_path": "/b.nii", "mask_path": "/b_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [1, 0, 1],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result.match_stats["matched"] == 2
    assert result.match_method == "exact"
    assert "P003" in result.unmatched_clinical_ids


def test_run_matching_no_match():
    pairs = [{"patient_id": "A001", "image_path": "/a.nii", "mask_path": "/a_mask.nii"}]
    df = pd.DataFrame({"PatientID": ["B001"], "Label": [1]})
    with pytest.raises(NoMatchError):
        run_matching(pairs, df, id_col="PatientID")


def test_run_matching_empty_pairs():
    with pytest.raises(IDEmptyError):
        run_matching([], pd.DataFrame(), id_col="ID")
```

---

## 8. 与 Clinical Agent 的代码组织

`clinical.py` 文件内建议按以下顺序组织：

```python
# clinical.py

# ── 导入 ──
import pandas as pd
# ...

# ═══════════════════════════════════════════════════════
# 第一部分：Clinical Agent
# ═══════════════════════════════════════════════════════

def run_clinical(csv_path: str, ...) -> Dict[str, Any]:
    """Clinical Agent 主入口"""
    ...

# ... Clinical Agent 内部函数 ...


# ═══════════════════════════════════════════════════════
# 第二部分：Matching Agent
# ═══════════════════════════════════════════════════════

class MatchingError(Exception):
    ...

# ... Matching Agent 全部代码 ...

def run_matching(...) -> MatchResult:
    ...
```

**铁律：**
- Clinical Agent 不调用 Matching Agent，Matching Agent 不调用 Clinical Agent
- 两者通过 Orchestrator 的顺序调度串联
- 共享同一文件仅为减少低年级同学维护文件数，逻辑完全解耦

---

## 9. 关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 大小写敏感？ | **不敏感**（统一转小写比较） | Windows 与 Linux 文件系统大小写行为不一致 |
| 保留哪侧 ID 格式？ | **影像侧原始格式** | 后续 Feature Agent 按 patient_id 查找文件路径 |
| fuzzy 默认开启？ | **是** | 医院数据常有不一致（如 `P001` vs `P-001`） |
| fuzzy 阈值 | **0.8** | 经验值，可覆盖大小写+分隔符差异，避免误匹配 |
| 重复 patient_id 处理 | **自动去重，保留第一条** | 数据质量问题不应阻塞流水线 |
| 一对多匹配 | **禁止**（贪心移除） | 避免数据泄露，一个患者只能对应一条临床记录 |
| 样本量 < 30 | **仅警告，不阻断** | 阻断权交给 Orchestrator，用户可选跳过/终止 |

---

## 10. 交付 checklist

- [ ] `clinical.py` 中 Matching Agent 代码完整可运行
- [ ] `_normalize_id` 覆盖常见扩展名残留
- [ ] `_exact_match` 大小写不敏感
- [ ] `_fuzzy_match` 使用 `difflib.SequenceMatcher`，贪心策略，阈值可配
- [ ] `run_matching` 包含完整前置校验和异常抛出
- [ ] 输出 `MatchResult` 包含 `matched_df`、`unmatched_*`、`stats`、`method`、`warnings`
- [ ] Orchestrator 可捕获 `MatchingError` / `NoMatchError` / `IDEmptyError`
- [ ] 单元测试覆盖：正常匹配、无匹配、空输入、模糊匹配、大小写差异
- [ ] 代码注释为中英双语，关键逻辑有中文说明

---

*文档版本：v1.0*  
*对应开发计划版本：开发计划.md（完整版）*  
*负责人：同学 B（在负责人 Code Review 后执行）*
