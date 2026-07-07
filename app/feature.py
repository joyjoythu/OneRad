import os
import tempfile
import time
import logging
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# Lazy-loaded by _extract_single on first use in each process.
cir_get_features = None


def _prepare_yaml(
    yaml_path: str,
    resampled_pixel_spacing: Optional[Tuple[float, float, float]] = None,
) -> str:
    """Return a YAML path, optionally overriding resampledPixelSpacing.

    When ``resampled_pixel_spacing`` is provided, the base YAML is loaded,
    the ``setting.resampledPixelSpacing`` value is replaced, and the result
    is written to a temporary file. The temporary file path is returned.
    The original file is never modified.
    """
    if resampled_pixel_spacing is None:
        return yaml_path

    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"YAML 文件格式错误: {yaml_path}")

    config.setdefault("setting", {})
    config["setting"]["resampledPixelSpacing"] = list(resampled_pixel_spacing)

    fd, tmp_path = tempfile.mkstemp(suffix="_Params_labels.yaml", prefix="radiomics_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception:
        os.remove(tmp_path)
        raise

    logger.info("使用临时 YAML: %s, resampledPixelSpacing=%s", tmp_path, resampled_pixel_spacing)
    return tmp_path


class FeatureAgent:
    def __init__(self, n_workers: int = -1, timeout_per_case: int = 300):
        import multiprocessing as mp
        self.n_workers = n_workers if n_workers > 0 else max(1, mp.cpu_count() - 1)
        self.timeout_per_case = timeout_per_case

    def run(
        self,
        pairs: List[Dict[str, str]],
        yaml_path: str = "",
        n_jobs: int = -1,
        resampled_pixel_spacing: Optional[Tuple[float, float, float]] = None,
    ) -> Dict[str, Any]:
        if not pairs:
            return {"success": False, "message": "pairs 为空"}

        required = {"patient_id", "image_path", "mask_path"}
        for p in pairs:
            missing = required - set(p.keys())
            if missing:
                return {"success": False, "message": f"pair 缺少必要字段: {', '.join(sorted(missing))}"}

        if not yaml_path or not os.path.exists(yaml_path):
            return {"success": False, "message": f"YAML 配置不存在: {yaml_path}"}

        effective_yaml = yaml_path
        tmp_yaml = None
        try:
            effective_yaml = _prepare_yaml(yaml_path, resampled_pixel_spacing)
            if effective_yaml != yaml_path:
                tmp_yaml = effective_yaml
        except Exception as e:
            return {"success": False, "message": f"准备 YAML 失败: {e}"}

        t0 = time.time()
        n_workers = n_jobs if n_jobs > 0 else self.n_workers

        if n_workers == 1 or len(pairs) == 1:
            results = [self._extract_single((p["patient_id"], p["image_path"], p["mask_path"], effective_yaml)) for p in pairs]
        else:
            results = []
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(self._extract_single, (p["patient_id"], p["image_path"], p["mask_path"], effective_yaml)): p
                    for p in pairs
                }
                for future in as_completed(futures):
                    try:
                        results.append(future.result(timeout=self.timeout_per_case))
                    except Exception as e:
                        p = futures[future]
                        results.append((p["patient_id"], None, str(e)))

        if tmp_yaml is not None:
            try:
                os.remove(tmp_yaml)
            except OSError:
                pass

        rows = []
        failed_ids = []
        for pid, feats, err in results:
            if err:
                failed_ids.append(pid)
                logger.warning("特征提取失败 %s: %s", pid, err)
            else:
                row = {"patient_id": pid}
                row.update(feats)
                rows.append(row)

        if not rows:
            return {"success": False, "message": "所有样本特征提取均失败"}

        df = pd.DataFrame(rows).set_index("patient_id")
        df = df.apply(pd.to_numeric, errors="coerce")
        nan_cols = df.columns[df.isna().all()].tolist()
        if nan_cols:
            df = df.drop(columns=nan_cols)
            logger.info("剔除全为 NaN 的特征列: %s", nan_cols)

        zero_var = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
        if zero_var:
            df = df.drop(columns=zero_var)
            logger.info("剔除零方差特征列: %s", zero_var)

        if df.empty:
            return {"success": False, "message": "有效特征为空"}

        settings_used: Dict[str, Any] = {"yaml_path": yaml_path}
        if resampled_pixel_spacing is not None:
            settings_used["resampled_pixel_spacing"] = list(resampled_pixel_spacing)

        return {
            "success": True,
            "message": f"特征提取完成: {len(df)}/{len(pairs)} 成功, {len(df.columns)} 特征",
            "feature_df": df,
            "feature_names": df.columns.tolist(),
            "failed_ids": failed_ids,
            "zero_variance_features": zero_var,
            "settings_used": settings_used,
            "extraction_time_seconds": round(time.time() - t0, 2),
        }

    @staticmethod
    def _extract_single(args):
        global cir_get_features
        if cir_get_features is None:
            try:
                from DONGGUAN_NEW_Radiomic.Atsea_def import cir_get_features as _cir
                cir_get_features = _cir
            except Exception as e:
                logger.warning("无法导入 cir_get_features: %s", e)
                patient_id = args[0]
                return patient_id, None, f"cir_get_features 不可用（导入失败: {e}）"

        patient_id, image_path, mask_path, yaml_path = args
        try:
            if not os.path.exists(image_path):
                return patient_id, None, f"影像不存在: {image_path}"
            if not os.path.exists(mask_path):
                return patient_id, None, f"Mask 不存在: {mask_path}"
            feats = cir_get_features(image_path, mask_path, yaml_path)
            return patient_id, feats, None
        except Exception as e:
            return patient_id, None, str(e)
