# Discovery Agent 实现方案

## 一、职责定位

Discovery Agent 是流水线的第一环，负责扫描用户上传的影像文件夹，将 **Image（原始影像）** 与 **Mask（分割掩码）** 按患者 ID 配对，输出结构化的配对列表和未配对文件列表，供下游 QC Agent 和 Matching Agent 使用。

| 项 | 内容 |
|---|---|
| **输入** | 文件夹路径（`str`） |
| **输出** | `DiscoveryResult` 对象（含配对列表 + 未配对列表 + 统计信息） |
| **下游消费者** | QC Agent（质检）、Matching Agent（与临床表格对齐） |
| **是否调用 LLM** | 是（两处：① 推断 ID 提取正则；② 兜底配对未匹配文件） |
| **依赖库** | `pathlib`, `re`, `pydantic`（或原生 dataclass） |

---

## 二、核心数据模型

### 2.1 `ImageEntry` — 单个文件条目

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

@dataclass(frozen=True)
class ImageEntry:
    """单个影像或 Mask 文件条目"""
    file_path: Path              # 绝对路径
    patient_id: str              # 从文件名提取的患者 ID（去扩展名后处理）
    modality: Literal["CT", "MRI", "PET", "UNKNOWN"]  # 模态推断
    file_type: Literal["image", "mask"]               # image 或 mask
    series_id: Optional[str]     # 序列 ID（可选，如时间点、模态后缀）
    
    def __post_init__(self):
        # frozen=True 时，校验逻辑放在外部函数，这里只做类型标注
        pass
```

### 2.2 `ImageMaskPair` — Image + Mask 配对

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ImageMaskPair:
    """一个配对单元：患者的一条 Image + 一条 Mask"""
    patient_id: str
    image: ImageEntry
    mask: ImageEntry
    series_id: Optional[str]    # 若存在时间点/序列信息
    
    @property
    def is_complete(self) -> bool:
        """配对是否完整（Image 和 Mask 都存在）"""
        return self.image is not None and self.mask is not None
```

### 2.3 `DiscoveryResult` — Agent 最终输出

```python
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class DiscoveryResult:
    """Discovery Agent 的输出，供 Orchestrator 写入 state dict"""
    
    # 核心输出
    pairs: List[ImageMaskPair] = field(default_factory=list)
    
    # 未配对文件（分类报告，便于用户排查）
    unpaired_images: List[ImageEntry] = field(default_factory=list)  # 只有 Image 无 Mask
    unpaired_masks: List[ImageEntry] = field(default_factory=list)   # 只有 Mask 无 Image
    
    # 统计信息
    total_files_scanned: int = 0
    total_images_found: int = 0
    total_masks_found: int = 0
    total_pairs_formed: int = 0
    
    # 模态分布
    modality_distribution: Dict[str, int] = field(default_factory=dict)
    
    # 状态标记
    success: bool = False
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        """序列化为字典，写入 state dict"""
        return {
            "pairs": [
                {
                    "patient_id": p.patient_id,
                    "image_path": str(p.image.file_path),
                    "mask_path": str(p.mask.file_path),
                    "modality": p.image.modality,
                    "series_id": p.series_id,
                }
                for p in self.pairs
            ],
            "unpaired_images": [str(e.file_path) for e in self.unpaired_images],
            "unpaired_masks": [str(e.file_path) for e in self.unpaired_masks],
            "stats": {
                "total_files": self.total_files_scanned,
                "images": self.total_images_found,
                "masks": self.total_masks_found,
                "pairs": self.total_pairs_formed,
                "modality_distribution": self.modality_distribution,
            },
            "success": self.success,
            "error_message": self.error_message,
        }
```

---

## 三、Discovery Agent 类定义

```python
import os
import re
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class DiscoveryAgent:
    """
    Discovery Agent：扫描文件夹，将 Image 与 Mask 按患者 ID 配对。
    
    设计原则：
    - 纯函数式核心，方便单元测试
    - 文件名规则可配置，覆盖常见命名约定
    - 异常不抛错，封装进 DiscoveryResult.error_message
    """
    
    # 支持的医学影像扩展名（按优先级排序，用于模态推断辅助）
    SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
        ".nii.gz", ".nii", ".nrrd", ".mha", ".mhd",
        ".dcm", ".dic", ".img", ".hdr"
    )
    
    # Mask 文件名关键词（不区分大小写）
    MASK_KEYWORDS: Tuple[str, ...] = (
        "mask", "seg", "segmentation", "label", "roi",
        "gt", "ground_truth", "annotation", "tumor",
    )
    
    # 模态推断关键词
    MODALITY_KEYWORDS: Dict[str, List[str]] = {
        "CT": ["ct", "computed_tomography", "computedtomography"],
        "MRI": ["mr", "mri", "magnetic", "t1", "t2", "t1c", "t2flair", "dwi", "adc", "flair"],
        "PET": ["pet", "positron"],
    }
    
    def __init__(
        self,
        llm_client=None,
        mask_keywords: Optional[Tuple[str, ...]] = None,
        id_pattern: Optional[str] = None,
        recursive: bool = True,
    ):
        """
        初始化 Discovery Agent。
        
        Args:
            llm_client: DeepSeek API 客户端（OpenAI 兼容），用于推断 ID 提取正则和兜底配对
            mask_keywords: 自定义 Mask 关键词，覆盖默认值
            id_pattern: 自定义患者 ID 提取正则，覆盖默认规则（含 LLM 推断结果）
            recursive: 是否递归扫描子文件夹
        """
        self.llm_client = llm_client  # 若未传入，回退到纯规则引擎
        self.mask_keywords = mask_keywords or self.MASK_KEYWORDS
        self.id_pattern = id_pattern  # 若为 None，先用 LLM 推断，再使用多规则 fallback
        self.recursive = recursive
    
    # ============================================================
    # 主入口
    # ============================================================
    
    def run(self, directory: str) -> DiscoveryResult:
        """
        主入口：扫描目录，完成 Image-Mask 配对。
        
        增强流程（含 LLM）：
        Step 1: 路径合法性检查
        Step 2: 递归扫描文件
        Step 3（可选 LLM）: 若未传入 id_pattern，采样文件名调用 DeepSeek 推断 ID 提取正则
        Step 4: 分类 Image / Mask（使用 LLM 推断或规则引擎提取 patient_id）
        Step 5: 按 patient_id 配对
        Step 6（可选 LLM）: 若未配对文件数 < 30，调用 DeepSeek 兜底配对
        Step 7: 模态分布统计
        Step 8: 组装结果
        """
        dir_path = Path(directory)
        
        # Step 1: 路径合法性检查
        if not self._validate_directory(dir_path):
            return DiscoveryResult(
                success=False,
                error_message=f"目录不存在或不可读: {directory}"
            )
        
        # Step 2: 递归扫描文件
        all_files = self._scan_files(dir_path)
        
        if len(all_files) == 0:
            return DiscoveryResult(
                success=False,
                error_message=f"目录中未找到支持的影像文件。支持的格式: {self.SUPPORTED_EXTENSIONS}"
            )
        
        # Step 3: 若未传入 id_pattern，尝试用 LLM 推断 ID 提取正则（仅调用一次 API）
        if self.id_pattern is None and self.llm_client is not None:
            inferred_pattern = self._infer_id_pattern_via_llm(all_files)
            if inferred_pattern:
                self.id_pattern = inferred_pattern
                logger.info(f"[LLM] 推断 ID 提取正则: {inferred_pattern}")
        
        # Step 4: 分类 Image / Mask
        images, masks = self._classify_files(all_files)
        
        if len(images) == 0:
            return DiscoveryResult(
                success=False,
                error_message="未找到 Image 文件（仅找到 Mask 或无匹配文件）。"
            )
        
        # Step 5: 按 patient_id 配对（规则引擎）
        pairs, unpaired_images, unpaired_masks = self._pair_images_masks(images, masks)
        
        # Step 6: 若未配对文件数 < 30，调用 LLM 兜底配对（token 可控）
        total_unpaired = len(unpaired_images) + len(unpaired_masks)
        if total_unpaired > 0 and total_unpaired < 30 and self.llm_client is not None:
            logger.info(f"[LLM] 兜底配对 {total_unpaired} 个未匹配文件")
            llm_pairs, llm_unpaired_images, llm_unpaired_masks = self._llm_resolve_unpaired(
                unpaired_images, unpaired_masks
            )
            pairs.extend(llm_pairs)
            unpaired_images = llm_unpaired_images
            unpaired_masks = llm_unpaired_masks
        
        # Step 7: 模态分布统计
        modality_dist = self._compute_modality_distribution(images)
        
        # Step 8: 组装结果
        result = DiscoveryResult(
            pairs=pairs,
            unpaired_images=unpaired_images,
            unpaired_masks=unpaired_masks,
            total_files_scanned=len(all_files),
            total_images_found=len(images),
            total_masks_found=len(masks),
            total_pairs_formed=len(pairs),
            modality_distribution=modality_dist,
            success=True,
        )
        
        logger.info(
            f"Discovery 完成: 扫描 {result.total_files_scanned} 个文件, "
            f"Image {result.total_images_found}, Mask {result.total_masks_found}, "
            f"配对 {result.total_pairs_formed}"
        )
        
        return result
```

