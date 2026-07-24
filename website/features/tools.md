# 工具说明

Agent 通过一组内置工具操作你的项目。所有工具按用途分为六类，除只读和元控制工具外，执行前都需要你[审批确认](/features/human-approval)。

## 只读探索工具

| 工具 | 作用 |
|------|------|
| `list_directory` | 列出目录内容 |
| `find_files` | 按模式搜索文件 |
| `get_file_info` | 查看文件元信息 |
| `read_yaml` / `read_json` | 读取配置文件（支持点号路径取值） |
| `read_tabular_file` | 读取 Excel / CSV 表格（自动识别 UTF-8 / GBK 编码，可按列筛选、只看结构） |
| `discover_radiomics_pairs` | 扫描并配对影像与掩膜，输出高 / 中 / 低置信度结果 |
| `inspect_image_spacing` | 检查影像的体素间距（spacing） |

只读工具也是**探索子 Agent** 的全部武器——子 Agent 用它们并行摸清项目情况。

## 写入配置工具

| 工具 | 作用 |
|------|------|
| `update_yaml` | 修改 YAML 参数（点号路径赋值，**保留注释与格式**） |
| `create_json` / `update_json` | 新建 / 修改 JSON 文件（已有文件不覆盖） |

## 计划与执行工具

| 工具 | 作用 |
|------|------|
| `plan_file_operations` | 生成文件整理计划（移动 / 复制 / 重命名 / 建目录），你可在[计划编辑器](/features/human-approval#计划编辑器-文件操作可改后再批)中修改后确认执行，执行时自动备份可回滚 |
| `execute_python_script` | 保存并执行 Python 脚本，带 AST [风险分级](/features/human-approval#脚本面板-风险分级)（low / medium / high） |

## 影像组学工具

| 工具 | 作用 |
|------|------|
| `convert_dicom_to_nifti` | 递归扫描 DICOM 目录，按序列分组批量转换为 `.nii.gz`，输出镜像输入目录结构 |
| `extract_radiomics_features` | PyRadiomics 特征提取，默认[断点续提](/features/resume) |
| `run_radiomics_analysis` | LASSO 特征筛选 + 逻辑回归五折交叉验证建模，自动检测输入文件和列名，有歧义时主动提问 |
| `run_feature_statistics` | 对选中特征做独立样本 t 检验 + Mann-Whitney U 检验 |

## 元控制工具

| 工具 | 作用 | 确认 |
|------|------|------|
| `update_todo_list` | 更新右侧 [Todo 步骤面板](/features/todo-panel) | 免确认 |
| `ask_user_choice` | 向你发起结构化提问（选项按钮 + 自定义输入） | 特殊交互 |
| `dispatch_subagent` | 并行分派[子 Agent](/features/subagents) | explore 免确认 / general 需确认 |

## 报告工具

| 工具 | 作用 | 确认 |
|------|------|------|
| `word_create` / `word_append` | 新建 / 追加 Word 文档（Markdown 组织内容，自动套用规范格式） | 需确认 |
| `reformat_report` | 把最新的分析报告重排为规范格式（幂等，原地保存） | 免确认 |
| `interpret_analysis_results` | 对最近一次分析生成三段式中文解读并注入报告（幂等） | 免确认 |

## 工具可见性

工具集随场景自动裁剪，保证最小权限：

| 场景 | 可用工具 |
|------|---------|
| 主 Agent（正常对话） | 全部约 24 个 |
| 全功能子 Agent | 除 `dispatch_subagent` 外的全部 |
| 只读探索子 Agent | 仅 8 个只读工具 |
