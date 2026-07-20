import os
import tempfile
import time
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import h5py
import numpy as np
import pandas as pd
import yaml

from app.cir_features import cir_get_features

logger = logging.getLogger(__name__)


def _h5_path_for_image(h5_dir: str, image_path: str, common_parent: str) -> str:
    """Derive an h5 file path from ``image_path``.

    If ``image_path`` contains an ``images/`` directory segment, the stem is
    built from the relative path below that segment so that sub-directory names
    are preserved. Otherwise the path is made relative to ``common_parent`` and
    the same underscore-joining is applied. If neither approach works, only the
    file stem is used.
    """
    image_path = os.path.normpath(image_path)

    # Prefer anchoring below an ``images`` directory when present.
    parts = Path(image_path).parts
    if "images" in parts:
        idx = parts.index("images") + 1
        rel = os.path.join(*parts[idx:]) if idx < len(parts) else os.path.basename(image_path)
    else:
        try:
            rel = os.path.relpath(image_path, common_parent)
        except ValueError:
            rel = os.path.basename(image_path)

    p = Path(rel)
    while True:
        name = p.name
        if name.endswith(".nii.gz"):
            p = p.with_name(name[:-7])
        elif name.endswith(".nii"):
            p = p.with_suffix("")
        else:
            break

    stem = str(p).replace(os.sep, "_").replace("/", "_")
    if not stem:
        stem = "features"
    return os.path.join(h5_dir, f"{stem}.h5")


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

    if len(resampled_pixel_spacing) != 3:
        raise ValueError(
            f"resampledPixelSpacing 需要 3 个数值, 得到 {len(resampled_pixel_spacing)}: {resampled_pixel_spacing}"
        )

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