---

## 四、核心函数实现

### 4.1 `_validate_directory` — 目录校验

```python
    def _validate_directory(self, dir_path: Path) -> bool:
        """检查目录是否存在、可读、非空。"""
        if not dir_path.exists():
            logger.error(f"目录不存在: {dir_path}")
            return False
        if not dir_path.is_dir():
            logger.error(f"路径不是目录: {dir_path}")
            return False
        if not os.access(dir_path, os.R_OK):
            logger.error(f"目录无读取权限: {dir_path}")
            return False
        return True
```

### 4.2 `_scan_files` — 递归扫描

```python
    def _scan_files(self, dir_path: Path) -> List[Path]:
        """
        扫描目录，收集所有支持格式的文件。
        
        注意：.nii.gz 是双扩展名，必须优先匹配，避免被拆成 .gz。
        """
        files = []
        
        if self.recursive:
            iterator = dir_path.rglob("*")
        else:
            iterator = dir_path.iterdir()
        
        for fpath in iterator:
            if not fpath.is_file():
                continue
            
            fpath_str = str(fpath).lower()
            
            # 优先匹配 .nii.gz（双扩展名）
            if fpath_str.endswith(".nii.gz"):
                files.append(fpath)
                continue
            
            # 单扩展名匹配
            if any(fpath_str.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS if ext != ".nii.gz"):
                files.append(fpath)
        
        logger.info(f"扫描到 {len(files)} 个候选文件")
        return sorted(files)  # 排序保证输出稳定
```

### 4.3 `_classify_files` — Image / Mask 分类

```python
    def _classify_files(self, files: List[Path]) -> Tuple[List[ImageEntry], List[ImageEntry]]:
        """
        将文件列表分类为 Image 和 Mask。
        
        分类规则（优先级从高到低）：
        1. 文件名含 Mask 关键词 → Mask
        2. 同目录下存在同名 + _mask 的文件 → 当前为 Image，_mask 为 Mask
        3. 其余 → Image
        
        返回:
            (images, masks): 两个 ImageEntry 列表
        """
        images: List[ImageEntry] = []
        masks: List[ImageEntry] = []
        
        # 第一遍：识别明确的 Mask
        file_entries: List[Tuple[Path, bool]] = []  # (path, is_mask_guess)
        
        for fpath in files:
            stem_lower = fpath.stem.lower()
            
            # 去除 .nii.gz 后 stem 是 .nii，需要额外处理
            name_lower = self._get_base_name(fpath).lower()
            
            is_mask = any(kw.lower() in name_lower for kw in self.mask_keywords)
            file_entries.append((fpath, is_mask))
        
        # 第二遍：处理同目录同名配对（如 patient001.nii + patient001_mask.nii）
        mask_stems = set()
        for fpath, is_mask in file_entries:
            if is_mask:
                base_name = self._get_base_name(fpath)
                # 去掉 mask 关键词，得到对应 image 的 stem
                clean_stem = self._remove_mask_suffix(base_name)
                mask_stems.add(clean_stem.lower())
        
        # 构建 entries
        for fpath, is_mask in file_entries:
            base_name = self._get_base_name(fpath)
            patient_id = self._extract_patient_id(base_name)
            modality = self._infer_modality(base_name)
            
            entry = ImageEntry(
                file_path=fpath,
                patient_id=patient_id,
                modality=modality,
                file_type="mask" if is_mask else "image",
                series_id=None,  # 后续可扩展
            )
            
            if is_mask:
                masks.append(entry)
            else:
                images.append(entry)
        
        logger.info(f"分类结果: Image {len(images)}, Mask {len(masks)}")
        return images, masks
    
    # --- 辅助方法 ---
    
    def _get_base_name(self, fpath: Path) -> str:
        """
        获取文件基础名（去除扩展名，处理 .nii.gz 特殊情况）。
        
        例：
            patient001.nii.gz → "patient001"
            patient002_mask.nrrd → "patient002_mask"
        """
        name = fpath.name
        if name.lower().endswith(".nii.gz"):
            return name[:-7]  # 去掉 .nii.gz
        return fpath.stem
    
    def _remove_mask_suffix(self, name: str) -> str:
        """从 Mask 文件名中去除 mask 后缀，得到对应 Image 的基础名。"""
        import re
        # 匹配常见模式：xxx_mask, xxx-seg, xxx_label, xxx_seg
        pattern = r'[_\-\.](mask|seg|segmentation|label|roi|gt|ground_truth|annotation|tumor)$'
        cleaned = re.sub(pattern, '', name, flags=re.IGNORECASE)
        return cleaned
```

### 4.4 `_extract_patient_id` — 患者 ID 提取

