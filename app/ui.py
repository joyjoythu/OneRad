import os
import traceback
from pathlib import Path

import gradio as gr

from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.utils import parse_covariates


def _run_analysis(img_dir, clinical, out_dir, mod, covs, key, m, yaml_path):
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
            base_url="https://api.deepseek.com/v1",
            model=m,
            yaml_path=yaml_path,
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


def create_ui():
    store = ProjectStore()

    def refresh_projects():
        projects = store.list_projects()
        choices = {p["name"]: p["id"] for p in projects}
        return gr.update(choices=choices if choices else None, value=None)

    def on_project_select(project_id):
        if not project_id:
            return [gr.update()] * 8 + ["", None]
        project = store.load_project(project_id)
        if project is None:
            return [gr.update()] * 8 + ["项目不存在", None]
        analysis = project.get("analysis", {})
        return (
            project_id,
            f"## 当前项目: {project['name']}",
            analysis.get("image_dir", ""),
            analysis.get("clinical_path", ""),
            analysis.get("output_dir", "./outputs"),
            analysis.get("modality", "auto"),
            analysis.get("covariates", ""),
            analysis.get("model", "deepseek-chat"),
            f"已加载项目: {project['name']}",
            None,
        )

    def on_create_project(name, path, description):
        if not name or not name.strip() or not path or not path.strip():
            return refresh_projects(), "项目名称和路径不能为空", "", ""
        try:
            project = store.create_project(name.strip(), path.strip(), description or "")
            choices = {p["name"]: p["id"] for p in store.list_projects()}
            return (
                gr.update(choices=choices, value=project["id"]),
                f"已创建项目: {project['name']}",
                "",
                "",
            )
        except Exception as e:
            return refresh_projects(), f"创建项目失败: {e}", "", ""

    def on_save_config(project_id, image_dir, clinical_path, output_dir, modality, covariates, model):
        if not project_id:
            return "请先选择一个项目"
        try:
            store.save_project_config(project_id, {
                "image_dir": image_dir or "",
                "clinical_path": clinical_path or "",
                "output_dir": output_dir or "./outputs",
                "modality": modality or "auto",
                "covariates": covariates or "",
                "model": model or "deepseek-chat",
            })
            return "项目配置已保存"
        except Exception as e:
            return f"保存失败: {e}"

    def on_run(project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model):
        if not project_id:
            return "请先选择一个项目", None
        config = {
            "image_dir": image_dir or "",
            "clinical_path": clinical_path or "",
            "output_dir": output_dir or "./outputs",
            "modality": modality or "auto",
            "covariates": covariates or "",
            "model": model or "deepseek-chat",
        }
        store.save_project_config(project_id, config)
        project = store.load_project(project_id)
        yaml_path = str(Path(project["path"]) / "Params_labels.yaml")
        run_id = store.record_run_start(project_id, config)
        logs, report_path = _run_analysis(
            config["image_dir"],
            config["clinical_path"],
            config["output_dir"],
            config["modality"],
            config["covariates"],
            api_key,
            config["model"],
            yaml_path,
        )
        status = "success" if report_path else "failed"
        summary = logs[-1000:] if isinstance(logs, str) else logs
        store.record_run_end(run_id, status, summary, report_path or "")
        return logs, report_path

    with gr.Blocks(title="OneRad") as demo:
        gr.Markdown("# OneRad")

        current_project_id = gr.State("")

        with gr.Row():
            # 左侧项目侧边栏
            with gr.Column(scale=0, min_width=260):
                gr.Markdown("## 项目")
                btn_new = gr.Button("+ 新建项目")
                project_selector = gr.Radio(label="选择项目", choices={})

                with gr.Row(visible=False) as new_project_row:
                    with gr.Column():
                        new_name = gr.Textbox(label="名称")
                        new_path = gr.Textbox(label="目录路径")
                        new_description = gr.Textbox(label="描述")
                        btn_create_confirm = gr.Button("创建")
                        btn_create_cancel = gr.Button("取消")

                status_msg = gr.Textbox(label="状态", interactive=False, lines=1)

            # 右侧工作区
            with gr.Column(scale=1):
                project_title = gr.Markdown("## 当前项目: 未选择")
                with gr.Row():
                    image_dir = gr.Textbox(label="影像文件夹路径")
                    clinical_path = gr.Textbox(label="临床表格路径")
                with gr.Row():
                    output_dir = gr.Textbox(label="输出目录", value="./outputs")
                    modality = gr.Dropdown(choices=["auto", "CT", "MRI"], value="auto", label="模态")
                    covariates = gr.Textbox(label="协变量（逗号分隔）", value="")
                with gr.Row():
                    api_key = gr.Textbox(label="DeepSeek API Key", type="password")
                    model = gr.Textbox(label="模型", value="deepseek-chat")

                with gr.Row():
                    btn_save = gr.Button("保存项目配置")
                    btn_run = gr.Button("运行分析")

                log = gr.Textbox(label="日志", lines=20, interactive=False)
                report_file = gr.File(label="生成报告")

        # 事件绑定
        demo.load(refresh_projects, outputs=[project_selector])

        btn_new.click(lambda: gr.update(visible=True), outputs=[new_project_row])
        btn_create_cancel.click(lambda: gr.update(visible=False), outputs=[new_project_row])
        btn_create_confirm.click(
            on_create_project,
            inputs=[new_name, new_path, new_description],
            outputs=[project_selector, status_msg, new_name, new_path],
        ).then(lambda: gr.update(visible=False), outputs=[new_project_row])

        project_selector.change(
            on_project_select,
            inputs=[project_selector],
            outputs=[
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                log,
                report_file,
            ],
        )

        btn_save.click(
            on_save_config,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, model],
            outputs=[status_msg],
        )

        btn_run.click(
            on_run,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
