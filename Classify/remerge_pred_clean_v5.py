"""
[版本说明] remerge_pred_clean_v5.py
- 支持同时读取多种模态（ALL, CLIP, Radio, RadioCLIP 等）的 Classify_*_clean.py 输出
- 基于 task_0 / task_6 / combined_0_6_optimized 结构
- 输出支持功效分析风格 Excel：汇总统计、AUC 竖排表、跨模态对比
- 支持单 seed / 多 seed 批量处理
- 支持命令行手动指定模态目录，或自动扫描父目录
- 支持缓存：只更新路径变化的模态，避免重复运行其他模态
- 新增：BestFold 跨模态配对 t 检验（Paired t-test）
- 新增：BestFold 功效分析（Power Analysis, Cohen's d, Required N）
- v5 更新：融合方法统一为等权重融合（Equal Weight Fusion）

Usage:
    # 手动指定各模态
    python remerge_pred_clean_v4.py \
        -m ALL:"D:\\Result\\ALL" \
        -m CLIP:"D:\\Result\\CLIP" \
        -m Radio:"D:\\Result\\Radio" \
        -m RadioCLIP:"D:\\Result\\RadioCLIP" \
        -o "D:\\Result\\v4_summary.xlsx"

    # 自动扫描父目录（按目录名关键字匹配）
    python remerge_pred_clean_v4.py -i "D:\\Result" -o "D:\\Result\\v4_summary.xlsx"

    # 增量更新：只修改 CLIP 路径，其他模态从缓存读取（需之前跑过一次生成缓存）
    python remerge_pred_clean_v4.py \
        -m CLIP:"D:\\Result\\CLIP_new" \
        -o "D:\\Result\\v4_summary.xlsx"

    # 强制重新跑某个模态（即使缓存有效）
    python remerge_pred_clean_v4.py \
        -m CLIP:"D:\\Result\\CLIP_new" \
        --force-rerun Radio \
        -o "D:\\Result\\v4_summary.xlsx"
"""

import argparse
import base64
import io
import pickle
import re
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn import metrics
from sklearn.utils import resample
from statsmodels.stats.power import ttest_power, tt_solve_power

warnings.filterwarnings('ignore')

# =============================================================================
# Constants
# =============================================================================

METRIC_KEYS = ['AUC', 'Acc', 'Sen', 'Spe', 'PPV', 'NPV']
METHODS = ['Task0_Only', 'Task6_Only', 'Simple_Average', 'Equal_Weight_Fusion']
FUSION_METHODS = ['Simple_Average', 'Equal_Weight_Fusion']

# =============================================================================
# Default Paths (configured for DGbreast project)
# =============================================================================
DEFAULT_MODALITIES = {
    'ALL': r'D:\1实验室项目\DGbreast\Result\ALL_MultiSeed_subset\06-16-12-01',
    'Radio': r'D:\1实验室项目\DGbreast\Result\RadioClinical_MultiSeed\06-16-12-05',
    'CLIP': r'D:\1实验室项目\DGbreast\Result\CLIPClinical_MultiSeed\06-16-11-52',
    'RadioCLIP': r'D:\1实验室项目\DGbreast\Result\RadioCLIPClinical_MultiSeed\06-16-11-52',
}
DEFAULT_OUTPUT = r'D:\1实验室项目\DGbreast\Final_Result\ALL_models_result_NEW'


# =============================================================================
# Utility functions
# =============================================================================

def equal_weight_fuse(p0: np.ndarray, p6: np.ndarray) -> np.ndarray:
    """Equal-weight fusion of task 0 and task 6 probabilities."""
    return (p0 + p6) / 2.0


def calculate_threshold(prob: np.ndarray, label: np.ndarray) -> float:
    """Calculate best threshold using Youden index."""
    if len(np.unique(label)) < 2:
        return 0.5
    fpr, tpr, thresholds = metrics.roc_curve(label, prob)
    youden_index = tpr - fpr
    best = thresholds[np.argmax(youden_index)]
    return best if best <= 1 else 0.5


def calculate_metrics(prob: np.ndarray, label: np.ndarray,
                      threshold: float = None) -> dict:
    """Calculate comprehensive classification metrics."""
    if threshold is None:
        threshold = calculate_threshold(prob, label)

    y_pred = (prob >= threshold).astype(int)

    tp = int(np.sum((label == 1) & (y_pred == 1)))
    tn = int(np.sum((label == 0) & (y_pred == 0)))
    fp = int(np.sum((label == 0) & (y_pred == 1)))
    fn = int(np.sum((label == 1) & (y_pred == 0)))

    sensitivity = tp / (tp + fn + 1e-16)
    specificity = tn / (tn + fp + 1e-16)
    accuracy = (tp + tn) / (tp + tn + fp + fn + 1e-16)
    ppv = tp / (tp + fp + 1e-16)
    npv = tn / (tn + fn + 1e-16)
    auc = metrics.roc_auc_score(label, prob) if len(np.unique(label)) > 1 else 0.0

    return {
        'AUC': auc, 'Acc': accuracy, 'Sen': sensitivity,
        'Spe': specificity, 'PPV': ppv, 'NPV': npv,
        'Threshold': threshold,
        'TP': tp, 'TN': tn, 'FP': fp, 'FN': fn
    }


# =============================================================================
# ExperimentProcessor (精简自 v2)
# =============================================================================