```python
    def _extract_patient_id(self, base_name: str) -> str:
        """
        从文件名基础名中提取患者 ID。
        
        提取策略（按优先级 fallback）：
        1. 用户自定义正则（self.id_pattern）
        2. 匹配纯数字前缀/主体（如 001, 12345）
        3. 匹配字母+数字组合（如 P001, Patient_123）
        4. 去除 mask 关键词后，取剩余部分作为 ID
        5. 全部失败 → 返回清理后的完整文件名（兜底）
        
        Args:
            base_name: 已去除扩展名的文件名（如 "P001_mask", "Patient_123_T1"）
            
        Returns:
            提取到的 patient_id 字符串
        """
        import re
        
        # 先去除 mask/seg 等后缀，避免干扰
        clean_name = self._remove_mask_suffix(base_name)
        clean_name = clean_name.strip('_-')  # 去除首尾分隔符
        
        # 策略 1: 用户自定义正则
        if self.id_pattern:
            match = re.search(self.id_pattern, clean_name)
            if match:
                return match.group(0)
        
        # 策略 2: 匹配纯数字序列（至少 2 位，避免单数字误匹配）
        # 支持前导零，如 001, 0123
        num_match = re.search(r'\b\d{2,}\b', clean_name)
        if num_match:
            return num_match.group(0)
        
        # 策略 3: 匹配字母+数字组合（如 P001, SUB_123, Case-45）
        alphanum_match = re.search(r'[A-Za-z]+[_\-]?\d+', clean_name)
        if alphanum_match:
            return alphanum_match.group(0)
        
        # 策略 4: 若 clean_name 非空，直接作为 ID
        if clean_name:
            return clean_name
        
        # 兜底：返回原始 base_name
        return base_name
```

### 4.5 `_infer_modality` — 模态推断

```python
    def _infer_modality(self, base_name: str) -> str:
        """
        从文件名推断成像模态。
        
        匹配规则：
        - CT 相关关键词 → "CT"
        - MRI 相关关键词（含 T1, T2, DWI, FLAIR 等） → "MRI"
        - PET 相关关键词 → "PET"
        - 无法推断 → "UNKNOWN"
        """
        name_lower = base_name.lower()
        
        for modality, keywords in self.MODALITY_KEYWORDS.items():
            for kw in keywords:
                # 使用单词边界匹配，避免 "pet" 匹配 "patient"
                # 但允许作为后缀，如 "T1", "T2"
                pattern = r'(?:^|[_\-])' + re.escape(kw) + r'(?:$|[_\-])'
                if re.search(pattern, name_lower):
                    return modality
        
        return "UNKNOWN"
```

### 4.6 `_pair_images_masks` — 核心配对算法

```python
    def _pair_images_masks(
        self,
        images: List[ImageEntry],
        masks: List[ImageEntry],
    ) -> Tuple[List[ImageMaskPair], List[ImageEntry], List[ImageEntry]]:
        """
        将 Image 和 Mask 按 patient_id 配对。
        
        配对规则：
        1. 精确匹配：Image.patient_id == Mask.patient_id
        2. 一个 Image 只配一个 Mask（1:1），若有多 Mask，选文件名最相似的
        3. 未配对的 Image / Mask 分别记录
        
        Args:
            images: ImageEntry 列表
            masks: ImageEntry 列表
            
        Returns:
            (pairs, unpaired_images, unpaired_masks)
        """
        from difflib import SequenceMatcher
        
        # 建立 patient_id → masks 映射（一个患者可能有多个 mask）
        mask_map: Dict[str, List[ImageEntry]] = {}
        for m in masks:
            mask_map.setdefault(m.patient_id, []).append(m)
        
        pairs: List[ImageMaskPair] = []
        used_masks: Set[int] = set()  # 记录已使用的 mask 索引（在 masks 列表中的位置）
        paired_image_indices: Set[int] = set()
        
        for img_idx, img in enumerate(images):
            pid = img.patient_id
            
            if pid not in mask_map or not mask_map[pid]:
                continue  # 无对应 Mask，留到 unpaired
            
            candidates = mask_map[pid]
            
            if len(candidates) == 1:
                # 唯一候选
                chosen_mask = candidates[0]
            else:
                # 多个 Mask：选与 Image 文件名相似度最高的
                img_name = self._get_base_name(img.file_path)
                
                best_mask = None
                best_score = -1.0
                for m in candidates:
                    m_name = self._get_base_name(m.file_path)
                    score = SequenceMatcher(None, img_name.lower(), m_name.lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best_mask = m
                chosen_mask = best_mask
            
            # 标记 mask 已使用（从 mask_map 中移除，防止复用）
            mask_map[pid].remove(chosen_mask)
            used_masks.add(id(chosen_mask))
            paired_image_indices.add(img_idx)
            
            pairs.append(ImageMaskPair(
                patient_id=pid,
                image=img,
                mask=chosen_mask,
                series_id=None,
            ))
        
        # 未配对的 Image
        unpaired_images = [img for i, img in enumerate(images) if i not in paired_image_indices]
        
        # 未配对的 Mask（mask_map 中剩余的）
        unpaired_masks = []
        for mlist in mask_map.values():
            unpaired_masks.extend(mlist)
        
        logger.info(
            f"配对完成: {len(pairs)} 对配对, "
            f"{len(unpaired_images)} 个未配对 Image, "
            f"{len(unpaired_masks)} 个未配对 Mask"
        )
        
        return pairs, unpaired_images, unpaired_masks
```

### 4.7 `_compute_modality_distribution` — 模态统计

```python
    def _compute_modality_distribution(self, images: List[ImageEntry]) -> Dict[str, int]:
        """统计 Image 的模态分布。"""
        dist = {}
        for img in images:
            mod = img.modality
            dist[mod] = dist.get(mod, 0) + 1
        return dist
```

### 4.8 `_infer_id_pattern_via_llm` — LLM 推断 ID 提取正则