def _settings_signature(
    yaml_path: str,
    resampled_pixel_spacing: Optional[Tuple[float, float, float]] = None,
) -> Dict[str, Any]:
    """Signature of the extraction settings, used to validate cached h5 files.

    Hashing the effective YAML content (rather than comparing paths) means
    edits to the same file are also detected.
    """
    with open(yaml_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return {
        "yaml_sha256": digest,
        "resampled_pixel_spacing": (
            list(resampled_pixel_spacing)
            if resampled_pixel_spacing is not None else None
        ),
    }


def _read_h5_features(h5_path: str) -> Optional[Dict[str, float]]:
    """Read cached per-case features from an h5 file.

    Returns a ``{feature_name: value}`` dict, or ``None`` when the file is
    missing/unreadable (the caller then re-extracts the case).
    """
    try:
        with h5py.File(h5_path, "r") as hf:
            names = [
                n.decode("utf-8") if isinstance(n, bytes) else str(n)
                for n in hf["feature_names"][()]
            ]
            values = hf["f_values"][()].reshape(-1)
        return {n: float(v) for n, v in zip(names, values)}
    except Exception:
        logger.warning("读取 h5 缓存失败，将重新提取: %s", h5_path, exc_info=True)
        return None


class FeatureAgent:
    def __init__(
        self,
        timeout_per_case: int = 300,
        extractor=None,
        output_dir: Optional[str] = None,
    ):
        self.timeout_per_case = timeout_per_case
        self._extractor = extractor
        self.output_dir = output_dir

    def _get_extractor(self):
        if self._extractor is not None:
            return self._extractor
        return cir_get_features

    def run(
        self,
        pairs: List[Dict[str, str]],
        yaml_path: str = "",
        n_jobs: int = -1,
        resampled_pixel_spacing: Optional[Tuple[float, float, float]] = None,
        output_dir: Optional[str] = None,
        progress_callback=None,
        cancel_event=None,
        resume: bool = True,
    ) -> Dict[str, Any]:
        """Extract features for all pairs, with h5-based resume support.

        When ``resume`` is True and an output directory is available, cases
        whose per-case h5 cache already exists (and whose stored settings
        signature matches the current YAML / resampling settings) are loaded
        from cache instead of being re-extracted. The merged
        ``radiomics_features.csv`` is always rewritten, so a lost or
        overwritten CSV is rebuilt from the h5 cache. Pass ``resume=False``
        to force re-extraction of every case.
        """
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

        def report(payload: Dict[str, Any]) -> None:
            """向调用方上报进度；回调异常不应中断提取。"""
            if progress_callback is None:
                return
            try:
                progress_callback(payload)
            except Exception:
                logger.debug("progress_callback 调用失败", exc_info=True)

        image_paths = [p["image_path"] for p in pairs]
        try:
            common_parent = os.path.commonpath(image_paths)
            if os.path.isfile(common_parent):
                common_parent = os.path.dirname(common_parent)
        except ValueError:
            common_parent = ""

        if cancel_event is None:
            logger.warning(
                "FeatureAgent.run: cancel_event 为 None，将无法响应 /stop 取消请求"
            )

        save_dir = output_dir or self.output_dir
        h5_dir = os.path.join(save_dir, "h5") if save_dir else None

        # 设置签名：与上次不一致时忽略 h5 缓存全量重提；无签名文件（旧版
        # 结果）时信任已有缓存。
        settings_sig = None
        sig_path = None
        settings_match = True
        if save_dir:
            settings_sig = _settings_signature(effective_yaml, resampled_pixel_spacing)
            sig_path = os.path.join(save_dir, "extraction_settings.json")
            if os.path.isfile(sig_path):
                try:
                    with open(sig_path, "r", encoding="utf-8") as f:
                        settings_match = json.load(f) == settings_sig
                except (OSError, json.JSONDecodeError):
                    settings_match = False
                if not settings_match:
                    logger.info("提取设置已变更（YAML 或重采样参数），忽略 h5 缓存全量重提")

        # 断点续提：命中 h5 缓存的病例直接读取，不再提取
        cached_rows: Dict[int, Dict[str, Any]] = {}
        todo: List[Tuple[int, Dict[str, str]]] = []
        for idx, p in enumerate(pairs):
            feats = None
            if resume and settings_match and h5_dir:
                h5_path = _h5_path_for_image(h5_dir, p["image_path"], common_parent)
                if os.path.isfile(h5_path):
                    feats = _read_h5_features(h5_path)
            if feats is not None:
                row = {"patient_id": p["patient_id"], "sequence": p.get("sequence", "")}
                row.update(feats)
                cached_rows[idx] = row
            else:
                todo.append((idx, p))

        total = len(pairs)
        report({"stage": "start", "current": 0, "total": total})
        if cached_rows:
            report({"stage": "resume", "n_skipped": len(cached_rows), "total": total})
        results: List[Tuple[int, Any]] = []
        cancelled = False
        for i, (idx, p) in enumerate(todo):
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    "FeatureAgent.run: 检测到取消信号，在 %d/%d 处停止提取",
                    len(cached_rows) + i + 1, total,
                )
                cancelled = True
                break
            report({
                "stage": "extracting",
                "current": len(cached_rows) + i + 1,
                "total": total,
                "patient_id": p["patient_id"],
            })
            results.append(
                (idx, self._extract_single(
                    (p["patient_id"], p["image_path"], p["mask_path"], effective_yaml)
                ))
            )

        rows = []
        failed_records = []
        new_successes: List[Tuple[int, str, str]] = []  # (row_pos, pid, image_path)
        result_by_idx = {idx: res for idx, res in results}
        for idx, p in enumerate(pairs):
            if idx in cached_rows:
                rows.append(cached_rows[idx])
                continue
            res = result_by_idx.get(idx)
            if res is None:
                continue  # 取消后未处理的病例
            pid, feats, err, image_path, mask_path = res
            if err:
                failed_records.append(
                    {
                        "patient_id": pid,
                        "image_path": image_path,
                        "mask_path": mask_path,
                        "reason": err,
                    }
                )
                logger.warning("特征提取失败 %s: %s", pid, err)
            else:
                row = {"patient_id": pid, "sequence": p.get("sequence", "")}
                row.update(feats)
                new_successes.append((len(rows), pid, image_path))
                rows.append(row)

        if tmp_yaml is not None:
            try:
                os.remove(tmp_yaml)
            except OSError:
                pass

        if not rows:
            if cancelled:
                return {"success": False, "cancelled": True, "message": "特征提取已取消，尚无完成样本"}
            return {"success": False, "message": "所有样本特征提取均失败"}

        failed_ids = [r["patient_id"] for r in failed_records]

        df = pd.DataFrame(rows)
        meta_cols = ["patient_id", "sequence"]
        feature_cols = [c for c in df.columns if c not in meta_cols]

        # Only feature columns should be coerced to numeric; metadata are strings.
        if feature_cols:
            df[feature_cols] = df[feature_cols].apply(pd.to_numeric, errors="coerce")

        nan_cols = [c for c in feature_cols if df[c].isna().all()]
        if nan_cols:
            df = df.drop(columns=nan_cols)
            feature_cols = [c for c in feature_cols if c not in nan_cols]
            logger.info("剔除全为 NaN 的特征列: %s", nan_cols)

        # 续提合并：缓存行与新提取行的特征集合可能不同（旧批次已做过列
        # 过滤），含缺失值的列直接剔除，保证矩阵完整。
        if cached_rows:
            partial_nan = [c for c in feature_cols if df[c].isna().any()]
            if partial_nan:
                df = df.drop(columns=partial_nan)
                feature_cols = [c for c in feature_cols if c not in partial_nan]
                logger.info("续提合并后剔除含缺失值的特征列: %s", partial_nan)

        zero_var = [c for c in feature_cols if len(df) > 1 and df[c].nunique(dropna=True) <= 1]
        if zero_var:
            df = df.drop(columns=zero_var)
            feature_cols = [c for c in feature_cols if c not in zero_var]
            logger.info("剔除零方差特征列: %s", zero_var)

        if df.empty or not feature_cols:
            return {"success": False, "message": "有效特征为空"}

        settings_used: Dict[str, Any] = {"yaml_path": yaml_path}
        if resampled_pixel_spacing is not None:
            settings_used["resampled_pixel_spacing"] = list(resampled_pixel_spacing)

        feature_path = None
        failed_path = None
        if save_dir:
            report({"stage": "finalizing", "current": len(rows), "total": total})
            os.makedirs(save_dir, exist_ok=True)
            feature_path = os.path.join(save_dir, "radiomics_features.csv")
            df.to_csv(feature_path, index=False)
            if failed_records:
                failed_path = os.path.join(save_dir, "failed_cases.csv")
                pd.DataFrame(
                    failed_records,
                    columns=["patient_id", "image_path", "mask_path", "reason"],
                ).to_csv(failed_path, index=False)
            elif os.path.isfile(os.path.join(save_dir, "failed_cases.csv")):
                # 本次无失败，清除上次的失败记录，避免过期信息
                os.remove(os.path.join(save_dir, "failed_cases.csv"))

            if settings_sig is not None and sig_path is not None:
                with open(sig_path, "w", encoding="utf-8") as f:
                    json.dump(settings_sig, f, ensure_ascii=False, indent=2)

            os.makedirs(h5_dir, exist_ok=True)
            for row_pos, pid, image_path in new_successes:
                values = df[feature_cols].iloc[row_pos].values.astype(np.float64).reshape(1, -1)
                h5_path = _h5_path_for_image(h5_dir, image_path, common_parent)
                with h5py.File(h5_path, "w") as hf:
                    hf.create_dataset("f_values", data=values, dtype="float64")
                    hf.create_dataset(
                        "feature_names",
                        data=np.array(feature_cols, dtype=h5py.string_dtype(encoding="utf-8")),
                    )
                    # patient_id/sequence 一并落盘，CSV 丢失时可仅从 h5 重建
                    hf.create_dataset("patient_id", data=pid)
                    hf.create_dataset(
                        "sequence", data=str(df.iloc[row_pos]["sequence"]))
                logger.info("单病例特征已保存: %s", h5_path)

            logger.info("特征矩阵已保存: %s", feature_path)

        image_to_pair = {p["image_path"]: p for p in pairs}
        failed_examples = []
        for r in failed_records:
            pair = image_to_pair.get(r["image_path"], {})
            seq = pair.get("sequence")
            failed_examples.append(f"{r['patient_id']}_{seq}" if seq else r["patient_id"])

        cache_note = f"（含缓存 {len(cached_rows)} 例）" if cached_rows else ""
        if cancelled:
            message = (
                f"特征提取已取消: 已完成 {len(df)}/{len(pairs)} 成功{cache_note}"
                f", {len(failed_records)} 失败, 部分结果已保存"
            )
        else:
            message = (f"特征提取完成: {len(df)}/{len(pairs)} 成功{cache_note}"
                       f", {len(failed_records)} 失败")

        return {
            "success": True,
            "cancelled": cancelled,
            "message": message,
            "feature_df": df,
            "feature_names": feature_cols,
            "failed_ids": failed_ids,
            "failed_examples": failed_examples,
            "zero_variance_features": zero_var,
            "settings_used": settings_used,
            "extraction_time_seconds": round(time.time() - t0, 2),
            "feature_path": feature_path,
            "failed_path": failed_path,
            "h5_dir": h5_dir,
            "resumed": bool(cached_rows),
            "n_skipped": len(cached_rows),
            "n_samples": len(pairs),
            "n_success": len(df),
            "n_failed": len(failed_records),
        }

    def _extract_single(self, args):
        extractor = self._get_extractor()
        if extractor is None:
            patient_id, image_path, mask_path = args[0], args[1], args[2]
            return patient_id, None, "cir_get_features 不可用（导入失败）", image_path, mask_path

        patient_id, image_path, mask_path, yaml_path = args
        try:
            if not os.path.exists(image_path):
                return patient_id, None, f"影像不存在: {image_path}", image_path, mask_path
            if not os.path.exists(mask_path):
                return patient_id, None, f"Mask 不存在: {mask_path}", image_path, mask_path
            feats = extractor(image_path, mask_path, yaml_path)
            return patient_id, feats, None, image_path, mask_path
        except Exception as e:
            return patient_id, None, str(e), image_path, mask_path
