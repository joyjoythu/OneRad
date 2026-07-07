# Feature Agent 实现方案

## 一、职责定位

Feature Agent 负责调用 **PyRadiomics** 从配对的影像文件与 mask 中提取影像组学（Radiomics）特征，并按 **CT / MRI** 模态自动推断最优参数配置，输出可用于下游 Analysis Agent 的特征矩阵。

**在流水线中的位置：**

```
Discovery -> Clinical -> Matching -> QC -> Feature -> Merge -> Analysis -> Report
                                      ↑        ↓
                                    QC Agent   Feature Agent
```

- **上游输入：** QC Agent 输出的 `pairs` 列表（每对包含 image_path, mask_path, patient_id, modality）。
- **下游输出：** `features_df`（pandas DataFrame，行=患者，列=影像组学特征）。

---

## 二、数据契约（与上下游接口）

### 2.1 上游输入（来自 QC Agent）

QC Agent 通过共享状态字典 `state` 传递以下数据结构：

```python
state["pairs"] = [
    {
        "patient_id": "P001",               # 患者 ID（字符串）
        "image_path": "/data/P001_ct.nii.gz",   # 影像文件绝对路径
        "mask_path": "/data/P001_mask.nii.gz",   # mask 文件绝对路径
        "modality": "CT",                    # 模态，枚举值: "CT" | "MRI" | "PET"
        "spacing": (1.0, 1.0, 1.0),          # QC 后统一 spacing（可选，用于日志）
    },
    # ...
]
```

**约束：**
- `image_path` 和 `mask_path` 指向的文件必须存在且可读。
- `modality` 字段在 Discovery Agent 阶段根据文件后缀名或 DICOM 标签推断，QC Agent 可修正。
- 如 QC Agent 未推断出 `modality`，默认按 `"CT"` 处理并记录 warning。

### 2.2 下游输出（供 Merge Agent 使用）

Feature Agent 向共享状态写入：

```python
state["features_df"] = pd.DataFrame(
    index=["P001", "P002", ...],          # 患者 ID 作为 index
    columns=["original_shape_VoxelVolume", "original_firstorder_Mean", ...],  # 特征名
    data=[[...], [...], ...]
)

state["feature_metadata"] = {
    "n_samples": 100,                     # 成功提取特征的患者数
    "n_features": 107,                    # 提取的特征维度（firstorder + shape + texture）
    "failed_ids": ["P003", "P007"],       # 提取失败的患者 ID 列表（可为空）
    "zero_variance_features": ["original_glcm_xxx", ...],  # 全零/零方差特征名（供 Analysis Agent 参考）
    "modality_stats": {"CT": 60, "MRI": 40},  # 各模态统计
    "settings_used": {...},               # 实际使用的 PyRadiomics settings dict
    "extraction_time_seconds": 45.3,      # 总耗时（含并行）
}
```

**关键约定：**
- `features_df` 的 `index` 必须是 `patient_id`（字符串），与 `state["pairs"]` 中的 `patient_id` 一一对应。
- `features_df` 不含任何临床信息列（Label、Age、Sex 等），这些由 Clinical Agent 提供，Merge Agent 负责拼接。
- 如个别患者提取失败，其行被排除，`failed_ids` 记录供 Orchestrator 做中断决策。

---

## 三、核心模块设计

### 3.1 模块结构

```
feature.py              # 主入口，FeatureAgent 类定义
├── FeatureAgent        # 主类，Orchestrator 直接调用
│   ├── run()           # 入口方法，接收 state，写入 state
│   ├── _build_settings()   # 按模态构建 PyRadiomics settings
│   ├── _extract_single()   # 单患者特征提取（核心）
│   └── _extract_parallel() # 多进程并行提取
└── feature_exceptions    # 自定义异常
    ├── FeatureExtractionError
    ├── AllZeroFeatureError
    └── ModalityUnknownError
```

### 3.2 FeatureAgent 类定义