```python
    def _infer_id_pattern_via_llm(self, all_files: List[Path]) -> Optional[str]:
        """
        采样文件名，调用 DeepSeek API 推断患者 ID 提取正则。
        
        策略：
        - 采样前 20 个文件名（image + mask 混合），控制 token 消耗
        - 只调用一次 API，返回结果缓存到 self.id_pattern
        - 若 API 失败或返回无效正则，返回 None，回退到规则引擎
        
        Args:
            all_files: 扫描到的所有文件路径列表
            
        Returns:
            推断出的正则表达式字符串，或 None
        """
        import json
        
        if self.llm_client is None:
            return None
        
        # 采样前 20 个文件名（去重后）
        samples = []
        seen = set()
        for fpath in all_files:
            name = self._get_base_name(fpath)
            if name not in seen:
                samples.append(name)
                seen.add(name)
            if len(samples) >= 20:
                break
        
        if len(samples) < 2:
            return None  # 样本太少，不调用 LLM
        
        ID_EXTRACTION_SYSTEM = (
            "你是一个医学影像数据命名规范分析专家。"
            "请根据提供的文件名样本，推断患者ID的提取规则，返回一个Python正则表达式字符串。"
            "要求：\n"
            "1. 正则只提取患者ID部分，不包含模态、序列、mask等后缀\n"
            "2. 尽可能通用，能覆盖所有样本\n"
            "3. 只输出纯JSON格式：{\"pattern\": \"正则表达式字符串\", \"explanation\": \"简要说明\"}"
        )
        
        ID_EXTRACTION_USER = (
            "以下是一组医学影像文件名样本（image和mask混在一起）：\n"
            + "\n".join(samples)
            + "\n\n请推断患者ID的提取正则表达式。"
        )
        
        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": ID_EXTRACTION_SYSTEM},
                    {"role": "user", "content": ID_EXTRACTION_USER},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            
            result = json.loads(response.choices[0].message.content)
            pattern = result.get("pattern", "")
            
            # 验证正则是否有效
            re.compile(pattern)
            logger.info(f"[LLM] 推断 ID 正则成功: {pattern}")
            return pattern
            
        except Exception as e:
            logger.warning(f"[LLM] 推断 ID 正则失败: {e}，回退到规则引擎")
            return None
```

### 4.9 `_llm_resolve_unpaired` — LLM 兜底配对未匹配文件

```python
    def _llm_resolve_unpaired(
        self,
        unpaired_images: List[ImageEntry],
        unpaired_masks: List[ImageEntry],
    ) -> Tuple[List[ImageMaskPair], List[ImageEntry], List[ImageEntry]]:
        """
        将规则引擎未配对的文件，调用 DeepSeek API 做兜底配对。
        
        触发条件：未配对文件数 < 30（控制 token 消耗）。
        策略：
        - 将未配对的 image 和 mask 文件名传给 LLM
        - LLM 判断哪些属于同一患者（即使 ID 格式不同，如 P001 vs patient_001）
        - 返回配对结果，剩余仍未配对的保留在 unpaired 列表中
        
        Args:
            unpaired_images: 规则引擎未配对的 Image 列表
            unpaired_masks: 规则引擎未配对的 Mask 列表
            
        Returns:
            (llm_pairs, remaining_unpaired_images, remaining_unpaired_masks)
        """
        import json
        
        if self.llm_client is None:
            return [], unpaired_images, unpaired_masks
        
        total_unpaired = len(unpaired_images) + len(unpaired_masks)
        if total_unpaired >= 30:
            logger.info(f"[LLM] 未配对文件数 {total_unpaired} >= 30，跳过 LLM 兜底，直接报给用户")
            return [], unpaired_images, unpaired_masks
        
        img_names = [self._get_base_name(e.file_path) for e in unpaired_images]
        mask_names = [self._get_base_name(e.file_path) for e in unpaired_masks]
        
        MATCHING_SYSTEM = (
            "你是医学影像数据配对助手。"
            "请将左侧的影像文件（images）与右侧的掩膜文件（masks）按患者ID配对。"
            "注意：同一患者的ID可能格式不同，比如 'P001' 和 'patient_001' 是同一个患者。"
            "输出纯JSON格式：{"
            "  \"pairs\": [{\"image\": \"...\", \"mask\": \"...\", \"patient_id\": \"...\"}],"
            "  \"unmatched_images\": [...],"
            "  \"unmatched_masks\": [...]"
            "}"
        )
        
        MATCHING_USER = (
            "以下文件未能通过规则引擎自动配对，请判断：\n\n"
            "影像文件（images）：\n" + "\n".join(img_names)
            + "\n\n掩膜文件（masks）：\n" + "\n".join(mask_names)
        )
        
        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": MATCHING_SYSTEM},
                    {"role": "user", "content": MATCHING_USER},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            
            result = json.loads(response.choices[0].message.content)
            llm_pairs = result.get("pairs", [])
            
            # 将 LLM 返回的配对结果转换为 ImageMaskPair
            pairs: List[ImageMaskPair] = []
            used_img_names = set()
            used_mask_names = set()
            
            for p in llm_pairs:
                img_name = p.get("image", "")
                mask_name = p.get("mask", "")
                patient_id = p.get("patient_id", "")
                
                # 在 unpaired_images 和 unpaired_masks 中查找对应条目
                img_entry = next(
                    (e for e in unpaired_images if self._get_base_name(e.file_path) == img_name),
                    None
                )
                mask_entry = next(
                    (e for e in unpaired_masks if self._get_base_name(e.file_path) == mask_name),
                    None
                )
                
                if img_entry and mask_entry and patient_id:
                    pairs.append(ImageMaskPair(
                        patient_id=patient_id,
                        image=img_entry,
                        mask=mask_entry,
                    ))
                    used_img_names.add(img_name)
                    used_mask_names.add(mask_name)
            
            remaining_images = [e for e in unpaired_images 
                                if self._get_base_name(e.file_path) not in used_img_names]
            remaining_masks = [e for e in unpaired_masks 
                               if self._get_base_name(e.file_path) not in used_mask_names]
            
            logger.info(
                f"[LLM] 兜底配对完成: {len(pairs)} 对新增配对, "
                f"剩余未配对 Image {len(remaining_images)}, Mask {len(remaining_masks)}"
            )
            return pairs, remaining_images, remaining_masks
            
        except Exception as e:
            logger.warning(f"[LLM] 兜底配对失败: {e}，保留原有未配对列表")
            return [], unpaired_images, unpaired_masks
```

---

## 五、完整代码（`discovery.py`）

