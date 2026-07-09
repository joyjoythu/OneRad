import html
import logging
import os
import traceback
from pathlib import Path
from typing import Optional

import gradio as gr
import pandas as pd

from app.direct_analysis import run_direct_analysis
from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.ui_style import (
    CUSTOM_CSS,
    header_html,
    section_title_html,
    project_status_html,
    ICON_FOLDER,
    ICON_SETTINGS,
    ICON_GLOBE,
    ICON_FILE_CODE,
)
from app.ui_agent import create_agent_tab
from app.utils import parse_covariates


# 侧边栏最多同时显示的项目行数
MAX_PROJECTS = 20


def _run_analysis(
    img_dir,
    clinical,
    out_dir,
    mod,
    covs,
    key,
    m,
    yaml_path,
    max_lasso_features,
    n_splits,
):
    cached_feature_csv = os.path.join(out_dir or "./outputs", "radiomics_features.csv")
    has_cached_features = os.path.exists(cached_feature_csv)

    if not clinical or not clinical.strip():
        return "错误：临床表格路径不能为空", None

    if not has_cached_features and (not img_dir or not img_dir.strip()):
        return "错误：未检测到已提取的特征文件，请填写影像文件夹路径", None

    try:
        # If cached features exist, bypass the heavy image pipeline.
        if has_cached_features:
            logs = [f"[ANALYSIS] stage_start: 开始: ANALYSIS", f"检测到已存在的特征文件，直接用于分析: {cached_feature_csv}"]
            report_path = run_direct_analysis(
                feature_csv=cached_feature_csv,
                clinical=clinical,
                output_dir=out_dir or "./outputs",
                modality=mod or "auto",
                covariates=parse_covariates(covs),
                max_lasso_features=max_lasso_features,
                n_splits=n_splits,
                api_key=key,
                model=m or "deepseek-v4-pro",
            )
            logs.append(f"[ANALYSIS] stage_complete: 完成: ANALYSIS")
            return "\n".join(logs), report_path

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
            max_lasso_features=max_lasso_features,
            n_splits=n_splits,
        )
        register_default_handlers(orch)

        logs = []
        def emitter(event):
            logs.append(f"[{event.get('stage', '')}] {event['type']}: {event['message']}")

        orch.set_sse_emitter(emitter)
        for _ in orch.run():
            pass

        # Cache extracted features so subsequent UI runs can skip extraction.
        _cache_features(orch.state, out_dir or "./outputs")

        report = orch.state.get("report")
        if not report or report.get("success") is False:
            return "\n".join(logs) + "\n错误：流水线执行失败，未能生成报告", None

        report_path = report.get("report_path")
        return "\n".join(logs), report_path
    except Exception:
        return traceback.format_exc(), None


def _config_status_html(image_dir, clinical_path, is_save=False):
    """根据配置完整性返回对应的项目状态 HTML。"""
    if clinical_path and clinical_path.strip():
        if is_save:
            return project_status_html("success", "已就绪", "配置已保存，可开始分析")
        return project_status_html("info", "等待开始分析", "临床表格已填写，可开始分析")
    return project_status_html("info", "等待配置", "请填写影像路径和临床表格")


def _cache_features(state: dict, output_dir: str) -> None:
    """Persist extracted features so the UI can reuse them on the next run."""
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
    except Exception:
        logging.warning("特征矩阵缓存失败", exc_info=True)


