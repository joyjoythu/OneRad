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