```python
"""
feature.py
Feature Agent: 影像组学特征提取模块
"""

import os
import time
import logging
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

import pandas as pd
import numpy as np
import SimpleITK as sitk

# PyRadiomics
from radiomics import featureextractor

logger = logging.getLogger("AutoRadiomics.FeatureAgent")


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class FeatureExtractionError(Exception):
    """单患者特征提取失败时抛出，带 patient_id。"""
    def __init__(self, patient_id: str, reason: str):
        self.patient_id = patient_id
        self.reason = reason
        super().__init__(f"[{patient_id}] 特征提取失败: {reason}")


class AllZeroFeatureError(Exception):
    """当提取出的特征全为零或方差为零时抛出。"""
    pass


class ModalityUnknownError(Exception):
    """无法识别或支持模态时抛出。"""
    pass


# ---------------------------------------------------------------------------
# 数据类：单患者输入参数（用于多进程传递）
# ---------------------------------------------------------------------------

@dataclass
class ExtractionTask:
    """传递给工作进程的最小数据单元。"""
    patient_id: str
    image_path: str
    mask_path: str
    modality: str
    settings: Dict[str, Any]   # 已序列化的 PyRadiomics settings


# ---------------------------------------------------------------------------
# FeatureAgent 主类
# ---------------------------------------------------------------------------

class FeatureAgent:
    """
    Feature Agent：从配对影像+mask中提取影像组学特征。

    Usage:
        agent = FeatureAgent()
        agent.run(state)   # 直接操作共享 state dict
    """

    # PyRadiomics 默认 feature classes 开关
    # 我们只提取：firstorder + shape + glcm + glrlm + glszm + gldm + ngtdm
    # 不提取 shape2D（3D 数据）
    DEFAULT_ENABLED_FEATURES = {
        "firstorder": True,
        "shape": True,
        "glcm": True,
        "glrlm": True,
        "glszm": True,
        "gldm": True,
        "ngtdm": True,
        "shape2D": False,
    }

    def __init__(
        self,
        n_workers: Optional[int] = None,
        timeout_per_case: int = 300,
    ):
        """
        Args:
            n_workers: 并行进程数，None=CPU 核心数。
            timeout_per_case: 单患者超时时间（秒）。
        """
        self.n_workers = n_workers or max(1, mp.cpu_count() - 1)
        self.timeout_per_case = timeout_per_case

    # -----------------------------------------------------------------------
    # 公共入口
    # -----------------------------------------------------------------------

    def run(self, state: Dict[str, Any]) -> None:
        """
        Orchestrator 调用的主入口。

        Args:
            state: 共享状态字典，必须包含 state["pairs"]。

        Side Effects:
            向 state 写入:
                - state["features_df"]
                - state["feature_metadata"]
                - state["feature_agent_status"] = "success" | "partial" | "failed"
        """
        logger.info("FeatureAgent 开始执行...")
        t_start = time.time()

        pairs = state.get("pairs", [])
        if not pairs:
            raise FeatureExtractionError("N/A", "state['pairs'] 为空，无影像可处理")

        # 按模态分组，每组生成对应的 settings
        modality_groups = self._group_by_modality(pairs)
        logger.info(f"模态分组: { {k: len(v) for k, v in modality_groups.items()} }")

        # 构建提取任务列表
        tasks: List[ExtractionTask] = []
        for modality, group_pairs in modality_groups.items():
            settings = self._build_settings(modality)
            for p in group_pairs:
                tasks.append(ExtractionTask(
                    patient_id=p["patient_id"],
                    image_path=p["image_path"],
                    mask_path=p["mask_path"],
                    modality=modality,
                    settings=settings,
                ))

        # 执行提取（并行或串行）
        if len(tasks) == 1 or self.n_workers == 1:
            results = self._extract_sequential(tasks)
        else:
            results = self._extract_parallel(tasks)

        # 组装 DataFrame
        features_df, failed_ids, zero_variance_features = self._assemble_results(
            results, expected_ids=[p["patient_id"] for p in pairs]
        )

        # 后处理：移除零方差特征（否则 LASSO / CoxPH 会炸）
        if zero_variance_features:
            features_df = features_df.drop(columns=zero_variance_features)
            logger.warning(f"移除 {len(zero_variance_features)} 个零方差特征")

        # 元数据
        modality_stats = {}
        for m, group in modality_groups.items():
            modality_stats[m] = len(group)

        status = "success"
        if failed_ids:
            status = "partial" if len(failed_ids) < len(pairs) else "failed"

        state["features_df"] = features_df
        state["feature_metadata"] = {
            "n_samples": len(features_df),
            "n_features": len(features_df.columns),
            "failed_ids": failed_ids,
            "zero_variance_features": zero_variance_features,
            "modality_stats": modality_stats,
            "settings_used": self._build_settings(list(modality_groups.keys())[0]),  # 取首个作为记录
            "extraction_time_seconds": round(time.time() - t_start, 2),
        }
        state["feature_agent_status"] = status

        logger.info(
            f"FeatureAgent 完成: {len(features_df)}/{len(pairs)} 成功, "
            f"{len(features_df.columns)} 特征, 状态={status}"
        )

    # -----------------------------------------------------------------------
    # 模态分组
    # -----------------------------------------------------------------------

    def _group_by_modality(self, pairs: List[Dict]) -> Dict[str, List[Dict]]:
        """将 pairs 按 modality 分组。"""
        groups: Dict[str, List[Dict]] = {}
        for p in pairs:
            mod = (p.get("modality") or "CT").upper()
            if mod not in groups:
                groups[mod] = []
            groups[mod].append(p)
        return groups

    # -----------------------------------------------------------------------
    # 参数配置：按 CT/MRI 自动推断
    # -----------------------------------------------------------------------

    def _build_settings(self, modality: str) -> Dict[str, Any]:
        """
        根据模态构建 PyRadiomics 的 settings 字典。

        核心差异：
        - CT：有物理意义的 Hounsfield Unit（HU），无需归一化，直接使用原始灰度。
        - MRI：灰度值无绝对物理意义，必须做归一化（z-score）+ 离散化（binWidth）。

        Args:
            modality: "CT" | "MRI" | "PET"

        Returns:
            PyRadiomics settings 字典，可直接传入 featureextractor.RadiomicsFeatureExtractor
        """
        modality = modality.upper()

        base = {
            "imageType": {"Original": {}},
            "featureClass": self.DEFAULT_ENABLED_FEATURES,
            "setting": {
                # 体素距离校正：让纹理特征对 spacing 变化更鲁棒
                "distances": [1],
                # 是否强制 3D（mask 有多个 slice 时）
                "force2D": False,
                # 是否计算 shape 特征
                "shape": {"shape": True},
                # 最小 ROI 体素数（低于此值不提取）
                "minimumROIDimensions": 1,
                "minimumROISize": None,
                # 插值（QC Agent 已做 resample，这里保持默认即可）
                "resampledPixelSpacing": None,
                "interpolator": "sitkBSpline",
                # 预处理
                "normalize": False,
                "normalizeScale": 1,
                "removeOutliers": None,
                "binWidth": 25,          # CT 默认
                "binCount": None,
                "voxelArrayShift": 0,
                # 标签值
                "label": 1,
                "additionalLabels": [],
            },
            "voxelSetting": {
                "kernelRadius": 2,
                "maskedKernel": True,
                "initValue": 0,
                "voxelBatch": 10000,
            },
        }

        if modality == "CT":
            # CT：HU 值有物理意义，binWidth=25 是文献常用值
            base["setting"]["binWidth"] = 25
            base["setting"]["normalize"] = False
            base["setting"]["removeOutliers"] = None
            logger.info("使用 CT 参数配置: binWidth=25, normalize=False")

        elif modality == "MRI":
            # MRI：必须归一化 + 更小的 binWidth
            base["setting"]["normalize"] = True
            base["setting"]["normalizeScale"] = 100  # 归一化到均值 0，标准差 100
            base["setting"]["binWidth"] = 5         # MRI 文献常用 5-10
            base["setting"]["removeOutliers"] = 3   # 去除 3 倍标准差外异常值
            logger.info("使用 MRI 参数配置: normalize=True, normalizeScale=100, binWidth=5")

        elif modality == "PET":
            # PET：SUV 值范围小，binWidth 可更小
            base["setting"]["normalize"] = False
            base["setting"]["binWidth"] = 0.5
            logger.info("使用 PET 参数配置: binWidth=0.5, normalize=False")

        else:
            logger.warning(f"未知模态 '{modality}'，默认按 CT 处理")
            # 保持 base 默认值（CT 风格）

        return base

    # -----------------------------------------------------------------------
    # 单患者特征提取（核心函数，必须可被 pickle 用于多进程）
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_single(task: ExtractionTask) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
        """
        为单个患者提取影像组学特征。

        这是一个 staticmethod，确保可被 pickle 后传给多进程 Pool。

        Args:
            task: ExtractionTask 数据类实例。

        Returns:
            (patient_id, features_dict_or_None, error_message_or_None)
            - 成功: (patient_id, features_dict, None)
            - 失败: (patient_id, None, error_msg)
        """
        pid = task.patient_id

        try:
            # 文件存在性检查
            if not os.path.exists(task.image_path):
                return pid, None, f"影像文件不存在: {task.image_path}"
            if not os.path.exists(task.mask_path):
                return pid, None, f"Mask 文件不存在: {task.mask_path}"

            # 构建 PyRadiomics Extractor
            extractor = featureextractor.RadiomicsFeatureExtractor(task.settings)

            # 执行提取
            result = extractor.execute(task.image_path, task.mask_path, label=1)

            # result 是 OrderedDict，包含诊断信息 + 特征，过滤掉以 "diagnostics_" 开头的元数据
            features = {
                k: v for k, v in result.items()
                if not k.startswith("diagnostics_")
            }

            # 全零检查
            if len(features) == 0:
                return pid, None, "提取结果为空（无特征返回）"

            numeric_values = [v for v in features.values() if isinstance(v, (int, float, np.number))]
            if len(numeric_values) == 0:
                return pid, None, "所有特征值均为非数值类型"

            if all(np.isclose(float(v), 0.0, atol=1e-12) for v in numeric_values):
                return pid, None, "所有数值特征均为零（可能 mask 为空或 ROI 无效）"

            return pid, features, None

        except Exception as e:
            return pid, None, f"异常: {type(e).__name__}: {str(e)}"

    # -----------------------------------------------------------------------
    # 串行提取（用于单样本或调试）
    # -----------------------------------------------------------------------

    def _extract_sequential(
        self, tasks: List[ExtractionTask]
    ) -> List[Tuple[str, Optional[Dict], Optional[str]]]:
        """串行提取，便于调试。"""
        results = []
        for task in tasks:
            logger.info(f"提取中: {task.patient_id} ({task.modality})")
            res = self._extract_single(task)
            results.append(res)
        return results

    # -----------------------------------------------------------------------
    # 并行提取（生产环境）
    # -----------------------------------------------------------------------

    def _extract_parallel(
        self, tasks: List[ExtractionTask]
    ) -> List[Tuple[str, Optional[Dict], Optional[str]]]:
        """
        使用 ProcessPoolExecutor 并行提取。
        每个进程独立初始化 PyRadiomics，无共享状态。
        """
        results = []
        with ProcessPoolExecutor(max_workers=self.n_workers) as executor:
            # 提交所有任务
            future_to_task = {
                executor.submit(self._extract_single, task): task
                for task in tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    res = future.result(timeout=self.timeout_per_case)
                    results.append(res)
                    if res[2]:
                        logger.warning(f"提取失败 {task.patient_id}: {res[2]}")
                    else:
                        logger.info(f"提取成功 {task.patient_id}")
                except Exception as e:
                    logger.error(f"进程异常 {task.patient_id}: {e}")
                    results.append((task.patient_id, None, f"进程异常: {e}"))

        return results

    # -----------------------------------------------------------------------
    # 结果组装
    # -----------------------------------------------------------------------

    def _assemble_results(
        self,
        results: List[Tuple[str, Optional[Dict], Optional[str]]],
        expected_ids: List[str],
    ) -> Tuple[pd.DataFrame, List[str], List[str]]:
        """
        将提取结果组装成 DataFrame。

        Args:
            results: [(patient_id, features_dict, error), ...]
            expected_ids: 期望包含的所有患者 ID。

        Returns:
            (features_df, failed_ids, zero_variance_features)
        """
        success_records = []
        failed_ids = []

        for pid, feats, err in results:
            if err:
                failed_ids.append(pid)
                logger.warning(f"组装时跳过失败样本 {pid}: {err}")
            else:
                # 将特征 dict 转为 Series，patient_id 作为 index
                success_records.append(pd.Series(feats, name=pid))

        if not success_records:
            raise FeatureExtractionError("N/A", "所有患者特征提取均失败，无法继续")

        features_df = pd.DataFrame(success_records)
        features_df.index.name = "patient_id"

        # 确保所有列为数值类型
        features_df = features_df.apply(pd.to_numeric, errors="coerce")

        # 检查 NaN 列（PyRadiomics 有时会返回 NaN）
        nan_cols = features_df.columns[features_df.isna().all()].tolist()
        if nan_cols:
            logger.warning(f"以下特征列全为 NaN，已移除: {nan_cols}")
            features_df = features_df.drop(columns=nan_cols)

        # 检查零方差特征（LASSO 要求特征至少有两值不同）
        zero_variance_features = []
        for col in features_df.columns:
            if features_df[col].nunique(dropna=True) <= 1:
                zero_variance_features.append(col)

        # 检查样本量
        n_samples = len(features_df)
        if n_samples < 30:
            logger.error(f"样本量严重不足: {n_samples} < 30，Analysis Agent 会中断")
            # 不在这里抛异常，让 Orchestrator / Analysis Agent 做统一决策

        # 检查特征全零（行维度）
        all_zero_rows = (features_df.fillna(0) == 0).all(axis=1)
        if all_zero_rows.any():
            bad_ids = features_df.index[all_zero_rows].tolist()
            logger.error(f"以下患者所有特征均为零，已从矩阵移除: {bad_ids}")
            features_df = features_df[~all_zero_rows]

        return features_df, failed_ids, zero_variance_features
```

