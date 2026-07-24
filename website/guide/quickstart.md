# 5 分钟快速上手

本页带你完成第一个影像组学分析项目。假设服务已启动（[安装部署](/guide/installation)），数据已准备好（[数据准备](/guide/data-preparation)）。

## 第一步：新建项目

打开 **http://localhost:8000**，左侧点击 **+ 新建项目** → **浏览**，在左侧位置列表选择 **📂 /data/input**，进入你的影像数据目录后确认。项目就建在你的数据目录上（按 [安装部署](/guide/installation#第五步-使用) 配置好数据挂载后，这里就能看到你的数据）。

> 📷 **截图位**：新建项目时浏览选择 /data/input 的界面

## 第二步：确认数据结构

项目目录推荐按如下结构组织（详见 [数据准备](/guide/data-preparation)）：

```
Breast-Radiomics/
├── images/          # 影像文件（.nii.gz 或 DICOM 目录）
├── masks/           # 分割掩膜（.nii.gz）
└── clinical.xlsx    # 临床表格
```

::: tip
原始数据是 DICOM？不用自己转换——直接对 Agent 说「**帮我把这些 DICOM 转成 nii.gz**」，它会扫描目录、识别序列、批量转换。详见 [数据准备](/guide/data-preparation#dicom-转-nifti)。
:::

## 第三步：一句话启动分析

在对话框输入：

> **开始分析**

然后观察 Agent 工作。你会在界面看到：

| 界面元素 | 展示内容 |
|---------|---------|
| **思考链面板** | Agent 的实时推理过程（做什么、为什么） |
| **右侧 Todo 面板** | 全流程步骤进度条，当前步骤高亮 |
| **子 Agent 卡片** | 多个只读子 Agent 并行探索项目的状态 |

> 📷 **截图位**：项目探索阶段的主界面（含思考链 + Todo + 子 Agent 卡片）

## 第四步：确认关键节点

Agent 每到一个关键操作都会停下来等你审批（详见 [审批面板](/features/human-approval)）：

1. **配对确认** — Agent 自动把 images 和 masks 按文件名匹配，给出**高 / 中 / 低置信度**的配对列表。检查无误后点「确认」。
2. **提取参数确认** — Agent 自动检查图像 spacing 并与 YAML 配置比对。如果实测 spacing 与配置不一致，它会**建议调整**而不是盲目按错误参数跑。
3. **特征提取** — 确认后开始提取。30 例数据大约需要十几分钟，界面有**逐例进度条**。中途关闭页面也没关系——[断点续提](/features/resume)机制保证下次接着跑。
4. **建模分析确认** — Agent 自动识别临床表的患者 ID 列、Label 列（遇到中文列名会自动翻译成英文，避免 SHAP 图乱码）。确认后执行 **LASSO 特征筛选 + 五折交叉验证逻辑回归**。

## 第五步：查看结果

分析完成后，Agent 自动生成**三段式中文解读**（模型性能 / 特征意义 / SHAP 解释）并输出规范的 Word 报告，包含方法学描述、结果表格和全部图表（ROC、校准曲线、DCA、SHAP），可直接放进论文 Supplementary。

产物保存在项目目录的 `output/` 下：

```
output/<分析目录>/
├── radiomics_features.csv      # 全部提取特征
├── analysis_result.json        # 分析结果结构化数据
├── AutoRadiomics_Report.docx   # Word 报告
└── figs/                       # ROC / 校准 / DCA / SHAP 图
```

> 📷 **截图位**：分析完成后的报告产物与对话总结

## 接下来

- 想继续这个项目？新对话里直接说「**继续分析**」或「**用同样的数据再做一次分析**」——[项目记忆](/features/project-memory)会让 Agent 记住你已确认的列名和偏好。
- 深入了解每个环节：[完整分析流程](/guide/workflow)
