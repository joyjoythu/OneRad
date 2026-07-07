# QC_Agent 实现方案文档

> 版本：v1.0
> 负责人：同学 A
> 对应文件：`app/qc.py`
> 上游输入：Discovery Agent 的配对列表
> 下游输出：Feature Agent（通过 Orchestrator 传递）

---

## 一、职责概述

QC Agent 对 Discovery Agent 产出的 image-mask 配对列表进行逐对**数据质量检查**。检查项覆盖：

1. **Mask 非空检查**：排除全零 mask（无 ROI 标注）。
2. **Image/Mask 尺寸一致性**：检查三维体素维度是否严格一致。
3. **Spacing 检查与自动 Resample**：若 image 与 mask 的 spacing 不一致，或目标要求统一 spacing，则使用 SimpleITK 自动重采样到目标 spacing。
4. **值域检查（CT/MRI）**：对 CT 检查 HU 值范围是否在合理区间；对 MRI 检查信号强度是否异常（如全零、NaN）。
5. **ID 与路径一致性**：确认配对信息无缺失。

**失败策略**：任何一项检查失败 → 标记该样本为 `FAILED`，记录失败原因，继续检查其余样本。最终由 Orchestrator 决定是否中断（若失败样本数 > 0）。用户可选"跳过失败样本"继续后续流程。

---

## 二、输入输出数据结构（接口契约）

### 2.1 输入：来自 Discovery Agent

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import SimpleITK as sitk

@dataclass
class ImageMaskPair:
    """
    Discovery Agent 产出的单对 image-mask 配对。
    QC Agent 只读取，不修改字段。
    """
    patient_id: str                       # 患者 ID，如 "P001"
    image_path: Path                      # 影像文件绝对路径（如 .nii, .nii.gz, .dicom 目录）
    mask_path: Path                       # Mask 文件绝对路径
    modality: str                         # "CT" 或 "MRI"，Discovery 阶段根据文件名或 DICOM 标签推断
    # --- 以下为可选辅助信息 ---
    image_meta: Dict = field(default_factory=dict)   # Discovery 读取的原始元数据（DICOM 头信息等）
    mask_meta: Dict = field(default_factory=dict)

# 输入类型
QCInput = List[ImageMaskPair]
```

### 2.2 输出：传给 Orchestrator → Feature Agent

```python
from enum import Enum

class QCStatus(str, Enum):
    PASSED = "passed"      # 全部检查通过
    FAILED = "failed"      # 某项检查失败
    SKIPPED = "skipped"    # 用户选择跳过该样本（Orchestrator 层标记，QC 不直接设置）

@dataclass
class QCResultItem:
    """单个样本的质检结果"""
    patient_id: str
    image_path: Path
    mask_path: Path
    modality: str
    status: QCStatus
    messages: List[str] = field(default_factory=list)   # 人类可读的信息列表（含成功/失败/警告）
    # --- 若通过，则以下字段有效 ---
    resampled_image_path: Optional[Path] = None   # 若执行了 resample，保存的新路径；否则为原路径
    resampled_mask_path: Optional[Path] = None
    actual_spacing: Optional[Tuple[float, float, float]] = None  # 最终（可能 resample 后）的 spacing
    original_spacing: Optional[Tuple[float, float, float]] = None
    shape: Optional[Tuple[int, int, int]] = None     # 最终体素维度 (X, Y, Z)
    roi_voxel_count: Optional[int] = None            # mask 中 ROI 体素数
    # --- 若失败，以下字段记录失败原因 ---
    fail_reason: Optional[str] = None
    fail_stage: Optional[str] = None   # 失败发生在哪个检查阶段："mask_empty", "dimension", "spacing", "value_range"

@dataclass
class QCReport:
    """
    QC Agent 的完整输出报告。
    Orchestrator 将该对象直接注入 state dict，Feature Agent 读取 `passed_pairs` 开始提取。
    """
    total: int
    passed: int
    failed: int
    results: List[QCResultItem]
    # 仅保留通过的样本列表，供 Feature Agent 直接消费
    passed_pairs: List[ImageMaskPair] = field(default_factory=list)
    # 保留失败项，供 Report Agent 写入"排除样本说明"
    failed_items: List[QCResultItem] = field(default_factory=list)
    # 全局元数据
    target_spacing: Optional[Tuple[float, float, float]] = None
    # 若执行了全局 resample，记录策略
    resample_strategy: str = "none"   # "none" | "individual" | "global_target"
```

### 2.3 配置参数（`config` 或构造函数入参）

```python
@dataclass
class QCConfig:
    """QC Agent 的配置，由 Orchestrator 初始化时传入"""
    # --- spacing 相关 ---
    resample_target_spacing: Optional[Tuple[float, float, float]] = None
    """若指定，所有 image/mask 统一 resample 到该 spacing；若 None，则仅做 image-mask 一致性检查，不强制统一。"""
    resample_interpolator_image: str = "linear"      # "linear" | "bspline"
    resample_interpolator_mask: str = "nearest"      # mask 必须 nearest，避免标签值插值出界
    # --- 值域检查阈值 ---
    ct_hu_min: float = -1000.0
    ct_hu_max: float = 3000.0
    mri_signal_max_ratio: float = 0.99   # MRI 若全零体素占比 > 99% 视为异常
    # --- 并行 ---
    n_workers: int = 4
    # --- 输出目录 ---
    output_dir: Path = Path("./tmp/qc")   # resample 后的文件缓存目录
