import html
import traceback
from pathlib import Path
from typing import Optional

import gradio as gr

from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.ui_style import (
    CUSTOM_CSS,
    header_html,
    section_title_html,
    project_status_html,
    project_list_html,
    ICON_FOLDER,
    ICON_SETTINGS,
    ICON_GLOBE,
    ICON_FILE_CODE,
)
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


def _config_status_html(image_dir, clinical_path, is_save=False):
    """根据配置完整性返回对应的项目状态 HTML。"""
    if image_dir and image_dir.strip() and clinical_path and clinical_path.strip():
        if is_save:
            return project_status_html("success", "已就绪", "配置已保存，可开始分析")
        return project_status_html("info", "等待开始分析", "配置已填写，可保存或开始分析")
    return project_status_html("info", "等待配置", "请填写影像路径和临床表格")


def _error_html(msg: str) -> str:
    return f'<div style="color:#dc2626;font-size:13px;margin-top:6px;">{html.escape(msg)}</div>'


def create_ui(store: Optional[ProjectStore] = None):
    store = store or ProjectStore()

    def _on_project_select(project_id):
        if not project_id:
            return (
                "",  # current_project_id
                "## 当前项目: 未选择",  # project_title
                "", "", "./outputs", "auto", "", "deepseek-chat", "",  # 表单字段
                _config_status_html("", ""),  # status_msg
                None,  # report_file
            )
        project = store.load_project(project_id)
        if project is None:
            return (
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                project_status_html("error", "项目不存在", "项目加载失败"),
                None,
            )
        analysis = project.get("analysis", {})
        return (
            project_id,
            f"## 当前项目: {html.escape(project['name'])}",
            analysis.get("image_dir", ""),
            analysis.get("clinical_path", ""),
            analysis.get("output_dir", "./outputs"),
            analysis.get("modality", "auto"),
            analysis.get("covariates", ""),
            analysis.get("model", "deepseek-chat"),
            analysis.get("api_key", ""),
            _config_status_html(analysis.get("image_dir", ""), analysis.get("clinical_path", "")),
            None,
        )

    def _refresh_project_list(selected_id: str = ""):
        return gr.update(value=project_list_html(store.list_projects(), selected_id))

    def _on_select_bridge(project_id):
        if not project_id:
            return (
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                _config_status_html("", ""),
                None,
            )
        return _on_project_select(project_id)

    def _on_delete_bridge(project_id, current_id):
        if not project_id:
            return (
                gr.update(),  # project_list
                gr.update(),  # current_project_id
                gr.update(),  # project_title
                gr.update(),  # image_dir
                gr.update(),  # clinical_path
                gr.update(),  # output_dir
                gr.update(),  # modality
                gr.update(),  # covariates
                gr.update(),  # model
                gr.update(),  # api_key
                project_status_html("error", "删除失败", "未获取到项目 ID"),
                gr.update(),  # report_file
            )
        try:
            store.delete_project(project_id)
        except Exception as e:
            return (
                gr.update(),  # project_list
                gr.update(),  # current_project_id
                gr.update(),  # project_title
                gr.update(),  # image_dir
                gr.update(),  # clinical_path
                gr.update(),  # output_dir
                gr.update(),  # modality
                gr.update(),  # covariates
                gr.update(),  # model
                gr.update(),  # api_key
                project_status_html("error", "删除项目失败", str(e)),
                gr.update(),  # report_file
            )

        projects = store.list_projects()
        if not projects:
            return (
                _refresh_project_list(""),
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                project_status_html("info", "未选择项目", "请从左侧选择或新建项目"),
                None,
            )

        # 如果被删的是当前项目，自动选择第一个；否则保持当前项目
        next_id = projects[0]["id"] if project_id == current_id else current_id
        select_updates = list(_on_project_select(next_id))
        return (
            _refresh_project_list(next_id),
            *select_updates,
        )

    def on_create_project(name, path, description):
        if not name or not name.strip() or not path or not path.strip():
            return (
                _refresh_project_list(""),
                "",  # current_project_id
                "## 当前项目: 未选择",  # project_title
                "", "", "./outputs", "auto", "", "deepseek-chat", "",  # 表单字段
                project_status_html("error", "创建失败", "项目名称和路径不能为空"),
                None,  # report_file
                "", "", "",  # new_name, new_path, new_description
                gr.update(visible=True, value=_error_html("项目名称和路径不能为空")),  # create_error_msg
            )
        if any(p["name"] == name.strip() for p in store.list_projects()):
            return (
                _refresh_project_list(""),
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                project_status_html("error", "创建失败", "项目名称已存在"),
                None,
                "", "", "",
                gr.update(visible=True, value=_error_html("项目名称已存在，请使用其他名称")),
            )
        try:
            project = store.create_project(name.strip(), path.strip(), description or "")
        except Exception as e:
            return (
                _refresh_project_list(""),
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                project_status_html("error", "创建项目失败", str(e)),
                None,
                "", "", "",
                gr.update(visible=True, value=_error_html(str(e))),
            )

        select_updates = list(_on_project_select(project["id"]))
        return (
            _refresh_project_list(project["id"]),
            *select_updates,
            "", "", "",  # new_name, new_path, new_description
            gr.update(visible=False, value=""),  # create_error_msg
        )

    def on_save_config(project_id, image_dir, clinical_path, output_dir, modality, covariates, model, api_key):
        if not project_id:
            return project_status_html("error", "请先选择一个项目", "保存前需要选择项目")
        try:
            store.save_project_config(project_id, {
                "image_dir": image_dir or "",
                "clinical_path": clinical_path or "",
                "output_dir": output_dir or "./outputs",
                "modality": modality or "auto",
                "covariates": covariates or "",
                "model": model or "deepseek-chat",
                "api_key": api_key or "",
            })
            return _config_status_html(image_dir, clinical_path, is_save=True)
        except Exception as e:
            return project_status_html("error", "保存失败", str(e))

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
            "api_key": api_key or "",
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
        gr.HTML(header_html())

        current_project_id = gr.State("")

        with gr.Row():
            # 左侧项目侧边栏
            with gr.Column(scale=0, min_width=320, elem_classes=["onerad-card", "onerad-sidebar"]):
                gr.HTML(section_title_html(ICON_FOLDER, "项目"))

                with gr.Row():
                    btn_new = gr.Button("+ 新建项目", scale=1, elem_classes="onerad-btn-new")

                with gr.Row(visible=False) as new_project_row:
                    with gr.Column():
                        new_name = gr.Textbox(label="名称", elem_classes="onerad-input")
                        new_path = gr.Textbox(label="目录路径", elem_classes="onerad-input")
                        new_description = gr.Textbox(label="描述", elem_classes="onerad-input")
                        create_error_msg = gr.HTML(visible=False)
                        with gr.Row():
                            btn_create_confirm = gr.Button("创建")
                            btn_create_cancel = gr.Button("取消")

                # 项目列表：使用 HTML 自定义渲染，项目数量动态变化，无空行占位
                project_list = gr.HTML(
                    value=project_list_html(store.list_projects(), ""),
                    elem_classes="onerad-project-list",
                )

                # JS 事件桥：隐藏在页面中，供 HTML 列表触发选择/删除
                select_bridge = gr.Textbox(elem_id="project-select-bridge", visible=False)
                delete_bridge = gr.Textbox(elem_id="project-delete-bridge", visible=False)

            # 右侧工作区
            with gr.Column(scale=1, elem_classes="onerad-card"):
                with gr.Row():
                    project_title = gr.Markdown("## 当前项目: 未选择", scale=1)
                    status_msg = gr.HTML(scale=0)

                gr.HTML(section_title_html(ICON_FOLDER, "数据源"))
                with gr.Row():
                    image_dir = gr.Textbox(label="影像文件夹路径", elem_classes="onerad-input")
                    clinical_path = gr.Textbox(label="临床表格路径", elem_classes="onerad-input")

                gr.HTML(section_title_html(ICON_SETTINGS, "分析配置"))
                with gr.Row():
                    output_dir = gr.Textbox(label="输出目录", value="./outputs", elem_classes="onerad-input")
                    modality = gr.Dropdown(choices=["auto", "CT", "MRI"], value="auto", label="模态")
                    covariates = gr.Textbox(label="协变量（逗号分隔）", value="", elem_classes="onerad-input")

                gr.HTML(section_title_html(ICON_GLOBE, "AI 模型配置"))
                with gr.Row():
                    api_key = gr.Textbox(label="DeepSeek API Key", type="password", elem_classes="onerad-input")
                    model = gr.Textbox(label="模型", value="deepseek-chat", elem_classes="onerad-input")

                with gr.Row():
                    btn_save = gr.Button("保存项目配置", elem_classes="onerad-btn-secondary")
                    btn_run = gr.Button("运行分析", elem_classes="onerad-btn-primary")

                gr.HTML(section_title_html(ICON_FILE_CODE, "运行日志"))
                log = gr.Textbox(label="日志", lines=20, interactive=False, elem_classes="onerad-logs")
                report_file = gr.File(label="生成报告")

        # 事件绑定
        demo.load(_refresh_project_list, outputs=[project_list])

        btn_new.click(
            lambda: [gr.update(visible=True), gr.update(visible=False, value="")],
            outputs=[new_project_row, create_error_msg],
        )
        btn_create_cancel.click(
            lambda: [gr.update(visible=False), gr.update(visible=False, value="")],
            outputs=[new_project_row, create_error_msg],
        )
        btn_create_confirm.click(
            on_create_project,
            inputs=[new_name, new_path, new_description],
            outputs=[
                project_list,
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                status_msg,
                report_file,
                new_name,
                new_path,
                new_description,
                create_error_msg,
            ],
        ).then(lambda: gr.update(visible=False), outputs=[new_project_row])

        select_bridge.change(
            _on_select_bridge,
            inputs=[select_bridge],
            outputs=[
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                status_msg,
                report_file,
            ],
        )

        delete_bridge.change(
            _on_delete_bridge,
            inputs=[delete_bridge, current_project_id],
            outputs=[
                project_list,
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                status_msg,
                report_file,
            ],
        )

        btn_save.click(
            on_save_config,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, model, api_key],
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
    demo.launch(css=CUSTOM_CSS)
