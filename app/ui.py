import traceback

import gradio as gr

from app.orchestrator import Orchestrator, register_default_handlers
from app.utils import parse_covariates


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
            base_url = gr.Textbox(label="Base URL", value="https://api.deepseek.com/v1")

        run_btn = gr.Button("运行分析")
        log = gr.Textbox(label="日志", lines=20, interactive=False)
        report_file = gr.File(label="生成报告")

        def run_analysis(img_dir, clinical, out_dir, mod, covs, key, m, url):
            if not img_dir or not img_dir.strip() or not clinical or not clinical.strip():
                return "错误：影像文件夹路径和临床表格路径不能为空", None

            try:
                orch = Orchestrator(
                    image_dir=img_dir,
                    clinical_path=clinical,
                    output_dir=out_dir,
                    modality=mod,
                    covariates=parse_covariates(covs),
                    api_key=key,
                    base_url=url,
                    model=m,
                )
                register_default_handlers(orch)

                logs = []
                def emitter(event):
                    logs.append(f"[{event.get('stage', '')}] {event['type']}: {event['message']}")

                orch.set_sse_emitter(emitter)
                for _ in orch.run():
                    pass

                report = orch.state.get("report")
                if not report or report.get("success") is False:
                    return "\n".join(logs) + "\n错误：流水线执行失败，未能生成报告", None

                report_path = report.get("report_path")
                return "\n".join(logs), report_path
            except Exception:
                return traceback.format_exc(), None

        run_btn.click(
            fn=run_analysis,
            inputs=[image_dir, clinical_path, output_dir, modality, covariates, api_key, model, base_url],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