```

---

## 三、核心类与函数签名

```python
class QCAgent:
    """
    QC Agent 主类。
    对外仅暴露两个方法：构造函数 + run()。
    """

    def __init__(self, config: QCConfig):
        ...

    def run(self, pairs: QCInput) -> QCReport:
        """
        主入口。对输入的配对列表执行全部质检流程。
        返回 QCReport，供 Orchestrator 决策。
        """
        ...

    # --- 以下为内部方法（可 private） ---
    def _check_single_pair(self, pair: ImageMaskPair) -> QCResultItem:
        ...

    def _read_image_and_mask(self, pair: ImageMaskPair) -> Tuple[sitk.Image, sitk.Image]:
        ...

    def _check_mask_non_empty(self, mask_sitk: sitk.Image) -> Tuple[bool, int, Optional[str]]:
        ...

    def _check_dimension_consistency(self, image_sitk: sitk.Image, mask_sitk: sitk.Image) -> Tuple[bool, Optional[str]]:
        ...

    def _check_and_resample_spacing(
        self,
        image_sitk: sitk.Image,
        mask_sitk: sitk.Image,
        pair: ImageMaskPair
    ) -> Tuple[bool, sitk.Image, sitk.Image, Tuple[float, float, float], Optional[str]]:
        ...

    def _check_value_range(self, image_sitk: sitk.Image, modality: str) -> Tuple[bool, Optional[str]]:
        ...

    def _resample_to_target(
        self,
        image_sitk: sitk.Image,
        mask_sitk: sitk.Image,
        target_spacing: Tuple[float, float, float],
        output_stem: str
    ) -> Tuple[Path, Path]:
        ...
```

---

## 四、详细实现逻辑

### 4.1 主流程 `run()`

```python
def run(self, pairs: QCInput) -> QCReport:
    if not pairs:
        return QCReport(total=0, passed=0, failed=0, results=[], passed_pairs=[])

    self.config.output_dir.mkdir(parents=True, exist_ok=True)

    results: List[QCResultItem] = []
    
    # 并行处理（ProcessPoolExecutor）
    from concurrent.futures import ProcessPoolExecutor, as_completed
    
    with ProcessPoolExecutor(max_workers=self.config.n_workers) as executor:
        future_to_pair = {
            executor.submit(self._check_single_pair, pair): pair 
            for pair in pairs
        }
        for future in as_completed(future_to_pair):
            result = future.result()
            results.append(result)

    # 统计
    passed_items = [r for r in results if r.status == QCStatus.PASSED]
    failed_items = [r for r in results if r.status == QCStatus.FAILED]

    passed_pairs = [
        ImageMaskPair(
            patient_id=r.patient_id,
            image_path=r.resampled_image_path or r.image_path,
            mask_path=r.resampled_mask_path or r.mask_path,
            modality=r.modality
        )
        for r in passed_items
    ]

    return QCReport(
        total=len(results),
        passed=len(passed_items),
        failed=len(failed_items),
        results=results,
        passed_pairs=passed_pairs,
        failed_items=failed_items,
        target_spacing=self.config.resample_target_spacing,
        resample_strategy="global_target" if self.config.resample_target_spacing else "individual"
    )
