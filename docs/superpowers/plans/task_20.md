# Task 20: 添加 LASSO 与结果可视化图

### Task 20: 添加 LASSO 与结果可视化图

**Files:**
- Modify: `app/analysis.py`
- Modify: `app/report.py`

- [ ] **Step 1: 在 AnalysisAgent 中保存 LASSO 路径图**

在 `AnalysisAgent.run` 中，每折 LASSO 拟合后保存路径图到 output_dir：
```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 在 LASSO 拟合后
plt.figure()
plt.semilogx(lasso.alphas_, lasso.coef_.T)
plt.axvline(lasso.alpha_, color="black", linestyle="--")
plt.xlabel("Alpha")
plt.ylabel("Coefficient")
plt.savefig(os.path.join(output_dir, f"lasso_path_fold{fold_idx}.png"))
plt.close()
```

- [ ] **Step 2: 在 ReportAgent 中添加图片**

`ReportAgent.run` 接收 `plot_paths: List[str]` 参数，在 Report 中插入图片：
```python
for plot_path in plot_paths:
    if os.path.exists(plot_path):
        doc.add_picture(plot_path, width=Inches(5.5))
```

- [ ] **Step 3: 测试并提交**

Run: `pytest tests/test_analysis.py tests/test_report.py -v`
Expected: PASS

```bash
git add app/analysis.py app/report.py
git commit -m "feat: add LASSO path plots to report"
```

---
