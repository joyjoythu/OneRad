# Task 18: 实现 Gradio UI

### Task 18: 实现 Gradio UI

**Files:**
- Create: `app/ui.py`
- Modify: `main.py`

- [ ] **Step 1: 实现 Gradio 界面**

`app/ui.py`:
```python
import gradio as gr
from app.orchestrator import Orchestrator, register_default_handlers


def create_ui():
    with gr.Blocks(title="AutoRadiomics Agent") as demo:
        gr.Markdown("# AutoRadiomics Agent")

        with gr.Row():
            image_dir = gr.Textbox(label="影像文件夹路径")
            clinical_path = gr.Textbox(label="临床表格路径")
        with gr.Row():
            output_dir = gr.Textbox(label="输出目录", value="./output")
            modality = gr.Dropdown(choices=["auto", "CT", "MRI"], value="auto", label="模态")
            covariates = gr.Textbox(label="协变量（逗号分隔）", value="")
        with gr.Row():
            api_key = gr.Textbox(label="DeepSeek API Key", type="password")
            model = gr.Textbox(label="模型", value="deepseek-chat")

        run_btn = gr.Button("运行分析")
        log = gr.Textbox(label="日志", lines=20, interactive=False)
        report_file = gr.File(label="生成报告")

        def run_analysis(img_dir, clinical, out_dir, mod, covs, key, m):
            orch = Orchestrator(
                image_dir=img_dir,
                clinical_path=clinical,
                output_dir=out_dir,
                modality=mod,
                covariates=[c.strip() for c in covs.split(",") if c.strip()],
                api_key=key,
                model=m,
            )
            register_default_handlers(orch)

            logs = []
            def emitter(event):
                logs.append(f"[{event.get('stage', '')}] {event['type']}: {event['message']}")

            orch.set_sse_emitter(emitter)
            for _ in orch.run():
                pass

            report_path = orch.state.get("report", {}).get("report_path")
            return "\n".join(logs), report_path

        run_btn.click(
            fn=run_analysis,
            inputs=[image_dir, clinical_path, output_dir, modality, covariates, api_key, model],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
```

- [ ] **Step 2: 更新 main.py 支持 launch UI**

`main.py` 修改：
```python
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
```

- [ ] **Step 3: 运行 UI 导入测试**

Run: `python -c "from app.ui import create_ui; print('UI OK')"`
Expected: `UI OK`

- [ ] **Step 4: Commit**

```bash
git add app/ui.py main.py
git commit -m "feat: add Gradio UI and CLI integration"
```

---