```

> **注意**：`ProcessPoolExecutor` 要求内部方法可序列化。若出现 pickle 问题，可回退到 `ThreadPoolExecutor`（GIL 对 I/O 密集型影像读写影响有限），或保持串行（`n_workers=1` 兜底）。

### 4.2 单样本检查 `_check_single_pair()`

```python
def _check_single_pair(self, pair: ImageMaskPair) -> QCResultItem:
    result = QCResultItem(
        patient_id=pair.patient_id,
        image_path=pair.image_path,
        mask_path=pair.mask_path,
        modality=pair.modality,
        status=QCStatus.PASSED,
        messages=[]
    )

    try:
        # Step 1: 读取
        image_sitk, mask_sitk = self._read_image_and_mask(pair)
        result.original_spacing = image_sitk.GetSpacing()
        result.shape = image_sitk.GetSize()
        result.messages.append(f"读取成功，原始 spacing: {result.original_spacing}")

        # Step 2: Mask 非空检查
        ok, roi_count, err = self._check_mask_non_empty(mask_sitk)
        if not ok:
            result.status = QCStatus.FAILED
            result.fail_stage = "mask_empty"
            result.fail_reason = err
            result.messages.append(f"FAIL[mask_empty]: {err}")
            return result
        result.roi_voxel_count = roi_count
        result.messages.append(f"Mask ROI 体素数: {roi_count}")

        # Step 3: 尺寸一致性
        ok, err = self._check_dimension_consistency(image_sitk, mask_sitk)
        if not ok:
            result.status = QCStatus.FAILED
            result.fail_stage = "dimension"
            result.fail_reason = err
            result.messages.append(f"FAIL[dimension]: {err}")
            return result
        result.messages.append("Image/Mask 尺寸一致")

        # Step 4: Spacing 检查与 Resample
        ok, image_final, mask_final, final_spacing, err = self._check_and_resample_spacing(
            image_sitk, mask_sitk, pair
        )
        if not ok:
            result.status = QCStatus.FAILED
            result.fail_stage = "spacing"
            result.fail_reason = err
            result.messages.append(f"FAIL[spacing]: {err}")
            return result
        result.actual_spacing = final_spacing
        result.messages.append(f"最终 spacing: {final_spacing}")

        # Step 5: 值域检查
        ok, err = self._check_value_range(image_final, pair.modality)
        if not ok:
            result.status = QCStatus.FAILED
            result.fail_stage = "value_range"
            result.fail_reason = err
            result.messages.append(f"FAIL[value_range]: {err}")
            return result
        result.messages.append("值域检查通过")

        # 若执行了 resample，记录输出路径
        if self.config.resample_target_spacing:
            out_stem = f"{pair.patient_id}_{pair.modality}"
            img_out, mask_out = self._resample_to_target(
                image_sitk, mask_sitk,
                self.config.resample_target_spacing, out_stem
            )
            result.resampled_image_path = img_out
            result.resampled_mask_path = mask_out
            result.messages.append(f"Resample 缓存: {img_out}, {mask_out}")

        result.messages.append("全部 QC 检查通过")
        return result

    except Exception as e:
        result.status = QCStatus.FAILED
        result.fail_stage = "exception"
        result.fail_reason = str(e)
        result.messages.append(f"FAIL[exception]: {e}")
        return result
```

### 4.3 读取影像 `_read_image_and_mask()`

```python
def _read_image_and_mask(self, pair: ImageMaskPair) -> Tuple[sitk.Image, sitk.Image]:
    """
    支持 .nii, .nii.gz, .mha, .mhd, 以及 DICOM 目录（自动读取 series）。
    """
    image_path = str(pair.image_path)
    mask_path = str(pair.mask_path)

    # Image 读取
    if Path(image_path).is_dir():
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(image_path)
        if not dicom_names:
            raise ValueError(f"DICOM 目录未找到有效序列: {image_path}")
        reader.SetFileNames(dicom_names)
        image_sitk = reader.Execute()
    else:
        image_sitk = sitk.ReadImage(image_path)

    # Mask 读取（mask 通常不会以 DICOM 序列给出，但保持兼容）
    if Path(mask_path).is_dir():
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(mask_path)
        reader.SetFileNames(dicom_names)
        mask_sitk = reader.Execute()
    else:
        mask_sitk = sitk.ReadImage(mask_path)

    # 强制 mask 为整型（避免浮点标签）
    if mask_sitk.GetPixelID() not in (sitk.sitkUInt8, sitk.sitkInt16, sitk.sitkInt32, sitk.sitkUInt16):
        mask_sitk = sitk.Cast(mask_sitk, sitk.sitkUInt8)

    return image_sitk, mask_sitk
```

### 4.4 Mask 非空检查 `_check_mask_non_empty()`

```python
def _check_mask_non_empty(self, mask_sitk: sitk.Image) -> Tuple[bool, int, Optional[str]]:
    """
    使用 SimpleITK 的 LabelStatisticsImageFilter 或 numpy 转换。
    返回：(是否通过, ROI 体素数, 错误信息)
    """
    import numpy as np
    mask_arr = sitk.GetArrayFromImage(mask_sitk)  # shape: (Z, Y, X)
    
    # 统计非零体素（假设 mask 中 >0 的值为 ROI）
    roi_voxels = np.count_nonzero(mask_arr > 0)
    
    if roi_voxels == 0:
        return False, 0, "Mask 全为零，无 ROI 标注"
    
    return True, roi_voxels, None
```

### 4.5 尺寸一致性检查 `_check_dimension_consistency()`

```python
def _check_dimension_consistency(self, image_sitk: sitk.Image, mask_sitk: sitk.Image) -> Tuple[bool, Optional[str]]:
    img_size = image_sitk.GetSize()   # (X, Y, Z)
    mask_size = mask_sitk.GetSize()
    
    if img_size != mask_size:
        return False, f"Image size {img_size} != Mask size {mask_size}"
    
    # 可选：同时检查 origin 和 direction 是否一致（若差异很大，spatial 对齐也会出问题）
    img_origin = image_sitk.GetOrigin()
    mask_origin = mask_sitk.GetOrigin()
    if img_origin != mask_origin:
        # 这里作为警告，不强制失败（某些数据集 origin 有微小浮点差异）
        pass
    
    return True, None