---

## 四、异常处理策略

### 4.1 异常分类与处理

| 异常场景 | 检测位置 | 处理方式 | 是否中断流水线 |
|---------|---------|---------|--------------|
| **影像/mask 文件不存在** | `_extract_single` 开头 | 记录 failed_id，跳过该患者 | 否（partial） |
| **PyRadiomics 内部异常**（如 mask 标签值错误） | `extractor.execute` 的 try-except | 记录 failed_id，跳过 | 否（partial） |
| **提取结果为空**（无特征返回） | `_extract_single` 结果检查 | 记录 failed_id，跳过 | 否（partial） |
| **所有数值特征均为零** | `_extract_single` 全零检查 | 记录 failed_id，跳过 | 否（partial） |
| **所有患者均失败** | `_assemble_results` | 抛出 `FeatureExtractionError` | **是（failed）** |
| **零方差特征列** | `_assemble_results` | 移除该列，保留患者 | 否（success） |
| **某患者提取后全行零值** | `_assemble_results` all_zero_rows | 移除该患者行 | 否（partial） |
| **样本量 < 30** | `_assemble_results` | 记录 warning，不抛异常 | 由 Orchestrator 决策 |
| **未知模态** | `_build_settings` | 默认按 CT 处理，记 warning | 否 |
| **单进程超时** | `_extract_parallel` future.result | 记录 failed_id | 否（partial） |