```python
"""
discovery.py — Discovery Agent
负责扫描影像文件夹，将 Image 与 Mask 按患者 ID 配对。

作者: 同学 A
依赖: 无第三方库（纯标准库 + 可选 pydantic）
"""

import os
import re
import logging
from pathlib import Path
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from typing import List, Tuple, Set, Dict, Optional, Literal

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass(frozen=True)
class ImageEntry:
    """单个影像或 Mask 文件条目"""
    file_path: Path
    patient_id: str
    modality: Literal["CT", "MRI", "PET", "UNKNOWN"]
    file_type: Literal["image", "mask"]
    series_id: Optional[str] = None


@dataclass(frozen=True)
class ImageMaskPair:
    """Image + Mask 配对"""
    patient_id: str
    image: ImageEntry
    mask: ImageEntry
    series_id: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return self.image is not None and self.mask is not None


@dataclass
class DiscoveryResult:
    """Discovery Agent 输出"""
    pairs: List[ImageMaskPair] = field(default_factory=list)
    unpaired_images: List[ImageEntry] = field(default_factory=list)
    unpaired_masks: List[ImageEntry] = field(default_factory=list)
    total_files_scanned: int = 0
    total_images_found: int = 0
    total_masks_found: int = 0
    total_pairs_formed: int = 0
    modality_distribution: Dict[str, int] = field(default_factory=dict)
    success: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "pairs": [
                {
                    "patient_id": p.patient_id,
                    "image_path": str(p.image.file_path),
                    "mask_path": str(p.mask.file_path),
                    "modality": p.image.modality,
                    "series_id": p.series_id,
                }
                for p in self.pairs
            ],
            "unpaired_images": [str(e.file_path) for e in self.unpaired_images],
            "unpaired_masks": [str(e.file_path) for e in self.unpaired_masks],
            "stats": {
                "total_files": self.total_files_scanned,
                "images": self.total_images_found,
                "masks": self.total_masks_found,
                "pairs": self.total_pairs_formed,
                "modality_distribution": self.modality_distribution,
            },
            "success": self.success,
            "error_message": self.error_message,
        }


# ============================================================
# Discovery Agent 主类
# ============================================================

class DiscoveryAgent:
    """Discovery Agent：扫描文件夹，配对 Image 与 Mask。"""

    SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
        ".nii.gz", ".nii", ".nrrd", ".mha", ".mhd",
        ".dcm", ".dic", ".img", ".hdr"
    )

    MASK_KEYWORDS: Tuple[str, ...] = (
        "mask", "seg", "segmentation", "label", "roi",
        "gt", "ground_truth", "annotation", "tumor",
    )

    MODALITY_KEYWORDS: Dict[str, List[str]] = {
        "CT": ["ct", "computed_tomography", "computedtomography"],
        "MRI": ["mr", "mri", "magnetic", "t1", "t2", "t1c", "t2flair", "dwi", "adc", "flair"],
        "PET": ["pet", "positron"],
    }

    def __init__(
        self,
        llm_client=None,
        mask_keywords: Optional[Tuple[str, ...]] = None,
        id_pattern: Optional[str] = None,
        recursive: bool = True,
    ):
        self.llm_client = llm_client
        self.mask_keywords = mask_keywords or self.MASK_KEYWORDS
        self.id_pattern = id_pattern
        self.recursive = recursive

    # ------------------ 主入口 ------------------

    def run(self, directory: str) -> DiscoveryResult:
        """扫描目录并完成 Image-Mask 配对（含 LLM 增强）。"""
        dir_path = Path(directory)

        # 目录校验
        if not self._validate_directory(dir_path):
            return DiscoveryResult(
                success=False,
                error_message=f"目录不存在或不可读: {directory}"
            )

        # 扫描文件
        all_files = self._scan_files(dir_path)
        if len(all_files) == 0:
            return DiscoveryResult(
                success=False,
                error_message=f"目录中未找到支持的影像文件。支持的格式: {self.SUPPORTED_EXTENSIONS}"
            )

        # LLM 推断 ID 提取正则（仅一次 API 调用）
        if self.id_pattern is None and self.llm_client is not None:
            inferred_pattern = self._infer_id_pattern_via_llm(all_files)
            if inferred_pattern:
                self.id_pattern = inferred_pattern
                logger.info(f"[LLM] 推断 ID 提取正则: {inferred_pattern}")

        # 分类
        images, masks = self._classify_files(all_files)
        if len(images) == 0:
            return DiscoveryResult(
                success=False,
                error_message="未找到 Image 文件（仅找到 Mask 或无匹配文件）。"
            )

        # 配对（规则引擎）
        pairs, unpaired_images, unpaired_masks = self._pair_images_masks(images, masks)

        # LLM 兜底未配对文件（token 可控，<30 才调用）
        total_unpaired = len(unpaired_images) + len(unpaired_masks)
        if total_unpaired > 0 and total_unpaired < 30 and self.llm_client is not None:
            logger.info(f"[LLM] 兜底配对 {total_unpaired} 个未匹配文件")
            llm_pairs, llm_unpaired_images, llm_unpaired_masks = self._llm_resolve_unpaired(
                unpaired_images, unpaired_masks
            )
            pairs.extend(llm_pairs)
            unpaired_images = llm_unpaired_images
            unpaired_masks = llm_unpaired_masks

        # 统计
        modality_dist = self._compute_modality_distribution(images)

        result = DiscoveryResult(
            pairs=pairs,
            unpaired_images=unpaired_images,
            unpaired_masks=unpaired_masks,
            total_files_scanned=len(all_files),
            total_images_found=len(images),
            total_masks_found=len(masks),
            total_pairs_formed=len(pairs),
            modality_distribution=modality_dist,
            success=True,
        )

        logger.info(
            f"Discovery 完成: 扫描 {result.total_files_scanned} 个文件, "
            f"Image {result.total_images_found}, Mask {result.total_masks_found}, "
            f"配对 {result.total_pairs_formed}"
        )

        return result

    # ------------------ 核心步骤 ------------------

    def _validate_directory(self, dir_path: Path) -> bool:
        if not dir_path.exists():
            logger.error(f"目录不存在: {dir_path}")
            return False
        if not dir_path.is_dir():
            logger.error(f"路径不是目录: {dir_path}")
            return False
        if not os.access(dir_path, os.R_OK):
            logger.error(f"目录无读取权限: {dir_path}")
            return False
        return True

    def _scan_files(self, dir_path: Path) -> List[Path]:
        files = []
        iterator = dir_path.rglob("*") if self.recursive else dir_path.iterdir()

        for fpath in iterator:
            if not fpath.is_file():
                continue
            fpath_str = str(fpath).lower()
            if fpath_str.endswith(".nii.gz"):
                files.append(fpath)
            elif any(fpath_str.endswith(ext) for ext in self.SUPPORTED_EXTENSIONS if ext != ".nii.gz"):
                files.append(fpath)

        logger.info(f"扫描到 {len(files)} 个候选文件")
        return sorted(files)

    def _classify_files(self, files: List[Path]) -> Tuple[List[ImageEntry], List[ImageEntry]]:
        images: List[ImageEntry] = []
        masks: List[ImageEntry] = []

        for fpath in files:
            base_name = self._get_base_name(fpath)
            name_lower = base_name.lower()

            # 判断是否为 Mask
            is_mask = any(kw.lower() in name_lower for kw in self.mask_keywords)

            # 提取 ID 和模态
            clean_name = self._remove_mask_suffix(base_name) if is_mask else base_name
            patient_id = self._extract_patient_id(clean_name)
            modality = self._infer_modality(base_name)

            entry = ImageEntry(
                file_path=fpath,
                patient_id=patient_id,
                modality=modality,
                file_type="mask" if is_mask else "image",
            )

            if is_mask:
                masks.append(entry)
            else:
                images.append(entry)

        logger.info(f"分类结果: Image {len(images)}, Mask {len(masks)}")
        return images, masks

    def _pair_images_masks(
        self,
        images: List[ImageEntry],
        masks: List[ImageEntry],
    ) -> Tuple[List[ImageMaskPair], List[ImageEntry], List[ImageEntry]]:
        # 建立 patient_id -> masks 映射
        mask_map: Dict[str, List[ImageEntry]] = {}
        for m in masks:
            mask_map.setdefault(m.patient_id, []).append(m)

        pairs: List[ImageMaskPair] = []
        paired_image_indices: Set[int] = set()

        for img_idx, img in enumerate(images):
            pid = img.patient_id
            if pid not in mask_map or not mask_map[pid]:
                continue

            candidates = mask_map[pid]

            if len(candidates) == 1:
                chosen_mask = candidates[0]
            else:
                # 多 Mask：选文件名最相似的
                img_name = self._get_base_name(img.file_path)
                best_mask = max(
                    candidates,
                    key=lambda m: SequenceMatcher(
                        None, img_name.lower(), self._get_base_name(m.file_path).lower()
                    ).ratio()
                )
                chosen_mask = best_mask

            mask_map[pid].remove(chosen_mask)
            paired_image_indices.add(img_idx)

            pairs.append(ImageMaskPair(
                patient_id=pid,
                image=img,
                mask=chosen_mask,
            ))

        unpaired_images = [img for i, img in enumerate(images) if i not in paired_image_indices]
        unpaired_masks = [m for mlist in mask_map.values() for m in mlist]

        logger.info(f"配对完成: {len(pairs)} 对, 未配对 Image {len(unpaired_images)}, 未配对 Mask {len(unpaired_masks)}")
        return pairs, unpaired_images, unpaired_masks

    # ------------------ 辅助方法 ------------------

    def _get_base_name(self, fpath: Path) -> str:
        name = fpath.name
        if name.lower().endswith(".nii.gz"):
            return name[:-7]
        return fpath.stem

    def _remove_mask_suffix(self, name: str) -> str:
        pattern = r'[_\-\.](mask|seg|segmentation|label|roi|gt|ground_truth|annotation|tumor)$'
        cleaned = re.sub(pattern, '', name, flags=re.IGNORECASE)
        return cleaned.strip('_-')

    def _extract_patient_id(self, base_name: str) -> str:
        clean_name = self._remove_mask_suffix(base_name).strip('_-')

        if self.id_pattern:
            match = re.search(self.id_pattern, clean_name)
            if match:
                return match.group(0)

        # 纯数字
        num_match = re.search(r'\b\d{2,}\b', clean_name)
        if num_match:
            return num_match.group(0)

        # 字母+数字
        alphanum_match = re.search(r'[A-Za-z]+[_\-]?\d+', clean_name)
        if alphanum_match:
            return alphanum_match.group(0)

        return clean_name if clean_name else base_name

    def _infer_modality(self, base_name: str) -> str:
        name_lower = base_name.lower()
        for modality, keywords in self.MODALITY_KEYWORDS.items():
            for kw in keywords:
                pattern = r'(?:^|[_\-])' + re.escape(kw) + r'(?:$|[_\-])'
                if re.search(pattern, name_lower):
                    return modality
        return "UNKNOWN"

    def _compute_modality_distribution(self, images: List[ImageEntry]) -> Dict[str, int]:
        dist = {}
        for img in images:
            dist[img.modality] = dist.get(img.modality, 0) + 1
        return dist

    # ------------------ LLM 增强方法 ------------------

    def _infer_id_pattern_via_llm(self, all_files: List[Path]) -> Optional[str]:
        """
        采样文件名，调用 DeepSeek API 推断患者 ID 提取正则。
        只调用一次 API，若失败回退到规则引擎。
        """
        import json
        if self.llm_client is None:
            return None
        samples = []
        seen = set()
        for fpath in all_files:
            name = self._get_base_name(fpath)
            if name not in seen:
                samples.append(name)
                seen.add(name)
            if len(samples) >= 20:
                break
        if len(samples) < 2:
            return None
        ID_EXTRACTION_SYSTEM = (
            "你是一个医学影像数据命名规范分析专家。"
            "请根据提供的文件名样本，推断患者ID的提取规则，返回一个Python正则表达式字符串。"
            "要求：\n"
            "1. 正则只提取患者ID部分，不包含模态、序列、mask等后缀\n"
            "2. 尽可能通用，能覆盖所有样本\n"
            "3. 只输出纯JSON格式：{\"pattern\": \"正则表达式字符串\", \"explanation\": \"简要说明\"}"
        )
        ID_EXTRACTION_USER = (
            "以下是一组医学影像文件名样本（image和mask混在一起）：\n"
            + "\n".join(samples)
            + "\n\n请推断患者ID的提取正则表达式。"
        )
        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": ID_EXTRACTION_SYSTEM},
                    {"role": "user", "content": ID_EXTRACTION_USER},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            result = json.loads(response.choices[0].message.content)
            pattern = result.get("pattern", "")
            re.compile(pattern)
            logger.info(f"[LLM] 推断 ID 正则成功: {pattern}")
            return pattern
        except Exception as e:
            logger.warning(f"[LLM] 推断 ID 正则失败: {e}，回退到规则引擎")
            return None

    def _llm_resolve_unpaired(
        self,
        unpaired_images: List[ImageEntry],
        unpaired_masks: List[ImageEntry],
    ) -> Tuple[List[ImageMaskPair], List[ImageEntry], List[ImageEntry]]:
        """
        将规则引擎未配对的文件，调用 DeepSeek API 做兜底配对。
        触发条件：未配对文件数 < 30。
        """
        import json
        if self.llm_client is None:
            return [], unpaired_images, unpaired_masks
        total_unpaired = len(unpaired_images) + len(unpaired_masks)
        if total_unpaired >= 30:
            logger.info(f"[LLM] 未配对文件数 {total_unpaired} >= 30，跳过 LLM 兜底")
            return [], unpaired_images, unpaired_masks
        img_names = [self._get_base_name(e.file_path) for e in unpaired_images]
        mask_names = [self._get_base_name(e.file_path) for e in unpaired_masks]
        MATCHING_SYSTEM = (
            "你是医学影像数据配对助手。"
            "请将左侧的影像文件（images）与右侧的掩膜文件（masks）按患者ID配对。"
            "注意：同一患者的ID可能格式不同，比如 'P001' 和 'patient_001' 是同一个患者。"
            "输出纯JSON格式：{"
            "  \"pairs\": [{\"image\": \"...\", \"mask\": \"...\", \"patient_id\": \"...\"}],"
            "  \"unmatched_images\": [...],"
            "  \"unmatched_masks\": [...]"
            "}"
        )
        MATCHING_USER = (
            "以下文件未能通过规则引擎自动配对，请判断：\n\n"
            "影像文件（images）：\n" + "\n".join(img_names)
            + "\n\n掩膜文件（masks）：\n" + "\n".join(mask_names)
        )
        try:
            response = self.llm_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": MATCHING_SYSTEM},
                    {"role": "user", "content": MATCHING_USER},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            result = json.loads(response.choices[0].message.content)
            llm_pairs = result.get("pairs", [])
            pairs: List[ImageMaskPair] = []
            used_img_names = set()
            used_mask_names = set()
            for p in llm_pairs:
                img_name = p.get("image", "")
                mask_name = p.get("mask", "")
                patient_id = p.get("patient_id", "")
                img_entry = next(
                    (e for e in unpaired_images if self._get_base_name(e.file_path) == img_name),
                    None
                )
                mask_entry = next(
                    (e for e in unpaired_masks if self._get_base_name(e.file_path) == mask_name),
                    None
                )
                if img_entry and mask_entry and patient_id:
                    pairs.append(ImageMaskPair(
                        patient_id=patient_id,
                        image=img_entry,
                        mask=mask_entry,
                    ))
                    used_img_names.add(img_name)
                    used_mask_names.add(mask_name)
            remaining_images = [e for e in unpaired_images
                                if self._get_base_name(e.file_path) not in used_img_names]
            remaining_masks = [e for e in unpaired_masks
                               if self._get_base_name(e.file_path) not in used_mask_names]
            logger.info(
                f"[LLM] 兜底配对完成: {len(pairs)} 对新增配对, "
                f"剩余未配对 Image {len(remaining_images)}, Mask {len(remaining_masks)}"
            )
            return pairs, remaining_images, remaining_masks
        except Exception as e:
            logger.warning(f"[LLM] 兜底配对失败: {e}，保留原有未配对列表")
            return [], unpaired_images, unpaired_masks


# ============================================================
# 便捷函数（对外暴露的普通函数接口）
# ============================================================

def discover_image_mask_pairs(directory: str, **kwargs) -> DiscoveryResult:
    """
    便捷函数：一行代码调用 Discovery Agent。
    
    Args:
        directory: 影像文件夹路径
        **kwargs: 传给 DiscoveryAgent.__init__ 的参数
        
    Returns:
        DiscoveryResult
        
    示例:
        result = discover_image_mask_pairs("/data/images")
        if result.success:
            print(f"找到 {len(result.pairs)} 对 Image-Mask")
    """
    agent = DiscoveryAgent(**kwargs)
    return agent.run(directory)
```