```

### 4.6 Spacing 检查与 Resample `_check_and_resample_spacing()`

这是 QC Agent 最复杂的部分。需处理三种情况：

1. **未配置 target spacing**：仅检查 image 与 mask 的 spacing 是否一致。
2. **配置了 target spacing**：将 image 和 mask 统一 resample 到目标 spacing。
3. **image 与 mask spacing 不一致**：先以 image 的 spacing 为参考，将 mask resample 到 image spacing，再统一处理。

```python
def _check_and_resample_spacing(
    self,
    image_sitk: sitk.Image,
    mask_sitk: sitk.Image,
    pair: ImageMaskPair
) -> Tuple[bool, sitk.Image, sitk.Image, Tuple[float, float, float], Optional[str]]:
    """
    返回：(是否通过, 最终 image, 最终 mask, 最终 spacing, 错误信息)
    """
    img_spacing = image_sitk.GetSpacing()
    mask_spacing = mask_sitk.GetSpacing()

    # 情况 A：image 与 mask spacing 不一致
    if img_spacing != mask_spacing:
        # 将 mask resample 到 image spacing（以 image 为准）
        mask_sitk = self._resample_image_to_reference(
            mask_sitk, image_sitk, is_mask=True
        )
        # 此时两者 spacing 已一致，继续

    # 确定最终目标 spacing
    target = self.config.resample_target_spacing
    if target is None:
        # 无需强制统一，当前 spacing 即最终 spacing
        return True, image_sitk, mask_sitk, img_spacing, None

    # 情况 B：需要 resample 到 target spacing
    if img_spacing == target:
        # 已经是目标 spacing
        return True, image_sitk, mask_sitk, target, None

    # 执行 resample（image 和 mask 分别处理插值方式）
    image_final = self._resample_to_spacing(image_sitk, target, is_mask=False)
    mask_final = self._resample_to_spacing(mask_sitk, target, is_mask=True)

    return True, image_final, mask_final, target, None