### 4.2 与 Orchestrator 的协作

Feature Agent **不直接决定**是否中断流水线，而是通过 `state["feature_agent_status"]` 报告状态：

- `"success"`: 全部成功，继续下游。
- `"partial"`: 部分失败，`feature_metadata["failed_ids"]` 中有值。Orchestrator 应提示用户："以下患者特征提取失败，是否继续？" 用户选"跳过"则继续（用成功子集跑分析）。
- `"failed"`: 全部失败，Orchestrator 必须中断，提示检查文件。

---

## 五、关键算法与参数详解

### 5.1 PyRadiomics 参数自动选择逻辑

PyRadiomics 的 `featureextractor.RadiomicsFeatureExtractor` 需要传入一个 YAML/JSON 格式的 settings。我们的 `_build_settings` 返回 Python dict，由 Extractor 内部解析。

**CT 参数原理：**
- `normalize=False`: CT 的 HU 值有绝对物理意义（空气=-1000，水=0），归一化会抹除这一信息。
- `binWidth=25`: 参考 [PyRadiomics 官方文档](https://pyradiomics.readthedocs.io/) 和 IBSI 标准，CT 常用 25 HU 为 bin 宽度。这决定了纹理特征（GLCM、GLRLM 等）的灰度离散化粒度。

**MRI 参数原理：**
- `normalize=True, normalizeScale=100`: MRI 信号强度无绝对单位，不同机器、序列差异巨大。z-score 归一化（均值为 0，标准差为 100）是标准做法。
- `binWidth=5`: 归一化后灰度范围约为 ±300，binWidth=5 可产生约 120 个灰度级，足够纹理计算且不过度稀疏。
- `removeOutliers=3`: 去除 3 倍标准差外的异常高信号（如脂肪、造影剂残留），避免极端值扭曲纹理统计。

### 5.2 特征类别说明

| featureClass | 中文名 | 数量（约） | 说明 |
|-------------|--------|----------|------|
| `firstorder` | 一阶统计量 | 18 | 均值、中位数、偏度、峰度、能量、熵等（基于原始体素值分布） |
| `shape` | 形状特征 | 14 | 体积、表面积、球形度、紧凑度、主轴长度等（3D 几何） |
| `glcm` | 灰度共生矩阵 | 24 | 对比度、相关性、同质性、能量等（反映体素对的灰度空间关系） |
| `glrlm` | 灰度游程矩阵 | 16 | 短/长游程强调、灰度非均匀性等（反映连续相同灰度的长度分布） |
| `glszm` | 灰度大小区域矩阵 | 16 | 小/大区域强调、区域大小非均匀性等（反映连通区域大小） |
| `gldm` | 灰度依赖矩阵 | 14 | 依赖非均匀性、大依赖高灰度强调等（反映体素与邻居的依赖关系） |
| `ngtdm` | 邻域灰度差分矩阵 | 5 | 粗糙度、对比度、忙碌度等（反映灰度变化剧烈程度） |

**总计约 107 维特征**（PyRadiomics 版本不同可能略有差异）。

### 5.3 多进程实现要点

PyRadiomics 的 `featureextractor` 实例**不可 pickle**（内部包含 SimpleITK Image 缓存）。因此我们的策略是：

1. **任务拆分阶段（主进程）：** 只传递文件路径 + settings dict（纯 Python 对象，可 pickle）。
2. **工作进程：** 每个进程独立 `import radiomics`、实例化 `RadiomicsFeatureExtractor`、读取文件、提取特征、返回纯 dict。
3. **结果聚合（主进程）：** 收集 dict 列表，组装成 pandas DataFrame。

这个设计避免了进程间共享状态，符合 PyRadiomics 的架构约束。

---

## 六、接口函数汇总（供 Orchestrator 调用）

```python
# orchestrator.py 中的调用方式示例

from feature import FeatureAgent

def run_feature_stage(state: dict) -> None:
    agent = FeatureAgent(n_workers=4)
    agent.run(state)
    
    # 状态机根据结果决策
    status = state.get("feature_agent_status")
    if status == "failed":
        raise RuntimeError("特征提取全部失败")
    elif status == "partial":
        # 进入中断：提示用户有 failed_ids
        pass
```

---

## 七、单元测试要点

```python
# test_feature.py（建议同学编写）

import unittest
from feature import FeatureAgent, FeatureExtractionError

class TestFeatureAgent(unittest.TestCase):
    
    def test_build_settings_ct(self):
        agent = FeatureAgent()
        s = agent._build_settings("CT")
        self.assertFalse(s["setting"]["normalize"])
        self.assertEqual(s["setting"]["binWidth"], 25)
    
    def test_build_settings_mri(self):
        agent = FeatureAgent()
        s = agent._build_settings("MRI")
        self.assertTrue(s["setting"]["normalize"])
        self.assertEqual(s["setting"]["binWidth"], 5)
    
    def test_empty_pairs(self):
        agent = FeatureAgent()
        state = {"pairs": []}
        with self.assertRaises(FeatureExtractionError):
            agent.run(state)
    
    def test_all_zero_features_removed(self):
        # 用 mock 数据测试零方差/全零行移除
        pass
```

---

## 八、与下游 Merge Agent 的衔接说明

Feature Agent 输出的 `features_df` 在 `state["features_df"]` 中，Merge Agent 的职责是：

1. 读取 `state["features_df"]`（索引为 patient_id）。
2. 读取 `state["clinical_df"]`（Clinical Agent 输出，索引为 patient_id）。
3. 按 `patient_id` 做 `join`（inner join，只保留两边都有的患者）。
4. 加入 Label 列（来自 clinical_df）。
5. 输出 `state["merged_df"]` 供 Analysis Agent 使用。

Feature Agent 不参与合并，只保证 `features_df` 的 index 类型为 string 且与 `pairs` 中的 `patient_id` 一致。

---

## 九、文档版本

- 版本：v1.0
- 编写日期：2026-06-18
- 适用：同学 B（负责 `feature.py` 实现）
- 依赖包：`pyradiomics>=3.0.1`, `SimpleITK>=2.3.0`, `pandas>=2.0`, `numpy>=1.24`