---

## 六、与上下游 Agent 的接口契约

### 6.1 上游（Orchestrator → Discovery）

| 参数 | 类型 | 说明 |
|------|------|------|
| `directory` | `str` | 用户上传的影像文件夹绝对路径（Orchestrator 确保路径存在） |

Orchestrator 调用示例：

```python
from discovery import DiscoveryAgent

discovery_agent = DiscoveryAgent(recursive=True)
result = discovery_agent.run(state["image_directory"])

if not result.success:
    # 触发中断：用户可选择跳过或终止
    raise AgentInterrupt(
        stage="DISCOVERY",
        reason=result.error_message,
        recoverable=False  # Discovery 失败无法跳过，因为后续全部依赖它
    )

# 写入 state，供下游使用
state["discovery"] = result.to_dict()
```

### 6.2 下游（Discovery → QC / Matching）

Discovery Agent 输出写入 `state["discovery"]`，下游各 Agent 从 state 读取所需字段：

**QC Agent 读取的字段：**

```python
pairs = state["discovery"]["pairs"]  # List[dict]
for pair in pairs:
    image_path = pair["image_path"]   # str
    mask_path = pair["mask_path"]     # str
    modality = pair["modality"]       # str
    patient_id = pair["patient_id"]   # str
```

**Matching Agent 读取的字段：**