```

**Resample 核心代码（辅助方法）**：

```python
def _resample_to_spacing(
    self,
    image: sitk.Image,
    target_spacing: Tuple[float, float, float],
    is_mask: bool
) -> sitk.Image:
    """
    将单张 image/mask 重采样到目标 spacing。
    """
    original_size = image.GetSize()
    original_spacing = image.GetSpacing()

    # 计算新尺寸（保持物理体积一致）
    new_size = [
        int(round(original_size[i] * original_spacing[i] / target_spacing[i]))
        for i in range(3)
    ]

    # 防止尺寸为 0
    new_size = [max(1, s) for s in new_size]

    interpolator = {
        False: sitk.sitkLinear,     # Image 用线性插值
        True: sitk.sitkNearestNeighbor  # Mask 用最近邻，保持标签值
    }[is_mask]

    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(target_spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetInterpolator(interpolator)
    resampler.SetDefaultPixelValue(0)
    resampler.SetOutputPixelType(image.GetPixelID())

    return resampler.Execute(image)

def _resample_image_to_reference(
    self,
    image: sitk.Image,
    reference: sitk.Image,
    is_mask: bool
) -> sitk.Image:
    """
    将 image resample 到 reference 的网格（spacing/size/origin/direction）。
    """
    interpolator = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear

    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(reference)
    resampler.SetInterpolator(interpolator)
    resampler.SetDefaultPixelValue(0)
    resampler.SetOutputPixelType(image.GetPixelID())

    return resampler.Execute(image)
```

### 4.7 Resample 文件缓存 `_resample_to_target()`

```python
def _resample_to_target(
    self,
    image_sitk: sitk.Image,
    mask_sitk: sitk.Image,
    target_spacing: Tuple[float, float, float],
    output_stem: str
) -> Tuple[Path, Path]:
    """
    将 resample 后的结果写入临时目录，供后续 Feature Agent 读取。
    返回：(image_out_path, mask_out_path)
    """
    out_dir = self.config.output_dir / "resampled"
    out_dir.mkdir(parents=True, exist_ok=True)

    img_out = out_dir / f"{output_stem}_image.nii.gz"
    mask_out = out_dir / f"{output_stem}_mask.nii.gz"

    image_final = self._resample_to_spacing(image_sitk, target_spacing, is_mask=False)
    mask_final = self._resample_to_spacing(mask_sitk, target_spacing, is_mask=True)

    sitk.WriteImage(image_final, str(img_out))
    sitk.WriteImage(mask_final, str(mask_out))

    return img_out, mask_out
```

### 4.8 值域检查 `_check_value_range()`

```python
def _check_value_range(self, image_sitk: sitk.Image, modality: str) -> Tuple[bool, Optional[str]]:
    import numpy as np
    arr = sitk.GetArrayFromImage(image_sitk)
    
    # 检查 NaN / Inf
    if not np.all(np.isfinite(arr)):
        nan_count = np.count_nonzero(~np.isfinite(arr))
        return False, f"影像包含 {nan_count} 个 NaN/Inf 值"

    if modality.upper() == "CT":
        # CT 值域通常应在 -1000 ~ 3000 HU 之间
        min_val = float(arr.min())
        max_val = float(arr.max())
        if min_val < self.config.ct_hu_min or max_val > self.config.ct_hu_max:
            # 作为警告，不强制失败（有些 CT 扫描范围特殊）
            return True, None  # 或返回 False，取决于项目策略
    
    elif modality.upper() == "MRI":
        # MRI 检查是否全零（已排除）或信号异常集中在极小范围
        unique_ratio = len(np.unique(arr)) / arr.size
        if unique_ratio < 0.001:
            # 信号过于单一，可能为退化数据
            return False, "MRI 信号过于单一，可能为无效数据"
    
    return True, None
```

---

## 五、与上下游 Agent 的接口契约

### 5.1 上游：Discovery Agent

| 字段 | 类型 | 说明 | QC Agent 使用方式 |
|------|------|------|-------------------|
| `patient_id` | `str` | 患者唯一标识 | 仅透传，用于日志和输出 |
| `image_path` | `Path` | 影像文件路径 | 读取并检查 |
| `mask_path` | `Path` | Mask 文件路径 | 读取并检查 |
| `modality` | `str` | `"CT"` / `"MRI"` | 决定值域检查阈值和 PyRadiomics 参数（透传） |

**契约约束**：
- Discovery Agent 保证 `image_path` 和 `mask_path` 存在且为文件或目录。
- `modality` 字段必须已推断（不能为 `None` 或空字符串）。若为空，QC Agent 按 `"UNKNOWN"` 处理，值域检查跳过模态特定逻辑。

### 5.2 下游：Feature Agent

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `passed_pairs` | `List[ImageMaskPair]` | 通过质检的样本列表 | QC Agent 构造，路径可能指向 resample 后的缓存文件 |
| `target_spacing` | `Tuple[float, float, float]` | 统一后的 spacing | QC Agent 配置或自动推断 |
| `failed_items` | `List[QCResultItem]` | 失败项（供 Report 写排除说明） | QC Agent 直接透传 |

**契约约束**：
- QC Agent 保证 `passed_pairs` 中的 `image_path` 和 `mask_path` 在 Feature Agent 运行时可读。
- 若执行了 resample，`passed_pairs` 中的路径指向 `tmp/qc/resampled/` 下的 `.nii.gz` 文件；否则为原始路径。
- Feature Agent 不应修改 `passed_pairs` 中的文件。

---

## 六、异常处理逻辑（QC Agent 特有）

| 异常场景 | 检测位置 | 处理策略 | 返回状态 |
|----------|----------|----------|----------|
| **Mask 全零** | `_check_mask_non_empty` | 标记该样本失败，继续检查其他样本 | `FAILED`, `fail_stage="mask_empty"` |
| **Image/Mask 尺寸不一致** | `_check_dimension_consistency` | 标记失败 | `FAILED`, `fail_stage="dimension"` |
| **Image/Mask Spacing 不一致（未配 target spacing）** | `_check_and_resample_spacing` | 自动将 mask resample 到 image spacing；若失败则标记 | 失败时 `FAILED`, `fail_stage="spacing"` |
| **Resample 计算后尺寸为 0** | `_resample_to_spacing` | 计算 new_size 时 `max(1, ...)` 兜底；若仍异常则捕获异常 | 失败时 `FAILED` |
| **CT 值域异常（超出 -1000~3000）** | `_check_value_range` | 策略可配置：当前实现为**警告不失败**（因某些特殊 CT 扫描可能超范围） | 返回 True，但可在 message 中记录警告 |
| **MRI 信号过于单一** | `_check_value_range` | 标记失败 | `FAILED` |
| **影像包含 NaN/Inf** | `_check_value_range` | 标记失败 | `FAILED` |
| **文件读取失败（路径不存在、格式损坏）** | `_read_image_and_mask` | 捕获异常，返回 `FAILED`, `fail_stage="exception"` | `FAILED` |
| **DICOM 目录无有效序列** | `_read_image_and_mask` | 抛出异常，外层捕获 | `FAILED` |
| **多进程 Pool 崩溃（pickle 错误）** | `run()` | 回退到串行处理（`n_workers=1`）或 `ThreadPoolExecutor` | 内部处理，对用户透明 |

**样本量不足提示**：QC Agent 本身不检查样本量，只负责单样本质检。样本量不足（`< 30`）的判定在 **Analysis Agent** 中执行。但 QC Agent 需在 `QCReport` 中提供 `total` / `passed` / `failed` 统计，供 Orchestrator 在日志中提示用户。

---

## 七、状态事件（SSE 推送给 Gradio）

QC Agent 在 `run()` 中每处理完一个样本，通过回调函数向 Orchestrator 报告进度。Orchestrator 定义一个回调接口：

```python
# Orchestrator 传入的回调函数签名
QCProgressCallback = Callable[[Dict], None]

# 在 QCAgent.__init__ 中接收
class QCAgent:
    def __init__(self, config: QCConfig, progress_callback: Optional[QCProgressCallback] = None):
        self.config = config
        self.progress_callback = progress_callback or (lambda x: None)
```

**QC Agent 触发的事件**：

```python
# 单个样本完成时
self.progress_callback({
    "agent": "QC",
    "event": "sample_checked",
    "patient_id": result.patient_id,
    "status": result.status,
    "message": result.fail_reason or "检查通过",
    "current": idx + 1,
    "total": total
})

# 全部完成时
self.progress_callback({
    "agent": "QC",
    "event": "stage_complete",
    "passed": report.passed,
    "failed": report.failed,
    "total": report.total
})
```

Orchestrator 将这些事件包装为 SSE 格式推送到前端。

---

## 八、完整代码骨架（`app/qc.py`）

```python
"""
app/qc.py — QC Agent 实现

职责：
- 读取 Discovery Agent 产出的 image-mask 配对列表。
- 逐对执行 mask 非空、尺寸一致、spacing 检查与 resample、值域检查。
- 输出质检报告，供 Feature Agent 消费。
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import SimpleITK as sitk
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型（与上游/下游的契约）
# ---------------------------------------------------------------------------

@dataclass
class ImageMaskPair:
    patient_id: str
    image_path: Path
    mask_path: Path
    modality: str
    image_meta: Dict = field(default_factory=dict)
    mask_meta: Dict = field(default_factory=dict)

class QCStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"

@dataclass
class QCResultItem:
    patient_id: str
    image_path: Path
    mask_path: Path
    modality: str
    status: QCStatus
    messages: List[str] = field(default_factory=list)
    resampled_image_path: Optional[Path] = None
    resampled_mask_path: Optional[Path] = None
    actual_spacing: Optional[Tuple[float, float, float]] = None
    original_spacing: Optional[Tuple[float, float, float]] = None
    shape: Optional[Tuple[int, int, int]] = None
    roi_voxel_count: Optional[int] = None
    fail_reason: Optional[str] = None
    fail_stage: Optional[str] = None

@dataclass
class QCReport:
    total: int
    passed: int
    failed: int
    results: List[QCResultItem]
    passed_pairs: List[ImageMaskPair] = field(default_factory=list)
    failed_items: List[QCResultItem] = field(default_factory=list)
    target_spacing: Optional[Tuple[float, float, float]] = None
    resample_strategy: str = "none"

@dataclass
class QCConfig:
    resample_target_spacing: Optional[Tuple[float, float, float]] = None
    resample_interpolator_image: str = "linear"
    resample_interpolator_mask: str = "nearest"
    ct_hu_min: float = -1000.0
    ct_hu_max: float = 3000.0
    mri_signal_max_ratio: float = 0.99
    n_workers: int = 4
    output_dir: Path = Path("./tmp/qc")

# ---------------------------------------------------------------------------
# QCAgent 主类
# ---------------------------------------------------------------------------

class QCAgent:
    def __init__(
        self,
        config: QCConfig,
        progress_callback: Optional[Callable[[Dict], None]] = None
    ):
        self.config = config
        self.progress_callback = progress_callback or (lambda _: None)

    # -------------------------------------------------------------------
    # 公共入口
    # -------------------------------------------------------------------
    def run(self, pairs: List[ImageMaskPair]) -> QCReport:
        if not pairs:
            return QCReport(total=0, passed=0, failed=0, results=[])

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        results: List[QCResultItem] = []
        total = len(pairs)

        # 多进程处理（失败时回退串行）
        try:
            with ProcessPoolExecutor(max_workers=self.config.n_workers) as executor:
                futures = {executor.submit(self._check_single_pair, p): i for i, p in enumerate(pairs)}
                for future in as_completed(futures):
                    idx = futures[future]
                    result = future.result()
                    results.append(result)
                    self.progress_callback({
                        "agent": "QC",
                        "event": "sample_checked",
                        "patient_id": result.patient_id,
                        "status": result.status,
                        "message": result.fail_reason or "检查通过",
                        "current": len(results),
                        "total": total
                    })
        except Exception as exc:
            logger.warning(f"ProcessPoolExecutor 失败 ({exc})，回退到串行处理")
            results = [self._check_single_pair(p) for p in pairs]

        # 分类统计
        passed_items = [r for r in results if r.status == QCStatus.PASSED]
        failed_items = [r for r in results if r.status == QCStatus.FAILED]

        passed_pairs = [
            ImageMaskPair(
                patient_id=r.patient_id,
                image_path=r.resampled_image_path or r.image_path,
                mask_path=r.resampled_mask_path or r.mask_path,
                modality=r.modality
            )
            for r in passed_items
        ]

        report = QCReport(
            total=total,
            passed=len(passed_items),
            failed=len(failed_items),
            results=results,
            passed_pairs=passed_pairs,
            failed_items=failed_items,
            target_spacing=self.config.resample_target_spacing,
            resample_strategy="global_target" if self.config.resample_target_spacing else "none"
        )

        self.progress_callback({
            "agent": "QC",
            "event": "stage_complete",
            "passed": report.passed,
            "failed": report.failed,
            "total": report.total
        })

        return report

    # -------------------------------------------------------------------
    # 内部方法：单样本检查
    # -------------------------------------------------------------------
    def _check_single_pair(self, pair: ImageMaskPair) -> QCResultItem:
        result = QCResultItem(
            patient_id=pair.patient_id,
            image_path=pair.image_path,
            mask_path=pair.mask_path,
            modality=pair.modality,
            status=QCStatus.PASSED,
            messages=[]
        )
        try:
            image_sitk, mask_sitk = self._read_image_and_mask(pair)
            result.original_spacing = image_sitk.GetSpacing()
            result.shape = image_sitk.GetSize()

            # Mask 非空
            ok, roi_count, err = self._check_mask_non_empty(mask_sitk)
            if not ok:
                return self._fail(result, "mask_empty", err)
            result.roi_voxel_count = roi_count
            result.messages.append(f"ROI 体素数: {roi_count}")

            # 尺寸一致
            ok, err = self._check_dimension_consistency(image_sitk, mask_sitk)
            if not ok:
                return self._fail(result, "dimension", err)
            result.messages.append("尺寸一致")

            # Spacing 检查与 resample
            ok, image_final, mask_final, final_spacing, err = self._check_and_resample_spacing(
                image_sitk, mask_sitk, pair
            )
            if not ok:
                return self._fail(result, "spacing", err)
            result.actual_spacing = final_spacing
            result.messages.append(f"spacing: {final_spacing}")

            # 值域
            ok, err = self._check_value_range(image_final, pair.modality)
            if not ok:
                return self._fail(result, "value_range", err)
            result.messages.append("值域检查通过")

            # 若需要缓存 resample 结果
            if self.config.resample_target_spacing and result.original_spacing != result.actual_spacing:
                out_stem = f"{pair.patient_id}_{pair.modality}"
                img_path, mask_path = self._resample_to_target(
                    image_sitk, mask_sitk, self.config.resample_target_spacing, out_stem
                )
                result.resampled_image_path = img_path
                result.resampled_mask_path = mask_path
                result.messages.append(f"Resample 缓存已写入")

            result.messages.append("全部通过")
            return result

        except Exception as e:
            logger.exception(f"QC 异常: {pair.patient_id}")
            return self._fail(result, "exception", str(e))

    def _fail(self, result: QCResultItem, stage: str, reason: str) -> QCResultItem:
        result.status = QCStatus.FAILED
        result.fail_stage = stage
        result.fail_reason = reason
        result.messages.append(f"FAIL[{stage}]: {reason}")
        return result

    # -------------------------------------------------------------------
    # 读取
    # -------------------------------------------------------------------
    def _read_image_and_mask(self, pair: ImageMaskPair) -> Tuple[sitk.Image, sitk.Image]:
        image = self._read_sitk(pair.image_path)
        mask = self._read_sitk(pair.mask_path)
        # 强制 mask 为整型
        if mask.GetPixelID() not in (sitk.sitkUInt8, sitk.sitkInt16, sitk.sitkInt32, sitk.sitkUInt16):
            mask = sitk.Cast(mask, sitk.sitkUInt8)
        return image, mask

    def _read_sitk(self, path: Path) -> sitk.Image:
        p = str(path)
        if Path(p).is_dir():
            reader = sitk.ImageSeriesReader()
            names = reader.GetGDCMSeriesFileNames(p)
            if not names:
                raise ValueError(f"DICOM 目录无序列: {p}")
            reader.SetFileNames(names)
            return reader.Execute()
        return sitk.ReadImage(p)

    # -------------------------------------------------------------------
    # 检查方法
    # -------------------------------------------------------------------
    def _check_mask_non_empty(self, mask: sitk.Image) -> Tuple[bool, int, Optional[str]]:
        arr = sitk.GetArrayFromImage(mask)
        roi = np.count_nonzero(arr > 0)
        if roi == 0:
            return False, 0, "Mask 全零，无 ROI"
        return True, roi, None

    def _check_dimension_consistency(self, image: sitk.Image, mask: sitk.Image) -> Tuple[bool, Optional[str]]:
        if image.GetSize() != mask.GetSize():
            return False, f"Size mismatch: img={image.GetSize()}, mask={mask.GetSize()}"
        return True, None

    def _check_and_resample_spacing(
        self, image: sitk.Image, mask: sitk.Image, pair: ImageMaskPair
    ) -> Tuple[bool, sitk.Image, sitk.Image, Tuple[float, float, float], Optional[str]]:
        img_sp = image.GetSpacing()
        mask_sp = mask.GetSpacing()

        # 若 image 与 mask spacing 不一致，先将 mask 对齐到 image
        if img_sp != mask_sp:
            mask = self._resample_image_to_reference(mask, image, is_mask=True)

        target = self.config.resample_target_spacing
        if target is None or img_sp == target:
            return True, image, mask, img_sp, None

        image_final = self._resample_to_spacing(image, target, is_mask=False)
        mask_final = self._resample_to_spacing(mask, target, is_mask=True)
        return True, image_final, mask_final, target, None

    def _check_value_range(self, image: sitk.Image, modality: str) -> Tuple[bool, Optional[str]]:
        arr = sitk.GetArrayFromImage(image)
        if not np.all(np.isfinite(arr)):
            return False, f"包含 {np.count_nonzero(~np.isfinite(arr))} 个 NaN/Inf"
        if modality.upper() == "MRI":
            if len(np.unique(arr)) / arr.size < 0.001:
                return False, "MRI 信号过于单一"
        return True, None

    # -------------------------------------------------------------------
    # Resample 工具
    # -------------------------------------------------------------------
    def _resample_to_spacing(
        self, image: sitk.Image, target_spacing: Tuple[float, float, float], is_mask: bool
    ) -> sitk.Image:
        orig_size = image.GetSize()
        orig_spacing = image.GetSpacing()
        new_size = [max(1, int(round(orig_size[i] * orig_spacing[i] / target_spacing[i]))) for i in range(3)]
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear

        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(target_spacing)
        resampler.SetSize(new_size)
        resampler.SetOutputOrigin(image.GetOrigin())
        resampler.SetOutputDirection(image.GetDirection())
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        resampler.SetOutputPixelType(image.GetPixelID())
        return resampler.Execute(image)

    def _resample_image_to_reference(
        self, image: sitk.Image, reference: sitk.Image, is_mask: bool
    ) -> sitk.Image:
        interp = sitk.sitkNearestNeighbor if is_mask else sitk.sitkLinear
        resampler = sitk.ResampleImageFilter()
        resampler.SetReferenceImage(reference)
        resampler.SetInterpolator(interp)
        resampler.SetDefaultPixelValue(0)
        resampler.SetOutputPixelType(image.GetPixelID())
        return resampler.Execute(image)

    def _resample_to_target(
        self, image: sitk.Image, mask: sitk.Image, target_spacing: Tuple[float, float, float], stem: str
    ) -> Tuple[Path, Path]:
        out_dir = self.config.output_dir / "resampled"
        out_dir.mkdir(parents=True, exist_ok=True)
        img_out = out_dir / f"{stem}_image.nii.gz"
        mask_out = out_dir / f"{stem}_mask.nii.gz"
        sitk.WriteImage(self._resample_to_spacing(image, target_spacing, False), str(img_out))
        sitk.WriteImage(self._resample_to_spacing(mask, target_spacing, True), str(mask_out))
        return img_out, mask_out
```

---

## 九、单元测试要点

```python
# tests/test_qc.py

import pytest
from app.qc import QCAgent, QCConfig, ImageMaskPair, QCStatus

def test_mask_empty(tmp_path):
    """全零 mask 应被标记为失败"""
    ...

def test_dimension_mismatch(tmp_path):
    """尺寸不一致应被标记为失败"""
    ...

def test_spacing_resample(tmp_path):
    """spacing 不一致时，resample 后应通过"""
    ...

def test_ct_value_range_warning():
    """CT 值域超范围时，策略为警告不失败"""
    ...

def test_mri_uniform_signal_fail():
    """MRI 信号过于单一应失败"""
    ...

def test_dicom_dir_read(tmp_path):
    """DICOM 目录读取"""
    ...

def test_parallel_fallback():
    """多进程失败后回退串行"""
    ...
```

---

## 十、关键设计决策

1. **Mask 插值必须用 NearestNeighbor**：线性/Bspline 插值会在标签边界产生中间值，导致 PyRadiomics 的 shape 特征计算错误。
2. **Image 插值默认 Linear**：保留 CT/MRI 信号的连续性，对 firstorder/texture 特征更合理。
3. **Resample 文件缓存**：若配置了 `target_spacing`，将结果写入 `./tmp/qc/resampled/`，Feature Agent 直接读取缓存路径。避免重复计算。
4. **CT 值域超范围不失败**：某些增强 CT 或特殊协议可能超出 -1000~3000，作为警告记录，不阻断流程。
5. **Spacing 对齐策略**：先对齐 image-mask 的 spacing，再统一 resample 到 target spacing。两步逻辑清晰，避免嵌套。
6. **多进程回退**：`ProcessPoolExecutor` 对复杂对象可能 pickle 失败，捕获异常后自动串行处理，保证鲁棒性。

---

## 十一、参考资料

- SimpleITK Resample 官方文档：https://simpleitk.readthedocs.io/en/master/Documentation/docs/source/fundamentalConcepts.html
- PyRadiomics 输入要求：https://pyradiomics.readthedocs.io/en/latest/usage.html
- DICOM 读取：https://simpleitk.readthedocs.io/en/master/IO/DICOM.html

---

> 文档编写完成。本方案可直接交付同学 A 实现，无需引入 LLM 调用（QC Agent 不调用 LLM）。
