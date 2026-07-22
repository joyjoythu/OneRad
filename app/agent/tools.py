import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage

from app.agent.safety import Sandbox, validate_plan
from app.code_runner import classify_risk, prepare_script, execute_script_if_safe
from app.radiomics_discovery import discover_pairs
from app.skills import load_skill


def build_tools(
    project_path: str,
    llm,
    allow_subagent: bool = False,
    readonly: bool = False,
):
    sandbox = Sandbox(project_path)
    tools: Dict[str, Any] = {}

    @tool
    def list_directory(path: str) -> str:
        """列出项目目录下的内容。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "list_directory", "args": {"path": path}})

    @tool
    def find_files(pattern: str, path: str = ".") -> str:
        """在项目目录内按通配符搜索文件。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "find_files", "args": {"pattern": pattern, "path": path}})

    @tool
    def get_file_info(path: str) -> str:
        """获取文件或目录的元信息。执行前需要用户确认。"""
        return json.dumps({"_pending_tool": "get_file_info", "args": {"path": path}})

    @tool
    def read_yaml(path: str, key: str = "") -> str:
        """读取项目内的 YAML 文件，返回解析后的内容（JSON）。
        key 可选：用点号路径取子节点，如 "setting.binWidth"，
        留空返回整个文件内容。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "read_yaml", "args": {"path": path, "key": key}},
            ensure_ascii=False,
        )

    @tool
    def read_json(path: str, key: str = "") -> str:
        """读取项目内的 JSON 文件，返回解析后的内容。
        key 可选：用点号路径取子节点，如 "setting.binWidth"，
        留空返回整个文件内容。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "read_json", "args": {"path": path, "key": key}},
            ensure_ascii=False,
        )

    @tool
    def create_json(path: str, content: Any) -> str:
        """在项目内新建 JSON 文件。content 为要写入的 JSON 内容（dict 或 list），
        格式化写入（缩进 2 空格、保留中文）。目标文件已存在时报错而不会覆盖；
        父目录不存在时自动创建。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "create_json",
             "args": {"path": path, "content": content}},
            ensure_ascii=False,
        )

    @tool
    def update_json(path: str, updates: Dict[str, Any]) -> str:
        """修改项目内的 JSON 文件。updates 为点号路径到值的映射，例如
        {"setting.binWidth": 10}；某个键的值传 null 表示删除该键。
        缺失的中间层级会自动创建为对象；目标文件必须已存在且是合法 JSON。
        执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "update_json",
             "args": {"path": path, "updates": updates}},
            ensure_ascii=False,
        )

    @tool
    def read_tabular_file(path: str, sheet_name: str = "", head: int = 20,
                          columns: List[str] = None) -> str:
        """读取项目内的 CSV 或 Excel 文件（按扩展名自动识别），返回智能预览：
        完整行列数、全部列名与类型、前 head 行数据。
        CSV 自动尝试 utf-8/gbk 编码；Excel 可用 sheet_name 指定工作表（默认第一个）；
        columns 可只读取指定列；head=0 时只看结构不取数据。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "read_tabular_file",
             "args": {"path": path, "sheet_name": sheet_name,
                      "head": head, "columns": columns}},
            ensure_ascii=False,
        )

    @tool
    def update_yaml(path: str, updates: Dict[str, Any]) -> str:
        """修改项目内的 YAML 文件。updates 为点号路径到值的映射，例如
        {"setting.binWidth": 10, "setting.normalize": True}。
        保留文件原有注释与格式；缺失的中间层级会自动创建；
        目标文件必须已存在。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "update_yaml",
             "args": {"path": path, "updates": updates}},
            ensure_ascii=False,
        )

    @tool
    def plan_file_operations(instruction: str) -> str:
        """根据用户需求生成文件操作计划。仅生成计划，不实际执行。"""
        snapshot = _directory_snapshot(sandbox.root)
        prompt = f"项目目录结构快照：\n{snapshot}\n\n用户需求：{instruction}"
        response = llm.invoke([
            SystemMessage(content=load_skill("file-operations")),
            HumanMessage(content=prompt),
        ])
        plan = _extract_json(response.content)
        validated = validate_plan(plan, sandbox)
        return json.dumps(validated)

    @tool
    def execute_python_script(description: str, code: str) -> str:
        """生成 Python 脚本并在项目虚拟环境中运行。所有脚本均需用户确认后执行；
        高风险脚本会在确认面板中以高危标记展示，不再直接拒绝。
        禁止用本工具提取影像组学特征（如自行调用 pyradiomics 或解析 h5 特征缓存）：
        特征提取必须改用 extract_radiomics_features 内置工具。"""
        meta = prepare_script(code, description, project_path)
        return json.dumps({"_pending_tool": "execute_python_script", "script": meta})

    @tool
    def discover_radiomics_pairs() -> str:
        """扫描项目下的 images/ 和 masks/，发现图像与掩膜的匹配计划。执行前需要用户确认。
        返回中的 existing_features 报告已有特征文件的覆盖情况（none/partial/
        complete 及病例数）：complete 时必须先用 ask_user_choice 询问用户是
        重新提取还是直接基于现有特征分析；partial 时按断点续提继续提取剩余
        病例，无需询问。"""
        result = discover_pairs(project_path)
        if not result.get("success", True):
            return json.dumps(result)
        return json.dumps({"_pending_tool": "discover_radiomics_pairs", **result})

    @tool
    def inspect_image_spacing(pairs: List[Dict[str, str]] = None) -> str:
        """检测队列影像的实际像素间距(spacing),为确认 resampledPixelSpacing 提供依据。
        pairs 可选:与 extract_radiomics_features 相同的配对列表(只读取其中的
        image_path);不传则扫描项目 images/ 目录下的全部 .nii.gz。
        返回各轴 spacing 的中位数/范围/不同取值数、逐例明细(病例数 ≤50 时)、
        建议值与读取失败列表。执行前需要用户确认。"""
        args: Dict[str, Any] = {}
        if pairs:
            args["pairs"] = pairs
        return json.dumps(
            {"_pending_tool": "inspect_image_spacing", "args": args},
            ensure_ascii=False,
        )

    @tool
    def extract_radiomics_features(pairs: List[Dict[str, str]], yaml_path: str = "",
                                   force_rerun: bool = False) -> str:
        """根据 image/mask 配对批量提取影像组学特征。执行前需要用户确认。

        默认断点续提：已有 h5 缓存且提取设置未变的病例直接读取缓存，不再
        重复提取；force_rerun=True 时忽略缓存，全部病例重新提取。
        """
        if not pairs:
            return json.dumps({"success": False, "error": "pairs must be a non-empty list"})
        if not yaml_path:
            yaml_path = "Params_labels.yaml"
        try:
            yaml_path = str(sandbox.resolve(yaml_path, must_exist=True))
        except FileNotFoundError:
            return json.dumps({"success": False, "error": f"YAML 配置不存在: {yaml_path}"})
        except ValueError:
            return json.dumps({"success": False, "error": f"路径超出项目目录: {yaml_path}"})

        for pair in pairs:
            for key in ("image_path", "mask_path"):
                rel_path = pair.get(key)
                if rel_path is None:
                    return json.dumps({"success": False, "error": f"pair missing {key}"})
                try:
                    sandbox.resolve(rel_path, must_exist=False)
                except ValueError:
                    return json.dumps({"success": False, "error": f"路径超出项目目录: {rel_path}"})

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            return json.dumps({"success": False, "error": f"YAML 解析失败: {e}"})

        output_dir = str(Path(project_path) / "radiomics_features")
        return json.dumps({
            "_pending_tool": "extract_radiomics_features",
            "meta": {
                "pairs": pairs,
                "n_cases": len(pairs),
                "yaml_path": yaml_path,
                "output_dir": output_dir,
                "force_rerun": force_rerun,
                "expected_outputs": ["radiomics_features.csv", "failed_cases.csv", "h5/*.h5"],
            },
        })

    @tool
    def run_radiomics_analysis(feature_csv: str = "", clinical: str = "",
                               id_col: str = "", label_col: str = "",
                               covariates: str = "", output_dir: str = "",
                               n_splits: Optional[int] = None,
                               max_lasso_features: Optional[int] = None,
                               random_state: Optional[int] = None) -> str:
        """对已提取的影像组学特征和临床表做 LASSO + 逻辑回归交叉验证分析，
        生成 ROC/校准/DCA 曲线、预测概率表和 Word/Markdown 报告。
        调用本工具前必须先用 ask_user_choice 询问用户是否调整分析参数
        （折数 n_splits 默认 5、LASSO 最大特征数 max_lasso_features 默认 100、
        随机种子 random_state 默认 42、协变量 covariates），用户要调整时
        通过对应参数传入。执行前需要用户确认；若输入文件或列名识别有歧义，
        会先返回需要向用户澄清的问题（status=need_clarification），
        此时请向用户提问并用用户回答重新调用本工具。
        分析会在输出目录保存 analysis_params.json 参数快照与
        run_analysis.py 复跑脚本，便于日后复现。
        参数均可留空：feature_csv 缺省用 radiomics_features/radiomics_features.csv，
        clinical 缺省时自动在项目内搜索，id_col/label_col 缺省时自动识别，
        covariates 为逗号分隔的临床协变量列名。"""
        from app.radiomics_analysis import inspect_analysis_inputs
        try:
            if feature_csv:
                feature_csv = str(sandbox.resolve(feature_csv, must_exist=False))
            if clinical:
                clinical = str(sandbox.resolve(clinical, must_exist=False))
            if output_dir:
                output_dir = str(sandbox.resolve(output_dir, must_exist=False))
        except ValueError:
            return json.dumps({"status": "error", "message": "路径超出项目目录"})
        cov_list = [c.strip() for c in covariates.split(",") if c.strip()]
        report = inspect_analysis_inputs(
            project_path,
            feature_csv=feature_csv,
            clinical=clinical,
            id_col=id_col,
            label_col=label_col,
            covariates=cov_list,
            output_dir=output_dir,
            n_splits=n_splits,
            max_lasso_features=max_lasso_features,
            random_state=random_state,
        )
        if report.get("status") != "ready":
            return json.dumps(report, ensure_ascii=False)
        return json.dumps(
            {"_pending_tool": "run_radiomics_analysis", "meta": report["resolved"]},
            ensure_ascii=False,
        )

    @tool
    def run_feature_statistics(feature_csv: str = "", clinical: str = "",
                               id_col: str = "", label_col: str = "",
                               selected_features_csv: str = "",
                               output_dir: str = "") -> str:
        """对 LASSO 筛选后的影像组学特征做分组统计分析（独立样本 t 检验 +
        Mann-Whitney U 检验），生成 Word 表格。执行前需要用户确认。
        所有参数均可留空：feature_csv 缺省用 radiomics_features/radiomics_features.csv，
        clinical 缺省时自动在项目内搜索，selected_features_csv 缺省用
        radiomics_analysis/selected_features.csv。"""
        from app.feature_statistics import inspect_statistics_inputs
        try:
            if feature_csv:
                feature_csv = str(sandbox.resolve(feature_csv, must_exist=False))
            if clinical:
                clinical = str(sandbox.resolve(clinical, must_exist=False))
            if selected_features_csv:
                selected_features_csv = str(sandbox.resolve(
                    selected_features_csv, must_exist=False))
            if output_dir:
                output_dir = str(sandbox.resolve(output_dir, must_exist=False))
        except ValueError:
            return json.dumps({"status": "error", "message": "路径超出项目目录"})
        report = inspect_statistics_inputs(
            project_path,
            feature_csv=feature_csv,
            clinical=clinical,
            id_col=id_col,
            label_col=label_col,
            selected_features_csv=selected_features_csv,
            output_dir=output_dir,
        )
        if report.get("status") != "ready":
            return json.dumps(report, ensure_ascii=False)
        return json.dumps(
            {"_pending_tool": "run_feature_statistics", "meta": report["resolved"]},
            ensure_ascii=False,
        )

    @tool
    def interpret_analysis_results() -> str:
        """对最近一次 run_radiomics_analysis 的分析结果生成 LLM 中文解读并注入
        报告：report.md 追加"结果解读"小节，report.docx 同步更新，解读原文保存为
        interpretation.md。无需参数：自动定位项目内最新的分析输出目录
        （含 analysis_result.json）。免确认，立即执行；重复调用幂等，报告不会
        叠加小节。分析成功、报告生成后应主动调用一次补全报告；用户要求
        "重新解读/再解读一次"时再次调用。若返回缺少 analysis_result.json 的错误，
        说明尚未运行分析或输出目录来自旧版本，需先重新运行分析。"""
        return json.dumps({"_pending_tool": "interpret_analysis_results"},
                          ensure_ascii=False)

    @tool
    def word_create(filename: str, content_markdown: str) -> str:
        """在项目目录下新建 Word 文档（.docx），套用中文学术论文格式
        （正文宋体小四、标题黑体、1.5 倍行距）。content_markdown 用 markdown
        组织内容：#/##/### 为各级标题，- 或 * 为列表项，**粗体** 保留加粗。
        文件已存在时报错而不会覆盖。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "word_create",
             "args": {"filename": filename, "content_markdown": content_markdown}},
            ensure_ascii=False,
        )

    @tool
    def word_append(filename: str, content_markdown: str) -> str:
        """向项目内已有 Word 文档（.docx）追加 markdown 内容（格式同
        word_create）。目标文件必须已存在。执行前需要用户确认。"""
        return json.dumps(
            {"_pending_tool": "word_append",
             "args": {"filename": filename, "content_markdown": content_markdown}},
            ensure_ascii=False,
        )

    @tool
    def reformat_report() -> str:
        """把最近一次分析输出的 AutoRadiomics_Report.docx 重排为中文学术论文
        格式（正文宋体小四、标题黑体、1.5 倍行距、表格五号）。无需参数：自动
        定位项目内最新的分析输出目录（含 analysis_result.json）。免确认，立即
        执行；原地保存不生成备份，重复调用幂等。用户觉得报告格式乱或
        要求"排版/重排报告"时调用。"""
        return json.dumps({"_pending_tool": "reformat_report"},
                          ensure_ascii=False)

    @tool
    def update_todo_list(todos: List[Any]) -> str:
        """全量更新右侧计划面板的步骤列表，向用户展示宏观分析进度。
        todos 为步骤数组，每项 {"content": 步骤描述, "status": "pending" |
        "in_progress" | "completed" | "cancelled"}；同一时刻至多一个
        in_progress；cancelled 仅用于标记已被用户停止的步骤。
        多步骤任务（如完整影像组学分析流程）开始时先建立完整列表，之后每
        进入/完成一个阶段就整体提交一次更新。免确认，立即生效。"""
        valid_status = {"pending", "in_progress", "completed", "cancelled"}
        normalized = []
        for item in todos if isinstance(todos, list) else []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            status = str(item.get("status", "pending")).strip()
            if status not in valid_status:
                status = "pending"
            normalized.append({"content": content, "status": status})
        if not normalized:
            return json.dumps(
                {"success": False, "error": "todos 不能为空，每项需包含 content"},
                ensure_ascii=False,
            )
        return json.dumps({"success": True, "todos": normalized}, ensure_ascii=False)

    @tool
    def ask_user_choice(question: str, options: List[str]) -> str:
        """向用户发起结构化提问，前端会以选择面板展示，挂起等待用户选择后
        把答案作为本工具的结果返回。适合需要用户在几个明确方案中做决定的
        场景（如参数取值、分析方案取舍），不要用于开放式问题。
        options 为 2-8 个简明选项；前端会固定追加"其他"供用户自由输入，
        无需也不应把"其他"列入 options。调用后等待用户提交，不要假设答案。"""
        cleaned = [str(o).strip() for o in options if str(o).strip()]
        if not question.strip() or len(cleaned) < 2:
            return json.dumps(
                {"success": False, "error": "question 不能为空且至少提供 2 个选项"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"_pending_tool": "ask_user_choice",
             "question": question.strip(),
             "options": cleaned[:8]},
            ensure_ascii=False,
        )

    tools["list_directory"] = list_directory
    tools["find_files"] = find_files
    tools["get_file_info"] = get_file_info
    tools["read_yaml"] = read_yaml
    tools["read_json"] = read_json
    tools["read_tabular_file"] = read_tabular_file
    tools["discover_radiomics_pairs"] = discover_radiomics_pairs
    tools["inspect_image_spacing"] = inspect_image_spacing
    if not readonly:
        # 只读模式（explore 子 agent）不注册写/重操作工具。
        tools["update_yaml"] = update_yaml
        tools["create_json"] = create_json
        tools["update_json"] = update_json
        tools["plan_file_operations"] = plan_file_operations
        tools["execute_python_script"] = execute_python_script
        tools["extract_radiomics_features"] = extract_radiomics_features
        tools["run_radiomics_analysis"] = run_radiomics_analysis
        tools["run_feature_statistics"] = run_feature_statistics
        tools["interpret_analysis_results"] = interpret_analysis_results
        tools["word_create"] = word_create
        tools["word_append"] = word_append
        tools["reformat_report"] = reformat_report
        tools["update_todo_list"] = update_todo_list
        tools["ask_user_choice"] = ask_user_choice

    if allow_subagent and not readonly:
        @tool
        def dispatch_subagent(tasks: List[Any], mode: str = "general") -> str:
            """把一个或多个独立任务分派给子 agent 执行。每个子任务在与本对话隔离的
            上下文中自主运行，多个任务会并行执行，结束后只把各任务的最终结论带回来。
            适合耗时的探查/分析任务：中间过程不占用本对话上下文。
            tasks 是任务描述字符串数组，每项应是完整的任务描述（包含路径、目标、
            期望输出）。
            mode 控制子 agent 的能力与确认方式：
            - "explore"：只读探索模式。子 agent 只能使用目录/文件探查与配对扫描等
              只读工具，免确认立即并行执行。收到"开始分析"类请求后，应优先用该模式
              把项目探索拆成 2-4 个互相独立的只读子任务一次派发。
            - "general"（默认）：全功能模式。子 agent 可使用全部工具
              （含 Python 脚本、影像组学提取等），执行前需要用户确认。"""
            # 模型常把每项写成 {"task": ..., "task_id": ...} 对象：归一化为字符串，
            # 避免 schema 校验直接拒绝（校验异常会把图弄崩，见 process_tool_calls）。
            normalized = []
            for t in tasks if isinstance(tasks, list) else []:
                if isinstance(t, str) and t.strip():
                    normalized.append(t.strip())
                elif isinstance(t, dict) and isinstance(t.get("task"), str) and t["task"].strip():
                    normalized.append(t["task"].strip())
            if not normalized:
                return json.dumps(
                    {"error": "tasks 不能为空，应为任务描述字符串数组"},
                    ensure_ascii=False,
                )
            # 未知 mode 一律回落为 general（全工具 + 需确认），保证安全边界。
            normalized_mode = "explore" if mode == "explore" else "general"
            return json.dumps(
                {
                    "_pending_tool": "dispatch_subagent",
                    "tasks": normalized,
                    "mode": normalized_mode,
                },
                ensure_ascii=False,
            )

        tools["dispatch_subagent"] = dispatch_subagent
    return tools


def _directory_snapshot(root: Path, max_depth: int = 2) -> str:
    lines = []
    for base, dirs, files in os.walk(root):
        depth = len(Path(base).relative_to(root).parts)
        if depth > max_depth:
            del dirs[:]
            continue
        indent = "  " * depth
        lines.append(f"{indent}{Path(base).name}/")
        for f in files[:20]:
            lines.append(f"{indent}  {f}")
    return "\n".join(lines)


def _extract_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    for m in matches:
        try:
            return json.loads(m.strip())
        except json.JSONDecodeError:
            continue
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return []