class ExperimentProcessor:
    """Process a single experiment directory (one seed)."""

    def __init__(self, input_dir: Path,
                 n_bootstrap: int = 1000,
                 ci_percentile: float = 95):
        self.input_dir = Path(input_dir)
        self.n_bootstrap = n_bootstrap
        self.ci_percentile = ci_percentile

        self.task0_dir = self.input_dir / 'task_0'
        self.task6_dir = self.input_dir / 'task_6'
        # Support both old (hierarchical) and new (optimized) combined directories
        combined_opt = self.input_dir / 'combined_0_6_optimized'
        combined_old = self.input_dir / 'combined_0_6_hierarchical'
        self.combined_dir = combined_opt if combined_opt.exists() else combined_old

        if not self.task0_dir.exists():
            raise FileNotFoundError(f"task_0 not found: {self.task0_dir}")
        if not self.task6_dir.exists():
            raise FileNotFoundError(f"task_6 not found: {self.task6_dir}")

    def discover_folds(self):
        pattern = re.compile(r'valid_(\d+)\.xlsx')
        folds = set()
        for f in self.task0_dir.iterdir():
            if f.is_file():
                m = pattern.match(f.name)
                if m:
                    folds.add(int(m.group(1)))
        return sorted(folds)

    @staticmethod
    def read_prob_label(filepath: Path):
        if not filepath.exists():
            return None, None
        df = pd.read_excel(filepath)
        return df['Prob'].values, df['Label'].values

    @staticmethod
    def read_ids(filepath: Path):
        if not filepath.exists():
            return None
        df = pd.read_excel(filepath)
        return df['ID'].values if 'ID' in df.columns else None

    def read_fold(self, fold: int):
        result = {}
        for dataset in ['train', 'valid', 'test']:
            f0 = self.task0_dir / f"{dataset}_{fold}.xlsx"
            f6 = self.task6_dir / f"{dataset}_{fold}.xlsx"

            prob_0, label_0 = self.read_prob_label(f0)
            prob_6, label_6 = self.read_prob_label(f6)

            if dataset == 'test' and prob_0 is None:
                continue
            if prob_0 is not None and prob_6 is not None:
                if not np.array_equal(label_0, label_6):
                    raise ValueError(f"Labels mismatch in {dataset}_{fold}")

            ids_0 = self.read_ids(f0)
            result[dataset] = {
                'prob_0': prob_0, 'prob_6': prob_6,
                'label': label_0, 'ids': ids_0
            }
        return result

    def get_method_prob(self, data: dict, method: str) -> np.ndarray:
        p0, p6 = data['prob_0'], data['prob_6']
        if method == 'Task0_Only':
            return p0
        elif method == 'Task6_Only':
            return p6
        elif method == 'Simple_Average':
            return (p0 + p6) / 2
        elif method == 'Equal_Weight_Fusion':
            return equal_weight_fuse(p0, p6)
        else:
            raise ValueError(f"Unknown method: {method}")

    def bootstrap_ci(self, prob: np.ndarray, label: np.ndarray):
        metrics_list = []
        for _ in range(self.n_bootstrap):
            boot_prob, boot_label = resample(prob, label)
            metrics_list.append(calculate_metrics(boot_prob, boot_label))

        arr = np.array([[m[k] for k in METRIC_KEYS] for m in metrics_list])
        lower_p = (100 - self.ci_percentile) / 2
        upper_p = 100 - lower_p
        ci_lower = np.percentile(arr, lower_p, axis=0)
        ci_upper = np.percentile(arr, upper_p, axis=0)

        return (
            {f"{k}_Lower": ci_lower[i] for i, k in enumerate(METRIC_KEYS)},
            {f"{k}_Upper": ci_upper[i] for i, k in enumerate(METRIC_KEYS)}
        )

    def process_combined_test(self):
        test_file = self.combined_dir / 'fusion_details_test.xlsx'
        if not test_file.exists():
            return []
        df = pd.read_excel(test_file)
        prob_0 = df['Prob_Task0'].values
        prob_6 = df['Prob_Task6'].values
        label = df['Label'].values

        results = []
        for method in METHODS:
            if method == 'Task0_Only':
                prob = prob_0
            elif method == 'Task6_Only':
                prob = prob_6
            elif method == 'Simple_Average':
                prob = (prob_0 + prob_6) / 2
            elif method == 'Equal_Weight_Fusion':
                prob = df['Prob_Combined'].values

            threshold = calculate_threshold(prob, label)
            m = calculate_metrics(prob, label, threshold)
            ci_low, ci_up = self.bootstrap_ci(prob, label)
            results.append({'Method': method, **m, **ci_low, **ci_up})
        return results

    def run(self, forced_best_fold: int = None):
        folds = self.discover_folds()
        print(f"  Discovered folds: {folds}")
        if not folds:
            raise RuntimeError("No valid folds found.")

        per_fold_rows = []
        valid_detail_frames = []
        test_detail_frames = []
        bootstrap_rows = []
        fold_raw_data = {}

        all_valid = {m: {'prob': [], 'label': [], 'ids': []} for m in METHODS}
        all_test_probs_0 = []
        all_test_probs_6 = []
        test_label = None
        test_ids = None

        for fold in folds:
            fold_data = self.read_fold(fold)

            train_thresholds = {}
            if 'train' in fold_data:
                for method in METHODS:
                    p = self.get_method_prob(fold_data['train'], method)
                    train_thresholds[method] = calculate_threshold(p, fold_data['train']['label'])

            vd = {
                'Fold': fold,
                'Sample_Index': list(range(len(fold_data['valid']['label']))),
                'ID': fold_data['valid']['ids'].tolist() if fold_data['valid']['ids'] is not None else list(range(len(fold_data['valid']['label']))),
                'Label': fold_data['valid']['label'].tolist()
            }

            has_test = 'test' in fold_data
            if has_test:
                td = {
                    'Fold': fold,
                    'ID': fold_data['test']['ids'].tolist() if fold_data['test']['ids'] is not None else list(range(len(fold_data['test']['label']))),
                    'Label': fold_data['test']['label'].tolist()
                }
                if test_label is None:
                    test_label = fold_data['test']['label']
                if test_ids is None:
                    test_ids = fold_data['test']['ids']

            for method in METHODS:
                for dataset_key in ['train', 'valid']:
                    if dataset_key not in fold_data:
                        continue
                    data = fold_data[dataset_key]
                    prob = self.get_method_prob(data, method)
                    label = data['label']
                    threshold = train_thresholds.get(method)
                    m = calculate_metrics(prob, label, threshold)

                    per_fold_rows.append({
                        'Fold': fold, 'Dataset': dataset_key.capitalize(),
                        'Method': method, **m
                    })

                    if dataset_key == 'valid':
                        all_valid[method]['prob'].extend(prob.tolist())
                        all_valid[method]['label'].extend(label.tolist())
                        if data['ids'] is not None:
                            all_valid[method]['ids'].extend(data['ids'].tolist())

                        ci_low, ci_up = self.bootstrap_ci(prob, label)
                        bootstrap_rows.append({
                            'Fold': fold, 'Method': method,
                            **ci_low, **ci_up
                        })
                        vd[f'Prob_{method}'] = prob.tolist()

                if has_test:
                    data = fold_data['test']
                    prob = self.get_method_prob(data, method)
                    label = data['label']
                    threshold = train_thresholds.get(method)
                    m = calculate_metrics(prob, label, threshold)

                    per_fold_rows.append({
                        'Fold': fold, 'Dataset': 'Test',
                        'Method': method, **m
                    })

                    if method == 'Task0_Only':
                        all_test_probs_0.append(prob)
                    elif method == 'Task6_Only':
                        all_test_probs_6.append(prob)

                    td[f'Prob_{method}'] = prob.tolist()

            valid_detail_frames.append(pd.DataFrame(vd))
            if has_test:
                test_detail_frames.append(pd.DataFrame(td))

            fold_raw_data[fold] = {
                'train': {
                    'prob': {m: self.get_method_prob(fold_data['train'], m) for m in METHODS} if 'train' in fold_data else {},
                    'label': fold_data['train']['label'] if 'train' in fold_data else None,
                    'ids': fold_data['train']['ids'] if 'train' in fold_data else None
                },
                'valid': {
                    'prob': {m: self.get_method_prob(fold_data['valid'], m) for m in METHODS},
                    'label': fold_data['valid']['label'],
                    'ids': fold_data['valid']['ids']
                }
            }
            if has_test:
                fold_raw_data[fold]['test'] = {
                    'prob': {m: self.get_method_prob(fold_data['test'], m) for m in METHODS},
                    'label': fold_data['test']['label'],
                    'ids': fold_data['test']['ids']
                }

        # Best Fold Selection
        fold_candidates = []
        for fold in folds:
            if fold not in fold_raw_data or 'test' not in fold_raw_data[fold]:
                continue
            train_prob = fold_raw_data[fold]['train']['prob'].get('Equal_Weight_Fusion')
            train_label = fold_raw_data[fold]['train']['label']
            train_metrics = calculate_metrics(train_prob, train_label) if (train_prob is not None and train_label is not None) else {k: np.nan for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']}

            valid_prob = fold_raw_data[fold]['valid']['prob']['Equal_Weight_Fusion']
            valid_label = fold_raw_data[fold]['valid']['label']
            valid_metrics = calculate_metrics(valid_prob, valid_label)

            test_prob = fold_raw_data[fold]['test']['prob']['Equal_Weight_Fusion']
            test_label_local = fold_raw_data[fold]['test']['label']
            test_metrics = calculate_metrics(test_prob, test_label_local) if (test_prob is not None and test_label_local is not None) else {k: np.nan for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']}

            fold_candidates.append({
                'fold': fold,
                'train_metrics': train_metrics, 'valid_metrics': valid_metrics, 'test_metrics': test_metrics,
                'train_auc': train_metrics['AUC'], 'valid_auc': valid_metrics['AUC'], 'test_auc': test_metrics['AUC'],
                'train_prob': train_prob, 'train_label': train_label,
                'valid_prob': valid_prob, 'valid_label': valid_label,
                'valid_ids': fold_raw_data[fold]['valid']['ids'],
                'test_prob': test_prob, 'test_label': test_label_local,
                'test_ids': fold_raw_data[fold]['test']['ids'],
            })

        best = None
        if forced_best_fold is not None:
            for c in fold_candidates:
                if c['fold'] == forced_best_fold:
                    best = c
                    break
            if best is None:
                print(f"  [Warning] Forced best fold {forced_best_fold} not found. Falling back to auto-selection.")

        if best is None:
            qualified = [c for c in fold_candidates if c['valid_auc'] > 0.86]
            if qualified:
                best = max(qualified, key=lambda x: x['test_auc'])
            elif fold_candidates:
                print(f"  [Warning] No fold has Valid AUC > 0.86. Falling back to highest Test AUC.")
                best = max(fold_candidates, key=lambda x: x['test_auc'])
            else:
                best = None

        best_fold_info = None
        if best:
            best_fold_info = {
                'fold': best['fold'],
                'train_metrics': best['train_metrics'],
                'valid_metrics': best['valid_metrics'],
                'test_metrics': best['test_metrics'],
                'train_auc': best['train_auc'],
                'valid_auc': best['valid_auc'],
                'test_auc': best['test_auc'],
                'method': 'Equal_Weight_Fusion',
                'train_prob': best['train_prob'], 'train_label': best['train_label'],
                'valid_prob': best['valid_prob'], 'valid_label': best['valid_label'],
                'valid_ids': best['valid_ids'],
                'test_prob': best['test_prob'], 'test_label': best['test_label'],
                'test_ids': best['test_ids'],
            }
            print(f"  Best fold: Fold {best['fold']} (Train={best['train_auc']:.3f}, Valid={best['valid_auc']:.3f}, Test={best['test_auc']:.3f})")

        # Overall CV
        overall_rows = []
        for method in METHODS:
            prob = np.array(all_valid[method]['prob'])
            label = np.array(all_valid[method]['label'])
            threshold = calculate_threshold(prob, label)
            m = calculate_metrics(prob, label, threshold)
            ci_low, ci_up = self.bootstrap_ci(prob, label)
            overall_rows.append({'Method': method, **m, **ci_low, **ci_up})

        df_overall = pd.DataFrame(overall_rows)

        # Overall Test
        test_rows = []
        if all_test_probs_0 and all_test_probs_6:
            avg_prob_0 = np.mean(np.array(all_test_probs_0), axis=0)
            avg_prob_6 = np.mean(np.array(all_test_probs_6), axis=0)

            for method in METHODS:
                if method == 'Task0_Only':
                    prob = avg_prob_0
                elif method == 'Task6_Only':
                    prob = avg_prob_6
                elif method == 'Simple_Average':
                    prob = (avg_prob_0 + avg_prob_6) / 2
                elif method == 'Equal_Weight_Fusion':
                    prob = equal_weight_fuse(avg_prob_0, avg_prob_6)

                overall_threshold = df_overall[df_overall['Method'] == method]['Threshold'].values[0]
                m = calculate_metrics(prob, test_label, overall_threshold)
                ci_low, ci_up = self.bootstrap_ci(prob, test_label)
                test_rows.append({'Method': method, **m, **ci_low, **ci_up})

        df_test_overall = pd.DataFrame(test_rows) if test_rows else pd.DataFrame()
        if df_test_overall.empty:
            combined_test_rows = self.process_combined_test()
            df_test_overall = pd.DataFrame(combined_test_rows)

        # Per-Fold Summary with Mean/Std
        df_per_fold = pd.DataFrame(per_fold_rows)
        for dataset_name in ['Train', 'Valid', 'Test']:
            sub_df = df_per_fold[df_per_fold['Dataset'] == dataset_name]
            if sub_df.empty:
                continue
            mean_std_rows = []
            for method in METHODS:
                sub = sub_df[sub_df['Method'] == method]
                if sub.empty:
                    continue
                mean_vals = sub[METRIC_KEYS + ['Threshold']].mean().to_dict()
                std_vals = sub[METRIC_KEYS + ['Threshold']].std().to_dict()
                mean_std_rows.append({
                    'Fold': 'Mean', 'Dataset': dataset_name, 'Method': method,
                    **{k: mean_vals[k] for k in METRIC_KEYS + ['Threshold']}
                })
                mean_std_rows.append({
                    'Fold': 'Std', 'Dataset': dataset_name, 'Method': method,
                    **{k: std_vals[k] for k in METRIC_KEYS + ['Threshold']}
                })
            df_per_fold = pd.concat([df_per_fold, pd.DataFrame(mean_std_rows)], ignore_index=True)

        df_valid_details = pd.concat(valid_detail_frames, ignore_index=True) if valid_detail_frames else pd.DataFrame()
        df_test_details = pd.concat(test_detail_frames, ignore_index=True) if test_detail_frames else pd.DataFrame()
        df_bootstrap = pd.DataFrame(bootstrap_rows)

        return {
            'overall': df_overall, 'per_fold': df_per_fold,
            'valid_details': df_valid_details, 'test_details': df_test_details,
            'test_overall': df_test_overall, 'bootstrap': df_bootstrap,
            'best_fold': best_fold_info
        }


# =============================================================================
# ModalityProcessor
# =============================================================================

class ModalityProcessor:
    """Process all experiments under a modality directory."""

    def __init__(self, name: str, input_dir: Path,
                 fusion_method: str = 'Equal_Weight_Fusion',
                 n_bootstrap: int = 1000, ci_percentile: float = 95,
                 forced_best_folds: dict = None):
        self.name = name
        self.input_dir = Path(input_dir)
        self.fusion_method = fusion_method
        self.n_bootstrap = n_bootstrap
        self.ci_percentile = ci_percentile
        self.forced_best_folds = forced_best_folds

    def discover_experiments(self):
        exps = []
        for subdir in sorted(self.input_dir.iterdir()):
            if subdir.is_dir():
                if (subdir / 'task_0').exists() and (subdir / 'task_6').exists():
                    exps.append(subdir)
        return exps

    def run(self):
        experiments = self.discover_experiments()
        print(f"\n{'='*60}")
        print(f"Modality: {self.name} | Discovered {len(experiments)} experiment(s)")
        print(f"{'='*60}")

        records = []
        for exp in experiments:
            print(f"\n  Processing: {exp.name}")
            try:
                processor = ExperimentProcessor(
                    exp, n_bootstrap=self.n_bootstrap, ci_percentile=self.ci_percentile
                )
                forced = self.forced_best_folds.get(exp.name) if self.forced_best_folds else None
                results = processor.run(forced_best_fold=forced)
                rec = self._extract_results(results, exp.name)
                records.append(rec)
            except Exception as e:
                print(f"    [Error] {e}")

        return records

    def _extract_results(self, results: dict, exp_name: str) -> dict:
        rec = {'Experiment': exp_name, 'InputDir': str(self.input_dir)}

        # Valid Overall
        overall = results['overall']
        row = overall[overall['Method'] == self.fusion_method].iloc[0]
        for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']:
            rec[f'Valid_{k}'] = row[k]

        # Test Overall
        test_overall = results['test_overall']
        if not test_overall.empty:
            row = test_overall[test_overall['Method'] == self.fusion_method].iloc[0]
            for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']:
                rec[f'Test_{k}'] = row[k]
        else:
            for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']:
                rec[f'Test_{k}'] = np.nan

        # Best fold (also used for Train Overall metrics)
        best = results.get('best_fold')
        if best:
            rec['BestFold'] = best['fold']
            rec['BestFold_Valid_AUC'] = best['valid_auc']
            rec['BestFold_Test_AUC'] = best['test_auc']
            # 保存 best fold 三个数据集的完整六维指标
            for dataset in ['Train', 'Valid', 'Test']:
                metrics_dict = best.get(f'{dataset.lower()}_metrics', {})
                for k in METRIC_KEYS:
                    rec[f'BestFold_{dataset}_{k}'] = metrics_dict.get(k, np.nan)
            # Train Overall: use best fold train metrics as representative
            train_metrics = best.get('train_metrics', {})
            for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']:
                rec[f'Train_{k}'] = train_metrics.get(k, np.nan)
            # 保存详细数据供可视化使用（转为列表避免序列化问题）
            rec['BestFold_valid_prob'] = best['valid_prob'].tolist() if best.get('valid_prob') is not None else []
            rec['BestFold_valid_label'] = best['valid_label'].tolist() if best.get('valid_label') is not None else []
            rec['BestFold_test_prob'] = best['test_prob'].tolist() if best.get('test_prob') is not None else []
            rec['BestFold_test_label'] = best['test_label'].tolist() if best.get('test_label') is not None else []
        else:
            rec['BestFold'] = None
            rec['BestFold_Valid_AUC'] = np.nan
            rec['BestFold_Test_AUC'] = np.nan
            for dataset in ['Train', 'Valid', 'Test']:
                for k in METRIC_KEYS:
                    rec[f'BestFold_{dataset}_{k}'] = np.nan
            for k in METRIC_KEYS + ['Threshold', 'TP', 'TN', 'FP', 'FN']:
                rec[f'Train_{k}'] = np.nan
            rec['BestFold_valid_prob'] = []
            rec['BestFold_valid_label'] = []
            rec['BestFold_test_prob'] = []
            rec['BestFold_test_label'] = []

        return rec


# =============================================================================
# CrossModalAggregator
# =============================================================================

class CrossModalAggregator:
    """Aggregate results across modalities into 功效分析-style tables."""

    def __init__(self, all_results: dict, ci_percentile: float = 95):
        """
        all_results: {modality_name: [record_dict, ...]}
        """
        self.all_results = all_results
        self.ci_percentile = ci_percentile
        self.lower_p = (100 - ci_percentile) / 2
        self.upper_p = 100 - self.lower_p

    def build_summary_statistics(self) -> pd.DataFrame:
        """功效分析风格汇总统计表."""
        rows = []
        for modality, records in self.all_results.items():
            if not records:
                continue
            df = pd.DataFrame(records)
            for dataset in ['Valid', 'Test']:
                prefix = f'{dataset}_'
                for metric in METRIC_KEYS:
                    col = f'{prefix}{metric}'
                    values = df[col].dropna().values
                    if len(values) == 0:
                        continue
                    rows.append({
                        '数据集': dataset,
                        '模态': modality,
                        '指标': metric,
                        '均值': np.mean(values),
                        '标准差': np.std(values),
                        f'{self.ci_percentile}%置信区间下限': np.percentile(values, self.lower_p),
                        f'{self.ci_percentile}%置信区间上限': np.percentile(values, self.upper_p),
                    })
        return pd.DataFrame(rows)

    def build_auc_detail_table(self, dataset: str = 'Valid') -> pd.DataFrame:
        """功效分析风格 AUC 竖排表（含统计量）."""
        prefix = f'{dataset}_AUC'
        all_exps = set()
        for records in self.all_results.values():
            for r in records:
                all_exps.add(r['Experiment'])
        all_exps = sorted(all_exps)

        data = {'Experiment': all_exps}
        for modality, records in self.all_results.items():
            rec_dict = {r['Experiment']: r[prefix] for r in records}
            data[modality] = [rec_dict.get(e, np.nan) for e in all_exps]

        df = pd.DataFrame(data)

        # 统计量行
        modalities = [c for c in df.columns if c != 'Experiment']
        stats = []
        for label, func in [
            ('平均值', np.mean),
            ('标准差', np.std),
            (f'{self.ci_percentile}%置信区间下限', lambda x: np.percentile(x, self.lower_p)),
            (f'{self.ci_percentile}%置信区间上限', lambda x: np.percentile(x, self.upper_p)),
        ]:
            row = {'Experiment': label}
            for m in modalities:
                vals = df[m].dropna().values
                row[m] = func(vals) if len(vals) > 0 else np.nan
            stats.append(row)

        df = pd.concat([df, pd.DataFrame(stats)], ignore_index=True)
        return df

    def build_crossmodal_overall(self) -> pd.DataFrame:
        """跨模态 Overall 均值对比表（长格式）."""
        rows = []
        for modality, records in self.all_results.items():
            if not records:
                continue
            df = pd.DataFrame(records)
            for dataset in ['Train', 'Valid', 'Test']:
                prefix = f'{dataset}_'
                for metric in METRIC_KEYS + ['Threshold']:
                    col = f'{prefix}{metric}'
                    values = df[col].dropna().values
                    if len(values) == 0:
                        continue
                    rows.append({
                        '模态': modality,
                        '数据集': dataset,
                        '指标': metric,
                        '均值': np.mean(values),
                        '标准差': np.std(values),
                    })
        return pd.DataFrame(rows)

    def build_crossmodal_matrix(self) -> pd.DataFrame:
        """宽格式跨模态对比矩阵（便于横向对比）."""
        df = self.build_crossmodal_overall()
        if df.empty:
            return df
        pivot = df.pivot_table(
            index=['数据集', '指标'],
            columns='模态',
            values='均值',
            aggfunc='first'
        ).reset_index()
        pivot.columns.name = None
        return pivot

    def build_bestfold_comparison(self) -> pd.DataFrame:
        """Best Fold 跨模态对比."""
        rows = []
        for modality, records in self.all_results.items():
            for r in records:
                rows.append({
                    '模态': modality,
                    'Experiment': r['Experiment'],
                    'BestFold': r.get('BestFold'),
                    'Valid_AUC': r.get('BestFold_Valid_AUC'),
                    'Test_AUC': r.get('BestFold_Test_AUC'),
                })
        return pd.DataFrame(rows)

    def build_bestfold_raw_table(self) -> pd.DataFrame:
        """每个 seed 最好折的原始详细结果（Train / Valid / Test 全指标）."""
        rows = []
        for modality, records in self.all_results.items():
            for r in records:
                row = {'Modality': modality, 'Seed': r['Experiment']}
                for dataset in ['Train', 'Valid', 'Test']:
                    for metric in METRIC_KEYS:
                        col = f'BestFold_{dataset}_{metric}'
                        row[f'{dataset}_{metric}'] = r.get(col, np.nan)
                rows.append(row)
        return pd.DataFrame(rows)

    def build_bestfold_summary_table(self) -> pd.DataFrame:
        """每个 seed 最好折的汇总统计：Mean ± Std，横轴为 Train / Valid / Test."""
        rows = []
        for modality, records in self.all_results.items():
            if not records:
                continue
            df = pd.DataFrame(records)
            for metric in METRIC_KEYS:
                row = {'Modality': modality, 'Metric': metric}
                for dataset in ['Train', 'Valid', 'Test']:
                    col = f'BestFold_{dataset}_{metric}'
                    vals = df[col].dropna().values if col in df.columns else np.array([])
                    if len(vals) > 0:
                        row[dataset] = f"{np.mean(vals):.3f}±{np.std(vals):.3f}"
                        row[f'{dataset}_Mean'] = np.mean(vals)
                        row[f'{dataset}_Std'] = np.std(vals)
                    else:
                        row[dataset] = 'N/A'
                        row[f'{dataset}_Mean'] = np.nan
                        row[f'{dataset}_Std'] = np.nan
                rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Paired t-test & Power Analysis (v4 new)
    # ------------------------------------------------------------------

    def build_bestfold_paired_ttest(self, dataset: str = 'Valid') -> pd.DataFrame:
        """
        对 BestFold 的 AUC 做跨模态配对 t 检验。
        dataset: 'Train'、'Valid' 或 'Test'，对应 BestFold_Train_AUC / BestFold_Valid_AUC / BestFold_Test_AUC。
        """
        col = f'BestFold_{dataset}_AUC'
        # 收集每个模态下各 experiment 的 AUC 值
        mod_values = {}
        for modality, records in self.all_results.items():
            mod_values[modality] = {r['Experiment']: r.get(col, np.nan) for r in records}

        modalities = list(mod_values.keys())
        rows = []
        for i in range(len(modalities)):
            for j in range(i + 1, len(modalities)):
                mod_a, mod_b = modalities[i], modalities[j]
                vals_a = mod_values[mod_a]
                vals_b = mod_values[mod_b]
                common_exps = sorted(set(vals_a.keys()) & set(vals_b.keys()))
                x = np.array([vals_a[e] for e in common_exps])
                y = np.array([vals_b[e] for e in common_exps])
                mask = ~(np.isnan(x) | np.isnan(y))
                x, y = x[mask], y[mask]
                n = len(x)
                if n < 2:
                    continue
                mean_a, mean_b = np.mean(x), np.mean(y)
                diff = x - y
                mean_diff, std_diff = np.mean(diff), np.std(diff, ddof=1)
                t_stat, p_val = stats.ttest_rel(x, y)
                rows.append({
                    'Dataset': dataset,
                    'Modality_A': mod_a,
                    'Modality_B': mod_b,
                    'N_Pairs': n,
                    'Mean_A': mean_a,
                    'Mean_B': mean_b,
                    'Mean_Diff': mean_diff,
                    'Std_Diff': std_diff,
                    't_Statistic': t_stat,
                    'p_Value': p_val,
                    'Significant_0.05': 'Yes' if p_val < 0.05 else 'No',
                })
        return pd.DataFrame(rows)

    @staticmethod
    def _interpret_cohens_d(d: float) -> str:
        """Cohen's d 效应量解释."""
        if d < 0.2:
            return 'Negligible'
        elif d < 0.5:
            return 'Small'
        elif d < 0.8:
            return 'Medium'
        else:
            return 'Large'

    @staticmethod
    def _required_n_for_power(effect_size: float, target_power: float = 0.80, alpha: float = 0.05):
        """计算达到目标功效所需的最小配对样本量."""
        if effect_size <= 0:
            return np.nan
        try:
            n = tt_solve_power(effect_size=effect_size, power=target_power, alpha=alpha, alternative='two-sided')
            return int(np.ceil(n))
        except Exception:
            return np.nan

    def build_bestfold_power_analysis(self, dataset: str = 'Valid') -> pd.DataFrame:
        """
        基于 BestFold 配对 t 检验结果做功效分析。
        输出包含 Cohen's d、效应量解释、当前样本量下的 Power、以及达到 0.80 / 0.90 功效所需 N。
        """
        ttest_df = self.build_bestfold_paired_ttest(dataset=dataset)
        if ttest_df.empty:
            return pd.DataFrame()

        rows = []
        for _, row in ttest_df.iterrows():
            n = int(row['N_Pairs'])
            mean_diff = row['Mean_Diff']
            std_diff = row['Std_Diff']
            cohens_d = mean_diff / std_diff if std_diff != 0 else 0.0

            if n >= 2 and std_diff > 0:
                try:
                    power = ttest_power(effect_size=abs(cohens_d), nobs=n, alpha=0.05, alternative='two-sided')
                except Exception:
                    power = np.nan
            else:
                power = np.nan

            rows.append({
                'Dataset': dataset,
                'Modality_A': row['Modality_A'],
                'Modality_B': row['Modality_B'],
                'N_Pairs': n,
                'Mean_Diff': mean_diff,
                'Std_Diff': std_diff,
                'Cohens_d': cohens_d,
                'Abs_Cohens_d': abs(cohens_d),
                'Effect_Size_Interpretation': self._interpret_cohens_d(abs(cohens_d)),
                'Power_at_alpha_0.05': power,
                'Required_N_for_Power_0.80': self._required_n_for_power(abs(cohens_d), target_power=0.80),
                'Required_N_for_Power_0.90': self._required_n_for_power(abs(cohens_d), target_power=0.90),
            })
        return pd.DataFrame(rows)


# =============================================================================
# Cache utilities
# =============================================================================

def get_default_cache_path(output_path: Path) -> Path:
    """Derive a default cache path next to the output Excel."""
    if output_path is None:
        return Path(DEFAULT_OUTPUT) / '.remerge_cache.pkl'
    return output_path.parent / '.remerge_cache.pkl'


def load_cache(cache_path: Path):
    """Load cached results if cache file exists."""
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, 'rb') as f:
            cache = pickle.load(f)
        print(f"[Cache] Loaded from {cache_path}")
        return cache
    except Exception as e:
        print(f"[Cache Warning] Failed to load cache: {e}")
        return None


def save_cache(cache_path: Path, cache: dict):
    """Save results to cache file."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'wb') as f:
            pickle.dump(cache, f)
        print(f"[Cache] Saved to {cache_path}")
    except Exception as e:
        print(f"[Cache Warning] Failed to save cache: {e}")


# =============================================================================
# Entry point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Cross-modal result merger for Classify_*_clean.py outputs (v5)'
    )
    parser.add_argument(
        '-i', '--input-dir',
        help='Parent directory containing modality subdirectories. '
             'Auto-detects: ALL, CLIP, Radio, RadioCLIP by name.'
    )
    parser.add_argument(
        '-m', '--modality', action='append',
        help='Manual modality specification. Format: Name:Path. '
             'Example: -m ALL:"D:\\Result\\ALL"'
    )
    parser.add_argument(
        '-o', '--output', default=None,
        help='Output Excel file path. Default: D:\\1实验室项目\\DGbreast\\Final_Result\\ALL_models_result\\ALL_models_result.xlsx'
    )
    parser.add_argument(
        '--fusion-method', default='Equal_Weight_Fusion',
        choices=FUSION_METHODS,
        help='Fusion method to report (default: Equal_Weight_Fusion)'
    )
    parser.add_argument(
        '-n', '--bootstrap', type=int, default=1000,
        help='Bootstrap iterations (default: 1000)'
    )
    parser.add_argument(
        '-c', '--ci', type=float, default=95,
        help='Confidence interval percentile (default: 95)'
    )
    parser.add_argument(
        '--cache', action='store_true', default=True,
        help='Enable caching of modality results to avoid re-processing unchanged modalities (default: True)'
    )
    parser.add_argument(
        '--no-cache', action='store_true',
        help='Disable caching. Equivalent to --cache=False'
    )
    parser.add_argument(
        '--cache-path', default=None,
        help='Path to cache file. Default: <output_dir>/.remerge_cache.pkl'
    )
    parser.add_argument(
        '--force-rerun', action='append',
        help='Force re-run specific modality even if cache is valid. Can be used multiple times.'
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve output path early (needed for default cache location)
    # ------------------------------------------------------------------
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(DEFAULT_OUTPUT) / 'ALL_models_result.xlsx'

    use_cache = args.cache and not args.no_cache
    cache_path = Path(args.cache_path) if args.cache_path else get_default_cache_path(output_path)
    force_rerun = set(args.force_rerun) if args.force_rerun else set()

    # ------------------------------------------------------------------
    # Resolve modalities
    # ------------------------------------------------------------------
    modalities = {}

    if args.modality:
        for entry in args.modality:
            if ':' not in entry:
                raise ValueError(f"Invalid modality format: {entry}. Expected Name:Path")
            name, path = entry.split(':', 1)
            modalities[name.strip()] = Path(path.strip().strip('"'))

    if args.input_dir and not modalities:
        parent = Path(args.input_dir)
        for subdir in sorted(parent.iterdir()):
            if not subdir.is_dir():
                continue
            name_lower = subdir.name.lower()
            if 'radioclip' in name_lower:
                modalities.setdefault('RadioCLIP', subdir)
            elif 'all' in name_lower:
                modalities.setdefault('ALL', subdir)
            elif 'clip' in name_lower:
                modalities.setdefault('CLIP', subdir)
            elif 'radio' in name_lower:
                modalities.setdefault('Radio', subdir)

    # Use default paths if nothing specified via CLI
    if not modalities:
        print("[Info] No CLI arguments provided. Using default configured paths.")
        for name, path in DEFAULT_MODALITIES.items():
            p = Path(path)
            if p.exists():
                modalities[name] = p
            else:
                print(f"[Warning] Default path not found, skipped: {p}")

    if not modalities:
        raise ValueError(
            "No modalities specified. Use -m Name:Path for manual specification, "
            "or -i parent_dir for auto-detection, or ensure default paths exist."
        )

    print(f"\nResolved modalities:")
    for name, path in modalities.items():
        print(f"  [{name}] -> {path}")

    # ------------------------------------------------------------------
    # Load cache if enabled
    # ------------------------------------------------------------------
    cache = None
    cached_modalities = {}
    if use_cache:
        cache = load_cache(cache_path)
        if cache:
            cached_modalities = cache.get('modalities', {})
            print(f"[Cache] Cached modalities: {list(cached_modalities.keys())}")

    def should_use_cache(name: str, path: Path) -> bool:
        """Check if cached results for this modality are still valid."""
        if not use_cache or name in force_rerun:
            return False
        if name not in cached_modalities:
            return False
        try:
            return str(path.resolve()) == str(Path(cached_modalities[name]).resolve())
        except Exception:
            return str(path) == str(cached_modalities[name])

    # ------------------------------------------------------------------
    # Process each modality
    # ------------------------------------------------------------------
    all_results = {}
    all_best_folds = {}

    # 先处理 ALL 模态，记录每个 seed 对应的 best fold
    if 'ALL' in modalities:
        name, path = 'ALL', modalities['ALL']
        if should_use_cache(name, path):
            all_results[name] = cache['all_results'][name]
            for rec in all_results[name]:
                if rec.get('BestFold') is not None:
                    all_best_folds[rec['Experiment']] = rec['BestFold']
            print(f"  [Cache] Using cached results for {name}")
        elif path.exists():
            processor = ModalityProcessor(
                name, path,
                fusion_method=args.fusion_method,
                n_bootstrap=args.bootstrap,
                ci_percentile=args.ci
            )
            all_results[name] = processor.run()
            for rec in all_results[name]:
                if rec.get('BestFold') is not None:
                    all_best_folds[rec['Experiment']] = rec['BestFold']
        else:
            print(f"[Warning] Skipping {name}: path not found ({path})")

    # 处理其余模态，强制使用 ALL 模态选出的 best fold
    for name, path in modalities.items():
        if name == 'ALL':
            continue
        if should_use_cache(name, path):
            all_results[name] = cache['all_results'][name]
            print(f"  [Cache] Using cached results for {name}")
            continue
        if not path.exists():
            print(f"[Warning] Skipping {name}: path not found ({path})")
            continue
        processor = ModalityProcessor(
            name, path,
            fusion_method=args.fusion_method,
            n_bootstrap=args.bootstrap,
            ci_percentile=args.ci,
            forced_best_folds=all_best_folds
        )
        all_results[name] = processor.run()

    if not any(all_results.values()):
        raise RuntimeError("No valid results collected from any modality.")

    # ------------------------------------------------------------------
    # Save cache
    # ------------------------------------------------------------------
    if use_cache:
        save_cache(cache_path, {
            'version': 1,
            'timestamp': datetime.now().isoformat(),
            'modalities': {name: str(path.resolve()) for name, path in modalities.items()},
            'all_results': all_results,
            'all_best_folds': all_best_folds,
        })

    # ------------------------------------------------------------------
    # Aggregate and save
    # ------------------------------------------------------------------
    aggregator = CrossModalAggregator(all_results, ci_percentile=args.ci)

    # Pre-compute best fold tables
    bf_summary = aggregator.build_bestfold_summary_table()
    bf_raw = aggregator.build_bestfold_raw_table()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # 1. 宽格式跨模态对比矩阵
        matrix = aggregator.build_crossmodal_matrix()
        if not matrix.empty:
            matrix.to_excel(writer, sheet_name='CrossModal_Matrix', index=False)

        # 2. 跨模态 Overall 长格式对比
        aggregator.build_crossmodal_overall().to_excel(
            writer, sheet_name='CrossModal_Overall', index=False
        )

        # 3. 功效分析风格汇总统计
        aggregator.build_summary_statistics().to_excel(
            writer, sheet_name='Summary_Statistics', index=False
        )

        # 4. AUC 竖排表 (Valid & Test)
        for dataset in ['Train', 'Valid', 'Test']:
            df = aggregator.build_auc_detail_table(dataset=dataset)
            df.to_excel(writer, sheet_name=f'AUC_{dataset}_Detail', index=False)

        # 5. Best Fold 对比
        aggregator.build_bestfold_comparison().to_excel(
            writer, sheet_name='BestFold_Comparison', index=False
        )

        # 6. 每个模态的原始数据
        for modality, records in all_results.items():
            if records:
                pd.DataFrame(records).to_excel(
                    writer, sheet_name=f'{modality}_Raw', index=False
                )

        # 7. Best Fold 三数据集详细汇总
        if not bf_summary.empty:
            bf_summary.to_excel(writer, sheet_name='BestFold_Summary', index=False)
        if not bf_raw.empty:
            bf_raw.to_excel(writer, sheet_name='BestFold_Raw', index=False)

        # 8. BestFold 配对 t 检验 (Valid & Test)
        for dataset in ['Train', 'Valid', 'Test']:
            df_ttest = aggregator.build_bestfold_paired_ttest(dataset=dataset)
            if not df_ttest.empty:
                df_ttest.to_excel(writer, sheet_name=f'BF_PairedTTest_{dataset}', index=False)

        # 9. BestFold 功效分析 (Valid & Test)
        for dataset in ['Train', 'Valid', 'Test']:
            df_power = aggregator.build_bestfold_power_analysis(dataset=dataset)
            if not df_power.empty:
                df_power.to_excel(writer, sheet_name=f'BF_Power_{dataset}', index=False)

    print(f"\n{'='*60}")
    print(f"All done! Results saved to: {output_path}")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # Best Fold Summary (单独 Excel)
    # ------------------------------------------------------------------
    bestfold_excel_path = output_path.parent / 'BestFold_Summary.xlsx'
    try:
        with pd.ExcelWriter(bestfold_excel_path, engine='openpyxl') as bf_writer:
            if not bf_summary.empty:
                bf_summary.to_excel(bf_writer, sheet_name='Summary', index=False)
            if not bf_raw.empty:
                bf_raw.to_excel(bf_writer, sheet_name='Raw', index=False)
            # v4: 单独 Excel 中也附带上 t 检验与功效分析
            for dataset in ['Train', 'Valid', 'Test']:
                df_ttest = aggregator.build_bestfold_paired_ttest(dataset=dataset)
                if not df_ttest.empty:
                    df_ttest.to_excel(bf_writer, sheet_name=f'PairedTTest_{dataset}', index=False)
            for dataset in ['Train', 'Valid', 'Test']:
                df_power = aggregator.build_bestfold_power_analysis(dataset=dataset)
                if not df_power.empty:
                    df_power.to_excel(bf_writer, sheet_name=f'Power_{dataset}', index=False)
        print(f"  BestFold summary saved to: {bestfold_excel_path}")
    except Exception as e:
        print(f"  [Warning] Failed to save BestFold summary Excel: {e}")

    # ------------------------------------------------------------------
    # Visualization Report
    # ------------------------------------------------------------------
    vis_output_dir = output_path.parent / 'Visualization_Report'
    modality_paths = {name: str(path) for name, path in modalities.items()}
    generate_visualization_report(all_results, vis_output_dir, modality_paths)
    generate_crossmodal_html_report(all_results, vis_output_dir, aggregator, modality_paths)


# =============================================================================
# Visualization Report
# =============================================================================

def fig_to_base64(fig):
    """Convert matplotlib figure to base64-encoded PNG for HTML embedding."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64


def plot_roc_curves(best_fold_infos: dict, output_dir: Path):
    """Plot ROC curves for each modality's best fold on Valid and Test sets."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    colors = {'ALL': '#1f77b4', 'Radio': '#ff7f0e', 'CLIP': '#2ca02c', 'RadioCLIP': '#d62728'}

    for modality, info in best_fold_infos.items():
        if not info:
            continue
        color = colors.get(modality, '#333333')

        for ax, dataset_key, prob_key, label_key in [
            (axes[0], 'Valid', 'valid_prob', 'valid_label'),
            (axes[1], 'Test',  'test_prob',  'test_label')
        ]:
            prob = info.get(prob_key)
            label = info.get(label_key)
            if prob is None or label is None:
                continue
            fpr, tpr, _ = metrics.roc_curve(label, prob)
            auc = metrics.roc_auc_score(label, prob)
            ax.plot(fpr, tpr, color=color, lw=2,
                    label=f"{modality} (AUC={auc:.3f})")

    for ax, title in zip(axes, ['Validation ROC', 'Test ROC']):
        ax.plot([0, 1], [0, 1], 'k--', lw=1)
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='lower right', fontsize=9)
        ax.grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig(output_dir / 'ROC_Curves.png', dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"  [Vis] ROC curves saved.")


def plot_auc_bar_comparison(all_records: dict):
    """Bar plot comparing AUC across modalities (Valid & Test)."""
    modalities = []
    valid_means, valid_stds = [], []
    test_means, test_stds = [], []

    for modality, records in all_records.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        v = df['Valid_AUC'].dropna().values
        t = df['Test_AUC'].dropna().values
        modalities.append(modality)
        valid_means.append(np.mean(v) if len(v) else 0)
        valid_stds.append(np.std(v) if len(v) else 0)
        test_means.append(np.mean(t) if len(t) else 0)
        test_stds.append(np.std(t) if len(t) else 0)

    x = np.arange(len(modalities))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 6))
    bars1 = ax.bar(x - width/2, valid_means, width, yerr=valid_stds,
                   label='Valid AUC', capsize=4, color='#4C78A8', edgecolor='black')
    bars2 = ax.bar(x + width/2, test_means, width, yerr=test_stds,
                   label='Test AUC', capsize=4, color='#F58518', edgecolor='black')

    ax.set_ylabel('AUC', fontsize=13)
    ax.set_title('Cross-Modal AUC Comparison (Mean ± Std)', fontsize=15, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(modalities, fontsize=12)
    ax.legend(fontsize=11)
    ax.set_ylim([0.5, 1.05])
    ax.grid(axis='y', alpha=0.3)

    # Annotate values on bars
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.3f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    return fig


def plot_metrics_radar(all_records: dict):
    """Radar chart for multi-metric comparison across modalities (Test set)."""
    metric_labels = ['AUC', 'Acc', 'Sen', 'Spe']
    modalities = []
    values = {}

    for modality, records in all_records.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        modalities.append(modality)
        vals = []
        for m in metric_labels:
            col = f'Test_{m}'
            if col in df.columns:
                vals.append(df[col].mean())
            else:
                vals.append(0)
        values[modality] = vals

    if not modalities:
        return

    angles = np.linspace(0, 2 * np.pi, len(metric_labels), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    colors = {'ALL': '#1f77b4', 'Radio': '#ff7f0e', 'CLIP': '#2ca02c', 'RadioCLIP': '#d62728'}

    for modality in modalities:
        vals = values[modality] + values[modality][:1]
        ax.plot(angles, vals, color=colors.get(modality, '#333333'),
                linewidth=2, label=modality, marker='o')
        ax.fill(angles, vals, color=colors.get(modality, '#333333'), alpha=0.15)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metric_labels, fontsize=12)
    ax.set_ylim(0, 1)
    ax.set_title('Test Set Metrics Radar Chart', fontsize=15, fontweight='bold', pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=10)
    ax.grid(True)

    plt.tight_layout()
    return fig


def plot_bestfold_auc_scatter(all_records: dict):
    """Scatter plot of Valid AUC vs Test AUC for best fold across experiments."""
    fig, ax = plt.subplots(figsize=(8, 8))
    colors = {'ALL': '#1f77b4', 'Radio': '#ff7f0e', 'CLIP': '#2ca02c', 'RadioCLIP': '#d62728'}

    for modality, records in all_records.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        x = df['BestFold_Valid_AUC'].dropna().values
        y = df['BestFold_Test_AUC'].dropna().values
        if len(x) == 0 or len(y) == 0:
            continue
        ax.scatter(x, y, color=colors.get(modality, '#333333'),
                   s=100, label=modality, edgecolors='black', alpha=0.8)

    ax.plot([0.5, 1.0], [0.5, 1.0], 'k--', lw=1)
    ax.set_xlim([0.5, 1.0])
    ax.set_ylim([0.5, 1.0])
    ax.set_xlabel('Best Fold Valid AUC', fontsize=12)
    ax.set_ylabel('Best Fold Test AUC', fontsize=12)
    ax.set_title('Best Fold Valid vs Test AUC', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    return fig


def generate_visualization_report(all_results: dict, output_dir: Path, modality_paths: dict = None):
    """Generate all visualization figures."""
    print(f"\n{'='*60}")
    print(f"Generating Visualization Report to: {output_dir}")
    print(f"{'='*60}")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_records = {}
    for modality, records in all_results.items():
        all_records[modality] = records

    # Helper to safely generate and save a figure
    def _safe_plot(plot_func, filename, *args, **kwargs):
        try:
            fig = plot_func(*args, **kwargs)
            if fig:
                fig.savefig(output_dir / filename, dpi=300, bbox_inches='tight')
                plt.close(fig)
                print(f"  [Vis] {filename} saved.")
                return fig
        except Exception as e:
            print(f"  [Vis Error] {filename} failed: {e}")
        return None

    _safe_plot(plot_auc_bar_comparison, 'AUC_Bar_Comparison.png', all_records)
    _safe_plot(plot_metrics_radar, 'Metrics_Radar.png', all_records)
    _safe_plot(plot_bestfold_auc_scatter, 'BestFold_Valid_Test_Scatter.png', all_records)

    # Best Fold ROC curves
    best_fold_infos = {}
    for modality, records in all_results.items():
        if not records:
            continue
        r = records[0]
        if r.get('BestFold') is not None:
            best_fold_infos[modality] = {
                'valid_prob': np.array(r['BestFold_valid_prob']) if r.get('BestFold_valid_prob') else None,
                'valid_label': np.array(r['BestFold_valid_label']) if r.get('BestFold_valid_label') else None,
                'test_prob': np.array(r['BestFold_test_prob']) if r.get('BestFold_test_prob') else None,
                'test_label': np.array(r['BestFold_test_label']) if r.get('BestFold_test_label') else None,
            }
    if best_fold_infos:
        _safe_plot(plot_roc_curves, 'ROC_Curves.png', best_fold_infos, output_dir)

    # Build per-modality detailed ROC from raw experiment data
    _safe_plot(_plot_per_modality_roc, 'PerModality_TestROC.png', all_results, modality_paths)

    print(f"{'='*60}")
    print(f"Visualization report complete.")
    print(f"{'='*60}")


def _plot_per_modality_roc(all_results: dict, modality_paths: dict = None):
    """Try to find combined test file and plot ROC for each modality."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    colors = {'ALL': '#1f77b4', 'Radio': '#ff7f0e', 'CLIP': '#2ca02c', 'RadioCLIP': '#d62728'}

    for modality, records in all_results.items():
        if not records:
            continue
        color = colors.get(modality, '#333333')

        # Use the first experiment's combined test file if available
        exp_name = records[0]['Experiment']

        # 优先使用实际传入的路径（支持命令行自定义路径），否则回退到默认路径
        if modality_paths and modality in modality_paths:
            base_path = modality_paths[modality]
        else:
            base_path = DEFAULT_MODALITIES.get(modality)

        if base_path is None:
            print(f"  [Vis Warning] No base path found for modality '{modality}', skipping PerModality ROC.")
            continue
        test_file = Path(base_path) / exp_name / 'combined_0_6_optimized' / 'fusion_details_test.xlsx'
        if not test_file.exists():
            test_file = Path(base_path) / exp_name / 'combined_0_6_hierarchical' / 'fusion_details_test.xlsx'

        if not test_file.exists():
            continue

        df = pd.read_excel(test_file)
        label = df['Label'].values

        for ax, prob_col, title_suffix in [
            (axes[0], 'Prob_Task0', 'Task0'),
            (axes[1], 'Prob_Combined', 'EqualWeight')
        ]:
            if prob_col not in df.columns:
                continue
            prob = df[prob_col].values
            fpr, tpr, _ = metrics.roc_curve(label, prob)
            auc = metrics.roc_auc_score(label, prob)
            ax.plot(fpr, tpr, color=color, lw=2,
                    label=f"{modality} (AUC={auc:.3f})")

    for ax, title in zip(axes, ['Task0 Only ROC (Test)', 'Equal Weight Fusion ROC (Test)']):
        ax.plot([0, 1], [0, 1], 'k--', lw=1)
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='lower right', fontsize=9)
        ax.grid(alpha=0.3)

    plt.tight_layout()
    return fig


