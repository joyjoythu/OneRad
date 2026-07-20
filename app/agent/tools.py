import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List

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
        """生成 Python 脚本并在项目虚拟环境中运行。高风险脚本会被拒绝，中低风险脚本均需用户确认后执行。"""
        risk_level = classify_risk(code)
        if risk_level == "high":
            return json.dumps({"error": "脚本被判定为高风险，拒绝执行", "risk_level": "high"})
        meta = prepare_script(code, description, project_path)
        return json.dumps({"_pending_tool": "execute_python_script", "script": meta})

    @tool
    def discover_radiomics_pairs() -> str:
        """扫描项目下的 images/ 和 masks/，发现图像与掩膜的匹配计划。执行前需要用户确认。"""
        result = discover_pairs(project_path)
        if not result.get("success", True):
            return json.dumps(result)
        return json.dumps({"_pending_tool": "discover_radiomics_pairs", **result})

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
                               covariates: str = "", output_dir: str = "") -> str:
        """对已提取的影像组学特征和临床表做 LASSO + 逻辑回归五折交叉验证分析，
        生成 ROC/校准/DCA 曲线、预测概率表和 Word/Markdown 报告。
        执行前需要用户确认；若输入文件或列名识别有歧义，
        会先返回需要向用户澄清的问题（status=need_clarification），
        此时请向用户提问并用用户回答重新调用本工具。
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

    tools["list_directory"] = list_directory
    tools["find_files"] = find_files
    tools["get_file_info"] = get_file_info
    tools["read_yaml"] = read_yaml
    tools["discover_radiomics_pairs"] = discover_radiomics_pairs
    if not readonly:
        # 只读模式（explore 子 agent）不注册写/重操作工具。
        tools["update_yaml"] = update_yaml
        tools["plan_file_operations"] = plan_file_operations
        tools["execute_python_script"] = execute_python_script
        tools["extract_radiomics_features"] = extract_radiomics_features
        tools["run_radiomics_analysis"] = run_radiomics_analysis
        tools["run_feature_statistics"] = run_feature_statistics

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