```python
image_patient_ids = [p["patient_id"] for p in state["discovery"]["pairs"]]
# 与 clinical.csv 中的 ID 列进行对齐
```

**Report Agent 读取的字段（用于方法学描述）：**

```python
stats = state["discovery"]["stats"]
total_images = stats["images"]
total_masks = stats["masks"]
total_pairs = stats["pairs"]
modality_dist = stats["modality_distribution"]
```

### 6.3 接口契约表

| 契约项 | 约定 |
|--------|------|
| 路径格式 | 所有路径使用 `str(Path.resolve())` 存储，绝对路径，避免相对路径歧义 |
| patient_id | 统一为字符串类型（即使是纯数字），下游不强制转型 |
| 未配对文件 | 若 `unpaired_images` 或 `unpaired_masks` 非空，Orchestrator 应在 UI 显示警告日志，但不中断流水线 |
| 空配对列表 | `total_pairs_formed == 0` 时，`success` 必须为 `False`，触发不可恢复中断 |
| 模态标记 | `"UNKNOWN"` 表示无法推断，Feature Agent 需回退到默认参数 |

---

## 七、异常处理逻辑

Discovery Agent 采用 **"异常不抛错，封装进结果对象"** 的策略，所有错误信息写入 `DiscoveryResult.error_message`，由 Orchestrator 决定是否中断。

### 7.1 异常分类与处理

| 异常场景 | 触发条件 | 处理策略 | recoverable |
|----------|----------|----------|-------------|
| **目录不存在** | `directory` 路径无效 | `success=False`，返回错误信息 | `False`（无法恢复） |
| **目录不可读** | 权限不足 | 同上 | `False` |
| **空文件夹** | 扫描到 0 个文件 | `success=False`，提示支持的格式 | `False` |
| **无 Image 文件** | 全是 Mask 或无匹配文件 | `success=False`，提示未找到 Image | `False` |
| **无 Mask 文件** | Image > 0, Mask = 0 | `success=True`（允许纯影像分析），`unpaired_masks=[]`，Orchestrator 记录警告 | `True`（可跳过 QC 中的 mask 检查） |
| **ID 提取全失败** | 所有文件的 `patient_id` 各不相同且无重复 | 正常返回，但 `total_pairs_formed=0`，触发中断 | `False` |
| **部分未配对** | 部分 Image 或 Mask 无对应项 | `success=True`，未配对的记入 `unpaired_*` 列表，Orchestrator 显示警告日志 | `True` |
| **重复 patient_id** | 同一患者有多个 Image 或多个 Mask | 取最相似文件名配对，剩余未配对，记录 warning 日志 | `True` |

### 7.2 关键异常处理代码

```python
# 空 mask 场景（在 Discovery 阶段，指无 mask 文件）
if len(masks) == 0:
    logger.warning("未找到 Mask 文件，将尝试纯影像分析（跳过 mask 相关质检）")
    # 不返回 False，因为 Analysis Agent 支持纯影像特征分析
    # 但 Orchestrator 需向用户显示警告

# 配对失败检测
if len(pairs) == 0 and len(images) > 0:
    logger.error(f"发现 {len(images)} 个 Image 但无法与 Mask 配对，请检查文件名中的患者 ID 是否一致")
    return DiscoveryResult(
        success=False,
        error_message=(
            f"Image-Mask 配对失败: 找到 {len(images)} 个 Image 和 {len(masks)} 个 Mask，"
            f"但患者 ID 无法对齐。常见原因:\n"
            f"1. Image 和 Mask 文件名中的 ID 格式不一致（如 001 vs P001）\n"
            f"2. Mask 文件命名不含 mask/seg/label 等关键词\n"
            f"3. 需要自定义 ID 提取正则"
        )
    )
```

### 7.3 警告日志规范

所有 warning 级别的日志使用统一前缀，便于 Orchestrator 捕获并推送给前端：

