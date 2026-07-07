import argparse


def main():
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", default=None)
    parser.add_argument("--clinical", default=None)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--ui", action="store_true", help="启动 Gradio UI")
    args = parser.parse_args()

    if args.ui or args.image_dir is None or args.clinical is None:
        from app.ui import create_ui
        demo = create_ui()
        demo.launch()
        return

    from app.orchestrator import Orchestrator, register_default_handlers
    orch = Orchestrator(
        image_dir=args.image_dir,
        clinical_path=args.clinical,
        output_dir=args.output_dir,
        modality=args.modality,
        covariates=[c.strip() for c in args.covariates.split(",") if c.strip()],
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    register_default_handlers(orch)
    for event in orch.run():
        print(event)
    print(f"Report: {orch.state.get('report', {}).get('report_path')}")


if __name__ == "__main__":
    main()