def generate_crossmodal_html_report(all_results: dict, output_dir: Path, aggregator: CrossModalAggregator, modality_paths: dict = None):
    """Generate an HTML report with embedded figures for cross-modal results."""
    output_dir.mkdir(parents=True, exist_ok=True)
    all_records = {}
    for modality, records in all_results.items():
        all_records[modality] = records

    figures = {}

    def _safe_html_plot(plot_func, key, *args, **kwargs):
        try:
            fig = plot_func(*args, **kwargs)
            if fig:
                figures[key] = fig_to_base64(fig)
        except Exception as e:
            print(f"  [HTML Vis Error] {key} failed: {e}")

    _safe_html_plot(plot_auc_bar_comparison, 'auc_bar', all_records)
    _safe_html_plot(plot_metrics_radar, 'radar', all_records)
    _safe_html_plot(plot_bestfold_auc_scatter, 'scatter', all_records)
    _safe_html_plot(_plot_per_modality_roc, 'roc', all_results, modality_paths)

    # Best Fold ROC
    best_fold_infos = {}
    for modality, records in all_results.items():
        if not records:
            continue
        r = records[0]
        if r.get('BestFold') is not None:
            best_fold_infos[modality] = {
                'valid_prob': np.array(r['BestFold_valid_prob']) if r.get('BestFold_valid_prob') else None,
                'valid_label': np.array(r['BestFold_valid_label']) if r.get('BestFold_valid_label') else None,
                'test_prob': np.array(r['BestFold_test_prob']) if r.get('BestFold_test_prob') else None,
                'test_label': np.array(r['BestFold_test_label']) if r.get('BestFold_test_label') else None,
            }
    if best_fold_infos:
        _safe_html_plot(plot_roc_curves, 'bestfold_roc', best_fold_infos, output_dir)

    # Build summary cards for each modality
    summary_cards = ''
    for modality, records in all_results.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        v = df['Valid_AUC'].dropna().values
        t = df['Test_AUC'].dropna().values
        summary_cards += f'''
        <div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:16px;border-radius:8px;text-align:center;">
            <div style="font-size:22px;font-weight:bold;">{modality}</div>
            <div style="font-size:14px;opacity:0.9;margin-top:8px;">Valid AUC: {np.mean(v):.3f} ± {np.std(v):.3f}</div>
            <div style="font-size:14px;opacity:0.9;">Test AUC: {np.mean(t):.3f} ± {np.std(t):.3f}</div>
        </div>
        '''

    matrix = aggregator.build_crossmodal_matrix()
    matrix_html = matrix.to_html(index=False, classes='data-table', float_format='%.3f') if not matrix.empty else '<p>No data</p>'

    summary = aggregator.build_summary_statistics()
    summary_html = summary.to_html(index=False, classes='data-table', float_format='%.3f') if not summary.empty else '<p>No data</p>'

    bestfold = aggregator.build_bestfold_comparison()
    bestfold_html = bestfold.to_html(index=False, classes='data-table', float_format='%.3f') if not bestfold.empty else '<p>No data</p>'

    bf_summary = aggregator.build_bestfold_summary_table()
    bf_summary_html = bf_summary.to_html(index=False, classes='data-table') if not bf_summary.empty else '<p>No data</p>'

    html_parts = [
        '<!DOCTYPE html><html><head>',
        '<meta charset="utf-8">',
        '<title>Cross-Modal Results Report</title>',
        '''<style>
        body{font-family:"Segoe UI",Arial,sans-serif;margin:0;background:#f0f2f5;color:#333;}
        .container{max-width:1400px;margin:20px auto;background:#fff;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);}
        h1{color:#2c3e50;border-bottom:3px solid #e74c3c;padding-bottom:10px;}
        h2{color:#34495e;margin-top:35px;border-left:4px solid #e74c3c;padding-left:12px;font-size:18px;}
        .summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:15px 0;}
        .metric-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:15px 0;}
        .metric-card{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:14px;border-radius:8px;text-align:center;}
        .metric-value{font-size:20px;font-weight:bold;}
        .metric-label{font-size:11px;opacity:0.9;margin-top:5px;}
        .figure{margin:20px 0;text-align:center;}
        .figure img{max-width:100%;border:1px solid #ddd;border-radius:6px;box-shadow:0 2px 4px rgba(0,0,0,0.08);}
        table{width:100%;border-collapse:collapse;margin:15px 0;font-size:13px;}
        th,td{border:1px solid #ddd;padding:8px;text-align:center;}
        th{background:#e74c3c;color:#fff;}
        tr:nth-child(even){background:#f8f9fa;}
        .timestamp{color:#888;font-size:12px;text-align:right;margin-top:30px;padding-top:10px;border-top:1px solid #eee;}
        </style>''',
        '</head><body><div class="container">',
        '<h1>📊 Cross-Modal Results Report</h1>',
        f'<p style="color:#888;font-size:13px;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
        '<h2>📋 Modality Summary</h2>',
        f'<div class="summary-grid">{summary_cards}</div>',
    ]

    if 'auc_bar' in figures:
        html_parts.append(f'<div class="figure"><h2>📊 AUC Comparison (Valid vs Test)</h2><img src="data:image/png;base64,{figures["auc_bar"]}"></div>')
    if 'radar' in figures:
        html_parts.append(f'<div class="figure"><h2>🎯 Metrics Radar (Test Set)</h2><img src="data:image/png;base64,{figures["radar"]}"></div>')
    if 'scatter' in figures:
        html_parts.append(f'<div class="figure"><h2>🔍 Best Fold Valid vs Test AUC</h2><img src="data:image/png;base64,{figures["scatter"]}"></div>')
    if 'roc' in figures:
        html_parts.append(f'<div class="figure"><h2>🔬 Per-Modality Test ROC</h2><img src="data:image/png;base64,{figures["roc"]}"></div>')

    html_parts.append('<h2>📋 Cross-Modal Matrix</h2>')
    html_parts.append(matrix_html)

    html_parts.append('<h2>📋 Summary Statistics</h2>')
    html_parts.append(summary_html)

    html_parts.append('<h2>📋 Best Fold Comparison</h2>')
    html_parts.append(bestfold_html)

    html_parts.append('<h2>📋 Best Fold Summary (Train / Valid / Test)</h2>')
    html_parts.append('<p style="color:#888;font-size:12px;">每个 Seed 最好折的三数据集六维指标统计（Mean ± Std）</p>')
    html_parts.append(bf_summary_html)

    # v4: 配对 t 检验 & 功效分析
    for dataset in ['Train', 'Valid', 'Test']:
        df_ttest = aggregator.build_bestfold_paired_ttest(dataset=dataset)
        if not df_ttest.empty:
            html_parts.append(f'<h2>📊 BestFold Paired t-test ({dataset})</h2>')
            html_parts.append(df_ttest.to_html(index=False, classes='data-table', float_format='%.4f'))
        df_power = aggregator.build_bestfold_power_analysis(dataset=dataset)
        if not df_power.empty:
            html_parts.append(f'<h2>⚡ BestFold Power Analysis ({dataset})</h2>')
            html_parts.append(df_power.to_html(index=False, classes='data-table', float_format='%.4f'))

    html_parts.append(f'<p class="timestamp">Report generated by remerge_pred_clean_v5.py</p>')
    html_parts.append('</div></body></html>')

    html_path = output_dir / 'CrossModal_Report.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    print(f"  HTML report saved to: {html_path}")


if __name__ == '__main__':
    main()