```python
logger.warning(f"[DISCOVERY-WARN] 患者 {pid} 有 {len(candidates)} 个 Mask，已自动选择最相似的: {chosen_path}")
logger.warning(f"[DISCOVERY-WARN] 未配对 Image: {unpaired.file_path}")
logger.warning(f"[DISCOVERY-WARN] 未配对 Mask: {unpaired.file_path}")
```

---

## 八、单元测试用例

```python
"""
test_discovery.py — Discovery Agent 单元测试
"""

import pytest
import tempfile
from pathlib import Path
from discovery import DiscoveryAgent, discover_image_mask_pairs


class TestDiscoveryAgent:
    def test_basic_pairing(self):
        """标准场景：Image 和 Mask 文件名完全对应"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            Path(tmpdir, "P001.nii.gz").touch()
            Path(tmpdir, "P001_mask.nii.gz").touch()
            Path(tmpdir, "P002.nii.gz").touch()
            Path(tmpdir, "P002_seg.nii.gz").touch()

            agent = DiscoveryAgent()
            result = agent.run(tmpdir)

            assert result.success is True
            assert result.total_pairs_formed == 2
            assert len(result.unpaired_images) == 0
            assert len(result.unpaired_masks) == 0

    def test_unpaired_files(self):
        """场景：部分 Image 无对应 Mask"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "P001.nii.gz").touch()
            Path(tmpdir, "P001_mask.nii.gz").touch()
            Path(tmpdir, "P003.nii.gz").touch()  # 无 Mask

            result = discover_image_mask_pairs(tmpdir)

            assert result.total_pairs_formed == 1
            assert len(result.unpaired_images) == 1

    def test_numeric_ids(self):
        """场景：纯数字 ID"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "001.nii.gz").touch()
            Path(tmpdir, "001_mask.nii.gz").touch()

            agent = DiscoveryAgent()
            result = agent.run(tmpdir)

            assert result.pairs[0].patient_id == "001"

    def test_modality_inference(self):
        """场景：模态自动推断"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "P001_CT.nii.gz").touch()
            Path(tmpdir, "P001_CT_mask.nii.gz").touch()
            Path(tmpdir, "P002_T1.nii.gz").touch()
            Path(tmpdir, "P002_T1_seg.nii.gz").touch()

            result = discover_image_mask_pairs(tmpdir)

            ct_pair = [p for p in result.pairs if p.patient_id == "P001"][0]
            mri_pair = [p for p in result.pairs if p.patient_id == "P002"][0]

            assert ct_pair.image.modality == "CT"
            assert mri_pair.image.modality == "MRI"

    def test_empty_directory(self):
        """场景：空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_image_mask_pairs(tmpdir)
            assert result.success is False
            assert "未找到" in result.error_message

    def test_custom_id_pattern(self):
        """场景：用户自定义 ID 正则"""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "SUB-01_T1.nii.gz").touch()
            Path(tmpdir, "SUB-01_mask.nii.gz").touch()

            agent = DiscoveryAgent(id_pattern=r'SUB-\d+')
            result = agent.run(tmpdir)

            assert result.pairs[0].patient_id == "SUB-01"
```

---

## 九、常见问题排查指南

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| "未找到支持的影像文件" | 格式不在支持列表 | 检查文件扩展名，或扩展 `SUPPORTED_EXTENSIONS` |
| "未找到 Image 文件" | Mask 关键词误匹配了所有文件 | 检查文件名是否都含 mask/seg 等词，调整 `mask_keywords` |
| "配对失败" | Image 和 Mask 的 patient_id 不一致 | 检查 ID 提取是否正确，考虑传入 `id_pattern` |
| 多个 Image 配到一个 Mask | 同一患者有多个时间点/序列 | 文件名中加入时间点标识，或拆分文件夹 |
| 模态推断为 UNKNOWN | 文件名不含 CT/MRI/PET 关键词 | Feature Agent 使用默认参数，不影响核心流程 |

---

## 十、版本记录

| 版本 | 日期 | 修改内容 |
|------|------|----------|
| v1.0 | — | 初始版本：文件扫描、ID 提取、Image/Mask 配对、模态推断 |

---

## 十一、LLM 调用说明

Discovery Agent 在系统 3 个 LLM 调用点之外，新增 **2 处** DeepSeek API 调用，均在 Discovery 阶段内部完成。

### 11.1 调用点 1：推断 ID 提取正则

| 项 | 内容 |
|---|---|
| **触发条件** | `id_pattern` 未传入（用户未指定），且 `llm_client` 已配置 |
| **输入** | 采样前 20 个不重复文件名（去扩展名） |
| **输出** | 一个 Python 正则表达式字符串，如 `r'P\d+'`、`r'SUB-\d+'` |
| **失败回退** | 返回 None，使用规则引擎 fallback（纯数字 → 字母+数字） |
| **Token 估算** | 20 个文件名 × 平均 20 字符 ≈ 400 输入 token，输出 < 100 token |
| **调用次数** | 每个数据集仅 1 次 |

### 11.2 调用点 2：兜底配对未匹配文件

| 项 | 内容 |
|---|---|
| **触发条件** | 规则引擎配对后仍有未配对文件，且未配对数 < 30，且 `llm_client` 已配置 |
| **输入** | 未配对 Image 文件名 + 未配对 Mask 文件名 |
| **输出** | JSON 格式的配对结果（image ↔ mask ↔ patient_id） |
| **失败回退** | 保留原有未配对列表，Orchestrator 显示警告 |
| **Token 估算** | < 30 个文件名 × 平均 20 字符 ≈ 600 输入 token，输出 < 300 token |
| **调用次数** | 每个数据集最多 1 次（未配对数 >= 30 时直接跳过，不浪费 token） |

### 11.3 为什么只在 Discovery 用 LLM？

命名规则推断是 Discovery 阶段独有的痛点：
- 不同数据集的患者 ID 格式千差万别（`001`、`P001`、`Patient_001`、`SUB-01`）
- 低年级同学写硬编码正则覆盖面有限，维护成本高
- LLM 看 20 个样本就能写出通用正则，一次性解决问题
- 兜底配对处理规则引擎的"漏网之鱼"（如 `P001` 和 `patient_001` 实为同一患者）

两处调用均遵循 **"能本地解决就不调 API"** 原则：
- 用户已传 `id_pattern` → 跳过 LLM 推断
- 未配对数 >= 30 → 跳过 LLM 兜底（token 太多，直接报给用户）
- LLM 返回无效 JSON 或正则不合法 → 自动回退，不中断流水线

### 11.4 Orchestrator 调用方式

```python
from discovery import DiscoveryAgent
import openai

llm_client = openai.OpenAI(
    api_key="sk-...",
    base_url="https://api.deepseek.com/v1"
)

agent = DiscoveryAgent(llm_client=llm_client, recursive=True)
result = agent.run(state["image_directory"])
```

若 `llm_client=None`（默认），Discovery Agent 完全退化为纯规则引擎，不触发任何 API 调用。