def create_ui(store: Optional[ProjectStore] = None):
    store = store or ProjectStore()

    def _on_project_select(project_id):
        if not project_id:
            return (
                "",  # current_project_id
                "## 当前项目: 未选择",  # project_title
                "", "", "./outputs", "auto", "", "deepseek-v4-pro", "", 100, 5,  # 表单字段
                _config_status_html("", ""),  # status_msg
                None,  # report_file
            )
        project = store.load_project(project_id)
        if project is None:
            return (
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-v4-pro", "", 100, 5,
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
            analysis.get("model", "deepseek-v4-pro"),
            analysis.get("api_key", ""),
            int(analysis.get("max_lasso_features", 100)),
            int(analysis.get("n_splits", 5)),
            _config_status_html(analysis.get("image_dir", ""), analysis.get("clinical_path", "")),
            None,
        )

    def _refresh_buttons(projects, selected_id: str = ""):
        """根据项目列表生成 20 行按钮的更新序列（不再更新 visible，空行由 CSS 隐藏）。"""
        n = len(projects)
        updates = []
        for i in range(MAX_PROJECTS):
            if i < n:
                is_active = projects[i]["id"] == selected_id
                variant = "primary" if is_active else "secondary"
                updates.append(gr.update(value=projects[i]["name"], variant=variant))
                updates.append(gr.update(value="×"))
            else:
                updates.append(gr.update(value=""))
                updates.append(gr.update(value=""))
            # Row 始终可见，占位保持布局稳定
            updates.append(gr.update())
        return updates

    def _refresh_project_list(selected_id: str = ""):
        projects = store.list_projects()
        ids = [p["id"] for p in projects]
        return [gr.update(value=ids)] + _refresh_buttons(projects, selected_id)

    def _on_select_by_index(ids, idx):
        if idx >= len(ids):
            return [gr.update()] * 13
        return _on_project_select(ids[idx])

    def _on_delete_by_index(ids, idx, current_id):
        if idx >= len(ids):
            updates = [gr.update() for _ in range(74)]
            updates[72] = project_status_html("error", "删除失败", "项目索引无效")
            return tuple(updates)
        project_id = ids[idx]
        try:
            store.delete_project(project_id)
        except Exception as e:
            updates = [gr.update() for _ in range(74)]
            updates[72] = project_status_html("error", "删除项目失败", str(e))
            return tuple(updates)

        projects = store.list_projects()
        new_ids = [p["id"] for p in projects]
        next_id = projects[0]["id"] if projects and project_id == current_id else current_id
        select_updates = list(_on_project_select(next_id))
        return (
            gr.update(value=new_ids),
            *_refresh_buttons(projects, next_id),
            *select_updates,
        )

    def on_create_project(name, path, description):
        error_html = lambda msg: f'<div style="color:#dc2626;font-size:13px;margin-top:6px;">{html.escape(msg)}</div>'
        if not name or not name.strip() or not path or not path.strip():
            error_updates = [gr.update() for _ in range(78)]
            error_updates[72] = project_status_html("error", "创建失败", "项目名称和路径不能为空")
            error_updates[77] = gr.update(visible=True, value=error_html("项目名称和路径不能为空"))
            return tuple(error_updates)
        if any(p["name"] == name.strip() for p in store.list_projects()):
            error_updates = [gr.update() for _ in range(78)]
            error_updates[72] = project_status_html("error", "创建失败", "项目名称已存在")
            error_updates[77] = gr.update(visible=True, value=error_html("项目名称已存在，请使用其他名称"))
            return tuple(error_updates)
        try:
            project = store.create_project(name.strip(), path.strip(), description or "")
        except Exception as e:
            error_updates = [gr.update() for _ in range(78)]
            error_updates[72] = project_status_html("error", "创建项目失败", str(e))
            error_updates[77] = gr.update(visible=True, value=error_html(str(e)))
            return tuple(error_updates)

        projects = store.list_projects()
        select_updates = list(_on_project_select(project["id"]))
        return (
            gr.update(value=[p["id"] for p in projects]),
            *_refresh_buttons(projects, project["id"]),
            *select_updates,
            "",  # new_name
            "",  # new_path
            "",  # new_description
            gr.update(visible=False, value=""),  # create_error_msg
        )

    def on_save_config(project_id, image_dir, clinical_path, output_dir, modality, covariates, model, api_key, max_lasso_features, n_splits):
        if not project_id:
            return project_status_html("error", "请先选择一个项目", "保存前需要选择项目")
        try:
            store.save_project_config(project_id, {
                "image_dir": image_dir or "",
                "clinical_path": clinical_path or "",
                "output_dir": output_dir or "./outputs",
                "modality": modality or "auto",
                "covariates": covariates or "",
                "model": model or "deepseek-v4-pro",
                "api_key": api_key or "",
                "max_lasso_features": int(max_lasso_features) if max_lasso_features is not None else 100,
                "n_splits": int(n_splits) if n_splits is not None else 5,
            })
            return _config_status_html(image_dir, clinical_path, is_save=True)
        except Exception as e:
            return project_status_html("error", "保存失败", str(e))

    def on_run(project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model, max_lasso_features, n_splits):
        if not project_id:
            return "请先选择一个项目", None
        config = {
            "image_dir": image_dir or "",
            "clinical_path": clinical_path or "",
            "output_dir": output_dir or "./outputs",
            "modality": modality or "auto",
            "covariates": covariates or "",
            "model": model or "deepseek-v4-pro",
            "api_key": api_key or "",
            "max_lasso_features": int(max_lasso_features) if max_lasso_features is not None else 100,
            "n_splits": int(n_splits) if n_splits is not None else 5,
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
            config["max_lasso_features"],
            config["n_splits"],
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

                # 项目 ID 状态，供按钮索引查找
                project_ids_state = gr.State([p["id"] for p in store.list_projects()])

                # 项目列表：使用原生 Button，每行一个选择按钮 + 一个删除按钮
                # 所有行初始可见，空行通过 CSS 隐藏，避免 Gradio 动态 visible 更新不生效
                project_select_btns = []
                project_delete_btns = []
                project_rows = []
                projects_initial = store.list_projects()
                with gr.Column(elem_classes="onerad-project-list"):
                    for i in range(MAX_PROJECTS):
                        if i < len(projects_initial):
                            btn_value = projects_initial[i]["name"]
                            btn_variant = "secondary"
                            delete_value = "×"
                        else:
                            btn_value = ""
                            btn_variant = "secondary"
                            delete_value = ""
                        with gr.Row(visible=True) as row:
                            select_btn = gr.Button(btn_value, scale=4, variant=btn_variant, elem_classes="onerad-project-item")
                            delete_btn = gr.Button(delete_value, scale=0, min_width=40, elem_classes="onerad-project-delete")
                            project_rows.append(row)
                            project_select_btns.append(select_btn)
                            project_delete_btns.append(delete_btn)

            # 右侧工作区
            with gr.Column(scale=1, elem_classes="onerad-card"):
                with gr.Tabs():
                    with gr.Tab("影像组学分析"):
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
                        with gr.Row():
                            max_lasso_features = gr.Number(label="LASSO 最大特征数", value=100, precision=0, elem_classes="onerad-input")
                            n_splits = gr.Number(label="交叉验证折数", value=5, precision=0, elem_classes="onerad-input")

                        gr.HTML(section_title_html(ICON_GLOBE, "AI 模型配置"))
                        with gr.Row():
                            api_key = gr.Textbox(label="DeepSeek API Key", type="password", elem_classes="onerad-input")
                            model = gr.Dropdown(
                                label="模型",
                                choices=["deepseek-v4-pro", "deepseek-v4-flash"],
                                value="deepseek-v4-pro",
                                elem_classes="onerad-input",
                            )

                        with gr.Row():
                            btn_save = gr.Button("保存项目配置", elem_classes="onerad-btn-secondary")
                            btn_run = gr.Button("运行分析", elem_classes="onerad-btn-primary")

                        gr.HTML(section_title_html(ICON_FILE_CODE, "运行日志"))
                        log = gr.Textbox(label="日志", lines=20, interactive=False, elem_classes="onerad-logs")
                        report_file = gr.File(label="生成报告")

                    with gr.Tab("AI Agent"):
                        create_agent_tab(store, current_project_id)

        # 事件绑定
        all_project_outputs = [project_ids_state]
        for i in range(MAX_PROJECTS):
            all_project_outputs.extend([project_select_btns[i], project_delete_btns[i], project_rows[i]])

        demo.load(_refresh_project_list, outputs=all_project_outputs)

        create_outputs = list(all_project_outputs)
        create_outputs.extend([
            current_project_id,
            project_title,
            image_dir,
            clinical_path,
            output_dir,
            modality,
            covariates,
            model,
            api_key,
            max_lasso_features,
            n_splits,
            status_msg,
            report_file,
            new_name,
            new_path,
            new_description,
            create_error_msg,
        ])
        btn_create_confirm.click(
            on_create_project,
            inputs=[new_name, new_path, new_description],
            outputs=create_outputs,
        ).then(lambda: gr.update(visible=False), outputs=[new_project_row])

        btn_new.click(lambda: [gr.update(visible=True), gr.update(visible=False, value="")], outputs=[new_project_row, create_error_msg])
        btn_create_cancel.click(lambda: [gr.update(visible=False), gr.update(visible=False, value="")], outputs=[new_project_row, create_error_msg])

        for i in range(MAX_PROJECTS):
            project_select_btns[i].click(
                lambda ids, idx=i: _on_select_by_index(ids, idx),
                inputs=[project_ids_state],
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
                    max_lasso_features,
                    n_splits,
                    status_msg,
                    report_file,
                ],
            )
            delete_outputs = list(all_project_outputs)
            delete_outputs.extend([
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                max_lasso_features,
                n_splits,
                status_msg,
                report_file,
            ])
            project_delete_btns[i].click(
                lambda ids, cid, idx=i: _on_delete_by_index(ids, idx, cid),
                inputs=[project_ids_state, current_project_id],
                outputs=delete_outputs,
                js="() => confirm('确定要删除该项目吗？')",
            )

        btn_save.click(
            on_save_config,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, model, api_key, max_lasso_features, n_splits],
            outputs=[status_msg],
        )

        btn_run.click(
            on_run,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model, max_lasso_features, n_splits],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch(css=CUSTOM_CSS)
