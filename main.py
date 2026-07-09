import argparse
import logging
import os
import sys
import traceback

import pandas as pd

from app.direct_analysis import run_direct_analysis
from app.utils import parse_covariates, parse_float_tuple
from app.ui_style import CUSTOM_CSS


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", default=None)
    parser.add_argument("--clinical", default=None)
    parser.add_argument("--feature-csv", default=None,
                        help="已提取好的影像组学特征 CSV 路径（含 patient_id 列或以其为索引）")
    parser.add_argument("--label-col", default=None,
                        help="临床表格中的标签列名（默认自动识别 'Label' 或 0/1 二分类列）")
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="")
    parser.add_argument("--max-lasso-features", type=int, default=100,
                        help="LASSO 前单变量预筛选保留的最大影像组学特征数（默认 100）")
    parser.add_argument("--n-splits", type=int, default=5,
                        help="交叉验证折数（默认 5；小样本可设为 3）")
    parser.add_argument("--resampled-pixel-spacing", default=None,
                        help="覆盖 pyradiomics 的 resampledPixelSpacing, e.g. '0.5,0.5,0.5'")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--ui", action="store_true", help="启动 Gradio UI")
    return parser.parse_args(argv)


def _run_direct_analysis(args) -> str:
    """CLI wrapper around ``app.direct_analysis.run_direct_analysis``."""
    return run_direct_analysis(
        feature_csv=args.feature_csv,
        clinical=args.clinical,
        output_dir=args.output_dir,
        label_col=args.label_col,
        modality=args.modality,
        covariates=parse_covariates(args.covariates),
        max_lasso_features=args.max_lasso_features,
        n_splits=args.n_splits,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )


def main():
    args = _parse_args()

    if args.ui or (args.image_dir is None and args.feature_csv is None):
        from app.ui import create_ui
        demo = create_ui()
        demo.launch(css=CUSTOM_CSS)
        return

    if args.feature_csv:
        if not args.clinical:
            print("错误: --feature-csv 模式必须同时提供 --clinical", file=sys.stderr)
            sys.exit(1)
        try:
            report_path = _run_direct_analysis(args)
            print(f"Report: {report_path}")
        except Exception as e:
            print(f"直接分析失败: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        return

    if args.clinical is None:
        print("错误: 必须提供 --clinical", file=sys.stderr)
        sys.exit(1)

    # Auto-detect previously extracted features in the output directory.
    # If they exist, reuse them directly instead of re-running the heavy
    # image discovery / QC / feature extraction stages.
    import os
    cached_feature_csv = os.path.join(args.output_dir, "radiomics_features.csv")
    if os.path.exists(cached_feature_csv) and args.image_dir:
        print(f"检测到已存在的特征文件，直接用于分析: {cached_feature_csv}")
        print("如需重新提取特征，请删除该文件或更换 --output-dir")
        args.feature_csv = cached_feature_csv
        try:
            report_path = _run_direct_analysis(args)
            print(f"Report: {report_path}")
        except Exception as e:
            print(f"直接分析失败: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        return

    from app.orchestrator import Orchestrator, register_default_handlers
    orch = Orchestrator(
        image_dir=args.image_dir,
        clinical_path=args.clinical,
        output_dir=args.output_dir,
        modality=args.modality,
        covariates=parse_covariates(args.covariates),
        max_lasso_features=args.max_lasso_features,
        n_splits=args.n_splits,
        resampled_pixel_spacing=parse_float_tuple(args.resampled_pixel_spacing),
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    register_default_handlers(orch)
    try:
        for event in orch.run():
            print(event)
    except Exception as e:
        print(f"流水线执行失败: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    # Cache extracted features for subsequent runs.
    _save_extracted_features(orch.state, args.output_dir)

    print(f"Report: {orch.state.get('report', {}).get('report_path')}")


def _save_extracted_features(state: dict, output_dir: str) -> None:
    """Persist the extracted feature matrix to output_dir/radiomics_features.csv.

    This allows subsequent runs to skip the expensive feature extraction stage
    and start directly from LASSO + logistic regression.
    """
    import os

    feature_state = state.get("feature")
    if not isinstance(feature_state, dict):
        return
    feature_df = feature_state.get("feature_df")
    if not isinstance(feature_df, pd.DataFrame) or feature_df.empty:
        return

    try:
        os.makedirs(output_dir, exist_ok=True)
        cache_path = os.path.join(output_dir, "radiomics_features.csv")
        feature_df.reset_index().to_csv(cache_path, index=False)
        print(f"特征矩阵已缓存: {cache_path}")
    except Exception as e:
        logging.warning(f"特征矩阵缓存失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
