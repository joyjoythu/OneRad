import argparse
import logging
import sys
import traceback

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
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="")
    parser.add_argument("--resampled-pixel-spacing", default=None,
                        help="覆盖 pyradiomics 的 resampledPixelSpacing, e.g. '0.5,0.5,0.5'")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--ui", action="store_true", help="启动 Gradio UI")
    return parser.parse_args(argv)


def main():
    args = _parse_args()

    if args.ui or args.image_dir is None or args.clinical is None:
        from app.ui import create_ui
        demo = create_ui()
        demo.launch(css=CUSTOM_CSS)
        return

    from app.orchestrator import Orchestrator, register_default_handlers
    orch = Orchestrator(
        image_dir=args.image_dir,
        clinical_path=args.clinical,
        output_dir=args.output_dir,
        modality=args.modality,
        covariates=parse_covariates(args.covariates),
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
    print(f"Report: {orch.state.get('report', {}).get('report_path')}")


if __name__ == "__main__":
    main()
